# ARGOS — Catálogo Silver M2

> **Milestone:** M2 — Silver / Canonical Data Model  
> **Estado:** ✅ CLOSED  
> **Schema version:** `m2-silver-v1`  
> **Gate:** 10/10 checks bloqueantes

Este documento cataloga los 12 artefactos canónicos que constituyen la salida formal de M2. Describe su grain y propósito de dominio; **no autoriza columnas como features de Machine Learning**.

| Artefacto | Grain canónico | Propósito | Restricción principal |
|---|---|---|---|
| `contracts.parquet` | 1 fila por `contract_id` | núcleo contractual canónico | no incluye campos M1 de alto riesgo de leakage ni PII configurada |
| `contracts_snapshot_state.parquet` | 1 fila por `contract_id` | estado mutable/current-state separado | no usar como feature sin reconstrucción PIT |
| `process_versions.parquet` | 1 fila por variante raw exacta deduplicada | preservar payloads/versiones observadas de Processes | no representa automáticamente estado válido en `t0` |
| `processes.parquet` | 1 fila por `process_id` | identidad/diagnóstico canónico de proceso | no es “latest state” para modelado |
| `contract_process_links.parquet` | 1 fila por contrato | relación contrato→proceso canonicalizada | conservar status de match; no asumir cobertura total |
| `suppliers.parquet` | 1 fila por `supplier_code` | entidad proveedor canónica | campos sensibles/contacto excluidos del analítico general |
| `bidder_participations.parquet` | 1 fila por participación Bronze preservada | relación de participación/propuesta | no equivale a identidad supplier resuelta |
| `procedure_process_map.parquet` | 1 fila por mapping canónico procedure→process | crosswalk para evitar join explosion | respetar status de resolución |
| `bidder_process_links.parquet` | 1 fila por link canónico bidder→process | relación de competencia/participación | no forzar supplier identity |
| `addition_event_versions.parquet` | 1 fila por payload raw exacto deduplicado | preservar versiones/eventos observados | no usar duplicates como eventos distintos |
| `addition_events.parquet` | 1 fila por evento canónico `(contract_id,event_at,event_type)` | fuente Silver de eventos contractuales | Gold define el subconjunto semántico del target |
| `bidder_supplier_entity_map.parquet` | 1 fila por bidder key canónica | resolución determinística bidder→supplier | `unresolved`/`ambiguous` son estados válidos |

## Evidencia de cierre

M2 conserva la población contractual y supplier validada, canonicaliza las relaciones sin expansión accidental y mantiene la incertidumbre de identidad explícita. El gate final verificó los 12 artefactos, manifests, consistencia de schema y ausencia de issues bloqueantes.

Documentos relacionados:

```text
docs/decisions/M2_GATE.md
docs/M2_RUNBOOK.md
docs/M3_HANDOFF.md
artifacts/manifests/silver_contracts_processes.json
artifacts/manifests/silver_suppliers_bidders.json
artifacts/manifests/silver_events.json
artifacts/manifests/silver_entity_resolution.json
artifacts/manifests/silver_m2_validation.json
```

## Contrato para Gold

Gold debe consumir estos artefactos sin reinterpretar silenciosamente su grain. Cualquier join debe preservar la unidad analítica `(contract_id, snapshot_date/t0)` y demostrar point-in-time correctness antes de materializar features.
