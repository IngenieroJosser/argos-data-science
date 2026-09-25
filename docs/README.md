# Documentación de ARGOS

## Estado de milestones

```text
M1 — Bronze Data Understanding & Target Feasibility   ✅ CLOSED
M2 — Silver / Canonical Data Model                    ✅ CLOSED
M3 — Gold / Point-in-Time Analytical Layer            ✅ CLOSED
M4 — Modeling & Evaluation                            ✅ CLOSED
M5 — Advanced Data Science & Robustness               ✅ CLOSED — 16/16
M6 — Productionization & MLOps                        ✅ CLOSED — 16/16
M7 — Prospective Validation                           ◐ ACTIVE — future evidence required
M8 — Advanced Intelligence & Survival                 ✅ CLOSED — RESEARCH_COMPLETE_NO_PROMOTION
M9 — Plataforma Analítica / Frontend                  ▶ NEXT — product development
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
| `M5_HANDOFF.md` | handoff histórico M4→M5, ya consumido |
| `M5_RUNBOOK.md` | protocolo ejecutado y evidencia de cierre de robustez M5 |
| `decisions/M5_START_2026-09-23.md` | decisión formal de inicio de M5 |
| `decisions/M5_EVALUATION_GOVERNANCE_2026-09-23.md` | política de TEST 2025 consumido y fresh OOT 2026 reservado |
| `data-dictionary/m5_robustness_catalog.md` | catálogo materializado de artefactos M5 |
| `decisions/M5_GATE.md` | decisión computable de cierre M5 — 16/16 |
| `decisions/M5_CLOSURE_REVIEW_2026-09-23.md` | revisión senior del cierre, limitaciones y deuda transportada |
| `models/ARGOS_V1_ROBUSTNESS_CARD.md` | evidencia empírica de robustez del V1 congelado |
| `monitoring/ARGOS_V1_MONITORING_SPEC.md` | contrato de monitoreo que debe operacionalizar M6 |
| `M6_HANDOFF.md` | handoff histórico M5→M6, ya consumido |
| `M6_RUNBOOK.md` | protocolo ejecutado de Productionization & MLOps |
| `decisions/M6_START_2026-09-23.md` | decisión formal de inicio de M6 |
| `decisions/M6_CODE_READINESS_2026-09-23.md` | alcance y controles implementados antes de ejecutar 50–57 |
| `data-dictionary/m6_production_catalog.md` | catálogo de registry, scoring, monitoring, audit y review queue |
| `decisions/M6_GATE.md` | decisión formal reconciliada de cierre M6 — 16/16 |
| `decisions/M6_CLOSURE_REVIEW_2026-09-23.md` | revisión senior, reconciliación de evidencia y estado operacional final |
| `operations/ARGOS_V1_OPERATIONAL_RUNBOOK.md` | runbook operativo para shadow/human-review |
| `POST_M6_OPERATIONS.md` | reglas posteriores al cierre: monitoreo prospectivo y gobernanza de nueva evidencia |
| `decisions/M8_GATE.md` | cierre formal de M8 y decisión `RESEARCH_COMPLETE_NO_PROMOTION` |
| `M9_FRONTEND_PLAN.md` | contrato de producto, arquitectura UX y criterios de aceptación del frontend |
| `decisions/M9_START_2026-09-25.md` | decisión formal de inicio de M9 sin alterar M7/M8 |

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

## Regla de precedencia y estado posterior

`docs/decisions/M6_GATE.md` es la decisión vigente del cierre M6 y `docs/decisions/M6_CLOSURE_REVIEW_2026-09-23.md` documenta la reconciliación senior de la evidencia final. La decisión previa `M6 ❌ OPEN` se conserva como artefacto histórico pre-reconciliación. TEST 2025 y OOT 2026 permanecen consumidos para ARGOS V1.

Ese estado posterior ya fue formalizado como `M7 — Prospective Validation & Operational Evaluation`. `POST_M6_OPERATIONS.md` conserva las reglas de shadow/human-review que M7 hereda sin modificar el lineage congelado de M6.

## M6 cerrado / operación shadow controlada

M5 cerró con **16/16 checks bloqueantes** y M6 cerró la operacionalización controlada con **16/16 condiciones del gate satisfechas**. ARGOS V1 dispone de runtime/registry reproducible, data contract, scoring batch idempotente, monitoring ejecutable, audit hash-chain, rollback y cola de revisión humana.

El status final es `OPERATIONALLY_READY_PROMOTION_BLOCKED`: la infraestructura está lista para operación shadow/human-review, pero las 6 alertas `high` del replay mantienen `promotion_blocked=true`. Esto no es un fallo del milestone; es el mecanismo de gobernanza funcionando como fue diseñado. No existe autorización de promoción automática ni de decisiones jurídicas autónomas.



## M7 — Prospective Validation & Operational Evaluation

- `M7_RUNBOOK.md` — protocolo de ejecución y requisitos de evidencia.
- `M7_HANDOFF.md` — handoff congelado desde M6.
- `decisions/M7_START_2026-09-23.md` — decisión formal de inicio.
- `decisions/M7_GATE.md` — estado vigente del gate; permanece abierto hasta madurar evidencia prospectiva.
- `data-dictionary/m7_prospective_catalog.md` — contrato de artefactos M7.


## M8 — Advanced Intelligence & Survival

- `M8_RUNBOOK.md` — ejecución 70–77 y metodología NLP/graph/anomaly/survival.
- `M8_HANDOFF.md` — contrato de salida del último milestone técnico.
- `decisions/M8_START_2026-09-23.md` — alcance congelado de M8 v2.
- `decisions/M8_CODE_READINESS_2026-09-23.md` — estado de implementación previo a la corrida empírica.
- `data-dictionary/m8_advanced_intelligence_catalog.md` — catálogo de features y survival outcomes.
- `PROJECT_COMPLETION_AND_TESTING.md` — procedimiento de verificación integral.

M8 cerró formalmente con `RESEARCH_COMPLETE_NO_PROMOTION`: la investigación avanzada está completa y ninguna familia experimental fue promovida. M7 permanece independiente y activo hasta disponer de cohorts futuros maduros.


## M9 — Plataforma Analítica / Frontend

- `M9_FRONTEND_PLAN.md` — visión de producto, arquitectura, pantallas, contrato de presentación y criterios de aceptación.
- `decisions/M9_START_2026-09-25.md` — inicio formal de la fase de frontend.

M9 es una capa de producto **read-only, batch-first y human-in-the-loop** sobre la evidencia gobernada. No reentrena modelos, no reabre TEST/OOT y no modifica el protocolo prospectivo M7.
