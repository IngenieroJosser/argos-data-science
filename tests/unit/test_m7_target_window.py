import pandas as pd

from argos.config.prospective import load_prospective_spec
from argos.prospective.outcomes import compute_labels


def test_m7_target_window_is_open_left_closed_right(tmp_path):
    root = __import__('pathlib').Path(__file__).resolve().parents[2]
    spec = load_prospective_spec(root / 'configs' / 'prospective.toml')
    t0 = pd.Timestamp('2027-01-01')
    cohort = pd.DataFrame({'contract_id': ['a', 'b', 'c'], 't0': [t0, t0, t0]})
    events = pd.DataFrame({
        'contract_id': ['a', 'b', 'c'],
        'event_at': [t0, t0 + pd.Timedelta(days=180), t0 + pd.Timedelta(days=181)],
        'event_type': ['ADICION EN EL VALOR'] * 3,
    })
    result = compute_labels(
        cohort=cohort,
        additions=events,
        observation_end=t0 + pd.Timedelta(days=181),
        spec=spec,
    )
    labels = dict(zip(result['contract_id'], result['y_addition_180d']))
    assert labels['a'] == 0
    assert labels['b'] == 1
    assert labels['c'] == 0
