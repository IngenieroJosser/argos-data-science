from __future__ import annotations

import argparse
from pathlib import Path

from argos.common.paths import ProjectPaths
from argos.config.gold import load_gold_spec
from argos.config.modeling import load_modeling_spec
from argos.config.production import load_production_spec
from argos.evaluation.m6_gate import evaluate_m6_gate
from argos.production.common import read_json, resolve
from argos.production.contracts import build_preflight_evidence
from argos.production.monitoring import build_monitoring_evidence
from argos.production.review import build_review_queue
from argos.production.scoring import score_batch


def _specs(root: Path):
    return (
        load_gold_spec(root / "configs" / "gold.toml"),
        load_modeling_spec(root / "configs" / "modeling.toml"),
        load_production_spec(root / "configs" / "production.toml"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="argos-production", description="ARGOS batch-first production operations")
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight", help="Validate a Parquet scoring batch against the frozen contract")
    preflight.add_argument("input", type=Path)

    score = sub.add_parser("score", help="Score a Parquet batch idempotently with frozen ARGOS V1")
    score.add_argument("input", type=Path)

    monitor = sub.add_parser("monitor", help="Execute feature/score monitoring for a scored batch")
    monitor.add_argument("input", type=Path, help="Original feature batch")
    monitor.add_argument("scored", type=Path, help="Scoring output from ARGOS")

    queue = sub.add_parser("review-queue", help="Materialize the configured top-K human review queue")
    queue.add_argument("scored", type=Path)

    sub.add_parser("status", help="Show current deployment state")
    sub.add_parser("gate", help="Evaluate the persisted M6 gate evidence")

    args = parser.parse_args()
    paths = ProjectPaths.discover()
    paths.ensure_runtime_dirs()
    gold, modeling, production = _specs(paths.root)
    manifests = paths.root / "artifacts" / "manifests"
    temp = paths.root / ".cache" / "duckdb"

    if args.command == "preflight":
        result = build_preflight_evidence(input_path=args.input.resolve(), root=paths.root, gold_spec=gold, modeling_spec=modeling, production_spec=production, reports_root=paths.reports, manifest_dir=manifests, temp_directory=temp)
        print(result.validation.to_string(index=False))
        raise SystemExit(0 if result.ready_for_next_notebook else 2)

    if args.command == "score":
        result = score_batch(input_path=args.input.resolve(), root=paths.root, gold_spec=gold, modeling_spec=modeling, production_spec=production, reports_root=paths.reports, manifest_dir=manifests, temp_directory=temp)
        print(result.summary.to_string(index=False))
        print(f"scored_path={result.scored_path}")
        print(f"reused_existing={result.reused_existing}")
        raise SystemExit(0 if result.ready_for_next_notebook else 2)

    if args.command == "monitor":
        result = build_monitoring_evidence(input_path=args.input.resolve(), scored_path=args.scored.resolve(), root=paths.root, gold_spec=gold, modeling_spec=modeling, production_spec=production, reports_root=paths.reports, manifest_dir=manifests)
        print(result.alerts.to_string(index=False) if not result.alerts.empty else "No warning/high alerts")
        raise SystemExit(0 if result.ready_for_next_notebook else 2)

    if args.command == "review-queue":
        result = build_review_queue(scored_path=args.scored.resolve(), root=paths.root, production_spec=production, reports_root=paths.reports, manifest_dir=manifests, temp_directory=temp)
        print(result.queue_summary.to_string(index=False))
        print(f"queue_path={result.queue_path}")
        raise SystemExit(0 if result.ready_for_next_notebook else 2)

    if args.command == "status":
        state = read_json(resolve(paths.root, production.deployment.state_path))
        print(state)
        return

    decision = evaluate_m6_gate(root=paths.root, production_spec=production, reports_root=paths.reports, manifest_dir=manifests, docs_root=paths.docs)
    print(decision.report.to_string(index=False))
    print(f"M6 {'CLOSED' if decision.closed else 'OPEN'} — {decision.deployment_status}")
    raise SystemExit(0 if decision.closed else 2)


if __name__ == "__main__":
    main()
