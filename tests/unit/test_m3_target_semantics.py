from pathlib import Path


def test_target_spec_is_frozen_and_explicit() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "docs" / "target-specs" / "y_addition_180d.md").read_text(encoding="utf-8")
    assert "FROZEN" in text
    assert "ADICION EN EL VALOR" in text
    assert "t0 < event_at <= t0 + 180" in text
    assert "y_addition_180d = NULL" in text
