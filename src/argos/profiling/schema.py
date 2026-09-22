from __future__ import annotations

from pathlib import Path

import pandas as pd

from argos.common.duckdb import connect
from argos.common.names import normalize_name
from argos.common.sql import csv_source, quote_identifier


def classify_semantic_type(column: str, physical_type: str | None = None) -> str:
    """Infer a preliminary semantic role from the column name.

    This is intentionally conservative. Bronze profiling must not assume
    business types solely from CSV auto-detection.
    """
    name = normalize_name(column)

    pii_tokens = [
        "numero_de_cuenta",
        "identificacion_representante",
        "documento_supervisor",
        "documento_ordenador",
        "numero_de_documento",
    ]
    if any(token in name for token in pii_tokens):
        return "pii"

    if "fecha" in name or "timestamp" in name:
        return "date"

    identifier_tokens = [
        "id_",
        "_id",
        "codigo",
        "nit",
        "documento_proveedor",
        "referencia",
        "pci",
    ]
    if (
        name.startswith("id_")
        or name.endswith("_id")
        or any(token in name for token in identifier_tokens)
    ):
        return "identifier"

    if any(
        token in name
        for token in ["valor", "saldo", "presupuesto", "monto"]
    ):
        return "money"

    if any(
        token in name
        for token in ["descripcion", "objeto", "justificacion", "detalle"]
    ):
        return "text"

    if any(
        token in name
        for token in [
            "departamento",
            "municipio",
            "ciudad",
            "localizacion",
            "direccion",
        ]
    ):
        return "geography"

    if name.startswith("es_") or name.startswith("habilita_"):
        return "boolean"

    return "category_or_text"


def preliminary_temporal_role(column: str) -> tuple[str, str]:
    """Return preliminary temporal and leakage classifications.

    These are triage hints only. Notebook 04 must validate temporal
    availability before a field is approved for modeling.
    """
    name = normalize_name(column)

    if name in {
        "fecha_de_firma",
        "fecha_firma",
        "fecha_adjudicacion",
    }:
        return "candidate_prediction_timestamp", "review"

    high_risk_tokens = [
        "dias_adicionados",
        "valor_pagado",
        "valor_facturado",
        "pendiente_de_pago",
        "pendiente_de_ejecucion",
        "liquidacion",
        "sancion",
        "multa",
        "prorroga",
        "ultima_actualizacion",
        "valor_amortizado",
    ]

    if any(token in name for token in high_risk_tokens):
        return "likely_post_t0_or_mutable", "high"

    if name == "estado_contrato":
        return "mutable_snapshot_state", "high"

    return "unknown_until_temporal_audit", "review"


def _bronze_source(
    path: Path,
    *,
    sample_size: int,
) -> str:
    """Return the canonical DuckDB reader for Bronze schema profiling.

    Bronze values are intentionally read as VARCHAR. Type inference is
    deferred until the data has been profiled and explicit Silver schemas
    can be defined.
    """
    return csv_source(
        path,
        sample_size=sample_size,
        all_varchar=True,
        parallel=False,
        null_padding=False,
        strict_mode=True,
        ignore_errors=False,
    )


def _describe(
    con,
    path: Path,
    sample_size: int,
) -> tuple[pd.DataFrame, str]:
    """Describe the raw Bronze schema without type coercion."""
    source = _bronze_source(
        path,
        sample_size=sample_size,
    )

    schema = con.execute(
        f"DESCRIBE SELECT * FROM {source}"
    ).fetchdf()

    return schema, "all_varchar_bronze"


def profile_dataset_columns(
    dataset: str,
    path: Path,
    *,
    sample_size: int = 100_000,
    example_rows: int = 2_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Profile the raw columns of one Bronze dataset.

    The function deliberately avoids automatic CSV type coercion.

    It measures structural properties of the raw source:

    - row count;
    - null count/rate;
    - approximate cardinality;
    - representative values;
    - preliminary semantic role;
    - preliminary temporal/leakage risk.

    Numerical and temporal validity are audited separately in later M1
    notebooks.
    """
    con = connect(temp_directory=temp_directory)

    try:
        schema, parse_mode = _describe(
            con,
            path,
            sample_size,
        )

        columns = schema["column_name"].tolist()

        # Bronze raw storage representation.
        physical_types = {
            column: str(column_type)
            for column, column_type in zip(
                schema["column_name"],
                schema["column_type"],
                strict=True,
            )
        }

        source = _bronze_source(
            path,
            sample_size=sample_size,
        )

        expressions: list[str] = [
            "COUNT(*) AS __rows"
        ]

        for idx, column in enumerate(columns):
            quoted = quote_identifier(column)

            expressions.append(
                f"COUNT(*) FILTER "
                f"(WHERE {quoted} IS NULL) "
                f"AS c{idx}__nulls"
            )

            expressions.append(
                f"APPROX_COUNT_DISTINCT({quoted}) "
                f"AS c{idx}__distinct"
            )

        aggregate_query = (
            f"SELECT {', '.join(expressions)} "
            f"FROM {source}"
        )

        aggregate = (
            con.execute(aggregate_query)
            .fetchdf()
            .iloc[0]
            .to_dict()
        )

        row_count = int(aggregate["__rows"])

        sample = con.execute(
            f"""
            SELECT *
            FROM {source}
            LIMIT {int(example_rows)}
            """
        ).fetchdf()

        records: list[dict[str, object]] = []

        for idx, column in enumerate(columns):
            examples: list[str] = []

            if column in sample.columns:
                unique_examples = (
                    sample[column]
                    .dropna()
                    .astype(str)
                    .drop_duplicates()
                    .head(3)
                )

                examples = [
                    value[:160]
                    for value in unique_examples
                ]

            temporal_role, leakage_risk = (
                preliminary_temporal_role(column)
            )

            null_count = int(
                aggregate[f"c{idx}__nulls"]
            )

            records.append(
                {
                    "dataset": dataset,
                    "column": column,
                    "normalized_column": normalize_name(column),

                    # At Bronze level this represents the raw
                    # storage/parser type, not the final business type.
                    "physical_type": physical_types[column],

                    "semantic_type": classify_semantic_type(
                        column
                    ),

                    "row_count": row_count,
                    "null_count": null_count,
                    "null_rate": (
                        null_count / row_count
                        if row_count
                        else None
                    ),
                    "approx_distinct_count": int(
                        aggregate[
                            f"c{idx}__distinct"
                        ]
                        or 0
                    ),

                    # Min/max are intentionally deferred.
                    # Lexicographical min/max over VARCHAR would be
                    # misleading for dates and monetary values.
                    "min_value": None,
                    "max_value": None,

                    "example_values": examples,
                    "temporal_role_hint": temporal_role,
                    "leakage_risk_hint": leakage_risk,
                    "parse_mode": parse_mode,
                }
            )

        return pd.DataFrame.from_records(records)

    finally:
        con.close()


def profile_all_datasets(
    files: dict[str, Path],
    *,
    sample_size: int = 100_000,
    example_rows: int = 2_000,
    temp_directory: Path | None = None,
) -> pd.DataFrame:
    """Profile every discovered Bronze dataset."""
    frames: list[pd.DataFrame] = []

    for dataset, path in files.items():
        profile = profile_dataset_columns(
            dataset,
            path,
            sample_size=sample_size,
            example_rows=example_rows,
            temp_directory=temp_directory,
        )

        frames.append(profile)

    if not frames:
        return pd.DataFrame()

    return pd.concat(
        frames,
        ignore_index=True,
    )