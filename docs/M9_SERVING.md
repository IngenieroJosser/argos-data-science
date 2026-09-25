# M9 — Serving read-only para la Plataforma Analítica

## Objetivo

M9 presenta los resultados de ARGOS sin convertir el frontend en parte del pipeline científico.
La capa serving es **derivada, borrable y regenerable**. M1–M8, Gold, modelos, manifests y
reportes científicos se consumen únicamente en modo lectura.

## Por qué no se usa `argos_v1.parquet` para enriquecer OOT 2026

`data/gold/ml/argos_v1.parquet` contiene TRAIN/VALIDATION/TEST hasta 2025. El batch M6 actual
fue puntuado sobre `data/m5/fresh_oot_2026.parquet`. Por tanto, el contexto point-in-time de
los contratos 2026 debe salir del **mismo input que fue puntuado**, no de la matriz V1 histórica.

La capa M9 combina:

```text
M6 scored batch                     score/raw_score/rank/t0
        +
exact scoring input (OOT 2026)      features PIT usadas por el modelo
        +
Silver contracts/suppliers          nombres, objeto e identidad descriptiva
        ↓
M9 serving DuckDB                   read-only para frontend
```

## Artefactos derivados

```text
data/serving/m9/argos-serving.duckdb
data/serving/m9/overview.json
data/serving/m9/manifest.json
reports/serving/m9_serving_validation.parquet
```

Eliminar `data/serving/m9/` no afecta ningún milestone científico.

## Construcción

```bash
uv run --no-sync python scripts/build_m9_serving.py
```

El build aborta si:

- cambia la cardinalidad del batch;
- aparece un `contract_id` duplicado o nulo;
- cambia `score`, `raw_score`, `rank` o `t0`;
- se intenta exponer target, campos post-t0 o PII prohibida.

## API local read-only

```bash
uv run --no-sync python scripts/serve_m9.py
```

Endpoints:

```text
GET /health
GET /api/v1/overview
GET /api/v1/contracts?page=1&pageSize=25
GET /api/v1/contracts?priority=Alta&q=instituto
GET /api/v1/contracts/CO1.PCCNTR.9203796
GET /api/v1/monitoring
```

El servidor no implementa POST, PUT, PATCH ni DELETE.

## Detalle contractual esperado

La respuesta de detalle incluye:

- entidad y proveedor cuando Silver dispone de nombre permitido;
- departamento, ciudad, modalidad, sector y tipo contractual;
- score, raw score, rank, percentil y banda de prioridad;
- contexto estrictamente previo a `t0` utilizado por V1;
- identificadores canónicos para trazabilidad.

La ausencia de un nombre descriptivo no altera scoring. En ese caso la UI utiliza el
identificador canónico como fallback.

## M8

Las features M8 no se proyectan sobre el OOT 2026. M8 permanece como evidencia de investigación
cerrada (`RESEARCH_COMPLETE_NO_PROMOTION`) y no se mezcla con la decisión operativa de V1.
