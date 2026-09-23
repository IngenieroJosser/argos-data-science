from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.modeling import ModelingSpec
from argos.config.robustness import RobustnessSpec
from argos.models.metrics import expected_calibration_error
from argos.robustness.common import deterministic_rank, deterministic_ranking_metrics


BUILD_IMPLEMENTATION = "m5-42-block-bootstrap-ranking-stability-v1"


@dataclass(frozen=True, slots=True)
class UncertaintyResult:
    bootstrap_distribution: pd.DataFrame
    intervals: pd.DataFrame
    tie_sensitivity: pd.DataFrame
    deterministic_ranking: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _metric_row(frame: pd.DataFrame, target: str, op_fraction: float, bins: int) -> dict[str, float]:
    y = frame[target].astype("int8").to_numpy()
    p = frame["score"].to_numpy(dtype=np.float64)
    ranked = deterministic_rank(frame)
    k = max(1, int(math.ceil(len(ranked) * op_fraction)))
    captured = int(ranked.iloc[:k][target].astype("int8").sum())
    positives = int(y.sum())
    prevalence = float(y.mean())
    precision = captured / k
    recall = captured / positives if positives else math.nan
    lift = precision / prevalence if prevalence > 0 else math.nan
    return {
        "rows": float(len(frame)),
        "positives": float(positives),
        "prevalence": prevalence,
        "pr_auc": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "ece": float(expected_calibration_error(y, p, bins=bins)),
        "precision_at_k": float(precision),
        "recall_at_k": float(recall),
        "lift_at_k": float(lift),
    }


