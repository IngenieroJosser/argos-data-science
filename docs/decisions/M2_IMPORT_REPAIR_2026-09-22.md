# M2 import repair — 2026-09-22

## Symptom

The project raised `ModuleNotFoundError: No module named 'argos.common'` and Pylance could not resolve modules such as `argos.common.paths`, `argos.config.registry`, `argos.evaluation.m1_gate`, and `argos.silver.contracts_processes`.

## Root cause

The M2 11–15 patch was applied as a replacement rather than as an overlay. The resulting project retained the new M2 modules but removed pre-existing package modules and configuration files required by M1 and notebook 10. In particular, the uploaded project contained only a subset of `src/argos` and only `configs/silver.toml`.

## Repair

Restored the previously validated project foundation from the last working M2 notebook-10 build, while preserving the newer M2 11–15 files and the user's current reports/manifests.

Restored at minimum:

- `src/argos/__init__.py`
- `src/argos/common/*`
- `src/argos/config/registry.py` and package init
- `src/argos/evaluation/m1_gate.py` and package init
- `src/argos/profiling/*`
- `src/argos/quality/*`
- `src/argos/targets/*`
- `src/argos/silver/contracts_processes.py` and package init
- `configs/project.toml`
- `configs/datasets.toml`
- M1 decision artifacts and prior unit tests

The newer M2 files (`suppliers_bidders`, `events`, `entity_resolution`, `validation`, `m2_gate`, and updated `silver.toml`) are preserved.
