# Target specification — `y_addition_180d`

> **Estado:** CANDIDATE — semantic freeze pendiente en M3  
> **Fuente de eventos:** `data/silver/addition_events.parquet` (`m2-silver-v1`)

## Analytical question

Given information available at contract prediction time `t0`, does the contract experience at least one event from the dedicated SECOP II **Adiciones** source during the next 180 days?

## Unit

One label per unique `contract_id` at `t0`.

## Candidate `t0`

`contracts.fecha_de_firma`.

The field is accepted only after the M1 gate confirms minimum raw coverage, parse success and calendar plausibility. Parsing uses the explicit SECOP timestamp policy in `argos.common.sql.timestamp_expr`.

## Event identity

Bronze Adiciones contains repeated rows. Feasibility labeling therefore uses distinct:

```text
(contract_id, event_at, event_type)
```

before calculating the first post-`t0` event. Source duplicates cannot create additional positives.

## Event scope

For M1/M2 feasibility, every parsable row in the dedicated Adiciones source is included. `Tipo` is retained in the deduplication key. This is explicitly a **feasibility scope**, not the final semantic freeze of the modeling target: the observed source contains several event types beyond literal value additions. Before Gold target/model training, the project must either (a) justify the all-row event interpretation and rename the target accordingly, or (b) explicitly configure the subset of `Tipo` values that represents the outcome of interest and revise this specification.

## Positive

A contract is positive when at least one deduplicated included event satisfies:

```text
t0 < event_at <= t0 + 180 days
```

Events at or before `t0` are diagnostics and do not count as future positives.

## Negative

A contract is negative only when the full 180-day horizon is observable before the label cutoff and no qualifying event occurs within that horizon.

## Censoring

If:

```text
t0 + 180 days > label_cutoff
```

the contract is right-censored for this horizon and is not labeled negative.

## Label cutoff

By default, the latest parsable timestamp among included Adiciones events. This avoids pretending that the source observes outcomes beyond its demonstrated event coverage.

## Leakage rule

No field whose value is generated or updated after `t0` may be used as a model feature. Current-state contract fields such as paid/factured values, added days, liquidation fields, current contract state and later updates remain excluded unless a point-in-time reconstruction proves their availability at `t0`.
