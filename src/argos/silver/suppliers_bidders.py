from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name, normalized_groups
from argos.common.reports import write_report
from argos.common.sql import csv_source, quote_identifier, row_md5_expr, sql_string
from argos.config.registry import DatasetSpec
from argos.config.silver import SilverSpec
from argos.silver.utils import (
    add_validation,
    compact_identifier_expr,
    copy_query,
    describe_source,
    metadata_sql,
    profile_lookup,
    semantic_type,
    snapshot_date_from_path,
    typed_projection,
    write_manifest,
)


BUILD_IMPLEMENTATION = "m2-11-suppliers-bidders-v2"


@dataclass(frozen=True, slots=True)
class SuppliersBiddersBuildResult:
    artifacts: dict[str, Path]
    routing: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _m1_inventory_count(reports_root: Path, dataset: str) -> int | None:
    path = reports_root / "profiling" / "dataset_inventory.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    row = frame.loc[frame["dataset"] == dataset]
    return None if row.empty else int(row.iloc[0]["row_count"])


def _route_dataset(
    *,
    dataset: str,
    columns: list[str],
    profile_path: Path,
    required: set[str],
    excluded_columns: tuple[str, ...],
    excluded_semantic_types: tuple[str, ...],
    rename: dict[str, str],
) -> pd.DataFrame:
    groups = normalized_groups(columns)
    missing = sorted(name for name in required if name not in groups)
    ambiguous = {name: groups[name] for name in required if len(groups.get(name, ())) > 1}
    if missing or ambiguous:
        raise KeyError(
            f"{dataset}: required Silver columns unresolved; missing={missing}, "
            f"ambiguous={ambiguous}"
        )

    profile = profile_lookup(profile_path, dataset)
    excluded = set(excluded_columns)
    records: list[dict[str, Any]] = []
    canonical_names: list[str] = []
    for raw in columns:
        normalized = normalize_name(raw)
        semantic = semantic_type(profile, normalized, raw)
        canonical = rename.get(normalized, normalized)
        if normalized in required:
            route = "core"
            reason = "required identity/link field"
        elif normalized in excluded:
            route = "excluded_sensitive"
            reason = "explicit Silver privacy exclusion"
        elif semantic in excluded_semantic_types:
            route = "excluded_sensitive"
            reason = f"semantic_type={semantic}"
        else:
            route = "core"
            reason = "canonical Silver attribute"
        if route == "core":
            canonical_names.append(canonical)
        records.append(
            {
                "dataset": dataset,
                "raw_column": raw,
                "normalized_column": normalized,
                "canonical_column": canonical,
                "semantic_type": semantic,
                "route": route,
                "reason": reason,
            }
        )

    duplicates = sorted({name for name in canonical_names if canonical_names.count(name) > 1})
    if duplicates:
        raise ValueError(f"{dataset}: canonical column collision: {duplicates}")
    return pd.DataFrame.from_records(records)


def _artifact_paths(silver_dir: Path) -> dict[str, Path]:
    return {
        "suppliers": silver_dir / "suppliers.parquet",
        "bidder_participations": silver_dir / "bidder_participations.parquet",
        "procedure_process_map": silver_dir / "procedure_process_map.parquet",
        "bidder_process_links": silver_dir / "bidder_process_links.parquet",
    }


def _core_projection(
    routing: pd.DataFrame,
    dataset: str,
    *,
    date_order: str,
) -> tuple[list[str], list[str]]:
    rows = routing.loc[
        (routing["dataset"] == dataset) & (routing["route"] == "core")
    ].to_dict(orient="records")
    expressions: list[str] = []
    lineage_columns: list[str] = []
    for row in rows:
        lineage_columns.append(str(row["raw_column"]))
        expressions.extend(
            typed_projection(
                str(row["raw_column"]),
                str(row["canonical_column"]),
                str(row["semantic_type"]),
                date_order=date_order,
            )
        )
    return expressions, lineage_columns


