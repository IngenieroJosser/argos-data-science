\
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name
from argos.common.sql import csv_source, quote_identifier


_NUMERIC_TYPES = ("INT", "DECIMAL", "DOUBLE", "FLOAT", "REAL", "HUGEINT", "UBIGINT")
_DATE_TYPES = ("DATE", "TIMESTAMP", "TIME")


def classify_semantic_type(column: str, physical_type: str) -> str:
    name = normalize_name(column)
    ptype = physical_type.upper()
    if any(token in name for token in ["numero_de_cuenta", "identificacion_representante", "documento_supervisor", "documento_ordenador"]):
        return "pii"
    if "fecha" in name or "timestamp" in name or any(t in ptype for t in _DATE_TYPES):
        return "date"
    if name.startswith("id_") or name.endswith("_id") or "codigo" in name or name in {"nit", "documento_proveedor"} or "referencia" in name:
        return "identifier"
    if any(token in name for token in ["valor", "saldo", "presupuesto", "monto"]):
        return "money"
    if any(token in name for token in ["descripcion", "objeto", "justificacion", "detalle"]):
        return "text"
    if any(token in name for token in ["departamento", "municipio", "ciudad", "localizacion", "direccion"]):
        return "geography"
    if ptype == "BOOLEAN" or name.startswith("es_") or name.startswith("habilita_"):
        return "boolean"
    if any(t in ptype for t in _NUMERIC_TYPES):
        return "numeric"
    return "category_or_text"


def preliminary_temporal_role(column: str) -> tuple[str, str]:
    """Return (temporal_role_hint, leakage_risk_hint).

    These are triage hints, not final scientific decisions. Notebook 04 plus domain
    documentation must approve every feature before model use.
    """
    name = normalize_name(column)
    if name in {"fecha_de_firma", "fecha_firma", "fecha_adjudicacion"}:
        return "candidate_prediction_timestamp", "review"

    high_risk_tokens = [
        "dias_adicionados", "valor_pagado", "valor_facturado", "pendiente_de_pago",
        "pendiente_de_ejecucion", "liquidacion", "sancion", "multa", "prorroga",
        "ultima_actualizacion", "valor_amortizado",
    ]
    if any(token in name for token in high_risk_tokens):
        return "likely_post_t0_or_mutable", "high"
    if name == "estado_contrato":
        return "mutable_snapshot_state", "high"
    return "unknown_until_temporal_audit", "review"


def _describe(con, path: Path, sample_size: int) -> tuple[pd.DataFrame, str]:
    inferred = csv_source(path, sample_size=sample_size)
    try:
        return con.execute(f"DESCRIBE SELECT * FROM {inferred}").fetchdf(), "inferred"
    except Exception:
        fallback = csv_source(path, sample_size=sample_size, all_varchar=True)
        return con.execute(f"DESCRIBE SELECT * FROM {fallback}").fetchdf(), "all_varchar_fallback"


def profile_dataset_columns(
    dataset: str,
    path: Path,
    *,
    sample_size: int = 100_000,
    example_rows: int = 2_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Profile all columns with one aggregate scan plus a small head sample."""
    con = connect(temp_directory=temp_directory)
    schema, parse_mode = _describe(con, path, sample_size)
    columns = schema["column_name"].tolist()
    physical_types = dict(zip(schema["column_name"], schema["column_type"], strict=True))

    source = csv_source(path, sample_size=sample_size, all_varchar=(parse_mode != "inferred"))
    expressions: list[str] = ["COUNT(*) AS __rows"]
    for idx, column in enumerate(columns):
        q = quote_identifier(column)
        expressions.append(f"COUNT(*) FILTER (WHERE {q} IS NULL) AS c{idx}__nulls")
        expressions.append(f"APPROX_COUNT_DISTINCT({q}) AS c{idx}__distinct")
        ptype = str(physical_types[column]).upper()
        if any(token in ptype for token in (*_NUMERIC_TYPES, *_DATE_TYPES)):
            expressions.append(f"MIN({q}) AS c{idx}__min")
            expressions.append(f"MAX({q}) AS c{idx}__max")

    aggregate = con.execute(
        f"SELECT {', '.join(expressions)} FROM {source}"
    ).fetchdf().iloc[0].to_dict()
    row_count = int(aggregate["__rows"])

    sample = con.execute(f"SELECT * FROM {source} LIMIT {int(example_rows)}").fetchdf()

    records: list[dict[str, object]] = []
    for idx, column in enumerate(columns):
        values: list[str] = []
        if column in sample.columns:
            for value in sample[column].dropna().astype(str).drop_duplicates().head(3):
                values.append(value[:160])
        role, leakage = preliminary_temporal_role(column)
        nulls = int(aggregate[f"c{idx}__nulls"])
        records.append(
            {
                "dataset": dataset,
                "column": column,
                "normalized_column": normalize_name(column),
                "physical_type": physical_types[column],
                "semantic_type": classify_semantic_type(column, str(physical_types[column])),
                "row_count": row_count,
                "null_count": nulls,
                "null_rate": (nulls / row_count) if row_count else None,
                "approx_distinct_count": int(aggregate[f"c{idx}__distinct"] or 0),
                "min_value": aggregate.get(f"c{idx}__min"),
                "max_value": aggregate.get(f"c{idx}__max"),
                "example_values": values,
                "temporal_role_hint": role,
                "leakage_risk_hint": leakage,
                "parse_mode": parse_mode,
            }
        )
    return pd.DataFrame.from_records(records)


def profile_all_datasets(
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    example_rows: int = 2_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    frames = [
        profile_dataset_columns(
            dataset,
            path,
            sample_size=sample_size,
            example_rows=example_rows,
            temp_directory=temp_directory,
        )
        for dataset, path in files.items()
    ]
    return pd.concat(frames, ignore_index=True)
