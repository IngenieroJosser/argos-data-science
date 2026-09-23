# ARGOS — M1 Data Understanding Gate

**Status:** M1 ✅ CLOSED

Generated: `2026-09-23T00:43:33+00:00`

Blocking checks passed: **19/19**.

| Check | Category | Gate role | Result | Observed | Requirement |
|---|---|---|---|---|---|
| `inventory_complete` — All required Bronze datasets are inventoried with rows | inventory | blocking | PASS | datasets=7, nonempty=7 | >= 7 non-empty datasets |
| `bronze_structural_integrity` — Bronze CSV records have the header-defined field count | inventory | blocking | PASS | ragged_rows=0 | ragged_row_count = 0 across active snapshots |
| `contracts_primary_key` — Contracts has a non-null unique technical key | grain | blocking | PASS | {'null_rate': np.float64(0.0), 'uniqueness': np.float64(1.0)} | id_contrato null_rate=0 and uniqueness=1 |
| `suppliers_primary_key` — Suppliers has a non-null unique technical key | grain | blocking | PASS | {'null_rate': np.float64(0.0), 'uniqueness': np.float64(1.0)} | codigo null_rate=0 and uniqueness=1 |
| `processes_grain_characterized` — The selected process join key is characterized before Silver canonicalization | grain | blocking | PASS | {'selected_key': 'id_del_portafolio', 'interpretation': 'multiple_payload_variants_per_key', 'duplicate_keys': np.int64(222287), 'conflicting_keys': np.int64(181101)} | selected relationship key has a duplicate/payload diagnostic |
| `additions_grain_characterized` — Addition-event duplication is characterized | grain | blocking | PASS | {'interpretation': 'multiple_payload_variants_per_key', 'duplicate_excess': np.int64(19741938)} | event-key duplication diagnostic exists |
| `contracts_processes_resolved` — Contracts -> Processes uses an empirically resolved key | relationships | blocking | PASS | {'right_keys': array(['id_del_portafolio'], dtype=object), 'coverage': 0.9754900910375112, 'requires_canonicalization': np.True_} | coverage >= 90.00% |
| `relationship_contracts_suppliers` — Contracts -> Suppliers has sufficient identifier coverage | relationships | blocking | PASS | {'coverage': 0.9466465459975967, 'expansion': np.float64(1.0), 'right_multiplicity': np.float64(1.0)} | coverage >= 90.00% |
| `relationship_additions_contracts` — Additions -> Contracts has sufficient identifier coverage | relationships | blocking | PASS | {'coverage': 0.9999459804294814, 'expansion': np.float64(1.0), 'right_multiplicity': np.float64(1.0)} | coverage >= 99.00% |
| `relationship_bidders_processes` — Bidders -> Processes has sufficient identifier coverage | relationships | blocking | PASS | {'coverage': 0.9883179072623022, 'expansion': np.float64(4.5650232092414), 'right_multiplicity': np.float64(8840.0)} | coverage >= 95.00% |
| `relationship_bidders_suppliers` — Bidders -> Suppliers uses Codigo Proveedor and has sufficient coverage | relationships | non-blocking | DEFERRED | {'coverage': 0.0, 'expansion': np.float64(1.0), 'right_multiplicity': np.float64(0.0)} | coverage >= 90.00% |
| `bidders_suppliers_resolution_deferred` — The failed direct Bidders -> Suppliers identifier hypothesis is measured and explicitly assigned to Silver entity resolution | scope | blocking | PASS | {'direct_coverage': np.float64(0.0), 'deferred_to': '13_entity_resolution'} | relationship is analyzed and listed in m1_scope.deferred_relationships |
| `t0_temporal_quality` — Candidate t0 has sufficient coverage, parseability and plausibility | temporal | blocking | PASS | {'coverage': 0.9297064481194977, 'parse_success': 1.0, 'plausible_rate': 1.0} | coverage>=85.00%, parse>=98.00%, plausible>=99.50% |
| `addition_event_time_quality` — Addition event timestamp is reliably parseable | temporal | blocking | PASS | {'parse_success': 1.0} | parse >= 99.00% |
| `addition_event_scope_profiled` — Adiciones Tipo values are profiled before freezing event semantics | target | blocking | PASS | {'event_types': 10, 'source_rows': 28378604} | non-empty event-type profile persisted by notebook 06 |
| `target_diagnostics_temporally_valid` — Target builder uses parsed t0 and deduplicated parsed events | target | blocking | PASS | {'t0_parse': 1.0, 'event_parse': 1.0, 'dedup_key': 'contract_id+event_at+event_type', 'duplicate_event_rate': np.float64(0.6956627605783569)} | target diagnostics clear parser thresholds and use explicit event deduplication |
| `target_180d_feasible` — y_addition_180d has observable positives and negatives | target | blocking | PASS | {'eligible': 5312182, 'positives': 1630300, 'negatives': 3681882, 'prevalence': 0.30689837057540575} | eligible>=100000, positives>=1000, positives+negatives=eligible, prevalence within configured sanity bounds |
| `leakage_register_present` — Known post-t0/mutable fields are explicitly registered as leakage risks | quality | blocking | PASS | potential_temporal_leakage=18 | > 0 documented leakage-risk fields |
| `deferred_sources_explicit` — Non-blocking V1 sources are explicitly deferred rather than silently ignored | scope | blocking | PASS | ['payments', 'sanctions'] | payments and sanctions explicitly listed as deferred for addition-risk V1 |
| `deferred_relationships_explicit` — Unresolved non-core relationships are explicitly deferred | scope | blocking | PASS | ['bidders_suppliers'] | bidders_suppliers explicitly listed for Silver entity resolution |

## Decision

M1 is closed for the **addition-risk V1 scope**. The project may proceed to Silver. Payments and sanctions remain explicitly deferred and do not become modeling inputs until their own data-quality gates are resolved.

The direct `bidders.codigo_proveedor -> suppliers.codigo` hypothesis is also explicitly deferred to `13_entity_resolution`: its measured failure is a Silver identity-resolution requirement, not an unobserved assumption.

The closure does not authorize mutable/post-t0 fields as model features. Point-in-time correctness remains mandatory in Gold feature engineering.
The all-row Adiciones event scope used in M1 is a feasibility scope; the final event-type semantics must be frozen before Gold target/model training.
