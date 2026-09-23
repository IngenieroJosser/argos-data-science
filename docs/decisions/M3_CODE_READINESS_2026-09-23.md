# M3 — Code readiness review — 2026-09-23

> **Estado de M3:** ▶ IN PROGRESS  
> **Prerequisito:** M2 ✅ CLOSED  
> **Gold schema:** `m3-gold-v1`

## Decisión

La implementación de M3 V1 está preparada para ejecución secuencial sobre los artefactos Silver cerrados de M2. Este documento **no cierra M3** y no sustituye la evidencia empírica de los notebooks `20`–`27`.

## Alcance implementado

- target engineering con censura explícita y evento positivo `ADICION EN EL VALOR`;
- split temporal congelado train/validation/test;
- EDA de modelado restringida a train;
- whitelist conservadora de features contractuales;
- históricos estrictamente anteriores a `t0`;
- features de competencia condicionadas a `publication_at <= t0`;
- auditoría Gold point-in-time y feature registry;
- gate computable de M3;
- manifests y reportes de lineage por componente;
- pipeline reproducible `20 → 27`.

## Controles preventivos

- `contracts_snapshot_state.parquet` no se consume como fuente de features V1;
- metadata `_pit_*` se conserva para auditoría pero se excluye del model matrix;
- históricos usan `history_timestamp < t0`;
- contratos firmados al mismo `t0` no se cuentan mutuamente como historia previa;
- participaciones sin timestamp observable no se asumen conocidas en `t0`;
- `24_historical_features` usa etapas Parquet temporales y agregaciones estrechas para reducir presión de memoria;
- el test permanece temporalmente separado y no debe utilizarse para decisiones de feature engineering o tuning.

## Validación realizada antes de entrega

Se verificó estáticamente:

1. compilación de `src/`, `scripts/` y `pipelines/`;
2. sintaxis de todas las celdas de código de notebooks `20`–`27`;
3. notebooks sin outputs ni execution counts pregrabados;
4. carga y validación de `configs/gold.toml` mediante tests unitarios;
5. tests de semántica del target, aliases SQL y render del gate;
6. ausencia de aliases SQL `rows` conocidos por entrar en conflicto con DuckDB;
7. ausencia de `sys.path` hacks, `ignore_errors=true` en lectores Gold y consumo de `contracts_snapshot_state` por módulos Gold.

## Limitación de esta revisión

El entorno usado para preparar el paquete no contiene DuckDB ni los Parquet Silver materiales del usuario. Por tanto, las consultas SQL de gran escala **no se consideran validadas empíricamente** hasta ejecutar los notebooks contra el repositorio local real.

## Criterio de avance

Ejecutar en orden y detenerse ante cualquier `❌ FAIL`:

```text
20_target_engineering.ipynb
21_temporal_split_design.ipynb
22_train_eda.ipynb
23_contract_features.ipynb
24_historical_features.ipynb
25_competition_relationship_features.ipynb
26_gold_point_in_time_audit.ipynb
27_m3_gate.ipynb
```

Modeling solo queda autorizado cuando `27_m3_gate.ipynb` produzca `M3 ✅ CLOSED` con todos los checks bloqueantes aprobados.
