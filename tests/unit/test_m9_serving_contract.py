from argos.serving.m9 import (
    FORBIDDEN_OUTPUT_COLUMNS,
    M9_SCHEMA_VERSION,
    SAFE_CONTEXT_COLUMNS,
)


def test_m9_serving_contract_is_versioned_and_excludes_target() -> None:
    assert M9_SCHEMA_VERSION == "m9-serving-v1"
    assert "y_addition_180d" in FORBIDDEN_OUTPUT_COLUMNS
    assert "y_addition_180d" not in SAFE_CONTEXT_COLUMNS
    assert "prior_supplier_contract_count" in SAFE_CONTEXT_COLUMNS
    assert "prior_supplier_entity_contract_count" in SAFE_CONTEXT_COLUMNS
    assert "supplier_tenure_days" in SAFE_CONTEXT_COLUMNS
