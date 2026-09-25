import numpy as np
import pandas as pd

from argos.anomaly.contextual import FrequencyRobustEncoder


def test_anomaly_encoder_is_train_fitted_and_finite_for_unknown_categories():
    train = pd.DataFrame({'num': [1.0, 2.0, 3.0, 100.0], 'cat': ['a', 'a', 'a', 'b']})
    enc = FrequencyRobustEncoder.fit(
        train,
        numeric_features=('num',),
        categorical_features=('cat',),
    )
    matrix, rarity = enc.transform(
        pd.DataFrame({'num': [2.0, np.nan], 'cat': ['a', 'never_seen']})
    )
    assert matrix.shape == (2, 2)
    assert np.isfinite(matrix).all()
    assert rarity[1] > rarity[0]


def test_anomaly_encoder_accepts_boolean_numeric_features():
    train = pd.DataFrame(
        {
            "flag": pd.Series([True, False, True, False], dtype="bool"),
            "nullable_flag": pd.Series([True, pd.NA, False, True], dtype="boolean"),
        }
    )
    enc = FrequencyRobustEncoder.fit(
        train,
        numeric_features=("flag", "nullable_flag"),
        categorical_features=(),
    )
    matrix, rarity = enc.transform(train)
    assert matrix.shape == (4, 2)
    assert np.isfinite(matrix).all()
    assert np.isfinite(rarity).all()
