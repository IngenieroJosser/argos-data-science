import json
from pathlib import Path


def test_m5_notebooks_are_present_and_valid_json() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = [
        "40_temporal_backtesting.ipynb",
        "41_explainability.ipynb",
        "42_uncertainty_and_ranking_stability.ipynb",
        "43_drift_and_calibration_monitoring.ipynb",
        "44_feature_family_revalidation.ipynb",
        "45_fresh_oot_2026.ipynb",
        "46_preproduction_readiness.ipynb",
        "47_m5_gate.ipynb",
    ]
    for name in expected:
        path = root / "notebooks" / name
        assert path.exists(), name
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["nbformat"] == 4


def test_pipeline_requires_explicit_fresh_oot_flag() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "pipelines" / "run_robustness_m5.py").read_text(encoding="utf-8")
    assert "--consume-fresh-oot" in source
    assert "Fresh OOT 2026 was NOT consumed" in source
