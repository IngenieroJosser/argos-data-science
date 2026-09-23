# ARGOS — M6 Runbook

> **Milestone:** M6 — Productionization & MLOps  
> **Estado:** ✅ CLOSED — 16/16 · `OPERATIONALLY_READY_PROMOTION_BLOCKED`  
> **Schema:** `m6-production-v1`  
> **Modelo heredado:** ARGOS V1 congelado (`hist_gradient_boosting + isotonic`)  
> **Modo inicial:** batch + shadow + human-in-the-loop

## Objetivo

M6 convierte los artefactos validados en M1–M5 en una operación reproducible, observable, auditable y reversible. No es una nueva fase de tuning y no usa TEST 2025 ni OOT 2026 para re-seleccionar el modelo.

El criterio técnico es:

```text
input batch inmutable
        ↓
data-contract preflight
        ↓
modelo/calibrador registrados por hash
        ↓
scoring batch idempotente
        ↓
ranking determinista
        ↓
monitoring + alert routing
        ↓
cola Top-K para revisión humana
        ↓
audit log + rollback/pause
```

## Secuencia obligatoria

```text
50_runtime_and_registry.ipynb
51_data_contracts_and_preflight.ipynb
52_batch_scoring_and_idempotency.ipynb
53_monitoring_execution.ipynb
54_human_review_and_audit.ipynb
55_shadow_and_rollback_drill.ipynb
56_operational_readiness.ipynb
57_m6_gate.ipynb
```

No ejecutar `57` como sustituto de los componentes anteriores: el gate consume evidencia persistida de `50–56`.

## Batch operacional de replay

Por defecto M6 usa:

```text
data/m5/fresh_oot_2026.parquet
```

únicamente como **operational replay**. Los labels presentes en ese archivo no entran al scoring ni se usan para tuning, selección o una nueva afirmación de performance. El objetivo es probar contratos, idempotencia, observabilidad, queueing, audit y rollback con una cohorte material real.

## Criterios de seguridad

- `allow_production_promotion = false` en `configs/production.toml`;
- `human_review_required = true`;
- ninguna transición de deployment admite `production`;
- output de scoring excluye target y columnas sensibles explícitas;
- alertas `high` bloquean promoción y pueden pausar un stage shadow;
- score y rank son evidencia del modelo, no decisiones humanas;
- audit log encadenado por SHA-256;
- ningún incidente se resuelve retuneando contra TEST 2025 u OOT 2026.

## Significado del cierre de M6

`M6 ✅ CLOSED` significa que la **infraestructura operacional** de ARGOS V1 pasó contratos de reproducibilidad, lineage, scoring, monitoring, audit, rollback y human review.

El deployment status se reporta por separado:

```text
SHADOW_READY
```

o, si el replay activa señales de alto drift:

```text
OPERATIONALLY_READY_PROMOTION_BLOCKED
```

Ambos estados preservan la conclusión negativa de M5 cuando corresponda. M6 no convierte una degradación real en un PASS artificial.

## Ejecución automatizada

```bash
uv run python pipelines/run_production_m6.py
```

Para otro batch inmutable:

```bash
uv run python pipelines/run_production_m6.py --shadow-input /ruta/batch.parquet
```

También existe CLI:

```bash
uv run argos-production preflight data/m5/fresh_oot_2026.parquet
uv run argos-production score data/m5/fresh_oot_2026.parquet
```


## Evidencia final de ejecución

```text
50 runtime + registry                 5/5 PASS
51 data contract + preflight          5/5 PASS
52 scoring + idempotency              4/4 PASS
53 executable monitoring              4/4 PASS
54 human review + audit               4/4 PASS
55 shadow + rollback                  4/4 PASS
56 operational readiness              6/6 PASS
57 M6 gate / closure reconciliation  16/16 PASS
```

Replay operacional:

```text
rows scored                 529,054
review fraction                1%
review queue rows            5,291
monitoring alerts               14
high alerts                       6
score PSI                  1.089164
promotion_blocked              true
```

La presencia de alertas `high` no invalida el cierre de M6. El criterio del milestone es que las señales sean detectadas, persistidas y aplicadas a la política de deployment. Por ello el status correcto es `OPERATIONALLY_READY_PROMOTION_BLOCKED`.

## Estado posterior al milestone

M6 queda congelado salvo bug documentado. El sistema puede continuar en shadow/human-review bajo el runbook operacional, pero cualquier cambio de modelo, features, calibración o thresholds de decisión debe abrir una nueva lineage y una nueva evaluación. TEST 2025 y OOT 2026 continúan consumidos para ARGOS V1.
