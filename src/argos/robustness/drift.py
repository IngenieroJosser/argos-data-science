from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec
from argos.config.robustness import RobustnessSpec
from argos.robustness.common import deterministic_time_sample, load_contract, matrix_path


BUILD_IMPLEMENTATION = "m5-43-feature-score-calibration-drift-v1"
EPS = 1e-6


@dataclass(frozen=True, slots=True)
class DriftResult:
    feature_drift: pd.DataFrame
    score_drift: pd.DataFrame
    tail_calibration: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _status(value: float, warning: float, high: float) -> str:
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
        ref_dist = np.array([EPS, 1.0 - EPS], dtype=float)
        present_rate = float(cur.notna().mean())
        cur_dist = np.array([max(EPS, present_rate), max(EPS, 1.0 - present_rate)], dtype=float)
        cur_dist = cur_dist / cur_dist.sum()
        return float(np.sum((cur_dist - ref_dist) * np.log(cur_dist / ref_dist)))
    edges = np.unique(np.quantile(ref_nonnull, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        # Near-constant numeric feature: reduce to missing/present plus equality bins.
        edges = np.array([-np.inf, float(np.nanmedian(ref_nonnull)), np.inf])
    else:
        edges[0] = -np.inf
        edges[-1] = np.inf
    ref_counts, _ = np.histogram(ref.dropna().to_numpy(dtype=float), bins=edges)
    cur_counts, _ = np.histogram(cur.dropna().to_numpy(dtype=float), bins=edges)
    ref_total = max(1, len(ref))
    cur_total = max(1, len(cur))
    ref_dist = np.append(ref_counts / ref_total, ref.isna().sum() / ref_total)
    cur_dist = np.append(cur_counts / cur_total, cur.isna().sum() / cur_total)
    ref_dist = np.clip(ref_dist, EPS, None)
    cur_dist = np.clip(cur_dist, EPS, None)
    return float(np.sum((cur_dist - ref_dist) * np.log(cur_dist / ref_dist)))


def _categorical_tvd(reference: pd.Series, current: pd.Series) -> tuple[float, float]:
    ref = reference.astype("string").fillna("__MISSING__")
    cur = current.astype("string").fillna("__MISSING__")
    ref_dist = ref.value_counts(normalize=True, dropna=False)
    cur_dist = cur.value_counts(normalize=True, dropna=False)
    cats = ref_dist.index.union(cur_dist.index)
    r = ref_dist.reindex(cats, fill_value=0.0).to_numpy(dtype=float)
    c = cur_dist.reindex(cats, fill_value=0.0).to_numpy(dtype=float)
    tvd = 0.5 * float(np.abs(r - c).sum())
    unseen = float(cur[~cur.isin(set(ref.unique()))].shape[0] / max(1, len(cur)))
    return tvd, unseen


def _load_prediction_period(path: Path, *, t0_column: str, target: str, period: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame[t0_column] = pd.to_datetime(frame[t0_column], errors="raise")
    required = {target, "score", "raw_score"}
    missing = required - set(frame.columns)
    if missing:
        raise KeyError(f"{path.name} missing prediction columns: {sorted(missing)}")
    frame = frame[[c for c in ["contract_id", t0_column, target, "raw_score", "score"] if c in frame.columns]].copy()
    frame["period"] = period
    return frame


def _tail_calibration(frame: pd.DataFrame, target: str, period: str) -> pd.DataFrame:
    out = frame.copy()
    # Rank percentile avoids unstable fixed-probability bins under base-rate shift.
    out["score_percentile"] = out["score"].rank(method="first", pct=True)
    bins = [0.0, 0.90, 0.95, 0.99, 0.995, 0.999, 1.0]
    labels = ["bottom_90", "90_95", "95_99", "99_99_5", "99_5_99_9", "top_0_1"]
    out["tail_bin"] = pd.cut(out["score_percentile"], bins=bins, labels=labels, include_lowest=True)
    rows = (
        out.groupby("tail_bin", observed=True)
        .agg(
            rows=(target, "size"),
            positives=(target, "sum"),
            mean_predicted_probability=("score", "mean"),
            observed_rate=(target, "mean"),
            min_score=("score", "min"),
            max_score=("score", "max"),
        )
        .reset_index()
    )
    rows.insert(0, "period", period)
    rows["calibration_gap"] = rows["observed_rate"] - rows["mean_predicted_probability"]
    return rows


def build_drift_monitoring(
    *,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    robustness_spec: RobustnessSpec,
    reports_root: Path,
    manifest_dir: Path,
) -> DriftResult:
    matrix = matrix_path(root, modeling_spec)
    contract = load_contract(root, gold_spec, modeling_spec)
    ref_start = pd.Timestamp(robustness_spec.drift.reference_start)
    ref_end = pd.Timestamp(robustness_spec.drift.reference_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    mon_start = pd.Timestamp(robustness_spec.drift.monitor_start)
    mon_end = pd.Timestamp(robustness_spec.drift.monitor_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    reference = deterministic_time_sample(
        matrix,
        columns=list(contract.all_features),
        id_column=modeling_spec.id_column,
        t0_column=modeling_spec.t0_column,
        start=ref_start,
        end=ref_end,
        max_rows=robustness_spec.drift.sample_rows_per_period,
        batch_size=robustness_spec.core.batch_size,
        seed=robustness_spec.core.random_seed + 4300,
    )
    current_by_year: dict[int, pd.DataFrame] = {}
    for year in range(mon_start.year, mon_end.year + 1):
        start = max(mon_start, pd.Timestamp(year=year, month=1, day=1))
        end = min(mon_end, pd.Timestamp(year=year, month=12, day=31, hour=23, minute=59, second=59))
        if start > end:
            continue
        current_by_year[year] = deterministic_time_sample(
            matrix,
            columns=list(contract.all_features),
            id_column=modeling_spec.id_column,
            t0_column=modeling_spec.t0_column,
            start=start,
            end=end,
            max_rows=robustness_spec.drift.sample_rows_per_period,
            batch_size=robustness_spec.core.batch_size,
            seed=robustness_spec.core.random_seed + year,
        )

    categorical = set(contract.categorical_features)
    drift_rows: list[dict[str, Any]] = []
    for year, current in current_by_year.items():
        for feature in contract.all_features:
            if feature in categorical:
                value, unseen = _categorical_tvd(reference[feature], current[feature])
                drift_rows.append(
                    {
                        "feature": feature,
                        "family": "categorical",
                        "reference_period": "2023",
                        "monitor_period": str(year),
                        "metric": "total_variation_distance",
                        "drift_value": value,
                        "unseen_category_rate": unseen,
                        "status": _status(value, robustness_spec.drift.categorical_tvd_warning, robustness_spec.drift.categorical_tvd_high),
                    }
                )
            else:
                value = _numeric_psi(reference[feature], current[feature], robustness_spec.drift.numeric_bins)
                drift_rows.append(
                    {
                        "feature": feature,
                        "family": "numeric",
                        "reference_period": "2023",
                        "monitor_period": str(year),
                        "metric": "psi",
                        "drift_value": value,
                        "unseen_category_rate": np.nan,
                        "status": _status(value, robustness_spec.drift.psi_warning, robustness_spec.drift.psi_high),
                    }
                )
    feature_drift = pd.DataFrame.from_records(drift_rows)

    val_path = reports_root / "modeling" / "33_selected_validation_predictions.parquet"
    test_path = reports_root / "modeling" / "36_final_test_predictions.parquet"
    if not val_path.exists() or not test_path.exists():
        raise FileNotFoundError("M5 drift monitoring requires M4 validation-selection and final TEST predictions")
    val = _load_prediction_period(val_path, t0_column=modeling_spec.t0_column, target=modeling_spec.target, period="validation_2024_h2")
    test = _load_prediction_period(test_path, t0_column=modeling_spec.t0_column, target=modeling_spec.target, period="test_2025_consumed_benchmark")

    score_rows: list[dict[str, Any]] = []
    ref_score = val["score"].to_numpy(dtype=float)
    for name, frame in [("validation_2024_h2", val), ("test_2025_consumed_benchmark", test)]:
        scores = frame["score"].to_numpy(dtype=float)
        score_rows.append(
            {
                "period": name,
                "rows": len(frame),
                "prevalence": float(frame[modeling_spec.target].mean()),
                "score_mean": float(np.mean(scores)),
                "score_std": float(np.std(scores)),
                "score_p50": float(np.quantile(scores, 0.50)),
                "score_p90": float(np.quantile(scores, 0.90)),
                "score_p99": float(np.quantile(scores, 0.99)),
                "score_p999": float(np.quantile(scores, 0.999)),
                "score_psi_vs_validation_h2": 0.0 if name == "validation_2024_h2" else _numeric_psi(pd.Series(ref_score), pd.Series(scores), robustness_spec.drift.numeric_bins),
                "usage": "development_reference" if name == "validation_2024_h2" else "historical_benchmark_only_not_selection",
            }
        )
    score_drift = pd.DataFrame.from_records(score_rows)
    tail_calibration = pd.concat(
        [
            _tail_calibration(val, modeling_spec.target, "validation_2024_h2"),
            _tail_calibration(test, modeling_spec.target, "test_2025_consumed_benchmark"),
        ],
        ignore_index=True,
    )

    write_report(feature_drift, reports_root / "robustness" / "43_feature_drift.parquet")
    write_report(score_drift, reports_root / "robustness" / "43_score_drift.parquet")
    write_report(tail_calibration, reports_root / "robustness" / "43_tail_calibration.parquet")

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="drift_feature_coverage",
        category="drift",
        passed=feature_drift["feature"].nunique() == len(contract.all_features) and feature_drift["monitor_period"].nunique() >= 2,
        observed={"features": int(feature_drift["feature"].nunique()), "periods": sorted(feature_drift["monitor_period"].unique().tolist())},
        requirement="every frozen V1 feature is monitored across the configured post-reference periods",
    )
    add_validation(
        records,
        check_id="drift_values_finite",
        category="quality",
        passed=bool(np.isfinite(feature_drift["drift_value"].replace([np.inf, -np.inf], np.nan)).all()),
        observed={"nonfinite": int((~np.isfinite(feature_drift["drift_value"].to_numpy(dtype=float))).sum())},
        requirement="feature drift metrics are finite and auditable",
    )
    add_validation(
        records,
        check_id="consumed_test_is_diagnostic_only",
        category="governance",
        passed=bool((score_drift.loc[score_drift["period"].str.contains("2025"), "usage"] == "historical_benchmark_only_not_selection").all()),
        observed={"test_usage": score_drift.loc[score_drift["period"].str.contains("2025"), "usage"].tolist()},
        requirement="TEST 2025 may be monitored post hoc but is never reintroduced as a selection set",
    )
    add_validation(
        records,
        check_id="tail_calibration_persisted",
        category="calibration",
        passed=tail_calibration["period"].nunique() == 2 and len(tail_calibration) >= 8,
        observed={"periods": tail_calibration["period"].unique().tolist(), "rows": len(tail_calibration)},
        requirement="calibration is monitored explicitly in the high-score tail, not only through global ECE",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "robustness" / "43_validation.parquet")

    manifest_path = write_manifest(
        manifest_dir / "m5_drift_monitoring.json",
        {
            "milestone": "M5",
            "component": "43_drift_and_calibration_monitoring",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": robustness_spec.schema_version,
            "reference_period": [str(robustness_spec.drift.reference_start), str(robustness_spec.drift.reference_end)],
            "monitor_period": [str(robustness_spec.drift.monitor_start), str(robustness_spec.drift.monitor_end)],
            "test_2025_role": "historical_benchmark_only_not_selection",
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return DriftResult(feature_drift, score_drift, tail_calibration, validation, manifest_path)
