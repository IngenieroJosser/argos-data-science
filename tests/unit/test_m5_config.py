from pathlib import Path

from argos.config.robustness import load_robustness_spec


def test_m5_contract_freezes_holdout_and_tie_break() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = load_robustness_spec(root / "configs" / "robustness.toml")
    assert spec.schema_version == "m5-robustness-v1"
    assert spec.governance.consumed_test_year == 2025
    assert spec.governance.fresh_oot_year == 2026
    assert 2025 not in spec.backtesting.evaluation_years
    assert spec.ranking.tie_break == ("score_desc", "raw_score_desc", "contract_id_asc")
    assert spec.governance.production_authorized is False
