\
from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalized_mapping
from argos.common.sql import csv_source, quote_identifier
from argos.config.registry import RelationshipSpec


def _column_mapping(con, path: Path, sample_size: int) -> dict[str, str]:
    source = csv_source(path, sample_size=sample_size, all_varchar=True)
    schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
    return normalized_mapping(schema["column_name"].tolist())


def analyze_relationship(
    relationship: RelationshipSpec,
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> dict[str, object]:
    """Audit one join hypothesis at key-distribution level.

    The query groups each side before joining. It avoids physically materializing an
    explosive many-to-many join while still computing the expected LEFT JOIN size.
    """
    left_path = files[relationship.left_dataset]
    right_path = files[relationship.right_dataset]
    con = connect(temp_directory=temp_directory)
    left_map = _column_mapping(con, left_path, sample_size)
    right_map = _column_mapping(con, right_path, sample_size)

    missing_left = [k for k in relationship.left_keys if k not in left_map]
    missing_right = [k for k in relationship.right_keys if k not in right_map]
    if missing_left or missing_right:
        return {
            "relationship": relationship.key,
            "left_dataset": relationship.left_dataset,
            "right_dataset": relationship.right_dataset,
            "status": "missing_columns",
            "missing_left": missing_left,
            "missing_right": missing_right,
        }

    left_raw = [left_map[k] for k in relationship.left_keys]
    right_raw = [right_map[k] for k in relationship.right_keys]
    left_q = [quote_identifier(v) for v in left_raw]
    right_q = [quote_identifier(v) for v in right_raw]
    left_source = csv_source(left_path, sample_size=sample_size, all_varchar=True)
    right_source = csv_source(right_path, sample_size=sample_size, all_varchar=True)

    left_null = " OR ".join(f"{c} IS NULL" for c in left_q)
    right_null = " OR ".join(f"{c} IS NULL" for c in right_q)
    left_group = ", ".join(left_q)
    right_group = ", ".join(right_q)

    # Alias grouped keys to stable names so left/right raw labels may differ.
    left_aliases = ", ".join(f"{c} AS k{i}" for i, c in enumerate(left_q))
    right_aliases = ", ".join(f"{c} AS k{i}" for i, c in enumerate(right_q))
    grouped_keys = ", ".join(f"k{i}" for i in range(len(left_q)))
    on_clause = " AND ".join(f"l.k{i} = r.k{i}" for i in range(len(left_q)))

    query = f"""
    WITH lbase AS (
        SELECT {left_aliases}
        FROM {left_source}
    ), rbase AS (
        SELECT {right_aliases}
        FROM {right_source}
    ), lg AS (
        SELECT {grouped_keys}, COUNT(*) AS left_n
        FROM lbase
        WHERE NOT ({' OR '.join(f'k{i} IS NULL' for i in range(len(left_q)))})
        GROUP BY {grouped_keys}
    ), rg AS (
        SELECT {grouped_keys}, COUNT(*) AS right_n
        FROM rbase
        WHERE NOT ({' OR '.join(f'k{i} IS NULL' for i in range(len(right_q)))})
        GROUP BY {grouped_keys}
    ), joined AS (
        SELECT l.*, r.right_n
        FROM lg l
        LEFT JOIN rg r ON {on_clause}
    )
    SELECT
        (SELECT COUNT(*) FROM lbase) AS left_rows,
        (SELECT COUNT(*) FROM rbase) AS right_rows,
        (SELECT COUNT(*) FROM lbase WHERE {' OR '.join(f'k{i} IS NULL' for i in range(len(left_q)))}) AS left_rows_null_key,
        (SELECT COUNT(*) FROM rbase WHERE {' OR '.join(f'k{i} IS NULL' for i in range(len(right_q)))}) AS right_rows_null_key,
        COALESCE(SUM(left_n) FILTER (WHERE right_n IS NOT NULL), 0) AS matched_left_rows,
        COALESCE(SUM(left_n) FILTER (WHERE right_n IS NULL), 0) AS unmatched_left_nonnull_rows,
        COUNT(*) FILTER (WHERE right_n IS NOT NULL) AS matched_distinct_left_keys,
        COALESCE(SUM(left_n * right_n) FILTER (WHERE right_n IS NOT NULL), 0) AS matched_join_rows,
        COALESCE(MAX(right_n) FILTER (WHERE right_n IS NOT NULL), 0) AS max_right_multiplicity
    FROM joined
    """
    result = con.execute(query).fetchdf().iloc[0]
    left_rows = int(result["left_rows"])
    null_left = int(result["left_rows_null_key"])
    matched = int(result["matched_left_rows"])
    unmatched_nonnull = int(result["unmatched_left_nonnull_rows"])
    matched_join_rows = int(result["matched_join_rows"])
    expected_left_join_rows = null_left + unmatched_nonnull + matched_join_rows

    return {
        "relationship": relationship.key,
        "left_dataset": relationship.left_dataset,
        "right_dataset": relationship.right_dataset,
        "left_keys": list(relationship.left_keys),
        "right_keys": list(relationship.right_keys),
        "left_raw_columns": left_raw,
        "right_raw_columns": right_raw,
        "status": "analyzed",
        "left_rows": left_rows,
        "right_rows": int(result["right_rows"]),
        "left_rows_null_key": null_left,
        "right_rows_null_key": int(result["right_rows_null_key"]),
        "matched_left_rows": matched,
        "left_row_coverage": (matched / left_rows) if left_rows else None,
        "matched_distinct_left_keys": int(result["matched_distinct_left_keys"]),
        "max_right_multiplicity": int(result["max_right_multiplicity"]),
        "expected_left_join_rows": expected_left_join_rows,
        "expansion_factor": (expected_left_join_rows / left_rows) if left_rows else None,
    }


def analyze_all_relationships(
    relationships: dict[str, RelationshipSpec],
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    return pd.DataFrame.from_records(
        [
            analyze_relationship(
                spec,
                files,
                sample_size=sample_size,
                temp_directory=temp_directory,
            )
            for spec in relationships.values()
        ]
    )
