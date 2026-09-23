from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from argos.config.prospective import ProspectiveSpec
from argos.prospective.common import sha256_file, write_json_atomic

OUTCOME_IMPLEMENTATION = "m7-62-label-lock-v2"


@dataclass(frozen=True, slots=True)
class LabelLockResult:
    labels: pd.DataFrame
    lock_manifest: Path
    labels_path: Path
    status: str


def _normalized_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.upper()


def outcome_watermark(additions: pd.DataFrame, spec: ProspectiveSpec) -> pd.Timestamp:
    event_col = spec.outcomes.event_time_column
    if event_col not in additions.columns:
        raise ValueError(f"additions missing {event_col!r}")
    event_times = pd.to_datetime(additions[event_col], errors="coerce")
    max_event = event_times.max()
    if pd.isna(max_event):
        raise ValueError("cannot derive outcome watermark: no parsed event timestamps")
    return pd.Timestamp(max_event) - pd.Timedelta(days=spec.cohorts.outcome_reporting_lag_days)


def compute_labels(
    *,
    cohort: pd.DataFrame,
    additions: pd.DataFrame,
    observation_end: pd.Timestamp,
    spec: ProspectiveSpec,
) -> pd.DataFrame:
    id_col = spec.outcomes.id_column
    t0_col = spec.outcomes.t0_column
    required = {id_col, t0_col}
    if not required.issubset(cohort.columns):
        raise ValueError(f"cohort missing required columns: {sorted(required - set(cohort.columns))}")
    if cohort[id_col].isna().any():
        raise ValueError("prospective cohort contains null contract_id")
    if cohort[id_col].duplicated().any():
        raise ValueError("prospective cohort must contain one row per contract_id")

    event_time_col = spec.outcomes.event_time_column
    event_required = {id_col, event_time_col, "event_type"}
    if not event_required.issubset(additions.columns):
        raise ValueError(f"additions missing required columns: {sorted(event_required - set(additions.columns))}")

    base = cohort[[id_col, t0_col]].copy()
    base[t0_col] = pd.to_datetime(base[t0_col], errors="raise")
    obs_end = pd.Timestamp(observation_end)
    base["followup_end"] = base[t0_col] + pd.Timedelta(days=spec.core.target_horizon_days)
    base["label_eligible"] = base["followup_end"] <= obs_end

    event_type = _normalized_text(additions["event_type"])
    target_type = spec.outcomes.event_type.strip().upper()
    events = additions.loc[event_type.eq(target_type), [id_col, event_time_col]].copy()
    events[event_time_col] = pd.to_datetime(events[event_time_col], errors="coerce")
    events = events.dropna(subset=[event_time_col])

    merged = base.merge(events, on=id_col, how="left", validate="one_to_many")
    in_window = (merged[event_time_col] > merged[t0_col]) & (
        merged[event_time_col] <= merged["followup_end"]
    )
    positives = merged.loc[in_window, id_col].drop_duplicates()
    base[spec.outcomes.target_column] = base[id_col].isin(set(positives)).astype("Int8")
    base.loc[~base["label_eligible"], spec.outcomes.target_column] = pd.NA
    return base


def _lock_payload(
    *,
    spec: ProspectiveSpec,
    observation_end: pd.Timestamp,
    labels_path: Path,
    labels: pd.DataFrame,
    lineage: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": spec.schema_version,
        "implementation": OUTCOME_IMPLEMENTATION,
        "observation_end": pd.Timestamp(observation_end).isoformat(),
        "rows": int(len(labels)),
        "eligible_rows": int(labels["label_eligible"].sum()),
        "positive_rows": int(labels[spec.outcomes.target_column].fillna(0).sum()),
        "labels_sha256": sha256_file(labels_path),
        "labels_path": str(labels_path),
        "lineage": lineage,
    }


def build_locked_labels(
    *,
    cohort: pd.DataFrame,
    additions: pd.DataFrame,
    observation_end: pd.Timestamp,
    spec: ProspectiveSpec,
    lock_path: Path,
    lineage: dict[str, Any] | None = None,
) -> LabelLockResult:
    labels = compute_labels(
        cohort=cohort,
        additions=additions,
        observation_end=observation_end,
        spec=spec,
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path = lock_path.with_suffix(".parquet")
    lineage = dict(lineage or {})

    if lock_path.exists() or labels_path.exists():
        if not (lock_path.exists() and labels_path.exists()):
            raise RuntimeError(f"partial label lock detected for {lock_path}")
        existing = json.loads(lock_path.read_text(encoding="utf-8"))
        existing_hash = existing.get("labels_sha256")
        current_hash = sha256_file(labels_path)
        if existing_hash != current_hash:
            raise RuntimeError(f"label lock bytes changed after freeze: {labels_path}")
        return LabelLockResult(pd.read_parquet(labels_path), lock_path, labels_path, "preserved")

    tmp = labels_path.with_suffix(labels_path.suffix + ".tmp")
    labels.to_parquet(tmp, index=False)
    tmp.replace(labels_path)
    payload = _lock_payload(
        spec=spec,
        observation_end=observation_end,
        labels_path=labels_path,
        labels=labels,
        lineage=lineage,
    )
    write_json_atomic(lock_path, payload)
    return LabelLockResult(labels, lock_path, labels_path, "created")
