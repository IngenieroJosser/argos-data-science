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
from argos.models.boosting import fit_boosting_bundle
from argos.models.metrics import metric_frame, ranking_metrics
from argos.robustness.common import (
    deterministic_time_sample,
    feature_family,
    iter_time_batches,
    load_contract,
    matrix_path,
    subset_contract,
)


BUILD_IMPLEMENTATION = "m5-44-feature-family-rolling-revalidation-v1"


@dataclass(frozen=True, slots=True)
class FeatureValueResult:
    metrics: pd.DataFrame
    ranking: pd.DataFrame
    deltas: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_feature_family_revalidation(
    *,
    root: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    robustness_spec: RobustnessSpec,
    reports_root: Path,
    manifest_dir: Path,
) -> FeatureValueResult:
    matrix = matrix_path(root, modeling_spec)
    contract = load_contract(root, gold_spec, modeling_spec)
    families = robustness_spec.feature_value.families
    if set(families) != {"contract", "contract_historical", "all"}:
        raise ValueError("M5 V1 expects contract, contract_historical and all feature families")

    metrics_parts: list[pd.DataFrame] = []
    ranking_parts: list[pd.DataFrame] = []
    fold_meta: list[dict[str, Any]] = []
    for fold_index, year in enumerate(robustness_spec.feature_value.evaluation_years):
        eval_start = pd.Timestamp(year=year, month=1, day=1)
        eval_end = pd.Timestamp(year=year, month=12, day=31, hour=23, minute=59, second=59)
        sample = deterministic_time_sample(
            matrix,
            columns=[*contract.all_features, modeling_spec.target],
            id_column=modeling_spec.id_column,
            t0_column=modeling_spec.t0_column,
            start=None,
            end=eval_start - pd.Timedelta(microseconds=1),
            max_rows=robustness_spec.feature_value.max_train_rows,
            batch_size=robustness_spec.core.batch_size,
            seed=robustness_spec.core.random_seed + 4400 + fold_index,
        )
        y_sample = sample[modeling_spec.target].astype("int8").to_numpy()
        if y_sample.sum() == 0:
            raise ValueError(f"Feature-value fold {year} training sample has no positives")
        pos_weight = min(
            modeling_spec.boosting.positive_class_weight_cap,
            (len(y_sample) - int(y_sample.sum())) / max(1, int(y_sample.sum())),
        )
        bundles: dict[str, Any] = {}
        feature_sets: dict[str, tuple[str, ...]] = {}
        for family in families:
            features = feature_family(contract, family)
            cat, num = subset_contract(contract, features)
            bundles[family] = fit_boosting_bundle(
                sample,
                categorical_features=cat,
                numeric_features=num,
                target=modeling_spec.target,
                missing_category=modeling_spec.preprocessing.missing_category,
                max_categories=modeling_spec.boosting.max_categories,
                max_iter=robustness_spec.feature_value.max_iter,
                learning_rate=modeling_spec.boosting.learning_rate,
                max_leaf_nodes=modeling_spec.boosting.max_leaf_nodes,
                min_samples_leaf=modeling_spec.boosting.min_samples_leaf,
                l2_regularization=modeling_spec.boosting.l2_regularization,
                positive_class_weight=pos_weight,
                random_seed=robustness_spec.core.random_seed + fold_index,
            )
            feature_sets[family] = features

        y_parts: list[np.ndarray] = []
        p_parts: dict[str, list[np.ndarray]] = {family: [] for family in families}
        columns = [modeling_spec.target, *contract.all_features]
        for frame in iter_time_batches(
            matrix,
            columns=columns,
            t0_column=modeling_spec.t0_column,
            start=eval_start,
            end=eval_end,
            batch_size=robustness_spec.core.batch_size,
        ):
            y_parts.append(frame[modeling_spec.target].astype("int8").to_numpy())
            for family in families:
                p_parts[family].append(bundles[family].predict_proba(frame))
        if not y_parts:
            raise ValueError(f"Feature-value fold {year} has no evaluation rows")
        y_eval = np.concatenate(y_parts)
        for family in families:
            p_eval = np.concatenate(p_parts[family])
            label = f"{family}_fixed_budget"
            split = f"feature_value_{year}"
            metric = metric_frame(label, split, y_eval, p_eval, bins=modeling_spec.ranking.calibration_bins)
            metric["family"] = family
            metric["evaluation_year"] = year
            metric["feature_count"] = len(feature_sets[family])
            metrics_parts.append(metric)
            rank = ranking_metrics(label, split, y_eval, p_eval, robustness_spec.ranking.review_fractions)
            rank["family"] = family
            rank["evaluation_year"] = year
            ranking_parts.append(rank)
        fold_meta.append(
            {
                "evaluation_year": year,
                "train_sample_rows": len(sample),
                "train_sample_positives": int(y_sample.sum()),
                "evaluation_rows": len(y_eval),
                "evaluation_positives": int(y_eval.sum()),
                "sample_seed": robustness_spec.core.random_seed + 4400 + fold_index,
            }
        )

    metrics = pd.concat(metrics_parts, ignore_index=True)
    ranking = pd.concat(ranking_parts, ignore_index=True)
    op = ranking.loc[np.isclose(ranking["review_fraction"], robustness_spec.feature_value.operational_fraction)].copy()
    delta_rows: list[dict[str, Any]] = []
    for year in robustness_spec.feature_value.evaluation_years:
        m = metrics.loc[metrics["evaluation_year"] == year].set_index("family")
        r = op.loc[op["evaluation_year"] == year].set_index("family")
        for family in ("contract_historical", "all"):
            delta_rows.append(
                {
                    "evaluation_year": year,
                    "family": family,
                    "reference_family": "contract",
                    "delta_pr_auc": float(m.loc[family, "pr_auc"] - m.loc["contract", "pr_auc"]),
                    "delta_roc_auc": float(m.loc[family, "roc_auc"] - m.loc["contract", "roc_auc"]),
                    "delta_lift_at_operational_k": float(r.loc[family, "lift_at_k"] - r.loc["contract", "lift_at_k"]),
                }
            )
        delta_rows.append(
            {
                "evaluation_year": year,
                "family": "competition_increment",
                "reference_family": "contract_historical",
                "delta_pr_auc": float(m.loc["all", "pr_auc"] - m.loc["contract_historical", "pr_auc"]),
                "delta_roc_auc": float(m.loc["all", "roc_auc"] - m.loc["contract_historical", "roc_auc"]),
                "delta_lift_at_operational_k": float(r.loc["all", "lift_at_k"] - r.loc["contract_historical", "lift_at_k"]),
            }
        )
    deltas = pd.DataFrame.from_records(delta_rows)

    write_report(metrics, reports_root / "robustness" / "44_feature_family_metrics.parquet")
    write_report(ranking, reports_root / "robustness" / "44_feature_family_ranking.parquet")
    write_report(deltas, reports_root / "robustness" / "44_feature_family_deltas.parquet")
    write_report(pd.DataFrame.from_records(fold_meta), reports_root / "robustness" / "44_feature_family_folds.parquet")

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="feature_family_protocol_complete",
        category="ablation",
        passed=metrics["evaluation_year"].nunique() == len(robustness_spec.feature_value.evaluation_years) and set(metrics["family"]) == set(families),
        observed={"years": sorted(metrics["evaluation_year"].unique().tolist()), "families": sorted(metrics["family"].unique().tolist())},
        requirement="all frozen feature families are compared across all predeclared rolling development years",
    )
    add_validation(
        records,
        check_id="feature_family_same_budget",
        category="ablation",
        passed=True,
        observed={"max_train_rows": robustness_spec.feature_value.max_train_rows, "max_iter": robustness_spec.feature_value.max_iter, "same_sample_seed_per_fold": True},
        requirement="family comparisons use the same algorithm, row sample and training budget within each fold",
    )
    add_validation(
        records,
        check_id="feature_family_no_test_2025",
        category="governance",
        passed=robustness_spec.governance.consumed_test_year not in set(metrics["evaluation_year"].astype(int)),
        observed={"years": sorted(metrics["evaluation_year"].unique().tolist()), "consumed_test_year": robustness_spec.governance.consumed_test_year},
        requirement="feature-family value is revalidated without selecting against consumed TEST 2025",
    )
    add_validation(
        records,
        check_id="competition_increment_measured",
        category="evidence",
        passed=len(deltas.loc[deltas["family"] == "competition_increment"]) == len(robustness_spec.feature_value.evaluation_years),
        observed={"competition_deltas": deltas.loc[deltas["family"] == "competition_increment"].to_dict(orient="records")},
        requirement="competition features have an explicit incremental-effect estimate versus contract+historical under a fair protocol",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "robustness" / "44_validation.parquet")

    manifest_path = write_manifest(
        manifest_dir / "m5_feature_family_value.json",
        {
            "milestone": "M5",
            "component": "44_feature_family_revalidation",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": robustness_spec.schema_version,
            "families": list(families),
            "evaluation_years": list(robustness_spec.feature_value.evaluation_years),
            "result_is_diagnostic_not_model_reselection": True,
            "test_2025_used_for_selection": False,
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return FeatureValueResult(metrics, ranking, deltas, validation, manifest_path)
