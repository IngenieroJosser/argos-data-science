# M3 Gate — Gold point-in-time analytical layer

**Decision:** M3 ✅ CLOSED

**Blocking checks:** 13/13

## Checks

| check_id | category | status | requirement | observed |
|---|---|---|---|---|
| notebook_20_blocking_checks | component | PASS | notebook 20 has all blocking checks passed | {"blocking": 13, "failed": [], "passed": 13} |
| notebook_21_blocking_checks | component | PASS | notebook 21 has all blocking checks passed | {"blocking": 7, "failed": [], "passed": 7} |
| notebook_22_blocking_checks | component | PASS | notebook 22 has all blocking checks passed | {"blocking": 3, "failed": [], "passed": 3} |
| notebook_23_blocking_checks | component | PASS | notebook 23 has all blocking checks passed | {"blocking": 4, "failed": [], "passed": 4} |
| notebook_24_blocking_checks | component | PASS | notebook 24 has all blocking checks passed | {"blocking": 3, "failed": [], "passed": 3} |
| notebook_25_blocking_checks | component | PASS | notebook 25 has all blocking checks passed | {"blocking": 3, "failed": [], "passed": 3} |
| notebook_26_blocking_checks | component | PASS | notebook 26 has all blocking checks passed | {"blocking": 8, "failed": [], "passed": 8} |
| gold_artifacts_complete | artifacts | PASS | all canonical M3 Gold artifacts exist | {"expected": 7, "missing": []} |
| gold_lineage_manifests_complete | lineage | PASS | all M3 component manifests are persisted | {"missing": []} |
| gold_schema_version_consistent | lineage | PASS | all M3 manifests declare the active Gold schema version | {"errors": [], "expected": "m3-gold-v1"} |
| target_spec_frozen | target | PASS | target specification is explicitly frozen for M3 V1 semantics | {"exists": true, "path": "/Users/macm1pro/Desktop/projects/argos/argos-code/docs/target-specs/y_addition_180d.md"} |
| temporal_split_decision_frozen | validation | PASS | temporal train/validation/test policy is documented as a frozen decision | {"exists": true, "path": "/Users/macm1pro/Desktop/projects/argos/argos-code/docs/decisions/M3_TEMPORAL_SPLIT_FREEZE.md"} |
| no_blocking_gold_issues | quality | PASS | M3 issue register exists and contains zero blocking issues | {"blocking_issues": 0, "warning_issues": 0} |

## Modeling handoff

- Modeling consumes `data/gold/ml/argos_v1.parquet`; it does not read Bronze directly.
- The test period is frozen and must not be used for feature design or hyperparameter tuning.
- `y_addition_180d` means a literal `ADICION EN EL VALOR` in `(t0, t0+180d]`.
- Historical and competition features have passed explicit point-in-time audits.
