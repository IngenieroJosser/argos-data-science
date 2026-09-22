from __future__ import annotations

import tomllib

from argos.common.paths import ProjectPaths
from argos.common.reports import write_report
from argos.evaluation.m1_gate import evaluate_m1_gate, render_m1_gate_markdown


def main() -> int:
    paths = ProjectPaths.discover()
    with (paths.configs / "project.toml").open("rb") as handle:
        config = tomllib.load(handle)

    report, decision = evaluate_m1_gate(paths.reports, config)
    write_report(report, paths.reports / "profiling" / "m1_gate_report.parquet")

    decision_path = paths.docs / "decisions" / "M1_GATE.md"
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(
        render_m1_gate_markdown(report, decision),
        encoding="utf-8",
    )

    print("M1 ✅ CLOSED" if decision.closed else "M1 ❌ OPEN")
    print(f"Blocking checks: {decision.passed}/{decision.total}")
    if decision.failed_checks:
        print("Failed:", ", ".join(decision.failed_checks))
    print("Decision:", decision_path)
    return 0 if decision.closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
