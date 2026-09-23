# Target specification — `y_addition_180d`

> **Estado:** FROZEN — M3 V1  
> **Gold schema:** `m3-gold-v1`  
> **Fuente de eventos:** `data/silver/addition_events.parquet`

## Pregunta analítica

Dada la información disponible al momento de firma de un contrato, ¿se registrará una **ADICION EN EL VALOR** durante los siguientes 180 días?

## Unidad de análisis

Una fila por `contract_id` evaluado en `t0`.

## Prediction time

```text
t0 = contracts.fecha_de_firma
```

## Evento positivo V1

Solo se incluye el tipo canónico:

```text
ADICION EN EL VALOR
```

Otros tipos preservados en Silver —por ejemplo `MODIFICACION GENERAL`, `CONCLUSION`, `CESION`, `SUSPENSION` o valores no definidos— **no convierten el label V1 en positivo**.

## Ventana

Un evento califica únicamente cuando:

```text
t0 < event_at <= t0 + 180 días
```

Los eventos en o antes de `t0` forman parte del historial observable y nunca del outcome futuro de esa fila.

## Label cutoff

Se utiliza el máximo `event_at` parsable observado en la fuente Silver canónica de eventos. El cutoff representa el límite empírico de observación de outcomes del snapshot disponible.

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

## Deduplicación

Gold consume `addition_events.parquet`, cuyo grain Silver ya es un evento canónico por `(contract_id, event_at, event_type)` con duplicados fuente contabilizados mediante lineage.

## Leakage rule

Ninguna feature puede utilizar información producida después de `t0`. Los campos del snapshot contractual actual identificados como mutables/post-`t0` permanecen excluidos del model matrix V1.
