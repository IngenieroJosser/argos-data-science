from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.names import normalize_name
from argos.config.registry import DatasetSpec
from argos.config.silver import load_silver_spec
from argos.silver.contracts_processes import build_contracts_processes_silver


def _dataset_spec(key: str, source_id: str) -> DatasetSpec:
    return DatasetSpec(
        key=key,
        source_id=source_id,
        name=key,
        match_tokens=(),
        source_url="https://example.invalid",
        candidate_keys=(),
    )


def test_build_contracts_processes_silver_preserves_grain_and_segregates_state(
    tmp_path: Path,
) -> None:
    bronze = tmp_path / "data" / "bronze"
    bronze.mkdir(parents=True)
    reports = tmp_path / "reports"
    (reports / "profiling").mkdir(parents=True)
    silver = tmp_path / "data" / "silver"
    manifests = tmp_path / "artifacts" / "manifests"

    spec = load_silver_spec(Path("configs/silver.toml"))

    contracts_path = bronze / "SECOP_II_-_Contratos_Electrónicos_20260921.csv"
    contracts_rows = pd.DataFrame(
        [
            {
                "ID Contrato": "C1",
                "Proceso de Compra": "P1",
                "Codigo Proveedor": "S1",
                "Fecha de Firma": "01/10/2022",
                "Estado Contrato": "Activo",
                "Valor Pagado": "$1.000.000",
                "Numero de Documento": "123",
            },
            {
                "ID Contrato": "C2",
                "Proceso de Compra": "P2",
                "Codigo Proveedor": "S2",
                "Fecha de Firma": "02/15/2022",
                "Estado Contrato": "Cerrado",
                "Valor Pagado": "$2.000.000",
                "Numero de Documento": "456",
            },
        ]
    )
    # Keep this fixture aligned with the frozen Silver contract. Snapshot-state
    # columns are part of the required Bronze schema even when a synthetic row
    # does not need a value for every one of them.
    existing_normalized = {normalize_name(column) for column in contracts_rows}
    for normalized in spec.contracts.snapshot_state_columns:
        if normalized in existing_normalized:
            continue
        contracts_rows[normalized.replace("_", " ").title()] = None
    contracts_rows.to_csv(contracts_path, index=False)

    processes_path = bronze / "SECOP_II_-_Procesos_de_Contratación_20260921.csv"
    processes_path.write_text(
        "ID del Portafolio,ID del Proceso,Referencia del Proceso,"
        "Fecha de Publicacion del Proceso,Precio Base,Fase\n"
        "P1,REQ1,R1,01/01/2022,$10.000.000,Oferta\n"
        "P1,REQ1,R1,01/01/2022,$10.000.000,Oferta\n"
        "P1,REQ1,R1,01/02/2022,$10.000.000,Adjudicado\n"
        "P2,REQ2,R2,02/01/2022,$20.000.000,Oferta\n",
        encoding="utf-8",
    )

    profile = pd.DataFrame(
        [
            ("contracts", "ID Contrato", "id_contrato", "identifier", "review"),
            ("contracts", "Proceso de Compra", "proceso_de_compra", "identifier", "review"),
            ("contracts", "Codigo Proveedor", "codigo_proveedor", "identifier", "review"),
            ("contracts", "Fecha de Firma", "fecha_de_firma", "date", "review"),
            ("contracts", "Estado Contrato", "estado_contrato", "category_or_text", "high"),
            ("contracts", "Valor Pagado", "valor_pagado", "money", "high"),
            ("contracts", "Numero de Documento", "numero_de_documento", "pii", "review"),
            ("processes", "ID del Portafolio", "id_del_portafolio", "identifier", "review"),
            ("processes", "ID del Proceso", "id_del_proceso", "identifier", "review"),
            (
                "processes",
                "Referencia del Proceso",
                "referencia_del_proceso",
                "identifier",
                "review",
            ),
            (
                "processes",
                "Fecha de Publicacion del Proceso",
                "fecha_de_publicacion_del_proceso",
                "date",
                "review",
            ),
            ("processes", "Precio Base", "precio_base", "money", "review"),
            ("processes", "Fase", "fase", "category_or_text", "review"),
        ],
        columns=[
            "dataset",
            "column",
            "normalized_column",
            "semantic_type",
            "leakage_risk_hint",
        ],
    )
    profile_path = reports / "profiling" / "column_profile.parquet"
    profile.to_parquet(profile_path, index=False)

    pd.DataFrame(
        [
            {"dataset": "contracts", "row_count": 2},
            {"dataset": "processes", "row_count": 4},
        ]
    ).to_parquet(reports / "profiling" / "dataset_inventory.parquet", index=False)

    pd.DataFrame(
        [
            {
                "dataset": "processes",
                "candidate_key": "id_del_portafolio",
                "status": "analyzed",
                "distinct_nonnull_keys": 2,
            }
        ]
    ).to_parquet(reports / "profiling" / "key_analysis.parquet", index=False)

    pd.DataFrame(
        [
            {
                "dataset": "contracts",
                "normalized_column": "fecha_de_firma",
                "raw_nonnull_count": 2,
                "parsed_count": 2,
            }
        ]
    ).to_parquet(reports / "profiling" / "temporal_profile.parquet", index=False)

    result = build_contracts_processes_silver(
        contracts_path,
        processes_path,
        contracts_spec=_dataset_spec("contracts", "jbjy-vk9h"),
        processes_spec=_dataset_spec("processes", "p6dx-8zbt"),
        column_profile_path=profile_path,
        reports_root=reports,
        silver_dir=silver,
        manifest_dir=manifests,
        silver_spec=spec,
        date_order="mdy",
        temp_directory=tmp_path / ".cache" / "duckdb",
        overwrite=True,
    )

    assert result.ready_for_next_notebook

    contracts = pd.read_parquet(result.artifacts["contracts"])
    state = pd.read_parquet(result.artifacts["contracts_snapshot_state"])
    versions = pd.read_parquet(result.artifacts["process_versions"])
    processes = pd.read_parquet(result.artifacts["processes"])
    links = pd.read_parquet(result.artifacts["contract_process_links"])

    assert contracts["contract_id"].tolist() == ["C1", "C2"]
    assert "estado_contrato" not in contracts.columns
    assert "valor_pagado" not in contracts.columns
    assert "numero_de_documento" not in contracts.columns
    assert {"estado_contrato", "valor_pagado"}.issubset(state.columns)

    assert len(versions) == 3
    assert versions["_source_row_count"].sum() == 4
    assert len(processes) == 2
    assert processes.set_index("process_id").loc["P1", "version_count"] == 2

    assert len(links) == 2
    assert set(links["link_status"]) == {"matched"}
