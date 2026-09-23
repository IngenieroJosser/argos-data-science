# Documentación de ARGOS

## Estado de milestones

```text
M1 — Bronze Data Understanding & Target Feasibility   ✅ CLOSED
M2 — Silver / Canonical Data Model                    ✅ CLOSED
M3 — Gold / Point-in-Time Analytical Layer            ▶ READY
```

## Documentos autoritativos

| Documento | Rol |
|---|---|
| `problem-definition.md` | definición del problema, decisión y restricciones metodológicas |
| `M1_RUNBOOK.md` | ejecución y cierre de Bronze/M1 |
| `decisions/M1_GATE.md` | decisión computable de cierre de M1 |
| `M2_RUNBOOK.md` | arquitectura, ejecución y estado final de Silver/M2 |
| `decisions/M2_GATE.md` | decisión computable de cierre de M2 |
| `decisions/M2_CLOSURE_REVIEW_2026-09-23.md` | revisión de cierre y autorización de transición |
| `data-dictionary/silver_m2_catalog.md` | catálogo de los 12 artefactos Silver canónicos |
| `M3_HANDOFF.md` | contrato de entrada, deudas y reglas para Gold/M3 |
| `target-specs/y_addition_180d.md` | especificación candidata del target; semantic freeze pendiente en M3 |

## Regla de precedencia

Cuando una nota histórica o documento de bootstrap contradiga el estado actual, prevalecen los artefactos de gate y los documentos de handoff más recientes. Las decisiones antiguas se conservan por trazabilidad; no se reescriben para aparentar que el conocimiento actual existía en el pasado.