def build_uncertainty_and_ranking_stability(
    *,
    reports_root: Path,
    manifest_dir: Path,
    modeling_spec: ModelingSpec,
    robustness_spec: RobustnessSpec,
) -> UncertaintyResult:
    pred_path = reports_root / "modeling" / "33_selected_validation_predictions.parquet"
    if not pred_path.exists():
        raise FileNotFoundError(pred_path)
    frame = pd.read_parquet(pred_path)
    frame[modeling_spec.t0_column] = pd.to_datetime(frame[modeling_spec.t0_column], errors="raise")
    start = pd.Timestamp(robustness_spec.uncertainty.validation_start)
    end = pd.Timestamp(robustness_spec.uncertainty.validation_end) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    frame = frame.loc[
        (frame[modeling_spec.t0_column] >= start) & (frame[modeling_spec.t0_column] <= end)
    ].copy()
    if frame.empty:
        raise ValueError("Uncertainty period contains no validation predictions")
    if "raw_score" not in frame.columns:
        raise KeyError("M5 requires raw_score in M4 selected validation predictions for deterministic tie-break")

    # Ranking sensitivity is measured on the complete selection population.
    deterministic = deterministic_rank(frame)
    deterministic_ranking = deterministic_ranking_metrics(
        frame,
        target=modeling_spec.target,
        review_fractions=robustness_spec.ranking.review_fractions,
        model_name="ARGOS_V1_deterministic_tiebreak",
        split="validation_selection",
    )
    legacy = frame.sort_values("score", ascending=False, kind="mergesort").reset_index(drop=True)
    sensitivity_rows: list[dict[str, Any]] = []
    positives = int(frame[modeling_spec.target].sum())
    prevalence = float(frame[modeling_spec.target].mean())
    for fraction in robustness_spec.ranking.review_fractions:
        k = max(1, int(math.ceil(len(frame) * fraction)))
        det_top = deterministic.head(k)
        legacy_top = legacy.head(k)
        det_ids = set(det_top[modeling_spec.id_column].astype(str))
        legacy_ids = set(legacy_top[modeling_spec.id_column].astype(str))
        intersection = len(det_ids & legacy_ids)
        union = len(det_ids | legacy_ids)
        det_captured = int(det_top[modeling_spec.target].sum())
        legacy_captured = int(legacy_top[modeling_spec.target].sum())
        sensitivity_rows.append(
            {
                "review_fraction": float(fraction),
                "reviewed": k,
                "top_k_jaccard": intersection / union if union else 1.0,
                "deterministic_captured": det_captured,
                "legacy_captured": legacy_captured,
                "captured_delta": det_captured - legacy_captured,
                "deterministic_precision": det_captured / k,
                "legacy_precision": legacy_captured / k,
                "deterministic_recall": det_captured / positives if positives else math.nan,
                "legacy_recall": legacy_captured / positives if positives else math.nan,
                "deterministic_lift": (det_captured / k) / prevalence if prevalence > 0 else math.nan,
                "legacy_lift": (legacy_captured / k) / prevalence if prevalence > 0 else math.nan,
            }
        )
    tie_sensitivity = pd.DataFrame.from_records(sensitivity_rows)

    # Bounded deterministic sample for temporal block bootstrap.
    if len(frame) > robustness_spec.uncertainty.sample_rows:
        hashes = pd.util.hash_pandas_object(
            frame[modeling_spec.id_column].astype(str) + f"::{robustness_spec.core.random_seed}", index=False
        )
        frame = frame.assign(_hash=hashes.to_numpy()).sort_values("_hash").head(robustness_spec.uncertainty.sample_rows).drop(columns=["_hash"])
    frame = frame.reset_index(drop=True)
    frame["_week"] = frame[modeling_spec.t0_column].dt.to_period("W-SUN").astype(str)
    week_groups = {week: grp.drop(columns=["_week"]) for week, grp in frame.groupby("_week", sort=True)}
    weeks = np.array(sorted(week_groups), dtype=object)
    if len(weeks) < 8:
        raise ValueError(f"Too few temporal blocks for bootstrap: {len(weeks)} weeks")

    rng = np.random.default_rng(robustness_spec.core.random_seed + 4200)
    bootstrap_rows: list[dict[str, Any]] = []
    for replicate in range(robustness_spec.uncertainty.bootstrap_replicates):
        sampled_weeks = rng.choice(weeks, size=len(weeks), replace=True)
        boot = pd.concat([week_groups[str(week)] for week in sampled_weeks], ignore_index=True)
        if boot[modeling_spec.target].nunique() < 2:
            continue
        metrics = _metric_row(
            boot,
            modeling_spec.target,
            robustness_spec.uncertainty.operational_fraction,
            modeling_spec.ranking.calibration_bins,
        )
        bootstrap_rows.append({"replicate": replicate, **metrics})
    bootstrap_distribution = pd.DataFrame.from_records(bootstrap_rows)
    if len(bootstrap_distribution) < max(50, int(0.9 * robustness_spec.uncertainty.bootstrap_replicates)):
        raise ValueError("Insufficient valid bootstrap replicates")

    alpha = 1.0 - robustness_spec.uncertainty.confidence_level
    metric_names = ["pr_auc", "roc_auc", "brier", "ece", "precision_at_k", "recall_at_k", "lift_at_k"]
    interval_rows: list[dict[str, Any]] = []
    point = _metric_row(frame.drop(columns=["_week"]), modeling_spec.target, robustness_spec.uncertainty.operational_fraction, modeling_spec.ranking.calibration_bins)
    for metric in metric_names:
        values = bootstrap_distribution[metric].to_numpy(dtype=float)
        interval_rows.append(
            {
                "metric": metric,
                "point_estimate_sample": float(point[metric]),
                "lower": float(np.quantile(values, alpha / 2)),
                "upper": float(np.quantile(values, 1 - alpha / 2)),
                "confidence_level": robustness_spec.uncertainty.confidence_level,
                "bootstrap_method": "calendar-week block bootstrap",
                "replicates": len(bootstrap_distribution),
            }
        )
    intervals = pd.DataFrame.from_records(interval_rows)

    write_report(bootstrap_distribution, reports_root / "robustness" / "42_bootstrap_distribution.parquet")
    write_report(intervals, reports_root / "robustness" / "42_uncertainty_intervals.parquet")
    write_report(tie_sensitivity, reports_root / "robustness" / "42_tie_sensitivity.parquet")
    write_report(deterministic_ranking, reports_root / "robustness" / "42_deterministic_ranking.parquet")

    op_tie = tie_sensitivity.loc[np.isclose(tie_sensitivity["review_fraction"], robustness_spec.uncertainty.operational_fraction)].iloc[0]
    lift_ci = intervals.loc[intervals["metric"] == "lift_at_k"].iloc[0]
    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="uncertainty_temporal_blocks_sufficient",
        category="uncertainty",
        passed=len(weeks) >= 8 and len(bootstrap_distribution) >= 50,
        observed={"weeks": len(weeks), "valid_replicates": len(bootstrap_distribution)},
        requirement="uncertainty uses multiple temporal blocks and enough deterministic bootstrap replicates",
    )
    add_validation(
        records,
        check_id="ranking_tie_break_frozen",
        category="ranking",
        passed=robustness_spec.ranking.tie_break == ("score_desc", "raw_score_desc", "contract_id_asc"),
        observed={"tie_break": list(robustness_spec.ranking.tie_break)},
        requirement="operational ranking has an explicit deterministic tie-break independent of Parquet row order",
    )
    add_validation(
        records,
        check_id="operational_lift_ci_above_random",
        category="usefulness",
        passed=float(lift_ci["lower"]) > 1.0,
        observed={"lower": float(lift_ci["lower"]), "upper": float(lift_ci["upper"]), "fraction": robustness_spec.uncertainty.operational_fraction},
        requirement="the confidence interval for Lift@K at the operational capacity remains above random review",
    )
    add_validation(
        records,
        check_id="tie_sensitivity_quantified",
        category="ranking",
        passed=np.isfinite(float(op_tie["top_k_jaccard"])),
        observed={"operational_top_k_jaccard": float(op_tie["top_k_jaccard"]), "captured_delta": int(op_tie["captured_delta"])},
        requirement="M5 quantifies the impact of isotonic score ties on the operational top-K set",
    )
    add_validation(
        records,
        check_id="uncertainty_no_test_selection",
        category="governance",
        passed=end.year < robustness_spec.governance.consumed_test_year,
        observed={"period_end": str(end.date()), "consumed_test_year": robustness_spec.governance.consumed_test_year},
        requirement="uncertainty/tie policy is frozen from development validation data, not TEST 2025",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "robustness" / "42_validation.parquet")

    manifest_path = write_manifest(
        manifest_dir / "m5_uncertainty_ranking.json",
        {
            "milestone": "M5",
            "component": "42_uncertainty_and_ranking_stability",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": robustness_spec.schema_version,
            "bootstrap_replicates": len(bootstrap_distribution),
            "confidence_level": robustness_spec.uncertainty.confidence_level,
            "tie_break": list(robustness_spec.ranking.tie_break),
            "test_2025_used_for_selection": False,
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return UncertaintyResult(bootstrap_distribution, intervals, tie_sensitivity, deterministic_ranking, validation, manifest_path)
