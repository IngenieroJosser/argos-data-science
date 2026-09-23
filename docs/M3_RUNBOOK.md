# M3 Runbook — Gold / Point-in-Time Analytical Layer

> **Estado:** ✅ CLOSED — 13/13 checks bloqueantes  
> **Prerequisito:** `M2 ✅ CLOSED`  
> **Gold schema:** `m3-gold-v1`  
> **Gate autoritativo:** `docs/decisions/M3_GATE.md`

M3 transforma la capa Silver canónica en una representación analítica apta para modelado temporal. El objetivo no fue maximizar el número de features, sino demostrar que **cada label y cada feature puede reconstruirse con la información disponible en su `t0`**.

## Orden ejecutado

```text
20_target_engineering.ipynb                  ✅ PASS — 13/13
21_temporal_split_design.ipynb               ✅ PASS — 7/7
22_train_eda.ipynb                           ✅ PASS — 3/3
23_contract_features.ipynb                   ✅ PASS — 4/4
24_historical_features.ipynb                 ✅ PASS — 3/3
25_competition_relationship_features.ipynb   ✅ PASS — 3/3
26_gold_point_in_time_audit.ipynb            ✅ PASS — 8/8
27_m3_gate.ipynb                             ✅ CLOSED — 13/13
```

M3 queda congelado. Estos notebooks no deben reejecutarse por rutina durante Modeling; solo deben reabrirse si cambia una fuente, target, split, regla temporal, schema Gold o artefacto que invalide su evidencia.

## 20 — Target engineering

Semántica V1 validada:

```text
t0 = fecha_de_firma
horizon = 180 días
evento positivo = ADICION EN EL VALOR
ventana = (t0, t0 + 180d]
label cutoff = 2026-09-09
```

Los contratos con ventana incompleta son censurados y conservan label `NULL`.

Evidencia empírica principal:

```text
contratos totales              6,066,730
t0 válido                      5,640,278
elegibles                      5,312,182
positivos                         85,864
prevalencia elegible              1.6164%
missing t0                       426,452
right censored                   301,370
t0 posterior al label cutoff      26,726
```

Salidas:

```text
data/gold/target_population.parquet
data/gold/labels/y_addition_180d.parquet
reports/gold/20_target_validation.parquet
reports/gold/20_target_by_year.parquet
reports/gold/20_target_event_scope.parquet
reports/gold/20_target_censoring.parquet
artifacts/manifests/gold_target_y_addition_180d.json
```

## 21 — Temporal split design

Split V1 congelado y validado:

| split | periodo | filas | positivos | prevalencia |
|---|---|---:|---:|---:|
| train | 2015-06-11 .. 2023-12-31 | 2,781,601 | 58,446 | 2.1012% |
| validation | 2024-01-01 .. 2024-12-31 | 950,670 | 9,180 | 0.9656% |
| test | 2025-01-01 .. 2025-12-31 | 1,050,857 | 10,983 | 1.0451% |

2026 permanece fuera del split principal. Hay 529,054 contratos elegibles en 2026 clasificados como `eligible_out_of_split`; la cohorte reciente no se mezcla con train/validation/test.

El test no debe utilizarse en feature engineering, selección de modelos ni tuning.

## 22 — Train-only EDA

Toda exploración orientada a decisiones de modelado se realizó sobre `split='train'`.

Resultado principal:

```text
train rows       2,781,601
positivos           58,446
negativos         2,723,155
prevalencia          2.1012%
null labels                0
```

Se auditaron cobertura, missingness y cardinalidad de los candidates autorizados sin utilizar validation o test para decidir features.

## 23 — Contract features

Se materializó una whitelist conservadora configurada en `configs/gold.toml`.

`contracts_snapshot_state.parquet` no fue consumido. Los campos conocidos como mutables/post-`t0` permanecieron prohibidos. El componente contractual aporta 23 features finales: 19 candidates conservadores y 4 derivados de calendario de `t0`.

## 24 — Historical features

Se construyó historia estrictamente anterior a `t0`:

- número previo de contratos del proveedor;
- número previo de contratos de la entidad;
- historial proveedor–entidad;
- tenure y recencia;
- eventos de `ADICION EN EL VALOR` observados antes de `t0`.

Regla validada:

```text
history_timestamp < t0
future_or_same_time_violations = 0
```

Los timestamps máximos utilizados se conservaron como metadata `_pit_*` para auditoría y no son features del modelo.

## 25 — Competition & relationship features

La competencia se construyó únicamente con observaciones demostrablemente disponibles antes de firma:

```text
publication_at <= t0
future_publication_violations = 0
```

Si `publication_at` es nulo, la participación no se considera demostrablemente disponible en `t0`.

## 26 — Gold PIT audit

El audit conjunto de labels, split y features materializó:

```text
data/gold/ml/argos_v1.parquet
```

Resultado:

```text
filas model matrix                 4,783,128
features auditadas                        41
null labels                                0
t0 mismatches                              0
historical future/same-time violations    0
competition future violations             0
forbidden snapshot fields                 []
PIT metadata exposed as features          []
```

Composición del feature registry:

```text
contract_features      23
historical_features    12
competition_features    6
TOTAL                   41
```

## 27 — M3 Gate

El gate verificó de forma computable:

- resultados bloqueantes de `20`–`26`;
- 7 artefactos Gold canónicos;
- manifests de lineage completos;
- schema `m3-gold-v1` consistente;
- target spec congelado;
- split temporal congelado;
- issue register sin issues bloqueantes ni warnings.

Resultado:

```text
M3 ✅ CLOSED
Blocking checks: 13/13
```

## Handoff a M4

Modeling queda autorizado únicamente sobre el contrato descrito en `docs/M4_HANDOFF.md`.

Principios que continúan vigentes:

- TEST 2025 permanece sellado hasta evaluación final;
- el desbalance y el cambio de prevalencia son propiedades del problema, no errores a borrar del evaluation set;
- ninguna feature nueva puede incorporarse sin volver a demostrar su point-in-time correctness;
- Bronze y Silver no se utilizan directamente para modelar cuando existe el model matrix Gold auditado.

## Principio de diseño

> El dataset Gold debe poder reconstruirse como si el sistema estuviera situado en cada `t0`. Si para calcular una feature es necesario conocer el futuro, esa feature no pertenece al modelo V1.
