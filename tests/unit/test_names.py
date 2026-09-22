from argos.common.names import (
    normalize_name,
    normalized_mapping,
    normalization_collisions,
    resolve_normalized_names,
)


def test_normalize_name_handles_accents_and_punctuation() -> None:
    assert (
        normalize_name("Fecha de Notificación de Prórroga")
        == "fecha_de_notificacion_de_prorroga"
    )


def test_normalized_mapping_rejects_collisions() -> None:
    try:
        normalized_mapping(["Código", "Codigo"])
    except ValueError:
        pass
    else:
        raise AssertionError("Expected normalization collision")


def test_normalization_collisions_preserves_all_raw_columns() -> None:
    collisions = normalization_collisions(
        ["Fecha de emision", "Fecha de emisión", "ID"]
    )

    assert collisions == {
        "fecha_de_emision": (
            "Fecha de emision",
            "Fecha de emisión",
        )
    }


def test_resolve_normalized_names_ignores_unrelated_collision() -> None:
    resolved, missing, ambiguous = resolve_normalized_names(
        ["Fecha de emision", "Fecha de emisión", "ID del Proceso"],
        ["id_del_proceso"],
    )

    assert resolved == {
        "id_del_proceso": "ID del Proceso"
    }
    assert missing == []
    assert ambiguous == {}


def test_resolve_normalized_names_reports_requested_ambiguity() -> None:
    resolved, missing, ambiguous = resolve_normalized_names(
        ["Fecha de emision", "Fecha de emisión", "ID"],
        ["fecha_de_emision"],
    )

    assert resolved == {}
    assert missing == []
    assert ambiguous == {
        "fecha_de_emision": (
            "Fecha de emision",
            "Fecha de emisión",
        )
    }
