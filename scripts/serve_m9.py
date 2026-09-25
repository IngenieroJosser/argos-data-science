from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import duckdb

from argos.serving.m9 import M9_SCHEMA_VERSION


def json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (AttributeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            pass
    return value


def row_to_dict(columns: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return {column: json_value(value) for column, value in zip(columns, row, strict=True)}


def signals_for(item: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    if (item.get("prior_supplier_contract_count") or 0) >= 20:
        signals.append("Recurrencia histórica del proveedor")
    if (item.get("prior_supplier_entity_contract_count") or 0) >= 5:
        signals.append("Relación proveedor–entidad recurrente")
    if (item.get("prior_supplier_addition_event_count") or 0) > 0:
        signals.append("Antecedentes históricos de adición")
    bidder_count = item.get("bidder_count_before_t0")
    if bidder_count is not None and bidder_count <= 1:
        signals.append("Baja competencia observable antes de t0")
    if not signals:
        signals.append("Score gobernado ARGOS V1")
    return signals[:4]


def contract_payload(item: dict[str, Any], *, detail: bool) -> dict[str, Any]:
    entity = item.get("entity_name") or item.get("entity_id") or "No disponible"
    supplier = item.get("supplier_name") or item.get("supplier_code") or "No disponible"
    contract_object = item.get("contract_object") or "Contrato priorizado por ARGOS"
    payload: dict[str, Any] = {
        "id": str(item["contract_id"]),
        "entity": str(entity),
        "supplier": str(supplier),
        "object": str(contract_object),
        "department": item.get("departamento"),
        "city": item.get("ciudad"),
        "modality": item.get("modalidad_de_contratacion"),
        "contractType": item.get("tipo_de_contrato"),
        "sector": item.get("sector"),
        "processId": item.get("process_id"),
        "supplierCode": item.get("supplier_code"),
        "entityId": item.get("entity_id"),
        "t0": json_value(item.get("t0")),
        "score": float(item.get("score") or 0.0),
        "rawScore": json_value(item.get("raw_score")),
        "rank": int(item.get("rank") or 0),
        "percentile": float(item.get("percentile") or 0.0),
        "priority": str(item.get("priority") or "Baja"),
        "signals": signals_for(item),
    }
    if detail:
        context_keys = [
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
        ]
        payload["context"] = {key: json_value(item.get(key)) for key in context_keys}
        payload["details"] = {
            "justification": item.get("justificacion_modalidad_de_contratacion"),
            "categoryCode": item.get("codigo_de_categoria_principal"),
            "branch": item.get("rama"),
            "order": item.get("orden"),
            "centralizedEntity": item.get("entidad_centralizada"),
            "isGroup": item.get("es_grupo"),
            "isSme": item.get("es_pyme"),
        }
    return payload


class ArgosServingHandler(BaseHTTPRequestHandler):
    server_version = "ARGOS-M9/1.0"

    @property
    def app(self) -> "ArgosServingServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: object) -> None:
        print(f"[M9 API] {self.address_string()} - {format % args}")

    def _send(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _query_one(
        self,
        sql: str,
        parameters: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        con = duckdb.connect(database=str(self.app.database_path), read_only=True)
        try:
            cursor = con.execute(sql, parameters or [])
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [str(item[0]) for item in cursor.description]
            return row_to_dict(columns, row)
        finally:
            con.close()

    def _query_all(
        self,
        sql: str,
        parameters: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        con = duckdb.connect(database=str(self.app.database_path), read_only=True)
        try:
            cursor = con.execute(sql, parameters or [])
            rows = cursor.fetchall()
            columns = [str(item[0]) for item in cursor.description]
            return [row_to_dict(columns, row) for row in rows]
        finally:
            con.close()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if path == "/health":
                self._send(
                    {
                        "status": "ok",
                        "schemaVersion": M9_SCHEMA_VERSION,
                        "database": str(self.app.database_path),
                    }
                )
                return

            if path == "/api/v1/overview":
                payload = json.loads(self.app.overview_path.read_text(encoding="utf-8"))
                self._send(payload)
                return

            if path == "/api/v1/monitoring":
                self._send(self.app.monitoring_payload())
                return

            if path == "/api/v1/contracts":
                self._send(self._contracts(query))
                return

            prefix = "/api/v1/contracts/"
            if path.startswith(prefix):
                contract_id = unquote(path[len(prefix) :])
                self._contract_detail(contract_id)
                return

            self._send(
                {"error": "NOT_FOUND", "path": path},
                HTTPStatus.NOT_FOUND,
            )
        except (ValueError, duckdb.Error) as exc:
            self._send(
                {"error": "BAD_REQUEST", "message": str(exc)},
                HTTPStatus.BAD_REQUEST,
            )
        except Exception as exc:  # noqa: BLE001
            self._send(
                {"error": "INTERNAL_ERROR", "message": str(exc)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _contracts(self, query: dict[str, list[str]]) -> dict[str, Any]:
        page = max(1, int(query.get("page", ["1"])[0]))
        page_size = min(100, max(1, int(query.get("pageSize", ["25"])[0])))
        priority = query.get("priority", [""])[0].strip()
        search = query.get("q", [""])[0].strip()
        if priority and priority not in {"Alta", "Media", "Baja"}:
            raise ValueError("priority must be Alta, Media or Baja")

        where: list[str] = []
        params: list[Any] = []
        if priority:
            where.append("priority = ?")
            params.append(priority)
        if search:
            pattern = f"%{search}%"
            where.append(
                "(" 
                "CAST(contract_id AS VARCHAR) ILIKE ? OR "
                "COALESCE(entity_name, '') ILIKE ? OR "
                "COALESCE(supplier_name, '') ILIKE ? OR "
                "COALESCE(contract_object, '') ILIKE ?"
                ")"
            )
            params.extend([pattern, pattern, pattern, pattern])
        clause = " WHERE " + " AND ".join(where) if where else ""
        total = self._query_one(f"SELECT COUNT(*) AS total FROM contracts{clause}", params)
        offset = (page - 1) * page_size
        rows = self._query_all(
            f"""
            SELECT *
            FROM contracts
            {clause}
            ORDER BY rank ASC, contract_id ASC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        )
        return {
            "total": int((total or {}).get("total", 0)),
            "page": page,
            "pageSize": page_size,
            "items": [contract_payload(row, detail=False) for row in rows],
        }

    def _contract_detail(self, contract_id: str) -> None:
        if not contract_id:
            raise ValueError("contract_id is required")
        row = self._query_one(
            "SELECT * FROM contracts WHERE contract_id = ? LIMIT 1",
            [contract_id],
        )
        if row is None:
            self._send(
                {"error": "CONTRACT_NOT_FOUND", "id": contract_id},
                HTTPStatus.NOT_FOUND,
            )
            return
        self._send(contract_payload(row, detail=True))


class ArgosServingServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        database_path: Path,
        overview_path: Path,
        root: Path,
    ) -> None:
        super().__init__(address, ArgosServingHandler)
        self.database_path = database_path
        self.overview_path = overview_path
        self.root = root

    def monitoring_payload(self) -> dict[str, Any]:
        score_drift = _parquet_first_row(
            self.root / "reports" / "production" / "53_score_drift.parquet"
        )
        alerts = _parquet_records(
            self.root / "reports" / "production" / "53_alerts.parquet",
            limit=50,
        )
        feature_drift = _parquet_records(
            self.root / "reports" / "production" / "53_feature_drift.parquet",
            limit=25,
            order_by="drift_value DESC",
        )
        return {
            "scoreDrift": score_drift,
            "alerts": alerts,
            "topFeatureDrift": feature_drift,
        }


def _parquet_first_row(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    con = duckdb.connect(database=":memory:")
    try:
        escaped = str(path).replace("'", "''")
        cursor = con.execute(f"SELECT * FROM read_parquet('{escaped}') LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            return {}
        columns = [str(item[0]) for item in cursor.description]
        return row_to_dict(columns, row)
    finally:
        con.close()


def _parquet_records(
    path: Path,
    *,
    limit: int,
    order_by: str | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    order = f" ORDER BY {order_by}" if order_by else ""
    con = duckdb.connect(database=":memory:")
    try:
        escaped = str(path).replace("'", "''")
        cursor = con.execute(
            f"SELECT * FROM read_parquet('{escaped}'){order} LIMIT {int(limit)}"
        )
        columns = [str(item[0]) for item in cursor.description]
        return [row_to_dict(columns, row) for row in cursor.fetchall()]
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sirve la capa M9 de ARGOS en modo read-only")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Raíz del backend ARGOS",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    serving = root / "data" / "serving" / "m9"
    database = serving / "argos-serving.duckdb"
    overview = serving / "overview.json"
    if not database.exists() or not overview.exists():
        raise FileNotFoundError(
            "M9 serving has not been built. Run: "
            "uv run --no-sync python scripts/build_m9_serving.py"
        )

    server = ArgosServingServer((args.host, args.port), database, overview, root)
    print(f"ARGOS M9 API ✅ http://{args.host}:{args.port}")
    print(f"database={database}")
    print("mode=READ_ONLY")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
