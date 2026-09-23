# M3 Runbook — Gold / Point-in-Time Analytical Layer

> **Estado:** ▶ IN PROGRESS  
> **Prerequisito:** `M2 ✅ CLOSED`  
> **Gold schema:** `m3-gold-v1`

M3 transforma la capa Silver canónica en una representación analítica apta para modelado temporal. El objetivo no es maximizar el número de features, sino demostrar que **cada label y cada feature puede reconstruirse con la información disponible en su `t0`**.

## Orden obligatorio

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

No avanzar si un notebook termina en `❌ FAIL`.

## 20 — Target engineering

Congela `y_addition_180d` con la semántica V1:

```text
t0 = fecha_de_firma
horizon = 180 días
evento positivo = ADICION EN EL VALOR
ventana = (t0, t0 + 180d]
label cutoff = max(event_at) observado en addition_events Silver
```

Los contratos con ventana incompleta son censurados y conservan label `NULL`.

Salidas:

```text
data/gold/target_population.parquet
data/gold/labels/y_addition_180d.parquet
reports/gold/20_target_validation.parquet
reports/gold/20_target_by_year.parquet
reports/gold/20_target_event_scope.parquet
reports/gold/20_target_censoring.parquet
artifacts/manifests/gold_target_y_addition_180d.json
```

## 21 — Temporal split design

Split V1 congelado:

```text
TRAIN       2015-01-01 .. 2023-12-31
VALIDATION  2024-01-01 .. 2024-12-31
TEST        2025-01-01 .. 2025-12-31
```

2026 permanece fuera del split principal porque el snapshot actual solo permite observar una fracción del año con horizonte completo de 180 días.

El test no debe utilizarse en feature engineering, selección de modelos ni tuning.

## 22 — Train-only EDA

Toda exploración orientada a decisiones de modelado se realiza sobre `split='train'`.

Se auditan:

- prevalencia;
- cobertura y missingness de candidates;
- cardinalidad categórica;
- distribuciones numéricas cuando existan candidates autorizados.

## 23 — Contract features

Usa una whitelist conservadora configurada en `configs/gold.toml`.

No consume `contracts_snapshot_state.parquet`. Los campos conocidos como mutables/post-`t0` continúan prohibidos. Las columnas monetarias de snapshot actual no están autorizadas en V1 hasta demostrar independientemente su semántica as-of-signing.

## 24 — Historical features

Construye historia estrictamente anterior a `t0`:

- número previo de contratos del proveedor;
- número previo de contratos de la entidad;
- historial proveedor–entidad;
- tenure y recencia;
- eventos de `ADICION EN EL VALOR` observados antes de `t0`.

Regla:

```text
history_timestamp < t0
```

Los timestamps máximos utilizados se conservan como metadata `_pit_*` para auditoría y no son features del modelo.

## 25 — Competition & relationship features

Caracteriza la competencia observable antes de firma. Una participación solo cuenta cuando:

```text
publication_at <= t0
```

Si `publication_at` es nulo, la participación no se considera demostrablemente disponible en `t0`.

## 26 — Gold PIT audit

Audita conjuntamente labels, split y features. Solo después de pasar este notebook se materializa:

```text
data/gold/ml/argos_v1.parquet
```

Checks principales:

- 1 fila por contrato asignado;
- labels completos;
- `t0` consistente entre componentes;
- historia estrictamente previa;
- competencia no posterior a `t0`;
- campos mutables Silver ausentes;
- metadata `_pit_*` ausente del feature matrix;
- feature registry explícito.

## 27 — M3 Gate

Autoridad formal de cierre de M3. Verifica reportes 20–26, artefactos, manifests, target spec congelado, split congelado y ausencia de issues bloqueantes.

M3 se considera cerrado únicamente cuando imprime:

```text
M3 ✅ CLOSED
```

## Principio de diseño

> El dataset Gold debe poder reconstruirse como si el sistema estuviera situado en cada `t0`. Si para calcular una feature es necesario conocer el futuro, esa feature no pertenece al modelo V1.
