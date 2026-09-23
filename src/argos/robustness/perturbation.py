from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
from pandas.api.types import is_bool_dtype


def reference_values(
    sample: pd.DataFrame,
    categorical: set[str],
    features: Iterable[str],
) -> dict[str, Any]:
    """Build stable one-feature reference values for local sensitivity analysis.

    Categorical features use their modal string value, boolean features keep a
    boolean mode, and remaining numeric-like features use the median after
    coercion. The function never mutates ``sample``.
    """
    refs: dict[str, Any] = {}
    for feature in features:
        series = sample[feature]

        if feature in categorical:
            mode = series.astype("string").dropna().mode()
            refs[feature] = "__MISSING__" if mode.empty else str(mode.iloc[0])
            continue

        if is_bool_dtype(series.dtype):
            mode = series.dropna().mode()
            refs[feature] = False if mode.empty else bool(mode.iloc[0])
            continue

        numeric = pd.to_numeric(series, errors="coerce")
        median = numeric.median()
        refs[feature] = 0.0 if pd.isna(median) else float(median)

    return refs


def replace_feature_value(
    frame: pd.DataFrame,
    feature: str,
    value: Any,
) -> pd.DataFrame:
    """Return a copy with one feature column replaced safely.

    Pandas 3.x rejects lossy scalar assignment such as assigning ``0.0`` into a
    ``bool`` column via ``DataFrame.at``. Local sensitivity intentionally may
    substitute a reference value whose dtype differs from the observed scalar,
    so we replace the *whole column* and allow pandas to infer the appropriate
    dtype. Model bundles normalize categorical/numeric inputs during transform.
    """
    if feature not in frame.columns:
        raise KeyError(f"Feature {feature!r} not present in perturbation frame")

    changed = frame.copy()
    changed[feature] = pd.Series([value] * len(changed), index=changed.index)
    return changed
