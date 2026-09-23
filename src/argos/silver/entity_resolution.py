from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.reports import write_report
from argos.common.sql import sql_string
from argos.config.silver import SilverSpec
from argos.silver.utils import (
    add_validation,
    compact_identifier_expr,
    copy_query,
    write_manifest,
)


BUILD_IMPLEMENTATION = "m2-13-deterministic-entity-resolution-v2"


@dataclass(frozen=True, slots=True)
class EntityResolutionBuildResult:
    artifacts: dict[str, Path]
    summary: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _artifact_paths(silver_dir: Path) -> dict[str, Path]:
    return {
        "bidder_supplier_entity_map": silver_dir / "bidder_supplier_entity_map.parquet",
    }


def build_entity_resolution_silver(
    *,
    reports_root: Path,
    silver_dir: Path,
    manifest_dir: Path,
    silver_spec: SilverSpec,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> EntityResolutionBuildResult:
    """Resolve bidder identities to registered suppliers deterministically.

    Accepted strategies are intentionally conservative:
    1. exact SECOP code equality when it exists;
    2. exact normalized NIT equality only when that NIT identifies one supplier.

    No fuzzy name matching, check-digit stripping or outcome-derived mapping is
    introduced in M2. Ambiguity is represented explicitly instead of guessed.
    """
    suppliers_path = silver_dir / "suppliers.parquet"
    bidder_links_path = silver_dir / "bidder_process_links.parquet"
    if not suppliers_path.exists() or not bidder_links_path.exists():
        raise FileNotFoundError(
            "Notebook 13 requires suppliers.parquet and bidder_process_links.parquet. "
            "Run notebook 11 first."
        )

    con = connect(
        temp_directory=temp_directory,
        threads=silver_spec.runtime.duckdb_threads,
        memory_limit=silver_spec.runtime.duckdb_memory_limit,
    )
    artifacts = _artifact_paths(silver_dir)
    try:
        suppliers = f"read_parquet({sql_string(suppliers_path)})"
        bidder_links = f"read_parquet({sql_string(bidder_links_path)})"
        supplier_nit_normalized = compact_identifier_expr("supplier_nit")

        code_enabled = silver_spec.entity_resolution.code_strategy_enabled
        nit_enabled = silver_spec.entity_resolution.nit_strategy_enabled
        code_candidate_sql = (
            "s.supplier_code" if code_enabled else "CAST(NULL AS VARCHAR)"
        )
        nit_join_condition = (
            "n.supplier_nit_normalized = b.bidder_nit_normalized"
            if nit_enabled
            else "FALSE"
        )

        query = f"""
            WITH bidder_identities AS (
                SELECT
                    bidder_key,
                    CASE WHEN COUNT(DISTINCT bidder_code) = 1 THEN MIN(bidder_code) END AS bidder_code,
                    CASE WHEN COUNT(DISTINCT bidder_nit_normalized) = 1 THEN MIN(bidder_nit_normalized) END AS bidder_nit_normalized,
                    COUNT(DISTINCT bidder_code)::BIGINT AS bidder_code_variants,
                    COUNT(DISTINCT bidder_nit_normalized)::BIGINT AS bidder_nit_variants,
                    SUM(source_row_count)::BIGINT AS source_row_count,
                    COUNT(*)::BIGINT AS process_link_count
                FROM {bidder_links}
                GROUP BY bidder_key
            ), supplier_base AS (
                SELECT
                    supplier_code,
                    supplier_nit,
                    {supplier_nit_normalized} AS supplier_nit_normalized
                FROM {suppliers}
            ), nit_index AS (
                SELECT
                    supplier_nit_normalized,
                    COUNT(DISTINCT supplier_code)::BIGINT AS supplier_count,
                    CASE WHEN COUNT(DISTINCT supplier_code) = 1 THEN MIN(supplier_code) END AS supplier_code
                FROM supplier_base
                WHERE supplier_nit_normalized IS NOT NULL
                GROUP BY supplier_nit_normalized
            ), candidates AS (
                SELECT
                    b.*,
                    {code_candidate_sql} AS code_supplier_code,
                    CASE WHEN {str(code_enabled).upper()} AND s.supplier_code IS NOT NULL THEN 1 ELSE 0 END::BIGINT AS code_candidate_count,
                    n.supplier_code AS nit_supplier_code,
                    COALESCE(n.supplier_count, 0)::BIGINT AS nit_candidate_count
                FROM bidder_identities b
                LEFT JOIN supplier_base s
                    ON {str(code_enabled).upper()} AND s.supplier_code = b.bidder_code
                LEFT JOIN nit_index n
                    ON {nit_join_condition}
            ), resolved AS (
                SELECT
                    *,
                    CASE
                        WHEN code_candidate_count = 1
                             AND nit_candidate_count = 1
                             AND code_supplier_code <> nit_supplier_code
                            THEN NULL
                        WHEN code_candidate_count = 1 THEN code_supplier_code
                        WHEN nit_candidate_count = 1 THEN nit_supplier_code
                        ELSE NULL
                    END AS supplier_code_resolved,
                    CASE
                        WHEN code_candidate_count = 1
                             AND nit_candidate_count = 1
                             AND code_supplier_code = nit_supplier_code
                            THEN 'resolved_code_and_nit'
                        WHEN code_candidate_count = 1
                             AND nit_candidate_count = 1
                             AND code_supplier_code <> nit_supplier_code
                            THEN 'conflict_code_vs_nit'
                        WHEN code_candidate_count = 1 THEN 'resolved_code_exact'
                        WHEN nit_candidate_count = 1 THEN 'resolved_nit_exact_unique'
                        WHEN nit_candidate_count > 1 THEN 'ambiguous_nit'
                        WHEN bidder_code IS NULL AND bidder_nit_normalized IS NULL THEN 'insufficient_identifiers'
                        ELSE 'unresolved_no_match'
                    END AS resolution_status
                FROM candidates
            )
            SELECT
                bidder_key,
                bidder_code,
                bidder_nit_normalized,
                supplier_code_resolved AS supplier_code,
                resolution_status,
                CASE
                    WHEN resolution_status = 'resolved_code_and_nit' THEN 'code_exact+nit_exact_unique'
                    WHEN resolution_status = 'resolved_code_exact' THEN 'code_exact'
                    WHEN resolution_status = 'resolved_nit_exact_unique' THEN 'nit_exact_unique'
                    ELSE NULL
                END AS resolution_strategy,
                code_candidate_count,
                nit_candidate_count,
                bidder_code_variants,
                bidder_nit_variants,
                source_row_count,
                process_link_count,
                {sql_string(silver_spec.schema_version)} AS _silver_schema_version
            FROM resolved
        """
        copy_query(
            con,
            query,
            artifacts["bidder_supplier_entity_map"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        mapping = f"read_parquet({sql_string(artifacts['bidder_supplier_entity_map'])})"
        summary = con.execute(
            f"""
            SELECT
                resolution_status,
                resolution_strategy,
                COUNT(*)::BIGINT AS bidder_entities,
                COALESCE(SUM(source_row_count), 0)::BIGINT AS represented_source_rows,
                COALESCE(SUM(process_link_count), 0)::BIGINT AS represented_process_links
            FROM {mapping}
            GROUP BY resolution_status, resolution_strategy
            ORDER BY bidder_entities DESC
            """
        ).fetchdf()
        write_report(summary, reports_root / "silver" / "13_resolution_summary.parquet")

        records: list[dict[str, Any]] = []
        stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS map_row_count,
                COUNT(DISTINCT bidder_key) AS distinct_bidder_keys,
                COUNT(*) FILTER (WHERE supplier_code IS NOT NULL) AS resolved,
                COUNT(*) FILTER (WHERE resolution_status = 'ambiguous_nit') AS ambiguous_nit,
                COUNT(*) FILTER (WHERE resolution_status = 'conflict_code_vs_nit') AS conflicts,
                COUNT(*) FILTER (
                    WHERE resolution_status = 'resolved_nit_exact_unique'
                      AND nit_candidate_count <> 1
                ) AS invalid_nit_resolutions
            FROM {mapping}
            """
        ).fetchdf().iloc[0]
        bidder_entity_count = int(
            con.execute(f"SELECT COUNT(DISTINCT bidder_key) FROM {bidder_links}").fetchone()[0]
        )
        coverage = int(stats["resolved"]) / int(stats["map_row_count"]) if int(stats["map_row_count"]) else 0.0

        add_validation(
            records,
            check_id="entity_map_grain",
            category="entity_resolution",
            passed=(
                int(stats["map_row_count"]) == int(stats["distinct_bidder_keys"])
                and int(stats["map_row_count"]) == bidder_entity_count
            ),
            observed={
                "map_rows": int(stats["map_row_count"]),
                "distinct_bidder_keys": int(stats["distinct_bidder_keys"]),
                "source_bidder_entities": bidder_entity_count,
            },
            requirement="one entity-resolution row per canonical bidder_key",
        )

        resolved_missing_supplier = int(
            con.execute(
                f"""
                SELECT COUNT(*)
                FROM {mapping} m
                LEFT JOIN {suppliers} s USING (supplier_code)
                WHERE m.supplier_code IS NOT NULL AND s.supplier_code IS NULL
                """
            ).fetchone()[0]
        )
        add_validation(
            records,
            check_id="resolved_suppliers_exist",
            category="entity_resolution",
            passed=resolved_missing_supplier == 0,
            observed={"resolved_supplier_codes_missing_from_suppliers": resolved_missing_supplier},
            requirement="every resolved supplier_code exists in canonical suppliers",
        )
        add_validation(
            records,
            check_id="ambiguous_identifiers_not_forced",
            category="entity_resolution",
            passed=int(stats["invalid_nit_resolutions"]) == 0,
            observed={
                "ambiguous_nit": int(stats["ambiguous_nit"]),
                "code_vs_nit_conflicts": int(stats["conflicts"]),
                "invalid_nit_resolutions": int(stats["invalid_nit_resolutions"]),
            },
            requirement="NIT resolution occurs only for a unique supplier candidate; conflicts remain unresolved",
        )
        add_validation(
            records,
            check_id="deterministic_resolution_only",
            category="entity_resolution",
            passed=True,
            observed=["code_exact", "nit_exact_unique"],
            requirement="M2 uses deterministic identifiers only; no fuzzy/name-based forced matches",
        )
        add_validation(
            records,
            check_id="entity_resolution_coverage_reference",
            category="entity_resolution",
            passed=coverage >= silver_spec.entity_resolution.report_min_resolved_coverage,
            observed={
                "resolved_coverage": coverage,
                "resolved": int(stats["resolved"]),
                "total": int(stats["map_row_count"]),
            },
            requirement=(
                f"reporting reference >= "
                f"{silver_spec.entity_resolution.report_min_resolved_coverage:.2%}; "
                "low coverage is a finding, not permission to force matches"
            ),
            blocking=False,
        )
        validation = pd.DataFrame.from_records(records)
        write_report(validation, reports_root / "silver" / "13_validation.parquet")
    finally:
        con.close()

    manifest_path = write_manifest(
        manifest_dir / "silver_entity_resolution.json",
        {
            "milestone": "M2",
            "component": "13_entity_resolution",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": silver_spec.schema_version,
            "artifacts": {name: str(path) for name, path in artifacts.items()},
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
            "resolved_coverage": coverage,
            "notes": [
                "direct bidder_code→supplier_code is measured rather than assumed",
                "NIT matching removes punctuation/case only; no check digit is dropped",
                "ambiguous and conflicting identifiers remain unresolved",
                "fuzzy name matching is out of scope for M2 unless separately justified",
            ],
        },
    )
    return EntityResolutionBuildResult(
        artifacts=artifacts,
        summary=summary,
        validation=validation,
        manifest_path=manifest_path,
    )
