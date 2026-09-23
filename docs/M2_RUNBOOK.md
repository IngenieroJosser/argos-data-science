# ARGOS — M2 Silver Runbook

> **Estado:** ✅ CLOSED  
> **Gate:** `15_m2_gate.ipynb`  
> **Resultado:** 10/10 checks bloqueantes  
> **Schema:** `m2-silver-v1`  
> **Decisión autoritativa:** `docs/decisions/M2_GATE.md`

## Objetivo alcanzado

M2 transformó los snapshots Bronze, que permanecen inmutables, en una representación canónica, tipada, trazable y reutilizable del dominio SECOP II.

Silver **no es un dataset de entrenamiento**. Una columna presente en Silver no queda automáticamente autorizada como feature. La corrección point-in-time se vuelve a auditar en Gold.

## Secuencia cerrada

```text
10_silver_contracts_processes.ipynb   ✅ PASS — 10/10
11_silver_suppliers_bidders.ipynb     ✅ PASS —  6/6
12_silver_events.ipynb                ✅ PASS —  5/5
13_entity_resolution.ipynb            ✅ PASS —  4/4 bloqueantes
14_silver_validation.ipynb            ✅ PASS —  8/8
15_m2_gate.ipynb                      ✅ CLOSED — 10/10
```

M2 queda congelado como baseline. No se reejecuta por rutina durante M3; solo se reabre si cambia una fuente, una regla canónica, el schema Silver o un artefacto que invalide la evidencia persistida.

## Runtime local utilizado

Las transformaciones Silver usan DuckDB con:

```text
threads = 2
memory_limit = 8GB
preserve_insertion_order = false
temp_directory = .cache/duckdb
```

El objetivo no es maximizar RAM, sino dejar headroom al kernel y permitir spill a disco en operaciones de alta cardinalidad.

## Notebook 10 — Contracts & Processes

Construye:

```text
data/silver/contracts.parquet
data/silver/contracts_snapshot_state.parquet
data/silver/process_versions.parquet
data/silver/processes.parquet
data/silver/contract_process_links.parquet
```

Principios cerrados:

1. `contract_id` conserva el grain 1 fila = 1 contrato.
2. Estado mutable/post-`t0` queda segregado físicamente.
3. `process_versions` elimina únicamente duplicados raw exactos.
4. `processes` representa identidad/diagnóstico, no “última versión”.
5. `contract_process_links` evita la expansión del join Bronze.
6. El parser explícito de `t0` preserva la población validada en M1.

Resultado: **10/10 checks bloqueantes**.

## Notebook 11 — Suppliers & Bidders

Construye:

```text
data/silver/suppliers.parquet
data/silver/bidder_participations.parquet
data/silver/procedure_process_map.parquet
data/silver/bidder_process_links.parquet
```

Principios cerrados:

1. `supplier_code` conserva la PK validada.
2. `bidder_participations` preserva todas las filas Bronze.
3. `procedure_process_map` canonicaliza `procedure_id -> process_id` antes del join.
4. `bidder_process_links` tiene grain canónico sin expansión accidental.
5. Campos de contacto/representante innecesarios para ER quedan fuera del Silver analítico general.
6. Bidder→supplier se resuelve únicamente en notebook 13.

Resultado: **6/6 checks bloqueantes**.

## Notebook 12 — Events

Construye:

```text
data/silver/addition_event_versions.parquet
data/silver/addition_events.parquet
```

La fuente de Adiciones se procesa out-of-core y solo colapsa duplicados raw después de verificar igualdad exacta. El evento canónico se identifica mediante `(contract_id, event_at, event_type)`.

Silver conserva **todos** los `Tipo`. La semántica final del target se congela en M3/Gold, no en Silver.

Resultado: **5/5 checks bloqueantes**.

## Notebook 13 — Entity Resolution

Construye:

```text
data/silver/bidder_supplier_entity_map.parquet
reports/silver/13_resolution_summary.parquet
```

Estrategias determinísticas aceptadas:

1. código SECOP exacto cuando aplica;
2. NIT exacto normalizado por case/espacios/puntuación, únicamente cuando identifica un supplier único.

No se fuerza fuzzy matching ni transformaciones especulativas de identificadores. `unresolved_no_match` y `ambiguous_nit` son estados válidos.

La cobertura determinística observada es limitada y queda como deuda **no bloqueante** para M3; la prioridad fue precisión de identidad, no cobertura artificial.

Resultado: **4/4 checks bloqueantes**.

## Notebook 14 — Cross-Silver Validation

Produce:

```text
reports/silver/m2_validation.parquet
reports/silver/m2_issue_register.parquet
artifacts/manifests/silver_m2_validation.json
```

Valida existencia de artefactos, manifests, schema, checks de componentes, coberturas cruzadas y deuda explícita.

Resultado: **8/8 checks bloqueantes**, **0 issues bloqueantes**.

## Notebook 15 — M2 Gate

Autoridad formal de cierre. Produce:

```text
reports/silver/m2_gate_report.parquet
docs/decisions/M2_GATE.md
```

Resultado persistido:

```text
M2 ✅ CLOSED
Blocking checks: 10/10
```

El gate no está hardcodeado: consume la evidencia persistida por notebooks `10`–`14`.

## Artefactos congelados

M2 cerró con 12 artefactos canónicos. El inventario, grain, propósito y restricciones están documentados en:

```text
docs/data-dictionary/silver_m2_catalog.md
```

Los manifests autoritativos están bajo:

```text
artifacts/manifests/
```

## Deuda explícita transportada a M3

- Bidder→supplier conserva población no resuelta/ambigua; no debe imputarse una identidad inexistente.
- `payments` y `sanctions` permanecen diferidos para el V1 de riesgo de adiciones.
- `y_addition_180d` continúa como especificación candidata hasta congelar los tipos de evento incluidos.
- `processes.parquet` no equivale a un estado histórico válido para cualquier `t0`; Gold debe seleccionar información disponible as-of `t0`.
- Silver no autoriza por sí mismo ninguna columna como feature.

## Handoff a M3

El contrato formal de entrada a Gold está documentado en:

```text
docs/M3_HANDOFF.md
```

El siguiente milestone debe comenzar por target engineering, semantic freeze y diseño temporal antes de construir features o entrenar modelos.
