# M5 Code Readiness — 2026-09-23

This document records **code readiness**, not empirical M5 closure.

The repository contains:

```text
configs/robustness.toml
40_temporal_backtesting.ipynb
41_explainability.ipynb
42_uncertainty_and_ranking_stability.ipynb
43_drift_and_calibration_monitoring.ipynb
44_feature_family_revalidation.ipynb
45_fresh_oot_2026.ipynb
46_preproduction_readiness.ipynb
47_m5_gate.ipynb
src/argos/robustness/*
src/argos/evaluation/m5_gate.py
pipelines/run_robustness_m5.py
scripts/evaluate_m5_gate.py
```

The design deliberately preserves M4 artifacts and prevents TEST 2025 from becoming a development selection set again. The pipeline requires an explicit `--consume-fresh-oot` flag before 2026 OOT evaluation.

M5 remains **IN PROGRESS** until the real project data executes notebooks 40–47 and the gate closes.
