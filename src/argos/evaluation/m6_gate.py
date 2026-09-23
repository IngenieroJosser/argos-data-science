from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation
from argos.config.production import ProductionSpec
from argos.production.audit import verify_audit_chain
from argos.production.common import read_json, resolve, sha256_file


@dataclass(frozen=True, slots=True)
class M6GateDecision:
    report: pd.DataFrame
    closed: bool
    deployment_status: str
    decision_artifact: Path


def _validation_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "blocking": 0, "passed": 0, "failed": ["missing_report"]}
    frame = pd.read_parquet(path)
    blocking = frame.loc[frame["blocking"]]
    failed = blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist()
    return {"exists": True, "blocking": len(blocking), "passed": int(blocking["passed"].sum()), "failed": failed}


def evaluate_m6_gate(
    *,
    root: Path,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
    docs_root: Path,
) -> M6GateDecision:
    records: list[dict[str, Any]] = []
    m5_gate = docs_root / "decisions" / "M5_GATE.md"
    add_validation(records, check_id="m5_closed_prerequisite", category="prerequisite", passed=m5_gate.exists() and "M5 ✅ CLOSED" in m5_gate.read_text(encoding="utf-8"), observed={"path": str(m5_gate)}, requirement="M6 starts from a formally closed M5")

    component_status: dict[str, Any] = {}
    for notebook in range(50, 57):
        path = reports_root / "production" / f"{notebook}_validation.parquet"
        status = _validation_status(path)
        component_status[str(notebook)] = status
        add_validation(records, check_id=f"notebook_{notebook}_blocking_checks", category="component", passed=status["exists"] and not status["failed"] and status["blocking"] > 0, observed=status, requirement=f"notebook {notebook} has all blocking operational checks passed")

    expected_manifests = [
        "m6_runtime_registry.json",
        "m6_data_contract_preflight.json",
        "m6_monitoring.json",
        "m6_human_review_queue.json",
        "m6_shadow_rollback.json",
        "m6_operational_readiness.json",
    ]
    scoring_manifests = sorted(manifest_dir.glob("m6_scoring_*.json"))
    missing_manifests = [name for name in expected_manifests if not (manifest_dir / name).exists()]
    add_validation(records, check_id="m6_manifests_complete", category="lineage", passed=not missing_manifests and len(scoring_manifests) >= 1, observed={"missing": missing_manifests, "scoring_manifests": [p.name for p in scoring_manifests]}, requirement="M6 persists lineage for registry, contract, scoring, monitoring, human review, rollback and readiness")

    schema_errors: list[str] = []
    for path in [*(manifest_dir / name for name in expected_manifests if (manifest_dir / name).exists()), *scoring_manifests]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != production_spec.schema_version:
            schema_errors.append(f"{path.name}:{payload.get('schema_version')}")
    add_validation(records, check_id="m6_schema_consistent", category="lineage", passed=not schema_errors, observed={"errors": schema_errors, "expected": production_spec.schema_version}, requirement="all M6 operational manifests declare the active production schema")

    registry_path = resolve(root, production_spec.registry.registry_record)
    state_path = resolve(root, production_spec.deployment.state_path)
    contract_path = resolve(root, production_spec.data_contract.contract_artifact)
    registry = read_json(registry_path) if registry_path.exists() else {}
    state = read_json(state_path) if state_path.exists() else {}
    selection = read_json(resolve(root, production_spec.registry.selection_manifest))
    lineage_ok = bool(registry) and registry.get("model_sha256") == selection.get("model_sha256") and registry.get("calibrator_sha256") == selection.get("calibrator_sha256")
    add_validation(records, check_id="frozen_model_registry_lineage", category="lineage", passed=lineage_ok, observed={"registry_model": registry.get("model_sha256"), "selection_model": selection.get("model_sha256"), "registry_calibrator": registry.get("calibrator_sha256"), "selection_calibrator": selection.get("calibrator_sha256")}, requirement="operational registry still references the exact frozen ARGOS V1 artifacts")

    chain_ok, event_count, chain_error = verify_audit_chain(root, log_path=production_spec.audit.log_path)
    add_validation(records, check_id="operational_audit_chain", category="audit", passed=chain_ok and event_count >= 5, observed={"events": event_count, "error": chain_error}, requirement="M6 has verifiable end-to-end operational audit evidence")

    add_validation(records, check_id="human_review_governance", category="governance", passed=production_spec.core.human_review_required and not production_spec.deployment.allow_production_promotion and registry.get("decision_mode") == "human_review_required", observed={"human_review_required": production_spec.core.human_review_required, "production_promotion_authorized": production_spec.deployment.allow_production_promotion, "registry_decision_mode": registry.get("decision_mode")}, requirement="M6 automates scoring/prioritization but preserves human institutional judgment")
    add_validation(records, check_id="shadow_only_deployment_state", category="governance", passed=state.get("stage") in set(production_spec.registry.allowed_stages) and state.get("stage") != "production" and not registry.get("production_promotion_authorized", True), observed=state, requirement="M6 closes as shadow/human-review operationalization, not autonomous production promotion")

    required_docs = [
        docs_root / "operations" / "ARGOS_V1_OPERATIONAL_RUNBOOK.md",
        docs_root / "operations" / "INCIDENT_RESPONSE.md",
        docs_root / "operations" / "HUMAN_REVIEW_SOP.md",
        docs_root / "operations" / "RETRAINING_POLICY.md",
        docs_root / "operations" / "SECURITY_AND_ACCESS.md",
    ]
    add_validation(records, check_id="operational_documentation_complete", category="documentation", passed=all(p.exists() for p in required_docs), observed={"missing": [str(p) for p in required_docs if not p.exists()]}, requirement="operators have explicit runbook, incident, review, retraining and security procedures")

    preflight_manifest_path = manifest_dir / "m6_data_contract_preflight.json"
    preflight_manifest = read_json(preflight_manifest_path) if preflight_manifest_path.exists() else {}
    contract_hash = sha256_file(contract_path) if contract_path.exists() else None
    add_validation(records, check_id="scoring_contract_frozen", category="contract", passed=contract_path.exists() and contract_hash == preflight_manifest.get("contract_sha256"), observed={"contract": str(contract_path), "contract_sha256": contract_hash, "manifest_sha256": preflight_manifest.get("contract_sha256")}, requirement="the production scoring contract is persisted, hashed and consistent with preflight lineage")

    report = pd.DataFrame.from_records(records)
    write_report(report, reports_root / "production" / "m6_gate_report.parquet")
    blocking = report.loc[report["blocking"]]
    closed = bool(not blocking.empty and blocking["passed"].all())
    if not closed:
        deployment_status = "NOT_READY"
    elif bool(state.get("promotion_blocked")):
        deployment_status = "OPERATIONALLY_READY_PROMOTION_BLOCKED"
    else:
        deployment_status = "SHADOW_READY"
    decision_artifact = docs_root / "decisions" / "M6_GATE.md"
    failed = blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist()
    decision_artifact.write_text(
        "# M6 Gate\n\n"
        f"**Decision:** {('M6 ✅ CLOSED — ' + deployment_status) if closed else 'M6 ❌ OPEN'}\n\n"
        f"**Blocking checks:** {int(blocking['passed'].sum())}/{len(blocking)}\n\n"
        f"**Deployment status:** `{deployment_status}`\n\n"
        "M6 closure validates reproducible batch scoring, lineage, executable monitoring, auditability, rollback and human-review workflow. It does **not** authorize autonomous sanctions, eligibility decisions, corruption/fraud findings or legal conclusions. Direct production promotion remains disabled in `configs/production.toml`.\n\n"
        + ("**Failed checks:** none\n" if not failed else "**Failed checks:** " + ", ".join(failed) + "\n"),
        encoding="utf-8",
    )
    return M6GateDecision(report, closed, deployment_status, decision_artifact)
