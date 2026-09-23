# ARGOS — Post-M6 Operations

> **Lifecycle status:** M1–M6 ✅ CLOSED  
> **Operational status:** `OPERATIONALLY_READY_PROMOTION_BLOCKED`  
> **Mode:** batch + shadow + human-in-the-loop

## Purpose

M6 completes the V1 engineering roadmap. Post-M6 work is not an implicit M7 and must not silently change the frozen model lineage. The immediate objective is to operate ARGOS in shadow/human-review mode, collect prospective evidence and verify that data/model behavior remains observable and governable.

## Required operating rules

1. Preserve `promotion_blocked=true` while high-severity monitoring conditions remain unresolved.
2. Do not promote by manually editing `deployment_state.json` or registry artifacts.
3. Keep scoring outputs and human-review outcomes logically separate.
4. Maintain the SHA-256 audit chain and immutable batch lineage.
5. Treat TEST 2025 and OOT 2026 as consumed for ARGOS V1.
6. Any retraining, recalibration, feature change or model-family change creates a new versioned lineage.
7. Any new performance claim requires genuinely prospective or otherwise predeclared evaluation data.
8. Continue monitoring feature drift, score drift, missingness and operational queue behavior.

## Current blocker

The M6 replay persisted 14 alerts, including 6 `high`; score PSI is 1.089164. This is sufficient to keep deployment promotion blocked under the frozen M6 policy.

## What would justify a new milestone

A future milestone should be explicitly scoped before implementation. Examples include prospective shadow validation over new months, model V2 retraining with new holdout governance, cloud deployment/managed orchestration, or institutional workflow integration. None is implicitly authorized by M6 closure.
