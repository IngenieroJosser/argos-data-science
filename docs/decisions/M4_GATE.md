# M4 Gate — Modeling & Evaluation

**Decision:** M4 ✅ CLOSED

**Blocking checks:** 14/14

## Checks

| check_id | category | status | requirement | observed |
|---|---|---|---|---|
| m3_gate_closed | prerequisite | PASS | M4 may close only on top of a formally closed M3 Gold layer | {"exists": true, "path": "/Users/macm1pro/Desktop/projects/argos/argos-code/docs/decisions/M3_GATE.md"} |
| notebook_30_blocking_checks | component | PASS | notebook 30 has all blocking checks passed | {"blocking": 4, "failed": [], "passed": 4} |
| notebook_31_blocking_checks | component | PASS | notebook 31 has all blocking checks passed | {"blocking": 4, "failed": [], "passed": 4} |
| notebook_32_blocking_checks | component | PASS | notebook 32 has all blocking checks passed | {"blocking": 4, "failed": [], "passed": 4} |
| notebook_33_blocking_checks | component | PASS | notebook 33 has all blocking checks passed | {"blocking": 6, "failed": [], "passed": 6} |
| notebook_34_blocking_checks | component | PASS | notebook 34 has all blocking checks passed | {"blocking": 3, "failed": [], "passed": 3} |
| notebook_35_blocking_checks | component | PASS | notebook 35 has all blocking checks passed | {"blocking": 4, "failed": [], "passed": 4} |
| notebook_36_blocking_checks | component | PASS | notebook 36 has all blocking checks passed | {"blocking": 5, "failed": [], "passed": 5} |
| m4_reports_complete | artifacts | PASS | all required M4 evaluation reports exist | {"expected": 11, "missing": []} |
| m4_manifests_complete | lineage | PASS | all M4 lineage manifests exist | {"missing": []} |
| m4_schema_version_consistent | lineage | PASS | all M4 manifests declare the active modeling schema | {"errors": [], "expected": "m4-model-v1"} |
| test_isolation_manifest_policy | test_isolation | PASS | only notebook 36 / final-test manifest declares TEST consumption | {"errors": []} |
| frozen_selection_matches_final_test | test_isolation | PASS | final TEST used exactly the model/calibrator selection frozen before TEST access | {"final_manifest_exists": true, "manifest_selection_sha256": "5b4a3e44292ff4a991d93044b869cb97f26473ee865a4d6f40d255f44cff2daf", "selection_exists": true, "selection_sha256": "5b4a3e44292ff4a991d93044b869cb97f26473ee865a4d6f40d255f44cff2daf", "selection_status": "FROZEN_FOR_TEST"} |
| model_card_persisted | documentation | PASS | final evaluated model has a persisted model card with scope and limitations | {"path": "/Users/macm1pro/Desktop/projects/argos/argos-code/docs/models/ARGOS_V1_MODEL_CARD.md"} |

## Interpretation

M4 closes only if model selection was frozen before TEST, the final TEST evaluation used those exact hashed artifacts, all required model/evaluation artifacts exist, and every component blocking check passes.

A closed M4 validates the V1 predictive modeling experiment; it does not by itself authorize autonomous decision-making or production deployment.
