from __future__ import annotations

import pandas as pd

from argos.robustness.perturbation import reference_values, replace_feature_value


def test_reference_values_preserve_boolean_semantics() -> None:
    sample = pd.DataFrame(
        {
            "flag": pd.Series([True, False, False], dtype="bool"),
            "numeric": pd.Series([1, 2, 4], dtype="int64"),
            "category": pd.Series(["b", "a", "a"], dtype="string"),
        }
    )

    refs = reference_values(
        sample,
        categorical={"category"},
        features=("flag", "numeric", "category"),
    )

    assert refs["flag"] is False
    assert refs["numeric"] == 2.0
    assert refs["category"] == "a"


def test_replace_feature_value_handles_bool_to_numeric_without_lossy_setitem() -> None:
    original = pd.DataFrame(
        {
            "flag": pd.Series([True], dtype="bool"),
            "count": pd.Series([1], dtype="int64"),
        }
    )

    changed = replace_feature_value(original, "flag", 0.0)

    assert float(changed.loc[0, "flag"]) == 0.0
    assert bool(original.loc[0, "flag"]) is True


def test_replace_feature_value_allows_fractional_reference_for_integer_column() -> None:
    original = pd.DataFrame({"count": pd.Series([1], dtype="int64")})

    changed = replace_feature_value(original, "count", 1.5)

    assert float(changed.loc[0, "count"]) == 1.5
    assert int(original.loc[0, "count"]) == 1
