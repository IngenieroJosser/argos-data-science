# ARGOS — M7 package

This repository snapshot starts `M7 — Prospective Validation & Operational Evaluation` on top of the formally closed M6 state.

Key contract:

- schema: `m7-prospective-v2`
- protocol freeze: `2026-09-23`
- first eligible prospective `t0`: `2026-09-24`
- target: `y_addition_180d`
- horizon: `(t0, t0 + 180d]`
- operating mode: `shadow_human_review`
- automatic production promotion: disabled
- TEST 2025 / OOT 2026: consumed; historical benchmark only

Run `60_prospective_protocol_freeze.ipynb` first. Notebook 61 remains waiting until genuinely future scoring batches exist. Notebooks 62–67 intentionally cannot close today because outcome evidence must mature prospectively.

The protocol manifest is immutable after creation. Historical M6 replay batches are excluded from M7 evidence rather than causing a false prospective-gate failure.
