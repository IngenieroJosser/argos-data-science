from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

MONITORING_IMPLEMENTATION = "m7-65-longitudinal-monitoring-v1"


def monitoring_events_for_batches(audit_log: Path, batch_ids: set[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not audit_log.exists():
        return pd.DataFrame()
    with audit_log.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event_type") != "monitoring_completed":
                continue
            payload = event.get("payload", {})
            batch_id = str(payload.get("batch_id", ""))
            if batch_id not in batch_ids:
                continue
            rows.append(
                {
                    "line_no": line_no,
                    "scoring_batch_id": batch_id,
                    "occurred_at_utc": pd.to_datetime(
                        event.get("occurred_at_utc"), errors="coerce", utc=True
                    ),
                    "alerts": int(payload.get("alerts", 0)),
                    "high_alerts": int(payload.get("high_alerts", 0)),
                    "score_psi": float(payload.get("score_psi", float("nan"))),
                    "event_hash": event.get("event_hash"),
                }
            )
    frame = pd.DataFrame.from_records(rows)
    if not frame.empty:
        frame = frame.sort_values(["occurred_at_utc", "line_no"]).drop_duplicates(
            "scoring_batch_id", keep="last"
        )
    return frame.reset_index(drop=True)


def initialize_incident_register(path: Path) -> pd.DataFrame:
    columns = [
        "incident_id",
        "opened_at_utc",
        "closed_at_utc",
        "severity",
        "status",
        "scoring_batch_id",
        "category",
        "summary",
        "owner",
        "resolution",
    ]
    if path.exists():
        return pd.read_parquet(path)
    frame = pd.DataFrame(columns=columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def incident_summary(incidents: pd.DataFrame) -> dict[str, int]:
    if incidents.empty:
        return {
            "incidents": 0,
            "critical_incidents": 0,
            "open_critical_incidents": 0,
        }
    severity = incidents["severity"].astype("string").str.lower().str.strip()
    status = incidents["status"].astype("string").str.lower().str.strip()
    critical = severity.eq("critical")
    closed = status.isin({"closed", "resolved"})
    return {
        "incidents": int(len(incidents)),
        "critical_incidents": int(critical.sum()),
        "open_critical_incidents": int((critical & ~closed).sum()),
    }
