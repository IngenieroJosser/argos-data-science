from __future__ import annotations

import argparse

from argos.common.paths import ProjectPaths
from argos.config.gold import load_gold_spec
from argos.config.modeling import load_modeling_spec
from argos.models.ablation import build_ablation_study
from argos.models.baselines import build_baselines
from argos.models.boosting import train_boosting_model
from argos.models.business import evaluate_final_test
from argos.models.calibration import build_calibration_and_selection
from argos.models.error_analysis import build_error_analysis
from argos.models.linear import train_linear_model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ARGOS M4 components. TEST is excluded unless --include-final-test is explicit."
    )
    parser.add_argument(
        "--include-final-test",
        action="store_true",
        help="Run notebook-36 equivalent after model selection is frozen. This is the only TEST-consuming stage.",
    )
    args = parser.parse_args()

    paths = ProjectPaths.discover()
    paths.ensure_runtime_dirs()
    gold = load_gold_spec(paths.configs / "gold.toml")
    spec = load_modeling_spec(paths.configs / "modeling.toml")
    model_dir = paths.root / "artifacts" / "models" / "m4"
    manifest_dir = paths.root / "artifacts" / "manifests"

    build_baselines(root=paths.root, gold_spec=gold, modeling_spec=spec, reports_root=paths.reports, manifest_dir=manifest_dir)
    train_linear_model(root=paths.root, gold_spec=gold, modeling_spec=spec, reports_root=paths.reports, model_dir=model_dir, manifest_dir=manifest_dir)
    train_boosting_model(root=paths.root, gold_spec=gold, modeling_spec=spec, reports_root=paths.reports, model_dir=model_dir, manifest_dir=manifest_dir)
    build_calibration_and_selection(reports_root=paths.reports, model_dir=model_dir, manifest_dir=manifest_dir, modeling_spec=spec)
    build_error_analysis(root=paths.root, modeling_spec=spec, reports_root=paths.reports, manifest_dir=manifest_dir)
    build_ablation_study(root=paths.root, gold_spec=gold, modeling_spec=spec, reports_root=paths.reports, manifest_dir=manifest_dir)

    if args.include_final_test:
        evaluate_final_test(root=paths.root, gold_spec=gold, modeling_spec=spec, reports_root=paths.reports, model_dir=model_dir, manifest_dir=manifest_dir, docs_root=paths.docs)
    else:
        print("M4 pre-TEST stages complete. TEST remains sealed. Run notebook 36 only after reviewing 30–35.")


if __name__ == "__main__":
    main()
