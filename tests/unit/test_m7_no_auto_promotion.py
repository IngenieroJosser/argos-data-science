from pathlib import Path

from argos.config.prospective import load_prospective_spec
from argos.config.production import load_production_spec


def test_m7_cannot_auto_promote() -> None:
    root = Path(__file__).resolve().parents[2]
    m7 = load_prospective_spec(root / 'configs' / 'prospective.toml')
    m6 = load_production_spec(root / 'configs' / 'production.toml')
    assert not m7.governance.automatic_production_promotion
    assert not m6.deployment.allow_production_promotion
    assert m7.governance.human_review_required
    assert m6.core.human_review_required
