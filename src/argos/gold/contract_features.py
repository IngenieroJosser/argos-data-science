from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import quote_identifier, sql_string
from argos.config.gold import GoldSpec
from argos.gold.utils import add_validation, columns_of, copy_query, parquet_source, require_columns, write_manifest


BUILD_IMPLEMENTATION = "m3-23-contract-features-v1"


@dataclass(frozen=True, slots=True)
class ContractFeaturesResult:
    artifact: Path
    selection: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_contract_features(
    *,
    silver_dir: Path,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> ContractFeaturesResult:
    contracts_path = silver_dir / "contracts.parquet"
    population_path = gold_dir / "target_population.parquet"
    if not contracts_path.exists() or not population_path.exists():
        raise FileNotFoundError("Notebook 23 requires contracts.parquet and target_population.parquet")

    artifact = gold_dir / "features" / "contract_features.parquet"
    contracts = parquet_source(contracts_path)
    population = parquet_source(population_path)
    con = connect(
        temp_directory=temp_directory,
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        contract_columns = set(columns_of(con, contracts))
        require_columns(con, population, ["contract_id", "t0"], label="target_population.parquet")
        missing_identity = sorted(set(gold_spec.contract_features.required_identity_columns) - contract_columns)
        if missing_identity:
            raise KeyError(f"contracts.parquet is missing required Gold identity columns: {missing_identity}")

        forbidden = set(gold_spec.contract_features.forbidden_columns)
        rows: list[dict[str, Any]] = []
        selected: list[tuple[str, str]] = []
        for feature in gold_spec.contract_features.categorical_candidates:
            available = feature in contract_columns
            allowed = feature not in forbidden
            status = "selected" if available and allowed else ("forbidden" if not allowed else "missing")
            rows.append({"feature": feature, "kind": "categorical", "available": available, "allowed": allowed, "status": status})
            if status == "selected":
                selected.append((feature, "categorical"))
        for feature in gold_spec.contract_features.numeric_candidates:
            available = feature in contract_columns
            allowed = feature not in forbidden
            status = "selected" if available and allowed else ("forbidden" if not allowed else "missing")
            rows.append({"feature": feature, "kind": "numeric", "available": available, "allowed": allowed, "status": status})
            if status == "selected":
                selected.append((feature, "numeric"))
        selection = pd.DataFrame(rows)

        projection = [
            "p.contract_id",
            "p.t0",
            "c.supplier_code",
            f"c.{quote_identifier(gold_spec.historical_features.entity_key)} AS entity_id",
            "EXTRACT(YEAR FROM p.t0)::INTEGER AS t0_year",
            "EXTRACT(MONTH FROM p.t0)::INTEGER AS t0_month",
            "EXTRACT(DOW FROM p.t0)::INTEGER AS t0_day_of_week",
            "EXTRACT(QUARTER FROM p.t0)::INTEGER AS t0_quarter",
        ]
        for feature, kind in selected:
            q = quote_identifier(feature)
            if kind == "categorical":
                projection.append(f"c.{q} AS {q}")
            else:
                projection.append(f"TRY_CAST(c.{q} AS DOUBLE) AS {q}")
        projection.append(f"{sql_string(gold_spec.schema_version)} AS _gold_schema_version")

        query = f"""
            SELECT {', '.join(projection)}
            FROM {population} p
            JOIN {contracts} c USING (contract_id)
            WHERE p.t0 IS NOT NULL
        """
        print("[23] materializing conservative at-signing contract feature whitelist...")
        copy_query(
            con,
            query,
            artifact,
            compression=gold_spec.compression,
            row_group_size=gold_spec.row_group_size,
            overwrite=overwrite,
        )
        features = parquet_source(artifact)
        stats = con.execute(
            f"""
            SELECT COUNT(*) AS row_count, COUNT(DISTINCT contract_id) AS distinct_contracts,
                   COUNT(*) FILTER (WHERE t0 IS NULL) AS null_t0
            FROM {features}
            """
        ).fetchdf().iloc[0]
        expected = int(con.execute(f"SELECT COUNT(*) FROM {population} WHERE t0 IS NOT NULL").fetchone()[0])
        artifact_columns = set(columns_of(con, features))
        forbidden_present = sorted(forbidden & artifact_columns)
        selected_count = len(selected) + 4  # explicit t0 calendar features

        records: list[dict[str, Any]] = []
        add_validation(
            records,
            check_id="contract_feature_population_preserved",
            category="grain",
            passed=int(stats["row_count"]) == expected and int(stats["distinct_contracts"]) == expected,
            observed={"rows": int(stats["row_count"]), "distinct_contracts": int(stats["distinct_contracts"]), "expected": expected},
            requirement="one contract-feature row per contract with valid t0",
        )
        add_validation(
            records,
            check_id="contract_feature_t0_complete",
            category="temporal",
            passed=int(stats["null_t0"]) == 0,
            observed={"null_t0": int(stats["null_t0"])},
            requirement="contract feature rows always carry their prediction timestamp t0",
        )
        add_validation(
            records,
            check_id="contract_forbidden_columns_absent",
            category="leakage",
            passed=not forbidden_present,
            observed={"forbidden_present": forbidden_present},
            requirement="M1/M2 mutable snapshot fields are absent from Gold contract features",
        )
        add_validation(
            records,
            check_id="contract_feature_whitelist_sufficient",
            category="features",
            passed=selected_count >= gold_spec.contract_features.min_selected_features,
            observed={"selected_configured": len(selected), "derived_calendar": 4, "total_model_candidates": selected_count},
            requirement=f"at least {gold_spec.contract_features.min_selected_features} conservative features are materialized",
        )
        validation = pd.DataFrame.from_records(records)
        write_report(selection, reports_root / "gold" / "23_feature_selection.parquet")
        write_report(validation, reports_root / "gold" / "23_contract_features_validation.parquet")
    finally:
        con.close()

    manifest_path = write_manifest(
        manifest_dir / "gold_contract_features.json",
        {
            "milestone": "M3",
            "component": "23_contract_features",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": gold_spec.schema_version,
            "artifact": str(artifact),
            "selected_features": [feature for feature, _ in selected] + ["t0_year", "t0_month", "t0_day_of_week", "t0_quarter"],
            "identity_columns_not_model_features": ["contract_id", "supplier_code", "entity_id", "t0"],
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return ContractFeaturesResult(artifact, selection, validation, manifest_path)
