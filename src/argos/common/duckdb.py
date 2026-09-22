from __future__ import annotations

import os
from pathlib import Path

import duckdb


def connect(*, temp_directory: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Create an analytical DuckDB connection with conservative local defaults."""
    con = duckdb.connect(database=":memory:")
    threads = max(1, min(os.cpu_count() or 1, 8))
    con.execute(f"SET threads = {threads}")
    con.execute("SET preserve_insertion_order = false")
    if temp_directory is not None:
        temp_directory.mkdir(parents=True, exist_ok=True)
        escaped = str(temp_directory).replace("'", "''")
        con.execute(f"SET temp_directory = '{escaped}'")
    return con
