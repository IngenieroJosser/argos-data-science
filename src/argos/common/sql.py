\
from __future__ import annotations

from pathlib import Path


def sql_string(value: str | Path) -> str:
    """Return a safely escaped SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def quote_identifier(value: str) -> str:
    """Quote an SQL identifier for DuckDB."""
    return '"' + value.replace('"', '""') + '"'


def csv_source(
    path: str | Path,
    *,
    sample_size: int = 100_000,
    all_varchar: bool = False,
) -> str:
    """DuckDB table expression for a CSV snapshot.

    Bronze is never mutated. DuckDB reads it directly and can spill to disk if needed.
    """
    return (
        "read_csv_auto("
        f"{sql_string(path)}, "
        "header=true, "
        f"sample_size={int(sample_size)}, "
        f"all_varchar={'true' if all_varchar else 'false'}, "
        "null_padding=true"
        ")"
    )


def timestamp_expr(identifier: str) -> str:
    """Best-effort timestamp parser that never raises on malformed values."""
    col = quote_identifier(identifier)
    as_text = f"CAST({col} AS VARCHAR)"
    return (
        "COALESCE("
        f"TRY_CAST({col} AS TIMESTAMP), "
        f"TRY_STRPTIME({as_text}, '%Y-%m-%dT%H:%M:%S.%g'), "
        f"TRY_STRPTIME({as_text}, '%Y-%m-%d %H:%M:%S'), "
        f"TRY_STRPTIME({as_text}, '%Y-%m-%d'), "
        f"TRY_STRPTIME({as_text}, '%d/%m/%Y %H:%M:%S'), "
        f"TRY_STRPTIME({as_text}, '%d/%m/%Y')"
        ")"
    )
