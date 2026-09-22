from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import resolve_normalized_names
from argos.common.sql import csv_source, quote_identifier
from argos.config.registry import RelationshipSpec


def _columns(con, path: Path, sample_size: int) -> list[str]:
    """Return physical column names for a Bronze CSV."""
    source = csv_source(
        path,
        sample_size=sample_size,
        all_varchar=True,
    )
    schema = con.execute(
        f"DESCRIBE SELECT * FROM {source}"
    ).fetchdf()
    return schema["column_name"].tolist()


def analyze_relationship(
    relationship: RelationshipSpec,
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> dict[str, object]:
    """Audit one join hypothesis at key-distribution level.

    The query groups each side before joining. It avoids physically
    materializing an explosive many-to-many join while still computing the
    expected LEFT JOIN size.

    Normalized-name collisions are tolerated unless they affect one of the
    requested join keys. Ambiguous requested keys are reported explicitly and
    are never resolved by arbitrarily selecting one physical column.
    """
    left_path = files[relationship.left_dataset]
    right_path = files[relationship.right_dataset]

    con = connect(temp_directory=temp_directory)

    try:
        left_columns = _columns(
            con,
            left_path,
            sample_size,
        )
        right_columns = _columns(
            con,
            right_path,
            sample_size,
        )

        left_resolved, missing_left, ambiguous_left = (
            resolve_normalized_names(
                left_columns,
                relationship.left_keys,
            )
        )
        right_resolved, missing_right, ambiguous_right = (
            resolve_normalized_names(
                right_columns,
                relationship.right_keys,
            )
        )

        if missing_left or missing_right:
            return {
                "relationship": relationship.key,
                "left_dataset": relationship.left_dataset,
                "right_dataset": relationship.right_dataset,
                "status": "missing_columns",
                "missing_left": missing_left,
                "missing_right": missing_right,
                "ambiguous_left": None,
                "ambiguous_right": None,
            }

        if ambiguous_left or ambiguous_right:
            return {
                "relationship": relationship.key,
                "left_dataset": relationship.left_dataset,
                "right_dataset": relationship.right_dataset,
                "status": "ambiguous_columns",
                "missing_left": None,
                "missing_right": None,
                "ambiguous_left": {
                    key: list(values)
                    for key, values in ambiguous_left.items()
                },
                "ambiguous_right": {
                    key: list(values)
                    for key, values in ambiguous_right.items()
                },
            }

        left_raw = [
            left_resolved[key]
            for key in relationship.left_keys
        ]
        right_raw = [
            right_resolved[key]
            for key in relationship.right_keys
        ]

        left_q = [
            quote_identifier(value)
            for value in left_raw
        ]
        right_q = [
            quote_identifier(value)
            for value in right_raw
        ]

        left_source = csv_source(
            left_path,
            sample_size=sample_size,
            all_varchar=True,
        )
        right_source = csv_source(
            right_path,
            sample_size=sample_size,
            all_varchar=True,
        )

        left_aliases = ", ".join(
            f"{column} AS k{idx}"
            for idx, column in enumerate(left_q)
        )
        right_aliases = ", ".join(
            f"{column} AS k{idx}"
            for idx, column in enumerate(right_q)
        )
        grouped_keys = ", ".join(
            f"k{idx}"
            for idx in range(len(left_q))
        )
        on_clause = " AND ".join(
            f"l.k{idx} = r.k{idx}"
            for idx in range(len(left_q))
        )

        left_null_alias = " OR ".join(
            f"k{idx} IS NULL"
            for idx in range(len(left_q))
        )
        right_null_alias = " OR ".join(
            f"k{idx} IS NULL"
            for idx in range(len(right_q))
        )

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
            WHERE NOT ({left_null_alias})
            GROUP BY {grouped_keys}
        ), rg AS (
            SELECT {grouped_keys}, COUNT(*) AS right_n
            FROM rbase
            WHERE NOT ({right_null_alias})
            GROUP BY {grouped_keys}
        ), joined AS (
            SELECT l.*, r.right_n
            FROM lg l
            LEFT JOIN rg r
              ON {on_clause}
        )
        SELECT
            (SELECT COUNT(*) FROM lbase) AS left_rows,
            (SELECT COUNT(*) FROM rbase) AS right_rows,
            (
                SELECT COUNT(*)
                FROM lbase
                WHERE {left_null_alias}
            ) AS left_rows_null_key,
            (
                SELECT COUNT(*)
                FROM rbase
                WHERE {right_null_alias}
            ) AS right_rows_null_key,
            COALESCE(
                SUM(left_n)
                FILTER (WHERE right_n IS NOT NULL),
                0
            ) AS matched_left_rows,
            COALESCE(
                SUM(left_n)
                FILTER (WHERE right_n IS NULL),
                0
            ) AS unmatched_left_nonnull_rows,
            COUNT(*)
                FILTER (WHERE right_n IS NOT NULL)
                AS matched_distinct_left_keys,
            COALESCE(
                SUM(left_n * right_n)
                FILTER (WHERE right_n IS NOT NULL),
                0
            ) AS matched_join_rows,
            COALESCE(
                MAX(right_n)
                FILTER (WHERE right_n IS NOT NULL),
                0
            ) AS max_right_multiplicity
        FROM joined
        """

        result = con.execute(query).fetchdf().iloc[0]

        left_rows = int(result["left_rows"])
        null_left = int(result["left_rows_null_key"])
        matched = int(result["matched_left_rows"])
        unmatched_nonnull = int(
            result["unmatched_left_nonnull_rows"]
        )
        matched_join_rows = int(
            result["matched_join_rows"]
        )

        expected_left_join_rows = (
            null_left
            + unmatched_nonnull
            + matched_join_rows
        )

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
            "right_rows_null_key": int(
                result["right_rows_null_key"]
            ),
            "matched_left_rows": matched,
            "left_row_coverage": (
                matched / left_rows
                if left_rows
                else None
            ),
            "matched_distinct_left_keys": int(
                result["matched_distinct_left_keys"]
            ),
            "max_right_multiplicity": int(
                result["max_right_multiplicity"]
            ),
            "expected_left_join_rows": expected_left_join_rows,
            "expansion_factor": (
                expected_left_join_rows / left_rows
                if left_rows
                else None
            ),
        }
    finally:
        con.close()


def analyze_all_relationships(
    relationships: dict[str, RelationshipSpec],
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Audit every configured join hypothesis."""
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


