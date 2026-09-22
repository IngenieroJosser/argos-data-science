\
from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name
from argos.common.sql import csv_source, quote_identifier, timestamp_expr


def discover_date_columns(columns: list[str]) -> list[str]:
    tokens = ("fecha", "date", "timestamp", "vigencia")
    return [c for c in columns if any(t in normalize_name(c) for t in tokens)]


def audit_temporal_dataset(
    dataset: str,
    path: Path,
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    con = connect(temp_directory=temp_directory)
    source = csv_source(path, sample_size=sample_size, all_varchar=True)
    schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
    date_columns = discover_date_columns(schema["column_name"].tolist())
    if not date_columns:
        return pd.DataFrame(columns=["dataset", "column"])

    expressions = ["COUNT(*) AS __rows"]
    for idx, column in enumerate(date_columns):
        q = quote_identifier(column)
        parsed = timestamp_expr(column)
        expressions += [
            f"COUNT(*) FILTER (WHERE {q} IS NOT NULL) AS c{idx}__raw_nonnull",
            f"COUNT(*) FILTER (WHERE {q} IS NOT NULL AND {parsed} IS NOT NULL) AS c{idx}__parsed",
            f"MIN({parsed}) AS c{idx}__min",
            f"MAX({parsed}) AS c{idx}__max",
        ]
    result = con.execute(f"SELECT {', '.join(expressions)} FROM {source}").fetchdf().iloc[0]
    rows = int(result["__rows"])

    records = []
    for idx, column in enumerate(date_columns):
        raw_nonnull = int(result[f"c{idx}__raw_nonnull"])
        parsed = int(result[f"c{idx}__parsed"])
        records.append(
            {
                "dataset": dataset,
                "column": column,
                "normalized_column": normalize_name(column),
                "row_count": rows,
                "raw_nonnull_count": raw_nonnull,
                "coverage": raw_nonnull / rows if rows else None,
                "parsed_count": parsed,
                "parse_success_rate_nonnull": parsed / raw_nonnull if raw_nonnull else None,
                "min_timestamp": result[f"c{idx}__min"],
                "max_timestamp": result[f"c{idx}__max"],
            }
        )
    return pd.DataFrame.from_records(records)


def audit_all_temporal(
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    frames = [
        audit_temporal_dataset(
            dataset,
            path,
            sample_size=sample_size,
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
    temp_directory: Path | None = None,
) -> dict[str, object]:
    """Audit `earlier <= later` using normalized names; return missing status if unavailable."""
    from argos.common.names import normalized_mapping

    con = connect(temp_directory=temp_directory)
    source = csv_source(path, sample_size=sample_size, all_varchar=True)
    schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
    mapping = normalized_mapping(schema["column_name"].tolist())
    if earlier_column not in mapping or later_column not in mapping:
        return {
            "dataset": dataset,
            "rule": f"{earlier_column} <= {later_column}",
            "status": "missing_columns",
        }

    early_raw = mapping[earlier_column]
    late_raw = mapping[later_column]
    early = timestamp_expr(early_raw)
    late = timestamp_expr(late_raw)
    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE {early} IS NOT NULL AND {late} IS NOT NULL) AS comparable_rows,
            COUNT(*) FILTER (WHERE {early} IS NOT NULL AND {late} IS NOT NULL AND {early} > {late}) AS failures
        FROM {source}
    """
    result = con.execute(query).fetchdf().iloc[0]
    comparable = int(result["comparable_rows"])
    failures = int(result["failures"])
    return {
        "dataset": dataset,
        "rule": f"{earlier_column} <= {later_column}",
        "status": "analyzed",
        "comparable_rows": comparable,
        "failures": failures,
        "failure_rate": failures / comparable if comparable else None,
    }
