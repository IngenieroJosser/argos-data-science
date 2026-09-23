# M2 — decisión de arquitectura Silver

## Decisión

ARGOS separa **identidad**, **versiones observadas** y **estado mutable** en lugar de construir una tabla plana única.

Para Contracts/Processes:

```text
contracts.parquet
contracts_snapshot_state.parquet
process_versions.parquet
processes.parquet
contract_process_links.parquet
```

## Motivación

M1 mostró que `contracts.id_contrato` es una PK estable, mientras que la identidad de proceso usada por Contracts (`id_del_portafolio`) aparece en múltiples filas/payloads de Procesos. Seleccionar arbitrariamente una fila "más reciente" podría incorporar información posterior al momento contractual y producir leakage.

Por tanto:

- Contracts mantiene un grain contractual estable.
- El snapshot mutable del contrato se separa para reducir el riesgo de uso accidental como feature.
- Las observaciones distintas de Procesos se preservan en `process_versions`.
- `processes` contiene una identidad canónica y diagnósticos de multiplicidad, no una falsa fotografía histórica.
- las relaciones se materializan como tablas de link cuando hacerlo evita many-to-many accidentales.

## No decisión

Esta arquitectura no define todavía qué columnas son features válidas para `y_addition_180d`. Esa autorización pertenece a Gold y requiere point-in-time correctness explícita.
