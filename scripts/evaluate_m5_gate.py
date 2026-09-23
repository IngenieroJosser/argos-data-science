from __future__ import annotations

from argos.common.paths import ProjectPaths
from argos.config.robustness import load_robustness_spec
from argos.evaluation.m5_gate import evaluate_m5_gate, persist_m5_gate


def main() -> None:
    paths = ProjectPaths.discover()
    spec = load_robustness_spec(paths.configs / "robustness.toml")
    report, decision = evaluate_m5_gate(
        root=paths.root,
        reports_root=paths.reports,
        manifest_dir=paths.root / "artifacts" / "manifests",
        docs_root=paths.docs,
        schema_version=spec.schema_version,
    )
    report_path, decision_path = persist_m5_gate(
        report=report,
        decision=decision,
        reports_root=paths.reports,
        decision_path=paths.docs / "decisions" / "M5_GATE.md",
    )
    print(f"M5 {'✅ CLOSED' if decision.closed else '❌ OPEN'}")
    print(f"Blocking checks: {decision.blocking_passed}/{decision.blocking_total}")
    print("Gate report:", report_path)
    print("Decision artifact:", decision_path)
    if not decision.closed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
