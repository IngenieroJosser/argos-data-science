from pathlib import Path

from argos.profiling.relationships import (
    analyze_relationship_candidates,
    select_relationship_candidate,
)


def test_relationship_candidate_resolution_selects_matching_key(tmp_path: Path) -> None:
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text("fk\nA\nB\nC\n", encoding="utf-8")
    right.write_text(
        "wrong_id,portfolio_id\nX,A\nY,B\nZ,C\n",
        encoding="utf-8",
    )

    candidates = analyze_relationship_candidates(
        key_prefix="left_right",
        left_dataset="left",
        right_dataset="right",
        left_keys=("fk",),
        right_key_candidates=(("wrong_id",), ("portfolio_id",)),
        files={"left": left, "right": right},
        sample_size=100,
        min_coverage=0.8,
        temp_directory=tmp_path / "duckdb",
    )

    selected, decision = select_relationship_candidate(
        candidates,
        relationship_key="left_right",
        min_coverage=0.8,
    )

    assert selected.right_keys == ("portfolio_id",)
    assert float(decision.iloc[0]["left_row_coverage"]) == 1.0
