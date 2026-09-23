from __future__ import annotations

import tomllib

from argos.common.paths import ProjectPaths
from argos.config.registry import discover_dataset_files, load_registry
from argos.config.silver import load_silver_spec
from argos.evaluation.m1_gate import evaluate_m1_gate
from argos.silver.contracts_processes import build_contracts_processes_silver


def main() -> int:
    paths = ProjectPaths.discover()
    paths.ensure_runtime_dirs()

    datasets, _ = load_registry(paths.configs / "datasets.toml")
    files = discover_dataset_files(paths.bronze, datasets)
    silver_spec = load_silver_spec(paths.configs / "silver.toml")

    with (paths.configs / "project.toml").open("rb") as handle:
        project = tomllib.load(handle)

    _, m1_decision = evaluate_m1_gate(paths.reports, project)
    if not m1_decision.closed:
        raise RuntimeError(
            "M1 is not closed according to the persisted M1 evidence; Silver build aborted."
        )

    result = build_contracts_processes_silver(
        files["contracts"],
        files["processes"],
        contracts_spec=datasets["contracts"],
        processes_spec=datasets["processes"],
        column_profile_path=paths.reports / "profiling" / "column_profile.parquet",
        reports_root=paths.reports,
        silver_dir=paths.silver,
        manifest_dir=paths.root / "artifacts" / "manifests",
        silver_spec=silver_spec,
        date_order=project["temporal"]["date_order"],
        sample_size=project["profiling"]["csv_sample_size"],
        temp_directory=paths.root / ".cache" / "duckdb",
        overwrite=True,
    )

    print(result.validation.to_string(index=False))
    print("Notebook 10 gate:", "PASS" if result.ready_for_next_notebook else "FAIL")
    print("Manifest:", result.manifest_path)
    return 0 if result.ready_for_next_notebook else 1


if __name__ == "__main__":
    raise SystemExit(main())
