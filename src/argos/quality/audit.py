\
from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name
from argos.common.sql import csv_source, quote_identifier


def audit_money_columns(
    dataset: str,
    path: Path,
    *,
    sample_size: int = 100_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Audit parseability, negatives and zeros for monetary-looking columns.

    It does not label extreme values as errors; outlier semantics require domain review.
    """
    con = connect(temp_directory=temp_directory)
    source = csv_source(path, sample_size=sample_size, all_varchar=True)
    schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
    monetary = [
        c for c in schema["column_name"].tolist()
        if any(token in normalize_name(c) for token in ["valor", "monto", "saldo", "presupuesto"])
    ]
    if not monetary:
        return pd.DataFrame(columns=["dataset", "column"])

    expressions = ["COUNT(*) AS __rows"]
    for idx, column in enumerate(monetary):
        q = quote_identifier(column)
        numeric = f"TRY_CAST({q} AS DOUBLE)"
        expressions += [
            f"COUNT(*) FILTER (WHERE {q} IS NOT NULL) AS c{idx}__nonnull",
            f"COUNT(*) FILTER (WHERE {q} IS NOT NULL AND {numeric} IS NOT NULL) AS c{idx}__parsed",
            f"COUNT(*) FILTER (WHERE {numeric} < 0) AS c{idx}__negative",
            f"COUNT(*) FILTER (WHERE {numeric} = 0) AS c{idx}__zero",
            f"MIN({numeric}) AS c{idx}__min",
            f"MAX({numeric}) AS c{idx}__max",
        ]
    result = con.execute(f"SELECT {', '.join(expressions)} FROM {source}").fetchdf().iloc[0]
    rows = int(result["__rows"])
    records = []
    for idx, column in enumerate(monetary):
        nonnull = int(result[f"c{idx}__nonnull"])
        parsed = int(result[f"c{idx}__parsed"])
        records.append(
            {
                "dataset": dataset,
                "column": column,
                "normalized_column": normalize_name(column),
                "row_count": rows,
                "nonnull_count": nonnull,
                "numeric_parse_rate_nonnull": parsed / nonnull if nonnull else None,
                "negative_count": int(result[f"c{idx}__negative"]),
                "zero_count": int(result[f"c{idx}__zero"]),
                "min_value": result[f"c{idx}__min"],
                "max_value": result[f"c{idx}__max"],
            }
        )
    return pd.DataFrame.from_records(records)


def summarize_quality(
    column_profile: pd.DataFrame,
    temporal_profile: pd.DataFrame,
    key_profile: pd.DataFrame,
    join_profile: pd.DataFrame,
    money_profile: pd.DataFrame,
) -> pd.DataFrame:
    """Create an issue register without silently cleaning anything."""
    issues: list[dict[str, object]] = []

    for row in column_profile.itertuples(index=False):
        if getattr(row, "null_rate", None) is not None and row.null_rate >= 0.50:
            issues.append({
                "dataset": row.dataset,
                "scope": row.column,
                "rule": "high_missingness",
                "severity": "warning",
                "metric": row.null_rate,
                "threshold": 0.50,
                "action": "investigate_by_time_and_segment_before_imputation_or_drop",
            })
        if getattr(row, "leakage_risk_hint", None) == "high":
            issues.append({
                "dataset": row.dataset,
                "scope": row.column,
                "rule": "potential_temporal_leakage",
                "severity": "critical_for_modeling",
                "metric": None,
                "threshold": None,
                "action": "exclude_from_features_until_temporal_audit_approves",
            })

    if not temporal_profile.empty:
        for row in temporal_profile.itertuples(index=False):
            rate = getattr(row, "parse_success_rate_nonnull", None)
            if rate is not None and rate < 0.98:
                issues.append({
                    "dataset": row.dataset,
                    "scope": row.column,
                    "rule": "date_parseability",
                    "severity": "warning",
                    "metric": rate,
                    "threshold": 0.98,
                    "action": "inspect_formats_and_invalid_values",
                })

    if not key_profile.empty:
        for row in key_profile.itertuples(index=False):
            if getattr(row, "status", None) == "analyzed" and getattr(row, "candidate_key", None):
                if getattr(row, "null_key_rate", 0) and row.null_key_rate > 0:
                    issues.append({
                        "dataset": row.dataset,
                        "scope": row.candidate_key,
                        "rule": "candidate_key_nulls",
                        "severity": "warning",
                        "metric": row.null_key_rate,
                        "threshold": 0.0,
                        "action": "do_not_accept_as_primary_key_without_resolution",
                    })

    if not join_profile.empty:
        for row in join_profile.itertuples(index=False):
            if getattr(row, "status", None) == "analyzed":
                coverage = getattr(row, "left_row_coverage", None)
                expansion = getattr(row, "expansion_factor", None)
                if coverage is not None and coverage < 0.95:
                    issues.append({
                        "dataset": f"{row.left_dataset}->{row.right_dataset}",
                        "scope": row.relationship,
                        "rule": "low_join_coverage",
                        "severity": "warning",
                        "metric": coverage,
                        "threshold": 0.95,
                        "action": "investigate_identifier_semantics_and_unmatched_population",
                    })
                if expansion is not None and expansion > 1.05:
                    issues.append({
                        "dataset": f"{row.left_dataset}->{row.right_dataset}",
                        "scope": row.relationship,
                        "rule": "join_expansion",
                        "severity": "warning",
                        "metric": expansion,
                        "threshold": 1.05,
                        "action": "confirm_expected_cardinality_before_materializing_join",
                    })

    if not money_profile.empty:
        for row in money_profile.itertuples(index=False):
            if getattr(row, "negative_count", 0) > 0:
                issues.append({
                    "dataset": row.dataset,
                    "scope": row.column,
                    "rule": "negative_monetary_values",
                    "severity": "review",
                    "metric": row.negative_count,
                    "threshold": 0,
                    "action": "determine_whether_negative_values_are_valid_business_events_or_errors",
                })

    return pd.DataFrame.from_records(issues)
