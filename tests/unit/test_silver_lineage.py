from pathlib import Path

import pytest

from argos.silver.contracts_processes import snapshot_date_from_path


def test_snapshot_date_from_secop_filename() -> None:
    path = Path("SECOP_II_-_Contratos_Electrónicos_20260921.csv")
    assert snapshot_date_from_path(path) == "2026-09-21"


def test_snapshot_date_requires_yyyymmdd() -> None:
    with pytest.raises(ValueError):
        snapshot_date_from_path(Path("contracts.csv"))
