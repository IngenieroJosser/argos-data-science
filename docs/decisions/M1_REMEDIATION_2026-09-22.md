# M1 remediation decision — 2026-09-22

## Context

The first complete M1 execution exposed four issues that prevented a defensible transition to Silver:

1. `Fecha de Firma` had high raw availability but low parser success because the parser did not explicitly support the SECOP/Socrata `MM/DD/YYYY` representation.
2. The configured `contracts.proceso_de_compra -> processes.id_del_proceso` relationship had zero observed coverage.
3. `processes` and `additions` showed substantial repeated candidate keys, so key uniqueness alone was insufficient to define Silver grain.
4. The provisional addition target used source event rows directly in diagnostics even though Adiciones contained repeated rows.

## Decisions

### Temporal parsing

ARGOS now uses deterministic explicit formats. ISO representations are attempted first, followed by the configured source order (`mdy` for the current SECOP snapshots), then the opposite slash order only as a fallback. Generic `TRY_CAST` is not the primary timestamp parser.

Temporal profiling distinguishes:

- raw meaningful values;
- parsable values;
- unparsable values;
- broad calendar plausibility;
- raw versus plausible min/max timestamps;
- parser-format distribution for target-critical timestamps.

### Contracts -> Processes

The failed hard-coded FK is no longer accepted. Notebook 03 compares `Proceso de Compra` against configured process-key candidates and persists the selected relationship only when it clears an explicit coverage threshold.

The selected right-side process key is then subjected to a duplicate/payload-variant diagnostic before Silver design.

### Grain and duplicates

M1 now fingerprints complete Bronze rows for blocking repeated keys. Repeated keys are classified as:

- unique;
- exact repeated rows only; or
- multiple payload variants per key.

This distinction determines whether Silver may use exact deduplication or requires a canonicalization/versioning rule.

### Addition target

`y_addition_180d` feasibility deduplicates parsed events on:

```text
(contract_id, event_at, event_type)
```

before finding the first event after `t0`. Duplicate source rows therefore cannot inflate the binary target.

### Deferred sources

`payments` and `sanctions` remain fully visible in Bronze profiling and the quality register, but are deferred for the first addition-risk V1. They cannot be used as V1 model features until their own quality/relationship gates are resolved.

## Closure authority

`07_m1_gate.ipynb` is the authoritative transition gate. It writes `docs/decisions/M1_GATE.md` from measured report artifacts and only reports `M1 ✅ CLOSED` when every blocking criterion passes.
