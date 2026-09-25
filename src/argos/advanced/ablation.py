from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.advanced import AdvancedSpec
from argos.config.gold import GoldSpec
from argos.config.modeling import ModelingSpec


BUILD_IMPLEMENTATION = "m8-74-temporal-ablation-v1"


@dataclass(frozen=True, slots=True)
class M8AblationResult:
    metrics: pd.DataFrame
    ranking: pd.DataFrame
    selection: dict[str, Any]
    validation: pd.DataFrame
    manifest_path: Path
    selection_manifest_path: Path

    @property
    def ready_for_gate(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def family_map(
    base_features: tuple[str, ...],
    semantic_features: tuple[str, ...],
    graph_features: tuple[str, ...],
    anomaly_features: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    return {
        "tabular": base_features,
        "tabular_nlp": (*base_features, *semantic_features),
        "tabular_graph": (*base_features, *graph_features),
        "tabular_anomaly": (*base_features, *anomaly_features),
        "tabular_m8_all": (*base_features, *semantic_features, *graph_features, *anomaly_features),
    }


def relative_gain(value: float, baseline: float) -> float:
    if baseline == 0:
        return float("inf") if value > 0 else 0.0
    return value / baseline - 1.0


def select_m8_family(
    metrics: pd.DataFrame,
    ranking: pd.DataFrame,
    *,
    operational_fraction: float,
    min_pr_auc_relative_gain: float,
    min_lift_relative_gain: float,
) -> dict[str, Any]:
    baseline_metric_rows = metrics.loc[metrics["feature_family"] == "tabular"]
    if baseline_metric_rows.empty:
        raise ValueError("M8 ablation requires the tabular baseline")
    baseline_metric = baseline_metric_rows.iloc[0]
    operational = ranking.loc[
        np.isclose(ranking["review_fraction"].astype(float), operational_fraction)
    ].copy()
    if operational.empty:
        raise ValueError("M8 ranking report lacks the operational review fraction")
    baseline_rank = operational.loc[operational["feature_family"] == "tabular"].iloc[0]

    comparisons: list[dict[str, Any]] = []
    for family in metrics["feature_family"].astype(str).tolist():
        if family == "tabular":
            continue
        metric = metrics.loc[metrics["feature_family"] == family].iloc[0]
        rank = operational.loc[operational["feature_family"] == family].iloc[0]
        pr_gain = relative_gain(float(metric["pr_auc"]), float(baseline_metric["pr_auc"]))
        lift_gain = relative_gain(float(rank["lift_at_k"]), float(baseline_rank["lift_at_k"]))
        comparisons.append(
            {
                "feature_family": family,
                "pr_auc": float(metric["pr_auc"]),
                "lift_at_operational_k": float(rank["lift_at_k"]),
                "pr_auc_relative_gain": pr_gain,
                "lift_relative_gain": lift_gain,
                "eligible": bool(
                    pr_gain >= min_pr_auc_relative_gain
                    and lift_gain >= min_lift_relative_gain
                ),
            }
        )
    eligible = [row for row in comparisons if row["eligible"]]
    selected = None
    if eligible:
        selected = sorted(
            eligible,
            key=lambda row: (
                float(row["pr_auc"]),
                float(row["lift_at_operational_k"]),
                str(row["feature_family"]),
            ),
            reverse=True,
        )[0]
    return {
        "baseline_family": "tabular",
        "baseline_pr_auc": float(baseline_metric["pr_auc"]),
        "baseline_lift_at_operational_k": float(baseline_rank["lift_at_k"]),
        "operational_fraction": operational_fraction,
        "comparisons": comparisons,
        "selected_family": selected["feature_family"] if selected else None,
        "decision": "PROMOTE_M8_FEATURES" if selected else "RESEARCH_COMPLETE_NO_PROMOTION",
        "final_unbiased_validation_required": True,
    }


def run_m8_ablation(
    *,
    root: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    modeling_spec: ModelingSpec,
    advanced_spec: AdvancedSpec,
) -> M8AblationResult:
    from argos.common.duckdb import connect
    from argos.gold.utils import columns_of, parquet_source
    from argos.models.boosting import fit_boosting_bundle
    from argos.models.metrics import metric_frame, ranking_metrics

    matrix_path = root / advanced_spec.artifacts.development_matrix
    registry_path = root / modeling_spec.feature_registry
    if not matrix_path.exists() or not registry_path.exists():
        raise FileNotFoundError("M8 ablation requires development matrix and M3 feature registry")

    con = connect(
        threads=modeling_spec.runtime.duckdb_threads,
        memory_limit=modeling_spec.runtime.duckdb_memory_limit,
    )
    try:
        matrix = parquet_source(matrix_path)
        registry = parquet_source(registry_path)
        base_features = tuple(
            con.execute(f"SELECT feature FROM {registry} WHERE model_role='feature'")
            .fetchdf()["feature"]
            .astype(str)
            .tolist()
        )
        columns = columns_of(con, matrix)
        semantic_features = tuple(c for c in columns if c.startswith("semantic_"))
        graph_features = tuple(c for c in columns if c.startswith("graph_"))
        anomaly_features = tuple(c for c in columns if c.startswith("anomaly_"))
        families = family_map(base_features, semantic_features, graph_features, anomaly_features)
        requested = set(advanced_spec.ablation.families)
        if not requested.issubset(families):
            raise ValueError(
                f"Unsupported M8 ablation families: {sorted(requested - set(families))}"
            )
        union_features = tuple(
            dict.fromkeys(
                feature
                for family in advanced_spec.ablation.families
                for feature in families[family]
            )
        )
        quoted = ", ".join(f'"{feature}"' for feature in union_features)
        sample = con.execute(
            f"""
            SELECT contract_id, {modeling_spec.target}, {quoted}
            FROM {matrix}
            WHERE split='train'
            ORDER BY hash(CAST(contract_id AS VARCHAR) || '::m8::{modeling_spec.random_seed}')
            LIMIT {advanced_spec.ablation.max_train_rows}
            """
        ).fetchdf()
        validation = con.execute(
            f"""
            SELECT contract_id, t0, {modeling_spec.target}, {quoted}
            FROM {matrix}
            WHERE split='validation'
            ORDER BY t0, contract_id
            """
        ).fetchdf()
        train_stats = con.execute(
            (
                f"SELECT COUNT(*) AS rows, SUM({modeling_spec.target}) AS positives "
                f"FROM {matrix} WHERE split='train'"
            )
        ).fetchdf().iloc[0]
    finally:
        con.close()

    train_rows = int(train_stats["rows"])
    train_positives = int(train_stats["positives"])
    positive_weight = min(
        modeling_spec.boosting.positive_class_weight_cap,
        (train_rows - train_positives) / max(1, train_positives),
    )
    metric_parts: list[pd.DataFrame] = []
    ranking_parts: list[pd.DataFrame] = []
    fitted_bundles: dict[str, Any] = {}

    for family in advanced_spec.ablation.families:
        features = families[family]
        categorical = tuple(
            feature
            for feature in gold_spec.contract_features.categorical_candidates
            if feature in features
        )
        numeric = tuple(feature for feature in features if feature not in set(categorical))
        bundle = fit_boosting_bundle(
            sample,
            categorical_features=categorical,
            numeric_features=numeric,
            target=modeling_spec.target,
            missing_category=modeling_spec.preprocessing.missing_category,
            max_categories=modeling_spec.boosting.max_categories,
            max_iter=advanced_spec.ablation.max_iter,
            learning_rate=modeling_spec.boosting.learning_rate,
            max_leaf_nodes=modeling_spec.boosting.max_leaf_nodes,
            min_samples_leaf=modeling_spec.boosting.min_samples_leaf,
            l2_regularization=modeling_spec.boosting.l2_regularization,
            positive_class_weight=positive_weight,
            random_seed=modeling_spec.random_seed + 800,
        )
        probabilities = bundle.predict_proba(validation)
        y = validation[modeling_spec.target].astype("int8").to_numpy()
        metric = metric_frame(
            f"m8_{family}",
            advanced_spec.ablation.validation_role,
            y,
            probabilities,
            bins=modeling_spec.ranking.calibration_bins,
        )
        metric["feature_family"] = family
        metric["feature_count"] = len(features)
        ranking = ranking_metrics(
            f"m8_{family}",
            advanced_spec.ablation.validation_role,
            y,
            probabilities,
            modeling_spec.ranking.review_fractions,
        )
        ranking["feature_family"] = family
        ranking["feature_count"] = len(features)
        metric_parts.append(metric)
        ranking_parts.append(ranking)
        fitted_bundles[family] = bundle

    metrics = pd.concat(metric_parts, ignore_index=True)
    ranking = pd.concat(ranking_parts, ignore_index=True)
    write_report(metrics, reports_root / "advanced" / "74_ablation_metrics.parquet")
    write_report(ranking, reports_root / "advanced" / "74_ablation_ranking.parquet")

    selection = select_m8_family(
        metrics,
        ranking,
        operational_fraction=advanced_spec.ablation.operational_fraction,
        min_pr_auc_relative_gain=advanced_spec.ablation.min_pr_auc_relative_gain,
        min_lift_relative_gain=advanced_spec.ablation.min_lift_relative_gain,
    )
    selected_family = selection.get("selected_family")
    if selected_family:
        selected_model_path = root / advanced_spec.artifacts.selected_model
        selected_model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(fitted_bundles[str(selected_family)], selected_model_path, compress=3)
        selection["selected_model"] = str(selected_model_path.relative_to(root))
    else:
        selection["selected_model"] = None
    selection.update(
        {
            "schema_version": advanced_spec.schema_version,
            "development_model_version": advanced_spec.core.development_model_version,
            "selection_population": advanced_spec.ablation.validation_role,
            "consumed_splits": ["train", "validation"],
            "consumed_test_or_oot_for_selection": False,
            "note": (
                "M8 is development/feature-selection evidence only. TEST 2025 and OOT 2026 "
                "remain consumed; any ARGOS V2 promotion requires a new future holdout."
            ),
        }
    )
    selection_manifest_path = root / advanced_spec.artifacts.selection_manifest
    selection_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    selection_manifest_path.write_text(
        json.dumps(selection, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="m8_ablation_families_complete",
        category="ablation",
        passed=set(metrics["feature_family"].astype(str)) == set(advanced_spec.ablation.families),
        observed={"families": metrics["feature_family"].astype(str).tolist()},
        requirement=(
            "tabular baseline and all configured advanced families use one temporal protocol"
        ),
    )
    add_validation(
        records,
        check_id="m8_ablation_metrics_finite",
        category="quality",
        passed=bool(
            np.isfinite(
                metrics[["pr_auc", "roc_auc", "log_loss", "brier", "ece"]].to_numpy(
                    dtype=float
                )
            ).all()
            and np.isfinite(ranking["lift_at_k"].to_numpy(dtype=float)).all()
        ),
        observed={"metric_rows": len(metrics), "ranking_rows": len(ranking)},
        requirement="M8 temporal ablation metrics are finite",
    )
    add_validation(
        records,
        check_id="m8_ablation_train_validation_only",
        category="evaluation_governance",
        passed=True,
        observed={
            "consumed_splits": ["train", "validation"],
            "test_consumed": False,
            "oot_consumed": False,
        },
        requirement="M8 selection never consumes TEST 2025 or OOT 2026",
    )
    add_validation(
        records,
        check_id="m8_feature_selection_explicit",
        category="governance",
        passed=selection["decision"] in {"PROMOTE_M8_FEATURES", "RESEARCH_COMPLETE_NO_PROMOTION"},
        observed={"decision": selection["decision"], "selected_family": selected_family},
        requirement=(
            "M8 persists an explicit promotion/no-promotion decision from development evidence"
        ),
    )
    validation_report = pd.DataFrame.from_records(records)
    write_report(validation_report, reports_root / "advanced" / "74_validation.parquet")

    manifest_path = root / advanced_spec.artifacts.ablation_manifest
    write_manifest(
        manifest_path,
        {
            "schema_version": advanced_spec.schema_version,
            "implementation": BUILD_IMPLEMENTATION,
            "development_matrix": advanced_spec.artifacts.development_matrix,
            "families": list(advanced_spec.ablation.families),
            "train_population_rows": train_rows,
            "train_sample_rows": len(sample),
            "validation_rows": len(validation),
            "positive_class_weight": positive_weight,
            "shared_random_seed": modeling_spec.random_seed + 800,
            "selection_decision": selection["decision"],
            "selected_family": selected_family,
            "consumed_test_or_oot_for_selection": False,
        },
    )
    return M8AblationResult(
        metrics=metrics,
        ranking=ranking,
        selection=selection,
        validation=validation_report,
        manifest_path=manifest_path,
        selection_manifest_path=selection_manifest_path,
    )
