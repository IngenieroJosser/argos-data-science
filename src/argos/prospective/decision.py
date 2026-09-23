from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argos.config.prospective import ProspectiveSpec
from argos.prospective.common import write_json_atomic

DECISION_IMPLEMENTATION = "m7-66-decision-record-v2"


@dataclass(frozen=True, slots=True)
class M7Decision:
    decision: str
    reasons: tuple[str, ...]
    artifact: Path
    approved_by: str


def record_decision(
    *,
    path: Path,
    spec: ProspectiveSpec,
    decision: str,
    reasons: list[str],
    evidence: dict[str, Any],
    approved_by: str,
) -> M7Decision:
    if decision not in spec.governance.allowed_decisions:
        raise ValueError(f"Unsupported M7 decision: {decision}")
    if not approved_by.strip():
        raise ValueError("M7 operational decision requires an explicit human approver")
    if not reasons:
        raise ValueError("M7 operational decision requires at least one documented reason")
    if path.exists():
        raise FileExistsError(
            f"M7 decision record already exists and is immutable: {path}. "
            "Create a superseding decision artifact instead of overwriting it."
        )
    payload = {
        "schema_version": spec.schema_version,
        "implementation": DECISION_IMPLEMENTATION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "approved_by": approved_by.strip(),
        "reasons": reasons,
        "evidence": evidence,
        "automatic_production_promotion": False,
        "human_review_required": True,
        "new_model_requires_new_future_holdout": spec.governance.new_model_requires_new_future_holdout,
    }
    write_json_atomic(path, payload)
    return M7Decision(
        decision=decision,
        reasons=tuple(reasons),
        artifact=path,
        approved_by=approved_by.strip(),
    )
