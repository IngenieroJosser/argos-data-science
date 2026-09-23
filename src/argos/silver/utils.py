from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

from argos.common.names import normalize_name, normalized_groups
from argos.common.sql import (
    clean_text_expr,
    money_expr,
    quote_identifier,
    sql_string,
    timestamp_expr,
    trimmed_text_expr,
)
from argos.profiling.schema import classify_semantic_type


def snapshot_date_from_path(path: Path) -> str:
    matches = re.findall(r"(?<!\d)(20\d{6})(?!\d)", path.stem)
    if not matches:
        raise ValueError(f"Could not infer YYYYMMDD snapshot date from {path.name!r}")
    return datetime.strptime(matches[-1], "%Y%m%d").date().isoformat()


def describe_source(con, source_sql: str) -> list[str]:
    return con.execute(f"DESCRIBE SELECT * FROM {source_sql}").fetchdf()[
        "column_name"
    ].astype(str).tolist()


def resolve_schema(columns: list[str], required: tuple[str, ...] | list[str]) -> dict[str, str]:
    groups = normalized_groups(columns)
    resolved: dict[str, str] = {}
    missing: list[str] = []
    ambiguous: dict[str, tuple[str, ...]] = {}
    for value in required:
        normalized = normalize_name(value)
        matches = groups.get(normalized, ())
        if len(matches) == 1:
            resolved[normalized] = matches[0]
        elif len(matches) == 0:
            missing.append(normalized)
        else:
            ambiguous[normalized] = matches
    if missing or ambiguous:
        raise KeyError(
            f"Required columns unresolved; missing={missing}, ambiguous={ambiguous}"
        )
    return resolved


def profile_lookup(profile_path: Path, dataset: str) -> dict[str, dict[str, Any]]:
    frame = pd.read_parquet(profile_path)
    subset = frame.loc[frame["dataset"] == dataset]
    result: dict[str, dict[str, Any]] = {}
    for row in subset.to_dict(orient="records"):
        normalized = str(row["normalized_column"])
        # A Bronze normalization collision is handled by request-scoped source
        # resolution. Do not silently let a later duplicate overwrite evidence.
        if normalized not in result:
            result[normalized] = row
    return result


def semantic_type(
    profile: dict[str, dict[str, Any]], normalized: str, raw_column: str
) -> str:
    row = profile.get(normalized)
    if row is not None and row.get("semantic_type"):
        return str(row["semantic_type"])
    return classify_semantic_type(raw_column)


def typed_projection(
    raw_column: str,
    canonical_column: str,
    semantic: str,
    *,
    date_order: str,
) -> list[str]:
    if semantic == "date":
        typed = timestamp_expr(raw_column, date_order=date_order)
    elif semantic == "money":
        typed = money_expr(raw_column)
    else:
        typed = trimmed_text_expr(raw_column)

    expressions = [f"{typed} AS {quote_identifier(canonical_column)}"]
    if semantic in {"date", "money"}:
        clean = clean_text_expr(raw_column)
        expressions.extend(
            [
                f"{trimmed_text_expr(raw_column)} AS {quote_identifier(canonical_column + '__raw')}",
                (
                    "CASE "
                    f"WHEN {clean} IS NULL THEN 'missing' "
                    f"WHEN {typed} IS NOT NULL THEN 'parsed' "
                    "ELSE 'unparsed' END "
                    f"AS {quote_identifier(canonical_column + '__parse_status')}"
                ),
            ]
        )
    return expressions


def prepare_output(path: Path, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not overwrite:
            raise FileExistsError(
                f"Artifact already exists: {path}. Pass overwrite=True intentionally."
            )
        path.unlink()


def copy_query(
    con,
    query: str,
    path: Path,
    *,
    compression: str,
    row_group_size: int,
    overwrite: bool,
) -> None:
    prepare_output(path, overwrite=overwrite)
    compression_sql = re.sub(r"[^A-Za-z0-9_]", "", compression).upper()
    if not compression_sql:
        raise ValueError("Invalid Parquet compression setting")
    con.execute(
        f"COPY ({query}) TO {sql_string(path)} "
        f"(FORMAT PARQUET, COMPRESSION {compression_sql}, ROW_GROUP_SIZE {int(row_group_size)})"
    )


def serialize_observed(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def add_validation(
    records: list[dict[str, Any]],
    *,
    check_id: str,
    category: str,
    passed: bool,
    observed: Any,
    requirement: str,
    blocking: bool = True,
) -> None:
    records.append(
        {
            "check_id": check_id,
            "category": category,
            "blocking": bool(blocking),
            "passed": bool(passed),
            "observed": serialize_observed(observed),
            "requirement": requirement,
        }
    )


def write_manifest(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    enriched = {
        **payload,
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def compact_identifier_expr(identifier: str) -> str:
    """Deterministic identifier normalization for entity-resolution candidates.

    Only case, whitespace and punctuation are removed. No check digit is dropped,
    no numeric coercion is performed and leading zeroes are preserved.
    """
    text = clean_text_expr(identifier)
    return (
        "CASE WHEN "
        f"{text} IS NULL THEN NULL ELSE "
        f"NULLIF(REGEXP_REPLACE(UPPER({text}), '[^0-9A-Z]', '', 'g'), '') END"
    )


def metadata_sql(*, source_id: str, snapshot_date: str, schema_version: str) -> str:
    return ", ".join(
        [
            f"DATE {sql_string(snapshot_date)} AS _source_snapshot_date",
            f"{sql_string(source_id)} AS _source_id",
            f"{sql_string(schema_version)} AS _silver_schema_version",
        ]
    )
