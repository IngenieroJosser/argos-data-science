# Documentación de ARGOS

## Estado de milestones

```text
M1 — Bronze Data Understanding & Target Feasibility   ✅ CLOSED
M2 — Silver / Canonical Data Model                    ✅ CLOSED
M3 — Gold / Point-in-Time Analytical Layer            ▶ IN PROGRESS
```

## Documentos autoritativos

| Documento | Rol |
|---|---|
| `problem-definition.md` | definición del problema, decisión y restricciones metodológicas |
| `M1_RUNBOOK.md` | ejecución y cierre de Bronze/M1 |
| `decisions/M1_GATE.md` | decisión computable de cierre de M1 |
| `M2_RUNBOOK.md` | arquitectura, ejecución y estado final de Silver/M2 |
| `decisions/M2_GATE.md` | decisión computable de cierre de M2 |
| `data-dictionary/silver_m2_catalog.md` | catálogo de los 12 artefactos Silver canónicos |
| `M3_HANDOFF.md` | contrato de entrada desde M2 |
| `M3_RUNBOOK.md` | orden, outputs y reglas operativas de Gold/M3 |
| `decisions/M3_START_2026-09-23.md` | decisión de inicio y alcance de M3 V1 |
| `decisions/M3_TEMPORAL_SPLIT_FREEZE.md` | periodos train/validation/test congelados |
| `decisions/M3_CODE_READINESS_2026-09-23.md` | revisión estática de preparación del código M3 antes de ejecución empírica |
| `target-specs/y_addition_180d.md` | semantic freeze del target V1 |
| `data-dictionary/gold_m3_catalog.md` | catálogo esperado de artefactos Gold |

## Regla de precedencia

Los artefactos de gate y decisiones más recientes prevalecen sobre notas históricas de bootstrap. Las decisiones antiguas se conservan por trazabilidad; no se reescriben para aparentar que el conocimiento actual existía en el pasado.
