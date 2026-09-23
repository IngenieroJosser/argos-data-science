# M6.56 — Deployment assets remediation

## Status
Resolved implementation/packaging defect. This decision does not weaken any M6 readiness criterion.

## Observed failure
`56_operational_readiness.ipynb` reported `5/6` blocking checks. The persisted validation showed the only failed check was `deployment_assets_present` with `.dockerignore` and `.github/workflows/ci.yml` missing from the repository root.

## Root cause
The operational readiness gate correctly requires deployment-support assets to be version-controlled at repository root. Prior delivery/application did not place the hidden `.dockerignore` and `.github/workflows/ci.yml` files in that root, so the gate continued to fail even though notebooks 50–55 were valid.

## Remediation
- add repository-root `.dockerignore`;
- add `.github/workflows/ci.yml` with locked dependency sync, unit tests, compilation, container build and CLI smoke test;
- bump readiness implementation to `m6-56-operational-readiness-v2`;
- make notebook 56 print the exact blocking failure before asserting.

## Preserved invariants
No model, calibrator, score, threshold, monitoring rule, human-review requirement, deployment state, model hash, or promotion policy was relaxed. `human_review_required=true` and `allow_production_promotion=false` remain unchanged.
