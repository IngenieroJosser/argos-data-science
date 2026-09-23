# M4 Code Readiness — 2026-09-23

**Status:** code-ready, empirically unvalidated until notebooks 30–37 execute on the local Gold artifacts.

## Scope reviewed

- `configs/modeling.toml`
- notebooks `30`–`37`
- `src/argos/models/*`
- `src/argos/evaluation/m4_gate.py`
- `pipelines/run_modeling_m4.py`
- M4 unit tests and documentation

## Engineering controls

- streaming logistic training over TRAIN;
- bounded deterministic sample for boosting;
- batch prediction for validation/test;
- explicit validation calibration-fit / selection split;
- no TEST consumption in 30–35;
- model/calibrator hash freeze before 36;
- final TEST artifacts are immutable-by-default and reused after successful materialization;
- M4 gate is computed from persisted component validations and lineage.

## Validation performed before handoff

- Python syntax compilation for source, scripts and pipeline;
- code-cell compilation for notebooks 30–37;
- notebook JSON validation;
- unit tests for the M4 config contract, ranking metric behavior and notebook-level TEST isolation.

## Limitation

The packaging environment does not contain the user's multi-million-row `data/gold/ml/argos_v1.parquet`, so model training, memory behavior, runtime and empirical metric values are not claimed as validated here. Notebook 30 is the first integration check on the user's machine.
