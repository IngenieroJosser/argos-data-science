# Target specification — `y_addition_180d`

> **Estado:** FROZEN & VALIDATED — M3 V1  
> **Gold schema:** `m3-gold-v1`  
> **Fuente de eventos:** `data/silver/addition_events.parquet`  
> **Validación:** `20_target_engineering.ipynb` — 13/13 checks bloqueantes

## Pregunta analítica

Dada la información disponible al momento de firma de un contrato, ¿se registrará una **ADICION EN EL VALOR** durante los siguientes 180 días?

## Unidad de análisis

Una fila por `contract_id` evaluado en `t0`.

## Prediction time

```text
t0 = contracts.fecha_de_firma
```

M3 observó 5,640,278 contratos con `t0` válido sobre una población contractual de 6,066,730.

## Evento positivo V1

Solo se incluye el tipo canónico:

```text
ADICION EN EL VALOR
```

Otros tipos preservados en Silver —por ejemplo `MODIFICACION GENERAL`, `CONCLUSION`, `CESION`, `SUSPENSION` o valores no definidos— **no convierten el label V1 en positivo**.

En la fuente Silver canónica se observaron 240,204 eventos `ADICION EN EL VALOR` asociados a 198,072 contratos distintos antes de aplicar la ventana específica de cada observación.

## Ventana

Un evento califica únicamente cuando:

```text
t0 < event_at <= t0 + 180 días
```

Los eventos en o antes de `t0` forman parte del historial observable y nunca del outcome futuro de esa fila.

## Label cutoff

El cutoff queda fijado empíricamente por el máximo `event_at` parsable observado en la fuente Silver canónica:

```text
label_cutoff = 2026-09-09
```

El cutoff representa el límite de observación de outcomes del snapshot utilizado para M3 V1.

## Positivo

```text
y_addition_180d = 1
```

si existe al menos un evento `ADICION EN EL VALOR` dentro de `(t0, t0 + 180d]`.

## Negativo

```text
y_addition_180d = 0
```

solo si el horizonte completo de 180 días es observable y no existe un evento calificante en la ventana.

## Censoring

Si:

```text
t0 + 180 días > label_cutoff
```

el contrato es right-censored y:

```text
y_addition_180d = NULL
```

Nunca se convierte automáticamente en negativo.

Estado empírico de la población:

| estado | contratos |
|---|---:|
| eligible | 5,312,182 |
| missing_t0 | 426,452 |
| right_censored | 301,370 |
| t0_after_label_cutoff | 26,726 |

Entre los contratos elegibles se observaron **85,864 positivos**, para una prevalencia global de aproximadamente **1.6164%**.

## Deduplicación

Gold consume `addition_events.parquet`, cuyo grain Silver ya es un evento canónico por `(contract_id, event_at, event_type)` con duplicados fuente contabilizados mediante lineage.

## Leakage rule

Ninguna feature puede utilizar información producida después de `t0`. Los campos del snapshot contractual actual identificados como mutables/post-`t0` permanecen excluidos del model matrix V1.

## Invariantes validados

`20_target_engineering.ipynb` confirmó, entre otros:

```text
target grain único                         PASS
scope del evento explícito                 PASS
solo eventos futuros                       PASS
horizonte exacto de 180 días               PASS
censoring correcto                         PASS
labels binarios o NULL                     PASS
consistencia label ↔ evento                PASS
positivos posteriores al cutoff            0
target population suficiente               PASS
prevalencia dentro del sanity range        PASS
```

Cualquier modificación de `t0`, horizonte, scope del evento, cutoff o regla de censura crea una nueva versión del target y requiere reejecutar los gates Gold afectados.
