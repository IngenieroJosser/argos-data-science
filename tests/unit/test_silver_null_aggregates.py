import math

from argos.silver.contracts_processes import _int_or_zero


def test_int_or_zero_handles_sql_null_and_pandas_nan() -> None:
    assert _int_or_zero(None) == 0
    assert _int_or_zero(float("nan")) == 0
    assert _int_or_zero(7) == 7
