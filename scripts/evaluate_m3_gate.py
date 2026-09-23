from __future__ import annotations

from argos.common.paths import ProjectPaths
from argos.config.gold import load_gold_spec
from argos.evaluation.m3_gate import evaluate_m3_gate, persist_m3_gate


def main() -> None:
    paths = ProjectPaths.discover()
    paths.ensure_runtime_dirs()
    spec = load_gold_spec(paths.configs / "gold.toml")
    report, decision = evaluate_m3_gate(
        reports_root=paths.reports,
        gold_dir=paths.gold,
        manifest_dir=paths.root / "artifacts" / "manifests",
        docs_root=paths.docs,
        schema_version=spec.schema_version,
    )
    report_path, decision_path = persist_m3_gate(
        report=report,
        decision=decision,
        reports_root=paths.reports,
        decision_path=paths.docs / "decisions" / "M3_GATE.md",
    )
    print("M3 ✅ CLOSED" if decision.closed else "M3 ❌ OPEN")
    print(f"Blocking checks: {decision.blocking_passed}/{decision.blocking_total}")
    print("Gate report:", report_path)
    print("Decision artifact:", decision_path)
    if not decision.closed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
