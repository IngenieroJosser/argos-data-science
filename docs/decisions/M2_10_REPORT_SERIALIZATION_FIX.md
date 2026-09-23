# M2 / Notebook 10 — corrección de persistencia del reporte de validación

## Contexto

La construcción out-of-core de `10_silver_contracts_processes.ipynb` llegó a completar
las etapas costosas de materialización de `processes`, pero falló al persistir
`reports/silver/10_validation.parquet` con PyArrow.

El campo `observed` del DataFrame de validación mezclaba diccionarios, listas y
escalares Python. Arrow exige un único tipo representable por columna y no puede
convertir de forma segura una columna `object` heterogénea de ese tipo.

## Decisión

La evidencia `observed` se serializa como texto JSON determinista antes de construir
el DataFrame de validación. Así:

- se preserva el payload diagnóstico completo;
- el esquema Parquet queda estable;
- el fallo de reporting no obliga a modificar la semántica de los checks;
- no se introducen coerciones silenciosas sobre los artefactos Silver.

Se incorpora además una ruta de recuperación
`finalize_existing_contracts_processes_silver(...)` que permite validar y persistir
reportes/manifest a partir de los cinco Parquet ya materializados. Esta ruta verifica
que todos los artefactos existan y que su `_silver_schema_version` coincida con la
configuración activa antes de aceptarlos.

## Alcance

Esta corrección no cambia:

- el grain de contratos o procesos;
- la lógica de deduplicación exacta;
- el routing de columnas;
- el parser temporal;
- la segregación de campos mutables;
- los criterios bloqueantes del notebook 10.

Solo corrige la representación del reporte de validación y permite reanudar una
ejecución que ya terminó la materialización pesada.
