from __future__ import annotations

import argparse
from pathlib import Path

from argos.common.paths import ProjectPaths
from argos.config.gold import load_gold_spec
from argos.evaluation.m3_gate import evaluate_m3_gate, persist_m3_gate
from argos.gold.competition_features import build_competition_features
from argos.gold.contract_features import build_contract_features
from argos.gold.historical_features import build_historical_features
from argos.gold.pit_audit import build_pit_audit
from argos.gold.splits import build_temporal_splits
from argos.gold.target import build_target_gold
from argos.gold.train_eda import build_train_eda


def _require(result, stage: str, attribute: str = "ready_for_next_notebook") -> None:
    ok = bool(getattr(result, attribute))
    if not ok:
        raise RuntimeError(f"M3 stage {stage} failed blocking validation")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and validate ARGOS M3 Gold layer")
    parser.add_argument("--root", type=Path, default=None, help="Project root; auto-discovered by default")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Gold parquet artifacts")
    args = parser.parse_args()

    paths = ProjectPaths.discover(args.root)
    paths.ensure_runtime_dirs()
    m2_gate = paths.docs / "decisions" / "M2_GATE.md"
    if not m2_gate.exists() or "M2 ✅ CLOSED" not in m2_gate.read_text(encoding="utf-8"):
        raise RuntimeError("M2 is not formally closed")

    spec = load_gold_spec(paths.configs / "gold.toml")
    manifests = paths.root / "artifacts" / "manifests"
    temp = paths.root / ".cache" / "duckdb"

    print("[M3] 20 target engineering")
    r20 = build_target_gold(
        silver_dir=paths.silver,
        gold_dir=paths.gold,
        reports_root=paths.reports,
        manifest_dir=manifests,
        gold_spec=spec,
        temp_directory=temp,
        overwrite=args.overwrite,
    )
    _require(r20, "20")

    print("[M3] 21 temporal split")
    r21 = build_temporal_splits(
        gold_dir=paths.gold,
        reports_root=paths.reports,
        manifest_dir=manifests,
        gold_spec=spec,
        temp_directory=temp,
        overwrite=args.overwrite,
    )
    _require(r21, "21")

    print("[M3] 22 train-only EDA")
    r22 = build_train_eda(
        silver_dir=paths.silver,
        gold_dir=paths.gold,
        reports_root=paths.reports,
        manifest_dir=manifests,
        gold_spec=spec,
        temp_directory=temp,
    )
    _require(r22, "22")

    print("[M3] 23 contract features")
    r23 = build_contract_features(
        silver_dir=paths.silver,
        gold_dir=paths.gold,
        reports_root=paths.reports,
        manifest_dir=manifests,
        gold_spec=spec,
        temp_directory=temp,
        overwrite=args.overwrite,
    )
    _require(r23, "23")

    print("[M3] 24 historical features")
    r24 = build_historical_features(
        silver_dir=paths.silver,
        gold_dir=paths.gold,
        reports_root=paths.reports,
        manifest_dir=manifests,
        gold_spec=spec,
        temp_directory=temp,
        overwrite=args.overwrite,
    )
    _require(r24, "24")

    print("[M3] 25 competition features")
    r25 = build_competition_features(
        silver_dir=paths.silver,
        gold_dir=paths.gold,
        reports_root=paths.reports,
        manifest_dir=manifests,
        gold_spec=spec,
        temp_directory=temp,
        overwrite=args.overwrite,
    )
    _require(r25, "25")

    print("[M3] 26 PIT audit / model matrix")
    r26 = build_pit_audit(
        gold_dir=paths.gold,
        reports_root=paths.reports,
        manifest_dir=manifests,
        gold_spec=spec,
        temp_directory=temp,
        overwrite=args.overwrite,
    )
    _require(r26, "26", "ready_for_gate")

    print("[M3] 27 gate")
    report, decision = evaluate_m3_gate(
        reports_root=paths.reports,
        gold_dir=paths.gold,
        manifest_dir=manifests,
        docs_root=paths.docs,
        schema_version=spec.schema_version,
    )
    persist_m3_gate(
        report=report,
        decision=decision,
        reports_root=paths.reports,
        decision_path=paths.docs / "decisions" / "M3_GATE.md",
    )
    print("M3 ✅ CLOSED" if decision.closed else "M3 ❌ OPEN")
    print(f"Blocking checks: {decision.blocking_passed}/{decision.blocking_total}")
    if not decision.closed:
        raise RuntimeError(f"M3 gate failed: {decision.failed_checks}")


if __name__ == "__main__":
    main()
