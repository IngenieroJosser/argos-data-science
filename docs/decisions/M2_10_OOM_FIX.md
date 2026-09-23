# M2 / Notebook 10 — Corrección de presión de memoria

## Síntoma

`10_silver_contracts_processes.ipynb` falló con `OutOfMemoryException` al alcanzar el
límite de memoria de DuckDB (~12.7 GiB en la estación de trabajo observada).

## Causa

La primera implementación de `process_versions` ejecutaba `GROUP BY ALL` sobre el
snapshot completo de Procesos: aproximadamente 9.2 millones de filas y 59 columnas.
Aunque DuckDB soporta spill a disco, ese patrón construye un estado de agregación muy
ancho y de cardinalidad alta. Es innecesario para resolver duplicados exactos.

## Decisión

Notebook 10 usa ahora una estrategia out-of-core:

1. materializa una etapa temporal Parquet mediante streaming desde Bronze;
2. calcula fingerprints de fila y agrega únicamente el fingerprint para localizar
   grupos candidatos a duplicado;
3. solo los grupos candidatos se comparan usando todas las columnas raw, de modo que
   el fingerprint no decide igualdad y una eventual colisión de hash no elimina filas;
4. materializa un representante por payload raw exacto con `_source_row_count`;
5. elimina los Parquet temporales una vez construido `process_versions.parquet`.

La configuración de DuckDB para Silver queda en `configs/silver.toml`:

```toml
[silver.runtime]
duckdb_threads = 2
duckdb_memory_limit = "8GB"
```

`preserve_insertion_order=false` ya se establece centralmente y el spill se dirige a
`.cache/duckdb`.

## Invariantes preservados

- Bronze permanece inmutable.
- `process_versions` elimina únicamente duplicados raw exactos.
- columnas sensibles pueden existir transitoriamente en el staging local para verificar
  igualdad exacta, pero no se publican en el Silver analítico general.
- `processes.parquet` sigue representando identidad canónica, no latest-state.
- ninguna decisión de target/features se introduce en Silver.

## Corrección adicional: agregados vacíos

También se observó `ValueError: cannot convert float NaN to integer`. El origen es
la semántica de SQL para agregados: `SUM(...)` sobre una entrada vacía devuelve
`NULL`, que pandas materializa como `NaN`. La auditoría ahora usa `COALESCE` en SQL
y una conversión defensiva `_int_or_zero`, de modo que un agregado vacío se
registre como cero y no oculte el estado real con una excepción secundaria.
