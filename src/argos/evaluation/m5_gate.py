from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation
from argos.robustness.common import load_frozen_v1, sha256_file


COMPONENT_REPORTS = (
    ("40", "40_validation.parquet"),
    ("41", "41_validation.parquet"),
    ("42", "42_validation.parquet"),
    ("43", "43_validation.parquet"),
    ("44", "44_validation.parquet"),
    ("45", "45_validation.parquet"),
    ("46", "46_validation.parquet"),
)

EXPECTED_MANIFESTS = (
    "m5_temporal_backtesting.json",
    "m5_explainability.json",
    "m5_uncertainty_ranking.json",
    "m5_drift_monitoring.json",
    "m5_feature_family_value.json",
    "m5_fresh_oot_2026.json",
    "m5_preproduction_evidence.json",
)

EXPECTED_REPORTS = (
    "40_backtest_metrics.parquet",
    "40_backtest_ranking.parquet",
    "41_global_permutation_importance.parquet",
    "41_local_sensitivity.parquet",
    "42_uncertainty_intervals.parquet",
    "42_tie_sensitivity.parquet",
    "43_feature_drift.parquet",
    "43_tail_calibration.parquet",
    "44_feature_family_metrics.parquet",
    "44_feature_family_deltas.parquet",
    "45_fresh_oot_metrics.parquet",
    "45_fresh_oot_ranking.parquet",
    "46_monitoring_thresholds.parquet",
    "46_evidence_summary.parquet",
)


@dataclass(frozen=True, slots=True)
class M5GateDecision:
    status: str
    blocking_passed: int
    blocking_total: int
    failed_checks: tuple[str, ...]

    @property
    def closed(self) -> bool:
        return self.status == "CLOSED"


def _blocking_report_ok(path: Path) -> tuple[bool, dict[str, Any]]:
    if not path.exists():
        return False, {"status": "missing", "path": str(path)}
    frame = pd.read_parquet(path)
    blocking = frame.loc[frame["blocking"]]
    ok = bool(not blocking.empty and blocking["passed"].all())
    return ok, {
        "blocking": int(len(blocking)),
        "passed": int(blocking["passed"].sum()) if not blocking.empty else 0,
        "failed": blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist(),
    }


