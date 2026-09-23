# ARGOS V1 — Operational Runbook

> **M6 status:** ✅ CLOSED  
> **Deployment status:** `OPERATIONALLY_READY_PROMOTION_BLOCKED`  
> **Promotion:** blocked by 6 high-severity monitoring alerts

## Operating mode
Batch-first, shadow deployment, human review required. ARGOS produces analytical priority queues; it does not issue sanctions, fraud/corruption findings, eligibility decisions or legal conclusions.

## Standard batch flow
1. Freeze incoming scoring batch and compute SHA-256.
2. Execute data-contract preflight.
3. Score with the registered frozen model/calibrator.
4. Persist deterministic ranking and batch manifest.
5. Run drift/missingness/score monitoring.
6. Materialize only the configured top-K review queue.
7. Route the queue to human analysts.
8. Persist audit evidence for every operational transition.

## Stop conditions
- schema or grain contract failure;
- model/calibrator/contract hash mismatch;
- non-finite scores;
- high-severity monitoring alert when pause policy is enabled;
- broken audit hash chain;
- missing human-review workflow.

## Recovery
Do not mutate a failed batch in place. Correct the upstream issue, materialize a new immutable input batch, rerun preflight, and produce a new batch id.
