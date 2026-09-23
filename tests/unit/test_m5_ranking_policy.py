from pathlib import Path


def test_deterministic_ranking_has_three_level_tie_break() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "src" / "argos" / "robustness" / "common.py").read_text(encoding="utf-8")
    assert '["score", "raw_score", "contract_id"]' in source
    assert 'ascending=[False, False, True]' in source
    assert 'kind="mergesort"' in source
