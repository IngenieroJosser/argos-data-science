from __future__ import annotations

import json
from pathlib import Path

import duckdb

from argos.serving.m9 import build_m9_serving


def _write_parquet(path: Path, sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")
    try:
        escaped = str(path).replace("'", "''")
        con.execute(f"COPY ({sql}) TO '{escaped}' (FORMAT PARQUET)")
    finally:
        con.close()


def test_build_m9_serving_preserves_scoring_and_enriches_contracts(tmp_path: Path) -> None:
    root = tmp_path
    scored = root / "data/production/scored_batches/batch-test.parquet"
    fresh = root / "data/m5/fresh_oot_2026.parquet"
    contracts = root / "data/silver/contracts.parquet"
    suppliers = root / "data/silver/suppliers.parquet"

    _write_parquet(
        scored,
        """
        SELECT * FROM (VALUES
          ('C1', TIMESTAMP '2026-01-10', 0.13, 0.99, 1, TRUE),
          ('C2', TIMESTAMP '2026-01-11', 0.08, 0.80, 2, FALSE),
          ('C3', TIMESTAMP '2026-01-12', 0.01, 0.20, 3, FALSE)
        ) t(contract_id,t0,score,raw_score,rank,review_priority)
        """,
    )
    _write_parquet(
        fresh,
        """
        SELECT * FROM (VALUES
          ('C1','Antioquia','Medellín','Contratación directa',24,387,6,912,17,1),
          ('C2','Bogotá D.C.','Bogotá','Licitación pública',4,100,0,300,80,0),
          ('C3','Valle del Cauca','Cali','Selección abreviada',2,20,0,90,12,0)
        ) t(contract_id,departamento,ciudad,modalidad_de_contratacion,
            prior_supplier_contract_count,prior_entity_contract_count,
            prior_supplier_entity_contract_count,supplier_tenure_days,
            days_since_supplier_last_contract,y_addition_180d)
        """,
    )
    _write_parquet(
        contracts,
        """
        SELECT * FROM (VALUES
          ('C1','P1','S1','9001','Instituto Alfa','Objeto contractual uno'),
          ('C2','P2','S2','9002','Entidad Beta','Objeto contractual dos'),
          ('C3','P3','S3','9003','Entidad Gamma','Objeto contractual tres')
        ) t(contract_id,process_id,supplier_code,nit_entidad,nombre_entidad,
            objeto_del_contrato)
        """,
    )
    _write_parquet(
        suppliers,
        """
        SELECT * FROM (VALUES
          ('S1','Proveedor Uno'),('S2','Proveedor Dos'),('S3','Proveedor Tres')
        ) t(supplier_code,nombre)
        """,
    )

    manifests = root / "artifacts/manifests"
    manifests.mkdir(parents=True)
    (manifests / "m6_scoring_batch-test.json").write_text(
        json.dumps(
            {
                "batch_id": "batch-test",
                "rows": 3,
                "input": str(fresh),
                "output": str(scored),
                "built_at_utc": "2026-09-25T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    result = build_m9_serving(root=root)
    assert result.row_count == 3

    con = duckdb.connect(database=str(result.database_path), read_only=True)
    try:
        row = con.execute(
            """
            SELECT entity_name, supplier_name, departamento,
                   modalidad_de_contratacion, score, rank,
                   prior_supplier_contract_count,
                   prior_entity_contract_count,
                   prior_supplier_entity_contract_count,
                   supplier_tenure_days,
                   days_since_supplier_last_contract
            FROM contracts WHERE contract_id='C1'
            """
        ).fetchone()
        columns = {r[0] for r in con.execute("DESCRIBE contracts").fetchall()}
    finally:
        con.close()

    assert row == (
        "Instituto Alfa",
        "Proveedor Uno",
        "Antioquia",
        "Contratación directa",
        0.13,
        1,
        24,
        387,
        6,
        912,
        17,
    )
    assert "y_addition_180d" not in columns

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["scientific_artifacts_mutated"] is False
    assert manifest["read_only_sources"] is True
