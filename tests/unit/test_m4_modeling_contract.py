from pathlib import Path

import numpy as np

from argos.config.modeling import load_modeling_spec
from argos.models.metrics import ranking_metrics


def _config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "modeling.toml"


def test_m4_test_policy_is_frozen_to_notebook_36() -> None:
    spec = load_modeling_spec(_config_path())
    assert spec.schema_version == "m4-model-v1"
    assert spec.test_policy.final_test_notebook == 36
    assert spec.ranking.operational_fraction == 0.01


def test_ranking_lift_detects_perfect_prioritization() -> None:
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.int8)
    p = np.array([0.99, 0.98, 0.4, 0.3, 0.2, 0.1, 0.09, 0.08, 0.07, 0.06])
    result = ranking_metrics("x", "validation", y, p, (0.2,))
    assert result.iloc[0]["precision_at_k"] == 1.0
    assert result.iloc[0]["recall_at_k"] == 1.0
    assert result.iloc[0]["lift_at_k"] == 5.0
