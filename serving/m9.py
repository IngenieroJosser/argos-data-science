from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import shutil
from typing import Any

import duckdb
import pandas as pd

from argos.common.sql import quote_identifier, sql_string

M9_SCHEMA_VERSION = "m9-serving-v1"
BUILD_IMPLEMENTATION = "m9-serving-read-only-v1"

DISPLAY_ENTITY_CANDIDATES = (
    "nombre_entidad",
    "nombre_de_la_entidad",
    "entidad",
    "entidad_compradora",
    "nombre_entidad_compradora",
)
DISPLAY_SUPPLIER_CONTRACT_CANDIDATES = (
    "nombre_proveedor",
    "proveedor_adjudicado",
    "proveedor",
    "nombre_del_proveedor",
    "razon_social_proveedor",
)
DISPLAY_SUPPLIER_DIM_CANDIDATES = (
    "nombre",
    "nombre_proveedor",
    "proveedor",
    "razon_social",
    "nombre_razon_social",
)
CONTRACT_OBJECT_CANDIDATES = (
    "objeto_del_contrato",
    "objeto_contrato",
    "descripcion_del_contrato",
    "objeto",
)

SAFE_CONTEXT_COLUMNS = (
    "prior_supplier_contract_count",
    "prior_entity_contract_count",
    "prior_supplier_entity_contract_count",
    "prior_supplier_addition_event_count",
    "prior_entity_addition_event_count",
    "prior_supplier_entity_addition_event_count",
    "prior_supplier_contracts_with_addition",
    "observed_supplier_addition_contract_share_before_t0",
    "supplier_tenure_days",
    "entity_tenure_days",
    "days_since_supplier_last_contract",
    "days_since_entity_last_contract",
    "bidder_count_before_t0",
    "unique_resolved_supplier_count_before_t0",
    "bidder_entity_resolution_rate_before_t0",
)

SAFE_CONTRACT_COLUMNS = (
    "departamento",
    "ciudad",
    "sector",
    "rama",
    "orden",
    "tipo_de_contrato",
    "modalidad_de_contratacion",
    "justificacion_modalidad_de_contratacion",
    "codigo_de_categoria_principal",
    "entidad_centralizada",
    "es_grupo",
    "es_pyme",
)

FORBIDDEN_OUTPUT_COLUMNS = {
    "y_addition_180d",
    "eligible",
    "label_cutoff",
    "first_qualifying_event_at",
    "estado_contrato",
    "dias_adicionados",
    "valor_pagado",
    "valor_facturado",
    "valor_amortizado",
    "valor_pendiente_de_ejecucion",
    "valor_pendiente_de_pago",
    "correo",
    "direccion",
    "telefono",
    "numero_de_cuenta",
    "numero_doc_representante_legal",
}


@dataclass(frozen=True, slots=True)
class ServingBuildResult:
    database_path: Path
    overview_path: Path
    manifest_path: Path
    validation_path: Path
    row_count: int
    batch_id: str


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_scoring_manifest(root: Path) -> tuple[Path, dict[str, Any]]:
    candidates = list((root / "artifacts" / "manifests").glob("m6_scoring_*.json"))
    if not candidates:
        raise FileNotFoundError("No M6 scoring manifest was found")

    def key(path: Path) -> tuple[str, float]:
        payload = _read_json(path, {})
        return str(payload.get("built_at_utc", "")), path.stat().st_mtime

    selected = max(candidates, key=key)
    return selected, _read_json(selected, {})


def _resolve_manifest_path(root: Path, value: str | None, fallback: Path) -> Path:
    if value:
        raw = Path(value).expanduser()
        if raw.exists():
            return raw.resolve()
        parts = raw.parts
        for anchor in ("data", "reports", "artifacts"):
            if anchor in parts:
                index = parts.index(anchor)
                candidate = root.joinpath(*parts[index:])
                if candidate.exists():
                    return candidate.resolve()
    if fallback.exists():
        return fallback.resolve()
    return fallback


def _columns(con: duckdb.DuckDBPyConnection, path: Path) -> set[str]:
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet({sql_string(str(path))})"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _pick(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in columns:
            return name
    return None


