from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalization_collisions, normalize_name, normalized_groups
from argos.common.reports import write_report
from argos.common.sql import (
    clean_text_expr,
    csv_source,
    money_expr,
    quote_identifier,
    row_md5_expr,
    sql_string,
    timestamp_expr,
    trimmed_text_expr,
)
from argos.config.registry import DatasetSpec
from argos.config.silver import SilverSpec
from argos.profiling.schema import classify_semantic_type, preliminary_temporal_role


BUILD_IMPLEMENTATION = "m2-10-out-of-core-v3"


@dataclass(frozen=True, slots=True)
class SilverBuildResult:
    artifacts: dict[str, Path]
    routing: pd.DataFrame
    conversion_audit: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def snapshot_date_from_path(path: Path) -> str:
    """Extract a YYYYMMDD snapshot suffix from a Bronze filename."""
    matches = re.findall(r"(?<!\d)(20\d{6})(?!\d)", path.stem)
    if not matches:
        raise ValueError(
            f"Could not infer snapshot date from {path.name!r}; expected YYYYMMDD."
        )
    value = matches[-1]
    parsed = datetime.strptime(value, "%Y%m%d")
    return parsed.date().isoformat()


def _profile_lookup(profile: pd.DataFrame, dataset: str) -> dict[str, dict[str, Any]]:
    subset = profile.loc[profile["dataset"] == dataset]
    result: dict[str, dict[str, Any]] = {}
    for row in subset.to_dict(orient="records"):
        normalized = str(row["normalized_column"])
        if normalized in result:
            raise ValueError(
                f"M1 column profile has duplicate normalized name {normalized!r} "
                f"for dataset={dataset!r}. Resolve the collision before Silver."
            )
        result[normalized] = row
    return result


def _physical_mapping(con, source_sql: str, dataset: str) -> tuple[list[str], dict[str, str]]:
    schema = con.execute(f"DESCRIBE SELECT * FROM {source_sql}").fetchdf()
    columns = schema["column_name"].astype(str).tolist()
    collisions = normalization_collisions(columns)
    if collisions:
        raise ValueError(
            f"Silver requires unambiguous normalized columns for {dataset!r}; "
            f"collisions={collisions}"
        )
    groups = normalized_groups(columns)
    return columns, {normalized: raw[0] for normalized, raw in groups.items()}


def _semantic(profile_row: dict[str, Any] | None, raw_column: str) -> str:
    if profile_row is not None and profile_row.get("semantic_type"):
        return str(profile_row["semantic_type"])
    return classify_semantic_type(raw_column)


def _leakage(profile_row: dict[str, Any] | None, raw_column: str) -> str:
    if profile_row is not None and profile_row.get("leakage_risk_hint"):
        return str(profile_row["leakage_risk_hint"])
    return preliminary_temporal_role(raw_column)[1]


def _canonical_name(normalized: str, rename: dict[str, str]) -> str:
    return rename.get(normalized, normalized)


