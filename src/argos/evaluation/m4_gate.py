from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation
from argos.models.calibration import sha256_file


COMPONENT_REPORTS = (
    ("30", "30_validation.parquet"),
    ("31", "31_validation.parquet"),
    ("32", "32_validation.parquet"),
    ("33", "33_validation.parquet"),
    ("34", "34_validation.parquet"),
    ("35", "35_validation.parquet"),
    ("36", "36_validation.parquet"),
)

EXPECTED_MANIFESTS = (
    "m4_baselines.json",
    "m4_logistic.json",
    "m4_boosting.json",
    "m4_calibration_selection.json",
    "m4_error_analysis.json",
    "m4_ablation.json",
    "m4_final_test.json",
)

EXPECTED_REPORTS = (
    "30_validation_metrics.parquet",
    "30_ranking_metrics.parquet",
    "31_validation_metrics.parquet",
    "32_validation_metrics.parquet",
    "33_candidate_metrics.parquet",
    "33_calibration_metrics.parquet",
    "33_ranking_metrics.parquet",
    "34_segment_error_analysis.parquet",
    "35_ablation_metrics.parquet",
    "36_final_test_metrics.parquet",
    "36_business_capacity_curve.parquet",
)


@dataclass(frozen=True, slots=True)
class M4GateDecision:
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


def evaluate_m4_gate(
    *,
    root: Path,
    reports_root: Path,
    model_dir: Path,
    manifest_dir: Path,
    docs_root: Path,
    schema_version: str,
) -> tuple[pd.DataFrame, M4GateDecision]:
    records: list[dict[str, Any]] = []

    m3_gate = docs_root / "decisions" / "M3_GATE.md"
    m3_closed = m3_gate.exists() and "M3 ✅ CLOSED" in m3_gate.read_text(encoding="utf-8")
    add_validation(records, check_id="m3_gate_closed", category="prerequisite", passed=m3_closed, observed={"path": str(m3_gate), "exists": m3_gate.exists()}, requirement="M4 may close only on top of a formally closed M3 Gold layer")

    for notebook, filename in COMPONENT_REPORTS:
        ok, observed = _blocking_report_ok(reports_root / "modeling" / filename)
        add_validation(records, check_id=f"notebook_{notebook}_blocking_checks", category="component", passed=ok, observed=observed, requirement=f"notebook {notebook} has all blocking checks passed")

    missing_reports = [name for name in EXPECTED_REPORTS if not (reports_root / "modeling" / name).exists()]
    add_validation(records, check_id="m4_reports_complete", category="artifacts", passed=not missing_reports, observed={"missing": missing_reports, "expected": len(EXPECTED_REPORTS)}, requirement="all required M4 evaluation reports exist")

    missing_manifests = [name for name in EXPECTED_MANIFESTS if not (manifest_dir / name).exists()]
    add_validation(records, check_id="m4_manifests_complete", category="lineage", passed=not missing_manifests, observed={"missing": missing_manifests}, requirement="all M4 lineage manifests exist")

    schema_errors: list[str] = []
    isolation_errors: list[str] = []
    for name in EXPECTED_MANIFESTS:
        path = manifest_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("schema_version")) != schema_version:
            schema_errors.append(f"{name}:{payload.get('schema_version')!r}")
        test_consumed = bool(payload.get("test_consumed", False))
        if name != "m4_final_test.json" and test_consumed:
            isolation_errors.append(name)
        if name == "m4_final_test.json" and not test_consumed:
            isolation_errors.append(name)
    add_validation(records, check_id="m4_schema_version_consistent", category="lineage", passed=not schema_errors, observed={"expected": schema_version, "errors": schema_errors}, requirement="all M4 manifests declare the active modeling schema")
    add_validation(records, check_id="test_isolation_manifest_policy", category="test_isolation", passed=not isolation_errors, observed={"errors": isolation_errors}, requirement="only notebook 36 / final-test manifest declares TEST consumption")

    selection_path = model_dir / "selected_model.json"
    final_manifest_path = manifest_dir / "m4_final_test.json"
    hashes_ok = False
    hash_observed: dict[str, Any] = {"selection_exists": selection_path.exists(), "final_manifest_exists": final_manifest_path.exists()}
    if selection_path.exists() and final_manifest_path.exists():
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        final_manifest = json.loads(final_manifest_path.read_text(encoding="utf-8"))
        hashes_ok = (
            selection.get("status") == "FROZEN_FOR_TEST"
            and final_manifest.get("selection_sha256") == sha256_file(selection_path)
            and final_manifest.get("model_sha256") == selection.get("model_sha256")
            and final_manifest.get("calibrator_sha256") == selection.get("calibrator_sha256")
        )
        hash_observed.update({
            "selection_status": selection.get("status"),
            "selection_sha256": sha256_file(selection_path),
            "manifest_selection_sha256": final_manifest.get("selection_sha256"),
        })
    add_validation(records, check_id="frozen_selection_matches_final_test", category="test_isolation", passed=hashes_ok, observed=hash_observed, requirement="final TEST used exactly the model/calibrator selection frozen before TEST access")

    model_card = docs_root / "models" / "ARGOS_V1_MODEL_CARD.md"
    add_validation(records, check_id="model_card_persisted", category="documentation", passed=model_card.exists(), observed={"path": str(model_card)}, requirement="final evaluated model has a persisted model card with scope and limitations")

    gate_report = pd.DataFrame.from_records(records)
    blocking = gate_report.loc[gate_report["blocking"]]
    failed = tuple(blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist())
    decision = M4GateDecision(
        status="CLOSED" if len(blocking) > 0 and not failed else "OPEN",
        blocking_passed=int(blocking["passed"].sum()),
        blocking_total=int(len(blocking)),
        failed_checks=failed,
    )
    return gate_report, decision


def render_m4_gate_markdown(report: pd.DataFrame, decision: M4GateDecision) -> str:
    icon = "✅" if decision.closed else "❌"
    lines = [
        "# M4 Gate — Modeling & Evaluation",
        "",
        f"**Decision:** M4 {icon} {decision.status}",
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
    lines.extend([
        "",
        "## Interpretation",
        "",
        "M4 closes only if model selection was frozen before TEST, the final TEST evaluation used those exact hashed artifacts, all required model/evaluation artifacts exist, and every component blocking check passes.",
        "",
        "A closed M4 validates the V1 predictive modeling experiment; it does not by itself authorize autonomous decision-making or production deployment.",
        "",
    ])
    if decision.failed_checks:
        lines.extend(["## Blocking failures", "", *[f"- `{x}`" for x in decision.failed_checks], ""])
    return "\n".join(lines)


def persist_m4_gate(
    *,
    report: pd.DataFrame,
    decision: M4GateDecision,
    reports_root: Path,
    decision_path: Path,
) -> tuple[Path, Path]:
    report_path = write_report(report, reports_root / "modeling" / "m4_gate_report.parquet")
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(render_m4_gate_markdown(report, decision), encoding="utf-8")
    return report_path, decision_path
