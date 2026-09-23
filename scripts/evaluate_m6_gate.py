from __future__ import annotations

from argos.common.paths import ProjectPaths
from argos.config.production import load_production_spec
from argos.evaluation.m6_gate import evaluate_m6_gate


def main() -> None:
    paths = ProjectPaths.discover()
    spec = load_production_spec(paths.configs / "production.toml")
    decision = evaluate_m6_gate(
        root=paths.root,
        production_spec=spec,
        reports_root=paths.reports,
        manifest_dir=paths.root / "artifacts" / "manifests",
        docs_root=paths.docs,
    )
    print(decision.report.to_string(index=False))
    print(f"M6 {'✅ CLOSED' if decision.closed else '❌ OPEN'} — {decision.deployment_status}")
    print(f"Decision artifact: {decision.decision_artifact}")
    raise SystemExit(0 if decision.closed else 2)


if __name__ == "__main__":
    main()
