# M5 Closure Review — 2026-09-23

## Decision

**M5 — Advanced Data Science & Robustness: ✅ CLOSED.**

The closure is supported by the computable gate in `docs/decisions/M5_GATE.md`, which passed **16/16 blocking checks**. This review records the professional interpretation of that evidence and the constraints that must travel to M6.

## Scope that was actually validated

M5 validated the robustness evidence package around the frozen ARGOS V1:

- rolling-origin temporal backtesting over 2021–2024;
- feature-level global explainability and local predictive sensitivity;
- block-bootstrap uncertainty and deterministic ranking semantics;
- feature/score drift and top-tail calibration diagnostics;
- fair feature-family revalidation;
- fresh post-2025 OOT evaluation with the exact frozen V1;
- monitoring and robustness documentation;
- lineage and holdout governance.

M5 did **not** silently reselect the model after observing TEST 2025 or OOT 2026.

## Fresh OOT 2026

The fully observable partial-year cohort spans `2026-01-01` through `2026-03-13`:

| Metric | Value |
|---|---:|
| Rows | 529,054 |
| Positives | 7,255 |
| Prevalence | 1.3713% |
| PR-AUC | 0.053274 |
| ROC-AUC | 0.744544 |
| Brier | 0.013238 |
| ECE | 0.003093 |
| Precision@1% | 8.5806% |
| Recall@1% | 6.2578% |
| Lift@1% | 6.257x |

The model still ranks positives above random review, but performance is materially below TEST 2025. Relative to the M4 TEST benchmark, PR-AUC decreased by approximately **60.6%** and Lift@1% by approximately **75.2%**. This is evidence of temporal degradation and is a production-monitoring requirement.

The 2026 cohort is partial-year because the 180-day target requires complete follow-up; it is not a seasonally representative full-year holdout.

## Temporal robustness

Rolling-origin PR-AUC varies materially by cohort:

```text
2021  0.048415
2022  0.072170
2023  0.094661
2024  0.060340
```

The system therefore must not assume stationarity. Operational evaluation must remain cohort-aware.

## Explainability and uncertainty

All 41 model features are covered by persisted permutation-importance evidence, and local sensitivity is available for selected priority cases. These artifacts describe predictive dependence, not causal effects.

The block-bootstrap protocol used 200 calendar-week replicates at 95% confidence. At the 1% operating capacity, Lift@K was 17.929 with interval `[12.130, 22.940]` in the development evaluation used by M5.

## Drift and feature families

M5 identified three high-drift feature-period pairs. The monitoring specification therefore freezes explicit thresholds for numeric PSI, categorical TVD, score PSI, prevalence shift, top-tail calibration, Lift@K and missingness.

Feature-family revalidation does not support an unconditional claim that adding competition features always improves the system. Future versions must demonstrate their incremental value under the same temporal protocol and training budget.

## Governance conclusion

M5 is professionally closable because:

1. the protocol is explicit and versioned;
2. holdout roles are preserved;
3. the fresh OOT was consumed only after development diagnostics;
4. no hidden reselection followed OOT observation;
5. model/calibrator lineage remained intact;
6. important negative findings (degradation and drift) were preserved rather than optimized away;
7. monitoring obligations are persisted;
8. the gate explicitly refuses to auto-authorize production.

## What M5 does not claim

M5 does not establish causal effects, corruption/fraud labels, legal conclusions, stationarity, full-year 2026 representativeness, or production safety by itself.

## Transition to M6

Productionization belongs to **M6 — Productionization & MLOps**. M6 must operationalize reproducible scoring, registry/versioning, monitoring, rollback, auditability and human review. The target operating model is not autonomous enforcement; it is automated analytical prioritization followed by human assessment.

TEST 2025 and OOT 2026 are now consumed for ARGOS V1. Any future V2 selected using knowledge gained from these results requires a later untouched holdout for a new final generalization claim.
