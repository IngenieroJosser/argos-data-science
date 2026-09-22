\
from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_report(df: pd.DataFrame, path: Path) -> Path:
    """Write a small analytical result as Parquet, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path
