from pathlib import Path


def test_fresh_oot_scores_frozen_v1_without_training() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "src" / "argos" / "robustness" / "fresh_oot.py").read_text(encoding="utf-8")
    assert "load_frozen_v1" in source
    assert "fresh_oot_consumed" in source
    assert "model_reselected_after_fresh_oot" in source
    assert "fit_boosting_bundle" not in source
    assert ".fit(" not in source


def test_development_modules_do_not_select_on_final_test() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ["backtesting.py", "explainability.py", "uncertainty.py", "feature_value.py"]:
        source = (root / "src" / "argos" / "robustness" / name).read_text(encoding="utf-8")
        assert "36_final_test_predictions" not in source
