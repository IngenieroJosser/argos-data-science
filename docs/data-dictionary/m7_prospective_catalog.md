# M7 Prospective Evidence Catalog

| Artifact | Grain | Purpose |
|---|---|---|
| `artifacts/manifests/m7_protocol_freeze.json` | one protocol | immutable preregistration of hashes, dates and governance |
| `artifacts/prospective/cohort_registry.parquet` | one eligible scoring batch | registry of genuinely post-freeze scoring evidence |
| `artifacts/prospective/label_locks/*.parquet` | one contract | immutable matured prospective labels |
| `artifacts/prospective/label_locks/*.json` | one cohort lock | label lineage, watermark and hashes |
| `artifacts/prospective/label_lock_registry.parquet` | one matured cohort | inventory of label locks |
| `artifacts/prospective/incident_register.parquet` | one incident | prospective incident history |
| `artifacts/prospective/m7_decision_record.json` | one governed decision | final human-approved operational decision |
| `reports/prospective/60_validation.parquet` | one check | protocol freeze validation |
| `reports/prospective/61_validation.parquet` | one check | future cohort collection readiness |
| `reports/prospective/62_validation.parquet` | one check | outcome maturity/label-lock evidence |
| `reports/prospective/63_validation.parquet` | one check | prospective model evaluation completeness |
| `reports/prospective/64_validation.parquet` | one check | human-review operational evidence |
| `reports/prospective/65_validation.parquet` | one check | longitudinal monitoring/incidents evidence |
| `reports/prospective/66_validation.parquet` | one check | governed decision evidence |
| `reports/prospective/m7_gate_report.parquet` | one gate check | final M7 acceptance evidence |
