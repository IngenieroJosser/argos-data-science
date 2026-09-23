# M6.56 — Repository-root deployment asset packaging fix

## Context

`56_operational_readiness` requires `.dockerignore` and `.github/workflows/ci.yml` at the repository root. The previous delivered ZIP contained the entire project under a top-level `code/` directory. If that archive was extracted *inside* the existing `argos-code` directory, the hidden deployment assets landed under `argos-code/code/` instead of the repository root and the blocking check `deployment_assets_present` remained false.

## Remediation

This package is intentionally **repository-rooted**: `Dockerfile`, `.dockerignore`, `.github/`, `src/`, `notebooks/`, etc. are at the archive root. It should be extracted directly into the existing `argos-code` directory.

`56_operational_readiness.ipynb` was also updated to print the exact failed blocking checks before asserting, so future gate failures are diagnosable without inference.

## Preserved invariants

No model, calibrator, score, monitoring threshold, deployment governance rule, human-review requirement, or promotion policy was weakened.
