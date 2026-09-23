# Silver data dictionary — Contracts & Processes

> **Estado M2:** ✅ CLOSED  
> **Schema version:** `m2-silver-v1`

## `contracts.parquet`

**Grain:** 1 row = 1 `contract_id`.

Contains canonical contract columns excluding fields routed to mutable snapshot state and configured sensitive/PII semantic types.

Key canonical aliases:

| Bronze normalized | Silver | Role |
|---|---|---|
| `id_contrato` | `contract_id` | primary key |
| `proceso_de_compra` | `process_id` | process link |
| `codigo_proveedor` | `supplier_code` | supplier identifier |

Dates are parsed with the explicit SECOP parser used in M1. Monetary fields use conservative locale-aware parsing into `DECIMAL(38,2)`. For every date/money field Silver also stores `__raw` and `__parse_status`, so unrecognized formats remain observable instead of disappearing silently.

Metadata columns:

- `_source_row_hash`
- `_source_snapshot_date`
- `_source_id`
- `_silver_schema_version`

Presence in this table **does not authorize a field as an ML feature**.

## `contracts_snapshot_state.parquet`

**Grain:** 1 row = 1 `contract_id`.

Contains contract fields identified in M1 as mutable/current-state or likely post-`t0`, including payment/facturation balances, added days, liquidation/prórroga fields and current contract state.

This physical separation exists to reduce accidental leakage. Gold must still perform point-in-time validation before any use.

## `process_versions.parquet`

**Grain:** 1 row = 1 distinct raw process payload after exact raw-row deduplication.

Key fields:

- `process_id` ← `id_del_portafolio`
- `procedure_id` ← `id_del_proceso`
- `process_reference` ← `referencia_del_proceso`
- `_source_row_count`: how many Bronze rows were represented by the distinct payload
- `_source_row_hash`: lineage fingerprint

No arbitrary "latest row" is selected.

## `processes.parquet`

**Grain:** 1 row = 1 `process_id`.

Identity/diagnostic table. It does not pretend that the current snapshot reconstructs historical state.

Diagnostics include:

- `source_row_count`
- `version_count`
- `exact_duplicate_excess_rows`
- `procedure_id_variants`
- `process_reference_variants`
- `has_multiple_payload_variants`

## `contract_process_links.parquet`

**Grain:** 1 row = 1 `contract_id`.

Columns:

- `contract_id`
- `process_id`
- `link_status`: `matched`, `unmatched_process`, or `missing_process_id`
- `process_version_count`

The table is constructed after process identity canonicalization, so it must not reproduce the Bronze join expansion observed in M1.
