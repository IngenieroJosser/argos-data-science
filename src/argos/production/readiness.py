from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.production import ProductionSpec
from argos.production.audit import verify_audit_chain
from argos.production.common import read_json, resolve

BUILD_IMPLEMENTATION = "m6-56-operational-readiness-v2"


@dataclass(frozen=True, slots=True)
class OperationalReadinessResult:
    evidence: pd.DataFrame
    validation: pd.DataFrame
    runbook_path: Path
    incident_path: Path
    human_review_path: Path
    retraining_path: Path
    security_path: Path
    manifest_path: Path

    @property
    def ready_for_next_notebook(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


def _component_status(reports_root: Path) -> tuple[dict[str, Any], bool]:
    status: dict[str, Any] = {}
    all_ok = True
    for notebook in range(50, 56):
        path = reports_root / "production" / f"{notebook}_validation.parquet"
        if not path.exists():
            status[str(notebook)] = {"exists": False}
            all_ok = False
            continue
        frame = pd.read_parquet(path)
        blocking = frame.loc[frame["blocking"]]
        ok = bool(not blocking.empty and blocking["passed"].all())
        status[str(notebook)] = {"exists": True, "blocking": len(blocking), "passed": int(blocking["passed"].sum()), "ok": ok}
        all_ok &= ok
    return status, all_ok


def _write_operational_docs(root: Path, production_spec: ProductionSpec) -> tuple[Path, Path, Path, Path, Path]:
    ops = root / "docs" / "operations"
    ops.mkdir(parents=True, exist_ok=True)
    runbook = ops / "ARGOS_V1_OPERATIONAL_RUNBOOK.md"
    incident = ops / "INCIDENT_RESPONSE.md"
    human = ops / "HUMAN_REVIEW_SOP.md"
    retraining = ops / "RETRAINING_POLICY.md"
    security = ops / "SECURITY_AND_ACCESS.md"

    runbook.write_text("""# ARGOS V1 — Operational Runbook\n\n## Operating mode\nBatch-first, shadow deployment, human review required. ARGOS produces analytical priority queues; it does not issue sanctions, fraud/corruption findings, eligibility decisions or legal conclusions.\n\n## Standard batch flow\n1. Freeze incoming scoring batch and compute SHA-256.\n2. Execute data-contract preflight.\n3. Score with the registered frozen model/calibrator.\n4. Persist deterministic ranking and batch manifest.\n5. Run drift/missingness/score monitoring.\n6. Materialize only the configured top-K review queue.\n7. Route the queue to human analysts.\n8. Persist audit evidence for every operational transition.\n\n## Stop conditions\n- schema or grain contract failure;\n- model/calibrator/contract hash mismatch;\n- non-finite scores;\n- high-severity monitoring alert when pause policy is enabled;\n- broken audit hash chain;\n- missing human-review workflow.\n\n## Recovery\nDo not mutate a failed batch in place. Correct the upstream issue, materialize a new immutable input batch, rerun preflight, and produce a new batch id.\n""", encoding="utf-8")

    incident.write_text("""# ARGOS — Incident Response\n\nSeverity HIGH includes schema breakage, model hash mismatch, audit-chain failure, or configured high drift. Immediate response: stop promotion/scoring as applicable, preserve artifacts, record the incident, identify the last known-good registry state, and execute the tested rollback/pause procedure. Never retune against TEST 2025 or OOT 2026 to clear an incident.\n""", encoding="utf-8")

    human.write_text("""# ARGOS — Human Review SOP\n\nThe model output is a priority signal. Reviewers receive contract id, prediction timestamp, score, raw score, rank, model version and batch lineage. Human outcomes are stored separately from immutable model evidence. A score is not a corruption/fraud finding and cannot directly trigger sanctions, exclusion, eligibility changes or legal conclusions.\n""", encoding="utf-8")

    retraining.write_text("""# ARGOS — Retraining Policy\n\nRetraining is event-driven or scheduled only after labels mature. Triggers include persistent drift, material ranking degradation, upstream schema changes, or an approved model-improvement cycle. TEST 2025 and OOT 2026 are consumed benchmarks and may not be reused as fresh final holdouts for V2. Any new model selected with knowledge from M4/M5 requires a later untouched temporal holdout before a new generalization claim.\n""", encoding="utf-8")

    security.write_text("""# ARGOS — Security and Access\n\nUse least privilege. Bronze/Silver sensitive fields are not model inputs by default and explicitly forbidden sensitive columns must not appear in scoring outputs or review queues. Registry, model artifacts, manifests and audit logs require restricted write access. Operational users may consume review queues without receiving training labels or sensitive source payloads. Secrets must be supplied by the deployment environment, never committed to the repository.\n""", encoding="utf-8")
    return runbook, incident, human, retraining, security


def build_operational_readiness(
    *,
    root: Path,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
) -> OperationalReadinessResult:
    status, components_ok = _component_status(reports_root)
    runbook, incident, human, retraining, security = _write_operational_docs(root, production_spec)
    state_path = resolve(root, production_spec.deployment.state_path)
    state = read_json(state_path)
    chain_ok, chain_events, chain_error = verify_audit_chain(root, log_path=production_spec.audit.log_path)

    required_repo_files = [root / "Dockerfile", root / ".dockerignore", root / ".github" / "workflows" / "ci.yml", root / "scripts" / "score_batch.py", root / "scripts" / "production_preflight.py"]
    evidence = pd.DataFrame.from_records([
        {"evidence": "components_50_55", "present": components_ok, "detail": str(status)},
        {"evidence": "container_contract", "present": (root / "Dockerfile").exists(), "detail": "Dockerfile"},
        {"evidence": "dockerignore_contract", "present": (root / ".dockerignore").exists(), "detail": ".dockerignore"},
        {"evidence": "ci_contract", "present": (root / ".github" / "workflows" / "ci.yml").exists(), "detail": ".github/workflows/ci.yml"},
        {"evidence": "audit_chain", "present": chain_ok, "detail": f"events={chain_events}; error={chain_error}"},
        {"evidence": "human_review", "present": production_spec.core.human_review_required, "detail": "required"},
        {"evidence": "production_auto_promotion", "present": not production_spec.deployment.allow_production_promotion, "detail": "disabled"},
    ])
    write_report(evidence, reports_root / "production" / "56_readiness_evidence.parquet")

    records: list[dict[str, Any]] = []
    add_validation(records, check_id="m6_components_50_55_complete", category="evidence", passed=components_ok, observed=status, requirement="all M6 operational components before readiness have passed their blocking checks")
    add_validation(records, check_id="deployment_assets_present", category="deployment", passed=all(p.exists() for p in required_repo_files), observed={"missing": [str(p.relative_to(root)) for p in required_repo_files if not p.exists()]}, requirement="container, CI and operator entrypoints are version-controlled")
    add_validation(records, check_id="operational_docs_present", category="documentation", passed=all(p.exists() for p in [runbook, incident, human, retraining, security]), observed={"paths": [str(p) for p in [runbook, incident, human, retraining, security]]}, requirement="operations, incident, human review, retraining and access procedures are explicit")
    add_validation(records, check_id="audit_chain_operational", category="audit", passed=chain_ok and chain_events >= 4, observed={"events": chain_events, "error": chain_error}, requirement="hash-chained audit logging contains end-to-end M6 operational evidence")
    add_validation(records, check_id="human_in_loop_is_enforced", category="governance", passed=production_spec.core.human_review_required and not production_spec.deployment.allow_production_promotion, observed={"human_review_required": production_spec.core.human_review_required, "production_promotion": production_spec.deployment.allow_production_promotion}, requirement="productionization automates prioritization, not institutional/legal judgment")
    add_validation(records, check_id="high_alerts_remain_visible", category="monitoring", passed="promotion_blocked" in state and "block_reason" in state, observed=state, requirement="deployment state explicitly carries monitoring/promotion blocking state rather than suppressing negative evidence")
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "production" / "56_validation.parquet")

    manifest_path = write_manifest(manifest_dir / "m6_operational_readiness.json", {"milestone": "M6", "component": "56_operational_readiness", "implementation": BUILD_IMPLEMENTATION, "schema_version": production_spec.schema_version, "shadow_ready": bool(validation.loc[validation["blocking"], "passed"].all()), "production_promotion_authorized": False, "deployment_state": state, "blocking_validation_passed": bool(validation.loc[validation["blocking"], "passed"].all())})
    return OperationalReadinessResult(evidence, validation, runbook, incident, human, retraining, security, manifest_path)
