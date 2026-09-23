from pathlib import Path

from argos.config.silver import load_silver_spec


def test_silver_spec_freezes_m1_contract_process_decisions() -> None:
    spec = load_silver_spec(Path("configs/silver.toml"))

    assert spec.schema_version == "m2-silver-v1"
    assert spec.runtime.duckdb_threads == 2
    assert spec.runtime.duckdb_memory_limit == "8GB"
    assert spec.contracts.primary_key == "id_contrato"
    assert spec.contracts.process_fk == "proceso_de_compra"
    assert spec.contracts.rename["id_contrato"] == "contract_id"
    assert spec.processes.identity_key == "id_del_portafolio"
    assert spec.processes.rename["id_del_portafolio"] == "process_id"
    assert "valor_pagado" in spec.contracts.snapshot_state_columns
