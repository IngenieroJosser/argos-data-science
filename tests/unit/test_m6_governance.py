from pathlib import Path


def test_m6_notebooks_do_not_enable_autonomous_production() -> None:
    root = Path(__file__).resolve().parents[2]
    forbidden = ["allow_production_promotion = true", "production_authorized = true"]
    for path in sorted((root / "notebooks").glob("5*.ipynb")):
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text


def test_production_config_keeps_human_review() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "configs" / "production.toml").read_text(encoding="utf-8").lower()
    assert 'human_review_required = true' in text
    assert 'allow_production_promotion = false' in text
