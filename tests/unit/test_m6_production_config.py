from pathlib import Path

from argos.config.production import load_production_spec


def test_m6_contract_is_shadow_batch_human_review() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = load_production_spec(root / "configs" / "production.toml")
    assert spec.schema_version == "m6-production-v1"
    assert spec.core.operating_mode == "shadow"
    assert spec.core.scoring_mode == "batch"
    assert spec.core.human_review_required is True
    assert spec.deployment.allow_production_promotion is False
    assert spec.scoring.tie_break == ("score_desc", "raw_score_desc", "contract_id_asc")
