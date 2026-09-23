# M5 Robustness Artifact Catalog

> **Schema:** `m5-robustness-v1`  
> **State:** expected artifacts while M5 is IN PROGRESS.

M5 does not replace M3 Gold or M4 model artifacts. It adds evidence around the frozen V1 benchmark.

| component | principal artifacts | grain / role |
|---|---|---|
| 40 Temporal backtesting | `40_backtest_metrics.parquet`, `40_backtest_ranking.parquet`, `40_backtest_folds.parquet` | one metric/ranking record per rolling fold/model/capacity |
| 41 Explainability | `41_global_permutation_importance.parquet`, `41_family_importance.parquet`, `41_local_sensitivity.parquet` | feature-level global sensitivity and contract-feature local sensitivity |
| 42 Uncertainty/ranking | `42_bootstrap_distribution.parquet`, `42_uncertainty_intervals.parquet`, `42_tie_sensitivity.parquet` | bootstrap replicate / metric CI / capacity-level tie sensitivity |
| 43 Drift/calibration | `43_feature_drift.parquet`, `43_score_drift.parquet`, `43_tail_calibration.parquet` | feature-period drift and score-tail reliability |
| 44 Feature value | `44_feature_family_metrics.parquet`, `44_feature_family_deltas.parquet` | family × rolling fold comparison |
| 45 Fresh OOT | `data/m5/fresh_oot_2026.parquet`, `45_fresh_oot_predictions.parquet`, metrics/ranking/reliability | one fully observed 2026 contract per row |
| 46 Readiness evidence | `46_monitoring_thresholds.parquet`, `46_evidence_summary.parquet` | governance/monitoring evidence |
| 47 Gate | `m5_gate_report.parquet`, `docs/decisions/M5_GATE.md` | formal milestone decision |

Every component also persists a `*_validation.parquet` report and a manifest under `artifacts/manifests/`.

## Holdout semantics

`data/m5/fresh_oot_2026.parquet` is not a new training matrix. It is a final evaluation cohort for the frozen V1 model. It must not be merged back into training/selection during M5.
