from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from argos.config.prospective import ProspectiveSpec
from argos.prospective.common import sha256_file

COHORT_IMPLEMENTATION = "m7-61-cohort-registry-v2"


@dataclass(frozen=True, slots=True)
class CohortInventory:
    discovered: pd.DataFrame
    eligible: pd.DataFrame
    ignored: pd.DataFrame

    @property
    def eligible_batch_count(self) -> int:
        return int(len(self.eligible))


def _inspect_batch(path: Path, spec: ProspectiveSpec, *, root: Path) -> dict[str, Any]:
    cols = [
        spec.outcomes.id_column,
        spec.outcomes.t0_column,
        "score",
        "raw_score",
        "rank",
        "model_version",
        "scoring_batch_id",
    ]
    frame = pd.read_parquet(path, columns=cols)
    if frame.empty:
        return {
            "batch_file": path.name,
            "batch_path": str(path),
            "batch_relative_path": str(path.relative_to(root)),
            "batch_sha256": sha256_file(path),
            "rows": 0,
            "eligible_m7": False,
            "eligibility_reason": "empty_batch",
        }

    t0 = pd.to_datetime(frame[spec.outcomes.t0_column], errors="coerce")
    min_t0 = t0.min()
    max_t0 = t0.max()
    null_t0 = int(t0.isna().sum())
    unique_ids = int(frame[spec.outcomes.id_column].nunique(dropna=False))
    duplicate_ids = int(len(frame) - unique_ids)
    batch_ids = frame["scoring_batch_id"].dropna().astype(str).unique().tolist()
    model_versions = frame["model_version"].dropna().astype(str).unique().tolist()
    scores = pd.to_numeric(frame["score"], errors="coerce")
    raw_scores = pd.to_numeric(frame["raw_score"], errors="coerce")
    ranks = pd.to_numeric(frame["rank"], errors="coerce")

    future_only = bool(
        null_t0 == 0
        and pd.notna(min_t0)
        and min_t0.date() >= spec.core.prospective_start
    )
    schema_ok = bool(
        duplicate_ids == 0
        and len(batch_ids) == 1
        and len(model_versions) == 1
        and model_versions[0] == spec.core.model_version
        and np.isfinite(scores.to_numpy(dtype=float)).all()
        and np.isfinite(raw_scores.to_numpy(dtype=float)).all()
        and ranks.notna().all()
        and ranks.nunique() == len(frame)
    )

    if not future_only:
        reason = "contains_pre_freeze_or_null_t0"
    elif not schema_ok:
        reason = "batch_contract_violation"
    else:
        reason = "eligible"

    return {
        "batch_file": path.name,
        "batch_path": str(path),
        "batch_relative_path": str(path.relative_to(root)),
        "batch_sha256": sha256_file(path),
        "scoring_batch_id": batch_ids[0] if len(batch_ids) == 1 else None,
        "model_version": model_versions[0] if len(model_versions) == 1 else None,
        "rows": int(len(frame)),
        "distinct_contracts": unique_ids,
        "duplicate_contract_ids": duplicate_ids,
        "null_t0": null_t0,
        "min_t0": min_t0,
        "max_t0": max_t0,
        "future_only": future_only,
        "batch_contract_ok": schema_ok,
        "eligible_m7": bool(future_only and schema_ok),
        "eligibility_reason": reason,
        "cohort_month_min": min_t0.to_period("M").strftime("%Y-%m") if pd.notna(min_t0) else None,
        "cohort_month_max": max_t0.to_period("M").strftime("%Y-%m") if pd.notna(max_t0) else None,
    }


def inventory_prospective_batches(root: Path, spec: ProspectiveSpec) -> CohortInventory:
    batch_root = root / spec.operations.scored_batch_root
    rows: list[dict[str, Any]] = []
    for path in sorted(batch_root.glob("*.parquet")) if batch_root.exists() else []:
        try:
            rows.append(_inspect_batch(path, spec, root=root))
        except Exception as exc:  # inventory must surface malformed files instead of crashing discovery
            rows.append(
                {
                    "batch_file": path.name,
                    "batch_path": str(path),
                    "batch_relative_path": str(path.relative_to(root)),
                    "batch_sha256": sha256_file(path),
                    "rows": None,
                    "eligible_m7": False,
                    "eligibility_reason": f"read_error:{type(exc).__name__}",
                }
            )
    discovered = pd.DataFrame.from_records(rows)
    if discovered.empty:
        return CohortInventory(discovered, discovered.copy(), discovered.copy())
    eligible = discovered.loc[discovered["eligible_m7"].fillna(False)].copy()
    ignored = discovered.loc[~discovered["eligible_m7"].fillna(False)].copy()
    if not eligible.empty:
        eligible = eligible.sort_values(["min_t0", "batch_file"]).reset_index(drop=True)
    if not ignored.empty:
        ignored = ignored.sort_values(["batch_file"]).reset_index(drop=True)
    return CohortInventory(discovered, eligible, ignored)


def register_prospective_batches(root: Path, spec: ProspectiveSpec) -> CohortInventory:
    inventory = inventory_prospective_batches(root, spec)
    registry_path = root / spec.artifacts.cohort_registry
    new = inventory.eligible.copy()
    if new.empty:
        return inventory

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new["first_registered_at_utc"] = now

    if registry_path.exists():
        old = pd.read_parquet(registry_path)
        key = "scoring_batch_id"
        old_hash = old.set_index(key)["batch_sha256"].to_dict() if not old.empty else {}
        for row in new.itertuples(index=False):
            batch_id = getattr(row, key)
            if batch_id in old_hash and old_hash[batch_id] != row.batch_sha256:
                raise RuntimeError(
                    f"Immutable M7 batch changed bytes for {batch_id}: "
                    f"{old_hash[batch_id]} != {row.batch_sha256}"
                )
        merged = pd.concat([old, new.loc[~new[key].isin(set(old[key]))]], ignore_index=True)
    else:
        merged = new

    merged = merged.sort_values(["min_t0", "batch_file"]).reset_index(drop=True)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = registry_path.with_suffix(registry_path.suffix + ".tmp")
    merged.to_parquet(tmp, index=False)
    tmp.replace(registry_path)

    return CohortInventory(inventory.discovered, merged, inventory.ignored)


def shadow_span_days(registry: pd.DataFrame) -> int:
    if registry.empty:
        return 0
    start = pd.to_datetime(registry["min_t0"], errors="coerce").min()
    end = pd.to_datetime(registry["max_t0"], errors="coerce").max()
    if pd.isna(start) or pd.isna(end):
        return 0
    return max(0, int((end.normalize() - start.normalize()).days) + 1)


def mature_date_for_t0(t0: pd.Timestamp, spec: ProspectiveSpec):
    return (t0 + pd.Timedelta(days=spec.core.target_horizon_days)).date()
