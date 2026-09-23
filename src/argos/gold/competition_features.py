from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import sql_string
from argos.config.gold import GoldSpec
from argos.gold.utils import add_validation, copy_query, parquet_source, require_columns, write_manifest
from argos.silver.utils import compact_identifier_expr


BUILD_IMPLEMENTATION = "m3-25-competition-features-v1"


@dataclass(frozen=True, slots=True)
class CompetitionFeaturesResult:
    artifact: Path
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def build_competition_features(
    *,
    silver_dir: Path,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> CompetitionFeaturesResult:
    contracts_path = silver_dir / "contracts.parquet"
    bidders_path = silver_dir / "bidder_participations.parquet"
    process_map_path = silver_dir / "procedure_process_map.parquet"
    entity_map_path = silver_dir / "bidder_supplier_entity_map.parquet"
    population_path = gold_dir / "target_population.parquet"
    for path in [contracts_path, bidders_path, process_map_path, entity_map_path, population_path]:
        if not path.exists():
            raise FileNotFoundError(f"Notebook 25 requires {path}")

    artifact = gold_dir / "features" / "competition_features.parquet"
    contracts = parquet_source(contracts_path)
    bidders = parquet_source(bidders_path)
    process_map = parquet_source(process_map_path)
    entity_map = parquet_source(entity_map_path)
    population = parquet_source(population_path)
    con = connect(
        temp_directory=temp_directory,
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    publication = gold_spec.competition_features.publication_time_column
    try:
        require_columns(con, contracts, ["contract_id", "process_id", "supplier_code"], label="contracts.parquet")
        require_columns(
            con,
            bidders,
            ["procedure_id", "bidder_code", "bidder_nit", publication, "_source_row_hash"],
            label="bidder_participations.parquet",
        )
        require_columns(con, process_map, ["procedure_id", "process_id", "resolution_status"], label="procedure_process_map.parquet")
        require_columns(con, entity_map, ["bidder_key", "supplier_code", "resolution_status"], label="bidder_supplier_entity_map.parquet")
        require_columns(con, population, ["contract_id", "t0"], label="target_population.parquet")

        nit_normalized = compact_identifier_expr("bidder_nit")
        timestamp_predicate = f"bp.{publication} IS NOT NULL AND bp.{publication} <= b.t0"
        if not gold_spec.competition_features.require_timestamp_for_pit:
            timestamp_predicate = f"(bp.{publication} IS NULL OR bp.{publication} <= b.t0)"

        query = f"""
            WITH base AS (
                SELECT p.contract_id, p.t0, c.process_id, c.supplier_code
                FROM {population} p
                JOIN {contracts} c USING (contract_id)
                WHERE p.t0 IS NOT NULL
            ), bidder_prepared AS (
                SELECT
                    b.procedure_id,
                    m.process_id,
                    b.{publication} AS publication_at,
                    CASE
                        WHEN b.bidder_code IS NOT NULL THEN 'code:' || b.bidder_code
                        WHEN {nit_normalized} IS NOT NULL THEN 'nit:' || {nit_normalized}
                        ELSE 'row:' || b._source_row_hash
                    END AS bidder_key
                FROM {bidders} b
                JOIN {process_map} m USING (procedure_id)
                WHERE m.resolution_status = 'resolved_unique'
            ), joined AS (
                SELECT
                    b.contract_id,
                    b.t0,
                    b.supplier_code AS awarded_supplier_code,
                    bp.bidder_key,
                    bp.publication_at,
                    er.supplier_code AS resolved_bidder_supplier_code,
                    er.resolution_status AS bidder_resolution_status
                FROM base b
                LEFT JOIN bidder_prepared bp
                  ON b.process_id = bp.process_id
                 AND {timestamp_predicate}
                LEFT JOIN {entity_map} er USING (bidder_key)
            )
            SELECT
                contract_id,
                MIN(t0) AS t0,
                COUNT(DISTINCT bidder_key)::BIGINT AS bidder_count_before_t0,
                COUNT(DISTINCT bidder_key) FILTER (WHERE resolved_bidder_supplier_code IS NOT NULL)::BIGINT AS resolved_bidder_count_before_t0,
                COUNT(DISTINCT resolved_bidder_supplier_code)::BIGINT AS unique_resolved_supplier_count_before_t0,
                COUNT(DISTINCT bidder_key) FILTER (WHERE bidder_key IS NOT NULL AND resolved_bidder_supplier_code IS NULL)::BIGINT AS unresolved_bidder_count_before_t0,
                CASE WHEN COUNT(DISTINCT bidder_key)=0 THEN NULL
                     ELSE COUNT(DISTINCT bidder_key) FILTER (WHERE resolved_bidder_supplier_code IS NOT NULL)::DOUBLE /
                          COUNT(DISTINCT bidder_key) END AS bidder_entity_resolution_rate_before_t0,
                COALESCE(BOOL_OR(resolved_bidder_supplier_code = awarded_supplier_code), FALSE) AS awarded_supplier_observed_as_bidder_before_t0,
                MAX(publication_at) AS _pit_max_bidder_publication_at,
                {sql_string(gold_spec.schema_version)} AS _gold_schema_version
            FROM joined
            GROUP BY contract_id
        """
        print("[25] materializing competition features from bidder observations available by t0...")
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
            f"SELECT COUNT(*) AS row_count, COUNT(DISTINCT contract_id) AS distinct_contracts FROM {features}"
        ).fetchdf().iloc[0]
        expected = int(con.execute(f"SELECT COUNT(*) FROM {population} WHERE t0 IS NOT NULL").fetchone()[0])
        future = int(
            con.execute(
                f"SELECT COUNT(*) FROM {features} WHERE _pit_max_bidder_publication_at IS NOT NULL AND _pit_max_bidder_publication_at > t0"
            ).fetchone()[0]
        )
        negative = int(
            con.execute(
                f"""
                SELECT COUNT(*) FROM {features}
                WHERE bidder_count_before_t0 < 0
                   OR resolved_bidder_count_before_t0 < 0
                   OR unresolved_bidder_count_before_t0 < 0
                """
            ).fetchone()[0]
        )
        records: list[dict[str, Any]] = []
        add_validation(
            records,
            check_id="competition_feature_grain",
            category="grain",
            passed=int(stats["row_count"]) == expected and int(stats["distinct_contracts"]) == expected,
            observed={"rows": int(stats["row_count"]), "distinct_contracts": int(stats["distinct_contracts"]), "expected": expected},
            requirement="one competition-feature row per contract with valid t0",
        )
        add_validation(
            records,
            check_id="competition_features_pit_safe",
            category="point_in_time",
            passed=future <= gold_spec.validation.max_feature_future_violations,
            observed={"future_publication_violations": future},
            requirement="no bidder publication used by a feature occurs after t0",
        )
        add_validation(
            records,
            check_id="competition_counts_nonnegative",
            category="features",
            passed=negative == 0,
            observed={"violations": negative},
            requirement="competition count features are non-negative",
        )
        validation = pd.DataFrame.from_records(records)
        write_report(validation, reports_root / "gold" / "25_competition_features_validation.parquet")
    finally:
        con.close()

    manifest_path = write_manifest(
        manifest_dir / "gold_competition_features.json",
        {
            "milestone": "M3",
            "component": "25_competition_relationship_features",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": gold_spec.schema_version,
            "artifact": str(artifact),
            "pit_rule": f"{publication} must be non-null and <= t0",
            "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all()),
        },
    )
    return CompetitionFeaturesResult(artifact, validation, manifest_path)
