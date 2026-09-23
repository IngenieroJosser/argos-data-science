from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name, normalization_collisions
from argos.common.reports import write_report
from argos.common.sql import csv_source, quote_identifier, row_md5_expr, sql_string, timestamp_expr, trimmed_text_expr
from argos.config.registry import DatasetSpec
from argos.config.silver import SilverSpec
from argos.silver.utils import (
    add_validation,
    copy_query,
    describe_source,
    metadata_sql,
    snapshot_date_from_path,
    write_manifest,
)


BUILD_IMPLEMENTATION = "m2-12-addition-events-out-of-core-v2"


@dataclass(frozen=True, slots=True)
class EventsBuildResult:
    artifacts: dict[str, Path]
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


def _artifact_paths(silver_dir: Path) -> dict[str, Path]:
    return {
        "addition_event_versions": silver_dir / "addition_event_versions.parquet",
        "addition_events": silver_dir / "addition_events.parquet",
    }


def _normalized_schema(columns: list[str]) -> dict[str, str]:
    collisions = normalization_collisions(columns)
    if collisions:
        raise ValueError(
            "Additions Silver requires an unambiguous normalized source schema; "
            f"collisions={collisions}"
        )
    return {normalize_name(raw): raw for raw in columns}


def _validate_existing(
    con,
    artifacts: dict[str, Path],
    *,
    reports_root: Path,
    spec: SilverSpec,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    versions = f"read_parquet({sql_string(artifacts['addition_event_versions'])})"
    events = f"read_parquet({sql_string(artifacts['addition_events'])})"

    version_stats = con.execute(
        f"""
        SELECT
            COUNT(*) AS version_rows,
            COALESCE(SUM(_source_row_count), 0)::BIGINT AS represented_source_rows,
            COALESCE(SUM(_source_row_count) FILTER (WHERE event_at__parse_status = 'parsed'), 0)::BIGINT AS parsed_source_rows,
            COALESCE(SUM(_source_row_count) FILTER (WHERE event_at__parse_status = 'unparsed'), 0)::BIGINT AS unparsed_source_rows,
            COALESCE(SUM(_source_row_count) FILTER (WHERE event_at__parse_status = 'missing'), 0)::BIGINT AS missing_source_rows
        FROM {versions}
        """
    ).fetchdf().iloc[0]
    expected = _m1_inventory_count(reports_root, "additions")
    represented = int(version_stats["represented_source_rows"])
    parsed = int(version_stats["parsed_source_rows"])
    unparsed = int(version_stats["unparsed_source_rows"])
    nonmissing = parsed + unparsed
    parse_rate = parsed / nonmissing if nonmissing else 0.0

    add_validation(
        records,
        check_id="addition_versions_represent_source",
        category="events",
        passed=(expected is None or represented == expected),
        observed={
            "version_rows": int(version_stats["version_rows"]),
            "represented_source_rows": represented,
            "m1_expected": expected,
        },
        requirement="exact-deduplicated event versions account for every Bronze addition row",
    )
    add_validation(
        records,
        check_id="addition_event_time_parseability",
        category="temporal",
        passed=parse_rate >= spec.validation.addition_event_min_parse_success_nonnull,
        observed={
            "parse_success_nonmissing": parse_rate,
            "parsed_source_rows": parsed,
            "unparsed_source_rows": unparsed,
            "missing_source_rows": int(version_stats["missing_source_rows"]),
        },
        requirement=(
            f"addition event time parse success >= "
            f"{spec.validation.addition_event_min_parse_success_nonnull:.2%}"
        ),
    )

    event_stats = con.execute(
        f"""
        SELECT
            COUNT(*) AS event_count,
            COUNT(DISTINCT event_id) AS distinct_event_ids,
            COALESCE(SUM(source_row_count), 0)::BIGINT AS represented_source_rows,
            COUNT(*) FILTER (WHERE contract_link_status = 'matched') AS matched_contract,
            COUNT(*) FILTER (WHERE contract_link_status = 'unmatched_contract') AS unmatched_contract,
            COUNT(*) FILTER (WHERE contract_link_status = 'missing_contract_id') AS missing_contract_id,
            COUNT(DISTINCT event_type) AS event_types
        FROM {events}
        """
    ).fetchdf().iloc[0]
    event_rows = int(event_stats["event_count"])
    coverage = (
        int(event_stats["matched_contract"]) / event_rows if event_rows else 0.0
    )
    add_validation(
        records,
        check_id="addition_event_grain",
        category="events",
        passed=(
            event_rows == int(event_stats["distinct_event_ids"])
            and int(event_stats["represented_source_rows"]) == represented
        ),
        observed={
            "events": event_rows,
            "distinct_event_ids": int(event_stats["distinct_event_ids"]),
            "represented_source_rows": int(event_stats["represented_source_rows"]),
            "version_represented_source_rows": represented,
        },
        requirement="one row per canonical event id with complete source-row accounting",
    )
    add_validation(
        records,
        check_id="addition_contract_coverage",
        category="relationships",
        passed=coverage >= spec.validation.additions_contracts_min_coverage,
        observed={
            "coverage": coverage,
            "matched": int(event_stats["matched_contract"]),
            "unmatched": int(event_stats["unmatched_contract"]),
            "missing_contract_id": int(event_stats["missing_contract_id"]),
        },
        requirement=(
            f"canonical addition→contract coverage >= "
            f"{spec.validation.additions_contracts_min_coverage:.2%}"
        ),
    )
    add_validation(
        records,
        check_id="addition_event_scope_preserved",
        category="events",
        passed=int(event_stats["event_types"]) > 0,
        observed={"distinct_nonnull_event_types": int(event_stats["event_types"])},
        requirement="Silver preserves all event types; target semantics are decided in Gold",
    )
    return pd.DataFrame.from_records(records)


def validate_existing_events_silver(
    *,
    reports_root: Path,
    silver_dir: Path,
    manifest_dir: Path,
    silver_spec: SilverSpec,
    additions_path: Path,
    temp_directory: Path | None = None,
) -> EventsBuildResult:
    artifacts = _artifact_paths(silver_dir)
    missing = [name for name, path in artifacts.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Cannot finalize notebook 12; missing artifacts={missing}")
    con = connect(
        temp_directory=temp_directory,
        threads=silver_spec.runtime.duckdb_threads,
        memory_limit=silver_spec.runtime.duckdb_memory_limit,
    )
    try:
        for name, path in artifacts.items():
            source = f"read_parquet({sql_string(path)})"
            columns = set(
                con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()["column_name"].astype(str)
            )
            if "_silver_schema_version" not in columns:
                raise ValueError(f"Existing event artifact {name!r} has no _silver_schema_version")
            versions = {
                str(row[0])
                for row in con.execute(
                    f"SELECT DISTINCT _silver_schema_version FROM {source} "
                    "WHERE _silver_schema_version IS NOT NULL LIMIT 2"
                ).fetchall()
            }
            if versions != {silver_spec.schema_version}:
                raise ValueError(
                    f"Existing event artifact {name!r} schema versions {sorted(versions)!r} "
                    f"do not match {silver_spec.schema_version!r}"
                )
        validation = _validate_existing(
            con, artifacts, reports_root=reports_root, spec=silver_spec
        )
    finally:
        con.close()
    write_report(validation, reports_root / "silver" / "12_validation.parquet")
    manifest_path = write_manifest(
        manifest_dir / "silver_events.json",
        {
            "milestone": "M2",
            "component": "12_silver_events",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": silver_spec.schema_version,
            "source": str(additions_path),
            "artifacts": {name: str(path) for name, path in artifacts.items()},
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
        },
    )
    return EventsBuildResult(artifacts, validation, manifest_path)


def build_events_silver(
    additions_path: Path,
    *,
    additions_spec: DatasetSpec,
    reports_root: Path,
    silver_dir: Path,
    manifest_dir: Path,
    silver_spec: SilverSpec,
    date_order: str = "mdy",
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> EventsBuildResult:
    """Build exact event versions and canonical addition events out-of-core."""
    con = connect(
        temp_directory=temp_directory,
        threads=silver_spec.runtime.duckdb_threads,
        memory_limit=silver_spec.runtime.duckdb_memory_limit,
    )
    artifacts = _artifact_paths(silver_dir)
    work_dir = (temp_directory or silver_dir / ".duckdb_tmp") / "m2_12"
    work_dir.mkdir(parents=True, exist_ok=True)
    stage_path = work_dir / "additions_stage.parquet"
    duplicate_hashes_path = work_dir / "duplicate_hashes.parquet"
    representatives_path = work_dir / "duplicate_representatives.parquet"

    try:
        source = csv_source(additions_path, sample_size=sample_size, all_varchar=True)
        source_columns = describe_source(con, source)
        mapping = _normalized_schema(source_columns)
        required = {
            silver_spec.additions.contract_key,
            silver_spec.additions.event_time,
            silver_spec.additions.event_type,
            silver_spec.additions.identifier,
            silver_spec.additions.description,
        }
        missing = sorted(required - set(mapping))
        if missing:
            raise KeyError(f"Additions is missing required Silver fields: {missing}")

        print("[12] additions: staging raw payloads (streaming CSV -> Parquet)...")
        raw_projection = ", ".join(
            f"{quote_identifier(raw)} AS {quote_identifier(normalize_name(raw))}"
            for raw in source_columns
        )
        stage_query = f"""
            SELECT
                ROW_NUMBER() OVER ()::BIGINT AS _source_row_number,
                {row_md5_expr(source_columns)} AS _bronze_row_hash,
                {raw_projection}
            FROM {source}
        """
        copy_query(
            con,
            stage_query,
            stage_path,
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=True,
        )

        stage = f"read_parquet({sql_string(stage_path)})"
        print("[12] additions: finding duplicate fingerprints (narrow aggregate)...")
        duplicate_hash_query = f"""
            SELECT _bronze_row_hash
            FROM {stage}
            GROUP BY _bronze_row_hash
            HAVING COUNT(*) > 1
        """
        copy_query(
            con,
            duplicate_hash_query,
            duplicate_hashes_path,
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=True,
        )

        duplicate_hashes = f"read_parquet({sql_string(duplicate_hashes_path)})"
        group_columns = ", ".join(quote_identifier(normalize_name(c)) for c in source_columns)
        print("[12] additions: resolving candidate duplicates by exact raw equality...")
        representative_query = f"""
            WITH candidates AS (
                SELECT s.* FROM {stage} s
                INNER JOIN {duplicate_hashes} d USING (_bronze_row_hash)
            )
            SELECT
                MIN(_source_row_number)::BIGINT AS _representative_row_number,
                COUNT(*)::BIGINT AS _source_row_count
            FROM candidates
            GROUP BY {group_columns}
        """
        copy_query(
            con,
            representative_query,
            representatives_path,
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=True,
        )

        representatives = f"read_parquet({sql_string(representatives_path)})"
        contract_col = silver_spec.additions.contract_key
        time_col = silver_spec.additions.event_time
        type_col = silver_spec.additions.event_type
        identifier_col = silver_spec.additions.identifier
        description_col = silver_spec.additions.description
        parsed_time = timestamp_expr(time_col, date_order=date_order)
        snapshot = snapshot_date_from_path(additions_path)
        print("[12] additions: materializing exact event versions...")
        versions_query = f"""
            WITH unique_hash AS (
                SELECT s.* FROM {stage} s
                ANTI JOIN {duplicate_hashes} d USING (_bronze_row_hash)
            ), duplicate_reps AS (
                SELECT s.*, r._source_row_count
                FROM {stage} s
                INNER JOIN {representatives} r
                    ON s._source_row_number = r._representative_row_number
            ), payloads AS (
                SELECT *, 1::BIGINT AS _source_row_count FROM unique_hash
                UNION ALL
                SELECT * FROM duplicate_reps
            )
            SELECT
                {trimmed_text_expr(contract_col)} AS contract_id,
                {parsed_time} AS event_at,
                {trimmed_text_expr(time_col)} AS event_at__raw,
                CASE
                    WHEN {trimmed_text_expr(time_col)} IS NULL THEN 'missing'
                    WHEN {parsed_time} IS NOT NULL THEN 'parsed'
                    ELSE 'unparsed'
                END AS event_at__parse_status,
                {trimmed_text_expr(type_col)} AS event_type,
                {trimmed_text_expr(identifier_col)} AS source_event_id,
                {trimmed_text_expr(description_col)} AS event_description,
                _source_row_count,
                _bronze_row_hash AS _source_row_hash,
                {metadata_sql(source_id=additions_spec.source_id, snapshot_date=snapshot, schema_version=silver_spec.schema_version)}
            FROM payloads
        """
        copy_query(
            con,
            versions_query,
            artifacts["addition_event_versions"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        versions = f"read_parquet({sql_string(artifacts['addition_event_versions'])})"
        contracts_path = silver_dir / "contracts.parquet"
        if not contracts_path.exists():
            raise FileNotFoundError("contracts.parquet is required. Run notebook 10 first.")
        contracts = f"read_parquet({sql_string(contracts_path)})"
        print("[12] additions: materializing canonical event grain...")
        events_query = f"""
            WITH prepared AS (
                SELECT
                    *,
                    COALESCE(
                        STRFTIME(event_at, '%Y-%m-%dT%H:%M:%S'),
                        'raw:' || COALESCE(event_at__raw, '<NULL>')
                    ) AS event_time_key
                FROM {versions}
            ), grouped AS (
                SELECT
                    contract_id,
                    event_at,
                    CASE WHEN COUNT(DISTINCT event_at__raw) = 1 THEN MIN(event_at__raw) END AS event_at__raw,
                    event_time_key,
                    event_type,
                    COUNT(DISTINCT event_at__raw)::BIGINT AS event_time_raw_variants,
                    SUM(_source_row_count)::BIGINT AS source_row_count,
                    COUNT(*)::BIGINT AS payload_variant_count,
                    COUNT(DISTINCT source_event_id)::BIGINT AS source_event_id_variants,
                    COUNT(DISTINCT event_description)::BIGINT AS description_variants,
                    CASE WHEN COUNT(DISTINCT source_event_id) = 1 THEN MIN(source_event_id) END AS source_event_id,
                    MIN(_source_snapshot_date) AS _source_snapshot_date
                FROM prepared
                GROUP BY contract_id, event_at, event_time_key, event_type
            )
            SELECT
                MD5(CONCAT_WS('|~|', COALESCE(g.contract_id, '<NULL>'), g.event_time_key, COALESCE(g.event_type, '<NULL>'))) AS event_id,
                g.contract_id,
                g.event_at,
                g.event_at__raw,
                g.event_type,
                g.event_time_raw_variants,
                g.source_event_id,
                g.source_row_count,
                g.payload_variant_count,
                g.source_event_id_variants,
                g.description_variants,
                (g.payload_variant_count > 1) AS has_multiple_payload_variants,
                CASE
                    WHEN g.contract_id IS NULL THEN 'missing_contract_id'
                    WHEN c.contract_id IS NULL THEN 'unmatched_contract'
                    ELSE 'matched'
                END AS contract_link_status,
                g._source_snapshot_date,
                {sql_string(silver_spec.schema_version)} AS _silver_schema_version
            FROM grouped g
            LEFT JOIN {contracts} c USING (contract_id)
        """
        copy_query(
            con,
            events_query,
            artifacts["addition_events"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        validation = _validate_existing(
            con, artifacts, reports_root=reports_root, spec=silver_spec
        )
        write_report(validation, reports_root / "silver" / "12_validation.parquet")
    finally:
        con.close()
        shutil.rmtree(work_dir, ignore_errors=True)

    manifest_path = write_manifest(
        manifest_dir / "silver_events.json",
        {
            "milestone": "M2",
            "component": "12_silver_events",
            "implementation": BUILD_IMPLEMENTATION,
            "schema_version": silver_spec.schema_version,
            "source": str(additions_path),
            "artifacts": {name: str(path) for name, path in artifacts.items()},
            "blocking_validation_passed": bool(
                validation.loc[validation["blocking"], "passed"].all()
            ),
            "notes": [
                "all Adiciones Tipo values are preserved in Silver",
                "Gold decides whether the prediction target includes all event types or a documented subset",
                "exact raw duplicates are collapsed only after exact equality verification",
            ],
        },
    )
    return EventsBuildResult(artifacts, validation, manifest_path)
