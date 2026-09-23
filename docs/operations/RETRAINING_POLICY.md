# ARGOS — Retraining Policy

Retraining is event-driven or scheduled only after labels mature. Triggers include persistent drift, material ranking degradation, upstream schema changes, or an approved model-improvement cycle. TEST 2025 and OOT 2026 are consumed benchmarks and may not be reused as fresh final holdouts for V2. Any new model selected with knowledge from M4/M5 requires a later untouched temporal holdout before a new generalization claim.
