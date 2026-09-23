# ARGOS

**Plataforma de inteligencia analítica para priorización de riesgo en contratación pública**

ARGOS es un proyecto de Ciencia de Datos orientado al análisis de contratación pública registrada en **SECOP II**. Su propósito es construir, validar y eventualmente productivizar un sistema capaz de **priorizar contratos para revisión analítica adicional** utilizando únicamente la información que habría estado disponible en el momento de evaluación.

El proyecto está diseñado como un ejercicio de nivel profesional que integra **Data Engineering, Data Quality, modelado temporal, Machine Learning, MLOps, NLP, grafos, detección de anomalías y análisis de supervivencia**, manteniendo como prioridad la validez metodológica y la reproducibilidad.

> **ARGOS no clasifica contratos, proveedores o entidades como corruptos o fraudulentos.**  
> Una predicción o anomalía representa una **señal analítica o prioridad de revisión**, no una acusación ni una conclusión jurídica.

---

## Tabla de contenidos

- [1. Problema](#1-problema)
- [2. Decisión que ARGOS busca apoyar](#2-decisión-que-argos-busca-apoyar)
- [3. Pregunta predictiva inicial](#3-pregunta-predictiva-inicial)
- [4. Principios metodológicos](#4-principios-metodológicos)
- [5. Datos](#5-datos)
- [6. Arquitectura de datos](#6-arquitectura-de-datos)
- [7. Estructura del repositorio](#7-estructura-del-repositorio)
- [8. Estado actual del proyecto](#8-estado-actual-del-proyecto)
- [9. Notebooks y gates de M1–M5](#9-notebooks-y-gates-de-m1m5)
- [10. Arquitectura del código](#10-arquitectura-del-código)
- [11. Configuración](#11-configuración)
- [12. Instalación](#12-instalación)
- [13. Ejecución](#13-ejecución)
- [14. Artefactos generados](#14-artefactos-generados)
- [15. Calidad, pruebas y estilo](#15-calidad-pruebas-y-estilo)
- [16. Gates y criterios de cierre](#16-gates-y-criterios-de-cierre)
- [17. Roadmap](#17-roadmap)
- [18. Riesgos metodológicos](#18-riesgos-metodológicos)
- [19. Convenciones de trabajo](#19-convenciones-de-trabajo)
- [20. Fuentes oficiales](#20-fuentes-oficiales)

---

# 1. Problema

SECOP II contiene millones de registros relacionados con procesos de contratación, contratos, proveedores, participantes, modificaciones, pagos y sanciones.

El reto no consiste únicamente en procesar grandes volúmenes de datos. El problema analítico principal es que existe una diferencia entre:

- la cantidad de contratos potencialmente revisables;
- la capacidad limitada para analizarlos manualmente;
- la necesidad de identificar qué casos requieren mayor atención.

ARGOS parte de esta pregunta:

> **¿Qué contratos deberían priorizarse para revisión analítica adicional utilizando únicamente información disponible hasta el momento de evaluación?**

---

# 2. Decisión que ARGOS busca apoyar

ARGOS se plantea como un sistema de **priorización**.

Un escenario conceptual sería:

```text
Contratos disponibles
        │
        ▼
Capacidad limitada de revisión
        │
        ▼
ARGOS calcula señales y scores
        │
        ▼
Ranking de prioridad
        │
        ▼
Revisión humana
```

Por esta razón, el éxito del sistema no se medirá únicamente mediante métricas tradicionales de clasificación.

También serán importantes métricas orientadas a decisión como:

```text
Precision@K
Recall@K
Lift@K
Cumulative Gain
```

donde `K` representa la cantidad de contratos que realmente podrían revisarse.

---

# 3. Pregunta predictiva inicial

La primera formulación predictiva de ARGOS es:

> **Dada la información conocida hasta un instante `t0`, ¿cuál es la probabilidad de que un contrato presente una modificación contractual relevante durante los siguientes 180 días?**

Formalmente:

\[
P(Y_{180}=1 \mid X_{t0})
\]

El target candidato inicial es:

```text
y_addition_180d
```

En M3 V1 su semántica quedó congelada y validada como:

```text
t0 = fecha_de_firma
horizonte = 180 días
evento positivo = ADICION EN EL VALOR
ventana = (t0, t0 + 180d]
censura = horizonte incompleto => label NULL
```

La definición está versionada en `docs/target-specs/y_addition_180d.md` y se valida empíricamente en `20_target_engineering.ipynb`.

---

# 4. Principios metodológicos

## 4.1 Point-in-Time Correctness

Toda feature utilizada para evaluar un contrato debe representar información conocida en ese momento.

Debe cumplirse:

```text
feature_timestamp <= prediction_timestamp
```

Ejemplo correcto:

```text
supplier_previous_contracts(t0)
```

Ejemplo incorrecto:

```text
supplier_total_contracts_2018_2026
```

si el contrato se está evaluando en 2022.

---

## 4.2 El tiempo forma parte del problema

ARGOS no tratará los datos como un conjunto estático.

El flujo conceptual es:

```text
Publicación
    ↓
Propuestas
    ↓
Adjudicación
    ↓
Firma / formalización
    ↓
   t0
    │
    ├── Adiciones
    ├── Pagos
    ├── Sanciones
    └── Liquidación
```

Una variable posterior a `t0` no puede utilizarse para predecir un evento desde `t0`.

---

## 4.3 No confundir asociación con causalidad

Que una característica esté asociada con una mayor tasa de modificaciones no significa que sea su causa.

ARGOS distinguirá explícitamente entre:

```text
descripción
asociación
predicción
anomalía
evidencia causal
```

---

## 4.4 Censoring

Un contrato reciente no puede clasificarse automáticamente como negativo si todavía no ha transcurrido todo el horizonte de observación.

Para un horizonte de 180 días:

```text
eligible_for_label =
    observation_end_date >= t0 + 180 days
```

Los contratos sin ventana completa deberán excluirse del problema de clasificación o tratarse posteriormente mediante análisis de supervivencia.

---

## 4.5 Baseline antes de complejidad

Antes de introducir modelos avanzados se establecerán referencias simples:

```text
prevalencia
    ↓
reglas heurísticas
    ↓
Logistic Regression
    ↓
modelos de boosting
    ↓
modelos avanzados
```

Un modelo más complejo solo se justifica si mejora de forma consistente una referencia más simple.

---

# 5. Datos

Los datos brutos se descargan desde **Datos Abiertos Colombia / SECOP II** y se almacenan localmente en:

```text
data/bronze/
```

Actualmente ARGOS trabaja con siete fuentes principales.

| # | Dataset | Uso principal |
|---|---|---|
| 1 | SECOP II — Procesos de Contratación | contexto del proceso, entidad, modalidad, fechas |
| 2 | SECOP II — Contratos Electrónicos | unidad contractual principal |
| 3 | Proponentes por Proceso SECOP II | competencia y relaciones proveedor–proceso |
| 4 | SECOP II — Proveedores Registrados | maestro de proveedores y entity resolution |
| 5 | SECOP II — Adiciones | fuente candidata del primer target |
| 6 | SECOP II — Multas y Sanciones | eventos adversos e historial futuro |
| 7 | SECOP II — Plan de pagos | información de ejecución y futuros targets |

Los CSV pueden contener millones de registros y varios GB. Por esa razón:

- no se asume que Pandas sea el motor principal de procesamiento;
- se utilizan **DuckDB**, **Polars** y **Parquet**;
- los datos Bronze se consideran inmutables;
- los conteos y auditorías iniciales pueden ser intensivos en I/O.

---

# 6. Arquitectura de datos

ARGOS utiliza una arquitectura tipo medallion:

```text
data/
├── bronze/
├── silver/
└── gold/
```

## Bronze

Representa el snapshot original descargado desde la fuente.

```text
RAW
READ-ONLY
SOURCE OF TRUTH
```

Regla:

> Los datos de `bronze/` no se corrigen ni se sobrescriben.

---

## Silver

M2 construyó la capa canónica `m2-silver-v1`. Silver contiene representaciones limpias, tipadas, trazables y reutilizables del dominio, pero **no constituye una whitelist de features**.

Los 12 artefactos canónicos cerrados en M2 son:

```text
contracts.parquet
contracts_snapshot_state.parquet
process_versions.parquet
processes.parquet
contract_process_links.parquet
suppliers.parquet
bidder_participations.parquet
procedure_process_map.parquet
bidder_process_links.parquet
addition_event_versions.parquet
addition_events.parquet
bidder_supplier_entity_map.parquet
```

Las transformaciones Bronze → Silver son:

- reproducibles;
- auditables;
- tipadas;
- validadas;
- diseñadas para ejecución out-of-core cuando el volumen lo exige;
- idempotentes cuando es posible.

Los campos contractuales mutables/post-`t0` se segregan físicamente y la ambigüedad de entity resolution se preserva en lugar de forzar correspondencias. Gold vuelve a auditar point-in-time correctness antes de autorizar cualquier feature.

---

## Gold

M3 materializó la capa analítica point-in-time `m3-gold-v1`, incluyendo labels, splits, features y el model matrix consumido por M4.

```text
labels/
features/
splits/
ml/argos_v1.parquet
```

La granularidad V1 es:

```text
1 fila = 1 contrato evaluado en t0
```

El model matrix contiene 4,783,128 contratos asignados a TRAIN/VALIDATION/TEST y 41 features autorizadas por el feature registry. M4 consumió este contrato sin reconstruir features desde Bronze/Silver.

---

# 7. Estructura del repositorio

```text
argos-code/
│
├── artifacts/
│   ├── manifests/
│   └── models/
│
├── configs/
│   ├── datasets.toml
│   ├── project.toml
│   ├── silver.toml
│   ├── gold.toml
│   ├── modeling.toml
│   └── robustness.toml
│
├── data/
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   ├── modeling/
│   └── robustness/
│
├── docs/
│   ├── problem-definition.md
│   ├── ARGOS_analytical_framing_workspace.md
│   ├── M1_RUNBOOK.md
│   ├── M2_RUNBOOK.md
│   ├── M3_HANDOFF.md
│   ├── M3_RUNBOOK.md
│   ├── M4_HANDOFF.md
│   ├── M4_RUNBOOK.md
│   ├── M5_HANDOFF.md
│   ├── M5_RUNBOOK.md
│   ├── README.md
│   ├── data-dictionary/
│   ├── decisions/
│   ├── models/
│   ├── monitoring/
│   └── target-specs/
│
├── notebooks/
│   ├── 00_bronze_inventory.ipynb
│   ├── 01_schema_and_semantic_profiling.ipynb
│   ├── 02_grain_keys_and_duplicates.ipynb
│   ├── 03_relationships_and_join_coverage.ipynb
│   ├── 04_temporal_audit.ipynb
│   ├── 05_data_quality_audit.ipynb
│   ├── 06_target_feasibility.ipynb
│   ├── 07_m1_gate.ipynb
│   ├── 10_silver_contracts_processes.ipynb
│   ├── 11_silver_suppliers_bidders.ipynb
│   ├── 12_silver_events.ipynb
│   ├── 13_entity_resolution.ipynb
│   ├── 14_silver_validation.ipynb
│   ├── 15_m2_gate.ipynb
│   ├── 20_target_engineering.ipynb
│   ├── 21_temporal_split_design.ipynb
│   ├── 22_train_eda.ipynb
│   ├── 23_contract_features.ipynb
│   ├── 24_historical_features.ipynb
│   ├── 25_competition_relationship_features.ipynb
│   ├── 26_gold_point_in_time_audit.ipynb
│   ├── 27_m3_gate.ipynb
│   ├── 30_baseline_heuristics.ipynb
│   ├── 31_logistic_regression_baseline.ipynb
│   ├── 32_boosting_models.ipynb
│   ├── 33_calibration_and_ranking.ipynb
│   ├── 34_error_analysis_and_explainability.ipynb
│   ├── 35_ablation_studies.ipynb
│   ├── 36_business_impact.ipynb
│   ├── 37_m4_gate.ipynb
│   ├── 40_temporal_backtesting.ipynb
│   ├── 41_explainability.ipynb
│   ├── 42_uncertainty_and_ranking_stability.ipynb
│   ├── 43_drift_and_calibration_monitoring.ipynb
│   ├── 44_feature_family_revalidation.ipynb
│   ├── 45_fresh_oot_2026.ipynb
│   ├── 46_preproduction_readiness.ipynb
│   └── 47_m5_gate.ipynb
│
├── pipelines/
│   ├── build_silver_contracts_processes.py
│   ├── build_gold_m3.py
│   ├── run_modeling_m4.py
│   └── run_robustness_m5.py
│
├── reports/
│   ├── experiments/
│   ├── figures/
│   ├── profiling/
│   ├── quality/
│   ├── silver/
│   ├── gold/
│   ├── modeling/
│   └── robustness/
│
├── scripts/
│   ├── bootstrap_workspace.sh
│   ├── evaluate_m1_gate.py
│   ├── evaluate_m3_gate.py
│   ├── evaluate_m4_gate.py
│   └── evaluate_m5_gate.py
│
├── sql/
│
├── src/
│   └── argos/
│       ├── common/
│       ├── config/
│       ├── entities/
│       ├── evaluation/
│       ├── features/
│       ├── gold/
│       ├── ingestion/
│       ├── models/
│       ├── profiling/
│       ├── quality/
│       ├── robustness/
│       ├── silver/
│       └── targets/
│
├── tests/
│   ├── integration/
│   └── unit/
│
├── .gitignore
├── pyproject.toml
├── uv.lock
└── README.md
```

---

# 8. Estado actual del proyecto

ARGOS completó y cerró formalmente su primer experimento predictivo V1 sobre la capa Gold point-in-time. El milestone activo es:

```text
M5 — Advanced Data Science & Robustness
```

Estado de milestones:

```text
M1 — Bronze Data Understanding & Target Feasibility   ✅ CLOSED — 19/19
M2 — Silver / Canonical Data Model                    ✅ CLOSED — 10/10
M3 — Gold / Point-in-Time Analytical Layer            ✅ CLOSED — 13/13
M4 — Modeling & Evaluation                            ✅ CLOSED — 14/14
M5 — Advanced Data Science & Robustness               ▶ IN PROGRESS
```

M4 quedó cerrado por `37_m4_gate.ipynb` con **14/14 checks bloqueantes aprobados**. El gate verificó la cadena completa `30`–`36`, presencia de reportes y manifests, consistencia de schema `m4-model-v1`, aislamiento del conjunto TEST, hashes del modelo/calibrador congelados antes de TEST y persistencia de la model card.

El modelo V1 seleccionado es:

```text
modelo       = hist_gradient_boosting
calibración  = isotonic
Gold schema  = m3-gold-v1
Model schema = m4-model-v1
target       = y_addition_180d
```

Resultado final sobre el **TEST temporal congelado de 2025**:

| métrica | resultado |
|---|---:|
| filas TEST | 1,050,857 |
| positivos | 10,983 |
| prevalencia | 1.0451% |
| PR-AUC | 0.135250 |
| ROC-AUC | 0.872745 |
| Log Loss | 0.045136 |
| Brier | 0.009638 |
| ECE | 0.002843 |
| Precision@1% | 26.4155% |
| Recall@1% | 25.2754% |
| Lift@1% | 25.274x |

A una capacidad predeclarada de revisión del **1%**, ARGOS priorizó 10,509 contratos y capturó 2,776 de los 10,983 positivos del TEST. Estas métricas describen utilidad de priorización; no representan ahorro monetario, corrupción, fraude ni una conclusión jurídica.

### Interpretación profesional del cierre M4

El cierre de M4 valida un **experimento predictivo V1 reproducible y temporalmente evaluado**. No equivale a autorización de producción. La revisión de cierre documenta de forma explícita restricciones que deben viajar a M5/M6:

- el TEST 2025 ya fue consumido y no puede volver a tratarse como holdout virgen para seleccionar mejoras futuras;
- existe drift/base-rate shift relevante entre TRAIN, las dos mitades de VALIDATION y TEST;
- la calibración global es razonable, pero el extremo superior del score todavía requiere monitoreo específico;
- los ablations no demuestran valor incremental monotónico de las 41 features: bajo el protocolo reducido, `contract + historical` mejora PR-AUC frente a `contract`, mientras `all` no domina; las features de competencia requieren revalidación;
- `34_error_analysis_and_explainability.ipynb` materializa diagnóstico por segmentos y deciles, pero M4 no persiste atribuciones de features tipo permutation importance/SHAP. Esto no bloquea el cierre experimental, pero sí debe resolverse antes de una propuesta de producción.
- la calibración isotónica introduce empates de score; antes de operación debe congelarse un desempate explícito (`calibrated_score`, luego `raw_score`, luego `contract_id`) y medirse la sensibilidad top-K;
- los artefactos `joblib` deben ejecutarse con un runtime versionado compatible con el lock que los produjo.

Documentos de autoridad:

```text
docs/decisions/M1_GATE.md
docs/decisions/M2_GATE.md
docs/decisions/M3_GATE.md
docs/decisions/M4_GATE.md
docs/decisions/M4_CLOSURE_REVIEW_2026-09-23.md
docs/models/ARGOS_V1_MODEL_CARD.md
docs/M5_HANDOFF.md
```

# 9. Notebooks y gates de M1–M5

Los notebooks deben ejecutarse **en orden**.

## `00_bronze_inventory.ipynb`

### Objetivo

Responder:

> ¿Qué datos tengo realmente?

Genera un inventario de los snapshots Bronze:

```text
dataset
filename
file_size
row_count
column_count
source_id
parse_mode
elapsed_seconds
```

Salida principal:

```text
reports/profiling/dataset_inventory.parquet
```

---

## `01_schema_and_semantic_profiling.ipynb`

### Objetivo

Responder:

> ¿Qué columnas existen y qué significan técnicamente?

Perfila:

```text
physical_type
semantic_type
null_count
null_rate
approx_distinct_count
examples
min
max
temporal_role_hint
leakage_risk_hint
```

Salida:

```text
reports/profiling/column_profile.parquet
```

---

## `02_grain_keys_and_duplicates.ipynb`

### Objetivo

Responder:

> ¿Qué representa exactamente una observación y qué identificadores podrían funcionar como claves?

Para cada clave candidata se estudia:

```text
null_key_rate
uniqueness_ratio
duplicate_excess_rows
max_multiplicity
```

Salida:

```text
reports/profiling/key_analysis.parquet
```

---

## `03_relationships_and_join_coverage.ipynb`

### Objetivo

Responder:

> ¿Cómo se relacionan realmente las fuentes?

Las relaciones configuradas son hipótesis que deben validarse con datos.

Se analizan métricas como:

### Coverage

\[
Coverage =
\frac{MatchedLeftRows}{LeftRows}
\]

### Expansion

\[
Expansion =
\frac{RowsAfterJoin}{RowsBeforeJoin}
\]

También se estudian:

```text
multiplicity
null keys
unmatched rows
right-side duplicates
```

Salida:

```text
reports/profiling/join_analysis.parquet
```

---

## `04_temporal_audit.ipynb`

### Objetivo

Responder:

> ¿Cómo funciona el tiempo y qué timestamp puede representar `t0`?

Se estudian:

```text
date coverage
parse success rate
min timestamp
max timestamp
temporal ordering
```

También se auditan reglas como:

```text
firma <= inicio
inicio <= fin
```

Salida:

```text
reports/profiling/temporal_profile.parquet
reports/profiling/temporal_rules.parquet
```

---

## `05_data_quality_audit.ipynb`

### Objetivo

Responder:

> ¿Qué problemas de calidad podrían comprometer el análisis?

Consolida evidencia de:

```text
missingness
keys
joins
dates
money
possible leakage
```

Salida principal:

```text
reports/quality/quality_issue_register.parquet
```

---

## `06_target_feasibility.ipynb`

### Objetivo

Responder:

> ¿Es científicamente viable construir `y_addition_180d`?

Se estudia:

```text
contratos elegibles
contratos censurados
positivos
negativos
prevalencia

30 días
90 días
180 días
365 días
```

También se revisan inconsistencias como:

```text
ambiguous t0
events <= t0
missing event timestamps
```

Salidas:

```text
reports/profiling/target_feasibility_horizons.parquet
reports/profiling/target_feasibility_diagnostics.parquet
reports/profiling/target_feasibility_by_year.parquet
```

---

## `07_m1_gate.ipynb`

### Objetivo

Responder de forma reproducible:

> ¿La evidencia de M1 es suficiente para iniciar Silver?

El gate consume los reportes de `00`–`06` y valida criterios bloqueantes sobre inventario, grain, relaciones, tiempo, target y leakage. No cierra M1 simplemente porque los notebooks hayan ejecutado.

Salidas:

```text
reports/profiling/m1_gate_report.parquet
docs/decisions/M1_GATE.md
```

La transición a Silver está autorizada únicamente cuando imprime:

```text
M1 ✅ CLOSED
```


## `10_silver_contracts_processes.ipynb`

Canonicaliza contratos y procesos, segrega estado mutable/post-`t0`, preserva variantes de procesos y materializa links contrato→proceso sin expansión accidental. **Resultado: 10/10 checks bloqueantes.**

## `11_silver_suppliers_bidders.ipynb`

Canonicaliza suppliers y participaciones de proponentes, materializa el mapa procedimiento→proceso y los links bidder→process. **Resultado: 6/6 checks bloqueantes.**

## `12_silver_events.ipynb`

Canonicaliza Adiciones con procesamiento out-of-core, preserva todos los tipos de evento y produce eventos únicos enlazables con contratos. **Resultado: 5/5 checks bloqueantes.**

## `13_entity_resolution.ipynb`

Resuelve bidder→supplier únicamente mediante estrategias determinísticas auditables y preserva `unresolved`/`ambiguous` cuando no existe evidencia suficiente. **Resultado: 4/4 checks bloqueantes.**

## `14_silver_validation.ipynb`

Valida integridad cruzada, manifests, schema, relaciones y deuda explícita de M2. **Resultado: 8/8 checks bloqueantes.**

## `15_m2_gate.ipynb`

Es la autoridad formal de transición M2→M3. Consume evidencia persistida de `10`–`14` y cerró M2 con:

```text
M2 ✅ CLOSED
Blocking checks: 10/10
```

La decisión persistida está en `docs/decisions/M2_GATE.md`.

## `20_target_engineering.ipynb`

Congela y materializa `y_addition_180d` con `ADICION EN EL VALOR` como evento positivo, ventana `(t0, t0+180d]` y censura explícita. **Resultado: 13/13 checks bloqueantes.**

## `21_temporal_split_design.ipynb`

Congela train 2015–2023, validation 2024 y test 2025. El test no participa en feature engineering ni tuning. **Resultado: 7/7 checks bloqueantes.**

## `22_train_eda.ipynb`

Realiza EDA orientado a modelado exclusivamente sobre TRAIN. **Resultado: 3/3 checks bloqueantes.**

## `23_contract_features.ipynb`

Materializa una whitelist conservadora de features contractuales y vuelve a bloquear campos mutables/post-`t0`. **Resultado: 4/4 checks bloqueantes.**

## `24_historical_features.ipynb`

Construye históricos de proveedor, entidad y relación proveedor–entidad usando solo timestamps estrictamente anteriores a `t0`. **Resultado: 3/3 checks bloqueantes.**

## `25_competition_relationship_features.ipynb`

Construye features de competencia únicamente con participaciones demostrablemente publicadas hasta `t0`. **Resultado: 3/3 checks bloqueantes.**

## `26_gold_point_in_time_audit.ipynb`

Audita grain, labels, timestamps y leakage; solo entonces materializa `data/gold/ml/argos_v1.parquet`. **Resultado: 8/8 checks bloqueantes; 41 features auditadas.**

## `27_m3_gate.ipynb`

Autoridad formal de cierre M3. Cerró el milestone con:

```text
M3 ✅ CLOSED
Blocking checks: 13/13
```

La decisión persistida está en `docs/decisions/M3_GATE.md`.

---

## `30_baseline_heuristics.ipynb`

Evalúa baseline de prevalencia y heurística histórica sin usar TEST. **Resultado: 4/4 checks bloqueantes.** La heurística alcanza PR-AUC 0.039690 y Lift@1% 9.390x sobre VALIDATION completo.

## `31_logistic_regression_baseline.ipynb`

Entrena una regresión logística mediante `SGDClassifier(loss="log_loss")` sobre TRAIN completo en batches. **Resultado: 4/4 checks bloqueantes.** Su score raw discrimina, pero presenta calibración pobre; M4 no oculta esa limitación y la trata posteriormente.

## `32_boosting_models.ipynb`

Entrena `HistGradientBoostingClassifier` sobre una muestra TRAIN determinística de 750,000 filas y evalúa VALIDATION completo. **Resultado: 4/4 checks bloqueantes.** Obtiene PR-AUC 0.064529, ROC-AUC 0.853849 y Lift@1% 11.165x antes de calibración.

## `33_calibration_and_ranking.ipynb`

Divide VALIDATION temporalmente: primera mitad para ajustar calibración y segunda mitad para seleccionar. Compara los candidatos y `none`/`sigmoid`/`isotonic`; congela modelo y calibrador con SHA-256 antes de TEST. **Resultado: 6/6 checks bloqueantes.** Selección: `hist_gradient_boosting + isotonic`, con Lift@1% 17.027x en la población de selección.

## `34_error_analysis_and_explainability.ipynb`

Realiza diagnóstico de errores por segmentos y deciles sobre la población de selección, sin TEST. **Resultado: 3/3 checks bloqueantes.** En M4 V1 su alcance real es error analysis/segment diagnostics; la atribución explícita de features queda como deuda de robustez para M5.

## `35_ablation_studies.ipynb`

Compara `contract`, `contract + historical` y `all` bajo un presupuesto fijo de entrenamiento. **Resultado: 4/4 checks bloqueantes.** Los resultados no muestran dominancia de la familia completa; esta evidencia se conserva como limitación y línea de trabajo para M5.

## `36_business_impact.ipynb`

Único notebook autorizado para consumir el TEST 2025. Verifica hashes de los artefactos congelados, evalúa el TEST completo y materializa métricas, curva de capacidad y model card. **Resultado: 5/5 checks bloqueantes.** Resultado principal: PR-AUC 0.135250, ROC-AUC 0.872745 y Lift@1% 25.274x.

## `37_m4_gate.ipynb`

Autoridad formal de cierre M4. Verifica componentes `30`–`36`, artefactos, manifests, schema, política de aislamiento de TEST, hashes congelados y model card. Cerró el milestone con:

```text
M4 ✅ CLOSED
Blocking checks: 14/14
```

La decisión computable se conserva en `docs/decisions/M4_GATE.md`.

---

## `40_temporal_backtesting.ipynb`

Ejecuta rolling-origin backtesting `2021–2024` con la receta HGB fijada y sin reutilizar TEST 2025. Persistirá métricas y Lift@K por fold.

## `41_explainability.ipynb`

Materializa permutation importance global, resumen por familia y sensibilidad local por sustitución de una feature hacia un valor de referencia. Las explicaciones son predictivas, no causales.

## `42_uncertainty_and_ranking_stability.ipynb`

Añade intervalos mediante calendar-week block bootstrap y congela el desempate operacional `calibrated_score DESC → raw_score DESC → contract_id ASC`.

## `43_drift_and_calibration_monitoring.ipynb`

Mide drift de features y scores, categorías nuevas y calibración explícita en la cola de mayor score. TEST 2025 aparece únicamente como benchmark histórico consumido.

## `44_feature_family_revalidation.ipynb`

Repite ablations de familias sobre varios años con el mismo algoritmo, muestra y presupuesto. Cuantifica de forma específica el incremento de `competition` frente a `contract + historical`.

## `45_fresh_oot_2026.ipynb`

Construye la cohorte 2026 completamente observable para el horizonte de 180 días y evalúa el **V1 congelado**, sin reselección. Es un holdout parcial de año y su limitación estacional queda explícita.

## `46_preproduction_readiness.ipynb`

Sintetiza evidencia y genera `ARGOS_V1_ROBUSTNESS_CARD.md` y `ARGOS_V1_MONITORING_SPEC.md`. Su aprobación no autoriza producción.

## `47_m5_gate.ipynb`

Gate formal de M5: valida `40–46`, lineage, hashes, fresh OOT, documentación y gobernanza. Solo entonces puede persistir `M5 ✅ CLOSED`.

---

# 10. Arquitectura del código

Los notebooks **no contienen la lógica principal del proyecto**.

Su responsabilidad es:

```text
orquestar
visualizar
interpretar
documentar evidencia
```

La lógica reusable vive en:

```text
src/argos/
```

Ejemplo:

```python
from argos.profiling.inventory import build_inventory
```

Este diseño permite:

- reutilización;
- unit testing;
- pipelines posteriores;
- menor duplicación;
- migración a producción;
- ejecución fuera de Jupyter.

---

## Principio

```text
Notebook
=
investigación + narrativa + visualización

src/argos/
=
lógica reusable + testeable
```

---

# 11. Configuración

La configuración está externalizada y versionada:

```text
configs/
├── datasets.toml
├── project.toml
├── silver.toml
├── gold.toml
├── modeling.toml
└── robustness.toml
```

`datasets.toml` describe fuentes y relaciones candidatas; `silver.toml` y `gold.toml` congelan contratos de datos; `modeling.toml` congela el protocolo M4 antes de TEST; y `robustness.toml` congela el protocolo M5, incluyendo rolling folds, bootstrap, drift thresholds, desempate del ranking y gobernanza del fresh OOT 2026.

El contrato M4 activo durante el experimento fue:

```text
schema_version       = m4-model-v1
model_matrix         = data/gold/ml/argos_v1.parquet
target               = y_addition_180d
operational_fraction = 0.01
final_test_notebook  = 36
```

La configuración externa evita hardcodear decisiones metodológicas dentro de notebooks y permite auditar qué protocolo produjo cada manifest.

---

# 12. Instalación

## Requisitos

```text
Python >= 3.12
uv
Git
```

El proyecto utiliza `uv` para gestión del entorno y dependencias.

---

## 1. Clonar el repositorio

```bash
git clone <URL_DEL_REPOSITORIO>
cd argos-code
```

---

## 2. Instalar dependencias

```bash
uv sync
```

Esto instalará las dependencias declaradas en:

```text
pyproject.toml
```

y respetará:

```text
uv.lock
```

---

## 3. Registrar el kernel de Jupyter

```bash
uv run python -m ipykernel install \
  --user \
  --name argos \
  --display-name "Python (ARGOS)"
```

---

## 4. Iniciar JupyterLab

```bash
uv run jupyter lab
```

En VS Code o Jupyter selecciona:

```text
Python (ARGOS)
```

---

# 13. Ejecución

Los CSV originales deben ubicarse en `data/bronze/`; los datos no forman parte del código fuente del proyecto.

La secuencia histórica cerrada es:

```text
00 → 01 → 02 → 03 → 04 → 05 → 06 → 07_m1_gate  → M1 ✅ CLOSED
10 → 11 → 12 → 13 → 14 → 15_m2_gate            → M2 ✅ CLOSED
20 → 21 → 22 → 23 → 24 → 25 → 26 → 27_m3_gate  → M3 ✅ CLOSED
30 → 31 → 32 → 33 → 34 → 35 → 36 → 37_m4_gate  → M4 ✅ CLOSED
```

M1–M4 se consideran congelados. No deben reejecutarse por rutina. Se reabren únicamente si cambia una fuente, target, split, feature contract, schema o implementación cuya modificación invalide evidencia previa.

Para M5, `docs/M5_HANDOFF.md` es el contrato vigente. TEST 2025 queda consumido como evaluación final V1 y no debe reutilizarse como holdout independiente para escoger nuevas mejoras.

> Bronze puede requerir scans de CSV multi-GB; Silver y Gold existen precisamente para evitar repetir procesamiento bruto durante experimentación avanzada.

---

# 14. Artefactos generados

Los milestones generan evidencia persistente; los outputs visuales de notebooks no son la única fuente de verdad.

```text
reports/
├── profiling/                 # evidencia M1
├── quality/                   # evidencia M1
├── silver/                    # validaciones y gate M2
├── gold/                      # validaciones, feature registry y gate M3
└── modeling/                  # métricas, predictions, ablations y gate M4

artifacts/
├── manifests/                 # lineage M2–M4
└── models/m4/                 # modelos, calibrador y selección congelada

docs/decisions/
├── M1_GATE.md
├── M2_GATE.md
├── M3_GATE.md
├── M3_CLOSURE_REVIEW_2026-09-23.md
├── M4_START_2026-09-23.md
├── M4_CODE_READINESS_2026-09-23.md
├── M4_GATE.md
└── M4_CLOSURE_REVIEW_2026-09-23.md

docs/models/
└── ARGOS_V1_MODEL_CARD.md
```

M2 materializó 12 artefactos Silver canónicos; M3 materializó 7 artefactos Gold y `data/gold/ml/argos_v1.parquet`; M4 añadió modelos versionados, predicciones de validación/TEST, métricas de ranking y calibración, ablations, model card y manifests con hashes.

Estos artefactos deben conservarse junto con la versión de código que los produjo. En particular, `selected_model.json`, `m4_final_test.json` y `M4_GATE.md` forman una cadena de evidencia sobre la selección pre-TEST y la evaluación final.

---

# 15. Calidad, pruebas y estilo

El proyecto utiliza:

```text
pytest
ruff
mypy
```

## Tests

```bash
uv run pytest
```

Con cobertura:

```bash
uv run pytest --cov=src/argos
```

---

## Lint

```bash
uv run ruff check .
```

Aplicar correcciones seguras:

```bash
uv run ruff check . --fix
```

---

## Formato

```bash
uv run ruff format .
```

---

## Type checking

```bash
uv run mypy src
```

---

# 16. Gates y criterios de cierre

Los milestones no terminan porque los notebooks ejecuten sin excepción. Terminan cuando existe evidencia persistida suficiente y el gate correspondiente aprueba todos los checks bloqueantes.

## M1 — cierre

`07_m1_gate.ipynb` cerró M1 con **19/19 checks bloqueantes**. La decisión autoritativa está en `docs/decisions/M1_GATE.md`.

## M2 — cierre

`15_m2_gate.ipynb` cerró M2 con **10/10 checks bloqueantes**. El gate verificó:

- checks bloqueantes de `10`–`14`;
- 12 artefactos canónicos completos;
- manifests de lineage;
- schema `m2-silver-v1` consistente;
- cero issues bloqueantes;
- entity resolution auditada sin forzar matches ambiguos.

La decisión autoritativa está en `docs/decisions/M2_GATE.md`.

## M3 — cierre

`27_m3_gate.ipynb` cerró M3 con **13/13 checks bloqueantes**. El gate verificó:

- checks bloqueantes de `20`–`26`;
- 7 artefactos Gold canónicos completos;
- manifests de lineage Gold;
- schema `m3-gold-v1` consistente;
- target `y_addition_180d` congelado y validado;
- split train/validation/test congelado;
- auditoría point-in-time sin violaciones detectadas;
- cero issues Gold bloqueantes o warnings registrados.

La decisión autoritativa está en `docs/decisions/M3_GATE.md`.

## M4 — cierre

`37_m4_gate.ipynb` cerró M4 con **14/14 checks bloqueantes**. El gate verificó:

- checks bloqueantes de `30`–`36`;
- reportes y manifests M4 completos;
- schema `m4-model-v1` consistente;
- separación temporal de calibración/selección;
- aislamiento de TEST durante `30`–`35`;
- hashes de modelo y calibrador congelados antes del acceso a TEST;
- evaluación final sobre las 1,050,857 filas del TEST;
- model card persistida.

La decisión autoritativa está en `docs/decisions/M4_GATE.md` y la revisión metodológica posterior en `docs/decisions/M4_CLOSURE_REVIEW_2026-09-23.md`.

## Regla de transición a M5

M5 puede investigar modelos y componentes avanzados, pero el TEST 2025 debe considerarse **consumido**. No puede reutilizarse como conjunto independiente para seleccionar nuevas features, modelos, hiperparámetros o calibradores. Cualquier nueva afirmación de generalización requerirá backtesting temporal adicional y, para una nueva evaluación final, un holdout temporal posterior no utilizado durante el desarrollo. El contrato de entrada está en `docs/M5_HANDOFF.md`.

---

# 17. Roadmap

## M1 — Data Understanding & Target Feasibility

```text
Bronze inventory
Schema profiling
Grain
Keys
Relationships
Temporal audit
Quality
Target feasibility
```

**Estado:** ✅ CLOSED — 19/19 checks bloqueantes.

---

## M2 — Silver / Canonical Data Model

Objetivo alcanzado:

```text
Bronze
   ↓
typing + canonicalization + lineage
entity resolution determinística
quality gates
   ↓
Silver m2-silver-v1
```

Resultados principales:

- 12 artefactos canónicos materializados;
- Contracts, Processes, Suppliers, Bidders y Additions canonicalizados;
- estado contractual mutable segregado;
- relaciones canónicas sin join explosion;
- entity resolution ambigua/no resuelta preservada explícitamente;
- manifests y validación cruzada persistidos;
- `15_m2_gate.ipynb`: **10/10 checks bloqueantes**.

**Estado:** ✅ CLOSED.

Autoridad: `docs/decisions/M2_GATE.md`.

---

## M3 — Gold / Point-in-Time Analytical Layer

**Estado:** ✅ CLOSED — 13/13 checks bloqueantes.

Resultados principales:

```text
target y_addition_180d congelado y validado
split temporal congelado
EDA de decisiones restringido a TRAIN
features contractuales conservadoras
históricos estrictamente anteriores a t0
competencia observable <= t0
model matrix auditado
41 features autorizadas
4,783,128 filas train/validation/test
```

Autoridad: `docs/decisions/M3_GATE.md`. Handoff a Modeling: `docs/M4_HANDOFF.md`.

---

## M4 — Modeling & Evaluation

**Estado:** ✅ CLOSED — 14/14 checks bloqueantes.

Resultados principales:

```text
selected model   hist_gradient_boosting
calibration      isotonic
TEST rows        1,050,857
TEST prevalence  1.0451%
PR-AUC           0.135250
ROC-AUC          0.872745
Brier            0.009638
ECE              0.002843
Precision@1%     26.4155%
Recall@1%        25.2754%
Lift@1%          25.274x
```

La selección quedó congelada mediante hashes antes del único acceso a TEST. `37_m4_gate.ipynb` verificó 14/14 checks bloqueantes. Autoridad: `docs/decisions/M4_GATE.md`. Revisión de cierre: `docs/decisions/M4_CLOSURE_REVIEW_2026-09-23.md`.

M4 cierra el **experimento predictivo V1**, no la preparación para producción. El TEST 2025 queda consumido y no puede reciclarse como holdout independiente en M5.

---

## M5 — Advanced Data Science & Robustness

**Estado:** ▶ IN PROGRESS.

M5 parte del ARGOS V1 congelado y fortalece evidencia antes de aumentar complejidad. El protocolo activo es `m5-robustness-v1` y se ejecuta mediante notebooks `40–47`:

```text
40  rolling-origin temporal backtesting
41  explainability global y local
42  incertidumbre + estabilidad del ranking
43  drift + calibración de cola
44  revalidación de familias de features
45  fresh OOT 2026 con V1 congelado
46  contrato de monitoreo / evidencia pre-producción
47  gate M5
```

Modelos o señales adicionales —CatBoost/LightGBM/XGBoost, supervivencia, anomalías, NLP, grafos, causalidad, forecasting y risk fusion— quedan **autorizados para investigación posterior**, pero no se promueven en este paquete solo por añadir complejidad. Primero debe cerrarse la evidencia de robustez del benchmark V1.

La regla central es que componentes avanzados deben demostrar **valor incremental** mediante ablations y evaluación temporal. TEST 2025 ya no es un holdout virgen. El fresh OOT 2026 se reserva hasta completar `40–44` y el pipeline exige `--consume-fresh-oot` para consumirlo. Handoff: `docs/M5_HANDOFF.md`. Runbook: `docs/M5_RUNBOOK.md`.

---

## M6 — Producción y MLOps

Futuro:

```text
reproducible pipelines
experiment tracking
model registry
API
monitoring
drift detection
CI/CD
cloud deployment
```

La arquitectura local busca mantener un núcleo portable para una migración futura a plataformas cloud.

---

# 18. Riesgos metodológicos

ARGOS debe controlar explícitamente:

## Data leakage

Información generada después de `t0` no puede utilizarse como feature.

Ejemplos potencialmente peligrosos:

```text
valor_pagado
valor_facturado
dias_adicionados
fecha_fin_liquidacion
estado posterior del contrato
```

---

## Snapshot actual vs. estado histórico

Un contrato antiguo puede aparecer en un snapshot reciente con valores actualizados posteriormente.

Que una columna esté presente en el CSV no significa que hubiese tenido ese mismo valor en `t0`.

---

## Right censoring

Los contratos recientes pueden no tener una ventana de observación suficiente.

---

## Entity resolution

NIT, códigos y nombres pueden presentar:

```text
formatos inconsistentes
duplicados
cambios de razón social
consorcios
uniones temporales
abreviaciones
```

Una fusión incorrecta puede contaminar todo el historial de una entidad.

---

## Join explosion

Una relación N:M mal interpretada puede duplicar observaciones y cambiar silenciosamente la unidad estadística.

Por ello cada relación debe medir:

```text
coverage
uniqueness
multiplicity
expansion
```

---

## Missingness no aleatorio

El missingness puede depender del año, modalidad, tipo de entidad o cambios en el sistema.

No se debe aplicar `dropna()` de forma indiscriminada.

---

## Temporal drift

El proceso de contratación y la captura de SECOP II pueden cambiar con el tiempo.

Por ello la validación principal será temporal.

---

## Target imperfecto

Una adición contractual:

```text
NO equivale a corrupción
NO equivale a fraude
NO equivale automáticamente a irregularidad
```

Representa un evento contractual posterior que puede ser útil para priorización analítica.

---

# 19. Convenciones de trabajo

## Git

Se versiona:

```text
código
configuración
tests
notebooks
documentación
SQL
```

No deben versionarse datasets masivos ni artefactos generados innecesariamente. Los artefactos pequeños de gobernanza que materializan decisiones de gate, manifests y especificaciones sí se conservan cuando forman parte del contrato de reproducibilidad.

Checkpoint recomendado para el cierre actual:

```bash
git add .
git commit -m "feat(silver): completa la capa canónica y cierra M2"
git tag m2-cerrado
```

---

## Bronze es inmutable

```text
data/bronze/
```

es read-only desde la perspectiva del pipeline.

---

## Notebooks delgados

Evitar:

```text
800 líneas de transformación
dentro de un notebook
```

Preferir:

```python
from argos.profiling.inventory import build_inventory
```

---

## Decisiones documentadas

Las decisiones metodológicas importantes deben quedar registradas.

Ejemplos futuros:

```text
docs/decisions/
├── 001-select-prediction-timestamp.md
├── 002-canonical-supplier-id.md
└── 003-label-cutoff-policy.md
```

---

## Experimentos reproducibles

Un resultado debe poder reconstruirse a partir de:

```text
código
configuración
snapshot de datos
split temporal
features
target
versión del modelo
```

---

# 20. Fuentes oficiales

## SECOP II — Procesos de Contratación

https://www.datos.gov.co/Estad-sticas-Nacionales/SECOP-II-Procesos-de-Contrataci-n/p6dx-8zbt/about_data

Dataset ID:

```text
p6dx-8zbt
```

---

## SECOP II — Contratos Electrónicos

https://www.datos.gov.co/Estad-sticas-Nacionales/SECOP-II-Contratos-Electr-nicos/jbjy-vk9h

Dataset ID:

```text
jbjy-vk9h
```

---

## Proponentes por Proceso — SECOP II

https://www.datos.gov.co/Estad-sticas-Nacionales/Proponentes-por-Proceso-SECOP-II/hgi6-6wh3/about_data

Dataset ID:

```text
hgi6-6wh3
```

---

## SECOP II — Proveedores Registrados

https://www.datos.gov.co/Estad-sticas-Nacionales/SECOP-II-Proveedores-Registrados/qmzu-gj57/about_data

Dataset ID:

```text
qmzu-gj57
```

---

## SECOP II — Adiciones

https://www.datos.gov.co/Estad-sticas-Nacionales/SECOP-II-Adiciones/cb9c-h8sn/about_data

Dataset ID:

```text
cb9c-h8sn
```

---

## SECOP II — Multas y Sanciones

https://www.datos.gov.co/Estad-sticas-Nacionales/SECOPII-Multas-y-Sanciones/it5q-hg94/about_data

Dataset ID:

```text
it5q-hg94
```

---

## SECOP II — Plan de pagos

https://www.datos.gov.co/Estad-sticas-Nacionales/SECOP-II-Plan-de-pagos/uymx-8p3j/about_data

Dataset ID:

```text
uymx-8p3j
```

---

# Principio rector

> **Primero construir una representación histórica correcta del mundo; después intentar predecirlo.**

La complejidad algorítmica no compensa un dataset incorrecto, una etiqueta mal definida o una fuga temporal.

ARGOS prioriza:

```text
validez
reproducibilidad
trazabilidad
temporal correctness
interpretabilidad
impacto en la decisión
```

antes que complejidad técnica.


## Gates automatizados

`07_m1_gate.ipynb` cerró M1 con **19/19 checks bloqueantes**. `15_m2_gate.ipynb` cerró M2 con **10/10**. `27_m3_gate.ipynb` cerró M3 con **13/13**. Las decisiones autoritativas están en:

```text
docs/decisions/M1_GATE.md
docs/decisions/M2_GATE.md
docs/decisions/M3_GATE.md
```

M3 validó empíricamente target, split y point-in-time correctness y materializó el model matrix auditado. M4 hereda de forma explícita la incertidumbre de entity resolution y el cambio temporal de prevalencia; ninguna de estas condiciones autoriza a modificar el conjunto TEST o a introducir información futura.