def _assert_unique_canonical_names(records: list[dict[str, Any]], dataset: str) -> None:
    active = [
        str(row["canonical_column"])
        for row in records
        if row["route"] != "excluded_sensitive"
    ]
    duplicates = sorted({name for name in active if active.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"Canonical Silver column collision for {dataset!r}: {duplicates}"
        )


def _plan_contracts(
    columns: list[str],
    mapping: dict[str, str],
    profile: dict[str, dict[str, Any]],
    spec: SilverSpec,
) -> list[dict[str, Any]]:
    normalized_available = set(mapping)
    required = {
        spec.contracts.primary_key,
        spec.contracts.process_fk,
        spec.contracts.supplier_fk,
    }
    missing_required = sorted(required - normalized_available)
    if missing_required:
        raise KeyError(f"Contracts is missing required Silver columns: {missing_required}")

    configured_state = set(spec.contracts.snapshot_state_columns)
    missing_state = sorted(configured_state - normalized_available)
    if missing_state:
        raise KeyError(
            "Configured contracts snapshot-state columns are missing from Bronze: "
            f"{missing_state}"
        )

    records: list[dict[str, Any]] = []
    for raw in columns:
        normalized = normalize_name(raw)
        profile_row = profile.get(normalized)
        semantic = _semantic(profile_row, raw)
        leakage = _leakage(profile_row, raw)
        canonical = _canonical_name(normalized, spec.contracts.rename)

        if semantic in spec.contracts.excluded_semantic_types:
            route = "excluded_sensitive"
            reason = f"semantic_type={semantic}"
        elif normalized in configured_state or leakage == "high":
            route = "snapshot_state"
            reason = "M1 mutable/post-t0 leakage risk"
        else:
            route = "core"
            reason = "canonical Silver; not automatically model-safe"

        if normalized in required:
            route = "core"
            reason = "required canonical key/link field"

        records.append(
            {
                "dataset": "contracts",
                "raw_column": raw,
                "normalized_column": normalized,
                "canonical_column": canonical,
                "semantic_type": semantic,
                "leakage_risk_hint": leakage,
                "route": route,
                "reason": reason,
            }
        )

    _assert_unique_canonical_names(records, "contracts")
    return records


def _plan_processes(
    columns: list[str],
    mapping: dict[str, str],
    profile: dict[str, dict[str, Any]],
    spec: SilverSpec,
) -> list[dict[str, Any]]:
    required = {
        spec.processes.identity_key,
        spec.processes.procedure_key,
        spec.processes.reference_key,
    }
    missing_required = sorted(required - set(mapping))
    if missing_required:
        raise KeyError(f"Processes is missing required Silver columns: {missing_required}")

    records: list[dict[str, Any]] = []
    for raw in columns:
        normalized = normalize_name(raw)
        profile_row = profile.get(normalized)
        semantic = _semantic(profile_row, raw)
        leakage = _leakage(profile_row, raw)
        canonical = _canonical_name(normalized, spec.processes.rename)
        if semantic in spec.processes.excluded_semantic_types:
            route = "excluded_sensitive"
            reason = f"semantic_type={semantic}"
        else:
            route = "version"
            reason = "preserve observed process payload variant"
        records.append(
            {
                "dataset": "processes",
                "raw_column": raw,
                "normalized_column": normalized,
                "canonical_column": canonical,
                "semantic_type": semantic,
                "leakage_risk_hint": leakage,
                "route": route,
                "reason": reason,
            }
        )

    _assert_unique_canonical_names(records, "processes")
    return records


def plan_contracts_processes_silver(
    contracts_path: Path,
    processes_path: Path,
    *,
    column_profile_path: Path,
    silver_spec: SilverSpec,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Create an auditable Bronze->Silver column-routing plan without writing data."""
    profile = pd.read_parquet(column_profile_path)
    con = connect(
        temp_directory=temp_directory,
        threads=silver_spec.runtime.duckdb_threads,
        memory_limit=silver_spec.runtime.duckdb_memory_limit,
    )
    try:
        contracts_source = csv_source(
            contracts_path, sample_size=sample_size, all_varchar=True
        )
        processes_source = csv_source(
            processes_path, sample_size=sample_size, all_varchar=True
        )
        contract_columns, contract_mapping = _physical_mapping(
            con, contracts_source, "contracts"
        )
        process_columns, process_mapping = _physical_mapping(
            con, processes_source, "processes"
        )
    finally:
        con.close()

    records = [
        *_plan_contracts(
            contract_columns,
            contract_mapping,
            _profile_lookup(profile, "contracts"),
            silver_spec,
        ),
        *_plan_processes(
            process_columns,
            process_mapping,
            _profile_lookup(profile, "processes"),
            silver_spec,
        ),
    ]
    return pd.DataFrame.from_records(records)


def _typed_expr(identifier: str, semantic_type: str, *, date_order: str) -> str:
    if semantic_type == "date":
        return timestamp_expr(identifier, date_order=date_order)
    if semantic_type == "money":
        return money_expr(identifier)
    return trimmed_text_expr(identifier)


def _typed_projection(
    identifier: str,
    canonical_name: str,
    semantic_type: str,
    *,
    date_order: str,
) -> list[str]:
    """Project one canonical column and lossless parse diagnostics when needed.

    Date and money parsing is intentionally non-destructive: Silver stores the
    typed value, a trimmed raw shadow and a parse-status column. This prevents
    values with unsupported formats from disappearing silently.
    """
    typed = _typed_expr(identifier, semantic_type, date_order=date_order)
    expressions = [f"{typed} AS {quote_identifier(canonical_name)}"]
    if semantic_type not in {"date", "money"}:
        return expressions

    raw_name = f"{canonical_name}__raw"
    status_name = f"{canonical_name}__parse_status"
    clean = clean_text_expr(identifier)
    expressions.extend(
        [
            f"{trimmed_text_expr(identifier)} AS {quote_identifier(raw_name)}",
            (
                "CASE "
                f"WHEN {clean} IS NULL THEN 'missing' "
                f"WHEN {typed} IS NOT NULL THEN 'parsed' "
                "ELSE 'unparsed' END "
                f"AS {quote_identifier(status_name)}"
            ),
        ]
    )
    return expressions


def _prepare_output(path: Path, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not overwrite:
            raise FileExistsError(
                f"Silver artifact already exists: {path}. Pass overwrite=True intentionally."
            )
        path.unlink()


def _copy_query(
    con,
    query: str,
    path: Path,
    *,
    compression: str,
    row_group_size: int,
    overwrite: bool,
) -> None:
    _prepare_output(path, overwrite=overwrite)
    compression_sql = re.sub(r"[^A-Za-z0-9_]", "", compression).upper()
    if not compression_sql:
        raise ValueError("Invalid Parquet compression setting")
    con.execute(
        f"COPY ({query}) TO {sql_string(path)} "
        f"(FORMAT PARQUET, COMPRESSION {compression_sql}, "
        f"ROW_GROUP_SIZE {int(row_group_size)})"
    )


def _literal_metadata(
    *,
    source_id: str,
    snapshot_date: str,
    schema_version: str,
) -> list[str]:
    return [
        f"DATE {sql_string(snapshot_date)} AS _source_snapshot_date",
        f"{sql_string(source_id)} AS _source_id",
        f"{sql_string(schema_version)} AS _silver_schema_version",
    ]


def _route_rows(routing: pd.DataFrame, dataset: str, route: str) -> list[dict[str, Any]]:
    subset = routing.loc[
        (routing["dataset"] == dataset) & (routing["route"] == route)
    ]
    return subset.to_dict(orient="records")


def _contracts_query(
    source_sql: str,
    source_columns: list[str],
    rows: list[dict[str, Any]],
    *,
    source_id: str,
    snapshot_date: str,
    schema_version: str,
    date_order: str,
) -> str:
    expressions: list[str] = []
    for row in rows:
        expressions.extend(
            _typed_projection(
                str(row["raw_column"]),
                str(row["canonical_column"]),
                str(row["semantic_type"]),
                date_order=date_order,
            )
        )
    expressions.extend(
        [
            f"{row_md5_expr(source_columns)} AS _source_row_hash",
            *_literal_metadata(
                source_id=source_id,
                snapshot_date=snapshot_date,
                schema_version=schema_version,
            ),
        ]
    )
    return f"SELECT {', '.join(expressions)} FROM {source_sql}"


def _process_stage_query(
    source_sql: str,
    source_columns: list[str],
) -> str:
    """Stage the process snapshot once before exact duplicate resolution.

    The old implementation executed ``GROUP BY ALL`` across the complete 9M-row,
    59-column CSV. That creates a very wide hash table and can consume the full
    memory budget of a 16 GB laptop.

    Staging keeps the raw values (including columns later excluded from analytical
    Silver) only inside the local temporary directory. They are required so that
    final duplicate resolution remains *exact*: the row fingerprint is used only
    to find candidate duplicate groups, never as the authority for equality.
    """
    raw_projection = ", ".join(
        f"{quote_identifier(raw)} AS {quote_identifier(normalize_name(raw))}"
        for raw in source_columns
    )
    full_row_fingerprint = row_md5_expr(source_columns)
    return f"""
        SELECT
            ROW_NUMBER() OVER ()::BIGINT AS _source_row_number,
            {full_row_fingerprint} AS _bronze_row_hash,
            {raw_projection}
        FROM {source_sql}
    """


def _process_duplicate_hashes_query(stage_path: Path) -> str:
    """Find only fingerprints that occur more than once.

    This is a narrow aggregation (one VARCHAR key + count), so DuckDB can spill it
    efficiently. The result is expected to be far smaller than the source snapshot.
    """
    stage = f"read_parquet({sql_string(stage_path)})"
    return f"""
        SELECT _bronze_row_hash
        FROM {stage}
        GROUP BY _bronze_row_hash
        HAVING COUNT(*) > 1
    """


def _process_duplicate_representatives_query(
    stage_path: Path,
    duplicate_hashes_path: Path,
    normalized_source_columns: list[str],
) -> str:
    """Resolve candidate hash groups by exact raw-column equality.

    Any accidental fingerprint collision is harmless: rows sharing a fingerprint
    are re-grouped using every raw Bronze column before one representative row is
    selected. ``GROUP BY`` is therefore wide only for the small duplicate-candidate
    population, not for all 9M process rows.
    """
    stage = f"read_parquet({sql_string(stage_path)})"
    duplicate_hashes = f"read_parquet({sql_string(duplicate_hashes_path)})"
    group_columns = ", ".join(quote_identifier(name) for name in normalized_source_columns)
    return f"""
        WITH duplicate_candidates AS (
            SELECT s.*
            FROM {stage} s
            INNER JOIN {duplicate_hashes} d USING (_bronze_row_hash)
        )
        SELECT
            MIN(_source_row_number)::BIGINT AS _representative_row_number,
            COUNT(*)::BIGINT AS _source_row_count
        FROM duplicate_candidates
        GROUP BY {group_columns}
    """


def _process_versions_from_stage_query(
    stage_path: Path,
    duplicate_hashes_path: Path,
    duplicate_representatives_path: Path,
    rows: list[dict[str, Any]],
    *,
    source_id: str,
    snapshot_date: str,
    schema_version: str,
    date_order: str,
) -> str:
    """Materialize one typed process row per exact Bronze payload."""
    active_rows = [row for row in rows if row["route"] == "version"]
    typed_expressions: list[str] = []
    for row in active_rows:
        typed_expressions.extend(
            _typed_projection(
                str(row["normalized_column"]),
                str(row["canonical_column"]),
                str(row["semantic_type"]),
                date_order=date_order,
            )
        )
    typed_projection = ", ".join(typed_expressions)
    metadata = ", ".join(
        _literal_metadata(
            source_id=source_id,
            snapshot_date=snapshot_date,
            schema_version=schema_version,
        )
    )
    stage = f"read_parquet({sql_string(stage_path)})"
    duplicate_hashes = f"read_parquet({sql_string(duplicate_hashes_path)})"
    representatives = f"read_parquet({sql_string(duplicate_representatives_path)})"
    return f"""
        WITH unique_fingerprint_rows AS (
            SELECT s.*
            FROM {stage} s
            ANTI JOIN {duplicate_hashes} d USING (_bronze_row_hash)
        ),
        duplicate_representatives AS (
            SELECT s.*, r._source_row_count
            FROM {stage} s
            INNER JOIN {representatives} r
                ON s._source_row_number = r._representative_row_number
        )
        SELECT
            {typed_projection},
            1::BIGINT AS _source_row_count,
            _bronze_row_hash AS _source_row_hash,
            {metadata}
        FROM unique_fingerprint_rows
        UNION ALL
        SELECT
            {typed_projection},
            _source_row_count,
            _bronze_row_hash AS _source_row_hash,
            {metadata}
        FROM duplicate_representatives
    """


def _process_identity_query(
    versions_path: Path,
    *,
    source_id: str,
    snapshot_date: str,
    schema_version: str,
) -> str:
    source = f"read_parquet({sql_string(versions_path)})"
    return f"""
        SELECT
            process_id,
            SUM(_source_row_count)::BIGINT AS source_row_count,
            COUNT(*)::BIGINT AS version_count,
            SUM(_source_row_count - 1)::BIGINT AS exact_duplicate_excess_rows,
            COUNT(DISTINCT procedure_id)::BIGINT AS procedure_id_variants,
            COUNT(DISTINCT process_reference)::BIGINT AS process_reference_variants,
            (COUNT(*) > 1) AS has_multiple_payload_variants,
            DATE {sql_string(snapshot_date)} AS _source_snapshot_date,
            {sql_string(source_id)} AS _source_id,
            {sql_string(schema_version)} AS _silver_schema_version
        FROM {source}
        WHERE process_id IS NOT NULL
        GROUP BY process_id
    """


def _links_query(
    contracts_path: Path,
    processes_path: Path,
    *,
    schema_version: str,
) -> str:
    contracts = f"read_parquet({sql_string(contracts_path)})"
    processes = f"read_parquet({sql_string(processes_path)})"
    return f"""
        SELECT
            c.contract_id,
            c.process_id,
            CASE
                WHEN c.process_id IS NULL THEN 'missing_process_id'
                WHEN p.process_id IS NULL THEN 'unmatched_process'
                ELSE 'matched'
            END AS link_status,
            p.version_count AS process_version_count,
            c._source_snapshot_date,
            {sql_string(schema_version)} AS _silver_schema_version
        FROM {contracts} c
        LEFT JOIN {processes} p USING (process_id)
    """


def _int_or_zero(value: Any) -> int:
    """Convert an aggregate result to int without failing on SQL NULL/NaN.

    DuckDB aggregate functions such as SUM return NULL for an empty input. When
    fetched through pandas that may become NaN; ``int(float("nan"))`` raises a
    ValueError and can obscure the real upstream condition.
    """
    if value is None or pd.isna(value):
        return 0
    return int(value)


def _conversion_audit(
    con,
    artifacts: dict[str, Path],
    routing: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize non-destructive date/money parsing from Silver artifacts."""
    records: list[dict[str, Any]] = []
    for row in routing.to_dict(orient="records"):
        semantic = str(row["semantic_type"])
        route = str(row["route"])
        if semantic not in {"date", "money"} or route == "excluded_sensitive":
            continue

        dataset = str(row["dataset"])
        canonical = str(row["canonical_column"])
        status = quote_identifier(f"{canonical}__parse_status")
        if dataset == "contracts" and route == "core":
            artifact_name = "contracts"
            weight = "1"
        elif dataset == "contracts" and route == "snapshot_state":
            artifact_name = "contracts_snapshot_state"
            weight = "1"
        elif dataset == "processes" and route == "version":
            artifact_name = "process_versions"
            weight = "_source_row_count"
        else:
            continue

        source = f"read_parquet({sql_string(artifacts[artifact_name])})"
        stats = con.execute(
            f"""
            SELECT
                COALESCE(SUM({weight}), 0) AS represented_rows,
                COALESCE(SUM({weight}) FILTER (WHERE {status} = 'missing'), 0) AS missing_rows,
                COALESCE(SUM({weight}) FILTER (WHERE {status} = 'parsed'), 0) AS parsed_rows,
                COALESCE(SUM({weight}) FILTER (WHERE {status} = 'unparsed'), 0) AS unparsed_rows
            FROM {source}
            """
        ).fetchdf().iloc[0]
        represented = _int_or_zero(stats["represented_rows"])
        missing = _int_or_zero(stats["missing_rows"])
        parsed = _int_or_zero(stats["parsed_rows"])
        unparsed = _int_or_zero(stats["unparsed_rows"])
        nonmissing = parsed + unparsed
        records.append(
            {
                "dataset": dataset,
                "artifact": artifact_name,
                "canonical_column": canonical,
                "semantic_type": semantic,
                "represented_rows": represented,
                "missing_rows": missing,
                "parsed_rows": parsed,
                "unparsed_rows": unparsed,
                "parse_success_rate_nonmissing": (
                    parsed / nonmissing if nonmissing else None
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def _read_inventory_expected(reports_root: Path, dataset: str) -> int | None:
    path = reports_root / "profiling" / "dataset_inventory.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    row = frame.loc[frame["dataset"] == dataset]
    if row.empty:
        return None
    return int(row.iloc[0]["row_count"])


def _read_key_expected(
    reports_root: Path, dataset: str, candidate_key: str
) -> int | None:
    path = reports_root / "profiling" / "key_analysis.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    row = frame.loc[
        (frame["dataset"] == dataset)
        & (frame["candidate_key"] == candidate_key)
        & (frame["status"] == "analyzed")
    ]
    if row.empty:
        return None
    return int(row.iloc[0]["distinct_nonnull_keys"])


def _read_t0_expected(
    reports_root: Path, dataset: str, normalized_column: str
) -> tuple[int, int] | None:
    path = reports_root / "profiling" / "temporal_profile.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    row = frame.loc[
        (frame["dataset"] == dataset)
        & (frame["normalized_column"] == normalized_column)
    ]
    if row.empty:
        return None
    record = row.iloc[0]
    return int(record["raw_nonnull_count"]), int(record["parsed_count"])


def _serialize_validation_observed(value: Any) -> str:
    """Serialize heterogeneous validation evidence to a Parquet-safe string.

    Validation checks naturally produce evidence with different shapes (dicts,
    lists, scalars). A pandas ``object`` column mixing those structures cannot be
    represented by one Arrow type, which makes ``DataFrame.to_parquet`` fail even
    after the expensive Silver artifacts were built successfully.

    Store the evidence as deterministic JSON text instead. This preserves the
    complete diagnostic payload while keeping the report schema stable.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _validation_record(
    records: list[dict[str, Any]],
    *,
    check_id: str,
    category: str,
    passed: bool,
    observed: Any,
    requirement: str,
    blocking: bool = True,
) -> None:
    records.append(
        {
            "check_id": check_id,
            "category": category,
            "blocking": blocking,
            "passed": bool(passed),
            "observed": _serialize_validation_observed(observed),
            "requirement": requirement,
        }
    )


def _validate_outputs(
    con,
    artifacts: dict[str, Path],
    routing: pd.DataFrame,
    *,
    reports_root: Path,
    spec: SilverSpec,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    contracts = f"read_parquet({sql_string(artifacts['contracts'])})"
    state = f"read_parquet({sql_string(artifacts['contracts_snapshot_state'])})"
    versions = f"read_parquet({sql_string(artifacts['process_versions'])})"
    processes = f"read_parquet({sql_string(artifacts['processes'])})"
    links = f"read_parquet({sql_string(artifacts['contract_process_links'])})"

    contract_stats = con.execute(
        f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT contract_id) AS distinct_ids,
            COUNT(*) FILTER (WHERE contract_id IS NULL) AS null_ids,
            COUNT(*) FILTER (WHERE fecha_de_firma IS NOT NULL) AS parsed_t0
        FROM {contracts}
        """
    ).fetchdf().iloc[0]
    expected_contracts = _read_inventory_expected(reports_root, "contracts")
    _validation_record(
        records,
        check_id="contracts_row_count",
        category="contracts",
        passed=(expected_contracts is None or int(contract_stats["rows"]) == expected_contracts),
        observed={"rows": int(contract_stats["rows"]), "m1_expected": expected_contracts},
        requirement="Silver contracts preserves the M1 Bronze contract population",
    )
    _validation_record(
        records,
        check_id="contracts_primary_key",
        category="contracts",
        passed=(
            int(contract_stats["null_ids"]) == 0
            and int(contract_stats["distinct_ids"]) == int(contract_stats["rows"])
        ),
        observed={
            "rows": int(contract_stats["rows"]),
            "distinct_contract_id": int(contract_stats["distinct_ids"]),
            "null_contract_id": int(contract_stats["null_ids"]),
        },
        requirement="contract_id is non-null and unique",
    )

    state_rows = int(con.execute(f"SELECT COUNT(*) FROM {state}").fetchone()[0])
    _validation_record(
        records,
        check_id="snapshot_state_alignment",
        category="contracts",
        passed=state_rows == int(contract_stats["rows"]),
        observed={"state_rows": state_rows, "contract_rows": int(contract_stats["rows"])},
        requirement="one snapshot-state row per contract",
    )

    risky_core = routing.loc[
        (routing["dataset"] == "contracts")
        & (routing["route"] == "core")
        & (routing["leakage_risk_hint"] == "high")
    ]
    _validation_record(
        records,
        check_id="mutable_fields_segregated",
        category="leakage",
        passed=risky_core.empty,
        observed=risky_core["canonical_column"].tolist(),
        requirement="no M1 high-leakage field is stored in contracts.parquet",
    )

    sensitive_core = routing.loc[
        (routing["dataset"] == "contracts")
        & (routing["route"] == "core")
        & (routing["semantic_type"].isin(spec.contracts.excluded_semantic_types))
    ]
    _validation_record(
        records,
        check_id="sensitive_fields_excluded",
        category="privacy",
        passed=sensitive_core.empty,
        observed=sensitive_core["canonical_column"].tolist(),
        requirement="configured sensitive semantic types are not in general Silver contracts",
    )

    t0_expected = _read_t0_expected(
        reports_root, "contracts", spec.validation.t0_column
    )
    if t0_expected is None:
        t0_rate = None
        t0_pass = False
        t0_observed: Any = "M1 temporal evidence missing"
    else:
        raw_nonnull, expected_parsed = t0_expected
        parsed = int(contract_stats["parsed_t0"])
        t0_rate = parsed / raw_nonnull if raw_nonnull else None
        t0_pass = (
            parsed == expected_parsed
            and t0_rate is not None
            and t0_rate >= spec.validation.t0_min_parse_success_nonnull
        )
        t0_observed = {
            "silver_parsed": parsed,
            "m1_raw_nonnull": raw_nonnull,
            "m1_parsed": expected_parsed,
            "parse_success": t0_rate,
        }
    _validation_record(
        records,
        check_id="t0_preserved",
        category="temporal",
        passed=t0_pass,
        observed=t0_observed,
        requirement=(
            "Silver uses the same explicit t0 parser and preserves the M1 parsed population"
        ),
    )

    version_stats = con.execute(
        f"""
        SELECT
            COUNT(*) AS versions,
            COALESCE(SUM(_source_row_count), 0) AS represented_source_rows,
            COUNT(*) FILTER (WHERE process_id IS NULL) AS null_process_id
        FROM {versions}
        """
    ).fetchdf().iloc[0]
    expected_process_rows = _read_inventory_expected(reports_root, "processes")
    _validation_record(
        records,
        check_id="process_versions_represent_source",
        category="processes",
        passed=(
            int(version_stats["null_process_id"]) == 0
            and (
                expected_process_rows is None
                or int(version_stats["represented_source_rows"]) == expected_process_rows
            )
        ),
        observed={
            "version_rows": int(version_stats["versions"]),
            "represented_source_rows": int(version_stats["represented_source_rows"]),
            "null_process_id": int(version_stats["null_process_id"]),
            "m1_expected_source_rows": expected_process_rows,
        },
        requirement=(
            "deduplicated versions account for every Bronze process row and "
            "preserve a non-null process identity"
        ),
    )

    process_stats = con.execute(
        f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT process_id) AS distinct_ids,
            COUNT(*) FILTER (WHERE process_id IS NULL) AS null_ids
        FROM {processes}
        """
    ).fetchdf().iloc[0]
    expected_process_ids = _read_key_expected(
        reports_root, "processes", spec.processes.identity_key
    )
    process_pk_ok = (
        int(process_stats["null_ids"]) == 0
        and int(process_stats["rows"]) == int(process_stats["distinct_ids"])
        and (
            expected_process_ids is None
            or int(process_stats["rows"]) == expected_process_ids
        )
    )
    _validation_record(
        records,
        check_id="process_identity_key",
        category="processes",
        passed=process_pk_ok,
        observed={
            "rows": int(process_stats["rows"]),
            "distinct_process_id": int(process_stats["distinct_ids"]),
            "null_process_id": int(process_stats["null_ids"]),
            "m1_expected_distinct": expected_process_ids,
        },
        requirement="processes.parquet is one row per non-null process_id",
    )

    link_stats = con.execute(
        f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT contract_id) AS distinct_contracts,
            COUNT(*) FILTER (WHERE link_status = 'matched') AS matched,
            COUNT(*) FILTER (WHERE link_status = 'unmatched_process') AS unmatched,
            COUNT(*) FILTER (WHERE link_status = 'missing_process_id') AS missing_key
        FROM {links}
        """
    ).fetchdf().iloc[0]
    coverage = (
        int(link_stats["matched"]) / int(link_stats["rows"])
        if int(link_stats["rows"])
        else 0.0
    )
    _validation_record(
        records,
        check_id="contract_process_link_grain",
        category="relationships",
        passed=(
            int(link_stats["rows"]) == int(contract_stats["rows"])
            and int(link_stats["distinct_contracts"]) == int(link_stats["rows"])
        ),
        observed={
            "rows": int(link_stats["rows"]),
            "distinct_contracts": int(link_stats["distinct_contracts"]),
        },
        requirement="one contract-process link row per contract; no join expansion",
    )
    _validation_record(
        records,
        check_id="contract_process_link_coverage",
        category="relationships",
        passed=coverage >= spec.validation.contracts_processes_min_coverage,
        observed={
            "coverage": coverage,
            "matched": int(link_stats["matched"]),
            "unmatched": int(link_stats["unmatched"]),
            "missing_key": int(link_stats["missing_key"]),
        },
        requirement=(
            f"coverage >= {spec.validation.contracts_processes_min_coverage:.2%} "
            "after process canonicalization"
        ),
    )

    return pd.DataFrame.from_records(records)


def _manifest_payload(
    *,
    artifacts: dict[str, Path],
    routing: pd.DataFrame,
    conversion_audit: pd.DataFrame,
    validation: pd.DataFrame,
    contracts_path: Path,
    processes_path: Path,
    spec: SilverSpec,
) -> dict[str, Any]:
    return {
        "milestone": "M2",
        "component": "10_silver_contracts_processes",
        "schema_version": spec.schema_version,
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duckdb_runtime": {
            "threads": spec.runtime.duckdb_threads,
            "memory_limit": spec.runtime.duckdb_memory_limit,
        },
        "sources": {
            "contracts": {
                "path": str(contracts_path),
                "snapshot_date": snapshot_date_from_path(contracts_path),
            },
            "processes": {
                "path": str(processes_path),
                "snapshot_date": snapshot_date_from_path(processes_path),
            },
        },
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "column_routes": routing["route"].value_counts().to_dict(),
        "type_conversion_unparsed_rows": int(
            conversion_audit["unparsed_rows"].sum() if not conversion_audit.empty else 0
        ),
        "blocking_validation_passed": bool(
            validation.loc[validation["blocking"], "passed"].all()
        ),
        "validation": validation.to_dict(orient="records"),
        "notes": [
            "contracts.parquet is canonical Silver, not a Gold feature whitelist",
            "mutable/current-state contract fields are physically segregated",
            "process_versions.parquet preserves payload variants after exact raw-row deduplication",
            "processes.parquet is an identity/diagnostic table, not a latest-state snapshot",
        ],
    }


