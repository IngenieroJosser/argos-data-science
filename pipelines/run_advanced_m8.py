from __future__ import annotations

import argparse
from pathlib import Path

from argos.advanced.ablation import run_m8_ablation
from argos.advanced.m8 import build_m8_development_matrix, build_m8_pit_audit
from argos.anomaly.contextual import build_anomaly_features
from argos.common.paths import ProjectPaths
from argos.config.advanced import load_advanced_spec
from argos.config.gold import load_gold_spec
from argos.config.modeling import load_modeling_spec
from argos.config.production import load_production_spec
from argos.config.prospective import load_prospective_spec
from argos.evaluation.m8_gate import evaluate_m8_gate
from argos.graph.temporal import build_graph_features
from argos.nlp.semantic import build_semantic_features
from argos.prospective.protocol import verify_frozen_protocol
from argos.survival.analysis import build_survival_analysis, build_survival_outcomes


def require_stage(result, stage: str, attribute: str) -> None:
    if not bool(getattr(result, attribute)):
        raise RuntimeError(f"M8 stage {stage} failed blocking validation")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run ARGOS M8 backend: semantic NLP, temporal graph intelligence, contextual anomaly "
            "detection, PIT audit, TRAIN/VALIDATION-only temporal ablation and survival analysis."
        )
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--start-stage",
        type=int,
        choices=range(70, 78),
        default=70,
        metavar="70-77",
        help=(
            "Resume M8 at a specific stage. Earlier stages are not recomputed; "
            "their persisted artifacts must already exist."
        ),
    )
    args = parser.parse_args()

    paths = ProjectPaths.discover(args.root)
    paths.ensure_runtime_dirs()
    (paths.reports / "advanced").mkdir(parents=True, exist_ok=True)
    (paths.root / "artifacts" / "models" / "m8").mkdir(parents=True, exist_ok=True)
    (paths.root / ".cache" / "m8").mkdir(parents=True, exist_ok=True)

    advanced = load_advanced_spec(paths.configs / "advanced.toml")
    gold = load_gold_spec(paths.configs / "gold.toml")
    modeling = load_modeling_spec(paths.configs / "modeling.toml")
    production = load_production_spec(paths.configs / "production.toml")
    prospective = load_prospective_spec(paths.configs / "prospective.toml")
    manifests = paths.root / "artifacts" / "manifests"

    m6_gate = paths.docs / "decisions" / "M6_GATE.md"
    if advanced.governance.require_m6_closed and not (
        m6_gate.exists() and "M6 ✅ CLOSED" in m6_gate.read_text(encoding="utf-8")
    ):
        raise RuntimeError("M8 requires formally closed M6")
    if advanced.governance.require_m7_protocol_frozen:
        ok, details = verify_frozen_protocol(
            root=paths.root,
            prospective_spec=prospective,
            production_spec=production,
            docs_root=paths.docs,
        )
        if not ok:
            raise RuntimeError(f"Frozen M7 protocol integrity failed before M8: {details}")

    start_stage = args.start_stage

    if start_stage <= 70:
        print("[M8] 70 semantic intelligence")
        r70 = build_semantic_features(
            root=paths.root,
            silver_dir=paths.silver,
            gold_dir=paths.gold,
            reports_root=paths.reports,
            manifest_dir=manifests,
            gold_spec=gold,
            advanced_spec=advanced,
        )
        require_stage(r70, "70", "ready_for_next_stage")
    else:
        required = [
            paths.root / advanced.artifacts.semantic_features,
            paths.root / advanced.artifacts.semantic_manifest,
        ]
        missing = [str(p.relative_to(paths.root)) for p in required if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"Cannot resume after stage 70; missing persisted artifacts: {missing}"
            )
        print("[M8] 70 semantic intelligence — reused persisted artifacts")

    if start_stage <= 71:
        print("[M8] 71 temporal graph intelligence")
        r71 = build_graph_features(
            root=paths.root,
            silver_dir=paths.silver,
            gold_dir=paths.gold,
            reports_root=paths.reports,
            manifest_dir=manifests,
            gold_spec=gold,
            advanced_spec=advanced,
        )
        require_stage(r71, "71", "ready_for_next_stage")
    else:
        required = [
            paths.root / advanced.artifacts.graph_features,
            paths.root / advanced.artifacts.graph_manifest,
        ]
        missing = [str(p.relative_to(paths.root)) for p in required if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"Cannot resume after stage 71; missing persisted artifacts: {missing}"
            )
        print("[M8] 71 temporal graph intelligence — reused persisted artifacts")

    if start_stage <= 72:
        print("[M8] 72 contextual anomaly detection")
        r72 = build_anomaly_features(
            root=paths.root,
            reports_root=paths.reports,
            manifest_dir=manifests,
            gold_spec=gold,
            modeling_spec=modeling,
            advanced_spec=advanced,
        )
        require_stage(r72, "72", "ready_for_next_stage")

    if start_stage <= 73:
        print("[M8] 73 development matrix + PIT audit")
        matrix = build_m8_development_matrix(
            root=paths.root,
            reports_root=paths.reports,
            gold_spec=gold,
            modeling_spec=modeling,
            advanced_spec=advanced,
        )
        require_stage(matrix, "73-matrix", "ready_for_pit_audit")
        pit = build_m8_pit_audit(
            root=paths.root,
            reports_root=paths.reports,
            manifest_dir=manifests,
            modeling_spec=modeling,
            advanced_spec=advanced,
            prospective_spec=prospective,
            production_spec=production,
            docs_root=paths.docs,
        )
        require_stage(pit, "73-pit", "ready_for_ablation")

    if start_stage <= 74:
        print("[M8] 74 temporal ablation + feature-family decision")
        ablation = run_m8_ablation(
            root=paths.root,
            reports_root=paths.reports,
            manifest_dir=manifests,
            gold_spec=gold,
            modeling_spec=modeling,
            advanced_spec=advanced,
        )
        require_stage(ablation, "74", "ready_for_gate")

    if start_stage <= 75:
        print("[M8] 75 survival outcomes + administrative censoring")
        survival_outcomes = build_survival_outcomes(
            root=paths.root,
            reports_root=paths.reports,
            manifest_dir=manifests,
            gold_spec=gold,
            modeling_spec=modeling,
            advanced_spec=advanced,
        )
        require_stage(survival_outcomes, "75", "ready_for_analysis")

    if start_stage <= 76:
        print("[M8] 76 survival analysis")
        survival = build_survival_analysis(
            root=paths.root,
            reports_root=paths.reports,
            manifest_dir=manifests,
            gold_spec=gold,
            modeling_spec=modeling,
            advanced_spec=advanced,
        )
        require_stage(survival, "76", "ready_for_gate")

    if start_stage <= 77:
        print("[M8] 77 formal gate")
        gate = evaluate_m8_gate(
            root=paths.root,
            advanced_spec=advanced,
            prospective_spec=prospective,
            production_spec=production,
            reports_root=paths.reports,
            manifest_dir=manifests,
            docs_root=paths.docs,
        )
        if not gate.closed:
            failed = gate.report.loc[
                gate.report["blocking"] & ~gate.report["passed"], "check_id"
            ].tolist()
            raise RuntimeError(f"M8 remains open: {failed}")
        print(f"M8 ✅ CLOSED — {gate.decision}")
        print(f"Selected family: {gate.selected_family or 'none'}")
        print(f"Decision artifact: {gate.decision_artifact}")


if __name__ == "__main__":
    main()
