# M2 SQL alias repair — 2026-09-23

## Context

Notebook `11_silver_suppliers_bidders.ipynb` failed under DuckDB 1.5.x with a parser error at `COUNT(*) rows`. `ROWS` is part of SQL window-frame grammar and should not be used as an unquoted implicit alias in production queries.

## Decision

- Replace the ambiguous alias `rows` with semantic aliases such as `row_count`, `link_row_count`, `event_count`, and `map_row_count`.
- Use explicit `AS` for aggregate aliases in M2 validation queries.
- Use `COALESCE(SUM(...), 0)` where Python later converts aggregate results to `int`, so empty inputs cannot become `NaN`.
- Keep the fix centralized in `src/argos/`; notebooks remain orchestration-only.

## Scope

The repair is applied to notebooks 11–14 through their reusable modules. No Bronze, M1, or already-validated notebook 10 data artifacts are changed.
