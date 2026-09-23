from __future__ import annotations

from argos.common.paths import ProjectPaths
from argos.config.prospective import load_prospective_spec
from argos.evaluation.m7_gate import evaluate_m7_gate


def main() -> None:
    paths = ProjectPaths.discover()
    spec = load_prospective_spec(paths.configs / "prospective.toml")
    decision = evaluate_m7_gate(root=paths.root, spec=spec, reports_root=paths.reports, docs_root=paths.docs)
    print(decision.report.to_string(index=False))
    print(f"M7 {'✅ CLOSED' if decision.closed else '⏳ OPEN'} — {decision.decision}")
    print(f"Decision artifact: {decision.decision_artifact}")
    raise SystemExit(0 if decision.closed else 2)


if __name__ == "__main__":
    main()
