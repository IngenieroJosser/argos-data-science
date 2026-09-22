\
from argos.common.names import normalize_name, normalized_mapping


def test_normalize_name_handles_accents_and_punctuation() -> None:
    assert normalize_name("Fecha de Notificación de Prórroga") == "fecha_de_notificacion_de_prorroga"


def test_normalized_mapping_rejects_collisions() -> None:
    try:
        normalized_mapping(["Código", "Codigo"])
    except ValueError:
        pass
    else:
        raise AssertionError("Expected normalization collision")
