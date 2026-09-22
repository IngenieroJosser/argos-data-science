\
from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalized_mapping
from argos.common.sql import csv_source, quote_identifier, timestamp_expr


def _mapping(con, path: Path, sample_size: int) -> dict[str, str]:
    source = csv_source(path, sample_size=sample_size, all_varchar=True)
    schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
    return normalized_mapping(schema["column_name"].tolist())


def analyze_addition_target_feasibility(
    contracts_path: Path,
    additions_path: Path,
    *,
    contract_id_column: str = "id_contrato",
    t0_column: str = "fecha_de_firma",
    addition_contract_id_column: str = "id_contrato",
    addition_event_column: str = "fecharegistro",
    horizons: tuple[int, ...] = (30, 90, 180, 365),
    label_cutoff: str | None = None,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assess whether an addition-within-horizon target can be labeled safely.

    Conservative behavior:
    - contract IDs with multiple distinct t0 values are excluded from the provisional
      labeling population and reported as ambiguous;
    - only addition timestamps strictly after t0 count as future events;
    - negatives exist only when the full horizon is observable before label_cutoff;
    - default label_cutoff is max parsable addition event time, not extraction date.
    """
    con = connect(temp_directory=temp_directory)
    cmap = _mapping(con, contracts_path, sample_size)
    amap = _mapping(con, additions_path, sample_size)

    required_contract = [contract_id_column, t0_column]
    required_addition = [addition_contract_id_column, addition_event_column]
    missing = [f"contracts.{c}" for c in required_contract if c not in cmap]
    missing += [f"additions.{c}" for c in required_addition if c not in amap]
    if missing:
        raise KeyError(f"Target feasibility cannot run; missing normalized columns: {missing}")

    cid = cmap[contract_id_column]
    t0_raw = cmap[t0_column]
    aid = amap[addition_contract_id_column]
    event_raw = amap[addition_event_column]
    csrc = csv_source(contracts_path, sample_size=sample_size, all_varchar=True)
    asrc = csv_source(additions_path, sample_size=sample_size, all_varchar=True)
    c_id = quote_identifier(cid)
    a_id = quote_identifier(aid)
    t0 = timestamp_expr(t0_raw)
    event = timestamp_expr(event_raw)

    if label_cutoff is None:
        cutoff = con.execute(f"SELECT MAX({event}) FROM {asrc}").fetchone()[0]
        if cutoff is None:
            raise ValueError("No parsable addition event timestamp available to define label_cutoff.")
        cutoff_sql = f"TIMESTAMP '{cutoff}'"
    else:
        cutoff_sql = f"TRY_CAST('{label_cutoff.replace("'", "''")}' AS TIMESTAMP)"

    # One row per unambiguous contract ID. A contract with several distinct t0 values
    # is excluded instead of choosing an arbitrary timestamp.
    base_ctes = f"""
    WITH contracts_raw AS (
        SELECT CAST({c_id} AS VARCHAR) AS contract_id, {t0} AS t0
        FROM {csrc}
        WHERE {c_id} IS NOT NULL
    ), contract_ids AS (
        SELECT
            contract_id,
            COUNT(*) AS source_rows,
            COUNT(DISTINCT t0) FILTER (WHERE t0 IS NOT NULL) AS distinct_t0_count,
            MIN(t0) AS t0
        FROM contracts_raw
        GROUP BY contract_id
    ), contracts AS (
        SELECT contract_id, t0
        FROM contract_ids
        WHERE distinct_t0_count = 1 AND t0 IS NOT NULL
    ), additions AS (
        SELECT CAST({a_id} AS VARCHAR) AS contract_id, {event} AS event_at
        FROM {asrc}
        WHERE {a_id} IS NOT NULL
    ), event_rollup AS (
        SELECT
            c.contract_id,
            c.t0,
            MIN(a.event_at) FILTER (WHERE a.event_at > c.t0) AS first_future_addition_at,
            COUNT(*) FILTER (WHERE a.event_at IS NOT NULL AND a.event_at <= c.t0) AS additions_at_or_before_t0
        FROM contracts c
        LEFT JOIN additions a USING (contract_id)
        GROUP BY c.contract_id, c.t0
    )
    """

    diagnostics = con.execute(base_ctes + f"""
    SELECT
        (SELECT COUNT(*) FROM {csrc}) AS contract_source_rows,
        (SELECT COUNT(*) FROM contract_ids) AS distinct_contract_ids,
        (SELECT COUNT(*) FROM contract_ids WHERE distinct_t0_count = 0) AS contract_ids_missing_t0,
        (SELECT COUNT(*) FROM contract_ids WHERE distinct_t0_count > 1) AS contract_ids_ambiguous_t0,
        (SELECT COUNT(*) FROM contracts) AS unambiguous_contracts_with_t0,
        (SELECT COUNT(*) FROM {asrc}) AS addition_source_rows,
        (SELECT COUNT(*) FROM additions WHERE event_at IS NULL) AS additions_unparsable_event_time,
        (SELECT SUM(additions_at_or_before_t0) FROM event_rollup) AS additions_at_or_before_t0,
        {cutoff_sql} AS label_cutoff
    """).fetchdf()

    horizon_records: list[dict[str, object]] = []
    for days in horizons:
        summary = con.execute(base_ctes + f"""
        SELECT
            COUNT(*) AS population,
            COUNT(*) FILTER (WHERE t0 + INTERVAL '{int(days)} days' <= {cutoff_sql}) AS eligible,
            COUNT(*) FILTER (
                WHERE t0 + INTERVAL '{int(days)} days' <= {cutoff_sql}
                  AND first_future_addition_at IS NOT NULL
                  AND first_future_addition_at <= t0 + INTERVAL '{int(days)} days'
            ) AS positives,
            COUNT(*) FILTER (
                WHERE t0 + INTERVAL '{int(days)} days' <= {cutoff_sql}
                  AND (first_future_addition_at IS NULL OR first_future_addition_at > t0 + INTERVAL '{int(days)} days')
            ) AS negatives
        FROM event_rollup
        """).fetchdf().iloc[0]
        population = int(summary["population"])
        eligible = int(summary["eligible"])
        positives = int(summary["positives"])
        negatives = int(summary["negatives"])
        horizon_records.append({
            "horizon_days": days,
            "population": population,
            "eligible": eligible,
            "censored": population - eligible,
            "positives": positives,
            "negatives": negatives,
            "prevalence": positives / eligible if eligible else None,
            "label_cutoff": diagnostics.iloc[0]["label_cutoff"],
        })

    return pd.DataFrame.from_records(horizon_records), diagnostics


def addition_target_by_year(
    contracts_path: Path,
    additions_path: Path,
    *,
    horizon_days: int = 180,
    contract_id_column: str = "id_contrato",
    t0_column: str = "fecha_de_firma",
    addition_contract_id_column: str = "id_contrato",
    addition_event_column: str = "fecharegistro",
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Prevalence by t0 year for unambiguous contracts; diagnostic only."""
    con = connect(temp_directory=temp_directory)
    cmap = _mapping(con, contracts_path, sample_size)
    amap = _mapping(con, additions_path, sample_size)
    cid, t0_raw = cmap[contract_id_column], cmap[t0_column]
    aid, event_raw = amap[addition_contract_id_column], amap[addition_event_column]
    csrc = csv_source(contracts_path, sample_size=sample_size, all_varchar=True)
    asrc = csv_source(additions_path, sample_size=sample_size, all_varchar=True)
    t0 = timestamp_expr(t0_raw)
    event = timestamp_expr(event_raw)
    cutoff = con.execute(f"SELECT MAX({event}) FROM {asrc}").fetchone()[0]
    if cutoff is None:
        raise ValueError("No parsable addition timestamp.")

    qcid = quote_identifier(cid)
    qaid = quote_identifier(aid)
    query = f"""
    WITH cr AS (
        SELECT CAST({qcid} AS VARCHAR) contract_id, {t0} t0
        FROM {csrc}
        WHERE {qcid} IS NOT NULL
    ), cids AS (
        SELECT contract_id, COUNT(DISTINCT t0) FILTER (WHERE t0 IS NOT NULL) n_t0, MIN(t0) t0
        FROM cr GROUP BY contract_id
    ), c AS (
        SELECT contract_id, t0 FROM cids WHERE n_t0 = 1 AND t0 IS NOT NULL
    ), a AS (
        SELECT CAST({qaid} AS VARCHAR) contract_id, {event} event_at
        FROM {asrc}
        WHERE {qaid} IS NOT NULL
    ), r AS (
        SELECT c.contract_id, c.t0,
               MIN(a.event_at) FILTER (WHERE a.event_at > c.t0) first_event
        FROM c LEFT JOIN a USING(contract_id)
        GROUP BY c.contract_id, c.t0
    )
    SELECT
        YEAR(t0) AS t0_year,
        COUNT(*) FILTER (WHERE t0 + INTERVAL '{int(horizon_days)} days' <= TIMESTAMP '{cutoff}') AS eligible,
        COUNT(*) FILTER (
            WHERE t0 + INTERVAL '{int(horizon_days)} days' <= TIMESTAMP '{cutoff}'
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
