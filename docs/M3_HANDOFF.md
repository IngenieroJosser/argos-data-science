# ARGOS — Handoff M2 → M3

> **Origen:** M2 — Silver / Canonical Data Model  
> **Estado de origen:** ✅ CLOSED — 10/10 checks bloqueantes  
> **Destino:** M3 — Gold / Point-in-Time Analytical Layer  
> **Estado actual del destino:** ✅ CLOSED — 13/13 checks bloqueantes  
> **Documento histórico:** contrato de entrada utilizado para construir M3

## Contrato de entrada

M3 partió de los 12 artefactos canónicos `m2-silver-v1`, manifests completos y cero issues Silver bloqueantes. Bronze no se reinterpretó desde los notebooks Gold.

## Semantic freeze adoptado

M3 V1 definió y validó:

```text
target = y_addition_180d
t0 = fecha_de_firma
horizon = 180 días
evento positivo = ADICION EN EL VALOR
ventana = (t0, t0 + 180d]
censura = ventana incompleta => label NULL
```

La decisión autoritativa está documentada en `target-specs/y_addition_180d.md` y fue validada empíricamente por `20_target_engineering.ipynb`.

## Regla central

Para cada observación `(contract_id, t0)`:

```text
feature_timestamp <= t0
```

Para históricos ARGOS adoptó una política más estricta:

```text
history_timestamp < t0
```

## Deuda heredada que permaneció explícita

- entity resolution bidder→supplier es parcial; no se forzaron matches;
- `payments` y `sanctions` permanecieron fuera de V1;
- `process_versions.parquet` no se interpretó como un historial SCD completo;
- `contracts_snapshot_state.parquet` permaneció fuera del feature matrix V1;
- todo uso de datos relacionales exigió evidencia temporal disponible en `t0`.

## Secuencia ejecutada

```text
20_target_engineering.ipynb                  ✅ PASS — 13/13
21_temporal_split_design.ipynb               ✅ PASS — 7/7
22_train_eda.ipynb                           ✅ PASS — 3/3
23_contract_features.ipynb                   ✅ PASS — 4/4
24_historical_features.ipynb                 ✅ PASS — 3/3
25_competition_relationship_features.ipynb   ✅ PASS — 3/3
26_gold_point_in_time_audit.ipynb            ✅ PASS — 8/8
27_m3_gate.ipynb                             ✅ CLOSED — 13/13
```

## Resultado del handoff

El contrato de entrada M2→M3 fue satisfecho. M3 materializó una capa Gold reproducible y auditada y quedó formalmente cerrado por `docs/decisions/M3_GATE.md`.

La transición vigente ya no es M2→M3. El contrato activo es:

```text
docs/M4_HANDOFF.md
```
