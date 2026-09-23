from __future__ import annotations

import argparse
from pathlib import Path

from argos.common.paths import ProjectPaths
from argos.config.gold import load_gold_spec
from argos.config.modeling import load_modeling_spec
from argos.config.production import load_production_spec
from argos.evaluation.m6_gate import evaluate_m6_gate
from argos.production.contracts import build_preflight_evidence
from argos.production.deployment import run_shadow_rollback_drill
from argos.production.monitoring import build_monitoring_evidence
from argos.production.readiness import build_operational_readiness
from argos.production.registry import build_model_registry
from argos.production.review import build_review_queue
from argos.production.scoring import score_batch


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ARGOS M6 batch-first productionization evidence in shadow/human-review mode."
    )
    parser.add_argument(
        "--shadow-input",
        type=Path,
        default=Path("data/m5/fresh_oot_2026.parquet"),
        help="Immutable Parquet batch used as an operational replay. Labels, if present, are ignored by scoring.",
    )
    args = parser.parse_args()

    paths = ProjectPaths.discover()
    paths.ensure_runtime_dirs()
    m5_gate = paths.docs / "decisions" / "M5_GATE.md"
    if not (m5_gate.exists() and "M5 ✅ CLOSED" in m5_gate.read_text(encoding="utf-8")):
        raise RuntimeError("M5 must be formally closed before M6")

    gold = load_gold_spec(paths.configs / "gold.toml")
    modeling = load_modeling_spec(paths.configs / "modeling.toml")
    production = load_production_spec(paths.configs / "production.toml")
    manifests = paths.root / "artifacts" / "manifests"
    temp = paths.root / ".cache" / "duckdb"
    input_path = args.shadow_input if args.shadow_input.is_absolute() else paths.root / args.shadow_input
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    r50 = build_model_registry(root=paths.root, production_spec=production, reports_root=paths.reports, manifest_dir=manifests)
    assert r50.ready_for_next_notebook
    r51 = build_preflight_evidence(input_path=input_path, root=paths.root, gold_spec=gold, modeling_spec=modeling, production_spec=production, reports_root=paths.reports, manifest_dir=manifests, temp_directory=temp)
    assert r51.ready_for_next_notebook
    r52 = score_batch(input_path=input_path, root=paths.root, gold_spec=gold, modeling_spec=modeling, production_spec=production, reports_root=paths.reports, manifest_dir=manifests, temp_directory=temp)
    assert r52.ready_for_next_notebook
    r53 = build_monitoring_evidence(input_path=input_path, scored_path=r52.scored_path, root=paths.root, gold_spec=gold, modeling_spec=modeling, production_spec=production, reports_root=paths.reports, manifest_dir=manifests)
    assert r53.ready_for_next_notebook
    r54 = build_review_queue(scored_path=r52.scored_path, root=paths.root, production_spec=production, reports_root=paths.reports, manifest_dir=manifests, temp_directory=temp)
    assert r54.ready_for_next_notebook
    r55 = run_shadow_rollback_drill(root=paths.root, production_spec=production, reports_root=paths.reports, manifest_dir=manifests)
    assert r55.ready_for_next_notebook
    r56 = build_operational_readiness(root=paths.root, production_spec=production, reports_root=paths.reports, manifest_dir=manifests)
    assert r56.ready_for_next_notebook
    decision = evaluate_m6_gate(root=paths.root, production_spec=production, reports_root=paths.reports, manifest_dir=manifests, docs_root=paths.docs)
    if not decision.closed:
        failed = decision.report.loc[decision.report["blocking"] & ~decision.report["passed"], "check_id"].tolist()
        raise RuntimeError(f"M6 remains open: {failed}")
    print(f"M6 ✅ CLOSED — {decision.deployment_status}")
    print(f"Decision artifact: {decision.decision_artifact}")


if __name__ == "__main__":
    main()
