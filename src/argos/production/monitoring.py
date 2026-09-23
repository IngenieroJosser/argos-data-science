from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec
from argos.config.production import ProductionSpec
from argos.models.data import load_feature_contract
from argos.production.audit import append_audit_event
from argos.production.common import read_json, resolve, sha256_file, write_json_atomic
from argos.robustness.common import deterministic_time_sample

BUILD_IMPLEMENTATION = "m6-53-executable-monitoring-v1"
EPS = 1e-6


@dataclass(frozen=True, slots=True)
class MonitoringResult:
    feature_drift: pd.DataFrame
    score_drift: pd.DataFrame
    alerts: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _severity(value: float, warning: float, high: float) -> str:
    if value >= high:
        return "high"
    if value >= warning:
        return "warning"
    return "stable"


def _numeric_psi(reference: pd.Series, current: pd.Series, bins: int) -> float:
    ref = pd.to_numeric(reference, errors="coerce")
    cur = pd.to_numeric(current, errors="coerce")
    ref_nonnull = ref.dropna().to_numpy(dtype=float)
    if len(ref_nonnull) == 0:
        r = np.array([EPS, 1.0 - EPS])
        present = float(cur.notna().mean())
        c = np.array([max(EPS, present), max(EPS, 1.0 - present)])
        c = c / c.sum()
        return float(np.sum((c - r) * np.log(c / r)))
    edges = np.unique(np.quantile(ref_nonnull, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        edges = np.array([-np.inf, float(np.nanmedian(ref_nonnull)), np.inf])
    else:
        edges[0] = -np.inf
        edges[-1] = np.inf
    ref_counts, _ = np.histogram(ref.dropna().to_numpy(dtype=float), bins=edges)
    cur_counts, _ = np.histogram(cur.dropna().to_numpy(dtype=float), bins=edges)
    ref_total = max(1, len(ref))
    cur_total = max(1, len(cur))
    r = np.append(ref_counts / ref_total, ref.isna().sum() / ref_total)
    c = np.append(cur_counts / cur_total, cur.isna().sum() / cur_total)
    r = np.clip(r, EPS, None)
    c = np.clip(c, EPS, None)
    return float(np.sum((c - r) * np.log(c / r)))


def _categorical_tvd(reference: pd.Series, current: pd.Series) -> tuple[float, float]:
    ref = reference.astype("string").fillna("__MISSING__")
    cur = current.astype("string").fillna("__MISSING__")
    rdist = ref.value_counts(normalize=True, dropna=False)
    cdist = cur.value_counts(normalize=True, dropna=False)
    cats = rdist.index.union(cdist.index)
    r = rdist.reindex(cats, fill_value=0.0).to_numpy(dtype=float)
    c = cdist.reindex(cats, fill_value=0.0).to_numpy(dtype=float)
    tvd = 0.5 * float(np.abs(r - c).sum())
    unseen = float((~cur.isin(set(ref.unique()))).mean())
    return tvd, unseen


def _stable_sample_parquet(path: Path, columns: list[str], id_column: str, max_rows: int) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=100_000, columns=list(dict.fromkeys([id_column, *columns]))):
        frame = batch.to_pandas()
        hashed = pd.util.hash_pandas_object(frame[id_column].astype(str), index=False).to_numpy(dtype=np.uint64)
        keep = (hashed % np.uint64(1_000_003)) < np.uint64(250_001)
        selected = frame.loc[keep]
        if not selected.empty:
            parts.append(selected)
        if sum(len(p) for p in parts) >= max_rows * 2:
            break
    if not parts:
        raise ValueError("Monitoring sample returned zero rows")
    sample = pd.concat(parts, ignore_index=True)
    order_hash = pd.util.hash_pandas_object(sample[id_column].astype(str) + "::m6-monitor", index=False)
    return sample.assign(_h=order_hash.to_numpy()).sort_values("_h").head(max_rows).drop(columns="_h").reset_index(drop=True)


def build_monitoring_evidence(
    *,
    input_path: Path,
    scored_path: Path,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
) -> MonitoringResult:
    contract = load_feature_contract(root, gold_spec, modeling_spec)
    reference_matrix = resolve(root, production_spec.monitoring.reference_matrix)
    if not reference_matrix.exists():
        raise FileNotFoundError(reference_matrix)

    reference = deterministic_time_sample(
        reference_matrix,
        columns=list(contract.all_features),
        id_column=modeling_spec.id_column,
        t0_column=modeling_spec.t0_column,
        start=pd.Timestamp(production_spec.monitoring.reference_start),
        end=pd.Timestamp(production_spec.monitoring.reference_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1),
        max_rows=production_spec.monitoring.reference_sample_rows,
        batch_size=production_spec.core.batch_size,
        seed=6053,
    )
    current = _stable_sample_parquet(input_path, list(contract.all_features), modeling_spec.id_column, production_spec.monitoring.reference_sample_rows)

    categorical = set(contract.categorical_features)
    rows: list[dict[str, Any]] = []
    for feature in contract.all_features:
        ref_missing = float(reference[feature].isna().mean())
        cur_missing = float(current[feature].isna().mean())
        missing_delta = abs(cur_missing - ref_missing)
        if feature in categorical:
            value, unseen = _categorical_tvd(reference[feature], current[feature])
            status = _severity(value, production_spec.monitoring.categorical_feature_tvd_warning, production_spec.monitoring.categorical_feature_tvd_high)
            metric = "tvd"
        else:
            value = _numeric_psi(reference[feature], current[feature], production_spec.monitoring.numeric_bins)
            unseen = np.nan
            status = _severity(value, production_spec.monitoring.numeric_feature_psi_warning, production_spec.monitoring.numeric_feature_psi_high)
            metric = "psi"
        if missing_delta >= production_spec.monitoring.feature_missingness_absolute_delta_warning and status == "stable":
            status = "warning"
        rows.append({"feature": feature, "kind": "categorical" if feature in categorical else "numeric", "metric": metric, "drift_value": value, "unseen_category_rate": unseen, "reference_missingness": ref_missing, "current_missingness": cur_missing, "missingness_abs_delta": missing_delta, "status": status})
    feature_drift = pd.DataFrame.from_records(rows)

    reference_scores_path = root / "reports" / "modeling" / "33_selected_validation_predictions.parquet"
    if not reference_scores_path.exists():
        raise FileNotFoundError(reference_scores_path)
    reference_scores = pd.read_parquet(reference_scores_path, columns=["score"])["score"]
    current_scores = pd.read_parquet(scored_path, columns=["score"])["score"]
    score_psi = _numeric_psi(reference_scores, current_scores, production_spec.monitoring.numeric_bins)
    score_status = _severity(score_psi, production_spec.monitoring.score_psi_warning, production_spec.monitoring.score_psi_high)
    score_drift = pd.DataFrame.from_records([{
        "reference": "validation_2024_h2_frozen",
        "current_batch": scored_path.stem,
        "reference_rows": len(reference_scores),
        "current_rows": len(current_scores),
        "reference_mean": float(reference_scores.mean()),
        "current_mean": float(current_scores.mean()),
        "score_psi": score_psi,
        "status": score_status,
    }])

    alerts_rows: list[dict[str, Any]] = []
    for row in feature_drift.itertuples(index=False):
        if row.status != "stable":
            alerts_rows.append({"signal": f"feature:{row.feature}", "severity": row.status, "metric": row.metric, "value": float(row.drift_value), "action": "investigate upstream data and feature distribution before promotion"})
    if score_status != "stable":
        alerts_rows.append({"signal": "score_distribution", "severity": score_status, "metric": "psi", "value": score_psi, "action": "review score shift and calibration; block promotion on high severity"})
    alerts = pd.DataFrame.from_records(alerts_rows, columns=["signal", "severity", "metric", "value", "action"])
    high_alerts = int((alerts["severity"] == "high").sum()) if not alerts.empty else 0

    state_path = resolve(root, production_spec.deployment.state_path)
    state = read_json(state_path)
    if high_alerts > 0 and production_spec.monitoring.pause_on_high_alert:
        state["promotion_blocked"] = True
        state["block_reason"] = f"{high_alerts} high-severity monitoring alert(s)"
        if state.get("stage") == production_spec.deployment.shadow_stage:
            state["previous_stage"] = state["stage"]
            state["stage"] = "paused"
        write_json_atomic(state_path, state)

    write_report(feature_drift, reports_root / "production" / "53_feature_drift.parquet")
    write_report(score_drift, reports_root / "production" / "53_score_drift.parquet")
    write_report(alerts, reports_root / "production" / "53_alerts.parquet")

    records: list[dict[str, Any]] = []
    add_validation(records, check_id="monitoring_feature_coverage", category="monitoring", passed=feature_drift["feature"].nunique() == len(contract.all_features), observed={"features_monitored": int(feature_drift["feature"].nunique()), "expected": len(contract.all_features)}, requirement="every frozen model feature is monitored on each scoring batch")
    add_validation(records, check_id="monitoring_values_finite", category="monitoring", passed=bool(np.isfinite(feature_drift["drift_value"].to_numpy(dtype=float)).all() and np.isfinite(score_psi)), observed={"score_psi": score_psi}, requirement="feature and score drift metrics are finite")
    add_validation(records, check_id="alerts_are_actionable", category="operations", passed=alerts.empty or bool(alerts["action"].astype(str).str.len().gt(10).all()), observed={"alerts": len(alerts), "high_alerts": high_alerts}, requirement="every warning/high signal is persisted with an operational response")
    add_validation(records, check_id="high_alerts_block_promotion", category="governance", passed=high_alerts == 0 or bool(read_json(state_path).get("promotion_blocked")), observed={"high_alerts": high_alerts, "deployment_state": read_json(state_path)}, requirement="high-severity drift cannot be silently ignored during promotion")
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "production" / "53_validation.parquet")

    append_audit_event(root, log_path=production_spec.audit.log_path, event_type="monitoring_completed", actor="argos.system", payload={"batch_id": scored_path.stem, "alerts": len(alerts), "high_alerts": high_alerts, "score_psi": score_psi})
    manifest_path = write_manifest(manifest_dir / "m6_monitoring.json", {"milestone": "M6", "component": "53_monitoring_execution", "implementation": BUILD_IMPLEMENTATION, "schema_version": production_spec.schema_version, "scored_batch_sha256": sha256_file(scored_path), "alerts": len(alerts), "high_alerts": high_alerts, "promotion_blocked": bool(read_json(state_path).get("promotion_blocked")), "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all())})
    return MonitoringResult(feature_drift, score_drift, alerts, validation, manifest_path)
