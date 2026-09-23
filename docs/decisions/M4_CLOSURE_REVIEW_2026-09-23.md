# M4 Closure Review — Modeling & Evaluation

> **Fecha:** 2026-09-23  
> **Milestone:** M4 — Modeling & Evaluation  
> **Decisión:** ✅ CLOSED  
> **Gate computable:** `docs/decisions/M4_GATE.md` — 14/14 checks bloqueantes  
> **Modeling schema:** `m4-model-v1`  
> **Gold schema:** `m3-gold-v1`

## 1. Alcance de esta revisión

Esta revisión determina si M4 puede cerrarse como un experimento predictivo V1 profesional, reproducible y metodológicamente defendible. No evalúa preparación para despliegue productivo ni autoriza decisiones autónomas.

La revisión se apoya en los artefactos persistidos por notebooks `30`–`37`, en los manifests de M4, en la selección congelada y en la evaluación TEST final. No se modifica el modelo después de observar TEST.

## 2. Evidencia de ejecución

| componente | checks bloqueantes | resultado |
|---|---:|---|
| 30 — baselines | 4/4 | PASS |
| 31 — logistic baseline | 4/4 | PASS |
| 32 — boosting | 4/4 | PASS |
| 33 — calibration & selection | 6/6 | PASS |
| 34 — error analysis | 3/3 | PASS |
| 35 — ablations | 4/4 | PASS |
| 36 — final TEST | 5/5 | PASS |
| 37 — M4 gate | 14/14 | CLOSED |

El gate verificó reportes y manifests completos, schema consistente, aislamiento de TEST, hash de selección, hashes de modelo/calibrador y model card persistida.

## 3. Baselines y progresión de complejidad

M4 siguió el orden esperado: prevalencia → heurística → modelo lineal → boosting → calibración.

### VALIDATION completo

| modelo | PR-AUC | ROC-AUC | Lift@1% | observación |
|---|---:|---:|---:|---|
| prevalence | 0.009656 | 0.500000 | 0.621x | referencia no informativa; el Lift@K fluctúa por empates |
| historical heuristic | 0.039690 | 0.688805 | 9.390x | ranking útil, calibración no adecuada como probabilidad |
| logistic SGD | 0.038582 | 0.764114 | 5.958x | discriminación moderada; score raw severamente descalibrado |
| hist gradient boosting | 0.064529 | 0.853849 | 11.165x | mejor candidato supervisado antes de calibración |

Los scores raw de los modelos ponderados no deben interpretarse como probabilidades calibradas. M4 lo trata explícitamente en `33`.

## 4. Selección y calibración sin TEST

VALIDATION 2024 se dividió temporalmente:

```text
calibration fit     <= 2024-06-30
selection eval      >= 2024-07-01
```

La selección final fue:

```text
model        = hist_gradient_boosting
calibration  = isotonic
status       = FROZEN_FOR_TEST
```

Sobre `validation_selection`:

| métrica | valor |
|---|---:|
| filas | 428,076 |
| positivos | 1,568 |
| prevalencia | 0.3663% |
| PR-AUC | 0.035580 |
| ROC-AUC | 0.864507 |
| Log Loss | 0.020681 |
| Brier | 0.003606 |
| ECE | 0.002340 |
| Lift@1% | 17.027x |

La selección fue persistida antes de TEST junto con SHA-256 del modelo y del calibrador. El manifest final TEST demuestra que se utilizaron esos mismos bytes.

## 5. Evaluación final TEST

El único acceso de M4 al conjunto TEST ocurrió en notebook `36`, después de congelar selección y calibración.

| métrica | TEST 2025 |
|---|---:|
| filas | 1,050,857 |
| positivos | 10,983 |
| prevalencia | 1.0451% |
| PR-AUC | 0.135250 |
| ROC-AUC | 0.872745 |
| Log Loss | 0.045136 |
| Brier | 0.009638 |
| ECE | 0.002843 |

A la capacidad operativa predeclarada del 1%:

```text
contratos revisados       10,509
positivos capturados       2,776
Precision@1%              26.4155%
Recall@1%                 25.2754%
Lift@1%                   25.274x
```

La PR-AUC está muy por encima de la prevalencia TEST y el Lift@1% muestra concentración material de positivos en el extremo superior del ranking. Esto respalda el cierre de M4 como experimento de priorización V1.

## 6. Hallazgos que NO deben ocultarse

### 6.1 Shift temporal fuerte

La prevalencia cambia materialmente:

```text
TRAIN                    2.1012%
VALIDATION 2024 total    0.9656%
VALIDATION H2            0.3663%
TEST 2025                1.0451%
```

