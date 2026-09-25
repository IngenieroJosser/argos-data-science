from pathlib import Path
import tomllib


def test_m8_backend_contract_files_exist():
    required = [
        'configs/advanced.toml',
        'src/argos/nlp/semantic.py',
        'src/argos/graph/temporal.py',
        'src/argos/anomaly/contextual.py',
        'src/argos/survival/analysis.py',
        'src/argos/advanced/m8.py',
        'src/argos/advanced/ablation.py',
        'src/argos/evaluation/m8_gate.py',
        'pipelines/run_advanced_m8.py',
        'docs/M8_RUNBOOK.md',
        'docs/M8_HANDOFF.md',
    ]
    assert all(Path(p).is_file() for p in required)


def test_m8_never_selects_on_consumed_holdouts_by_config():
    cfg = tomllib.loads(Path('configs/advanced.toml').read_text())
    gov = cfg['governance']
    assert gov['development_splits'] == ['train', 'validation']
    assert gov['allow_consumed_holdouts_for_selection'] is False
    assert set(gov['consumed_holdout_years']) == {2025, 2026}
