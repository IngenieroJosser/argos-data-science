from pathlib import Path

from argos.config.silver import load_silver_spec


def test_silver_spec_includes_m2_components() -> None:
    spec = load_silver_spec(Path("configs/silver.toml"))

    assert spec.suppliers.primary_key == "codigo"
    assert spec.suppliers.rename["codigo"] == "supplier_code"
    assert spec.bidders.process_key == "id_procedimiento"
    assert spec.bidders.nit_candidate == "nit_proveedor"
    assert spec.additions.event_time == "fecharegistro"
    assert spec.additions.rename["tipo"] == "event_type"
    assert spec.validation.bidders_processes_min_coverage == 0.95
    assert spec.validation.additions_contracts_min_coverage == 0.99
    assert spec.entity_resolution.code_strategy_enabled is True
    assert spec.entity_resolution.nit_strategy_enabled is True
