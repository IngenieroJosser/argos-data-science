from argos.silver.utils import compact_identifier_expr


def test_compact_identifier_is_conservative_sql_expression() -> None:
    expression = compact_identifier_expr("NIT")

    assert "REGEXP_REPLACE" in expression
    assert "[^0-9A-Z]" in expression
    assert "CAST" in expression
    # The implementation must not encode a rule that drops a trailing check digit.
    assert "LEFT(" not in expression.upper()
    assert "SUBSTR" not in expression.upper()
