# ARGOS — M1 Data Understanding & Target Feasibility Runbook

Run notebooks **in order**:

1. `00_bronze_inventory.ipynb`
2. `01_schema_and_semantic_profiling.ipynb`
3. `02_grain_keys_and_duplicates.ipynb`
4. `03_relationships_and_join_coverage.ipynb`
5. `04_temporal_audit.ipynb`
6. `05_data_quality_audit.ipynb`
7. `06_target_feasibility.ipynb`
8. `07_m1_gate.ipynb`

`07_m1_gate.ipynb` is the authority for the M1 → Silver transition. A notebook running without an exception is **not** sufficient evidence that M1 is closed.

## Remediations incorporated after the first full M1 run

The first pass exposed four blocking issues. The code now treats them explicitly:

- **Temporal parsing:** SECOP/Socrata dates are parsed with explicit ISO and `MM/DD/YYYY` formats. Generic `TRY_CAST` is not used as the primary parser. Parser success and calendar plausibility are measured separately.
- **Contracts → Processes:** the failed hard-coded `Proceso de Compra → ID del Proceso` assumption was removed. Notebook 03 compares candidate process identifiers and persists the empirically selected relationship.
- **Grain:** notebook 02 distinguishes exact repeated rows from multiple payload variants for repeated process/event keys.
- **Target duplication:** the addition target uses distinct `(contract_id, event_at, event_type)` events, so repeated Bronze rows cannot inflate the binary outcome.

`payments` and `sanctions` remain inventoried and audited, but are explicitly deferred for the first addition-risk V1. Their unresolved issues do not become model features and do not block the V1 Silver gate.

The direct `bidders.codigo_proveedor -> suppliers.codigo` hypothesis is also measured rather than hidden: the current snapshot produced 0% direct overlap. Because the first Silver contract/event layer and `y_addition_180d` do not depend on this edge, M1 records it as a **non-blocking, explicit Silver entity-resolution obligation**. `13_entity_resolution.ipynb` must investigate provider-code representation and alternative deterministic identifiers (for example normalized NIT) before bidder-level supplier history is used in features.

## Design rule

Notebooks are orchestration + scientific narrative. Reusable computation is under `src/argos/`.
Bronze is read-only. No notebook writes to `data/bronze`.

## Before running

```bash
uv sync
uv pip install -e .
uv run python -m ipykernel install --user --name argos --display-name "Python (ARGOS)"
```

Restart the Jupyter kernel after replacing project code. Execute notebooks from the repository using the `Python (ARGOS)` kernel.

## Runtime note

Exact counts, duplicate fingerprints, candidate-key comparisons and relationship audits scan multi-GB CSVs. This is expected for the first governance pass. The duplicate-structure diagnostics in notebook 02 are intentionally expensive because they distinguish exact duplicated rows from true payload variants.

Once Silver exists as Parquet, repeated profiling will be materially faster.

## M1 closure criteria

The automated gate requires evidence for all blocking checks configured in `configs/project.toml`, including:

- seven non-empty Bronze snapshots;
- `contracts.id_contrato` unique and non-null;
- `suppliers.codigo` unique and non-null;
- process duplicate/grain behavior characterized;
- addition-event duplicate behavior characterized;
- Contracts → Processes resolved empirically with sufficient coverage;
- core relationship coverage above configured thresholds;
- `fecha_de_firma` with sufficient raw coverage, parsing success and plausible calendar range;
- `FechaRegistro` in Adiciones with sufficient parsing success;
- `y_addition_180d` with enough eligible observations, positives and internally consistent labels;
- known post-`t0`/mutable columns explicitly registered as leakage risks;
- deferred V1 sources explicitly declared rather than silently ignored.

When every blocking check passes, notebook 07 writes:

```text
reports/profiling/m1_gate_report.parquet
docs/decisions/M1_GATE.md
```

and prints:

```text
M1 ✅ CLOSED
```

Only then should ARGOS proceed to the Silver notebooks.
