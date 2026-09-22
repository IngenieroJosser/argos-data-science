from argos.common.sql import timestamp_expr, timestamp_format_expr
from argos.profiling.temporal import discover_date_columns


def test_timestamp_parser_prioritizes_iso_then_mdy_then_dmy() -> None:
    expression = timestamp_expr("Fecha de Firma", date_order="mdy")

    assert "%Y-%m-%d" in expression
    assert "%m/%d/%Y" in expression
    assert "%d/%m/%Y" in expression
    assert expression.index("%m/%d/%Y") < expression.index("%d/%m/%Y")
    assert "TRY_CAST" not in expression


def test_timestamp_format_expression_exposes_unparsed_values() -> None:
    expression = timestamp_format_expr("Fecha Evento", date_order="mdy")

    assert "mdy_date" in expression
    assert "unparsed" in expression


def test_saldo_vigencia_is_not_misclassified_as_a_date_column() -> None:
    columns = ["Fecha de Firma", "Saldo Vigencia", "timestamp_evento"]

    assert discover_date_columns(columns) == ["Fecha de Firma", "timestamp_evento"]
