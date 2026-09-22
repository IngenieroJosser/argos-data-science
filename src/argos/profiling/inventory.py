from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from time import perf_counter

import pandas as pd

from argos.common.csv import inspect_csv_snapshot
from argos.config.registry import DatasetSpec


def file_sha256(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Return SHA-256 for a snapshot without loading it fully into memory."""
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(
    files: dict[str, Path],
    specs: dict[str, DatasetSpec],
    *,
    sample_size: int = 100_000,
    compute_sha256: bool = False,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Inventory the exact local Bronze snapshots.

    Notebook 00 is a governance inventory, not a type-profiling step. It uses a
    streaming CSV parser to count *logical* records exactly, including records
    whose quoted text contains embedded newlines. The file is never loaded fully
    into memory and Bronze is never modified.

    ``sample_size`` and ``temp_directory`` remain in the signature for API
    compatibility with the existing notebook; they are intentionally unused here.
    Detailed schema/type profiling starts in notebook 01.
    """
    del sample_size, temp_directory

    records: list[dict[str, object]] = []

    for key, path in files.items():
        started = perf_counter()
        if not path.is_file():
            raise FileNotFoundError(f"Bronze snapshot does not exist: {path}")

        stats = inspect_csv_snapshot(path)
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
                "row_count": stats.row_count,
                "column_count": stats.column_count,
                "min_fields_per_row": stats.min_fields,
                "max_fields_per_row": stats.max_fields,
                "ragged_row_count": stats.ragged_row_count,
                "parse_mode": "python_csv_streaming",
                "sha256": file_sha256(path) if compute_sha256 else None,
                "elapsed_seconds": perf_counter() - started,
                "source_url": specs[key].source_url,
            }
        )

    if not records:
        return pd.DataFrame()

    return pd.DataFrame.from_records(records).sort_values("dataset").reset_index(drop=True)
