# ARGOS — Handoff M5 → M6

> Este handoff fue aceptado y consumido por M6. El milestone está cerrado; la operación vigente está gobernada por `M6_RUNBOOK.md`, `configs/production.toml` y `docs/operations/`.

> **Origen:** M5 — Advanced Data Science & Robustness  
> **Estado de origen:** ✅ CLOSED — 16/16 checks bloqueantes  
> **Destino:** M6 — Productionization & MLOps  
> **Estado de destino:** ✅ CLOSED — 16/16 · `OPERATIONALLY_READY_PROMOTION_BLOCKED`  
> **Sistema de referencia:** ARGOS V1 congelado (`hist_gradient_boosting + isotonic`)

## 1. Propósito

M6 no es otra ronda de tuning. Su objetivo es convertir la evidencia y los artefactos de ARGOS V1 en una operación reproducible, observable, reversible y auditable.

La pregunta central es:

> ¿Puede ARGOS ejecutar scoring y priorización de forma confiable en un entorno operacional, con contratos de datos/modelo, monitoreo, rollback y revisión humana?

## 2. Producción vs. autonomía

**Productionization pertenece a M6.** Sin embargo, autonomía decisional no es un objetivo del roadmap.

ARGOS puede automatizar:

```text
ingestión → validación → feature pipeline → scoring → ranking → monitoreo → cola de revisión
```

pero la decisión final permanece:

```text
cola priorizada → analista/revisor humano → acción posterior según proceso institucional
```

No se autoriza uso autónomo para sanciones, elegibilidad, acusaciones de corrupción/fraude o decisiones legales.

## 3. Contratos congelados de entrada

```text
Gold schema       m3-gold-v1
Model schema      m4-model-v1
Robustness schema m5-robustness-v1
target            y_addition_180d
model             hist_gradient_boosting
calibration       isotonic
ranking           calibrated DESC -> raw DESC -> contract_id ASC
TEST 2025         consumed
OOT 2026          consumed
```

## 4. Evidencia que M6 debe heredar

```text
docs/decisions/M5_GATE.md
docs/decisions/M5_CLOSURE_REVIEW_2026-09-23.md
docs/models/ARGOS_V1_MODEL_CARD.md
docs/models/ARGOS_V1_ROBUSTNESS_CARD.md
docs/monitoring/ARGOS_V1_MONITORING_SPEC.md
artifacts/manifests/m5_*.json
```

## 5. Requisitos mínimos de M6

M6 debe cubrir, como mínimo:

- packaging/runtime reproducible y compatible con el modelo serializado;
- batch scoring idempotente y, solo si existe necesidad real, contrato de serving online;
- model/artifact registry con versionado y promotion policy;
- data contracts y validaciones pre-score;
- observabilidad de pipelines y modelo;
- implementación ejecutable de thresholds de M5;
- audit logging de dataset/model/version/score/run;
- CI/CD con pruebas de datos, código y artefactos;
- rollback/pause seguro;
- shadow o canary validation antes de promoción;
- control de acceso y manejo de datos sensibles;
- workflow human-in-the-loop;
- política explícita de retraining y evaluación con nuevos holdouts.

## 6. Deuda que M6 no puede ignorar

El fresh OOT 2026 mostró degradación respecto a TEST 2025. M6 debe tratarla como requisito de monitoreo y criterio de pausa/promoción, no esconderla mediante retuning sobre el mismo OOT.

La cohorte OOT es parcial de año. Antes de cualquier afirmación de estabilidad anual se requerirá evidencia temporal adicional.

## 7. Criterio de éxito

M6 no se cierra por levantar una API. Debe demostrar que el sistema puede operar de forma reproducible y segura, que los datos/modelos son trazables, que las alertas de monitoreo accionan respuestas concretas y que existe un procedimiento verificable de rollback y revisión humana.

## 8. Principio

> Automatizar el pipeline no significa automatizar el juicio. ARGOS prioriza evidencia para revisión; no sustituye la decisión humana.
