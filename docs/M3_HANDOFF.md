# ARGOS — Handoff M2 → M3

> **Origen:** M2 — Silver / Canonical Data Model  
> **Estado de origen:** ✅ CLOSED — 10/10 checks bloqueantes  
> **Destino:** M3 — Gold / Point-in-Time Analytical Layer  
> **Estado de destino:** ▶ IN PROGRESS

## Contrato de entrada

M3 parte de los 12 artefactos canónicos `m2-silver-v1`, manifests completos y cero issues Silver bloqueantes. Bronze no se reinterpreta desde los notebooks Gold.

## Semantic freeze adoptado

M3 V1 define:

```text
target = y_addition_180d
t0 = fecha_de_firma
horizon = 180 días
evento positivo = ADICION EN EL VALOR
ventana = (t0, t0 + 180d]
censura = ventana incompleta => label NULL
```

La decisión está documentada en `target-specs/y_addition_180d.md` y debe ser validada empíricamente por notebook 20.

## Regla central

Para cada observación `(contract_id, t0)`:

```text
feature_timestamp <= t0
```

Para históricos ARGOS adopta una política más estricta:

```text
history_timestamp < t0
```

## Deuda heredada que permanece explícita

- entity resolution bidder→supplier es parcial; no se fuerzan matches;
- `payments` y `sanctions` permanecen fuera de V1;
- `process_versions.parquet` no se interpreta como history SCD;
- `contracts_snapshot_state.parquet` queda fuera del model matrix V1;
- campos monetarios del snapshot contractual actual no se habilitan como features V1 hasta demostrar su semántica as-of-signing.

## Secuencia M3

```text
20_target_engineering.ipynb
21_temporal_split_design.ipynb
22_train_eda.ipynb
23_contract_features.ipynb
24_historical_features.ipynb
25_competition_relationship_features.ipynb
26_gold_point_in_time_audit.ipynb
27_m3_gate.ipynb
```

Modeling no está autorizado hasta que `27_m3_gate.ipynb` imprima `M3 ✅ CLOSED`.
