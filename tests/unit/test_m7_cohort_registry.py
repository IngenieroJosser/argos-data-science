from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from argos.config.prospective import load_prospective_spec
from argos.prospective.cohorts import inventory_prospective_batches


def _batch(path: Path, t0: str, batch_id: str) -> None:
    pd.DataFrame(
        {
            "contract_id": [f"{batch_id}-1", f"{batch_id}-2"],
            "t0": [pd.Timestamp(t0), pd.Timestamp(t0)],
            "score": [0.2, 0.1],
            "raw_score": [0.3, 0.2],
            "rank": [1, 2],
            "model_version": ["argos-v1", "argos-v1"],
            "scoring_batch_id": [batch_id, batch_id],
        }
    ).to_parquet(path, index=False)


def test_historical_m6_replay_is_ignored_not_registered(tmp_path: Path) -> None:
    project = tmp_path
    root = Path(__file__).resolve().parents[2]
    spec = load_prospective_spec(root / "configs" / "prospective.toml")
    batch_root = project / spec.operations.scored_batch_root
    batch_root.mkdir(parents=True)
    _batch(batch_root / "old.parquet", "2026-03-01", "old")
    _batch(batch_root / "future.parquet", "2026-10-01", "future")

    inv = inventory_prospective_batches(project, spec)
    assert set(inv.eligible["scoring_batch_id"]) == {"future"}
    assert set(inv.ignored["scoring_batch_id"].dropna()) == {"old"}
