from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name, resolve_normalized_names
from argos.common.sql import csv_source, quote_identifier


def analyze_duplicate_structure(
    dataset: str,
    path: Path,
    key_columns: tuple[str, ...],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> dict[str, object]:
    """Characterize repeated keys without mutating or deduplicating Bronze.

    A duplicate key can mean two very different things:

    - repeated *identical* source rows, which Silver can usually collapse with a
      documented exact-deduplication rule;
    - several payload variants for the same key, which indicates a versioned or
      otherwise non-entity grain and requires canonicalization logic.

    ``row_fingerprint`` is computed across every physical source column. The
    function therefore distinguishes exact duplicate rows from conflicting rows
    for the requested key.
    """
    con = connect(temp_directory=temp_directory)

    try:
        source = csv_source(path, sample_size=sample_size, all_varchar=True)
        schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
        columns = schema["column_name"].tolist()
        resolved, missing, ambiguous = resolve_normalized_names(columns, key_columns)
        key_label = "+".join(normalize_name(value) for value in key_columns)

        if missing:
            return {
                "dataset": dataset,
                "key": key_label,
                "status": "missing_columns",
                "missing_columns": missing,
                "ambiguous_columns": None,
            }
        if ambiguous:
            return {
                "dataset": dataset,
                "key": key_label,
                "status": "ambiguous_columns",
                "missing_columns": None,
                "ambiguous_columns": {
                    name: list(values) for name, values in ambiguous.items()
                },
            }

        normalized_keys = [normalize_name(value) for value in key_columns]
        raw_keys = [resolved[value] for value in normalized_keys]
        quoted_keys = [quote_identifier(value) for value in raw_keys]
        key_select = ", ".join(
            f"{column} AS k{idx}" for idx, column in enumerate(quoted_keys)
        )
        key_group = ", ".join(f"k{idx}" for idx in range(len(quoted_keys)))
        null_predicate = " OR ".join(
            f"k{idx} IS NULL" for idx in range(len(quoted_keys))
        )

        all_quoted = [quote_identifier(column) for column in columns]
        fingerprint = f"hash({', '.join(all_quoted)})"

        query = f"""
        WITH base AS (
            SELECT
                {key_select},
                {fingerprint} AS row_fingerprint
            FROM {source}
        ), grouped AS (
            SELECT
                {key_group},
                COUNT(*) AS n,
                COUNT(DISTINCT row_fingerprint) AS payload_variants
            FROM base
            WHERE NOT ({null_predicate})
            GROUP BY {key_group}
        )
        SELECT
            COUNT(*) AS distinct_nonnull_keys,
            COUNT(*) FILTER (WHERE n > 1) AS duplicate_key_count,
            COALESCE(SUM(n) FILTER (WHERE n > 1), 0) AS rows_on_duplicate_keys,
            COALESCE(SUM(n - 1) FILTER (WHERE n > 1), 0) AS duplicate_excess_rows,
            COALESCE(
                SUM(n - payload_variants) FILTER (WHERE n > 1),
                0
            ) AS exact_duplicate_excess_rows,
            COUNT(*) FILTER (
                WHERE n > 1 AND payload_variants = 1
            ) AS exact_duplicate_key_count,
            COUNT(*) FILTER (
                WHERE n > 1 AND payload_variants > 1
            ) AS conflicting_duplicate_key_count,
            COALESCE(MAX(n), 0) AS max_key_multiplicity,
            COALESCE(MAX(payload_variants), 0) AS max_payload_variants
        FROM grouped
        """
        result = con.execute(query).fetchdf().iloc[0]

        duplicate_excess = int(result["duplicate_excess_rows"])
        exact_duplicate_excess = int(result["exact_duplicate_excess_rows"])
        conflicting_keys = int(result["conflicting_duplicate_key_count"])

        if duplicate_excess == 0:
            grain_interpretation = "unique_key"
        elif conflicting_keys == 0:
            grain_interpretation = "exact_row_duplicates_only"
        else:
            grain_interpretation = "multiple_payload_variants_per_key"

        return {
            "dataset": dataset,
            "key": key_label,
            "raw_columns": raw_keys,
            "status": "analyzed",
            "distinct_nonnull_keys": int(result["distinct_nonnull_keys"]),
            "duplicate_key_count": int(result["duplicate_key_count"]),
            "rows_on_duplicate_keys": int(result["rows_on_duplicate_keys"]),
            "duplicate_excess_rows": duplicate_excess,
            "exact_duplicate_excess_rows": exact_duplicate_excess,
            "exact_duplicate_key_count": int(result["exact_duplicate_key_count"]),
            "conflicting_duplicate_key_count": conflicting_keys,
            "max_key_multiplicity": int(result["max_key_multiplicity"]),
            "max_payload_variants": int(result["max_payload_variants"]),
            "grain_interpretation": grain_interpretation,
            "silver_implication": (
                "none"
                if grain_interpretation == "unique_key"
                else "drop_exact_duplicates"
                if grain_interpretation == "exact_row_duplicates_only"
                else "canonicalize_or_model_versioned_rows"
            ),
        }
    finally:
        con.close()


def top_duplicate_keys(
    dataset: str,
    path: Path,
    key_columns: tuple[str, ...],
    *,
    sample_size: int = 100_000,
    limit: int = 25,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Return the most repeated keys and their payload-variant counts."""
    con = connect(temp_directory=temp_directory)

    try:
        source = csv_source(path, sample_size=sample_size, all_varchar=True)
        schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
        columns = schema["column_name"].tolist()
        resolved, missing, ambiguous = resolve_normalized_names(columns, key_columns)
        if missing:
            raise KeyError(f"Missing key columns for {dataset!r}: {missing}")
        if ambiguous:
            raise ValueError(f"Ambiguous key columns for {dataset!r}: {ambiguous}")

        normalized_keys = [normalize_name(value) for value in key_columns]
        raw_keys = [resolved[value] for value in normalized_keys]
        quoted_keys = [quote_identifier(value) for value in raw_keys]
        key_select = ", ".join(
            f"{column} AS k{idx}" for idx, column in enumerate(quoted_keys)
        )
        key_group = ", ".join(f"k{idx}" for idx in range(len(quoted_keys)))
        null_predicate = " OR ".join(
            f"k{idx} IS NULL" for idx in range(len(quoted_keys))
        )
        all_quoted = [quote_identifier(column) for column in columns]
        fingerprint = f"hash({', '.join(all_quoted)})"

        query = f"""
        WITH base AS (
            SELECT {key_select}, {fingerprint} AS row_fingerprint
            FROM {source}
        )
        SELECT
            {key_group},
            COUNT(*) AS rows,
            COUNT(DISTINCT row_fingerprint) AS payload_variants
        FROM base
        WHERE NOT ({null_predicate})
        GROUP BY {key_group}
        HAVING COUNT(*) > 1
        ORDER BY rows DESC, payload_variants DESC
        LIMIT {int(limit)}
        """
        result = con.execute(query).fetchdf()
        rename_map = {
            f"k{idx}": normalize_name(key_columns[idx])
            for idx in range(len(key_columns))
        }
        result = result.rename(columns=rename_map)
        result.insert(0, "dataset", dataset)
        result.insert(1, "key", "+".join(normalized_keys))
        return result
    finally:
        con.close()
