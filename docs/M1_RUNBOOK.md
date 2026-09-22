# ARGOS — M1 Data Understanding & Target Feasibility Runbook

Run notebooks **in order**:

1. `00_bronze_inventory.ipynb`
2. `01_schema_and_semantic_profiling.ipynb`
3. `02_grain_keys_and_duplicates.ipynb`
4. `03_relationships_and_join_coverage.ipynb`
5. `04_temporal_audit.ipynb`
6. `05_data_quality_audit.ipynb`
7. `06_target_feasibility.ipynb`

## Design rule

Notebooks are orchestration + scientific narrative. Reusable computation is under `src/argos/`.
Bronze is read-only. No notebook writes to `data/bronze`.

## Before running

```bash
uv sync
uv run python -m ipykernel install --user --name argos --display-name "Python (ARGOS)"
uv run jupyter lab
```

Execute from the repository root. Outputs go to `reports/` and should be treated as generated evidence.

## Runtime note

Exact `COUNT(*)`, key and join audits scan multi-GB CSVs. This is expected for the first governance pass.
Once Silver exists as Parquet, repeated profiling will be materially faster.

## M1 Definition of Done

- [ ] seven Bronze snapshots inventoried
- [ ] schema/semantic profile generated
- [ ] grain documented for every source
- [ ] candidate keys measured
- [ ] join coverage/multiplicity/expansion measured
- [ ] temporal coverage and ordering audited
- [ ] preliminary leakage register reviewed
- [ ] quality issue register created
- [ ] candidate `t0` supported by evidence
- [ ] `y_addition_180d` feasibility measured with censoring
- [ ] GO / REDEFINE decision documented
