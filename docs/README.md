# Documentación de ARGOS

## Estado de milestones

```text
M1 — Bronze Data Understanding & Target Feasibility   ✅ CLOSED
M2 — Silver / Canonical Data Model                    ✅ CLOSED
M3 — Gold / Point-in-Time Analytical Layer            ✅ CLOSED
M4 — Modeling & Evaluation                            ✅ CLOSED
M5 — Advanced Data Science & Robustness               ▶ READY
```

La autoridad operativa de cada milestone es su gate persistido. Los documentos de inicio/readiness se conservan como evidencia histórica y no sustituyen las decisiones de cierre posteriores.

## Documentos autoritativos

| Documento | Rol |
|---|---|
| `problem-definition.md` | definición vigente del problema, decisión y restricciones metodológicas |
| `decisions/M1_GATE.md` | cierre computable de M1 |
| `decisions/M2_GATE.md` | cierre computable de M2 |
| `data-dictionary/silver_m2_catalog.md` | catálogo de los 12 artefactos Silver canónicos |
| `decisions/M3_GATE.md` | cierre computable de M3 |
| `target-specs/y_addition_180d.md` | semantic freeze validado del target V1 |
| `data-dictionary/gold_m3_catalog.md` | catálogo de los 7 artefactos Gold canónicos |
| `M4_HANDOFF.md` | contrato histórico M3→M4 que gobernó Modeling |
| `M4_RUNBOOK.md` | protocolo ejecutado de Modeling y aislamiento de TEST |
| `decisions/M4_GATE.md` | decisión computable de cierre de M4 — 14/14 |
| `decisions/M4_CLOSURE_REVIEW_2026-09-23.md` | revisión senior de validez, resultados y deuda transportada |
| `models/ARGOS_V1_MODEL_CARD.md` | ficha del modelo V1 finalmente evaluado |
| `M5_HANDOFF.md` | contrato de entrada a Advanced Data Science & Robustness |

## Evidencia histórica preservada

Se conservan los documentos de bootstrap/readiness de M3 y M4 (`M3_START`, `M3_CODE_READINESS`, `M4_START`, `M4_CODE_READINESS`) para trazabilidad. Sus estados fueron supersedidos por los gates correspondientes.

## Contrato analítico V1 cerrado

```text
Gold schema        = m3-gold-v1
Modeling schema    = m4-model-v1
target             = y_addition_180d
t0                 = fecha_de_firma
horizon            = 180 días
positive event     = ADICION EN EL VALOR
model matrix       = data/gold/ml/argos_v1.parquet
features           = 41 PIT-auditadas
selected model     = hist_gradient_boosting
calibration        = isotonic
TEST               = 2025, consumido una única vez por notebook 36
```

Resultado TEST V1:

```text
rows          1,050,857
positives        10,983
prevalence       1.0451%
PR-AUC           0.135250
ROC-AUC          0.872745
Brier            0.009638
ECE              0.002843
Lift@1%         25.274x
Recall@1%       25.2754%
Precision@1%    26.4155%
```

## Regla de precedencia y siguiente fase

`docs/decisions/M4_GATE.md` es la autoridad del cierre M4. La revisión posterior no cambia los artefactos del experimento; documenta sus limitaciones. M5 no puede utilizar TEST 2025 para seleccionar mejoras. Una nueva evaluación final requiere un holdout temporal posterior no usado durante desarrollo.
