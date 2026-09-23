# ARGOS — Catálogo Gold M3

> **Milestone:** M3 — Gold / Point-in-Time Analytical Layer  
> **Estado:** ✅ CLOSED — 13/13 checks bloqueantes  
> **Schema:** `m3-gold-v1`  
> **Gate:** `docs/decisions/M3_GATE.md`

M3 materializa el contrato analítico V1 utilizado por Modeling. Estos artefactos están congelados junto con el código y las decisiones que produjeron el cierre del milestone.

| Artefacto | Grain | Filas observadas | Propósito |
|---|---|---:|---|
| `target_population.parquet` | 1 fila por contrato | 6,066,730 | `t0`, ventana, cutoff, elegibilidad y censura |
| `labels/y_addition_180d.parquet` | 1 fila por contrato | 6,066,730 | label binario/null + evidencia del primer evento |
| `splits/temporal_split.parquet` | 1 fila por contrato | 6,066,730 | asignación temporal train/validation/test/out-of-split |
| `features/contract_features.parquet` | 1 fila por contrato con `t0` válido | 5,640,278 | whitelist conservadora de features contractuales |
| `features/historical_features.parquet` | 1 fila por contrato con `t0` válido | 5,640,278 | históricos estrictamente anteriores a `t0` |
| `features/competition_features.parquet` | 1 fila por contrato con `t0` válido | 5,640,278 | competencia observable hasta `t0` |
| `ml/argos_v1.parquet` | 1 fila por contrato asignado | 4,783,128 | model matrix auditado para Modeling |

## Model matrix V1

`data/gold/ml/argos_v1.parquet` contiene únicamente contratos asignados a TRAIN, VALIDATION o TEST y con label binario completo.

```text
train        2,781,601
validation     950,670
test         1,050,857
TOTAL        4,783,128
```

El feature registry auditado contiene **41 features**:

```text
contract_features      23
historical_features    12
competition_features    6
TOTAL                   41
```

## Convenciones

- `_gold_schema_version` es lineage, no feature.
- columnas `_pit_*` son evidence timestamps para auditoría y no se exponen en `ml/argos_v1.parquet`.
- `contract_id` y `t0` son claves/contexto, no features.
- `split` y `y_addition_180d` son metadata/target, no features.
- el conjunto `test` está congelado y no participa en feature design, model selection ni tuning.
- ninguna columna de `contracts_snapshot_state.parquet` está autorizada automáticamente como feature.

## Semántica del target

```text
target          = y_addition_180d
t0              = fecha_de_firma
positive event  = ADICION EN EL VALOR
window          = (t0, t0 + 180d]
horizon         = 180 días
censoring       = label NULL cuando el horizonte no es observable
label cutoff    = 2026-09-09
```

La definición autoritativa vive en `docs/target-specs/y_addition_180d.md`.

## Evidencia point-in-time

`26_gold_point_in_time_audit.ipynb` cerró con **8/8 checks bloqueantes** y observó:

```text
t0 mismatches                              0
historical future/same-time violations    0
competition future violations             0
forbidden snapshot fields                 []
PIT metadata exposed as features          []
null labels in model matrix                0
```

## Consumo autorizado

M4 debe consumir `ml/argos_v1.parquet` y `reports/gold/26_feature_registry.parquet` como contrato de entrada. Cambios a la semántica, split o feature registry requieren una nueva decisión y la reejecución de los checks Gold afectados.
