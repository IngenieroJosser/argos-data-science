# ARGOS — M4 Runbook: Modeling & Evaluation

> **Milestone:** M4 — Modeling & Evaluation  
> **Estado:** ✅ CLOSED — 14/14 checks bloqueantes  
> **Entrada congelada:** `m3-gold-v1`  
> **Contrato M4:** `m4-model-v1`

## 1. Objetivo

M4 determina si las 41 señales point-in-time aprobadas en M3 permiten priorizar contratos con mayor probabilidad de una `ADICION EN EL VALOR` en los 180 días posteriores a `t0`.

M4 no redefine target, splits ni features. Cualquier modificación de esas piezas vuelve a Gold y requiere reauditoría PIT.

## 2. Dataset autorizado

```text
data/gold/ml/argos_v1.parquet
```

Feature registry:

```text
reports/gold/26_feature_registry.parquet
```

Split congelado:

| split | filas | positivos | prevalencia |
|---|---:|---:|---:|
| train | 2,781,601 | 58,446 | 2.1012% |
| validation | 950,670 | 9,180 | 0.9656% |
| test | 1,050,857 | 10,983 | 1.0451% |

## 3. Política de TEST

TEST permanece sellado durante notebooks `30`–`35`.

```text
30–35 -> TRAIN + VALIDATION solamente
36    -> única evaluación final TEST
37    -> gate sobre artefactos ya materializados
```

Notebook `33` congela `artifacts/models/m4/selected_model.json` y hashes del modelo/calibrador antes de TEST. Notebook `36` verifica esos hashes antes de evaluar TEST y persiste la evidencia en `m4_final_test.json`.

Una ejecución completa de `36` se reutiliza en reruns; no se recalcula TEST. Si existe un conjunto parcial de artefactos de `36`, el pipeline se detiene para exigir investigación explícita.

## 4. Secuencia

### 30 — Baselines

- prevalencia constante;
- heurística histórica PIT;
- PR-AUC, ROC-AUC, Log Loss, Brier, ECE;
- Precision@K, Recall@K, Lift@K, cumulative gain;
- cero acceso a TEST.

### 31 — Logistic Regression baseline

Implementación escalable: `SGDClassifier(loss="log_loss")` con one-hot acotado, entrenamiento streaming sobre TRAIN completo y class weighting solo durante entrenamiento.

### 32 — Boosting

`HistGradientBoostingClassifier` sobre una muestra TRAIN determinística y versionada. La muestra es una decisión de ingeniería para respetar el presupuesto de memoria local; VALIDATION se evalúa completo.

### 33 — Calibration & ranking

VALIDATION se divide temporalmente:

```text
calibration fit   <= 2024-06-30
selection eval    >= 2024-07-01
```

Se comparan `none`, `sigmoid` e `isotonic`. El candidato de modelo se selecciona por PR-AUC/ROC-AUC en la segunda mitad; la calibración se selecciona por Brier, Log Loss y ECE. El resultado queda congelado antes de TEST.

### 34 — Error analysis

Diagnóstico de score y errores operativos por segmentos suficientemente poblados. No cambia el modelo seleccionado.

### 35 — Ablations

Compara, con protocolo fijo:

```text
contract
contract + historical
all = contract + historical + competition
```

Los ablations son diagnósticos y no reabren el feature contract de Gold.

### 36 — Final TEST & business impact

Único acceso a TEST. Reporta desempeño final y curvas de capacidad de revisión. No estima ahorros monetarios sin un modelo económico validado.

### 37 — M4 Gate

Verifica integridad de componentes, manifests, schema, aislamiento de TEST, hashes congelados y model card.

## 5. Métricas

Primarias para un target raro:

```text
PR-AUC
Precision@K
Recall@K
Lift@K
Cumulative Gain
```

Complementarias:

```text
ROC-AUC
Log Loss
Brier
ECE / reliability
```

`accuracy` no es criterio de aceptación.

## 6. Operating point predeclarado

La capacidad operativa V1 se congela en:

```text
review_fraction = 1%
```

También se reportan 0.1%, 0.5%, 2.5%, 5% y 10% para sensibilidad.

## 7. Criterios de utilidad congelados antes de TEST

M4 exige como mínimo:

- PR-AUC de selección superior a la prevalencia de referencia;
- Lift@1% de selección > 1;
- Lift@1% final TEST > 1;
- métricas finitas y población TEST completa;
- modelo/calibrador usados en TEST idénticos a los hashes congelados en 33.

Estos umbrales comprueban utilidad mínima frente a revisión aleatoria; no representan un SLA de producción.

## 8. Artefactos principales

```text
artifacts/models/m4/
  logistic_sgd.joblib
  hist_gradient_boosting.joblib
  selected_calibrator.joblib
  selected_model.json

reports/modeling/
  30_*.parquet
  31_*.parquet
  32_*.parquet
  33_*.parquet
  34_*.parquet
  35_*.parquet
  36_*.parquet
  m4_gate_report.parquet

artifacts/manifests/
  m4_baselines.json
  m4_logistic.json
  m4_boosting.json
  m4_calibration_selection.json
  m4_error_analysis.json
  m4_ablation.json
  m4_final_test.json

docs/models/ARGOS_V1_MODEL_CARD.md
docs/decisions/M4_GATE.md
```

## 9. Orden de ejecución

Ejecutar notebooks `30` → `37` en orden. No avanzar si el notebook actual no termina en `✅ PASS`. En particular, no abrir `36` como vía de exploración: su única función es ejecutar o reutilizar la evaluación TEST final.

## 10. Cierre

M4 solo puede cerrarse mediante `37_m4_gate.ipynb`. Un cierre M4 valida el experimento predictivo V1 y su evaluación temporal; no equivale a autorización de despliegue autónomo ni a una conclusión jurídica sobre contratos o proveedores.

## 11. Resultado ejecutado

La ejecución real cerró todos los componentes:

```text
30 baselines                   4/4 PASS
31 logistic baseline           4/4 PASS
32 boosting                    4/4 PASS
33 calibration + selection     6/6 PASS
34 error analysis              3/3 PASS
35 ablations                   4/4 PASS
36 final TEST                  5/5 PASS
37 M4 gate                    14/14 PASS
```

Modelo congelado antes de TEST: `hist_gradient_boosting + isotonic`. Resultado final TEST: PR-AUC `0.135250`, ROC-AUC `0.872745`, Brier `0.009638`, ECE `0.002843` y Lift@1% `25.274x`.

## 12. Deuda transportada

El cierre M4 valida el experimento V1, no producción. Permanecen como trabajo explícito: robustez temporal adicional, explicación por feature, incertidumbre de métricas, revisión de la utilidad incremental de competition features y monitoreo de calibración en la cola alta. El TEST 2025 queda consumido. Ver `decisions/M4_CLOSURE_REVIEW_2026-09-23.md` y `M5_HANDOFF.md`.
