from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation
from argos.config.advanced import AdvancedSpec
from argos.config.production import ProductionSpec
from argos.config.prospective import ProspectiveSpec
from argos.prospective.protocol import verify_frozen_protocol


@dataclass(frozen=True, slots=True)
class M8GateDecision:
    report: pd.DataFrame
    closed: bool
    decision: str
    selected_family: str | None
    decision_artifact: Path


def validation_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "blocking": 0, "passed": 0, "failed": ["missing_report"]}
    frame = pd.read_parquet(path)
    blocking = frame.loc[frame["blocking"]]
    failed = blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist()
    return {
        "exists": True,
        "blocking": int(len(blocking)),
        "passed": int(blocking["passed"].sum()),
        "failed": failed,
    }


def evaluate_m8_gate(
    *,
    root: Path,
    advanced_spec: AdvancedSpec,
    prospective_spec: ProspectiveSpec,
    production_spec: ProductionSpec,
    reports_root: Path,
    manifest_dir: Path,
    docs_root: Path,
) -> M8GateDecision:
    records: list[dict[str, Any]] = []

    m6_gate = docs_root / "decisions" / "M6_GATE.md"
    m6_closed = m6_gate.exists() and "M6 ✅ CLOSED" in m6_gate.read_text(encoding="utf-8")
    add_validation(
        records,
        check_id="m6_closed_prerequisite",
        category="prerequisite",
        passed=(not advanced_spec.governance.require_m6_closed) or m6_closed,
        observed={"path": str(m6_gate)},
        requirement="M8 extends the formally closed M6 baseline",
    )

    m7_verified, m7_details = verify_frozen_protocol(
        root=root,
        prospective_spec=prospective_spec,
        production_spec=production_spec,
        docs_root=docs_root,
    )
    add_validation(
        records,
        check_id="m7_protocol_unchanged",
        category="governance",
        passed=(not advanced_spec.acceptance.require_m7_hash_integrity) or m7_verified,
        observed=m7_details,
        requirement="ARGOS V1 prospective M7 protocol remains frozen while M8 develops V2 signals",
    )

    component_reports = {
        "70_semantic": reports_root / "advanced" / "70_validation.parquet",
        "71_graph": reports_root / "advanced" / "71_validation.parquet",
        "72_anomaly": reports_root / "advanced" / "72_validation.parquet",
        "73_matrix": reports_root / "advanced" / "73_matrix_validation.parquet",
        "73_pit": reports_root / "advanced" / "73_validation.parquet",
        "74_ablation": reports_root / "advanced" / "74_validation.parquet",
        "75_survival_outcomes": reports_root / "advanced" / "75_validation.parquet",
        "76_survival": reports_root / "advanced" / "76_validation.parquet",
    }
    for stage, path in component_reports.items():
        status = validation_status(path)
        add_validation(
            records,
            check_id=f"{stage}_blocking_checks",
            category="component",
            passed=status["exists"] and status["blocking"] > 0 and not status["failed"],
            observed=status,
            requirement=f"M8 component {stage} persists and passes blocking validation",
        )

    expected_manifests = [
        Path(advanced_spec.artifacts.semantic_manifest).name,
        Path(advanced_spec.artifacts.graph_manifest).name,
        Path(advanced_spec.artifacts.anomaly_manifest).name,
        Path(advanced_spec.artifacts.survival_outcomes_manifest).name,
        Path(advanced_spec.artifacts.survival_manifest).name,
        Path(advanced_spec.artifacts.pit_manifest).name,
        Path(advanced_spec.artifacts.ablation_manifest).name,
        Path(advanced_spec.artifacts.selection_manifest).name,
    ]
    missing_manifests = [name for name in expected_manifests if not (manifest_dir / name).exists()]
    add_validation(
        records,
        check_id="m8_manifests_complete",
        category="lineage",
        passed=not missing_manifests,
        observed={"missing": missing_manifests},
        requirement=(
            "M8 persists complete semantic/graph/anomaly/survival/PIT/ablation/selection lineage"
        ),
    )

    schema_errors: list[str] = []
    holdout_errors: list[str] = []
    manifest_payloads: dict[str, dict[str, Any]] = {}
    for name in expected_manifests:
        path = manifest_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest_payloads[name] = payload
        if payload.get("schema_version") != advanced_spec.schema_version:
            schema_errors.append(f"{name}:{payload.get('schema_version')}")
        if payload.get("consumed_test_or_oot_for_selection") is True:
            holdout_errors.append(name)

    semantic_payload = manifest_payloads.get(
        Path(advanced_spec.artifacts.semantic_manifest).name, {}
    )
    semantic_backend_ok = (
        semantic_payload.get("embedding_backend_used") == advanced_spec.nlp.embedding_backend
        and (
            semantic_payload.get("index_backend_used") == advanced_spec.nlp.index_backend
            or advanced_spec.nlp.allow_fallback_for_gate
        )
    )
    add_validation(
        records,
        check_id="m8_semantic_backend_authoritative",
        category="runtime",
        passed=(not advanced_spec.acceptance.require_semantic_backend) or semantic_backend_ok,
        observed={
            "embedding_backend_used": semantic_payload.get("embedding_backend_used"),
            "index_backend_used": semantic_payload.get("index_backend_used"),
        },
        requirement="formal M8 closure uses the configured semantic embedding and ANN backends",
    )

    pit_payload = manifest_payloads.get(Path(advanced_spec.artifacts.pit_manifest).name, {})
    pit_violations = pit_payload.get("future_feature_violations", {})
    graph_contract_violations = pit_violations.get("graph_contract")
    graph_cobid_violations = pit_violations.get("graph_cobid")
    graph_pit_complete = isinstance(graph_contract_violations, int) and isinstance(
        graph_cobid_violations, int
    )
    graph_pit_violations = (
        int(graph_contract_violations) + int(graph_cobid_violations)
        if graph_pit_complete
        else None
    )
    graph_pit_ok = (
        graph_pit_complete
        and graph_pit_violations is not None
        and graph_pit_violations <= advanced_spec.governance.max_future_feature_violations
    )
    add_validation(
        records,
        check_id="m8_graph_pit_authoritative",
        category="point_in_time",
        passed=(not advanced_spec.acceptance.require_graph_pit) or graph_pit_ok,
        observed={"future_graph_violations": graph_pit_violations},
        requirement="formal M8 closure independently verifies zero future graph observations",
    )

    anomaly_payload = manifest_payloads.get(Path(advanced_spec.artifacts.anomaly_manifest).name, {})
    anomaly_train_only = anomaly_payload.get("fitted_split") == "train"
    add_validation(
        records,
        check_id="m8_anomaly_train_fit_authoritative",
        category="evaluation_governance",
        passed=(not advanced_spec.acceptance.require_anomaly_train_only_fit) or anomaly_train_only,
        observed={"fitted_split": anomaly_payload.get("fitted_split")},
        requirement="formal M8 closure independently verifies TRAIN-only anomaly fitting",
    )

    ablation_payload = manifest_payloads.get(
        Path(advanced_spec.artifacts.ablation_manifest).name, {}
    )
    ablation_families = set(str(v) for v in ablation_payload.get("families", []))
    ablation_ok = set(advanced_spec.ablation.families).issubset(ablation_families)
    add_validation(
        records,
        check_id="m8_temporal_ablation_authoritative",
        category="ablation",
        passed=(not advanced_spec.acceptance.require_temporal_ablation) or ablation_ok,
        observed={"families": sorted(ablation_families)},
        requirement="formal M8 closure independently verifies all configured ablation families",
    )

    survival_payload = manifest_payloads.get(
        Path(advanced_spec.artifacts.survival_manifest).name, {}
    )
    survival_outcomes_payload = manifest_payloads.get(
        Path(advanced_spec.artifacts.survival_outcomes_manifest).name, {}
    )
    survival_horizon = survival_outcomes_payload.get("horizon_days")
    survival_ok = (
        survival_payload.get("fitted_split") == "train"
        and survival_payload.get("evaluated_split") == "validation"
        and survival_payload.get("optimizer_success") is True
        and survival_payload.get("consumed_test_or_oot_for_selection") is False
        and survival_outcomes_payload.get("consumed_test_or_oot_for_selection") is False
        and isinstance(survival_horizon, int)
        and survival_horizon == advanced_spec.survival.horizon_days
        and tuple(survival_payload.get("evaluation_horizons", []))
        == advanced_spec.survival.evaluation_horizons
    )
    add_validation(
        records,
        check_id="m8_survival_authoritative",
        category="survival",
        passed=(not advanced_spec.acceptance.require_survival_analysis) or survival_ok,
        observed={
            "fitted_split": survival_payload.get("fitted_split"),
            "evaluated_split": survival_payload.get("evaluated_split"),
            "optimizer_success": survival_payload.get("optimizer_success"),
            "evaluation_horizons": survival_payload.get("evaluation_horizons"),
            "horizon_days": survival_outcomes_payload.get("horizon_days"),
        },
        requirement=(
            "formal M8 closure includes TRAIN-fit/VALIDATION-evaluated survival analysis "
            "with administrative censoring and no consumed holdout reuse"
        ),
    )

    add_validation(
        records,
        check_id="m8_schema_consistent",
        category="lineage",
        passed=not schema_errors,
        observed={"errors": schema_errors, "expected": advanced_spec.schema_version},
        requirement="all M8 manifests use the same advanced-intelligence schema",
    )
    add_validation(
        records,
        check_id="m8_consumed_holdouts_never_selected_on",
        category="evaluation_governance",
        passed=(
            not advanced_spec.acceptance.require_no_consumed_holdout_selection
            or (
                not holdout_errors
                and not advanced_spec.governance.allow_consumed_holdouts_for_selection
            )
        ),
        observed={
            "manifest_violations": holdout_errors,
            "consumed_years": list(advanced_spec.governance.consumed_holdout_years),
        },
        requirement="TEST 2025 and OOT 2026 remain unavailable for M8 feature/model selection",
    )

    selection_path = root / advanced_spec.artifacts.selection_manifest
    selection = (
        json.loads(selection_path.read_text(encoding="utf-8"))
        if selection_path.exists()
        else {}
    )
    selection_decision = selection.get("decision")
    selected_family = selection.get("selected_family")
    selection_ok = (
        selection_decision in {"PROMOTE_M8_FEATURES", "RESEARCH_COMPLETE_NO_PROMOTION"}
        and selection.get("consumed_test_or_oot_for_selection") is False
        and selection.get("final_unbiased_validation_required") is True
    )
    add_validation(
        records,
        check_id="m8_explicit_feature_decision",
        category="governance",
        passed=(not advanced_spec.acceptance.require_explicit_feature_selection) or selection_ok,
        observed={
            "decision": selection_decision,
            "selected_family": selected_family,
            "final_unbiased_validation_required": selection.get(
                "final_unbiased_validation_required"
            ),
        },
        requirement=(
            "M8 persists explicit promote/no-promote evidence and requires a new future "
            "holdout for V2"
        ),
    )

    required_docs = [
        docs_root / "M8_RUNBOOK.md",
        docs_root / "M8_HANDOFF.md",
        docs_root / "data-dictionary" / "m8_advanced_intelligence_catalog.md",
        docs_root / "decisions" / "M8_START_2026-09-23.md",
    ]
    add_validation(
        records,
        check_id="m8_documentation_complete",
        category="documentation",
        passed=all(path.exists() for path in required_docs),
        observed={"missing": [str(path) for path in required_docs if not path.exists()]},
        requirement=(
            "M8 has executable runbook, handoff, feature catalog and governance start record"
        ),
    )
    add_validation(
        records,
        check_id="m8_human_review_semantics_preserved",
        category="governance",
        passed=(
            advanced_spec.governance.human_review_required
            and prospective_spec.governance.human_review_required
            and not prospective_spec.governance.automatic_production_promotion
        ),
        observed={
            "m8_human_review_required": advanced_spec.governance.human_review_required,
            "m7_human_review_required": prospective_spec.governance.human_review_required,
            "m7_auto_promotion": prospective_spec.governance.automatic_production_promotion,
        },
        requirement=(
            "advanced signals remain human-review prioritization evidence, not autonomous "
            "legal/corruption findings"
        ),
    )

    report = pd.DataFrame.from_records(records)
    write_report(report, reports_root / "advanced" / "m8_gate_report.parquet")
    blocking = report.loc[report["blocking"]]
    closed = bool(not blocking.empty and blocking["passed"].all())
    decision = str(selection_decision) if closed else "M8_OPEN"
    failed = blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist()

    decision_artifact = docs_root / "decisions" / "M8_GATE.md"
    decision_artifact.write_text(
        "# M8 Gate\n\n"
        f"**Decision:** {('M8 ✅ CLOSED — ' + decision) if closed else 'M8 ❌ OPEN'}\n\n"
        f"**Blocking checks:** {int(blocking['passed'].sum())}/{len(blocking)}\n\n"
        f"**Selected feature family:** `{selected_family or 'none'}`\n\n"
        "M8 closes advanced-intelligence research only when NLP, graph and anomaly signals are "
        "point-in-time safe, survival analysis is valid, temporal ablation is persisted, consumed "
        "holdouts remain sealed, and "
        "the frozen M7 protocol is unchanged. M8 does not replace M7 and is not final unbiased "
        "validation of ARGOS V2; any V2 promotion requires a new future holdout. Anomaly/graph "
        "signals are prioritization evidence, not findings of corruption, fraud, illegality or "
        "supplier ineligibility.\n\n"
        + (
            "**Failed checks:** none\n"
            if not failed
            else "**Failed checks:** " + ", ".join(failed) + "\n"
        ),
        encoding="utf-8",
    )
    return M8GateDecision(
        report=report,
        closed=closed,
        decision=decision,
        selected_family=selected_family,
        decision_artifact=decision_artifact,
    )
