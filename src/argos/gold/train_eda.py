from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import quote_identifier
from argos.config.gold import GoldSpec
from argos.gold.utils import add_validation, columns_of, parquet_source, require_columns, write_manifest


BUILD_IMPLEMENTATION = "m3-22-train-eda-v1"


@dataclass(frozen=True, slots=True)
class TrainEDAResult:
    validation: pd.DataFrame
    target_profile: pd.DataFrame
    feature_profile: pd.DataFrame
    category_cardinality: pd.DataFrame
    numeric_summary: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_train_eda(
    *,
    silver_dir: Path,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    temp_directory: Path | None = None,
) -> TrainEDAResult:
    contracts_path = silver_dir / "contracts.parquet"
    split_path = gold_dir / "splits" / "temporal_split.parquet"
    if not contracts_path.exists() or not split_path.exists():
        raise FileNotFoundError("Notebook 22 requires contracts.parquet and temporal_split.parquet")

    contracts = parquet_source(contracts_path)
    splits = parquet_source(split_path)
    con = connect(
        temp_directory=temp_directory,
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        require_columns(con, contracts, ["contract_id"], label="contracts.parquet")
        require_columns(
            con,
            splits,
            ["contract_id", "t0", "split", gold_spec.target.name],
            label="temporal_split.parquet",
        )
        available = set(columns_of(con, contracts))
        candidates = [
            *gold_spec.contract_features.categorical_candidates,
            *gold_spec.contract_features.numeric_candidates,
        ]
        availability_rows = [
            {
                "feature": feature,
                "configured_kind": (
                    "categorical"
                    if feature in gold_spec.contract_features.categorical_candidates
                    else "numeric"
                ),
                "available": feature in available,
            }
            for feature in candidates
        ]
        availability = pd.DataFrame(availability_rows)

        train_source = f"""
            (
                SELECT s.contract_id, s.t0, s.{gold_spec.target.name}, c.* EXCLUDE (contract_id)
                FROM {splits} s
                JOIN {contracts} c USING (contract_id)
                WHERE s.split = 'train'
            )
        """
        target_profile = con.execute(
            f"""
            SELECT
                COUNT(*) AS train_rows,
                COUNT(*) FILTER (WHERE {gold_spec.target.name}=1) AS positives,
                COUNT(*) FILTER (WHERE {gold_spec.target.name}=0) AS negatives,
                COUNT(*) FILTER (WHERE {gold_spec.target.name} IS NULL) AS null_labels,
                AVG({gold_spec.target.name}::DOUBLE) AS prevalence,
                MIN(t0) AS min_t0,
                MAX(t0) AS max_t0
            FROM {train_source}
            """
        ).fetchdf()

        categorical = [f for f in gold_spec.contract_features.categorical_candidates if f in available]
        if categorical:
            category_queries = []
            for feature in categorical:
                q = quote_identifier(feature)
                category_queries.append(
                    f"""
                    SELECT
                        '{feature}' AS feature,
                        COUNT(*) AS row_count,
                        COUNT(*) FILTER (WHERE {q} IS NULL) AS missing_rows,
                        COUNT(DISTINCT {q}) AS cardinality,
                        COUNT(DISTINCT {q}) FILTER (WHERE {q} IS NOT NULL) AS nonnull_cardinality
                    FROM {train_source}
                    """
                )
            category_cardinality = con.execute(" UNION ALL ".join(category_queries)).fetchdf()
        else:
            category_cardinality = pd.DataFrame(
                columns=["feature", "row_count", "missing_rows", "cardinality", "nonnull_cardinality"]
            )

        numeric = [f for f in gold_spec.contract_features.numeric_candidates if f in available]
        if numeric:
            numeric_queries = []
            for feature in numeric:
                q = quote_identifier(feature)
                numeric_queries.append(
                    f"""
                    SELECT
                        '{feature}' AS feature,
                        COUNT(*) AS row_count,
                        COUNT(*) FILTER (WHERE {q} IS NULL) AS missing_rows,
                        MIN(TRY_CAST({q} AS DOUBLE)) AS min_value,
                        APPROX_QUANTILE(TRY_CAST({q} AS DOUBLE), 0.50) AS median_value,
                        AVG(TRY_CAST({q} AS DOUBLE)) AS mean_value,
                        MAX(TRY_CAST({q} AS DOUBLE)) AS max_value
                    FROM {train_source}
                    """
                )
            numeric_summary = con.execute(" UNION ALL ".join(numeric_queries)).fetchdf()
        else:
            numeric_summary = pd.DataFrame(
                columns=["feature", "row_count", "missing_rows", "min_value", "median_value", "mean_value", "max_value"]
            )

        train_rows = int(target_profile.iloc[0]["train_rows"])
        profiles: list[dict[str, Any]] = []
        for row in availability_rows:
            feature = str(row["feature"])
            kind = str(row["configured_kind"])
            if not bool(row["available"]):
                profiles.append({"feature": feature, "kind": kind, "available": False, "missing_rate": None})
                continue
            if kind == "categorical":
                r = category_cardinality.loc[category_cardinality["feature"] == feature].iloc[0]
            else:
                r = numeric_summary.loc[numeric_summary["feature"] == feature].iloc[0]
            missing = int(r["missing_rows"])
            profiles.append(
                {
                    "feature": feature,
                    "kind": kind,
                    "available": True,
                    "missing_rate": missing / train_rows if train_rows else None,
                }
            )
        feature_profile = pd.DataFrame(profiles)

        records: list[dict[str, Any]] = []
        null_labels = int(target_profile.iloc[0]["null_labels"])
        add_validation(
            records,
            check_id="eda_train_only",
            category="leakage",
            passed=train_rows > 0,
            observed={
                "train_rows": train_rows,
                "min_t0": str(target_profile.iloc[0]["min_t0"]),
                "max_t0": str(target_profile.iloc[0]["max_t0"]),
            },
            requirement="EDA population is explicitly restricted to split='train'",
        )
        add_validation(
            records,
            check_id="eda_train_labels_complete",
            category="target",
            passed=null_labels == 0,
            observed={"null_labels": null_labels},
            requirement="train-only EDA contains no censored/unlabeled rows",
        )
        selected_available = int(availability["available"].sum()) if not availability.empty else 0
        add_validation(
            records,
            check_id="eda_candidate_features_visible",
            category="features",
            passed=selected_available >= gold_spec.contract_features.min_selected_features,
            observed={"available_candidates": selected_available, "configured_candidates": len(candidates)},
            requirement=f"at least {gold_spec.contract_features.min_selected_features} conservative candidate features are available",
        )
        validation = pd.DataFrame.from_records(records)

        write_report(validation, reports_root / "gold" / "22_train_eda_validation.parquet")
        write_report(target_profile, reports_root / "gold" / "22_train_target_profile.parquet")
        write_report(feature_profile, reports_root / "gold" / "22_train_feature_profile.parquet")
        write_report(category_cardinality, reports_root / "gold" / "22_train_category_cardinality.parquet")
        write_report(numeric_summary, reports_root / "gold" / "22_train_numeric_summary.parquet")
    finally:
        con.close()

    manifest_path = write_manifest(
        manifest_dir / "gold_train_eda.json",
        {
            "milestone": "M3",
            "component": "22_train_eda",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": gold_spec.schema_version,
            "population": "train only",
            "reports": [
                "22_train_target_profile.parquet",
                "22_train_feature_profile.parquet",
                "22_train_category_cardinality.parquet",
                "22_train_numeric_summary.parquet",
            ],
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
        },
    )
    return TrainEDAResult(
        validation,
        target_profile,
        feature_profile,
        category_cardinality,
        numeric_summary,
        manifest_path,
    )