def evaluate_m5_gate(
    *,
    root: Path,
    reports_root: Path,
    manifest_dir: Path,
    docs_root: Path,
    schema_version: str,
) -> tuple[pd.DataFrame, M5GateDecision]:
    records: list[dict[str, Any]] = []

    m4_gate = docs_root / "decisions" / "M4_GATE.md"
    m4_closed = m4_gate.exists() and "M4 ✅ CLOSED" in m4_gate.read_text(encoding="utf-8")
    add_validation(
        records,
        check_id="m4_gate_closed",
        category="prerequisite",
        passed=m4_closed,
        observed={"path": str(m4_gate), "exists": m4_gate.exists()},
        requirement="M5 may close only on top of a formally closed M4 predictive experiment",
    )

    for notebook, filename in COMPONENT_REPORTS:
        ok, observed = _blocking_report_ok(reports_root / "robustness" / filename)
        add_validation(
            records,
            check_id=f"notebook_{notebook}_blocking_checks",
            category="component",
            passed=ok,
            observed=observed,
            requirement=f"notebook {notebook} has all blocking checks passed",
        )

    missing_reports = [name for name in EXPECTED_REPORTS if not (reports_root / "robustness" / name).exists()]
    add_validation(
        records,
        check_id="m5_reports_complete",
        category="artifacts",
        passed=not missing_reports,
        observed={"missing": missing_reports, "expected": len(EXPECTED_REPORTS)},
        requirement="all required M5 robustness reports exist",
    )

    missing_manifests = [name for name in EXPECTED_MANIFESTS if not (manifest_dir / name).exists()]
    add_validation(
        records,
        check_id="m5_manifests_complete",
        category="lineage",
        passed=not missing_manifests,
        observed={"missing": missing_manifests},
        requirement="all M5 lineage manifests exist",
    )

    schema_errors: list[str] = []
    selection_errors: list[str] = []
    for name in EXPECTED_MANIFESTS:
        path = manifest_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("schema_version")) != schema_version:
            schema_errors.append(f"{name}:{payload.get('schema_version')!r}")
        if bool(payload.get("test_2025_used_for_selection", False)):
            selection_errors.append(name)
    add_validation(
        records,
        check_id="m5_schema_version_consistent",
        category="lineage",
        passed=not schema_errors,
        observed={"expected": schema_version, "errors": schema_errors},
        requirement="all M5 manifests declare the active robustness schema",
    )
    add_validation(
        records,
        check_id="consumed_test_not_reused_for_selection",
        category="governance",
        passed=not selection_errors,
        observed={"errors": selection_errors},
        requirement="no M5 development component reuses consumed TEST 2025 as a selection set",
    )

    fresh_manifest_path = manifest_dir / "m5_fresh_oot_2026.json"
    fresh_ok = False
    fresh_observed: dict[str, Any] = {"exists": fresh_manifest_path.exists()}
    if fresh_manifest_path.exists():
        fresh = json.loads(fresh_manifest_path.read_text(encoding="utf-8"))
        fresh_ok = bool(fresh.get("fresh_oot_consumed") and not fresh.get("model_reselected_after_fresh_oot", True))
        fresh_observed.update(
            {
                "fresh_oot_consumed": fresh.get("fresh_oot_consumed"),
                "model_reselected_after_fresh_oot": fresh.get("model_reselected_after_fresh_oot"),
                "cohort_start": fresh.get("cohort_start"),
                "cohort_end": fresh.get("cohort_end"),
            }
        )
    add_validation(
        records,
        check_id="fresh_oot_governance",
        category="governance",
        passed=fresh_ok,
        observed=fresh_observed,
        requirement="fresh 2026 OOT evidence is consumed once under a frozen V1 and does not trigger hidden reselection",
    )

    lineage_ok = False
    lineage_observed: dict[str, Any] = {}
    try:
        _, _, selection = load_frozen_v1(root)
        readiness_path = manifest_dir / "m5_preproduction_evidence.json"
        fresh_path = manifest_dir / "m5_fresh_oot_2026.json"
        if readiness_path.exists() and fresh_path.exists():
            readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
            fresh = json.loads(fresh_path.read_text(encoding="utf-8"))
            selection_path = root / "artifacts" / "models" / "m4" / "selected_model.json"
            lineage_ok = (
                readiness.get("model_sha256") == selection.get("model_sha256")
                and readiness.get("calibrator_sha256") == selection.get("calibrator_sha256")
                and fresh.get("model_sha256") == selection.get("model_sha256")
                and fresh.get("calibrator_sha256") == selection.get("calibrator_sha256")
                and fresh.get("selection_sha256") == sha256_file(selection_path)
            )
            lineage_observed = {
                "selection_sha256": sha256_file(selection_path),
                "fresh_selection_sha256": fresh.get("selection_sha256"),
                "model_sha256": selection.get("model_sha256"),
                "fresh_model_sha256": fresh.get("model_sha256"),
            }
    except (FileNotFoundError, ValueError, KeyError) as exc:
        lineage_observed = {"error": str(exc)}
    add_validation(
        records,
        check_id="frozen_v1_lineage_intact",
        category="lineage",
        passed=lineage_ok,
        observed=lineage_observed,
        requirement="M5 evidence traces to the exact M4 V1 model/calibrator frozen before final holdout evaluation",
    )

    robustness_card = docs_root / "models" / "ARGOS_V1_ROBUSTNESS_CARD.md"
    monitoring_spec = docs_root / "monitoring" / "ARGOS_V1_MONITORING_SPEC.md"
    add_validation(
        records,
        check_id="m5_documentation_complete",
        category="documentation",
        passed=robustness_card.exists() and monitoring_spec.exists(),
        observed={"robustness_card": robustness_card.exists(), "monitoring_spec": monitoring_spec.exists()},
        requirement="robustness evidence and monitoring contract are persisted before M5 closure",
    )

    readiness_manifest_path = manifest_dir / "m5_preproduction_evidence.json"
    production_false = False
    if readiness_manifest_path.exists():
        payload = json.loads(readiness_manifest_path.read_text(encoding="utf-8"))
        production_false = payload.get("production_authorized") is False
    add_validation(
        records,
        check_id="m5_does_not_auto_authorize_production",
        category="governance",
        passed=production_false,
        observed={"production_authorized": False if production_false else None},
        requirement="closing M5 completes robustness evidence but does not by itself authorize production deployment",
    )

    report = pd.DataFrame.from_records(records)
    blocking = report.loc[report["blocking"]]
    failed = tuple(blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist())
    decision = M5GateDecision(
        status="CLOSED" if len(blocking) > 0 and not failed else "OPEN",
        blocking_passed=int(blocking["passed"].sum()),
        blocking_total=int(len(blocking)),
        failed_checks=failed,
    )
    return report, decision


def render_m5_gate_markdown(report: pd.DataFrame, decision: M5GateDecision) -> str:
    icon = "✅" if decision.closed else "❌"
    lines = [
        "# M5 Gate — Advanced Data Science & Robustness",
        "",
        f"**Decision:** M5 {icon} {decision.status}",
        "",
        f"**Blocking checks:** {decision.blocking_passed}/{decision.blocking_total}",
        "",
        "## Checks",
        "",
        "| check_id | category | status | requirement | observed |",
        "|---|---|---|---|---|",
    ]
    for row in report.to_dict(orient="records"):
        status = "PASS" if bool(row["passed"]) else ("FAIL" if bool(row["blocking"]) else "DEFERRED")
        observed = str(row["observed"]).replace("|", "\\|").replace("\n", " ")
        requirement = str(row["requirement"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {row['check_id']} | {row['category']} | {status} | {requirement} | {observed} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "M5 closes only if temporal robustness, explainability, uncertainty, drift/calibration monitoring, fair feature-family revalidation, a fresh post-2025 OOT evaluation, and lineage/monitoring documentation are all complete.",
            "",
            "A closed M5 strengthens the evidence around ARGOS V1. It does not by itself authorize autonomous production use, legal determinations, or enforcement actions.",
            "",
        ]
    )
    if decision.failed_checks:
        lines.extend(["## Blocking failures", "", *[f"- `{x}`" for x in decision.failed_checks], ""])
    return "\n".join(lines)


def persist_m5_gate(
    *,
    report: pd.DataFrame,
    decision: M5GateDecision,
    reports_root: Path,
    decision_path: Path,
) -> tuple[Path, Path]:
    report_path = write_report(report, reports_root / "robustness" / "m5_gate_report.parquet")
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(render_m5_gate_markdown(report, decision), encoding="utf-8")
    return report_path, decision_path
