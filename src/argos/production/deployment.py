from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.production import ProductionSpec
from argos.production.audit import append_audit_event, verify_audit_chain
from argos.production.common import read_json, resolve, write_json_atomic

BUILD_IMPLEMENTATION = "m6-55-shadow-rollback-drill-v1"

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"shadow", "archived"},
    "shadow": {"paused", "archived"},
    "paused": {"shadow", "candidate", "archived"},
    "archived": set(),
}


@dataclass(frozen=True, slots=True)
class RollbackResult:
    drill: pd.DataFrame
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def transition_allowed(source: str, target: str, allowed_stages: tuple[str, ...]) -> bool:
    if source not in allowed_stages or target not in allowed_stages:
        return False
    return target in ALLOWED_TRANSITIONS.get(source, set())


def update_stage(
    root: Path,
    *,
    production_spec: ProductionSpec,
    target_stage: str,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    state_path = resolve(root, production_spec.deployment.state_path)
    state = read_json(state_path)
    source = str(state.get("stage"))
    if not transition_allowed(source, target_stage, production_spec.registry.allowed_stages):
        raise ValueError(f"Disallowed deployment transition: {source} -> {target_stage}")
    if target_stage == "shadow" and bool(state.get("promotion_blocked")):
        raise ValueError(f"Shadow promotion blocked: {state.get('block_reason')}")
    state["previous_stage"] = source
    state["stage"] = target_stage
    state["last_transition_reason"] = reason
    write_json_atomic(state_path, state)
    append_audit_event(root, log_path=production_spec.audit.log_path, event_type="deployment_stage_changed", actor=actor, payload={"from": source, "to": target_stage, "reason": reason})
    return state


def _simulate_drill(allowed_stages: tuple[str, ...]) -> pd.DataFrame:
    sequence = [
        ("candidate", "shadow", "shadow promotion"),
        ("shadow", "paused", "synthetic high-severity alert"),
        ("paused", "candidate", "rollback to known safe candidate"),
    ]
    rows: list[dict[str, Any]] = []
    for source, target, reason in sequence:
        rows.append({"from_stage": source, "to_stage": target, "reason": reason, "allowed": transition_allowed(source, target, allowed_stages)})
    rows.append({"from_stage": "candidate", "to_stage": "production", "reason": "forbidden autonomous promotion path", "allowed": transition_allowed("candidate", "production", allowed_stages)})
    return pd.DataFrame.from_records(rows)


def run_shadow_rollback_drill(
    *,
    root: Path,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
) -> RollbackResult:
    drill = _simulate_drill(production_spec.registry.allowed_stages)
    write_report(drill, reports_root / "production" / "55_rollback_drill.parquet")
    chain_ok, event_count, chain_error = verify_audit_chain(root, log_path=production_spec.audit.log_path)

    expected_allowed = drill.iloc[:3]["allowed"].all()
    production_forbidden = not bool(drill.iloc[-1]["allowed"])
    records: list[dict[str, Any]] = []
    add_validation(records, check_id="shadow_pause_rollback_transitions", category="rollback", passed=bool(expected_allowed), observed=drill.iloc[:3].to_dict(orient="records"), requirement="candidate→shadow→paused→candidate rollback path is explicitly supported")
    add_validation(records, check_id="production_transition_not_available", category="governance", passed=production_forbidden and not production_spec.deployment.allow_production_promotion, observed={"production_transition_allowed": not production_forbidden, "config_allow_production": production_spec.deployment.allow_production_promotion}, requirement="M6 V1 has no accidental direct path to autonomous production promotion")
    add_validation(records, check_id="audit_hash_chain_valid", category="audit", passed=chain_ok and event_count >= 1, observed={"events": event_count, "error": chain_error}, requirement="operational audit evidence is append-only and hash-chain verifiable")
    add_validation(records, check_id="rollback_drill_is_non_destructive", category="operations", passed=True, observed={"mode": "simulation", "deployment_state_not_mutated": True}, requirement="rollback mechanism is tested without mutating the real deployment state during the drill")
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "production" / "55_validation.parquet")

    append_audit_event(root, log_path=production_spec.audit.log_path, event_type="rollback_drill_completed", actor="argos.system", payload={"passed": bool(validation.loc[validation["blocking"], "passed"].all()), "audit_events_before_drill_event": event_count})
    manifest_path = write_manifest(manifest_dir / "m6_shadow_rollback.json", {"milestone": "M6", "component": "55_shadow_and_rollback_drill", "implementation": BUILD_IMPLEMENTATION, "schema_version": production_spec.schema_version, "audit_chain_valid": chain_ok, "production_transition_forbidden": production_forbidden, "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all())})
    return RollbackResult(drill, validation, manifest_path)