def _artifact_paths(silver_dir: Path) -> dict[str, Path]:
    return {
        "contracts": silver_dir / "contracts.parquet",
        "contracts_snapshot_state": silver_dir / "contracts_snapshot_state.parquet",
        "process_versions": silver_dir / "process_versions.parquet",
        "processes": silver_dir / "processes.parquet",
        "contract_process_links": silver_dir / "contract_process_links.parquet",
    }


def finalize_existing_contracts_processes_silver(
    contracts_path: Path,
    processes_path: Path,
    *,
    column_profile_path: Path,
    reports_root: Path,
    silver_dir: Path,
    manifest_dir: Path,
    silver_spec: SilverSpec,
    date_order: str = "mdy",
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> SilverBuildResult:
    """Validate/finalize an already materialized notebook-10 artifact set.

    This recovery path exists for failures that happen *after* the expensive
    Parquet materialization (for example report serialization). It deliberately
    does not rewrite any Silver data. All five artifacts must already exist; the
    normal validation suite is then rerun before reports/manifest are persisted.
    """
    artifacts = _artifact_paths(silver_dir)
    missing = [name for name, path in artifacts.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Cannot finalize notebook 10 because Silver artifacts are missing: "
            + ", ".join(missing)
        )

    routing = plan_contracts_processes_silver(
        contracts_path,
        processes_path,
        column_profile_path=column_profile_path,
        silver_spec=silver_spec,
        sample_size=sample_size,
        temp_directory=temp_directory,
    )
    write_report(routing, reports_root / "silver" / "10_column_routing.parquet")

    con = connect(
        temp_directory=temp_directory,
        threads=silver_spec.runtime.duckdb_threads,
        memory_limit=silver_spec.runtime.duckdb_memory_limit,
    )
    try:
        # Refuse to bless artifacts from an incompatible schema contract.
        for name, path in artifacts.items():
            source = f"read_parquet({sql_string(path)})"
            columns = {
                str(value)
                for value in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()[
                    "column_name"
                ].tolist()
            }
            if "_silver_schema_version" not in columns:
                raise ValueError(
                    f"Existing artifact {name!r} has no _silver_schema_version; "
                    "rebuild notebook 10 instead of finalizing it."
                )
            versions = con.execute(
                f"""
                SELECT DISTINCT _silver_schema_version
                FROM {source}
                WHERE _silver_schema_version IS NOT NULL
                LIMIT 2
                """
            ).fetchall()
            observed_versions = {str(row[0]) for row in versions}
            if observed_versions != {silver_spec.schema_version}:
                raise ValueError(
                    f"Existing artifact {name!r} schema versions "
                    f"{sorted(observed_versions)!r} do not match "
                    f"{silver_spec.schema_version!r}; rebuild notebook 10."
                )

        conversion_audit = _conversion_audit(con, artifacts, routing)
        validation = _validate_outputs(
            con,
            artifacts,
            routing,
            reports_root=reports_root,
            spec=silver_spec,
        )
    finally:
        con.close()

    write_report(
        conversion_audit, reports_root / "silver" / "10_type_conversion_audit.parquet"
    )
    write_report(validation, reports_root / "silver" / "10_validation.parquet")

    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "silver_contracts_processes.json"
    manifest = _manifest_payload(
        artifacts=artifacts,
        routing=routing,
        conversion_audit=conversion_audit,
        validation=validation,
        contracts_path=contracts_path,
        processes_path=processes_path,
        spec=silver_spec,
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    return SilverBuildResult(
        artifacts=artifacts,
        routing=routing,
        conversion_audit=conversion_audit,
        validation=validation,
        manifest_path=manifest_path,
    )


def build_contracts_processes_silver(
    contracts_path: Path,
    processes_path: Path,
    *,
    contracts_spec: DatasetSpec,
    processes_spec: DatasetSpec,
    column_profile_path: Path,
    reports_root: Path,
    silver_dir: Path,
    manifest_dir: Path,
    silver_spec: SilverSpec,
    date_order: str = "mdy",
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
    overwrite: bool = False,
) -> SilverBuildResult:
    """Build canonical Contract/Process Silver artifacts from immutable Bronze CSVs.

    This function deliberately does not create ML features or labels. It produces
    reusable domain tables plus validation evidence for notebook 10.
    """
    routing = plan_contracts_processes_silver(
        contracts_path,
        processes_path,
        column_profile_path=column_profile_path,
        silver_spec=silver_spec,
        sample_size=sample_size,
        temp_directory=temp_directory,
    )
    write_report(routing, reports_root / "silver" / "10_column_routing.parquet")

    con = connect(
        temp_directory=temp_directory,
        threads=silver_spec.runtime.duckdb_threads,
        memory_limit=silver_spec.runtime.duckdb_memory_limit,
    )
    artifacts = _artifact_paths(silver_dir)

    try:
        contracts_source = csv_source(
            contracts_path, sample_size=sample_size, all_varchar=True
        )
        processes_source = csv_source(
            processes_path, sample_size=sample_size, all_varchar=True
        )
        _physical_mapping(con, contracts_source, "contracts")
        process_columns, _ = _physical_mapping(con, processes_source, "processes")

        contract_core = _route_rows(routing, "contracts", "core")
        contract_state = _route_rows(routing, "contracts", "snapshot_state")
        contract_lineage_columns = [
            str(row["raw_column"])
            for row in routing.loc[
                (routing["dataset"] == "contracts")
                & (routing["route"] != "excluded_sensitive")
            ].to_dict(orient="records")
        ]
        contract_id_row = next(
            row
            for row in contract_core
            if row["normalized_column"] == silver_spec.contracts.primary_key
        )
        state_rows = [contract_id_row, *contract_state]

        contract_snapshot = snapshot_date_from_path(contracts_path)
        process_snapshot = snapshot_date_from_path(processes_path)

        _copy_query(
            con,
            _contracts_query(
                contracts_source,
                contract_lineage_columns,
                contract_core,
                source_id=contracts_spec.source_id,
                snapshot_date=contract_snapshot,
                schema_version=silver_spec.schema_version,
                date_order=date_order,
            ),
            artifacts["contracts"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )
        _copy_query(
            con,
            _contracts_query(
                contracts_source,
                contract_lineage_columns,
                state_rows,
                source_id=contracts_spec.source_id,
                snapshot_date=contract_snapshot,
                schema_version=silver_spec.schema_version,
                date_order=date_order,
            ),
            artifacts["contracts_snapshot_state"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        process_rows = routing.loc[routing["dataset"] == "processes"].to_dict(
            orient="records"
        )

        # The raw process snapshot is too wide for an in-memory GROUP BY ALL on
        # typical 16 GB developer machines. Stage once, aggregate only a narrow
        # row fingerprint, then recover one representative payload per fingerprint.
        work_dir = (temp_directory or silver_dir / ".duckdb_tmp") / "m2_10"
        work_dir.mkdir(parents=True, exist_ok=True)
        process_stage = work_dir / "processes_stage.parquet"
        duplicate_hashes = work_dir / "processes_duplicate_hashes.parquet"
        duplicate_representatives = work_dir / "processes_duplicate_representatives.parquet"

        print("[10] processes: staging raw payloads (streaming CSV -> Parquet)...")
        _copy_query(
            con,
            _process_stage_query(processes_source, process_columns),
            process_stage,
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=True,
        )
        print("[10] processes: finding duplicate fingerprints (narrow aggregate)...")
        _copy_query(
            con,
            _process_duplicate_hashes_query(process_stage),
            duplicate_hashes,
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=True,
        )
        print("[10] processes: resolving candidate duplicates by exact raw equality...")
        _copy_query(
            con,
            _process_duplicate_representatives_query(
                process_stage,
                duplicate_hashes,
                [normalize_name(column) for column in process_columns],
            ),
            duplicate_representatives,
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=True,
        )
        print("[10] processes: materializing typed unique payloads...")
        _copy_query(
            con,
            _process_versions_from_stage_query(
                process_stage,
                duplicate_hashes,
                duplicate_representatives,
                process_rows,
                source_id=processes_spec.source_id,
                snapshot_date=process_snapshot,
                schema_version=silver_spec.schema_version,
                date_order=date_order,
            ),
            artifacts["process_versions"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )
        process_stage.unlink(missing_ok=True)
        duplicate_hashes.unlink(missing_ok=True)
        duplicate_representatives.unlink(missing_ok=True)
        _copy_query(
            con,
            _process_identity_query(
                artifacts["process_versions"],
                source_id=processes_spec.source_id,
                snapshot_date=process_snapshot,
                schema_version=silver_spec.schema_version,
            ),
            artifacts["processes"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )
        _copy_query(
            con,
            _links_query(
                artifacts["contracts"],
                artifacts["processes"],
                schema_version=silver_spec.schema_version,
            ),
            artifacts["contract_process_links"],
            compression=silver_spec.compression,
            row_group_size=silver_spec.row_group_size,
            overwrite=overwrite,
        )

        conversion_audit = _conversion_audit(con, artifacts, routing)
        validation = _validate_outputs(
            con,
            artifacts,
            routing,
            reports_root=reports_root,
            spec=silver_spec,
        )
    finally:
        con.close()

    write_report(
        conversion_audit, reports_root / "silver" / "10_type_conversion_audit.parquet"
    )
    write_report(validation, reports_root / "silver" / "10_validation.parquet")

    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "silver_contracts_processes.json"
    manifest = _manifest_payload(
        artifacts=artifacts,
        routing=routing,
        conversion_audit=conversion_audit,
        validation=validation,
        contracts_path=contracts_path,
        processes_path=processes_path,
        spec=silver_spec,
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    return SilverBuildResult(
        artifacts=artifacts,
        routing=routing,
        conversion_audit=conversion_audit,
        validation=validation,
        manifest_path=manifest_path,
    )
