# M3 — Closure review — 2026-09-23

> **Milestone:** M3 — Gold / Point-in-Time Analytical Layer  
> **Decision:** ✅ CLOSED  
> **Gate:** `27_m3_gate.ipynb` — 13/13 checks bloqueantes  
> **Gold schema:** `m3-gold-v1`  
> **Next milestone:** M4 — Modeling & Evaluation

## 1. Decisión

M3 se considera formalmente cerrado. La evidencia persistida demuestra que ARGOS dispone de una representación Gold reproducible, con target, split y features auditados bajo reglas point-in-time explícitas.

El cierre no depende únicamente de la ejecución exitosa de notebooks. `27_m3_gate.ipynb` consume la evidencia persistida de `20`–`26` y exige que los 13 checks bloqueantes del gate sean aprobados.

## 2. Evidencia de componentes

| componente | checks bloqueantes | estado |
|---|---:|---|
| `20_target_engineering` | 13/13 | PASS |
| `21_temporal_split_design` | 7/7 | PASS |
| `22_train_eda` | 3/3 | PASS |
| `23_contract_features` | 4/4 | PASS |
| `24_historical_features` | 3/3 | PASS |
| `25_competition_relationship_features` | 3/3 | PASS |
| `26_gold_point_in_time_audit` | 8/8 | PASS |
| `27_m3_gate` | 13/13 | CLOSED |

## 3. Target V1 congelado y validado

```text
target          = y_addition_180d
t0              = fecha_de_firma
horizon         = 180 días
positive event  = ADICION EN EL VALOR
window          = (t0, t0 + 180d]
label cutoff    = 2026-09-09
censoring       = horizonte incompleto => NULL
```

Población observada:

```text
contracts total                 6,066,730
valid t0                        5,640,278
eligible                        5,312,182
positive                           85,864
eligible prevalence                1.6164%
missing t0                        426,452
right censored                    301,370
t0 after label cutoff              26,726
```

Las validaciones del target no detectaron eventos positivos fuera de la ventana, labels inconsistentes ni positivos posteriores al cutoff.

## 4. Split temporal congelado

| split | rango `t0` | filas | positivos | prevalencia |
|---|---|---:|---:|---:|
| train | 2015-06-11 .. 2023-12-31 | 2,781,601 | 58,446 | 2.1012% |
| validation | 2024-01-01 .. 2024-12-31 | 950,670 | 9,180 | 0.9656% |
| test | 2025-01-01 .. 2025-12-31 | 1,050,857 | 10,983 | 1.0451% |

La prevalencia cambia materialmente entre TRAIN y 2024–2025. Esto se transporta a M4 como señal de temporal/prior probability shift. No se modifica el split para homogeneizar artificialmente las prevalencias.

## 5. Point-in-time audit

El model matrix final tiene **4,783,128 filas** y **41 features** autorizadas.

El audit observó:

```text
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

## 6. Artefactos y lineage

El gate confirmó:

- 7 artefactos Gold canónicos presentes;
- manifests de componentes completos;
- versión `m3-gold-v1` consistente;
- target spec congelado;
- decisión de split temporal congelada;
- issue register con 0 bloqueantes y 0 warnings.

El contrato de modelado es:

```text
data/gold/ml/argos_v1.parquet
reports/gold/26_feature_registry.parquet
```

## 7. Riesgos transportados a M4

No bloquean el cierre de M3, pero deben permanecer visibles:

1. **Class imbalance:** el target tiene baja prevalencia; accuracy no debe utilizarse como métrica primaria.
2. **Temporal / prior probability shift:** TRAIN presenta prevalencia mayor que validation/test.
3. **Entity resolution parcial:** bidder→supplier conserva estados no resueltos/ambiguos; no deben convertirse artificialmente en matches.
4. **Scope V1:** payments y sanctions permanecen fuera del target actual.
5. **Feature freeze:** nuevas features requieren una nueva auditoría PIT antes de incorporarse al model matrix.
6. **Test isolation:** TEST 2025 no puede intervenir en feature design, model selection, hyperparameter tuning ni threshold selection.

## 8. Condición de transición

Con la evidencia anterior, M4 queda autorizado para construir baselines y modelos sobre el dataset Gold auditado, manteniendo el split temporal y las métricas orientadas a ranking/calibración.

```text
M3 ✅ CLOSED
M4 ▶ READY
```
