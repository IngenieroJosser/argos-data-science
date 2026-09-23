import json

from argos.silver.contracts_processes import _serialize_validation_observed


def test_validation_observed_is_always_parquet_safe_text() -> None:
    values = [
        {"rows": 2, "coverage": 0.95},
        [],
        ["a", "b"],
        "already text",
        7,
        None,
    ]

    serialized = [_serialize_validation_observed(value) for value in values]

    assert all(isinstance(value, str) for value in serialized)
    assert json.loads(serialized[0]) == {"coverage": 0.95, "rows": 2}
    assert json.loads(serialized[1]) == []
    assert serialized[3] == "already text"
