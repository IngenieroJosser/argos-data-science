# ARGOS — Catálogo Gold M3

> **Milestone:** M3 — Gold / Point-in-Time Analytical Layer  
> **Estado:** ▶ IN PROGRESS  
> **Schema:** `m3-gold-v1`

| Artefacto | Grain | Propósito |
|---|---|---|
| `target_population.parquet` | 1 fila por contrato | `t0`, ventana, cutoff, elegibilidad y censura |
| `labels/y_addition_180d.parquet` | 1 fila por contrato | label binario/null + evidencia del primer evento |
| `splits/temporal_split.parquet` | 1 fila por contrato | asignación temporal train/validation/test/out-of-split |
| `features/contract_features.parquet` | 1 fila por contrato con t0 | whitelist conservadora de features contractuales |
| `features/historical_features.parquet` | 1 fila por contrato con t0 | históricos estrictamente anteriores a `t0` |
| `features/competition_features.parquet` | 1 fila por contrato con t0 | competencia observable por publicación antes de `t0` |
| `ml/argos_v1.parquet` | 1 fila por contrato asignado | model matrix auditado para Modeling |

## Convenciones

- `_gold_schema_version` es lineage, no feature.
- columnas `_pit_*` son evidence timestamps para auditoría y no se exponen en `ml/argos_v1.parquet`.
- `contract_id` y `t0` son claves/contexto, no features.
- `split` y `y_addition_180d` son metadata/target, no features.