def _text_expr(alias: str, column: str | None) -> str:
    if column is None:
        return "CAST(NULL AS VARCHAR)"
    q = quote_identifier(column)
    return f"NULLIF(TRIM(CAST({alias}.{q} AS VARCHAR)), '')"


def _source(alias: str, path: Path) -> str:
    return f"read_parquet({sql_string(str(path))}) AS {alias}"


def _scalar(con: duckdb.DuckDBPyConnection, query: str) -> Any:
    return con.execute(query).fetchone()[0]


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            pass
    return value


def _parquet_first_row(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    con = duckdb.connect(database=":memory:")
    try:
        frame = con.execute(
            f"SELECT * FROM read_parquet({sql_string(str(path))}) LIMIT 1"
        ).fetchdf()
    finally:
        con.close()
    if frame.empty:
        return {}
    return {str(k): _jsonable(v) for k, v in frame.iloc[0].to_dict().items()}


def _ranking_at_one_percent(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    con = duckdb.connect(database=":memory:")
    try:
        frame = con.execute(
            f"""
            SELECT *
            FROM read_parquet({sql_string(str(path))})
            ORDER BY ABS(CAST(review_fraction AS DOUBLE) - 0.01)
            LIMIT 1
            """
        ).fetchdf()
    finally:
        con.close()
    if frame.empty:
        return {}
    return {str(k): _jsonable(v) for k, v in frame.iloc[0].to_dict().items()}


def _parquet_records(
    path: Path,
    *,
    limit: int = 25,
    order_by: str | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    order = f" ORDER BY {order_by}" if order_by else ""
    con = duckdb.connect(database=":memory:")
    try:
        frame = con.execute(
            f"SELECT * FROM read_parquet({sql_string(str(path))}){order} LIMIT {int(limit)}"
        ).fetchdf()
    finally:
        con.close()
    return [
        {str(k): _jsonable(v) for k, v in row.items()}
        for row in frame.to_dict("records")
    ]


def _overview_payload(
    *,
    root: Path,
    db_path: Path,
    batch_id: str,
    scoring_manifest: dict[str, Any],
    coverage: dict[str, float],
) -> dict[str, Any]:
    registry = _read_json(root / "artifacts" / "registry" / "argos_v1.json", {})
    deployment = _read_json(root / "artifacts" / "registry" / "deployment_state.json", {})
    monitoring = _read_json(root / "artifacts" / "manifests" / "m6_monitoring.json", {})
    queue = _read_json(root / "artifacts" / "manifests" / "m6_human_review_queue.json", {})
    m7 = _read_json(root / "artifacts" / "manifests" / "m7_protocol_freeze.json", {})
    m8 = _read_json(root / "artifacts" / "manifests" / "m8_feature_selection.json", {})
    survival = _read_json(root / "artifacts" / "manifests" / "m8_survival.json", {})

    score_drift = _parquet_first_row(root / "reports" / "production" / "53_score_drift.parquet")
    test_metrics = _parquet_first_row(
        root / "reports" / "modeling" / "36_final_test_metrics.parquet"
    )
    test_ranking = _ranking_at_one_percent(
        root / "reports" / "modeling" / "36_business_capacity_curve.parquet"
    )
    oot_metrics = _parquet_first_row(
        root / "reports" / "robustness" / "45_fresh_oot_metrics.parquet"
    )
    oot_ranking = _ranking_at_one_percent(
        root / "reports" / "robustness" / "45_fresh_oot_ranking.parquet"
    )

    con = duckdb.connect(database=str(db_path), read_only=True)
    try:
        counts = con.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE priority = 'Alta') AS high_count,
                COUNT(*) FILTER (WHERE priority = 'Media') AS medium_count,
                COUNT(*) FILTER (WHERE priority = 'Baja') AS low_count
            FROM contracts
            """
        ).fetchone()
        trend_frame = con.execute(
            """
            SELECT
                STRFTIME(t0, '%Y-%m') AS month,
                COUNT(*)::BIGINT AS total,
                COUNT(*) FILTER (
                    WHERE rank <= CEIL((SELECT COUNT(*) FROM contracts) * 0.05)
                )::BIGINT AS focus,
                AVG(score)::DOUBLE AS meanScore
            FROM contracts
            WHERE t0 IS NOT NULL
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchdf()
    finally:
        con.close()

    trend: list[dict[str, Any]] = []
    for row in trend_frame.to_dict("records"):
        total = int(row["total"])
        focus = int(row["focus"])
        trend.append(
            {
                "month": str(row["month"]),
                "total": total,
                "focus": focus,
                "focusPct": (100.0 * focus / total) if total else 0.0,
                "meanScore": float(row["meanScore"] or 0.0),
            }
        )

    total, high_count, medium_count, low_count = [int(value or 0) for value in counts]
    review_fraction = high_count / total if total else 0.0
    return {
        "schemaVersion": M9_SCHEMA_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {
            "batchId": batch_id,
            "modelVersion": registry.get("model_version", "argos-v1"),
            "modelStage": deployment.get("stage", registry.get("stage")),
            "scoringMode": registry.get("scoring_mode", "batch"),
            "dataMode": "serving-materialized",
            "scoringRows": int(scoring_manifest.get("rows") or total),
        },
        "overview": {
            "scoredContracts": total,
            "reviewQueueRows": int(queue.get("rows", high_count)),
            "reviewFraction": review_fraction,
            "highCount": high_count,
            "mediumCount": medium_count,
            "lowCount": low_count,
            "alerts": int(monitoring.get("alerts", 0)),
            "highAlerts": int(monitoring.get("high_alerts", 0)),
            "scorePsi": _jsonable(score_drift.get("score_psi")),
            "promotionBlocked": bool(deployment.get("promotion_blocked", False)),
            "blockReason": deployment.get("block_reason"),
            "operationalStatus": (
                "OPERATIONALLY_READY_PROMOTION_BLOCKED"
                if deployment.get("promotion_blocked")
                else "OPERATIONALLY_READY"
            ),
        },
        "governance": {
            "humanReviewRequired": bool(m7.get("human_review_required", True)),
            "productionPromotionAuthorized": bool(
                registry.get("production_promotion_authorized", False)
            ),
            "m7Status": "ACTIVE / EVIDENCE PENDING",
            "m7ProtocolId": m7.get("protocol_id"),
            "m7ProspectiveStart": m7.get("prospective_start"),
            "m7HorizonDays": m7.get("target_horizon_days"),
            "m8Status": "CLOSED",
            "m8Decision": m8.get("decision"),
            "m8SelectedFamily": m8.get("selected_family"),
        },
        "performance": {
            "test2025": {
                **test_metrics,
                **{f"ranking_{key}": value for key, value in test_ranking.items()},
            },
            "oot2026": {
                **oot_metrics,
                **{f"ranking_{key}": value for key, value in oot_ranking.items()},
            },
        },
        "advanced": {
            "decision": m8.get("decision"),
            "baselinePrAuc": m8.get("baseline_pr_auc"),
            "baselineLiftAtK": m8.get("baseline_lift_at_operational_k"),
            "comparisons": m8.get("comparisons", []),
            "survival": {
                "validationCIndex": survival.get("validation_c_index"),
                "meanValidationBrier": survival.get("mean_validation_brier"),
                "horizons": survival.get("evaluation_horizons", []),
                "trainEvents": survival.get("train_events"),
                "validationEvents": survival.get("validation_events"),
            },
        },
        "trend": trend,
        "coverage": coverage,
        "disclaimer": (
            "ARGOS prioriza casos para revisión analítica adicional. Sus scores, "
            "anomalías y relaciones no constituyen una acusación ni una conclusión "
            "jurídica de fraude o corrupción."
        ),
    }


def build_m9_serving(
    *,
    root: Path,
    output_dir: Path | None = None,
    overwrite: bool = True,
) -> ServingBuildResult:
    root = root.expanduser().resolve()
    if output_dir is None:
        output_dir = root / "data" / "serving" / "m9"
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    _, scoring_manifest = _latest_scoring_manifest(root)
    batch_id = str(scoring_manifest.get("batch_id") or "").strip()
    if not batch_id:
        raise ValueError("Latest M6 scoring manifest does not contain batch_id")

    scored_path = _resolve_manifest_path(
        root,
        scoring_manifest.get("output"),
        root / "data" / "production" / "scored_batches" / f"{batch_id}.parquet",
    )
    input_path = _resolve_manifest_path(
        root,
        scoring_manifest.get("input"),
        root / "data" / "m5" / "fresh_oot_2026.parquet",
    )
    contracts_path = root / "data" / "silver" / "contracts.parquet"
    suppliers_path = root / "data" / "silver" / "suppliers.parquet"

    required = {
        "scored_batch": scored_path,
        "scoring_input": input_path,
        "silver_contracts": contracts_path,
    }
    missing = {name: str(path) for name, path in required.items() if not path.exists()}
    if missing:
        raise FileNotFoundError(
            "M9 serving requires the existing ARGOS runtime artifacts: "
            + json.dumps(missing, ensure_ascii=False)
        )

    database_path = output_dir / "argos-serving.duckdb"
    temp_path = output_dir / ".argos-serving.tmp.duckdb"
    overview_path = output_dir / "overview.json"
    manifest_path = output_dir / "manifest.json"
    validation_path = root / "reports" / "serving" / "m9_serving_validation.parquet"

    if temp_path.exists():
        temp_path.unlink()
    if database_path.exists() and not overwrite:
        raise FileExistsError(database_path)

    source_con = duckdb.connect(database=":memory:")
    try:
        scored_columns = _columns(source_con, scored_path)
        input_columns = _columns(source_con, input_path)
        contract_columns = _columns(source_con, contracts_path)
        supplier_columns = (
            _columns(source_con, suppliers_path) if suppliers_path.exists() else set()
        )
    finally:
        source_con.close()

    for name in ["contract_id", "t0", "score", "raw_score", "rank"]:
        if name not in scored_columns:
            raise KeyError(f"Scored batch is missing required column: {name}")
    if "contract_id" not in input_columns:
        raise KeyError("Scoring input is missing contract_id")
    if "contract_id" not in contract_columns:
        raise KeyError("Silver contracts is missing contract_id")

    entity_name_col = _pick(contract_columns, DISPLAY_ENTITY_CANDIDATES)
    supplier_contract_col = _pick(contract_columns, DISPLAY_SUPPLIER_CONTRACT_CANDIDATES)
    supplier_dim_col = _pick(supplier_columns, DISPLAY_SUPPLIER_DIM_CANDIDATES)
    object_col = _pick(contract_columns, CONTRACT_OBJECT_CANDIDATES)

    select_parts = [
        "s.contract_id",
        "s.t0",
        "CAST(s.score AS DOUBLE) AS score",
        "CAST(s.raw_score AS DOUBLE) AS raw_score",
        "CAST(s.rank AS BIGINT) AS rank",
        "CAST(COALESCE(s.review_priority, FALSE) AS BOOLEAN) AS review_priority"
        if "review_priority" in scored_columns
        else "CAST(FALSE AS BOOLEAN) AS review_priority",
    ]

    if "process_id" in contract_columns:
        select_parts.append("CAST(c.process_id AS VARCHAR) AS process_id")
    else:
        select_parts.append("CAST(NULL AS VARCHAR) AS process_id")
    if "supplier_code" in contract_columns:
        select_parts.append("CAST(c.supplier_code AS VARCHAR) AS supplier_code")
    else:
        select_parts.append("CAST(NULL AS VARCHAR) AS supplier_code")

    entity_id_source = "nit_entidad" if "nit_entidad" in contract_columns else None
    if entity_id_source:
        select_parts.append(
            f"CAST(c.{quote_identifier(entity_id_source)} AS VARCHAR) AS entity_id"
        )
    else:
        select_parts.append("CAST(NULL AS VARCHAR) AS entity_id")

    entity_expr = _text_expr("c", entity_name_col)
    supplier_contract_expr = _text_expr("c", supplier_contract_col)
    object_expr = _text_expr("c", object_col)

    supplier_join = ""
    supplier_dim_expr = "CAST(NULL AS VARCHAR)"
    if (
        suppliers_path.exists()
        and "supplier_code" in supplier_columns
        and "supplier_code" in contract_columns
    ):
        supplier_join = (
            f"LEFT JOIN {_source('sp', suppliers_path)} "
            "ON c.supplier_code = sp.supplier_code"
        )
        supplier_dim_expr = _text_expr("sp", supplier_dim_col)

    select_parts.extend(
        [
            f"{entity_expr} AS entity_name",
            f"COALESCE({supplier_dim_expr}, {supplier_contract_expr}) AS supplier_name",
            f"{object_expr} AS contract_object",
        ]
    )

    for name in SAFE_CONTRACT_COLUMNS:
        if name in input_columns:
            select_parts.append(f"i.{quote_identifier(name)} AS {quote_identifier(name)}")
        elif name in contract_columns:
            select_parts.append(f"c.{quote_identifier(name)} AS {quote_identifier(name)}")
        else:
            select_parts.append(f"CAST(NULL AS VARCHAR) AS {quote_identifier(name)}")

    for name in SAFE_CONTEXT_COLUMNS:
        if name in input_columns:
            select_parts.append(f"i.{quote_identifier(name)} AS {quote_identifier(name)}")
        else:
            select_parts.append(f"CAST(NULL AS DOUBLE) AS {quote_identifier(name)}")

    build_con = duckdb.connect(database=str(temp_path))
    try:
        build_con.execute("SET threads = 2")
        build_con.execute("SET preserve_insertion_order = false")
        build_con.execute("SET memory_limit = '8GB'")
        build_con.execute(
            f"""
            CREATE TABLE contracts_base AS
            SELECT {', '.join(select_parts)}
            FROM {_source('s', scored_path)}
            LEFT JOIN {_source('i', input_path)} USING (contract_id)
            LEFT JOIN {_source('c', contracts_path)} USING (contract_id)
            {supplier_join}
            """
        )
        total_rows = int(_scalar(build_con, "SELECT COUNT(*) FROM contracts_base"))
        expected_rows = int(scoring_manifest.get("rows") or total_rows)
        duplicate_rows = int(
            _scalar(
                build_con,
                "SELECT COUNT(*) - COUNT(DISTINCT contract_id) FROM contracts_base",
            )
        )
        null_ids = int(
            _scalar(build_con, "SELECT COUNT(*) FROM contracts_base WHERE contract_id IS NULL")
        )
        score_mismatches = int(
            _scalar(
                build_con,
                f"""
                SELECT COUNT(*)
                FROM contracts_base b
                JOIN {_source('s', scored_path)} USING (contract_id)
                WHERE b.score IS DISTINCT FROM CAST(s.score AS DOUBLE)
                   OR b.raw_score IS DISTINCT FROM CAST(s.raw_score AS DOUBLE)
                   OR b.rank IS DISTINCT FROM CAST(s.rank AS BIGINT)
                   OR b.t0 IS DISTINCT FROM s.t0
                """,
            )
        )

        if total_rows != expected_rows:
            raise ValueError(
                f"M9 serving cardinality changed: {total_rows} != {expected_rows}"
            )
        if duplicate_rows or null_ids:
            raise ValueError(
                f"M9 serving invalid grain: duplicate_rows={duplicate_rows}, null_ids={null_ids}"
            )
        if score_mismatches:
            raise ValueError(f"M9 serving modified {score_mismatches} scored rows")

        high_limit = int(math.ceil(total_rows * 0.01))
        medium_limit = int(math.ceil(total_rows * 0.05))
        build_con.execute(
            f"""
            CREATE TABLE contracts AS
            SELECT
                *,
                ROUND(100.0 * (1.0 - (rank - 1)::DOUBLE / {max(total_rows, 1)}), 4)
                    AS percentile,
                CASE
                    WHEN rank <= {high_limit} THEN 'Alta'
                    WHEN rank <= {medium_limit} THEN 'Media'
                    ELSE 'Baja'
                END AS priority
            FROM contracts_base
            """
        )
        build_con.execute("DROP TABLE contracts_base")
        build_con.execute("CREATE UNIQUE INDEX contracts_id_idx ON contracts(contract_id)")
        build_con.execute("CREATE INDEX contracts_rank_idx ON contracts(rank)")
        build_con.execute("CREATE INDEX contracts_priority_idx ON contracts(priority)")

        serving_columns = {
            str(row[0]) for row in build_con.execute("DESCRIBE contracts").fetchall()
        }
        leaked = sorted(FORBIDDEN_OUTPUT_COLUMNS & serving_columns)
        if leaked:
            raise ValueError(f"Forbidden columns leaked into M9 serving: {leaked}")

        coverage_fields = {
            "entityName": "entity_name",
            "supplierName": "supplier_name",
            "contractObject": "contract_object",
            "department": "departamento",
            "city": "ciudad",
            "modality": "modalidad_de_contratacion",
            "historicalSupplier": "prior_supplier_contract_count",
            "historicalEntity": "prior_entity_contract_count",
            "historicalPair": "prior_supplier_entity_contract_count",
        }
        coverage: dict[str, float] = {}
        for label, column in coverage_fields.items():
            count = int(
                _scalar(
                    build_con,
                    f"""
                    SELECT COUNT(*)
                    FROM contracts
                    WHERE {quote_identifier(column)} IS NOT NULL
                      AND TRIM(CAST({quote_identifier(column)} AS VARCHAR)) <> ''
                    """,
                )
            )
            coverage[label] = count / total_rows if total_rows else 0.0
    finally:
        build_con.close()

    if database_path.exists():
        database_path.unlink()
    shutil.move(str(temp_path), str(database_path))

    overview = _overview_payload(
        root=root,
        db_path=database_path,
        batch_id=batch_id,
        scoring_manifest=scoring_manifest,
        coverage=coverage,
    )
    overview_path.write_text(
        json.dumps(overview, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    validation_records = [
        {
            "check_id": "serving_row_count_preserved",
            "blocking": True,
            "passed": total_rows == expected_rows,
            "observed": json.dumps(total_rows),
            "requirement": str(expected_rows),
        },
        {
            "check_id": "serving_contract_id_unique",
            "blocking": True,
            "passed": duplicate_rows == 0 and null_ids == 0,
            "observed": json.dumps(
                {"duplicates": duplicate_rows, "null_ids": null_ids},
                sort_keys=True,
            ),
            "requirement": "one non-null row per contract_id",
        },
        {
            "check_id": "serving_scoring_unchanged",
            "blocking": True,
            "passed": score_mismatches == 0,
            "observed": json.dumps(score_mismatches),
            "requirement": "score/raw_score/rank/t0 identical to M6 scored batch",
        },
        {
            "check_id": "serving_forbidden_columns_absent",
            "blocking": True,
            "passed": not leaked,
            "observed": json.dumps(leaked),
            "requirement": "no target, mutable post-t0 state or configured PII",
        },
    ]
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(validation_records).to_parquet(validation_path, index=False)

    manifest = {
        "schema_version": M9_SCHEMA_VERSION,
        "implementation": BUILD_IMPLEMENTATION,
        "batch_id": batch_id,
        "database": str(database_path),
        "overview": str(overview_path),
        "validation": str(validation_path),
        "rows": total_rows,
        "source_paths": {
            "scored_batch": str(scored_path),
            "scoring_input": str(input_path),
            "silver_contracts": str(contracts_path),
            "silver_suppliers": str(suppliers_path) if suppliers_path.exists() else None,
        },
        "display_columns": {
            "entity": entity_name_col,
            "supplier_contract": supplier_contract_col,
            "supplier_dimension": supplier_dim_col,
            "object": object_col,
        },
        "coverage": coverage,
        "scientific_artifacts_mutated": False,
        "read_only_sources": True,
        "built_at_utc": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    return ServingBuildResult(
        database_path=database_path,
        overview_path=overview_path,
        manifest_path=manifest_path,
        validation_path=validation_path,
        row_count=total_rows,
        batch_id=batch_id,
    )
