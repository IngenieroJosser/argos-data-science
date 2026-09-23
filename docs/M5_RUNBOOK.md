# ARGOS — M5 Runbook

> **Milestone:** M5 — Advanced Data Science & Robustness  
> **Estado:** ✅ CLOSED — 16/16 checks bloqueantes  
> **Schema:** `m5-robustness-v1`  
> **Autoridad de cierre:** `docs/decisions/M5_GATE.md`

## 1. Objetivo y resultado

M5 fortaleció la evidencia alrededor del **ARGOS V1 congelado** sin reabrir TEST 2025 para selección. El milestone evaluó estabilidad temporal, explicabilidad, incertidumbre, drift, calibración, utilidad incremental de familias y un nuevo holdout out-of-time de 2026.

Resultado formal:

```text
M5 ✅ CLOSED
Blocking checks: 16/16
```

El cierre significa que la evidencia de robustez prevista por M5 fue materializada y auditada. **No significa autorización automática de producción.**

## 2. Contratos congelados

```text
Gold schema       m3-gold-v1
Model schema      m4-model-v1
M5 schema         m5-robustness-v1
target            y_addition_180d
V1 model          hist_gradient_boosting
calibration       isotonic
TEST 2025         consumed historical benchmark
fresh OOT 2026    consumed final M5 holdout
ranking tie-break calibrated_score DESC -> raw_score DESC -> contract_id ASC
```

TEST 2025 y fresh OOT 2026 ya no pueden utilizarse como holdouts vírgenes para seleccionar una futura versión del modelo.

## 3. Ejecución cerrada

| Notebook | Propósito | Checks bloqueantes | Estado |
|---|---|---:|---|
| `40_temporal_backtesting.ipynb` | rolling-origin 2021–2024 | 4/4 | PASS |
| `41_explainability.ipynb` | permutation importance + sensibilidad local | 5/5 | PASS |
| `42_uncertainty_and_ranking_stability.ipynb` | bootstrap temporal + desempate determinista | 5/5 | PASS |
| `43_drift_and_calibration_monitoring.ipynb` | drift y calibración de cola | 4/4 | PASS |
| `44_feature_family_revalidation.ipynb` | revalidación justa de familias | 4/4 | PASS |
| `45_fresh_oot_2026.ipynb` | evaluación final OOT 2026 | 7/7 | PASS |
| `46_preproduction_readiness.ipynb` | monitoring/robustness evidence | 7/7 | PASS |
| `47_m5_gate.ipynb` | gate formal | 16/16 | CLOSED |

## 4. Temporal backtesting

Rolling-origin sobre 2021–2024, sin usar TEST 2025 como criterio de selección:

| Periodo | PR-AUC | ROC-AUC | Prevalencia |
|---|---:|---:|---:|
| 2021 | 0.048415 | 0.752242 | 1.0333% |
| 2022 | 0.072170 | 0.786582 | 1.3073% |
| 2023 | 0.094661 | 0.813049 | 1.8128% |
| 2024 | 0.060340 | 0.834935 | 0.9656% |

La variabilidad confirma que el desempeño es temporalmente dependiente y debe monitorearse por cohorte.

## 5. Explainability

Se materializaron permutation importance global, importancia por familia y sensibilidad local. Las señales globales más importantes incluyen `codigo_de_categoria_principal`, `t0_month`, `prior_entity_contract_count`, `justificacion_modalidad_de_contratacion` y `prior_supplier_entity_addition_event_count`.

Estas explicaciones representan **sensibilidad predictiva**, no causalidad.

## 6. Incertidumbre y ranking

Se ejecutó calendar-week block bootstrap con 200 réplicas y nivel de confianza 95%. Para el operating point del 1%, Lift@K fue 17.929 con intervalo `[12.130, 22.940]` en el protocolo de desarrollo.

El ranking operacional queda congelado como:

```text
1. calibrated_score DESC
2. raw_score DESC
3. contract_id ASC
```

Esto elimina dependencia accidental del orden físico frente a plateaus del calibrador isotónico.

## 7. Drift y calibración

M5 encontró **3 pares feature-period con drift alto**. El hallazgo no invalida automáticamente el modelo, pero se convierte en requisito de monitoreo. El contrato operativo persiste umbrales para PSI, TVD categórico, score shift, prevalencia, calibración de cola, Lift@K y missingness.

## 8. Feature-family revalidation

Se compararon de forma homogénea:

```text
contract
contract + historical
all
```

La evidencia no justifica asumir que la familia completa domina de manera estable. Las features de competencia permanecen útiles como hipótesis analítica, pero su valor incremental debe seguir siendo demostrado antes de promover cambios de modelo.

## 9. Fresh OOT 2026

La cohorte final se derivó por observabilidad completa del horizonte de 180 días:

```text
cohort_start  2026-01-01
cohort_end    2026-03-13
rows          529,054
positives       7,255
prevalence      1.3713%
PR-AUC          0.053274
ROC-AUC         0.744544
Brier           0.013238
ECE             0.003093
Precision@1%    8.5806%
Recall@1%       6.2578%
Lift@1%         6.257x
```

El OOT confirma señal por encima de revisión aleatoria, pero evidencia degradación material frente al TEST 2025. Además, es un holdout **partial-year** y no representa estacionalmente un año calendario completo.

## 10. Evidencia preproducción

M5 generó:

```text
docs/models/ARGOS_V1_ROBUSTNESS_CARD.md
docs/monitoring/ARGOS_V1_MONITORING_SPEC.md
```

El manifest de preproducción conserva `production_authorized=false`. Esto es correcto: M5 valida evidencia; la operacionalización pertenece a M6.

## 11. Gate y gobernanza

`47_m5_gate.ipynb` verificó, entre otros:

- M4 previamente cerrado;
- todos los checks bloqueantes `40–46`;
- 14 reportes M5 obligatorios y manifests completos;
- consistencia `m5-robustness-v1`;
- TEST 2025 no reutilizado para selección;
- fresh OOT 2026 consumido bajo V1 congelado y sin reselección;
- hashes del V1 intactos;
- robustness card y monitoring spec persistidos;
- ausencia de autorización automática de producción.

## 12. Qué queda congelado

A partir del cierre:

```text
M5 notebooks/results      frozen salvo bug documentado
TEST 2025                 consumed
fresh OOT 2026            consumed
ARGOS V1                  historical benchmark
monitoring contract       input obligatorio para M6
```

Una futura V2 que use lo aprendido en M5 necesita un nuevo holdout temporal posterior para sostener una nueva afirmación final de generalización.

## 13. Siguiente milestone

M6 es **Productionization & MLOps**. Su objetivo es operacionalizar scoring y priorización con observabilidad, reproducibilidad, rollback, seguridad y revisión humana. No persigue decisiones legales autónomas. Véase `docs/M6_HANDOFF.md`.
