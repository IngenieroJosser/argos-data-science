from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name, normalized_groups
from argos.common.sql import (
    clean_text_expr,
    csv_source,
    quote_identifier,
    sql_string,
    timestamp_expr,
)


def _mapping(con, path: Path, sample_size: int) -> dict[str, str]:
    """Return only unambiguous normalized -> physical column mappings."""
    source = csv_source(path, sample_size=sample_size, all_varchar=True)
    schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
    groups = normalized_groups(schema["column_name"].tolist())
    return {
        normalized: originals[0]
        for normalized, originals in groups.items()
        if len(originals) == 1
    }


def _type_filter_sql(
    event_type_expr: str,
    included_addition_types: tuple[str, ...] | None,
) -> str:
    if not included_addition_types:
        return "TRUE"
    values = ", ".join(sql_string(value) for value in included_addition_types)
    return f"{event_type_expr} IN ({values})"


def analyze_addition_target_feasibility(
    contracts_path: Path,
    additions_path: Path,
    *,
    contract_id_column: str = "id_contrato",
    t0_column: str = "fecha_de_firma",
    addition_contract_id_column: str = "id_contrato",
    addition_event_column: str = "fecharegistro",
    addition_type_column: str | None = "tipo",
    included_addition_types: tuple[str, ...] | None = None,
    horizons: tuple[int, ...] = (30, 90, 180, 365),
    label_cutoff: str | None = None,
    date_order: str = "mdy",
    plausible_t0_year_min: int = 2015,
    plausible_t0_year_max: int = 2100,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assess whether ``addition within horizon`` can be labeled safely.

    Key safeguards:

    - timestamps use ARGOS' explicit SECOP parser rather than CSV type inference;
    - contracts with no parsable t0 are excluded and quantified;
    - event rows are deduplicated on ``(contract_id, event_at, type)`` before
      labeling, so repeated source rows cannot inflate event diagnostics;
    - only events strictly after t0 count as future outcomes;
    - negatives exist only when the complete horizon is observable;
    - the default label cutoff is the latest parsable *included* addition event.
    """
    con = connect(temp_directory=temp_directory)

    try:
        cmap = _mapping(con, contracts_path, sample_size)
        amap = _mapping(con, additions_path, sample_size)

        contract_id_column = normalize_name(contract_id_column)
        t0_column = normalize_name(t0_column)
        addition_contract_id_column = normalize_name(addition_contract_id_column)
        addition_event_column = normalize_name(addition_event_column)
        normalized_type = normalize_name(addition_type_column) if addition_type_column else None

        required_contract = [contract_id_column, t0_column]
        required_addition = [addition_contract_id_column, addition_event_column]
        missing = [f"contracts.{name}" for name in required_contract if name not in cmap]
        missing += [f"additions.{name}" for name in required_addition if name not in amap]
        if normalized_type and normalized_type not in amap:
            missing.append(f"additions.{normalized_type}")
        if missing:
            raise KeyError(
                "Target feasibility cannot run; missing normalized columns: "
                f"{missing}"
            )

        cid = cmap[contract_id_column]
        t0_raw_column = cmap[t0_column]
        aid = amap[addition_contract_id_column]
        event_raw_column = amap[addition_event_column]
        type_raw_column = amap[normalized_type] if normalized_type else None

        csrc = csv_source(contracts_path, sample_size=sample_size, all_varchar=True)
        asrc = csv_source(additions_path, sample_size=sample_size, all_varchar=True)
        c_id = quote_identifier(cid)
        a_id = quote_identifier(aid)
        t0_raw_text = clean_text_expr(t0_raw_column)
        event_raw_text = clean_text_expr(event_raw_column)
        t0 = timestamp_expr(t0_raw_column, date_order=date_order)
        event = timestamp_expr(event_raw_column, date_order=date_order)

        if type_raw_column:
            event_type = clean_text_expr(type_raw_column)
        else:
            event_type = "CAST(NULL AS VARCHAR)"
        type_filter = _type_filter_sql(event_type, included_addition_types)

        if label_cutoff is None:
            cutoff = con.execute(
                f"SELECT MAX({event}) FROM {asrc} WHERE {type_filter}"
            ).fetchone()[0]
            if cutoff is None:
                raise ValueError(
                    "No parsable included addition event timestamp is available "
                    "to define label_cutoff."
                )
            cutoff_sql = f"TIMESTAMP {sql_string(str(cutoff))}"
        else:
            cutoff_sql = f"TRY_CAST({sql_string(label_cutoff)} AS TIMESTAMP)"

        base_ctes = f"""
        WITH contracts_raw AS (
            SELECT
                CAST({c_id} AS VARCHAR) AS contract_id,
                {t0_raw_text} AS t0_raw_text,
                {t0} AS t0
            FROM {csrc}
            WHERE {c_id} IS NOT NULL
        ), contract_ids AS (
            SELECT
                contract_id,
                COUNT(*) AS source_rows,
                COUNT(*) FILTER (WHERE t0_raw_text IS NOT NULL) AS raw_t0_rows,
                COUNT(*) FILTER (WHERE t0 IS NOT NULL) AS parsed_t0_rows,
                COUNT(DISTINCT t0) FILTER (WHERE t0 IS NOT NULL) AS distinct_t0_count,
                MIN(t0) AS t0
            FROM contracts_raw
            GROUP BY contract_id
        ), contracts AS (
            SELECT contract_id, t0
            FROM contract_ids
            WHERE distinct_t0_count = 1 AND t0 IS NOT NULL
        ), additions_raw AS (
            SELECT
                CAST({a_id} AS VARCHAR) AS contract_id,
                {event_raw_text} AS event_raw_text,
                {event} AS event_at,
                {event_type} AS event_type
            FROM {asrc}
            WHERE {a_id} IS NOT NULL
              AND {type_filter}
        ), additions AS (
            SELECT DISTINCT
                contract_id,
                event_at,
                event_type
            FROM additions_raw
            WHERE event_at IS NOT NULL
        ), event_rollup AS (
            SELECT
                c.contract_id,
                c.t0,
                MIN(a.event_at) FILTER (WHERE a.event_at > c.t0) AS first_future_addition_at,
                COUNT(*) FILTER (
                    WHERE a.event_at IS NOT NULL AND a.event_at <= c.t0
                ) AS additions_at_or_before_t0
            FROM contracts c
            LEFT JOIN additions a USING (contract_id)
            GROUP BY c.contract_id, c.t0
        )
        """

        diagnostics = con.execute(
            base_ctes
            + f"""
            SELECT
                (SELECT COUNT(*) FROM {csrc}) AS contract_source_rows,
                (SELECT COUNT(*) FROM contract_ids) AS distinct_contract_ids,
                (
                    SELECT COUNT(*) FROM contract_ids
                    WHERE raw_t0_rows = 0
                ) AS contract_ids_raw_missing_t0,
                (
                    SELECT COUNT(*) FROM contract_ids
                    WHERE raw_t0_rows > 0 AND parsed_t0_rows = 0
                ) AS contract_ids_unparsable_t0,
                (
                    SELECT COUNT(*) FROM contract_ids
                    WHERE distinct_t0_count = 0
                ) AS contract_ids_without_parsed_t0,
                (
                    SELECT COUNT(*) FROM contract_ids
                    WHERE distinct_t0_count > 1
                ) AS contract_ids_ambiguous_t0,
                (SELECT COUNT(*) FROM contracts) AS unambiguous_contracts_with_t0,
                (
                    SELECT COUNT(*) FROM contracts
                    WHERE YEAR(t0) BETWEEN {int(plausible_t0_year_min)}
                        AND {int(plausible_t0_year_max)}
                ) AS plausible_contracts_with_t0,
                (
                    SELECT COUNT(*) FROM contracts WHERE t0 > {cutoff_sql}
                ) AS contracts_t0_after_label_cutoff,
                (SELECT COUNT(*) FROM {asrc}) AS addition_source_rows,
                (SELECT COUNT(*) FROM additions_raw) AS included_addition_source_rows,
                (
                    SELECT COUNT(*) FROM additions_raw
                    WHERE event_raw_text IS NOT NULL
                ) AS included_addition_event_raw_nonnull_rows,
                (
                    SELECT COUNT(*) FROM additions_raw
                    WHERE event_raw_text IS NOT NULL AND event_at IS NULL
                ) AS additions_unparsable_event_time,
                (
                    SELECT COUNT(*) FROM additions_raw WHERE event_at IS NOT NULL
                ) AS parsed_addition_rows,
                (SELECT COUNT(*) FROM additions) AS unique_addition_events,
                (
                    SELECT COUNT(*) FROM additions_raw WHERE event_at IS NOT NULL
                ) - (SELECT COUNT(*) FROM additions) AS duplicate_addition_event_rows,
                (
                    SELECT SUM(additions_at_or_before_t0) FROM event_rollup
                ) AS unique_additions_at_or_before_t0,
                {cutoff_sql} AS label_cutoff
            """
        ).fetchdf()

        diag_row = diagnostics.iloc[0]
        raw_t0_contracts = (
            int(diag_row["unambiguous_contracts_with_t0"])
            + int(diag_row["contract_ids_unparsable_t0"])
        )
        parsed_t0_contracts = int(diag_row["unambiguous_contracts_with_t0"])
        diagnostics["t0_parse_success_rate_nonnull_contracts"] = (
            parsed_t0_contracts / raw_t0_contracts if raw_t0_contracts else None
        )
        diagnostics["t0_plausible_rate_parsed_contracts"] = (
            int(diag_row["plausible_contracts_with_t0"]) / parsed_t0_contracts
            if parsed_t0_contracts
            else None
        )
        parsed_addition_rows = int(diag_row["parsed_addition_rows"])
        event_raw_nonnull_rows = int(
            diag_row["included_addition_event_raw_nonnull_rows"]
        )
        diagnostics["addition_event_parse_success_rate_nonnull"] = (
            parsed_addition_rows / event_raw_nonnull_rows
            if event_raw_nonnull_rows
            else None
        )
        diagnostics["addition_event_duplicate_rate"] = (
            int(diag_row["duplicate_addition_event_rows"]) / parsed_addition_rows
            if parsed_addition_rows
            else None
        )
        diagnostics["event_deduplication_key"] = "contract_id+event_at+event_type"
        diagnostics["event_scope"] = (
            "all_rows_in_additions_source"
            if not included_addition_types
            else "configured_addition_types"
        )

        horizon_records: list[dict[str, object]] = []
        for days in horizons:
            summary = con.execute(
                base_ctes
                + f"""
                SELECT
                    COUNT(*) AS population,
                    COUNT(*) FILTER (
                        WHERE t0 + INTERVAL '{int(days)} days' <= {cutoff_sql}
                    ) AS eligible,
                    COUNT(*) FILTER (
                        WHERE t0 + INTERVAL '{int(days)} days' <= {cutoff_sql}
                          AND first_future_addition_at IS NOT NULL
                          AND first_future_addition_at <=
                              t0 + INTERVAL '{int(days)} days'
                    ) AS positives,
                    COUNT(*) FILTER (
                        WHERE t0 + INTERVAL '{int(days)} days' <= {cutoff_sql}
                          AND (
                              first_future_addition_at IS NULL
                              OR first_future_addition_at >
                                  t0 + INTERVAL '{int(days)} days'
                          )
                    ) AS negatives
                FROM event_rollup
                """
            ).fetchdf().iloc[0]
            population = int(summary["population"])
            eligible = int(summary["eligible"])
            positives = int(summary["positives"])
            negatives = int(summary["negatives"])
            horizon_records.append(
                {
                    "horizon_days": days,
                    "population": population,
                    "eligible": eligible,
                    "censored": population - eligible,
                    "positives": positives,
                    "negatives": negatives,
                    "prevalence": positives / eligible if eligible else None,
                    "label_cutoff": diagnostics.iloc[0]["label_cutoff"],
                }
            )

        return pd.DataFrame.from_records(horizon_records), diagnostics
    finally:
        con.close()


def addition_target_by_year(
    contracts_path: Path,
    additions_path: Path,
    *,
    horizon_days: int = 180,
    contract_id_column: str = "id_contrato",
    t0_column: str = "fecha_de_firma",
    addition_contract_id_column: str = "id_contrato",
    addition_event_column: str = "fecharegistro",
    addition_type_column: str | None = "tipo",
    included_addition_types: tuple[str, ...] | None = None,
    date_order: str = "mdy",
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Return 180-day (or configured) target prevalence by parsed t0 year."""
    con = connect(temp_directory=temp_directory)

    try:
        cmap = _mapping(con, contracts_path, sample_size)
        amap = _mapping(con, additions_path, sample_size)

        contract_id_column = normalize_name(contract_id_column)
        t0_column = normalize_name(t0_column)
        addition_contract_id_column = normalize_name(addition_contract_id_column)
        addition_event_column = normalize_name(addition_event_column)
        normalized_type = normalize_name(addition_type_column) if addition_type_column else None

        cid = cmap[contract_id_column]
        t0_raw = cmap[t0_column]
        aid = amap[addition_contract_id_column]
        event_raw = amap[addition_event_column]
        type_raw = amap[normalized_type] if normalized_type else None

        csrc = csv_source(contracts_path, sample_size=sample_size, all_varchar=True)
        asrc = csv_source(additions_path, sample_size=sample_size, all_varchar=True)
        t0 = timestamp_expr(t0_raw, date_order=date_order)
        event = timestamp_expr(event_raw, date_order=date_order)
        event_type = clean_text_expr(type_raw) if type_raw else "CAST(NULL AS VARCHAR)"
        type_filter = _type_filter_sql(event_type, included_addition_types)

        cutoff = con.execute(
            f"SELECT MAX({event}) FROM {asrc} WHERE {type_filter}"
        ).fetchone()[0]
        if cutoff is None:
            raise ValueError("No parsable included addition timestamp.")

        qcid = quote_identifier(cid)
        qaid = quote_identifier(aid)
        cutoff_sql = f"TIMESTAMP {sql_string(str(cutoff))}"

        query = f"""
        WITH cr AS (
            SELECT CAST({qcid} AS VARCHAR) AS contract_id, {t0} AS t0
            FROM {csrc}
            WHERE {qcid} IS NOT NULL
        ), cids AS (
            SELECT
                contract_id,
                COUNT(DISTINCT t0) FILTER (WHERE t0 IS NOT NULL) AS n_t0,
                MIN(t0) AS t0
            FROM cr
            GROUP BY contract_id
        ), c AS (
            SELECT contract_id, t0
            FROM cids
            WHERE n_t0 = 1 AND t0 IS NOT NULL
        ), ar AS (
            SELECT
                CAST({qaid} AS VARCHAR) AS contract_id,
                {event} AS event_at,
                {event_type} AS event_type
            FROM {asrc}
            WHERE {qaid} IS NOT NULL
              AND {type_filter}
        ), a AS (
            SELECT DISTINCT contract_id, event_at, event_type
            FROM ar
            WHERE event_at IS NOT NULL
        ), r AS (
            SELECT
                c.contract_id,
                c.t0,
                MIN(a.event_at) FILTER (WHERE a.event_at > c.t0) AS first_event
            FROM c
            LEFT JOIN a USING (contract_id)
            GROUP BY c.contract_id, c.t0
        )
        SELECT
            YEAR(t0) AS t0_year,
            COUNT(*) FILTER (
                WHERE t0 + INTERVAL '{int(horizon_days)} days' <= {cutoff_sql}
            ) AS eligible,
            COUNT(*) FILTER (
                WHERE t0 + INTERVAL '{int(horizon_days)} days' <= {cutoff_sql}
                  AND first_event IS NOT NULL
                  AND first_event <= t0 + INTERVAL '{int(horizon_days)} days'
            ) AS positives
        FROM r
        GROUP BY YEAR(t0)
        ORDER BY t0_year
        """
        result = con.execute(query).fetchdf()
        result["prevalence"] = result["positives"] / result["eligible"].replace(0, pd.NA)
        return result
    finally:
        con.close()


def addition_event_type_profile(
    additions_path: Path,
    *,
    addition_contract_id_column: str = "id_contrato",
    addition_event_column: str = "fecharegistro",
    addition_type_column: str = "tipo",
    date_order: str = "mdy",
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Profile ``Tipo`` values in Adiciones without deciding their semantics."""
    con = connect(temp_directory=temp_directory)

    try:
        amap = _mapping(con, additions_path, sample_size)
        contract_key = normalize_name(addition_contract_id_column)
        event_key = normalize_name(addition_event_column)
        type_key = normalize_name(addition_type_column)
        missing = [
            key for key in (contract_key, event_key, type_key)
            if key not in amap
        ]
        if missing:
            raise KeyError(f"Missing Adiciones columns for event-type profile: {missing}")

        source = csv_source(additions_path, sample_size=sample_size, all_varchar=True)
        contract_id = quote_identifier(amap[contract_key])
        event_at = timestamp_expr(amap[event_key], date_order=date_order)
        event_type = clean_text_expr(amap[type_key])

        return con.execute(
            f"""
            SELECT
                COALESCE({event_type}, '<NULL>') AS event_type,
                COUNT(*) AS source_rows,
                COUNT(DISTINCT CAST({contract_id} AS VARCHAR)) AS distinct_contracts,
                COUNT(*) FILTER (WHERE {event_at} IS NOT NULL) AS parsed_event_rows,
                MIN({event_at}) AS min_event_at,
                MAX({event_at}) AS max_event_at
            FROM {source}
            GROUP BY 1
            ORDER BY source_rows DESC, event_type
            """
        ).fetchdf()
    finally:
        con.close()
