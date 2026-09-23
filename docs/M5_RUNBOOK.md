# ARGOS — M5 Runbook

> **Milestone:** M5 — Advanced Data Science & Robustness  
> **Estado:** ▶ IN PROGRESS  
> **Entrada autoritativa:** `docs/M5_HANDOFF.md`  
> **Schema:** `m5-robustness-v1`

## 1. Objetivo

M5 fortalece la evidencia alrededor del **ARGOS V1 congelado**. No parte de cero y no convierte TEST 2025 nuevamente en un conjunto de selección.

La pregunta de M5 es:

> ¿El comportamiento predictivo, el ranking, la calibración y las explicaciones de ARGOS V1 se sostienen bajo protocolos temporales más exigentes y un nuevo holdout posterior, con lineage y monitoreo suficientes para una futura evaluación de producción?

M5 no autoriza producción automáticamente y no modifica silenciosamente el modelo seleccionado en M4.

## 2. Contratos congelados

```text
Gold schema       m3-gold-v1
Model schema      m4-model-v1
M5 schema         m5-robustness-v1
target            y_addition_180d
V1 model          hist_gradient_boosting
calibration       isotonic
TEST 2025         consumed historical benchmark
fresh OOT         eligible 2026 partial-year cohort
ranking tie-break calibrated_score DESC -> raw_score DESC -> contract_id ASC
```

## 3. Orden obligatorio

```text
40_temporal_backtesting.ipynb
41_explainability.ipynb
42_uncertainty_and_ranking_stability.ipynb
43_drift_and_calibration_monitoring.ipynb
44_feature_family_revalidation.ipynb
45_fresh_oot_2026.ipynb
46_preproduction_readiness.ipynb
47_m5_gate.ipynb
```

No ejecutar `45` antes de revisar que `40–44` estén aprobados. `45` consume el primer holdout post-M4 que no participó en selección.

## 4. Notebook 40 — Temporal backtesting

Rolling-origin sobre años de desarrollo `2021–2024` con la receta HGB congelada y un presupuesto uniforme. Se evalúan discriminación y ranking. 2025 queda excluido.

Salidas:

```text
reports/robustness/40_backtest_metrics.parquet
reports/robustness/40_backtest_ranking.parquet
reports/robustness/40_backtest_folds.parquet
reports/robustness/40_validation.parquet
artifacts/manifests/m5_temporal_backtesting.json
```

## 5. Notebook 41 — Explainability

Materializa:

- permutation importance global por feature;
- resumen por familia;
- sensibilidad local por sustitución de una feature hacia un valor de referencia.

La sensibilidad local describe dependencia predictiva, no causalidad.

## 6. Notebook 42 — Uncertainty y ranking

Usa calendar-week block bootstrap sobre VALIDATION H2 para persistir intervalos de confianza de métricas principales. También congela un desempate determinístico frente a plateaus de calibración isotónica.

## 7. Notebook 43 — Drift y calibración

Monitorea:

- PSI de features numéricas;
- total variation distance y categorías nuevas en features categóricas;
- drift de scores;
- calibración explícita en la cola superior del ranking.

TEST 2025 se usa aquí solo como benchmark histórico ya consumido, nunca para selección.

## 8. Notebook 44 — Feature-family revalidation

Compara en rolling folds, con mismo algoritmo, muestra y presupuesto:

```text
contract
contract + historical
all
```

La diferencia `all - contract_historical` cuantifica de manera explícita el valor incremental de competition features. El resultado es diagnóstico y no reemplaza automáticamente el modelo V1.

## 9. Notebook 45 — Fresh OOT 2026

Construye desde Gold los contratos de 2026 con horizonte completo de 180 días y los puntúa con el **modelo y calibrador exactos congelados en M4**.

El rango temporal real se deriva de observabilidad. Con el snapshot actual, el extremo superior esperado está alrededor de marzo de 2026; por ello el holdout es partial-year y tiene limitación estacional explícita.

Una vez consumido, este holdout también deja de ser virgen para futuros ciclos de selección.

## 10. Notebook 46 — Pre-production evidence

Genera:

```text
docs/models/ARGOS_V1_ROBUSTNESS_CARD.md
docs/monitoring/ARGOS_V1_MONITORING_SPEC.md
```

El monitoring spec congela thresholds de drift, score shift, calibración de cola, lift y missingness. `production_authorized=false` permanece explícito.

## 11. Notebook 47 — Gate

El gate exige:

- M4 previamente cerrado;
- 40–46 con checks bloqueantes aprobados;
- reportes y manifests completos;
- schema `m5-robustness-v1` consistente;
- TEST 2025 no reutilizado para selección;
- fresh OOT gobernado y sin reselección posterior;
- hashes del V1 intactos;
- robustness card y monitoring spec persistidos;
- producción no auto-autorizada.

Solo entonces puede persistirse `docs/decisions/M5_GATE.md` como CLOSED.

## 12. Pipeline

El pipeline incluye un freno deliberado:

```bash
uv run python pipelines/run_robustness_m5.py
```

ejecuta `40–44` y se detiene **antes** de consumir 2026.

Después de revisar esa evidencia, el consumo explícito requiere:

```bash
uv run python pipelines/run_robustness_m5.py --consume-fresh-oot
```

Esto evita que un comando rutinario consuma accidentalmente el holdout final.

## 13. Interpretación

M5 es una fase de robustez y gobernanza del modelo V1. Complejidad algorítmica adicional —CatBoost/LightGBM/XGBoost, NLP, supervivencia, grafos o anomalías— no se promueve por defecto. Cualquier experimento avanzado posterior debe respetar los holdouts ya consumidos y demostrar valor incremental bajo un protocolo temporal versionado.
