# ARGOS — M7 Runbook

## Prospective Validation & Operational Evaluation

**Schema:** `m7-prospective-v2`  
**Prerequisite:** M6 formally closed  
**Mode:** shadow + human review  
**Protocol freeze:** 2026-09-23  
**First eligible prospective t0:** 2026-09-24

## Objective

M7 answers a question that M4–M6 cannot answer retrospectively:

> Does the frozen ARGOS V1 system retain useful, calibrated and operationally manageable signal on contracts that occur only after the prospective protocol has been frozen?

M7 does not retrain V1, does not reopen TEST 2025 or OOT 2026, and does not authorize autonomous legal or enforcement decisions.

## Sequence

| Notebook | Purpose | Earliest execution |
|---|---|---|
| 60 | freeze protocol, hashes and governance | now |
| 61 | register genuinely future shadow batches | after post-2026-09-23 batches exist |
| 62 | mature 180-day outcomes and lock labels | after complete follow-up + reporting-lag buffer |
| 63 | evaluate frozen V1 prospectively | after 62 |
| 64 | evaluate human-review operations | after real prospective review activity |
| 65 | longitudinal monitoring and incidents | after multiple prospective batches |
| 66 | record human-approved operational decision | after 61–65 |
| 67 | final M7 gate | last |

## Non-negotiable temporal boundary

- TEST 2025 is consumed.
- OOT 2026 used in M5 is consumed.
- Neither can be reused for M7 selection, tuning or re-authorization.
- M7 registers only batches whose entire `t0` range is on or after `2026-09-24`.
- Historical M6 replay batches are ignored as M7 evidence rather than causing false gate failures.
- A V2 motivated by M7 findings requires a new future holdout.

## Two evidence tracks

### Operational evidence

Starts as soon as genuinely prospective batches exist: scoring reliability, data-contract compliance, review completion, review latency, monitoring alerts, incidents and audit integrity.

### Outcome evidence

Starts only after the frozen 180-day target is fully observable. M7 adds a conservative reporting-lag buffer before treating a contract as label-mature. Immature contracts remain censored and are never imputed as negatives.

## Frozen ranking semantics

Operational top-K evaluation preserves the deterministic V1 ranking:

```text
score DESC
raw_score DESC
contract_id ASC
```

This matters because isotonic calibration can create score plateaus.

## Interpretation of failure

M7 closure is an **evidence-completeness** decision, not a requirement that ARGOS V1 performs well. A scientifically valid negative prospective result can close M7 with a governed decision such as:

- `continue_shadow`
- `recalibrate`
- `retrain_v2`
- `controlled_pilot`

Only the last one is a possible controlled operating state, and even it is not an autonomous production promotion.

## Human review limitation

Reviewer outcomes from the model-selected top-K queue are operational/descriptive evidence. Without an independently sampled comparison group they must not be interpreted as a causal estimate of model utility versus unreviewed contracts.

## Gate philosophy

M7 remains open while prospective evidence is immature. Waiting is a methodological requirement, not a software failure.