def build_suppliers_bidders_silver(
    suppliers_path: Path,
    bidders_path: Path,
    *,
    suppliers_spec: DatasetSpec,
    bidders_spec: DatasetSpec,
    column_profile_path: Path,
    reports_root: Path,
    silver_dir: Path,
    manifest_dir: Path,
    silver_spec: SilverSpec,
    date_order: str = "mdy",
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> SuppliersBiddersBuildResult:
    """Build supplier entities and canonical bidder-process relations.

    This notebook deliberately does *not* force bidder→supplier identity. It
    preserves the identifiers required by notebook 13 and resolves only the
    already-supported bidder→process relationship without raw-join expansion.
    """
    con = connect(
        temp_directory=temp_directory,
        threads=silver_spec.runtime.duckdb_threads,
        memory_limit=silver_spec.runtime.duckdb_memory_limit,
    )
    artifacts = _artifact_paths(silver_dir)
    try:
        supplier_source = csv_source(
            suppliers_path, sample_size=sample_size, all_varchar=True
        )
        bidder_source = csv_source(
            bidders_path, sample_size=sample_size, all_varchar=True
        )
        supplier_columns = describe_source(con, supplier_source)
        bidder_columns = describe_source(con, bidder_source)

        supplier_required = {
            silver_spec.suppliers.primary_key,
            silver_spec.suppliers.nit_key,
        }
        bidder_required = {
            silver_spec.bidders.process_key,
            silver_spec.bidders.supplier_code_candidate,
            silver_spec.bidders.nit_candidate,
        }
        supplier_routing = _route_dataset(
            dataset="suppliers",
            columns=supplier_columns,
            profile_path=column_profile_path,
            required=supplier_required,
            excluded_columns=silver_spec.suppliers.excluded_columns,
            excluded_semantic_types=silver_spec.suppliers.excluded_semantic_types,
            rename=silver_spec.suppliers.rename,
        )
        bidder_routing = _route_dataset(
            dataset="bidders",
            columns=bidder_columns,
            profile_path=column_profile_path,
            required=bidder_required,
            excluded_columns=silver_spec.bidders.excluded_columns,
            excluded_semantic_types=silver_spec.bidders.excluded_semantic_types,
            rename=silver_spec.bidders.rename,
        )
        routing = pd.concat([supplier_routing, bidder_routing], ignore_index=True)
        write_report(routing, reports_root / "silver" / "11_column_routing.parquet")

        supplier_projection, supplier_lineage = _core_projection(
            routing, "suppliers", date_order=date_order
        )
        bidder_projection, bidder_lineage = _core_projection(
            routing, "bidders", date_order=date_order
        )
        supplier_snapshot = snapshot_date_from_path(suppliers_path)
        bidder_snapshot = snapshot_date_from_path(bidders_path)

        supplier_query = f"""
            SELECT
                {', '.join(supplier_projection)},
                {row_md5_expr(supplier_lineage)} AS _source_row_hash,
                {metadata_sql(source_id=suppliers_spec.source_id, snapshot_date=supplier_snapshot, schema_version=silver_spec.schema_version)}
            FROM {supplier_source}
        """
        copy_query(
            con,
            supplier_query,
            artifacts["suppliers"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        bidder_query = f"""
            SELECT
                {', '.join(bidder_projection)},
                {row_md5_expr(bidder_lineage)} AS _source_row_hash,
                {metadata_sql(source_id=bidders_spec.source_id, snapshot_date=bidder_snapshot, schema_version=silver_spec.schema_version)}
            FROM {bidder_source}
        """
        copy_query(
            con,
            bidder_query,
            artifacts["bidder_participations"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        process_versions_path = silver_dir / "process_versions.parquet"
        if not process_versions_path.exists():
            raise FileNotFoundError(
                "process_versions.parquet is required. Run notebook 10 first."
            )
        versions = f"read_parquet({sql_string(process_versions_path)})"
        map_query = f"""
            SELECT
                procedure_id,
                CASE WHEN COUNT(DISTINCT process_id) = 1 THEN MIN(process_id) END AS process_id,
                COUNT(DISTINCT process_id)::BIGINT AS candidate_process_count,
                CASE
                    WHEN COUNT(DISTINCT process_id) = 1 THEN 'resolved_unique'
                    ELSE 'ambiguous_procedure'
                END AS resolution_status,
                {sql_string(silver_spec.schema_version)} AS _silver_schema_version
            FROM {versions}
            WHERE procedure_id IS NOT NULL
            GROUP BY procedure_id
        """
        copy_query(
            con,
            map_query,
            artifacts["procedure_process_map"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        bidders = f"read_parquet({sql_string(artifacts['bidder_participations'])})"
        procedure_map = f"read_parquet({sql_string(artifacts['procedure_process_map'])})"
        normalized_nit = compact_identifier_expr("bidder_nit")
        link_query = f"""
            WITH prepared AS (
                SELECT
                    *,
                    {normalized_nit} AS bidder_nit_normalized,
                    CASE
                        WHEN bidder_code IS NOT NULL THEN 'code:' || bidder_code
                        WHEN {normalized_nit} IS NOT NULL THEN 'nit:' || {normalized_nit}
                        ELSE 'row:' || _source_row_hash
                    END AS bidder_key
                FROM {bidders}
            ), grouped AS (
                SELECT
                    procedure_id,
                    bidder_key,
                    bidder_code,
                    bidder_nit,
                    bidder_nit_normalized,
                    COUNT(*)::BIGINT AS source_row_count,
                    COUNT(DISTINCT _source_row_hash)::BIGINT AS payload_variant_count,
                    MIN(_source_snapshot_date) AS _source_snapshot_date
                FROM prepared
                GROUP BY
                    procedure_id, bidder_key, bidder_code, bidder_nit, bidder_nit_normalized
            )
            SELECT
                MD5(CONCAT_WS('|~|', COALESCE(procedure_id, '<NULL>'), bidder_key)) AS bidder_process_link_id,
                g.procedure_id,
                p.process_id,
                g.bidder_key,
                g.bidder_code,
                g.bidder_nit,
                g.bidder_nit_normalized,
                g.source_row_count,
                g.payload_variant_count,
                CASE
                    WHEN g.procedure_id IS NULL THEN 'missing_procedure_id'
                    WHEN p.procedure_id IS NULL THEN 'unmatched_procedure'
                    WHEN p.resolution_status <> 'resolved_unique' THEN 'ambiguous_procedure'
                    ELSE 'matched'
                END AS process_link_status,
                COALESCE(p.candidate_process_count, 0)::BIGINT AS candidate_process_count,
                g._source_snapshot_date,
                {sql_string(silver_spec.schema_version)} AS _silver_schema_version
            FROM grouped g
            LEFT JOIN {procedure_map} p USING (procedure_id)
        """
        copy_query(
            con,
            link_query,
            artifacts["bidder_process_links"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        validation_records: list[dict[str, Any]] = []
        suppliers = f"read_parquet({sql_string(artifacts['suppliers'])})"
        supplier_stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT supplier_code) AS distinct_codes,
                COUNT(*) FILTER (WHERE supplier_code IS NULL) AS null_codes
            FROM {suppliers}
            """
        ).fetchdf().iloc[0]
        expected_suppliers = _m1_inventory_count(reports_root, "suppliers")
        add_validation(
            validation_records,
            check_id="suppliers_population_preserved",
            category="suppliers",
            passed=(expected_suppliers is None or int(supplier_stats["row_count"]) == expected_suppliers),
            observed={"rows": int(supplier_stats["row_count"]), "m1_expected": expected_suppliers},
            requirement="Silver suppliers preserves the Bronze supplier population",
        )
        add_validation(
            validation_records,
            check_id="suppliers_primary_key",
            category="suppliers",
            passed=(
                int(supplier_stats["null_codes"]) == 0
                and int(supplier_stats["distinct_codes"]) == int(supplier_stats["row_count"])
            ),
            observed={
                "rows": int(supplier_stats["row_count"]),
                "distinct_supplier_code": int(supplier_stats["distinct_codes"]),
                "null_supplier_code": int(supplier_stats["null_codes"]),
            },
            requirement="supplier_code is non-null and unique",
        )

        bidder_rows = int(con.execute(f"SELECT COUNT(*) FROM {bidders}").fetchone()[0])
        expected_bidders = _m1_inventory_count(reports_root, "bidders")
        add_validation(
            validation_records,
            check_id="bidder_population_preserved",
            category="bidders",
            passed=(expected_bidders is None or bidder_rows == expected_bidders),
            observed={"rows": bidder_rows, "m1_expected": expected_bidders},
            requirement="bidder_participations preserves every Bronze bidder row",
        )

        links = f"read_parquet({sql_string(artifacts['bidder_process_links'])})"
        link_stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS link_row_count,
                COUNT(DISTINCT bidder_process_link_id) AS distinct_links,
                COALESCE(SUM(source_row_count), 0)::BIGINT AS represented_rows,
                COUNT(*) FILTER (WHERE process_link_status = 'matched') AS matched_links,
                COUNT(*) FILTER (WHERE process_link_status = 'ambiguous_procedure') AS ambiguous_links,
                COUNT(*) FILTER (WHERE process_link_status = 'unmatched_procedure') AS unmatched_links,
                COUNT(*) FILTER (WHERE process_link_status = 'missing_procedure_id') AS missing_key_links,
                COALESCE(SUM(source_row_count) FILTER (WHERE process_link_status = 'matched'), 0)::BIGINT AS matched_source_rows,
                COALESCE(SUM(source_row_count) FILTER (WHERE process_link_status = 'ambiguous_procedure'), 0)::BIGINT AS ambiguous_source_rows,
                COALESCE(SUM(source_row_count) FILTER (WHERE process_link_status = 'unmatched_procedure'), 0)::BIGINT AS unmatched_source_rows,
                COALESCE(SUM(source_row_count) FILTER (WHERE process_link_status = 'missing_procedure_id'), 0)::BIGINT AS missing_key_source_rows
            FROM {links}
            """
        ).fetchdf().iloc[0]
        coverage = (
            int(link_stats["matched_source_rows"]) / int(link_stats["represented_rows"])
            if int(link_stats["represented_rows"])
            else 0.0
        )
        add_validation(
            validation_records,
            check_id="bidder_process_link_grain",
            category="relationships",
            passed=(
                int(link_stats["link_row_count"]) == int(link_stats["distinct_links"])
                and int(link_stats["represented_rows"]) == bidder_rows
            ),
            observed={
                "links": int(link_stats["link_row_count"]),
                "distinct_link_ids": int(link_stats["distinct_links"]),
                "represented_source_rows": int(link_stats["represented_rows"]),
                "bidder_source_rows": bidder_rows,
            },
            requirement="canonical bidder-process links are unique and account for all source rows",
        )
        add_validation(
            validation_records,
            check_id="bidder_process_link_coverage",
            category="relationships",
            passed=coverage >= silver_spec.validation.bidders_processes_min_coverage,
            observed={
                "coverage": coverage,
                "source_row_coverage": coverage,
                "matched_source_rows": int(link_stats["matched_source_rows"]),
                "ambiguous_source_rows": int(link_stats["ambiguous_source_rows"]),
                "unmatched_source_rows": int(link_stats["unmatched_source_rows"]),
                "missing_key_source_rows": int(link_stats["missing_key_source_rows"]),
                "matched_links": int(link_stats["matched_links"]),
                "ambiguous_links": int(link_stats["ambiguous_links"]),
            },
            requirement=(
                f"canonical bidder→process coverage >= "
                f"{silver_spec.validation.bidders_processes_min_coverage:.2%}"
            ),
        )

        sensitive_active = routing.loc[
            (routing["route"] == "core")
            & (
                routing["normalized_column"].isin(
                    set(silver_spec.suppliers.excluded_columns)
                    | set(silver_spec.bidders.excluded_columns)
                )
                | routing["semantic_type"].isin(
                    set(silver_spec.suppliers.excluded_semantic_types)
                    | set(silver_spec.bidders.excluded_semantic_types)
                )
            )
        ]
        add_validation(
            validation_records,
            check_id="party_sensitive_fields_excluded",
            category="privacy",
            passed=sensitive_active.empty,
            observed=sensitive_active["canonical_column"].tolist(),
            requirement="configured sensitive party fields are outside general analytical Silver",
        )

        validation = pd.DataFrame.from_records(validation_records)
        write_report(validation, reports_root / "silver" / "11_validation.parquet")
    finally:
        con.close()

    manifest_path = write_manifest(
        manifest_dir / "silver_suppliers_bidders.json",
        {
            "milestone": "M2",
            "component": "11_silver_suppliers_bidders",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": silver_spec.schema_version,
            "sources": {
                "suppliers": str(suppliers_path),
                "bidders": str(bidders_path),
            },
            "artifacts": {name: str(path) for name, path in artifacts.items()},
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
            "notes": [
                "bidder→supplier identity is intentionally deferred to notebook 13",
                "bidder→process uses a procedure crosswalk to avoid raw process-row expansion",
                "party names/contact fields are not needed for deterministic identifier resolution",
            ],
        },
    )
    return SuppliersBiddersBuildResult(
        artifacts=artifacts,
        routing=routing,
        validation=validation,
        manifest_path=manifest_path,
    )
