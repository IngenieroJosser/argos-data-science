from __future__ import annotations

import argparse
import json
import math
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

SCHEMA_VERSION = "m9-presentation-v1"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is not None:
        frame = frame.head(limit)
    return [{k: json_value(v) for k, v in row.items()} for row in frame.to_dict("records")]


def read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if columns:
        available = set(pq.ParquetFile(path).schema_arrow.names)
        columns = [c for c in columns if c in available]
    return pd.read_parquet(path, columns=columns or None)


def latest_scoring_manifest(root: Path) -> dict[str, Any]:
    candidates = sorted((root / "artifacts" / "manifests").glob("m6_scoring_*.json"))
    if not candidates:
        return {}
    return read_json(candidates[-1], {})


def metric_record(path: Path) -> dict[str, Any]:
    frame = read_parquet(path)
    return {} if frame.empty else {k: json_value(v) for k, v in frame.iloc[0].to_dict().items()}


def ranking_at_one_percent(path: Path) -> dict[str, Any]:
    frame = read_parquet(path)
    if frame.empty or "review_fraction" not in frame.columns:
        return {}
    idx = (frame["review_fraction"].astype(float) - 0.01).abs().idxmin()
    return {k: json_value(v) for k, v in frame.loc[idx].to_dict().items()}


def model_card_fallback(root: Path) -> dict[str, float]:
    path = root / "docs" / "models" / "ARGOS_V1_MODEL_CARD.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    out: dict[str, float] = {}
    patterns = {
        "pr_auc": r"PR-AUC\s*\|\s*([0-9.]+)",
        "roc_auc": r"ROC-AUC\s*\|\s*([0-9.]+)",
        "brier": r"Brier\s*\|\s*([0-9.]+)",
        "ece": r"ECE\s*\|\s*([0-9.]+)",
        "lift_at_1pct": r"Lift@K:\s*\*\*([0-9.]+)x",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            out[key] = float(match.group(1))
    return out


def robustness_card_fallback(root: Path) -> dict[str, float]:
    path = root / "docs" / "models" / "ARGOS_V1_ROBUSTNESS_CARD.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    out: dict[str, float] = {}
    for key, label in [("pr_auc", "PR-AUC"), ("roc_auc", "ROC-AUC"), ("brier", "Brier"), ("ece", "ECE")]:
        m = re.search(rf"{re.escape(label)}:\s*\*\*([0-9.]+)", text)
        if m:
            out[key] = float(m.group(1))
    m = re.search(r"Lift@1%:\s*\*\*([0-9.]+)x", text)
    if m:
        out["lift_at_1pct"] = float(m.group(1))
    m = re.search(r"Recall@1%:\s*\*\*([0-9.]+)%", text)
    if m:
        out["recall_at_1pct"] = float(m.group(1)) / 100.0
    return out


def band_from_percentile(percentile: float) -> str:
    if percentile >= 99.0:
        return "Alta"
    if percentile >= 95.0:
        return "Media"
    return "Baja"


def choose_contract_rows(scored: pd.DataFrame, max_contracts: int) -> pd.DataFrame:
    if scored.empty:
        return scored
    scored = scored.sort_values("rank", kind="stable").reset_index(drop=True)
    n = len(scored)
    high_n = min(max(8, max_contracts // 3), max_contracts)
    each = max(1, (max_contracts - high_n) // 2)
    positions: list[int] = list(range(min(high_n, n)))
    for lo, hi in [(0.01, 0.05), (0.05, 0.20)]:
        start = min(n - 1, int(n * lo))
        stop = min(n - 1, max(start, int(n * hi) - 1))
        if stop >= start:
            positions.extend(np.linspace(start, stop, each, dtype=int).tolist())
    positions = sorted(set(p for p in positions if 0 <= p < n))[:max_contracts]
    return scored.iloc[positions].copy()


def enrich_gold(root: Path, selected: pd.DataFrame, feature_names: list[str]) -> pd.DataFrame:
    gold_path = root / "data" / "gold" / "ml" / "argos_v1.parquet"
    if selected.empty or not gold_path.exists():
        return selected
    schema = set(pq.ParquetFile(gold_path).schema_arrow.names)
    safe_candidates = [
        "contract_id", "supplier_code", "entity_id", "departamento", "ciudad", "sector",
        "tipo_de_contrato", "modalidad_de_contratacion", "prior_supplier_contract_count",
        "prior_entity_contract_count", "prior_supplier_entity_contract_count",
        "prior_supplier_addition_event_count", "prior_supplier_contracts_with_addition",
        "observed_supplier_addition_contract_share_before_t0", "bidder_count_before_t0",
        "unique_resolved_supplier_count_before_t0", "bidder_entity_resolution_rate_before_t0",
    ]
    allowed = set(feature_names) | {"contract_id", "supplier_code", "entity_id"}
    columns = [c for c in safe_candidates if c in schema and c in allowed]
    if "contract_id" not in columns:
        columns.insert(0, "contract_id")
    ids = selected["contract_id"].astype(str).tolist()
    dataset = ds.dataset(gold_path, format="parquet")
    table = dataset.to_table(columns=columns, filter=pc.field("contract_id").isin(ids))
    gold = table.to_pandas()
    if gold.empty:
        return selected
    return selected.merge(gold, on="contract_id", how="left", validate="one_to_one")


def attach_m8_context(root: Path, selected: pd.DataFrame) -> pd.DataFrame:
    if selected.empty:
        return selected
    config_path = root / "configs" / "advanced.toml"
    if not config_path.exists():
        return selected
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    artifacts = cfg.get("artifacts", {})
    wanted = {
        "semantic_features": ["semantic_novelty_score", "semantic_similarity_max", "semantic_neighbor_count"],
        "graph_features": ["supplier_degree", "entity_degree", "supplier_pagerank", "entity_pagerank", "supplier_entity_pair_contract_count", "supplier_entity_hhi"],
        "anomaly_features": ["anomaly_score", "anomaly_isolation_raw_score", "anomaly_categorical_rarity_mean"],
    }
    ids = selected["contract_id"].astype(str).tolist()
    out = selected
    for key, requested in wanted.items():
        rel = artifacts.get(key)
        if not rel:
            continue
        path = root / str(rel)
        if not path.exists():
            continue
        schema = set(pq.ParquetFile(path).schema_arrow.names)
        columns = ["contract_id", *[c for c in requested if c in schema]]
        dataset = ds.dataset(path, format="parquet")
        table = dataset.to_table(columns=columns, filter=pc.field("contract_id").isin(ids))
        frame = table.to_pandas()
        if not frame.empty:
            out = out.merge(frame, on="contract_id", how="left", validate="one_to_one")
    return out


def signals_for(row: pd.Series) -> list[str]:
    signals: list[str] = []
    def num(name: str) -> float | None:
        value = row.get(name)
        try:
            return None if pd.isna(value) else float(value)
        except (TypeError, ValueError):
            return None
    if (v := num("prior_supplier_contract_count")) is not None and v >= 20:
        signals.append("Recurrencia histórica del proveedor")
    if (v := num("prior_supplier_entity_contract_count")) is not None and v >= 5:
        signals.append("Relación proveedor–entidad recurrente")
    if (v := num("prior_supplier_addition_event_count")) is not None and v > 0:
        signals.append("Antecedentes históricos de adición")
    if (v := num("bidder_count_before_t0")) is not None and v <= 1:
        signals.append("Baja competencia observable antes de t0")
    if (v := num("anomaly_score")) is not None and v >= 0.95:
        signals.append("Rareza contextual elevada (M8)")
    if (v := num("semantic_novelty_score")) is not None and v >= 0.50:
        signals.append("Novedad semántica alta (M8)")
    if not signals:
        signals.append("Score gobernado ARGOS V1")
    return signals[:4]


def contract_records(frame: pd.DataFrame, total_rows: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if frame.empty:
        return items
    for _, row in frame.iterrows():
        rank = int(row.get("rank", row.get("model_rank", 0)) or 0)
        percentile = 100.0 * (1.0 - max(rank - 1, 0) / max(total_rows, 1))
        sector = row.get("sector")
        contract_type = row.get("tipo_de_contrato")
        modality = row.get("modalidad_de_contratacion")
        description_parts = [str(x) for x in [sector, contract_type] if x is not None and not pd.isna(x) and str(x).strip()]
        items.append({
            "id": str(row.get("contract_id")),
            "entity": str(row.get("entity_id")) if pd.notna(row.get("entity_id")) else "Entidad no expuesta en snapshot",
            "supplier": str(row.get("supplier_code")) if pd.notna(row.get("supplier_code")) else "Proveedor no expuesto en snapshot",
            "object": " · ".join(description_parts) if description_parts else "Contrato priorizado por ARGOS",
            "score": float(row.get("score", row.get("model_score", 0.0))),
            "rawScore": json_value(row.get("raw_score", row.get("model_raw_score"))),
            "rank": rank,
            "percentile": round(percentile, 2),
            "priority": band_from_percentile(percentile),
            "signals": signals_for(row),
            "t0": json_value(row.get("t0")),
            "process": None if pd.isna(modality) else str(modality),
            "department": None if pd.isna(row.get("departamento")) else str(row.get("departamento")),
            "city": None if pd.isna(row.get("ciudad")) else str(row.get("ciudad")),
            "context": {k: json_value(row.get(k)) for k in [
                "prior_supplier_contract_count", "prior_entity_contract_count",
                "prior_supplier_entity_contract_count", "prior_supplier_addition_event_count",
                "bidder_count_before_t0", "unique_resolved_supplier_count_before_t0",
                "bidder_entity_resolution_rate_before_t0", "semantic_novelty_score",
                "semantic_similarity_max", "anomaly_score", "supplier_degree", "entity_degree",
                "supplier_pagerank", "entity_pagerank", "supplier_entity_hhi",
            ] if k in row.index},
        })
    return items


def build_snapshot(root: Path, max_contracts: int) -> dict[str, Any]:
    scoring_manifest = latest_scoring_manifest(root)
    batch_id = str(scoring_manifest.get("batch_id", ""))
    scored_path = root / "data" / "production" / "scored_batches" / f"{batch_id}.parquet" if batch_id else Path("__missing__")
    queue_path = root / "data" / "production" / "review_queues" / f"{batch_id}.parquet" if batch_id else Path("__missing__")
    scoring_contract = read_json(root / "artifacts" / "contracts" / "argos_v1_scoring_contract.json", {})
    production_cfg = tomllib.loads((root / "configs" / "production.toml").read_text(encoding="utf-8")) if (root / "configs" / "production.toml").exists() else {}
    review_fraction = float(production_cfg.get("scoring", {}).get("operational_review_fraction", 0.01))
    registry = read_json(root / "artifacts" / "registry" / "argos_v1.json", {})
    deployment = read_json(root / "artifacts" / "registry" / "deployment_state.json", {})
    monitoring_manifest = read_json(root / "artifacts" / "manifests" / "m6_monitoring.json", {})
    queue_manifest = read_json(root / "artifacts" / "manifests" / "m6_human_review_queue.json", {})
    m7 = read_json(root / "artifacts" / "manifests" / "m7_protocol_freeze.json", {})
    m8 = read_json(root / "artifacts" / "manifests" / "m8_feature_selection.json", {})
    survival = read_json(root / "artifacts" / "manifests" / "m8_survival.json", {})

    scored = read_parquet(scored_path, ["contract_id", "t0", "score", "raw_score", "rank", "review_priority"])
    total_rows = int(scoring_manifest.get("rows") or len(scored) or 0)
    review_rows = int(queue_manifest.get("rows") or 0)
    if not scored.empty:
        scored["t0"] = pd.to_datetime(scored["t0"], errors="coerce")
        scored["rank"] = pd.to_numeric(scored["rank"], errors="coerce").astype("Int64")
        selected = choose_contract_rows(scored, max_contracts)
        selected = enrich_gold(root, selected, [f.get("name") for f in scoring_contract.get("features", []) if f.get("name")])
        selected = attach_m8_context(root, selected)
        contracts = contract_records(selected, total_rows)
        high_count = int(math.ceil(total_rows * 0.01))
        medium_count = max(0, int(math.ceil(total_rows * 0.05)) - high_count)
        low_count = max(0, total_rows - high_count - medium_count)
        valid_t0 = scored.dropna(subset=["t0"]).copy()
        if not valid_t0.empty:
            valid_t0["month"] = valid_t0["t0"].dt.to_period("M").astype(str)
            valid_t0["focus"] = valid_t0["rank"].astype(float) <= math.ceil(total_rows * 0.05)
            grouped = valid_t0.groupby("month", observed=True).agg(total=("contract_id", "size"), focus=("focus", "sum"), meanScore=("score", "mean")).reset_index().tail(12)
            grouped["focusPct"] = grouped["focus"] / grouped["total"] * 100.0
            trend = records(grouped[["month", "total", "focus", "focusPct", "meanScore"]])
        else:
            trend = []
    else:
        contracts = []
        high_count = review_rows
        medium_count = 0
        low_count = max(0, total_rows - review_rows)
        trend = []

    alerts = read_parquet(root / "reports" / "production" / "53_alerts.parquet")
    feature_drift = read_parquet(root / "reports" / "production" / "53_feature_drift.parquet")
    score_drift = metric_record(root / "reports" / "production" / "53_score_drift.parquet")
    if not feature_drift.empty and "drift_value" in feature_drift.columns:
        feature_drift = feature_drift.sort_values("drift_value", ascending=False)

    test_metrics = metric_record(root / "reports" / "modeling" / "36_final_test_metrics.parquet") or model_card_fallback(root)
    test_ranking = ranking_at_one_percent(root / "reports" / "modeling" / "36_business_capacity_curve.parquet")
    oot_metrics = metric_record(root / "reports" / "robustness" / "45_fresh_oot_metrics.parquet") or robustness_card_fallback(root)
    oot_ranking = ranking_at_one_percent(root / "reports" / "robustness" / "45_fresh_oot_ranking.parquet")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {
            "backendRoot": str(root),
            "batchId": batch_id or None,
            "modelVersion": registry.get("model_version", "argos-v1"),
            "modelStage": deployment.get("stage", registry.get("stage")),
            "scoringMode": registry.get("scoring_mode"),
            "dataMode": "materialized" if not scored.empty else "metadata-only",
        },
        "overview": {
            "scoredContracts": total_rows,
            "reviewQueueRows": review_rows,
            "reviewFraction": review_fraction,
            "highCount": high_count,
            "mediumCount": medium_count,
            "lowCount": low_count,
            "alerts": int(monitoring_manifest.get("alerts", len(alerts))),
            "highAlerts": int(monitoring_manifest.get("high_alerts", 0)),
            "scorePsi": json_value(score_drift.get("score_psi")),
            "promotionBlocked": bool(deployment.get("promotion_blocked", False)),
            "blockReason": deployment.get("block_reason"),
            "operationalStatus": "OPERATIONALLY_READY_PROMOTION_BLOCKED" if deployment.get("promotion_blocked") else "OPERATIONALLY_READY",
        },
        "governance": {
            "humanReviewRequired": bool(scoring_contract.get("human_review_required", True)),
            "productionPromotionAuthorized": bool(registry.get("production_promotion_authorized", False)),
            "m7Status": "ACTIVE / EVIDENCE PENDING",
            "m7ProtocolId": m7.get("protocol_id"),
            "m7ProspectiveStart": m7.get("prospective_start"),
            "m7HorizonDays": m7.get("target_horizon_days"),
            "m8Status": "CLOSED",
            "m8Decision": m8.get("decision"),
            "m8SelectedFamily": m8.get("selected_family"),
        },
        "performance": {
            "test2025": {**test_metrics, **{f"ranking_{k}": v for k, v in test_ranking.items()}},
            "oot2026": {**oot_metrics, **{f"ranking_{k}": v for k, v in oot_ranking.items()}},
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
        "contracts": contracts,
        "monitoring": {
            "scoreDrift": score_drift,
            "alerts": records(alerts, 25),
            "topFeatureDrift": records(feature_drift, 12),
        },
        "disclaimer": "ARGOS prioriza casos para revisión analítica adicional. Sus scores, anomalías y relaciones no constituyen una acusación ni una conclusión jurídica de fraude o corrupción.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta un snapshot M9 consumible por Next.js")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="Raíz del backend ARGOS")
    parser.add_argument("--output", type=Path, required=True, help="JSON de salida, normalmente frontend/data/argos-presentation.json")
    parser.add_argument("--max-contracts", type=int, default=60)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    snapshot = build_snapshot(root, max_contracts=max(12, args.max_contracts))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"M9 snapshot ✅ {output}")
    print(f"mode={snapshot['source']['dataMode']} scored={snapshot['overview']['scoredContracts']} contracts={len(snapshot['contracts'])}")


if __name__ == "__main__":
    main()
