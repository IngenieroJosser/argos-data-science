from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from argos.common.reports import write_report
from argos.common.validation import add_validation


EXPECTED_GOLD_ARTIFACTS = (
    "target_population.parquet",
    "labels/y_addition_180d.parquet",
    "splits/temporal_split.parquet",
    "features/contract_features.parquet",
    "features/historical_features.parquet",
    "features/competition_features.parquet",
    "ml/argos_v1.parquet",
)

EXPECTED_GOLD_MANIFESTS = (
    "gold_target_y_addition_180d.json",
    "gold_temporal_split.json",
    "gold_train_eda.json",
    "gold_contract_features.json",
    "gold_historical_features.json",
    "gold_competition_features.json",
    "gold_pit_audit.json",
)

COMPONENT_REPORTS = (
    ("20", "20_target_validation.parquet"),
    ("21", "21_split_validation.parquet"),
    ("22", "22_train_eda_validation.parquet"),
    ("23", "23_contract_features_validation.parquet"),
    ("24", "24_historical_features_validation.parquet"),
    ("25", "25_competition_features_validation.parquet"),
    ("26", "26_pit_validation.parquet"),
)


@dataclass(frozen=True, slots=True)
class M3GateDecision:
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


def evaluate_m3_gate(
    *,
    reports_root: Path,
    gold_dir: Path,
    manifest_dir: Path,
    docs_root: Path,
    schema_version: str,
) -> tuple[pd.DataFrame, M3GateDecision]:
    records: list[dict[str, Any]] = []

    for notebook, filename in COMPONENT_REPORTS:
        ok, observed = _blocking_report_ok(reports_root / "gold" / filename)
        add_validation(
            records,
            check_id=f"notebook_{notebook}_blocking_checks",
            category="component",
            passed=ok,
            observed=observed,
            requirement=f"notebook {notebook} has all blocking checks passed",
        )

    missing_artifacts = [
        name for name in EXPECTED_GOLD_ARTIFACTS if not (gold_dir / name).exists()
    ]
    add_validation(
        records,
        check_id="gold_artifacts_complete",
        category="artifacts",
        passed=not missing_artifacts,
        observed={"missing": missing_artifacts, "expected": len(EXPECTED_GOLD_ARTIFACTS)},
        requirement="all canonical M3 Gold artifacts exist",
    )

    missing_manifests = [
        name for name in EXPECTED_GOLD_MANIFESTS if not (manifest_dir / name).exists()
    ]
    add_validation(
        records,
        check_id="gold_lineage_manifests_complete",
        category="lineage",
        passed=not missing_manifests,
        observed={"missing": missing_manifests},
        requirement="all M3 component manifests are persisted",
    )

    schema_errors: list[str] = []
    for name in EXPECTED_GOLD_MANIFESTS:
        path = manifest_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("schema_version")) != schema_version:
            schema_errors.append(f"{name}:{payload.get('schema_version')!r}")
    add_validation(
        records,
        check_id="gold_schema_version_consistent",
        category="lineage",
        passed=not schema_errors,
        observed={"expected": schema_version, "errors": schema_errors},
        requirement="all M3 manifests declare the active Gold schema version",
    )

    target_spec = docs_root / "target-specs" / "y_addition_180d.md"
    target_text = target_spec.read_text(encoding="utf-8") if target_spec.exists() else ""
    target_frozen = (
        "FROZEN" in target_text
        and "ADICION EN EL VALOR" in target_text
        and "(t0, t0 + 180" in target_text
    )
    add_validation(
        records,
        check_id="target_spec_frozen",
        category="target",
        passed=target_frozen,
        observed={"path": str(target_spec), "exists": target_spec.exists()},
        requirement="target specification is explicitly frozen for M3 V1 semantics",
    )

    split_spec = docs_root / "decisions" / "M3_TEMPORAL_SPLIT_FREEZE.md"
    add_validation(
        records,
        check_id="temporal_split_decision_frozen",
        category="validation",
        passed=split_spec.exists(),
        observed={"path": str(split_spec), "exists": split_spec.exists()},
        requirement="temporal train/validation/test policy is documented as a frozen decision",
    )

    issues_path = reports_root / "gold" / "m3_issue_register.parquet"
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
        check_id="no_blocking_gold_issues",
        category="quality",
        passed=blocking_issues == 0,
        observed={"blocking_issues": blocking_issues, "warning_issues": warning_issues},
        requirement="M3 issue register exists and contains zero blocking issues",
    )

    report = pd.DataFrame.from_records(records)
    blocking = report.loc[report["blocking"]]
    failed = tuple(blocking.loc[~blocking["passed"], "check_id"].astype(str).tolist())
    passed = int(blocking["passed"].sum())
    total = int(len(blocking))
    decision = M3GateDecision(
        status="CLOSED" if total > 0 and not failed else "OPEN",
        blocking_passed=passed,
        blocking_total=total,
        failed_checks=failed,
    )
    return report, decision


def render_m3_gate_markdown(report: pd.DataFrame, decision: M3GateDecision) -> str:
    icon = "✅" if decision.closed else "❌"
    lines = [
        "# M3 Gate — Gold point-in-time analytical layer",
        "",
        f"**Decision:** M3 {icon} {decision.status}",
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
        lines.append(
            f"| {row['check_id']} | {row['category']} | {status} | {requirement} | {observed} |"
        )
    lines.extend(
        [
            "",
            "## Modeling handoff",
            "",
            "- Modeling consumes `data/gold/ml/argos_v1.parquet`; it does not read Bronze directly.",
            "- The test period is frozen and must not be used for feature design or hyperparameter tuning.",
            "- `y_addition_180d` means a literal `ADICION EN EL VALOR` in `(t0, t0+180d]`.",
            "- Historical and competition features have passed explicit point-in-time audits.",
            "",
        ]
    )
    if decision.failed_checks:
        lines.extend(["## Blocking failures", "", *[f"- `{x}`" for x in decision.failed_checks], ""])
    return "\n".join(lines)


def persist_m3_gate(
    *,
    report: pd.DataFrame,
    decision: M3GateDecision,
    reports_root: Path,
    decision_path: Path,
) -> tuple[Path, Path]:
    report_path = write_report(report, reports_root / "gold" / "m3_gate_report.parquet")
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(render_m3_gate_markdown(report, decision), encoding="utf-8")
    return report_path, decision_path
