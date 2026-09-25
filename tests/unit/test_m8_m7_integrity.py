from pathlib import Path

from argos.config.production import load_production_spec
from argos.config.prospective import load_prospective_spec
from argos.prospective.protocol import verify_frozen_protocol


def test_m8_does_not_modify_frozen_m7_protocol():
    root = Path('.').resolve()
    prospective = load_prospective_spec(root / 'configs' / 'prospective.toml')
    production = load_production_spec(root / 'configs' / 'production.toml')
    ok, details = verify_frozen_protocol(
        root=root,
        prospective_spec=prospective,
        production_spec=production,
        docs_root=root / 'docs',
    )
    assert ok, details
    assert details['hash_mismatches'] == {}
    assert details['core_mismatches'] == {}
