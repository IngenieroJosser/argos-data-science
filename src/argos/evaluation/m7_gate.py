from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation
from argos.config.prospective import ProspectiveSpec
from argos.config.production import load_production_spec
from argos.prospective.protocol import verify_frozen_protocol

GATE_IMPLEMENTATION = "m7-67-gate-v2"


@dataclass(frozen=True, slots=True)
class M7GateDecision:
    report: pd.DataFrame
    closed: bool
    decision: str
    decision_artifact: Path


def _validation_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "blocking": 0, "passed": 0, "failed": ["missing_report"]}
    frame = pd.read_parquet(path)
    blocking = frame.loc[frame["blocking"]]
    failed = blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist()
    return {
        "exists": True,
        "blocking": len(blocking),
        "passed": int(blocking["passed"].sum()),
        "failed": failed,
    }


def evaluate_m7_gate(
    *, root: Path, spec: ProspectiveSpec, reports_root: Path, docs_root: Path
) -> M7GateDecision:
    records: list[dict[str, Any]] = []
    m6_gate = docs_root / "decisions" / "M6_GATE.md"
    add_validation(
        records,
        check_id="m6_closed_prerequisite",
        category="prerequisite",
        passed=m6_gate.exists() and "M6 ✅ CLOSED" in m6_gate.read_text(encoding="utf-8"),
        observed={"path": str(m6_gate)},
        requirement="M7 requires formally closed M6",
    )

    production_spec = load_production_spec(root / "configs" / "production.toml")
    protocol_ok, protocol_details = verify_frozen_protocol(
        root=root,
        prospective_spec=spec,
        production_spec=production_spec,
        docs_root=docs_root,
    )
    add_validation(
        records,
        check_id="protocol_frozen_and_unchanged",
        category="lineage",
        passed=protocol_ok,
        observed=protocol_details,
        requirement="the prospective protocol and frozen V1 assets remain byte-identical to the preregistered hashes",
    )

    for notebook in range(60, 67):
        status = _validation_status(reports_root / "prospective" / f"{notebook}_validation.parquet")
        add_validation(
            records,
            check_id=f"notebook_{notebook}_blocking_checks",
            category="component",
            passed=status["exists"] and status["blocking"] > 0 and not status["failed"],
            observed=status,
            requirement=f"notebook {notebook} has all blocking M7 evidence-completeness checks passed",
        )

    decision_path = root / spec.artifacts.decision_record
    payload = json.loads(decision_path.read_text(encoding="utf-8")) if decision_path.exists() else {}
    allowed = payload.get("decision") in set(spec.governance.allowed_decisions)
    safe = (
        payload.get("automatic_production_promotion") is False
        and payload.get("human_review_required") is True
        and bool(str(payload.get("approved_by", "")).strip())
    )
    add_validation(
        records,
        check_id="explicit_governed_decision",
        category="governance",
        passed=allowed and safe,
        observed={
            "decision": payload.get("decision"),
            "approved_by": payload.get("approved_by"),
            "automatic_production_promotion": payload.get("automatic_production_promotion"),
            "human_review_required": payload.get("human_review_required"),
        },
        requirement="M7 ends with a human-approved governed decision and no automatic production promotion",
    )

    report = pd.DataFrame.from_records(records)
    write_report(report, reports_root / "prospective" / "m7_gate_report.parquet")
    blocking = report.loc[report["blocking"]]
    closed = bool(not blocking.empty and blocking["passed"].all())
    decision = str(payload.get("decision", "pending")) if closed else "pending"
    artifact = docs_root / "decisions" / "M7_GATE.md"
    failed = blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist()
    artifact.write_text(
        "# M7 Gate\n\n"
        f"**Implementation:** `{GATE_IMPLEMENTATION}`\n\n"
        f"**Decision:** {('M7 ✅ CLOSED' if closed else 'M7 ⏳ OPEN')}\n\n"
        f"**Blocking checks:** {int(blocking['passed'].sum())}/{len(blocking)}\n\n"
        f"**Operational decision:** `{decision}`\n\n"
        "M7 closure means that genuinely prospective evidence was collected and evaluated under the frozen protocol. "
        "It does not require the model to perform well: a negative result can legitimately close M7 with a governed "
        "decision such as `retrain_v2` or `continue_shadow`. Closure never authorizes autonomous legal, eligibility, "
        "enforcement or corruption/fraud decisions.\n\n"
        + ("**Failed checks:** none\n" if not failed else "**Pending/failed checks:** " + ", ".join(failed) + "\n"),
        encoding="utf-8",
    )
    return M7GateDecision(report=report, closed=closed, decision=decision, decision_artifact=artifact)
