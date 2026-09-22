from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import (
    normalization_collisions,
    resolve_normalized_names,
)
from argos.common.sql import csv_source, quote_identifier
from argos.config.registry import DatasetSpec


def _columns(con, path: Path, sample_size: int) -> list[str]:
    """Return physical column names without coercing Bronze values."""
    source = csv_source(
        path,
        sample_size=sample_size,
        all_varchar=True,
    )
    schema = con.execute(
        f"DESCRIBE SELECT * FROM {source}"
    ).fetchdf()
    return schema["column_name"].tolist()


def analyze_column_normalization_collisions(
    dataset: str,
    path: Path,
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Report lossy name-normalization collisions in a Bronze schema.

    A collision is a data-modeling finding, not automatically an error. Both
    physical columns are preserved in Bronze and the ambiguity must be resolved
    explicitly before canonical Silver renaming.
    """
    con = connect(temp_directory=temp_directory)

    try:
        columns = _columns(con, path, sample_size)
        collisions = normalization_collisions(columns)

        records = [
            {
                "dataset": dataset,
                "normalized_column": normalized,
                "raw_columns": list(raw_columns),
                "collision_size": len(raw_columns),
                "status": "normalization_collision",
            }
            for normalized, raw_columns in collisions.items()
        ]

        return pd.DataFrame.from_records(
            records,
            columns=[
                "dataset",
                "normalized_column",
                "raw_columns",
                "collision_size",
                "status",
            ],
        )
    finally:
        con.close()


def analyze_all_normalization_collisions(
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Report normalization collisions for every Bronze dataset."""
    frames = [
        analyze_column_normalization_collisions(
            dataset,
            path,
            sample_size=sample_size,
            temp_directory=temp_directory,
        )
        for dataset, path in files.items()
    ]

    non_empty = [frame for frame in frames if not frame.empty]

    if not non_empty:
        return pd.DataFrame(
            columns=[
                "dataset",
                "normalized_column",
                "raw_columns",
                "collision_size",
                "status",
            ]
        )

    return pd.concat(non_empty, ignore_index=True)


def analyze_candidate_keys(
    dataset: str,
    path: Path,
    spec: DatasetSpec,
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Measure uniqueness and nullness for configured key hypotheses.

    Normalized-name collisions are handled only when they affect the requested
    candidate key. An unrelated collision elsewhere in the dataset does not
    block key profiling.
    """
    con = connect(temp_directory=temp_directory)

    try:
        source = csv_source(
            path,
            sample_size=sample_size,
            all_varchar=True,
        )
        columns = _columns(con, path, sample_size)

        records: list[dict[str, object]] = []

        for candidate in spec.candidate_keys:
            resolved, missing, ambiguous = resolve_normalized_names(
                columns,
                candidate,
            )

            candidate_label = "+".join(candidate)

            if missing:
                records.append(
                    {
                        "dataset": dataset,
                        "candidate_key": candidate_label,
                        "status": "missing_columns",
                        "missing_columns": missing,
                        "ambiguous_columns": None,
                    }
                )
                continue

            if ambiguous:
                records.append(
                    {
                        "dataset": dataset,
                        "candidate_key": candidate_label,
                        "status": "ambiguous_columns",
                        "missing_columns": None,
                        "ambiguous_columns": {
                            key: list(values)
                            for key, values in ambiguous.items()
                        },
                    }
                )
                continue

            raw_columns = [resolved[name] for name in candidate]
            quoted = [
                quote_identifier(name)
                for name in raw_columns
            ]
            null_predicate = " OR ".join(
                f"{column} IS NULL"
                for column in quoted
            )
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
                (
                    SELECT COUNT(*)
                    FROM base
                    WHERE {null_predicate}
                ) AS rows_with_null_key,
                COUNT(*) AS distinct_nonnull_keys,
                COALESCE(SUM(n), 0) AS nonnull_rows,
                COALESCE(
                    SUM(
                        CASE
                            WHEN n > 1 THEN n - 1
                            ELSE 0
                        END
                    ),
                    0
                ) AS duplicate_excess_rows,
                COALESCE(MAX(n), 0) AS max_multiplicity
            FROM grouped
            """

            result = con.execute(query).fetchdf().iloc[0]

            row_count = int(result["row_count"])
            distinct = int(result["distinct_nonnull_keys"])
            nonnull_rows = int(result["nonnull_rows"])
            duplicates = int(result["duplicate_excess_rows"])
            null_rows = int(result["rows_with_null_key"])

            records.append(
                {
                    "dataset": dataset,
                    "candidate_key": candidate_label,
                    "raw_columns": raw_columns,
                    "status": "analyzed",
                    "missing_columns": None,
                    "ambiguous_columns": None,
                    "row_count": row_count,
                    "rows_with_null_key": null_rows,
                    "null_key_rate": (
                        null_rows / row_count
                        if row_count
                        else None
                    ),
                    "distinct_nonnull_keys": distinct,
                    "nonnull_rows": nonnull_rows,
                    "uniqueness_ratio": (
                        distinct / nonnull_rows
                        if nonnull_rows
                        else None
                    ),
                    "duplicate_excess_rows": duplicates,
                    "max_multiplicity": int(
                        result["max_multiplicity"]
                    ),
                    "is_unique_when_nonnull": (
                        duplicates == 0
                        and nonnull_rows > 0
                    ),
                }
            )

        return pd.DataFrame.from_records(records)
    finally:
        con.close()


def analyze_all_candidate_keys(
    files: dict[str, Path],
    specs: dict[str, DatasetSpec],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Analyze configured candidate keys for every Bronze dataset."""
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
