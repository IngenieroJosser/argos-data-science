# M6 Gate

**Decision:** M6 ❌ OPEN

**Blocking checks:** 9/16

**Deployment status:** `NOT_READY`

M6 closure validates reproducible batch scoring, lineage, executable monitoring, auditability, rollback and human-review workflow. It does **not** authorize autonomous sanctions, eligibility decisions, corruption/fraud findings or legal conclusions. Direct production promotion remains disabled in `configs/production.toml`.

**Failed checks:** notebook_50_blocking_checks, notebook_53_blocking_checks, notebook_56_blocking_checks, m6_manifests_complete, frozen_model_registry_lineage, human_review_governance, shadow_only_deployment_state
