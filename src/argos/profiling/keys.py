\
from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalized_mapping
from argos.common.sql import csv_source, quote_identifier
from argos.config.registry import DatasetSpec


def _columns(con, path: Path, sample_size: int) -> list[str]:
    source = csv_source(path, sample_size=sample_size, all_varchar=True)
    schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
    return schema["column_name"].tolist()


def analyze_candidate_keys(
    dataset: str,
    path: Path,
    spec: DatasetSpec,
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Measure uniqueness/nullness for configured key hypotheses without modifying data."""
    con = connect(temp_directory=temp_directory)
    source = csv_source(path, sample_size=sample_size, all_varchar=True)
    mapping = normalized_mapping(_columns(con, path, sample_size))

    records: list[dict[str, object]] = []
    for candidate in spec.candidate_keys:
        missing = [name for name in candidate if name not in mapping]
        if missing:
            records.append(
                {
                    "dataset": dataset,
                    "candidate_key": "+".join(candidate),
                    "status": "missing_columns",
                    "missing_columns": missing,
                }
            )
            continue

        raw_columns = [mapping[name] for name in candidate]
        quoted = [quote_identifier(name) for name in raw_columns]
        null_predicate = " OR ".join(f"{col} IS NULL" for col in quoted)
        group_expr = ", ".join(quoted)

        query = f"""
        WITH base AS (
            SELECT {group_expr}
            FROM {source}
        ), grouped AS (
            SELECT {group_expr}, COUNT(*) AS n
            FROM base
            WHERE NOT ({null_predicate})
            GROUP BY {group_expr}
        )
        SELECT
            (SELECT COUNT(*) FROM base) AS row_count,
            (SELECT COUNT(*) FROM base WHERE {null_predicate}) AS rows_with_null_key,
            COUNT(*) AS distinct_nonnull_keys,
            COALESCE(SUM(n), 0) AS nonnull_rows,
            COALESCE(SUM(CASE WHEN n > 1 THEN n - 1 ELSE 0 END), 0) AS duplicate_excess_rows,
            COALESCE(MAX(n), 0) AS max_multiplicity
        FROM grouped
        """
        result = con.execute(query).fetchdf().iloc[0]
        row_count = int(result["row_count"])
        distinct = int(result["distinct_nonnull_keys"])
        nonnull_rows = int(result["nonnull_rows"])
        duplicates = int(result["duplicate_excess_rows"])
        records.append(
            {
                "dataset": dataset,
                "candidate_key": "+".join(candidate),
                "raw_columns": raw_columns,
                "status": "analyzed",
                "row_count": row_count,
                "rows_with_null_key": int(result["rows_with_null_key"]),
                "null_key_rate": (int(result["rows_with_null_key"]) / row_count) if row_count else None,
                "distinct_nonnull_keys": distinct,
                "nonnull_rows": nonnull_rows,
                "uniqueness_ratio": (distinct / nonnull_rows) if nonnull_rows else None,
                "duplicate_excess_rows": duplicates,
                "max_multiplicity": int(result["max_multiplicity"]),
                "is_unique_when_nonnull": duplicates == 0 and nonnull_rows > 0,
            }
        )

    return pd.DataFrame.from_records(records)


def analyze_all_candidate_keys(
    files: dict[str, Path],
    specs: dict[str, DatasetSpec],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    frames = [
        analyze_candidate_keys(
            dataset,
            path,
            specs[dataset],
            sample_size=sample_size,
            temp_directory=temp_directory,
        )
        for dataset, path in files.items()
    ]
    return pd.concat(frames, ignore_index=True)
