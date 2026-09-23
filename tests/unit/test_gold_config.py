from pathlib import Path

from argos.config.gold import load_gold_spec


def test_gold_spec_freezes_target_and_temporal_split() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = load_gold_spec(root / "configs" / "gold.toml")
    assert spec.schema_version == "m3-gold-v1"
    assert spec.target.name == "y_addition_180d"
    assert spec.target.horizon_days == 180
    assert spec.target.included_event_types == ("ADICION EN EL VALOR",)
    assert spec.splits.train_end < spec.splits.validation_start
    assert spec.splits.validation_end < spec.splits.test_start
    assert "estado_contrato" in spec.contract_features.forbidden_columns
