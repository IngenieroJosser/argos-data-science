from __future__ import annotations

import os
from pathlib import Path

import duckdb


def connect(
    *,
    temp_directory: Path | None = None,
    threads: int | None = None,
    memory_limit: str | None = None,
) -> duckdb.DuckDBPyConnection:
    """Create an analytical DuckDB connection with conservative local defaults.

    ``threads`` and ``memory_limit`` are optional workload controls. M2 uses
    explicit values because wide SECOP transformations can otherwise consume
    nearly all unified memory before DuckDB starts spilling to disk.
    """
    con = duckdb.connect(database=":memory:")
    effective_threads = threads if threads is not None else max(1, min(os.cpu_count() or 1, 8))
    if effective_threads < 1:
        raise ValueError("threads must be >= 1")
    con.execute(f"SET threads = {int(effective_threads)}")
    con.execute("SET preserve_insertion_order = false")
    if memory_limit is not None:
        escaped_limit = str(memory_limit).replace("'", "''")
        con.execute(f"SET memory_limit = '{escaped_limit}'")
    if temp_directory is not None:
        temp_directory.mkdir(parents=True, exist_ok=True)
        escaped = str(temp_directory).replace("'", "''")
        con.execute(f"SET temp_directory = '{escaped}'")
    return con
