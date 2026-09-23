# M6 Production Artifact Catalog

## Config

`configs/production.toml` freezes `m6-production-v1`: batch/shadow operating mode, runtime compatibility, registry paths, data contract, ranking, monitoring thresholds, audit policy and deployment-state policy.

## Registry and contracts

```text
artifacts/registry/argos_v1.json
artifacts/registry/deployment_state.json
artifacts/contracts/argos_v1_scoring_contract.json
artifacts/audit/production_events.jsonl
```

The registry identifies the exact M4 model/calibrator by SHA-256 and hashes the M4/M5 governance documents. The scoring contract contains the frozen model feature list and explicit forbidden output columns.

## Batch outputs

```text
data/production/scored_batches/<batch_id>.parquet
data/production/review_queues/<batch_id>.parquet
```

`batch_id` is an idempotency key derived from input SHA-256, model SHA-256, calibrator SHA-256 and contract SHA-256.

Scoring output grain:

```text
1 row = 1 contract scored at its t0 in one immutable scoring batch
```

Review queue grain:

```text
1 row = 1 top-K contract requiring human review
```

The review queue keeps model fields (`model_score`, `model_raw_score`, `model_rank`) separate from human fields (`review_status`, `review_outcome`, `review_notes`).

## Reports

```text
reports/production/50_validation.parquet
reports/production/51_preflight_profile.parquet
reports/production/51_validation.parquet
reports/production/52_scoring_summary.parquet
reports/production/52_validation.parquet
reports/production/53_feature_drift.parquet
reports/production/53_score_drift.parquet
reports/production/53_alerts.parquet
reports/production/53_validation.parquet
reports/production/54_review_queue_summary.parquet
reports/production/54_validation.parquet
reports/production/55_rollback_drill.parquet
reports/production/55_validation.parquet
reports/production/56_readiness_evidence.parquet
reports/production/56_validation.parquet
reports/production/m6_gate_report.parquet
```

## Gate interpretation

M6 validates operational engineering separately from model promotion. A high-drift replay can therefore produce valid monitoring evidence while leaving `promotion_blocked=true`. This is not a contradiction: detecting and enforcing a stop condition is an operational success.


## Materialized V1 closure evidence

```text
schema                        m6-production-v1
model_version                 argos-v1
batch_id                      a8865bfed9374218183eb302
scored_rows                   529,054
review_rows                   5,291
review_fraction               1%
monitoring_alerts              14
high_alerts                     6
score_psi                1.089164
verified_audit_events          16
human_review_required        true
production_promotion         false
promotion_blocked            true
final_status     OPERATIONALLY_READY_PROMOTION_BLOCKED
```

The operational replay is an engineering replay over an already-consumed evaluation cohort; it is not a new model-performance claim. The high-drift result is retained as governance evidence and intentionally blocks promotion.

## Gate reconciliation artifact

The cached `m6_gate_report.parquet` created before the final component reruns was archived at:

```text
reports/production/history/m6_gate_report_pre_reconciliation.parquet
```

The current closure reconciliation is persisted as:

```text
reports/production/m6_gate_reconciliation.json
docs/decisions/M6_GATE.md
docs/decisions/M6_CLOSURE_REVIEW_2026-09-23.md
```

`57_m6_gate.ipynb` keeps its executable gate logic but its stale cached output was cleared rather than overwritten with synthetic execution output.
