from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name, resolve_normalized_names
from argos.common.sql import (
    clean_text_expr,
    csv_source,
    quote_identifier,
    timestamp_expr,
    timestamp_format_expr,
)


def discover_date_columns(columns: list[str]) -> list[str]:
    """Return source columns whose names are plausibly temporal.

    ``vigencia`` is intentionally not a generic token: SECOP contains fields such
    as ``Saldo Vigencia`` that are monetary rather than timestamps.
    """
    tokens = ("fecha", "date", "timestamp")
    return [column for column in columns if any(token in normalize_name(column) for token in tokens)]


def audit_temporal_dataset(
    dataset: str,
    path: Path,
    *,
    sample_size: int = 100_000,
    date_order: str = "mdy",
    plausible_year_min: int = 2000,
    plausible_year_max: int = 2100,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Audit timestamp coverage, parseability and broad calendar plausibility."""
    con = connect(temp_directory=temp_directory)

    try:
        source = csv_source(path, sample_size=sample_size, all_varchar=True)
        schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
        date_columns = discover_date_columns(schema["column_name"].tolist())

        if not date_columns:
            return pd.DataFrame(columns=["dataset", "column"])

        parsed_selects: list[str] = []
        expressions = ["COUNT(*) AS __rows"]
        for idx, column in enumerate(date_columns):
            raw_text = clean_text_expr(column)
            parsed = timestamp_expr(column, date_order=date_order)
            parsed_selects += [
                f"{raw_text} AS c{idx}__raw",
                f"{parsed} AS c{idx}__ts",
            ]
            expressions += [
                f"COUNT(*) FILTER (WHERE c{idx}__raw IS NOT NULL) AS c{idx}__raw_nonnull",
                f"COUNT(*) FILTER (WHERE c{idx}__raw IS NOT NULL AND c{idx}__ts IS NOT NULL) "
                f"AS c{idx}__parsed",
                f"COUNT(*) FILTER (WHERE c{idx}__raw IS NOT NULL AND c{idx}__ts IS NULL) "
                f"AS c{idx}__unparsed",
                f"COUNT(*) FILTER (WHERE c{idx}__ts IS NOT NULL "
                f"AND YEAR(c{idx}__ts) BETWEEN {int(plausible_year_min)} "
                f"AND {int(plausible_year_max)}) AS c{idx}__plausible",
                f"MIN(c{idx}__ts) FILTER (WHERE c{idx}__ts IS NOT NULL "
                f"AND YEAR(c{idx}__ts) BETWEEN {int(plausible_year_min)} "
                f"AND {int(plausible_year_max)}) AS c{idx}__min",
                f"MAX(c{idx}__ts) FILTER (WHERE c{idx}__ts IS NOT NULL "
                f"AND YEAR(c{idx}__ts) BETWEEN {int(plausible_year_min)} "
                f"AND {int(plausible_year_max)}) AS c{idx}__max",
                f"MIN(c{idx}__ts) AS c{idx}__raw_min",
                f"MAX(c{idx}__ts) AS c{idx}__raw_max",
            ]

        result = con.execute(
            "WITH parsed AS ("
            f"SELECT {', '.join(parsed_selects)} FROM {source}"
            ") "
            f"SELECT {', '.join(expressions)} FROM parsed"
        ).fetchdf().iloc[0]
        rows = int(result["__rows"])

        records: list[dict[str, object]] = []
        for idx, column in enumerate(date_columns):
            raw_nonnull = int(result[f"c{idx}__raw_nonnull"])
            parsed_count = int(result[f"c{idx}__parsed"])
            unparsed_count = int(result[f"c{idx}__unparsed"])
            plausible_count = int(result[f"c{idx}__plausible"])

            records.append(
                {
                    "dataset": dataset,
                    "column": column,
                    "normalized_column": normalize_name(column),
                    "row_count": rows,
                    "raw_nonnull_count": raw_nonnull,
                    "coverage": raw_nonnull / rows if rows else None,
                    "parsed_count": parsed_count,
                    "unparsed_count": unparsed_count,
                    "parse_success_rate_nonnull": (
                        parsed_count / raw_nonnull if raw_nonnull else None
                    ),
                    "plausible_parsed_count": plausible_count,
                    "plausible_rate_parsed": (
                        plausible_count / parsed_count if parsed_count else None
                    ),
                    "min_timestamp": result[f"c{idx}__min"],
                    "max_timestamp": result[f"c{idx}__max"],
                    "raw_min_timestamp": result[f"c{idx}__raw_min"],
                    "raw_max_timestamp": result[f"c{idx}__raw_max"],
                    "date_order": date_order,
                    "plausible_year_min": int(plausible_year_min),
                    "plausible_year_max": int(plausible_year_max),
                }
            )

        return pd.DataFrame.from_records(records)
    finally:
        con.close()


def audit_all_temporal(
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    date_order: str = "mdy",
    plausible_year_min: int = 2000,
    plausible_year_max: int = 2100,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    frames = [
        audit_temporal_dataset(
            dataset,
            path,
            sample_size=sample_size,
            date_order=date_order,
            plausible_year_min=plausible_year_min,
            plausible_year_max=plausible_year_max,
            temp_directory=temp_directory,
        )
        for dataset, path in files.items()
    ]
    non_empty = [frame for frame in frames if not frame.empty]
    return pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()


def audit_order_rule(
    dataset: str,
    path: Path,
    earlier_column: str,
    later_column: str,
    *,
    sample_size: int = 100_000,
    date_order: str = "mdy",
    temp_directory: Path | None = None,
) -> dict[str, object]:
    """Audit ``earlier <= later`` using normalized source names safely."""
    con = connect(temp_directory=temp_directory)

    try:
        source = csv_source(path, sample_size=sample_size, all_varchar=True)
        schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
        columns = schema["column_name"].tolist()

        resolved, missing, ambiguous = resolve_normalized_names(
            columns,
            [earlier_column, later_column],
        )

        rule = f"{earlier_column} <= {later_column}"

        if missing:
            return {
                "dataset": dataset,
                "rule": rule,
                "status": "missing_columns",
                "missing_columns": missing,
            }

        if ambiguous:
            return {
                "dataset": dataset,
                "rule": rule,
                "status": "ambiguous_columns",
                "ambiguous_columns": {
                    key: list(values) for key, values in ambiguous.items()
                },
            }

        early_raw = resolved[normalize_name(earlier_column)]
        late_raw = resolved[normalize_name(later_column)]
        early = timestamp_expr(early_raw, date_order=date_order)
        late = timestamp_expr(late_raw, date_order=date_order)

        query = f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE {early} IS NOT NULL
                      AND {late} IS NOT NULL
                ) AS comparable_rows,
                COUNT(*) FILTER (
                    WHERE {early} IS NOT NULL
                      AND {late} IS NOT NULL
                      AND {early} > {late}
                ) AS failures
            FROM {source}
        """

        result = con.execute(query).fetchdf().iloc[0]
        comparable = int(result["comparable_rows"])
        failures = int(result["failures"])

        return {
            "dataset": dataset,
            "rule": rule,
            "status": "analyzed",
            "earlier_raw_column": early_raw,
            "later_raw_column": late_raw,
            "comparable_rows": comparable,
            "failures": failures,
            "failure_rate": failures / comparable if comparable else None,
        }
    finally:
        con.close()


def temporal_format_distribution(
    dataset: str,
    path: Path,
    column: str,
    *,
    sample_size: int = 100_000,
    date_order: str = "mdy",
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Count which explicit parser format is used by one temporal column."""
    con = connect(temp_directory=temp_directory)

    try:
        source = csv_source(path, sample_size=sample_size, all_varchar=True)
        schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
        resolved, missing, ambiguous = resolve_normalized_names(
            schema["column_name"].tolist(),
            [column],
        )
        normalized = normalize_name(column)
        if missing:
            raise KeyError(f"Missing temporal column {normalized!r} in dataset {dataset!r}")
        if ambiguous:
            raise ValueError(
                f"Ambiguous temporal column {normalized!r}: {ambiguous[normalized]}"
            )

        raw_column = resolved[normalized]
        raw_text = clean_text_expr(raw_column)
        format_expr = timestamp_format_expr(raw_column, date_order=date_order)
        query = f"""
            SELECT
                {format_expr} AS parse_format,
                COUNT(*) AS rows
            FROM {source}
            WHERE {raw_text} IS NOT NULL
            GROUP BY 1
            ORDER BY rows DESC, parse_format
        """
        result = con.execute(query).fetchdf()
        result.insert(0, "normalized_column", normalized)
        result.insert(0, "column", raw_column)
        result.insert(0, "dataset", dataset)
        return result
    finally:
        con.close()


def temporal_parse_failures(
    dataset: str,
    path: Path,
    column: str,
    *,
    sample_size: int = 100_000,
    date_order: str = "mdy",
    limit: int = 25,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Return frequent non-null raw values that the explicit parser cannot parse."""
    con = connect(temp_directory=temp_directory)

    try:
        source = csv_source(path, sample_size=sample_size, all_varchar=True)
        schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
        resolved, missing, ambiguous = resolve_normalized_names(
            schema["column_name"].tolist(),
            [column],
        )
        normalized = normalize_name(column)
        if missing:
            raise KeyError(f"Missing temporal column {normalized!r} in dataset {dataset!r}")
        if ambiguous:
            raise ValueError(
                f"Ambiguous temporal column {normalized!r}: {ambiguous[normalized]}"
            )

        raw_column = resolved[normalized]
        raw_text = clean_text_expr(raw_column)
        parsed = timestamp_expr(raw_column, date_order=date_order)
        query = f"""
            SELECT
                {raw_text} AS raw_value,
                COUNT(*) AS rows
            FROM {source}
            WHERE {raw_text} IS NOT NULL
              AND {parsed} IS NULL
            GROUP BY 1
            ORDER BY rows DESC, raw_value
            LIMIT {int(limit)}
        """
        result = con.execute(query).fetchdf()
        result.insert(0, "normalized_column", normalized)
        result.insert(0, "column", raw_column)
        result.insert(0, "dataset", dataset)
        return result
    finally:
        con.close()
