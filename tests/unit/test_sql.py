from pathlib import Path

from argos.common.sql import csv_source


def test_csv_source_is_conservative_by_default() -> None:
    source = csv_source(Path("data/bronze/sample.csv"))

    assert "read_csv(" in source
    assert "parallel=false" in source
    assert "null_padding=false" in source
    assert "strict_mode=true" in source
    assert "ignore_errors=false" in source
