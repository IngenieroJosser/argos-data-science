from __future__ import annotations

from argos.common.paths import ProjectPaths
from argos.config.modeling import load_modeling_spec
from argos.evaluation.m4_gate import evaluate_m4_gate, persist_m4_gate


def main() -> None:
    paths = ProjectPaths.discover()
    paths.ensure_runtime_dirs()
    spec = load_modeling_spec(paths.configs / "modeling.toml")
    report, decision = evaluate_m4_gate(
        root=paths.root,
        reports_root=paths.reports,
        model_dir=paths.root / "artifacts" / "models" / "m4",
        manifest_dir=paths.root / "artifacts" / "manifests",
        docs_root=paths.docs,
        schema_version=spec.schema_version,
    )
    report_path, decision_path = persist_m4_gate(
        report=report,
        decision=decision,
        reports_root=paths.reports,
        decision_path=paths.docs / "decisions" / "M4_GATE.md",
    )
    print(f"M4 {'✅ CLOSED' if decision.closed else '❌ OPEN'}")
    print(f"Blocking checks: {decision.blocking_passed}/{decision.blocking_total}")
    print("Gate report:", report_path)
    print("Decision artifact:", decision_path)


if __name__ == "__main__":
    main()
