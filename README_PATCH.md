# ARGOS M2 — SQL alias compatibility patch

Apply this ZIP **as an overlay** on the existing `argos-code/` project. Do not replace the project directory and do not delete `data/bronze/`, `data/silver/`, M1 reports, or the already-passed notebook 10 artifacts.

## What it fixes

Notebook 11 failed in a DuckDB validation query using the bare alias:

```sql
COUNT(*) rows
```

`ROWS` is SQL grammar in DuckDB and is unsafe as a bare alias. The patch uses explicit `AS` aliases and prefers `row_count`. It also makes later M2 aggregate queries more defensive with `COALESCE(SUM(...), 0)` where Python expects integers.

Files patched:

- `src/argos/silver/suppliers_bidders.py` → `m2-11-suppliers-bidders-v2`
- `src/argos/silver/events.py` → `m2-12-addition-events-out-of-core-v2`
- `src/argos/silver/entity_resolution.py` → `m2-13-deterministic-entity-resolution-v2`
- `src/argos/silver/validation.py` → `m2-14-cross-silver-validation-v2`

## After copying

From the project root:

```bash
uv pip install -e .
```

Restart the Jupyter kernel. Then rerun notebook 11 from the first cell. Notebook 11 already invokes the build with `overwrite=True`, so partial artifacts from the failed execution will be rebuilt safely.

You do **not** need to rerun notebook 10. The old `ModuleNotFoundError` shown for notebook 10 is a stale VS Code diagnostic if notebook 11 can import and enter `argos.silver.suppliers_bidders`.
