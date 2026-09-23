# ARGOS — Handoff M2 → M3

> **Origen:** M2 — Silver / Canonical Data Model  
> **Estado de origen:** ✅ CLOSED — 10/10 checks bloqueantes  
> **Destino:** M3 — Gold / Point-in-Time Analytical Layer  
> **Estado de destino:** ▶ READY

## 1. Contrato de entrada a M3

M3 puede comenzar porque:

- M1 está cerrado con 19/19 checks bloqueantes;
- M2 está cerrado con 10/10 checks bloqueantes;
- existen 12 artefactos Silver canónicos bajo schema `m2-silver-v1`;
- los manifests de lineage están persistidos;
- la validación cruzada de Silver no tiene issues bloqueantes;
- Contracts, Processes, Suppliers, Bidders y Addition Events tienen grain explícito;
- la ambigüedad de entity resolution está representada, no ocultada.

## 2. Lo que M2 NO autoriza

El cierre de Silver no implica que:

- todas las columnas sean features válidas;
- `processes.parquet` represente el estado histórico correcto para cualquier contrato;
- los campos de `contracts_snapshot_state.parquet` puedan usarse en ML;
- una entidad bidder no resuelta pueda imputarse a un supplier;
- todos los eventos de `addition_events.parquet` pertenezcan al target final.

M3 debe demostrar de nuevo disponibilidad temporal `<= t0`.

## 3. Primera decisión de M3: semantic freeze del target

Antes de construir el dataset Gold definitivo, `20_target_engineering.ipynb` debe congelar como mínimo:

```text
target_name
prediction_timestamp / t0
horizon_days
included_event_types
excluded_event_types
eligibility_rule
censoring_rule
positive_rule
negative_rule
label_cutoff
```

La especificación actual `docs/target-specs/y_addition_180d.md` es candidata y todavía conserva la deuda semántica heredada de M1/M2.

## 4. Secuencia prevista de M3

```text
20_target_engineering.ipynb
21_temporal_split_design.ipynb
22_train_eda.ipynb
23_contract_features.ipynb
24_historical_features.ipynb
25_competition_relationship_features.ipynb
26_gold_point_in_time_audit.ipynb
```

Un gate formal de M3 debe añadirse antes de autorizar Modeling.

## 5. Reglas de point-in-time

Para cada observación `(contract_id, t0)`:

```text
feature_timestamp <= t0
```

Los históricos de supplier, entidad, proceso, competencia y relaciones deben calcularse únicamente con eventos anteriores a `t0`. No se permiten agregados “all years” aplicados retrospectivamente a contratos antiguos.

## 6. Deuda no bloqueante heredada

### Entity resolution

La cobertura determinística bidder→supplier es parcial. M3 debe:

- preservar `resolution_status`;
- evitar imputaciones arbitrarias;
- medir missingness/coverage por periodo y segmento;
- realizar ablations cuando una familia de features dependa de supplier identity.

### Eventos

Silver conserva todos los tipos de Adiciones. M3 debe justificar el outcome exacto antes de etiquetar.

### Fuentes diferidas

`payments` y `sanctions` continúan fuera del V1 hasta que tengan su propia canonicalización y gate de calidad.

## 7. Definition of Ready para empezar `20`

- [x] M1 cerrado.
- [x] M2 cerrado.
- [x] `M2_GATE.md` persistido.
- [x] 12 artefactos Silver completos.
- [x] Manifests consistentes con `m2-silver-v1`.
- [x] Cero issues Silver bloqueantes.
- [x] Deudas no bloqueantes documentadas.
- [ ] Semantic freeze del target — responsabilidad de `20_target_engineering.ipynb`.

M3 está listo para comenzar, pero Modeling todavía no está autorizado.
