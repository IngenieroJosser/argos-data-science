from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.modeling import ModelingSpec
from argos.config.robustness import RobustnessSpec
from argos.robustness.common import load_frozen_v1, sha256_file


BUILD_IMPLEMENTATION = "m5-46-preproduction-evidence-v1"


COMPONENT_VALIDATIONS = (
    "40_validation.parquet",
    "41_validation.parquet",
    "42_validation.parquet",
    "43_validation.parquet",
    "44_validation.parquet",
    "45_validation.parquet",
)


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    monitoring_thresholds: pd.DataFrame
    evidence_summary: pd.DataFrame
    validation: pd.DataFrame
    robustness_card_path: Path
    monitoring_spec_path: Path
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _component_ok(path: Path) -> tuple[bool, dict[str, Any]]:
    if not path.exists():
        return False, {"status": "missing", "path": str(path)}
    frame = pd.read_parquet(path)
    blocking = frame.loc[frame["blocking"]]
    return bool(not blocking.empty and blocking["passed"].all()), {
        "blocking": int(len(blocking)),
        "passed": int(blocking["passed"].sum()) if not blocking.empty else 0,
        "failed": blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist(),
    }


def _sklearn_lock_version(lock_path: Path) -> str | None:
    if not lock_path.exists():
        return None
    text = lock_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'name = "scikit-learn"\s+version = "([^"]+)"', text)
    return None if match is None else match.group(1)


def _monitoring_thresholds(spec: RobustnessSpec) -> pd.DataFrame:
    rows = [
        {"signal": "numeric_feature_psi", "warning": spec.drift.psi_warning, "high": spec.drift.psi_high, "action": "investigate feature distribution / upstream data changes"},
        {"signal": "categorical_feature_tvd", "warning": spec.drift.categorical_tvd_warning, "high": spec.drift.categorical_tvd_high, "action": "investigate category mix and unseen values"},
        {"signal": "score_psi", "warning": spec.monitoring.score_psi_warning, "high": spec.monitoring.score_psi_high, "action": "review score shift and calibration"},
        {"signal": "prevalence_relative_change", "warning": spec.monitoring.prevalence_relative_change_warning, "high": np.nan, "action": "review prior probability shift; recalibration may be required"},
        {"signal": "tail_calibration_abs_gap", "warning": spec.monitoring.tail_calibration_abs_gap_warning, "high": np.nan, "action": "review top-score calibration before operational use"},
        {"signal": "lift_at_operational_k", "warning": spec.monitoring.top_k_lift_floor, "high": np.nan, "action": "pause promotion if lift is at/below random review"},
        {"signal": "feature_missingness_absolute_delta", "warning": spec.monitoring.feature_missingness_absolute_delta_warning, "high": np.nan, "action": "investigate ingestion/schema/source changes"},
    ]
    return pd.DataFrame.from_records(rows)


