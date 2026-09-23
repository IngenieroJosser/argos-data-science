import pandas as pd

from argos.prospective.metrics import prospective_metrics


def test_prospective_metrics_ranking_is_above_random_for_ordered_example() -> None:
    frame = pd.DataFrame(
        {
            "contract_id": list("abcdef"),
            "y": [1, 1, 0, 0, 0, 0],
            "score": [0.9, 0.8, 0.7, 0.3, 0.2, 0.1],
            "raw_score": [6, 5, 4, 3, 2, 1],
        }
    )
    result = prospective_metrics(
        frame,
        label="y",
        score="score",
        raw_score="raw_score",
        id_column="contract_id",
        fraction=0.34,
    )
    assert result["pr_auc_over_prevalence"] > 1.0
    assert result["lift_at_k"] > 1.0


def test_top_k_uses_frozen_raw_score_tiebreak() -> None:
    frame = pd.DataFrame(
        {
            "contract_id": ["b", "a", "c", "d"],
            "y": [0, 1, 0, 0],
            "score": [0.5, 0.5, 0.2, 0.1],
            "raw_score": [0.1, 0.9, 0.3, 0.2],
        }
    )
    result = prospective_metrics(
        frame,
        label="y",
        score="score",
        raw_score="raw_score",
        id_column="contract_id",
        fraction=0.25,
    )
    assert result["precision_at_k"] == 1.0
