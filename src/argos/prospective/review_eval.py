from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from argos.config.prospective import ProspectiveSpec

REVIEW_IMPLEMENTATION = "m7-64-review-utility-v2"


def _audit_queue_times(audit_log: Path) -> dict[str, pd.Timestamp]:
    result: dict[str, pd.Timestamp] = {}
    if not audit_log.exists():
        return result
    with audit_log.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event_type") != "review_queue_materialized":
                continue
            batch_id = str(event.get("payload", {}).get("batch_id", ""))
            occurred = pd.to_datetime(event.get("occurred_at_utc"), errors="coerce", utc=True)
            if batch_id and pd.notna(occurred) and batch_id not in result:
                result[batch_id] = occurred
    return result


def review_operational_metrics(
    queue: pd.DataFrame,
    *,
    terminal_statuses: tuple[str, ...] = ("reviewed", "dismissed", "escalated"),
    queued_at: pd.Timestamp | None = None,
) -> dict[str, float]:
    if "review_status" not in queue.columns:
        raise ValueError("review queue missing review_status")
    total = len(queue)
    status = queue["review_status"].astype("string").str.lower().str.strip()
    completed = status.isin(set(terminal_statuses))
    result: dict[str, float] = {
        "rows": float(total),
        "completed_rows": float(completed.sum()),
        "review_completion_rate": float(completed.mean()) if total else float("nan"),
    }

    if "reviewed_at" in queue.columns:
        reviewed = pd.to_datetime(queue["reviewed_at"], errors="coerce", utc=True)
        if "queued_at" in queue.columns:
            queued = pd.to_datetime(queue["queued_at"], errors="coerce", utc=True)
            latency = (reviewed - queued).dt.total_seconds().div(3600)
        elif queued_at is not None:
            q = pd.Timestamp(queued_at)
            q = q.tz_localize("UTC") if q.tzinfo is None else q.tz_convert("UTC")
            latency = (reviewed - q).dt.total_seconds().div(3600)
        else:
            latency = pd.Series(dtype=float)
        latency = latency.loc[completed & latency.notna() & (latency >= 0)]
        result["p50_review_latency_hours"] = (
            float(np.percentile(latency, 50)) if len(latency) else float("nan")
        )
        result["p95_review_latency_hours"] = (
            float(np.percentile(latency, 95)) if len(latency) else float("nan")
        )

    result["review_outcome_nonnull_rate"] = (
        float(queue.loc[completed, "review_outcome"].notna().mean())
        if completed.any() and "review_outcome" in queue.columns
        else float("nan")
    )
    return result


def evaluate_registered_review_queues(
    *,
    root: Path,
    spec: ProspectiveSpec,
    registry: pd.DataFrame,
    audit_log: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    queue_times = _audit_queue_times(audit_log)
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for record in registry.to_dict(orient="records"):
        batch_id = str(record["scoring_batch_id"])
        queue_path = root / spec.operations.review_queue_root / f"{batch_id}.parquet"
        if not queue_path.exists():
            missing.append({"scoring_batch_id": batch_id, "queue_path": str(queue_path)})
            continue
        queue = pd.read_parquet(queue_path)
        metrics = review_operational_metrics(
            queue,
            terminal_statuses=spec.operations.terminal_review_statuses,
            queued_at=queue_times.get(batch_id),
        )
        rows.append(
            {
                "scoring_batch_id": batch_id,
                "queue_path": str(queue_path),
                **metrics,
            }
        )
    return pd.DataFrame.from_records(rows), pd.DataFrame.from_records(missing)
