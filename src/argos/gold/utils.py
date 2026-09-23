from __future__ import annotations

from pathlib import Path
from typing import Iterable

from argos.common.sql import sql_string
from argos.common.validation import add_validation, write_manifest
from argos.silver.utils import copy_query


def parquet_source(path: Path) -> str:
    return f"read_parquet({sql_string(path)})"


def columns_of(con, source_sql: str) -> list[str]:
    return (
        con.execute(f"DESCRIBE SELECT * FROM {source_sql}")
        .fetchdf()["column_name"]
        .astype(str)
        .tolist()
    )


def require_columns(con, source_sql: str, required: Iterable[str], *, label: str) -> list[str]:
    columns = columns_of(con, source_sql)
    missing = sorted(set(required) - set(columns))
    if missing:
        raise KeyError(f"{label} is missing required columns: {missing}")
    return columns


def sql_list(values: Iterable[str]) -> str:
    values = tuple(values)
    if not values:
        raise ValueError("sql_list requires at least one value")
    return ", ".join(sql_string(value) for value in values)


__all__ = [
    "add_validation",
    "copy_query",
    "write_manifest",
    "parquet_source",
    "columns_of",
    "require_columns",
    "sql_list",
]
