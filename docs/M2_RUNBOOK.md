# ARGOS — M2 Silver Runbook

## Objetivo

M2 transforma los snapshots Bronze, que permanecen inmutables, en una representación canónica, tipada, trazable y reutilizable del dominio SECOP II.

Silver **no es un dataset de entrenamiento**. Una columna presente en Silver no queda automáticamente autorizada como feature. La corrección point-in-time se vuelve a auditar en Gold.

## Orden de ejecución

```text
10_silver_contracts_processes.ipynb   ✅ requerido
11_silver_suppliers_bidders.ipynb
12_silver_events.ipynb
13_entity_resolution.ipynb
14_silver_validation.ipynb
15_m2_gate.ipynb
```

No avanzar al notebook siguiente si el actual deja checks bloqueantes fallidos.

## Runtime local

Las transformaciones Silver usan DuckDB con:

```text
threads = 2
memory_limit = 8GB
preserve_insertion_order = false
temp_directory = .cache/duckdb
```

El objetivo no es maximizar RAM; es dejar headroom al kernel y permitir spill a disco.

## Notebook 10 — Contracts & Processes

Construye:

```text
data/silver/contracts.parquet
data/silver/contracts_snapshot_state.parquet
data/silver/process_versions.parquet
data/silver/processes.parquet
data/silver/contract_process_links.parquet
```

Principios:

1. `contract_id` conserva el grain 1 fila = 1 contrato.
2. Estado mutable/post-`t0` se segrega físicamente.
3. `process_versions` elimina únicamente duplicados raw exactos.
4. `processes` es identidad/diagnóstico, no “última versión”.
5. `contract_process_links` evita la expansión del join Bronze.

## Notebook 11 — Suppliers & Bidders

Construye:

```text
data/silver/suppliers.parquet
data/silver/bidder_participations.parquet
data/silver/procedure_process_map.parquet
data/silver/bidder_process_links.parquet
```

Principios:

1. `supplier_code` conserva la PK validada en M1.
2. `bidder_participations` preserva todas las filas de la fuente Bronze.
3. `procedure_process_map` canonicaliza `procedure_id -> process_id` antes del join.
4. `bidder_process_links` representa una relación canónica sin expansión accidental.
5. Campos de contacto/representante que no se necesitan para ER quedan fuera del Silver analítico general.
6. **No** se fuerza bidder→supplier en este notebook.

## Notebook 12 — Events

Construye:

```text
data/silver/addition_event_versions.parquet
data/silver/addition_events.parquet
```

La fuente de Adiciones se procesa out-of-core:

1. staging CSV → Parquet con fingerprint de fila;
2. agregación estrecha por fingerprint;
3. comparación raw exacta solo de candidatos duplicados;
4. materialización de payloads exactos;
5. canonicalización del evento por `(contract_id, event_at, event_type)`.

Silver conserva **todos** los `Tipo`. La semántica final de `y_addition_180d` se congela en Gold.

## Notebook 13 — Entity Resolution

Construye:

```text
data/silver/bidder_supplier_entity_map.parquet
reports/silver/13_resolution_summary.parquet
```

Estrategias determinísticas por prioridad:

1. código SECOP exacto;
2. NIT exacto después de normalizar únicamente case/espacios/puntuación, y solo si identifica un supplier único.

No se usa:

- fuzzy name matching;
- truncado/transformación especulativa de IDs;
- eliminación del dígito de verificación;
- adjudicación futura para resolver identidad.

`unresolved`, `ambiguous_nit` y `conflict_code_vs_nit` son estados válidos y auditables.

La cobertura de ER es **métrica de reporting**, no un incentivo para inventar matches.

## Notebook 14 — Cross-Silver Validation

Produce:

```text
reports/silver/m2_validation.parquet
reports/silver/m2_issue_register.parquet
artifacts/manifests/silver_m2_validation.json
```

Valida:

- existencia de artefactos;
- manifests;
- schema version;
- checks bloqueantes de 10–13;
- cobertura Contract→Supplier;
- integridad BidderLink→EntityMap;
- integridad AdditionEvent→Contract;
- deuda/deferred explícita.

## Notebook 15 — M2 Gate

Autoridad formal de cierre.

Produce:

```text
reports/silver/m2_gate_report.parquet
docs/decisions/M2_GATE.md
```

M2 solo se considera cerrado cuando imprime:

```text
M2 ✅ CLOSED
```

El gate no está hardcodeado: consume evidencia persistida por 10–14.

## Después de M2

Al cerrar M2:

1. congelar `M2_GATE.md`, manifests y reportes Silver;
2. crear commit/tag del milestone;
3. iniciar Gold;
4. no entrenar directamente sobre Silver.

Gold deberá volver a aplicar point-in-time correctness, congelar la semántica del target y diseñar el split temporal antes de cualquier modelo.
