# M5 Evaluation Governance — 2026-09-23

## Context

M4 consumed TEST 2025 exactly once after freezing `hist_gradient_boosting + isotonic`. Reusing that period to select M5 changes would invalidate any claim that it remains an independent final test.

At the current SECOP II snapshot, Gold contains some 2026 contracts whose full 180-day target horizon is already observable. Those rows have not participated in M4 selection or evaluation.

## Decision

1. TEST 2025 is permanently classified as a **consumed historical benchmark**.
2. M5 development evidence uses only pre-2025 periods for selection-like work.
3. 2026 fully observed rows are reserved as the **fresh OOT M5 holdout**.
4. Notebooks `40–44` must complete before notebook `45` can consume the 2026 holdout.
5. Notebook `45` scores the exact M4-frozen model/calibrator; it does not train, tune, recalibrate, select features or alter thresholds.
6. After notebook `45`, the 2026 cohort is also considered consumed for future model selection.
7. Any subsequent improved model requires a later untouched temporal holdout for a new final-generalization claim.

## Rationale

The rule separates **development evidence** from **final evidence** and prevents iterative peeking from silently converting a holdout into another validation set.

The 2026 holdout is partial-year because label eligibility requires the complete 180-day horizon. Its freshness is valuable, but seasonal representativeness is explicitly limited.

## Operational safeguard

`pipelines/run_robustness_m5.py` stops after notebooks `40–44` by default. Holdout consumption requires the explicit CLI flag:

```bash
uv run python pipelines/run_robustness_m5.py --consume-fresh-oot
```
