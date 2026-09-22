from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CsvSnapshotStats:
    """Structural statistics collected with Python's RFC-style CSV parser."""

    row_count: int
    column_count: int
    min_fields: int
    max_fields: int
    ragged_row_count: int
    header: tuple[str, ...]


def _raise_csv_field_limit() -> None:
    """Raise csv.field_size_limit safely for large SECOP text fields."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def inspect_csv_snapshot(
    path: Path,
    *,
    encoding: str = "utf-8-sig",
    delimiter: str = ",",
    quotechar: str = '"',
) -> CsvSnapshotStats:
    """Count logical CSV records without loading the file into memory.

    ``csv.reader`` correctly treats newlines inside quoted fields as part of the
    same logical record. This makes it a robust choice for the exact M1 Bronze
    inventory, where correctness is more important than maximum throughput.

    Ragged records are counted rather than silently repaired or discarded.
    """
    _raise_csv_field_limit()

    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, quotechar=quotechar)
        try:
            header = tuple(next(reader))
        except StopIteration as exc:
            raise ValueError(f"CSV snapshot is empty: {path}") from exc

        expected = len(header)
        row_count = 0
        min_fields = expected
        max_fields = expected
        ragged = 0

        for row in reader:
            row_count += 1
            width = len(row)
            min_fields = min(min_fields, width)
            max_fields = max(max_fields, width)
            if width != expected:
                ragged += 1

    return CsvSnapshotStats(
        row_count=row_count,
        column_count=expected,
        min_fields=min_fields,
        max_fields=max_fields,
        ragged_row_count=ragged,
        header=header,
    )