Esto es evidencia de no-estacionariedad. No invalida la evaluación temporal; sí convierte drift monitoring y backtesting por ventanas en requisitos del siguiente milestone.

### 6.2 Calibración de cola alta

El ECE global de TEST es bajo (`0.002843`), pero el bin de mayor score tiene media predicha `0.075748` y tasa observada `0.099972`. La calibración agregada no garantiza calibración perfecta en el segmento operativo de mayor riesgo.

M5 debe reportar calibración condicionada a top-K/deciles además de métricas globales.

### 6.3 Ablations: no hay dominancia de todas las features

En el protocolo reducido de notebook `35`:

```text
contract                  PR-AUC 0.032450
contract + historical     PR-AUC 0.033984
all                       PR-AUC 0.030481
```

Y a 1% de capacidad:

```text
contract                  Lift@1% 18.239x
contract + historical     Lift@1% 16.900x
all                       Lift@1% 14.285x
```

Estos modelos de ablation utilizan un presupuesto distinto al modelo seleccionado, por lo que no deben sustituir retrospectivamente la selección congelada. Sin embargo, sí demuestran que **el valor incremental de las features de competencia no está establecido** y que las familias de features deben revalidarse antes de complejizar el sistema.

### 6.4 Explainability incompleta para producción

Notebook `34` implementa error analysis por segmentos y deciles. No persiste atribución global/local por feature mediante permutation importance, SHAP u otra técnica equivalente.

Esto **no bloquea M4**, cuyo alcance es validar el experimento predictivo V1. Sí debe considerarse bloqueante antes de presentar ARGOS como sistema operativo de apoyo a revisión en un entorno institucional.

### 6.5 Empates introducidos por calibración isotónica

La calibración isotónica es monotónica pero genera plateaus de probabilidad. El ranking actual ordena por el score calibrado con sort estable; por tanto, si un corte top-K cae dentro de un plateau, el orden relativo puede depender del orden de entrada.

Esto no invalida la discriminación del modelo ni el cierre experimental, pero el contrato operativo debe definir un desempate explícito y reproducible, preferiblemente `score calibrado DESC, raw_score DESC, contract_id ASC`. M5 debe cuantificar sensibilidad de Precision/Recall/Lift@K a empates.

### 6.6 Portabilidad del artefacto de modelo

Los modelos M4 se serializan con `joblib` y el lock actual fija `scikit-learn 1.9.1`. Para reproducibilidad local esto es suficiente; para serving/producción el artefacto debe viajar con un entorno versionado y verificado. No se debe asumir compatibilidad de pickles/joblib entre versiones distintas de scikit-learn.

### 6.7 Presupuesto de entrenamiento

El boosting principal se entrenó sobre una muestra TRAIN determinística de 750,000 filas por restricción de memoria local. La decisión es reproducible y válida para M4, pero M5 puede estudiar si el uso de mayor población o algoritmos más adecuados para categorías mejora de forma consistente el resultado.

## 7. Integridad y gobernanza

La revisión considera profesionalmente adecuadas las siguientes decisiones:

- Gold PIT congelado antes de Modeling;
- TEST temporal separado y no utilizado por `30`–`35`;
- selección y calibración congeladas antes de TEST;
- hashes SHA-256 verificados en la evaluación final;
- baseline antes de complejidad;
- métricas apropiadas para target raro y capacidad limitada;
- ablations sin reabrir retrospectivamente el modelo seleccionado;
- model card y manifests persistidos;
- gate computable independiente de que los notebooks simplemente “corran verde”.

## 8. Decisión

**M4 puede cerrarse profesionalmente como Modeling & Evaluation V1.**

La evidencia demuestra utilidad predictiva y de ranking fuera del periodo de selección, con control razonable de leakage y de test contamination para el alcance local del proyecto.

El cierre significa:

```text
M4 ✅ CLOSED — predictive experiment V1 validated
```

No significa:

```text
production ready
causal evidence
fraud/corruption detection
autonomous decision system
```

## 9. Condiciones de entrada a M5

1. TEST 2025 queda **consumido** y no puede usarse para seleccionar mejoras.
2. M5 debe usar rolling/temporal backtests para iteración y reservar un nuevo holdout futuro para otra evaluación final.
3. Toda feature nueva debe volver a Gold y pasar auditoría PIT.
4. Componentes avanzados requieren ablations de valor incremental.
5. Deben añadirse explicabilidad por feature, incertidumbre de métricas y evaluación de drift/calibración por segmento operativo.

Handoff vigente: `docs/M5_HANDOFF.md`.
