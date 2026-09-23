# ARGOS — Post-M6 Operations

> **Lifecycle status:** M1–M6 ✅ CLOSED  
> **Operational status:** `OPERATIONALLY_READY_PROMOTION_BLOCKED`  
> **Mode:** batch + shadow + human-in-the-loop

## Purpose

M6 completes the V1 productionization milestone. The post-M6 operating rules below were later formalized as M7 and must not silently change the frozen model lineage. The objective is to operate ARGOS in shadow/human-review mode, collect prospective evidence and verify that data/model behavior remains observable and governable.

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

## Formal transition to M7

The next milestone was explicitly scoped as `M7 — Prospective Validation & Operational Evaluation`. It collects future evidence under a preregistered protocol. Model V2 retraining, cloud deployment changes or institutional workflow integration remain separate changes and are not implicitly authorized by M6 closure.


---

## M7 — Prospective Validation

The formal next milestone is `M7 — Prospective Validation & Operational Evaluation`. See `docs/M7_RUNBOOK.md`. M6 artifacts remain frozen; M7 collects future evidence rather than rewriting M6.
