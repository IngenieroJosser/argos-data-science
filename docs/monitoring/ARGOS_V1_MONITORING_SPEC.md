# ARGOS V1 — Monitoring Specification

> **M5 schema:** `m5-robustness-v1`  
> **Purpose:** operational monitoring contract; it does not authorize autonomous decisions.

## Deterministic ranking

```text
calibrated score DESC
raw model score DESC
contract_id ASC
```

This order must be used whenever top-K metrics or review queues are materialized.

## Frozen monitoring thresholds

| signal | warning | high | action |
|---|---:|---:|---|
| numeric_feature_psi | 0.1000 | 0.2500 | investigate feature distribution / upstream data changes |
| categorical_feature_tvd | 0.1000 | 0.2500 | investigate category mix and unseen values |
| score_psi | 0.1000 | 0.2500 | review score shift and calibration |
| prevalence_relative_change | 0.3000 | — | review prior probability shift; recalibration may be required |
| tail_calibration_abs_gap | 0.0300 | — | review top-score calibration before operational use |
| lift_at_operational_k | 1.0000 | — | pause promotion if lift is at/below random review |
| feature_missingness_absolute_delta | 0.0500 | — | investigate ingestion/schema/source changes |

## Required recurring checks before production

- schema and lineage integrity;
- target prevalence and label latency;
- feature missingness, category novelty and drift;
- raw/calibrated score distribution drift;
- global and top-tail calibration;
- PR-AUC and Lift@K once labels mature;
- deterministic ranking tie-break;
- runtime/model hash compatibility.

## Governance

TEST 2025 remains a consumed historical benchmark. The 2026 fresh OOT cohort becomes consumed after notebook 45. Any future model selection requires development windows that exclude both final-evaluation cohorts, and any new generalization claim requires a later untouched holdout.
