from pathlib import Path

from argos.config.prospective import load_prospective_spec


def test_m7_config_preserves_temporal_governance() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = load_prospective_spec(root / "configs" / "prospective.toml")
    assert spec.schema_version == "m7-prospective-v2"
    assert spec.core.prospective_start > spec.core.protocol_freeze_date
    assert spec.core.target_horizon_days == 180
    assert spec.cohorts.outcome_reporting_lag_days == 30
    assert spec.governance.consumed_test_year == 2025
    assert spec.governance.consumed_oot_year == 2026
    assert not spec.governance.allow_reuse_consumed_holdouts_for_selection
    assert spec.governance.human_review_required
    assert not spec.governance.automatic_production_promotion
    assert spec.operations.terminal_review_statuses == ("reviewed", "dismissed", "escalated")
