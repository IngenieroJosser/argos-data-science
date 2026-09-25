from pathlib import Path

from argos.config.advanced import load_advanced_spec


def test_m8_config_governance_and_backends():
    spec = load_advanced_spec(Path('configs/advanced.toml'))
    assert spec.schema_version == 'm8-advanced-intelligence-v2'
    assert spec.governance.development_splits == ('train', 'validation')
    assert spec.governance.consumed_holdout_years == (2025, 2026)
    assert spec.governance.allow_consumed_holdouts_for_selection is False
    assert spec.nlp.embedding_backend == 'sentence_transformers'
    assert spec.nlp.index_backend == 'faiss'
    assert spec.nlp.allow_fallback_for_gate is False


def test_m8_survival_contract():
    spec = load_advanced_spec(Path('configs/advanced.toml'))
    assert spec.survival.enabled is True
    assert spec.survival.horizon_days == 180
    assert spec.survival.evaluation_horizons == (30, 90, 180)
    assert spec.acceptance.require_survival_analysis is True
