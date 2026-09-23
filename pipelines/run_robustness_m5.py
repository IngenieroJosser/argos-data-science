from __future__ import annotations

import argparse

from argos.common.paths import ProjectPaths
from argos.config.gold import load_gold_spec
from argos.config.modeling import load_modeling_spec
from argos.config.robustness import load_robustness_spec
from argos.evaluation.m5_gate import evaluate_m5_gate, persist_m5_gate
from argos.robustness.backtesting import build_temporal_backtesting
from argos.robustness.drift import build_drift_monitoring
from argos.robustness.explainability import build_explainability
from argos.robustness.feature_value import build_feature_family_revalidation
from argos.robustness.fresh_oot import build_fresh_oot_2026
from argos.robustness.readiness import build_preproduction_evidence
from argos.robustness.uncertainty import build_uncertainty_and_ranking_stability


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ARGOS M5 robustness pipeline")
    parser.add_argument(
        "--consume-fresh-oot",
        action="store_true",
        help="Explicitly authorize notebook-45-equivalent consumption of the untouched 2026 holdout.",
    )
    args = parser.parse_args()

    paths = ProjectPaths.discover()
    paths.ensure_runtime_dirs()
    (paths.reports / "robustness").mkdir(parents=True, exist_ok=True)
    (paths.root / "data" / "m5").mkdir(parents=True, exist_ok=True)
    m4_gate = paths.docs / "decisions" / "M4_GATE.md"
    if not (m4_gate.exists() and "M4 ✅ CLOSED" in m4_gate.read_text(encoding="utf-8")):
        raise RuntimeError("M4 must be formally closed before M5")

    gold = load_gold_spec(paths.configs / "gold.toml")
    modeling = load_modeling_spec(paths.configs / "modeling.toml")
    m5 = load_robustness_spec(paths.configs / "robustness.toml")
    manifests = paths.root / "artifacts" / "manifests"
    temp = paths.root / ".cache" / "duckdb"

    r40 = build_temporal_backtesting(root=paths.root, gold_spec=gold, modeling_spec=modeling, robustness_spec=m5, reports_root=paths.reports, manifest_dir=manifests, temp_directory=temp)
    assert r40.ready_for_next_notebook
    r41 = build_explainability(root=paths.root, gold_spec=gold, modeling_spec=modeling, robustness_spec=m5, reports_root=paths.reports, manifest_dir=manifests)
    assert r41.ready_for_next_notebook
    r42 = build_uncertainty_and_ranking_stability(reports_root=paths.reports, manifest_dir=manifests, modeling_spec=modeling, robustness_spec=m5)
    assert r42.ready_for_next_notebook
    r43 = build_drift_monitoring(root=paths.root, gold_spec=gold, modeling_spec=modeling, robustness_spec=m5, reports_root=paths.reports, manifest_dir=manifests)
    assert r43.ready_for_next_notebook
    r44 = build_feature_family_revalidation(root=paths.root, gold_spec=gold, modeling_spec=modeling, robustness_spec=m5, reports_root=paths.reports, manifest_dir=manifests)
    assert r44.ready_for_next_notebook

    if not args.consume_fresh_oot:
        print("M5 development evidence 40–44 completed.")
        print("Fresh OOT 2026 was NOT consumed. Re-run with --consume-fresh-oot only after reviewing 40–44.")
        return

    r45 = build_fresh_oot_2026(root=paths.root, gold_spec=gold, modeling_spec=modeling, robustness_spec=m5, reports_root=paths.reports, manifest_dir=manifests, temp_directory=temp)
    assert r45.ready_for_next_notebook
    r46 = build_preproduction_evidence(root=paths.root, reports_root=paths.reports, manifest_dir=manifests, docs_root=paths.docs, modeling_spec=modeling, robustness_spec=m5)
    assert r46.ready_for_next_notebook
    report, decision = evaluate_m5_gate(root=paths.root, reports_root=paths.reports, manifest_dir=manifests, docs_root=paths.docs, schema_version=m5.schema_version)
    persist_m5_gate(report=report, decision=decision, reports_root=paths.reports, decision_path=paths.docs / "decisions" / "M5_GATE.md")
    if not decision.closed:
        raise RuntimeError(f"M5 remains open: {decision.failed_checks}")
    print(f"M5 ✅ CLOSED — {decision.blocking_passed}/{decision.blocking_total}")


if __name__ == "__main__":
    main()
