# Documentación de ARGOS

## Estado de milestones

```text
M1 — Bronze Data Understanding & Target Feasibility   ✅ CLOSED
M2 — Silver / Canonical Data Model                    ✅ CLOSED
M3 — Gold / Point-in-Time Analytical Layer            ✅ CLOSED
M4 — Modeling & Evaluation                            ▶ READY
```

La autoridad operativa de cada milestone es su gate persistido. Los documentos de inicio y readiness se conservan como evidencia histórica y no deben interpretarse como el estado actual del proyecto.

## Documentos autoritativos

| Documento | Rol |
|---|---|
| `problem-definition.md` | definición vigente del problema, decisión y restricciones metodológicas |
| `M1_RUNBOOK.md` | ejecución y cierre de Bronze/M1 |
| `decisions/M1_GATE.md` | decisión computable de cierre de M1 |
| `M2_RUNBOOK.md` | arquitectura, ejecución y cierre de Silver/M2 |
| `decisions/M2_GATE.md` | decisión computable de cierre de M2 |
| `data-dictionary/silver_m2_catalog.md` | catálogo de los 12 artefactos Silver canónicos |
| `M3_HANDOFF.md` | contrato histórico de entrada M2→M3 |
| `M3_RUNBOOK.md` | ejecución y cierre de Gold/M3 |
| `decisions/M3_TEMPORAL_SPLIT_FREEZE.md` | periodos train/validation/test congelados |
| `target-specs/y_addition_180d.md` | semantic freeze validado del target V1 |
| `data-dictionary/gold_m3_catalog.md` | catálogo de los 7 artefactos Gold canónicos |
| `decisions/M3_GATE.md` | decisión computable de cierre de M3 |
| `decisions/M3_CLOSURE_REVIEW_2026-09-23.md` | revisión de cierre y riesgos transportados a Modeling |
| `M4_HANDOFF.md` | contrato de entrada Gold→Modeling |

## Evidencia histórica preservada

Los siguientes documentos describen decisiones tomadas antes del cierre de M3 y se conservan sin reescribir su contexto temporal:

- `decisions/M3_START_2026-09-23.md`;
- `decisions/M3_CODE_READINESS_2026-09-23.md`.

## Regla de precedencia

Los gates y decisiones de cierre más recientes prevalecen sobre notas históricas de bootstrap o readiness. Las decisiones antiguas se conservan por trazabilidad; no se reescriben para aparentar que el conocimiento actual existía en el pasado.

## Estado del contrato analítico V1

M3 dejó congelados y auditados:

```text
Gold schema      = m3-gold-v1
target           = y_addition_180d
t0               = fecha_de_firma
horizon          = 180 días
positive event   = ADICION EN EL VALOR
window           = (t0, t0 + 180d]
train            = 2015-06-11 .. 2023-12-31
validation       = 2024-01-01 .. 2024-12-31
test             = 2025-01-01 .. 2025-12-31
model matrix     = data/gold/ml/argos_v1.parquet
features         = 41 auditadas
```

M4 debe consumir este contrato sin rediseñar target, split o features utilizando el conjunto TEST.
