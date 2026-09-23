from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.silver.utils import add_validation
from argos.silver.validation import EXPECTED_ARTIFACTS, EXPECTED_MANIFESTS


@dataclass(frozen=True, slots=True)
class M2GateDecision:
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


def evaluate_m2_gate(
    *,
    reports_root: Path,
    silver_dir: Path,
    manifest_dir: Path,
    schema_version: str,
) -> tuple[pd.DataFrame, M2GateDecision]:
    records: list[dict[str, Any]] = []

    for notebook, filename in [
        ("10", "10_validation.parquet"),
        ("11", "11_validation.parquet"),
        ("12", "12_validation.parquet"),
        ("13", "13_validation.parquet"),
    ]:
        ok, observed = _blocking_report_ok(reports_root / "silver" / filename)
        add_validation(
            records,
            check_id=f"notebook_{notebook}_blocking_checks",
            category="component",
            passed=ok,
            observed=observed,
            requirement=f"notebook {notebook} has all blocking checks passed",
        )

    validation_ok, validation_observed = _blocking_report_ok(
        reports_root / "silver" / "m2_validation.parquet"
    )
    add_validation(
        records,
        check_id="notebook_14_cross_validation",
        category="validation",
        passed=validation_ok,
        observed=validation_observed,
        requirement="notebook 14 cross-Silver validation has no blocking failure",
    )

    missing_artifacts = [name for name in EXPECTED_ARTIFACTS if not (silver_dir / name).exists()]
    add_validation(
        records,
        check_id="canonical_artifacts_complete",
        category="artifacts",
        passed=not missing_artifacts,
        observed={"missing": missing_artifacts, "expected": len(EXPECTED_ARTIFACTS)},
        requirement="all M2 canonical Silver artifacts exist",
    )

    missing_manifests = [name for name in EXPECTED_MANIFESTS if not (manifest_dir / name).exists()]
    validation_manifest = manifest_dir / "silver_m2_validation.json"
    if not validation_manifest.exists():
        missing_manifests.append(validation_manifest.name)
    add_validation(
        records,
        check_id="lineage_manifests_complete",
        category="lineage",
        passed=not missing_manifests,
        observed={"missing": missing_manifests},
        requirement="component and M2 validation manifests are persisted",
    )

    manifest_schema_errors: list[str] = []
    for name in [*EXPECTED_MANIFESTS, validation_manifest.name]:
        path = manifest_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("schema_version")) != schema_version:
            manifest_schema_errors.append(
                f"{name}:{payload.get('schema_version')!r}"
            )
    add_validation(
        records,
        check_id="manifest_schema_version_consistent",
        category="lineage",
        passed=not manifest_schema_errors,
        observed={"expected": schema_version, "errors": manifest_schema_errors},
        requirement="all M2 manifests declare the active Silver schema version",
    )

    issues_path = reports_root / "silver" / "m2_issue_register.parquet"
    if issues_path.exists():
        issues = pd.read_parquet(issues_path)
        blocking_issues = int(
            (issues["severity"] == "blocking").sum() if not issues.empty else 0
        )
        warning_issues = int(
            (issues["severity"] == "warning").sum() if not issues.empty else 0
        )
    else:
        blocking_issues = -1
        warning_issues = -1
    add_validation(
        records,
        check_id="no_blocking_silver_issues",
        category="quality",
        passed=blocking_issues == 0,
        observed={"blocking_issues": blocking_issues, "warning_issues": warning_issues},
        requirement="M2 issue register exists and contains zero blocking issues",
    )

    er_summary_path = reports_root / "silver" / "13_resolution_summary.parquet"
    er_ok = False
    er_observed: Any = "missing"
    if er_summary_path.exists():
        summary = pd.read_parquet(er_summary_path)
        er_ok = not summary.empty
        er_observed = {
            "rows": int(len(summary)),
            "statuses": sorted(summary["resolution_status"].dropna().astype(str).unique().tolist()),
        }
    add_validation(
        records,
        check_id="entity_resolution_audited",
        category="entity_resolution",
        passed=er_ok,
        observed=er_observed,
        requirement="bidder→supplier resolution has an explicit strategy/status summary, including unresolved population",
    )

    report = pd.DataFrame.from_records(records)
    blocking = report.loc[report["blocking"]]
    failed = tuple(blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist())
    passed = int(blocking["passed"].sum())
    total = int(len(blocking))
    decision = M2GateDecision(
        status="CLOSED" if total > 0 and not failed else "OPEN",
        blocking_passed=passed,
        blocking_total=total,
        failed_checks=failed,
    )
    return report, decision


def render_m2_gate_markdown(report: pd.DataFrame, decision: M2GateDecision) -> str:
    icon = "✅" if decision.closed else "❌"
    lines = [
        "# M2 Gate — Silver canonical domain layer",
        "",
        f"**Decision:** M2 {icon} {decision.status}",
        "",
        f"**Blocking checks:** {decision.blocking_passed}/{decision.blocking_total}",
        "",
        "## Checks",
        "",
        "| check_id | category | status | requirement | observed |",
        "|---|---|---|---|---|",
    ]
    for row in report.to_dict(orient="records"):
        if bool(row["passed"]):
            status = "PASS"
        elif bool(row["blocking"]):
            status = "FAIL"
        else:
            status = "DEFERRED"
        observed = str(row["observed"]).replace("|", "\\|").replace("\n", " ")
        requirement = str(row["requirement"]).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {row['check_id']} | {row['category']} | {status} | {requirement} | {observed} |"
        )
    lines.extend(
        [
            "",
            "## Scope notes",
            "",
            "- Silver remains a reusable domain layer; it is not a model feature whitelist.",
            "- Payments and sanctions remain deferred from the addition-risk V1 scope.",
            "- The semantic scope of the prediction label is frozen later in Gold; Silver preserves all addition event types.",
            "- Entity-resolution ambiguity is preserved explicitly rather than converted into guessed links.",
            "",
        ]
    )
    if decision.failed_checks:
        lines.extend(
            [
                "## Blocking failures",
                "",
                *[f"- `{check}`" for check in decision.failed_checks],
                "",
            ]
        )
    return "\n".join(lines)


def persist_m2_gate(
    *,
    report: pd.DataFrame,
    decision: M2GateDecision,
    reports_root: Path,
    decision_path: Path,
) -> tuple[Path, Path]:
    report_path = write_report(report, reports_root / "silver" / "m2_gate_report.parquet")
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(render_m2_gate_markdown(report, decision), encoding="utf-8")
    return report_path, decision_path