def analyze_relationship_candidates(
    *,
    key_prefix: str,
    left_dataset: str,
    right_dataset: str,
    left_keys: tuple[str, ...],
    right_key_candidates: tuple[tuple[str, ...], ...],
    files: dict[str, Path],
    sample_size: int = 100_000,
    min_coverage: float = 0.80,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Compare alternative right-side keys for one relationship hypothesis.

    The function does not silently accept the highest-scoring candidate. It
    records whether each candidate clears ``min_coverage`` and leaves the
    canonicalization requirement visible when the right side is non-unique.
    """
    records: list[dict[str, object]] = []

    for candidate in right_key_candidates:
        normalized_right = tuple(candidate)
        candidate_label = "+".join(normalized_right)
        spec = RelationshipSpec(
            key=f"{key_prefix}__{candidate_label}",
            left_dataset=left_dataset,
            right_dataset=right_dataset,
            left_keys=tuple(left_keys),
            right_keys=normalized_right,
        )
        record = analyze_relationship(
            spec,
            files,
            sample_size=sample_size,
            temp_directory=temp_directory,
        )
        coverage = record.get("left_row_coverage")
        multiplicity = record.get("max_right_multiplicity")
        record["candidate_group"] = key_prefix
        record["candidate_right_keys"] = list(normalized_right)
        record["meets_min_coverage"] = bool(
            record.get("status") == "analyzed"
            and coverage is not None
            and float(coverage) >= float(min_coverage)
        )
        record["requires_right_canonicalization"] = bool(
            multiplicity is not None and int(multiplicity) > 1
        )
        records.append(record)

    result = pd.DataFrame.from_records(records)
    if result.empty:
        return result

    result["coverage_rank"] = result["left_row_coverage"].rank(
        method="dense",
        ascending=False,
        na_option="bottom",
    )
    return result.sort_values(
        ["meets_min_coverage", "left_row_coverage", "expansion_factor"],
        ascending=[False, False, True],
        na_position="last",
    ).reset_index(drop=True)


def select_relationship_candidate(
    candidates: pd.DataFrame,
    *,
    relationship_key: str,
    min_coverage: float = 0.80,
) -> tuple[RelationshipSpec, pd.DataFrame]:
    """Select the highest-coverage candidate that clears an explicit threshold.

    Returns the selected ``RelationshipSpec`` and a one-row decision frame for
    persistence in ``reports/profiling/relationship_resolution.parquet``.
    """
    if candidates.empty:
        raise ValueError(f"No relationship candidates were analyzed for {relationship_key!r}.")

    eligible = candidates.loc[
        (candidates["status"] == "analyzed")
        & (candidates["left_row_coverage"].fillna(0) >= float(min_coverage))
    ].copy()

    if eligible.empty:
        observed = candidates[
            ["candidate_right_keys", "status", "left_row_coverage", "expansion_factor"]
        ].to_dict("records")
        raise ValueError(
            f"No candidate for {relationship_key!r} reached coverage >= {min_coverage:.3f}. "
            f"Observed: {observed}"
        )

    eligible = eligible.sort_values(
        ["left_row_coverage", "expansion_factor", "max_right_multiplicity"],
        ascending=[False, True, True],
        na_position="last",
    )
    selected = eligible.iloc[0]

    left_keys = tuple(selected["left_keys"])
    right_keys = tuple(selected["right_keys"])
    spec = RelationshipSpec(
        key=relationship_key,
        left_dataset=str(selected["left_dataset"]),
        right_dataset=str(selected["right_dataset"]),
        left_keys=left_keys,
        right_keys=right_keys,
    )

    decision = pd.DataFrame.from_records(
        [
            {
                "relationship": relationship_key,
                "status": "resolved",
                "left_dataset": spec.left_dataset,
                "right_dataset": spec.right_dataset,
                "left_keys": list(spec.left_keys),
                "selected_right_keys": list(spec.right_keys),
                "left_row_coverage": float(selected["left_row_coverage"]),
                "max_right_multiplicity": int(selected["max_right_multiplicity"]),
                "expansion_factor": float(selected["expansion_factor"]),
                "requires_right_canonicalization": bool(
                    selected["requires_right_canonicalization"]
                ),
                "selection_rule": "max_coverage_then_min_expansion",
                "minimum_required_coverage": float(min_coverage),
            }
        ]
    )
    return spec, decision