def _render_monitoring_spec(spec: RobustnessSpec, thresholds: pd.DataFrame) -> str:
    lines = [
        "# ARGOS V1 — Monitoring Specification",
        "",
        f"> **M5 schema:** `{spec.schema_version}`  ",
        "> **Purpose:** operational monitoring contract; it does not authorize autonomous decisions.",
        "",
        "## Deterministic ranking",
        "",
        "```text",
        "calibrated score DESC",
        "raw model score DESC",
        "contract_id ASC",
        "```",
        "",
        "This order must be used whenever top-K metrics or review queues are materialized.",
        "",
        "## Frozen monitoring thresholds",
        "",
        "| signal | warning | high | action |",
        "|---|---:|---:|---|",
    ]
    for row in thresholds.to_dict(orient="records"):
        high = "—" if pd.isna(row["high"]) else f"{float(row['high']):.4f}"
        lines.append(f"| {row['signal']} | {float(row['warning']):.4f} | {high} | {row['action']} |")
    lines.extend(
        [
            "",
            "## Required recurring checks before production",
            "",
            "- schema and lineage integrity;",
            "- target prevalence and label latency;",
            "- feature missingness, category novelty and drift;",
            "- raw/calibrated score distribution drift;",
            "- global and top-tail calibration;",
            "- PR-AUC and Lift@K once labels mature;",
            "- deterministic ranking tie-break;",
            "- runtime/model hash compatibility.",
            "",
            "## Governance",
            "",
            "TEST 2025 remains a consumed historical benchmark. The 2026 fresh OOT cohort becomes consumed after notebook 45. Any future model selection requires development windows that exclude both final-evaluation cohorts, and any new generalization claim requires a later untouched holdout.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_robustness_card(
    *,
    backtest: pd.DataFrame,
    uncertainty: pd.DataFrame,
    drift: pd.DataFrame,
    feature_deltas: pd.DataFrame,
    fresh: pd.DataFrame,
    fresh_ranking: pd.DataFrame,
    importance: pd.DataFrame,
    spec: RobustnessSpec,
) -> str:
    fresh_row = fresh.iloc[0]
    op = fresh_ranking.loc[np.isclose(fresh_ranking["review_fraction"], spec.fresh_oot.operational_fraction)].iloc[0]
    top_features = importance.head(10)[["feature", "family", "importance_mean_pr_auc_drop"]]
    high_drift = drift.loc[drift["status"] == "high"]
    competition = feature_deltas.loc[feature_deltas["family"] == "competition_increment"]
    lines = [
        "# ARGOS V1 — Robustness Card",
        "",
        f"> **M5 schema:** `{spec.schema_version}`  ",
        "> **Model under review:** frozen ARGOS V1 (`hist_gradient_boosting + isotonic`)  ",
        "> **Status:** robustness evidence generated; production authorization is evaluated separately.",
        "",
        "## Fresh out-of-time 2026 evidence",
        "",
        f"- rows: **{int(fresh_row['rows']):,}**",
        f"- positives: **{int(fresh_row['positives']):,}**",
        f"- prevalence: **{float(fresh_row['prevalence']):.4%}**",
        f"- PR-AUC: **{float(fresh_row['pr_auc']):.6f}**",
        f"- ROC-AUC: **{float(fresh_row['roc_auc']):.6f}**",
        f"- Brier: **{float(fresh_row['brier']):.6f}**",
        f"- ECE: **{float(fresh_row['ece']):.6f}**",
        f"- Lift@1%: **{float(op['lift_at_k']):.3f}x**",
        f"- Precision@1%: **{float(op['precision_at_k']):.4%}**",
        f"- Recall@1%: **{float(op['recall_at_k']):.4%}**",
        "",
        "The 2026 cohort is partial-year because eligibility requires a complete 180-day outcome horizon. It is fresher than TEST 2025 but not seasonally representative of a full calendar year.",
        "",
        "## Rolling-origin development backtesting",
        "",
        "| period | PR-AUC | ROC-AUC | prevalence |",
        "|---|---:|---:|---:|",
    ]
    for row in backtest.sort_values("split").to_dict(orient="records"):
        lines.append(f"| {row['split']} | {float(row['pr_auc']):.6f} | {float(row['roc_auc']):.6f} | {float(row['prevalence']):.4%} |")
    lines.extend(["", "## Uncertainty", ""])
    for row in uncertainty.to_dict(orient="records"):
        lines.append(f"- `{row['metric']}`: {float(row['point_estimate_sample']):.6f} [{float(row['lower']):.6f}, {float(row['upper']):.6f}] ({float(row['confidence_level']):.1%})")
    lines.extend(["", "## Top global permutation signals", "", "| feature | family | mean PR-AUC drop |", "|---|---|---:|"])
    for row in top_features.to_dict(orient="records"):
        lines.append(f"| {row['feature']} | {row['family']} | {float(row['importance_mean_pr_auc_drop']):.6f} |")
    lines.extend(
        [
            "",
            "## Drift and feature-family evidence",
            "",
            f"- high-drift feature-period pairs: **{len(high_drift)}**; these are monitoring findings, not automatic model failures.",
            f"- competition incremental comparisons available: **{len(competition)}** rolling folds.",
            "- feature-family revalidation is diagnostic and does not mutate the M4 frozen model.",
            "",
            "## Interpretation limits",
            "",
            "Permutation importance and local perturbation describe predictive sensitivity, not causality. The model remains a prioritization aid for human analytical review and is not a corruption/fraud classifier or legal decision system.",
            "",
        ]
    )
    return "\n".join(lines)


def build_preproduction_evidence(
    *,
    root: Path,
    reports_root: Path,
    manifest_dir: Path,
    docs_root: Path,
    modeling_spec: ModelingSpec,
    robustness_spec: RobustnessSpec,
) -> ReadinessResult:
    component_status: dict[str, Any] = {}
    all_components_ok = True
    for name in COMPONENT_VALIDATIONS:
        ok, observed = _component_ok(reports_root / "robustness" / name)
        component_status[name] = observed
        all_components_ok &= ok

    required_reports = {
        "backtest": reports_root / "robustness" / "40_backtest_metrics.parquet",
        "importance": reports_root / "robustness" / "41_global_permutation_importance.parquet",
        "uncertainty": reports_root / "robustness" / "42_uncertainty_intervals.parquet",
        "drift": reports_root / "robustness" / "43_feature_drift.parquet",
        "feature_deltas": reports_root / "robustness" / "44_feature_family_deltas.parquet",
        "fresh": reports_root / "robustness" / "45_fresh_oot_metrics.parquet",
        "fresh_ranking": reports_root / "robustness" / "45_fresh_oot_ranking.parquet",
    }
    missing = [name for name, path in required_reports.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing M5 evidence reports before notebook 46: {missing}")

    backtest = pd.read_parquet(required_reports["backtest"])
    importance = pd.read_parquet(required_reports["importance"])
    uncertainty = pd.read_parquet(required_reports["uncertainty"])
    drift = pd.read_parquet(required_reports["drift"])
    feature_deltas = pd.read_parquet(required_reports["feature_deltas"])
    fresh = pd.read_parquet(required_reports["fresh"])
    fresh_ranking = pd.read_parquet(required_reports["fresh_ranking"])
    _, _, selection = load_frozen_v1(root)

    thresholds = _monitoring_thresholds(robustness_spec)
    write_report(thresholds, reports_root / "robustness" / "46_monitoring_thresholds.parquet")
    evidence_summary = pd.DataFrame.from_records(
        [
            {"evidence": "rolling_origin_folds", "value": int(backtest["split"].nunique()), "interpretation": "development-only temporal robustness"},
            {"evidence": "global_features_explained", "value": int(importance["feature"].nunique()), "interpretation": "permutation importance coverage"},
            {"evidence": "uncertainty_metrics", "value": int(uncertainty["metric"].nunique()), "interpretation": "block-bootstrap intervals"},
            {"evidence": "high_drift_pairs", "value": int((drift["status"] == "high").sum()), "interpretation": "monitor, do not silently ignore"},
            {"evidence": "competition_increment_folds", "value": int((feature_deltas["family"] == "competition_increment").sum()), "interpretation": "fair incremental feature-family comparisons"},
            {"evidence": "fresh_oot_rows", "value": int(fresh.iloc[0]["rows"]), "interpretation": "post-2025 fully observed partial-year holdout"},
        ]
    )
    write_report(evidence_summary, reports_root / "robustness" / "46_evidence_summary.parquet")

    monitoring_spec_path = docs_root / "monitoring" / "ARGOS_V1_MONITORING_SPEC.md"
    monitoring_spec_path.parent.mkdir(parents=True, exist_ok=True)
    monitoring_spec_path.write_text(_render_monitoring_spec(robustness_spec, thresholds), encoding="utf-8")
    robustness_card_path = docs_root / "models" / "ARGOS_V1_ROBUSTNESS_CARD.md"
    robustness_card_path.write_text(
        _render_robustness_card(
            backtest=backtest,
            uncertainty=uncertainty,
            drift=drift,
            feature_deltas=feature_deltas,
            fresh=fresh,
            fresh_ranking=fresh_ranking,
            importance=importance,
            spec=robustness_spec,
        ),
        encoding="utf-8",
    )

    fresh_manifest_path = manifest_dir / "m5_fresh_oot_2026.json"
    fresh_manifest = json.loads(fresh_manifest_path.read_text(encoding="utf-8")) if fresh_manifest_path.exists() else {}
    sklearn_version = _sklearn_lock_version(root / "uv.lock")
    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="m5_component_evidence_complete",
        category="evidence",
        passed=all_components_ok,
        observed=component_status,
        requirement="notebooks 40–45 have all blocking evidence checks passed before readiness synthesis",
    )
    add_validation(
        records,
        check_id="monitoring_contract_persisted",
        category="monitoring",
        passed=monitoring_spec_path.exists() and len(thresholds) >= 5,
        observed={"path": str(monitoring_spec_path), "thresholds": len(thresholds)},
        requirement="pre-production monitoring thresholds and deterministic ranking rules are persisted",
    )
    add_validation(
        records,
        check_id="robustness_card_persisted",
        category="documentation",
        passed=robustness_card_path.exists(),
        observed={"path": str(robustness_card_path)},
        requirement="ARGOS V1 has a dedicated robustness card distinct from the M4 model card",
    )
    add_validation(
        records,
        check_id="fresh_oot_consumed_without_reselection",
        category="governance",
        passed=bool(fresh_manifest.get("fresh_oot_consumed") and not fresh_manifest.get("model_reselected_after_fresh_oot", True)),
        observed={"fresh_oot_consumed": fresh_manifest.get("fresh_oot_consumed"), "model_reselected_after_fresh_oot": fresh_manifest.get("model_reselected_after_fresh_oot")},
        requirement="2026 holdout is recorded as consumed and does not trigger hidden model reselection",
    )
    add_validation(
        records,
        check_id="model_runtime_pinned",
        category="portability",
        passed=sklearn_version == "1.9.1",
        observed={"scikit_learn_uv_lock": sklearn_version},
        requirement="serialized M4 model runtime remains pinned to the scikit-learn version used for V1",
    )
    add_validation(
        records,
        check_id="frozen_model_lineage_intact",
        category="lineage",
        passed=fresh_manifest.get("model_sha256") == selection.get("model_sha256") and fresh_manifest.get("calibrator_sha256") == selection.get("calibrator_sha256"),
        observed={"model_sha256": selection.get("model_sha256"), "fresh_model_sha256": fresh_manifest.get("model_sha256"), "calibrator_sha256": selection.get("calibrator_sha256"), "fresh_calibrator_sha256": fresh_manifest.get("calibrator_sha256")},
        requirement="all M5 final holdout evidence refers to the exact M4 frozen V1 artifacts",
    )
    add_validation(
        records,
        check_id="production_not_auto_authorized",
        category="governance",
        passed=not robustness_spec.governance.production_authorized,
        observed={"production_authorized": robustness_spec.governance.production_authorized},
        requirement="M5 evidence completion must not silently authorize autonomous production deployment",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "robustness" / "46_validation.parquet")

    manifest_path = write_manifest(
        manifest_dir / "m5_preproduction_evidence.json",
        {
            "milestone": "M5",
            "component": "46_preproduction_readiness",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": robustness_spec.schema_version,
            "benchmark_model_schema": modeling_spec.schema_version,
            "model_sha256": selection["model_sha256"],
            "calibrator_sha256": selection["calibrator_sha256"],
            "fresh_oot_manifest_sha256": sha256_file(fresh_manifest_path),
            "production_authorized": False,
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return ReadinessResult(thresholds, evidence_summary, validation, robustness_card_path, monitoring_spec_path, manifest_path)
