\
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from time import perf_counter

import pandas as pd

from argos.common.duckdb import connect
from argos.common.sql import csv_source
from argos.config.registry import DatasetSpec


def file_sha256(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _describe_csv(con, path: Path, *, sample_size: int) -> pd.DataFrame:
    source = csv_source(path, sample_size=sample_size)
    try:
        return con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()
    except Exception:
        fallback = csv_source(path, sample_size=sample_size, all_varchar=True)
        return con.execute(f"DESCRIBE SELECT * FROM {fallback}").fetchdf()


def build_inventory(
    files: dict[str, Path],
    specs: dict[str, DatasetSpec],
    *,
    sample_size: int = 100_000,
    compute_sha256: bool = False,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Inventory the exact local Bronze snapshots.

    COUNT(*) scans each CSV once. This is intentionally exact because row count is a
    governance property of the snapshot, not an estimate.
    """
    con = connect(temp_directory=temp_directory)
    records: list[dict[str, object]] = []

    for key, path in files.items():
        started = perf_counter()
        source = csv_source(path, sample_size=sample_size)
        parse_mode = "inferred"
        try:
            row_count = int(con.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[0])
            schema = _describe_csv(con, path, sample_size=sample_size)
        except Exception:
            parse_mode = "all_varchar_fallback"
            source = csv_source(path, sample_size=sample_size, all_varchar=True)
            row_count = int(con.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[0])
            schema = con.execute(f"DESCRIBE SELECT * FROM {source}").fetchdf()

        stat = path.stat()
        records.append(
            {
                "dataset": key,
                "source_id": specs[key].source_id,
                "source_name": specs[key].name,
                "filename": path.name,
                "path": str(path),
                "file_size_bytes": stat.st_size,
                "file_size_gb": stat.st_size / (1024**3),
                "row_count": row_count,
                "column_count": int(len(schema)),
                "parse_mode": parse_mode,
                "sha256": file_sha256(path) if compute_sha256 else None,
                "elapsed_seconds": perf_counter() - started,
                "source_url": specs[key].source_url,
            }
        )

    return pd.DataFrame.from_records(records).sort_values("dataset").reset_index(drop=True)
