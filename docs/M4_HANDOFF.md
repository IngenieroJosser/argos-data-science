# ARGOS — Handoff M3 → M4

> **Origen:** M3 — Gold / Point-in-Time Analytical Layer  
> **Estado de origen:** ✅ CLOSED — 13/13 checks bloqueantes  
> **Destino:** M4 — Modeling & Evaluation  
> **Estado de destino:** ✅ CLOSED — 14/14 checks bloqueantes  
> **Contrato de entrada:** `m3-gold-v1`

## Estado del handoff

Este contrato fue ejecutado completamente por M4 y se conserva como evidencia histórica. La autoridad de cierre es `docs/decisions/M4_GATE.md`; la transición vigente está en `docs/M5_HANDOFF.md`.

## 1. Propósito

M4 debe medir si las señales construidas en Gold permiten priorizar contratos con riesgo de una `ADICION EN EL VALOR` futura bajo un esquema temporal realista. M4 no redefine el target ni reconstruye el dataset histórico.

## 2. Inputs autorizados

Entrada principal:

```text
data/gold/ml/argos_v1.parquet
```

Registro de features:

```text
reports/gold/26_feature_registry.parquet
```

Documentos de autoridad:

```text
docs/target-specs/y_addition_180d.md
docs/decisions/M3_TEMPORAL_SPLIT_FREEZE.md
docs/decisions/M3_GATE.md
docs/decisions/M3_CLOSURE_REVIEW_2026-09-23.md
```

Modeling no debe leer Bronze directamente para construir features. Silver solo puede consultarse para investigación o debugging trazable; cualquier feature nueva exige volver al proceso Gold y repetir su auditoría point-in-time.

## 3. Target

```text
y = y_addition_180d
positive = ADICION EN EL VALOR en (t0, t0 + 180d]
```

El target es binario dentro del model matrix; los contratos censurados no forman parte de train/validation/test.

## 4. Split congelado

| split | filas | positivos | prevalencia |
|---|---:|---:|---:|
| train | 2,781,601 | 58,446 | 2.1012% |
| validation | 950,670 | 9,180 | 0.9656% |
| test | 1,050,857 | 10,983 | 1.0451% |

Política:

```text
TRAIN       fit + feature/model diagnostics permitidos
VALIDATION  model selection, hyperparameter tuning, calibration design
TEST        evaluación final; no tuning, no feature selection, no threshold selection
```

No se permiten splits aleatorios como evaluación primaria.

## 5. Feature contract

M3 autorizó **41 features**:

```text
23 contract features
12 historical features
 6 competition features
```

`contract_id`, `t0`, `split` y `y_addition_180d` son metadata/target, no predictores.

No están autorizados:

- campos mutables de `contracts_snapshot_state.parquet`;
- columnas `_pit_*` de auditoría;
- agregados calculados sobre toda la historia sin corte temporal;
- información del outcome futuro;
- features derivadas utilizando TEST.

## 6. Riesgos de evaluación

### Desbalance

El target es infrecuente. `accuracy` puede ser alta con un clasificador inútil y no será una métrica primaria.

### Temporal shift

La prevalencia disminuye de 2.1012% en TRAIN a 0.9656% en validation y 1.0451% en TEST. M4 debe medir discriminación y calibración bajo este cambio de base rate.

No se debe rebalancear validation/test. Si se utilizan class weights o sampling en entrenamiento, deben aplicarse exclusivamente a TRAIN y sus efectos sobre calibración deben medirse explícitamente.

## 7. Métricas obligatorias

Métricas de discriminación/probabilidad:

```text
PR-AUC
ROC-AUC
Log Loss
Brier Score
Calibration / reliability
```

Métricas de decisión y ranking:

```text
Precision@K
Recall@K
Lift@K
Cumulative Gain
```

`K` debe interpretarse como capacidad de revisión y documentarse con valores operativos concretos.

## 8. Secuencia ejecutable de M4

```text
30_baseline_heuristics.ipynb
31_logistic_regression_baseline.ipynb
32_boosting_models.ipynb
33_calibration_and_ranking.ipynb
34_error_analysis_and_explainability.ipynb
35_ablation_studies.ipynb
36_business_impact.ipynb
37_m4_gate.ipynb
```

La secuencia puede refinarse mediante una decisión documentada, pero el principio permanece: baseline antes de complejidad y TEST solo al final.

## 9. Criterios mínimos para cerrar M4

M4 deberá demostrar, como mínimo:

- baseline de prevalencia/dummy reproducible;
- baseline heurístico reproducible;
- Logistic Regression temporalmente correcta;
- al menos un modelo boosting comparado de forma justa;
- métricas de ranking y probabilidad en validation;
- calibración medida y, si se aplica, calibrador entrenado sin TEST;
- evaluación final única sobre TEST para el conjunto de modelos/decisiones congeladas;
- error analysis por segmentos relevantes;
- ablations para cuantificar el valor incremental de familias de features;
- artefactos y manifests reproducibles;
- un gate M4 sin checks bloqueantes fallidos.

## 10. Principio operativo

> M4 evalúa modelos sobre un mundo histórico ya congelado. Si una mejora exige cambiar el pasado, el target, el split o las features, esa mejora vuelve a Gold y debe reauditarse antes de competir como modelo.
