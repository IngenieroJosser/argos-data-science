from pathlib import Path


def test_m7_notebook_sequence_and_docs_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = [
        '60_prospective_protocol_freeze.ipynb',
        '61_prospective_shadow_cohorts.ipynb',
        '62_outcome_maturation_and_label_lock.ipynb',
        '63_prospective_model_performance.ipynb',
        '64_human_review_operational_utility.ipynb',
        '65_longitudinal_monitoring_and_incidents.ipynb',
        '66_operational_decision.ipynb',
        '67_m7_gate.ipynb',
    ]
    assert all((root / 'notebooks' / name).exists() for name in expected)
    assert (root / 'docs' / 'M7_RUNBOOK.md').exists()
    assert (root / 'docs' / 'M7_HANDOFF.md').exists()
    assert (root / 'docs' / 'decisions' / 'M7_START_2026-09-23.md').exists()
