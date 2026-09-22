from pathlib import Path

from argos.config.registry import load_relationship_candidates


def test_load_relationship_candidates(tmp_path: Path) -> None:
    path = tmp_path / "datasets.toml"
    path.write_text(
        """
[relationship_candidates.contracts_processes]
left_dataset = "contracts"
right_dataset = "processes"
left_keys = ["Proceso de Compra"]
right_key_candidates = [["ID del Proceso"], ["ID del Portafolio"]]
""".strip(),
        encoding="utf-8",
    )

    candidates = load_relationship_candidates(path)
    spec = candidates["contracts_processes"]

    assert spec.left_keys == ("proceso_de_compra",)
    assert spec.right_key_candidates == (
        ("id_del_proceso",),
        ("id_del_portafolio",),
    )
