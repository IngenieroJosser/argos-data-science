from argos.profiling.schema import classify_semantic_type, preliminary_temporal_role


def test_money_semantic_type() -> None:
    assert classify_semantic_type("Valor del Contrato", "DOUBLE") == "money"


def test_obvious_post_t0_field_is_high_risk_hint() -> None:
    role, risk = preliminary_temporal_role("Días adicionados")
    assert role == "likely_post_t0_or_mutable"
    assert risk == "high"
