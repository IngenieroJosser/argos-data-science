from __future__ import annotations

import argparse
from pathlib import Path

from argos.common.paths import ProjectPaths
from argos.config.gold import load_gold_spec
from argos.config.modeling import load_modeling_spec
from argos.config.production import load_production_spec
from argos.production.contracts import build_preflight_evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    paths = ProjectPaths.discover()
    paths.ensure_runtime_dirs()
    result = build_preflight_evidence(
        input_path=args.input.resolve(),
        root=paths.root,
        gold_spec=load_gold_spec(paths.configs / "gold.toml"),
        modeling_spec=load_modeling_spec(paths.configs / "modeling.toml"),
        production_spec=load_production_spec(paths.configs / "production.toml"),
        reports_root=paths.reports,
        manifest_dir=paths.root / "artifacts" / "manifests",
        temp_directory=paths.root / ".cache" / "duckdb",
    )
    print(result.validation.to_string(index=False))
    raise SystemExit(0 if result.ready_for_next_notebook else 2)


if __name__ == "__main__":
    main()
