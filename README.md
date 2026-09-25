# ARGOS

**Plataforma de inteligencia analítica para priorización de riesgo en contratación pública**

ARGOS es un proyecto de Ciencia de Datos orientado al análisis de contratación pública registrada en **SECOP II**. Su propósito es construir, validar y eventualmente productivizar un sistema capaz de **priorizar contratos para revisión analítica adicional** utilizando únicamente la información que habría estado disponible en el momento de evaluación.

El proyecto está diseñado como un ejercicio de nivel profesional que integra **Data Engineering, Data Quality, modelado temporal, Machine Learning, MLOps, NLP, grafos, detección de anomalías y análisis de supervivencia**, manteniendo como prioridad la validez metodológica y la reproducibilidad.

> **ARGOS no clasifica contratos, proveedores o entidades como corruptos o fraudulentos.**

> Una predicción o anomalía representa una **señal analítica o prioridad de revisión**, no una acusación ni una conclusión jurídica.

**Estado actual:** M1–M6 `CLOSED`; M7 `ACTIVE — EVIDENCE PENDING`; M8 `CLOSED — RESEARCH_COMPLETE_NO_PROMOTION`; implementación científica/técnica `COMPLETE`; M9 `ACTIVE — SERVING BACKEND COMPLETE / FRONTEND INTEGRATED`. La capa M9 expone resultados gobernados mediante un serving read-only derivado, sin modificar Gold, Silver, modelos, manifests ni el protocolo prospectivo de M7.

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

- [9. Notebooks y gates de M1–M6](#9-notebooks-y-gates-de-m1m6)

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

- [21. M7 — Prospective Validation & Operational Evaluation](#21-m7--prospective-validation--operational-evaluation)

- [22. M8 — Advanced Intelligence & Survival](#22-m8--advanced-intelligence--survival)

- [23. Cierre técnico y estado científico](#23-cierre-técnico-y-estado-científico)

- [24. M9 — Plataforma Analítica / Frontend](#24-m9--plataforma-analítica--frontend)

- [25. M9 Serving — integración read-only backend ↔ frontend](#25-m9-serving--integración-read-only-backend--frontend)

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

$$

P(Y_{180}=1 \mid X_{t0})

$$

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

│   ├── robustness.toml

│   └── production.toml

│

├── data/

│   ├── bronze/

│   ├── silver/

│   ├── gold/

│   ├── modeling/

│   ├── robustness/

│   └── production/

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

│   ├── M6_HANDOFF.md

│   ├── M6_RUNBOOK.md

│   ├── POST_M6_OPERATIONS.md

│   ├── operations/

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

│   ├── 47_m5_gate.ipynb

│   ├── 50_runtime_and_registry.ipynb

│   ├── 51_data_contracts_and_preflight.ipynb

│   ├── 52_batch_scoring_and_idempotency.ipynb

│   ├── 53_monitoring_execution.ipynb

│   ├── 54_human_review_and_audit.ipynb

│   ├── 55_shadow_and_rollback_drill.ipynb

│   ├── 56_operational_readiness.ipynb

│   └── 57_m6_gate.ipynb

│

├── pipelines/

│   ├── build_silver_contracts_processes.py

│   ├── build_gold_m3.py

│   ├── run_modeling_m4.py

│   ├── run_robustness_m5.py

│   └── run_production_m6.py

│

├── reports/

│   ├── experiments/

│   ├── figures/

│   ├── profiling/

│   ├── quality/

│   ├── silver/

│   ├── gold/

│   ├── modeling/

│   ├── robustness/

│   └── production/

│

├── scripts/

│   ├── bootstrap_workspace.sh

│   ├── evaluate_m1_gate.py

│   ├── evaluate_m3_gate.py

│   ├── evaluate_m4_gate.py

│   ├── evaluate_m5_gate.py

│   ├── evaluate_m6_gate.py

│   ├── production_preflight.py

│   ├── score_batch.py

│   └── check_notebooks.py

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

│       ├── production/

│       ├── silver/

│       └── targets/

│

├── tests/

│   ├── integration/

│   └── unit/

│

├── .github/workflows/ci.yml

├── Dockerfile

├── .dockerignore

├── pyproject.toml

├── uv.lock

└── README.md
```

---

### Extensiones actuales M7–M9

La estructura anterior se conserva como historia del proyecto. Sobre ella se añadieron las capas prospectiva, avanzada y de serving:
```text
notebooks/
├── 60_prospective_protocol_freeze.ipynb
├── 61_prospective_shadow_cohorts.ipynb
├── 62_outcome_maturation_and_label_lock.ipynb
├── 63_prospective_model_performance.ipynb
├── 64_human_review_operational_utility.ipynb
├── 65_longitudinal_monitoring_and_incidents.ipynb
├── 66_operational_decision.ipynb
├── 67_m7_gate.ipynb
├── 70_semantic_intelligence.ipynb
├── 71_temporal_graph_intelligence.ipynb
├── 72_contextual_anomaly_detection.ipynb
├── 73_m8_matrix_and_pit_audit.ipynb
├── 74_temporal_ablation.ipynb
├── 75_survival_outcomes.ipynb
├── 76_survival_analysis.ipynb
└── 77_m8_gate.ipynb

pipelines/
└── run_advanced_m8.py

src/argos/
├── advanced/
├── anomaly/
├── graph/
├── nlp/
├── survival/
└── serving/
    └── m9.py

scripts/
├── evaluate_m7_gate.py
├── project_status.py
├── execute_notebooks.py
├── clean_notebooks.py
├── build_m9_serving.py
└── serve_m9.py

data/
└── serving/
    └── m9/
        ├── argos-serving.duckdb
        ├── overview.json
        └── manifest.json

reports/
└── serving/
    └── m9_serving_validation.parquet

artifacts/contracts/
└── m9_serving_contract.json
```

La capa `data/serving/m9/` es **derivada, read-only respecto a sus fuentes y regenerable**. No reemplaza la fuente científica de verdad; sirve resultados ya gobernados a la aplicación analítica.

---

# 8. Estado actual del proyecto

ARGOS completó formalmente su implementación científica/técnica y la operacionalización batch-first, shadow y human-in-the-loop. El sistema conserva el estado operativo de M6 `OPERATIONALLY_READY_PROMOTION_BLOCKED`, mientras la evidencia longitudinal se acumula en M7. M8 cerró la investigación avanzada sin promover una nueva familia de features.
```text
M6 operational status            OPERATIONALLY_READY_PROMOTION_BLOCKED

M8 research decision             RESEARCH_COMPLETE_NO_PROMOTION

Technical implementation         COMPLETE

M9 serving                       BUILT — 529,054 rows

M9 scientific backend mutated    NO

Prospective validation           ACTIVE
```

Estado de milestones:
```text
M1 — Bronze Data Understanding & Target Feasibility   ✅ CLOSED — 19/19

M2 — Silver / Canonical Data Model                    ✅ CLOSED — 10/10

M3 — Gold / Point-in-Time Analytical Layer            ✅ CLOSED — 13/13

M4 — Modeling & Evaluation                            ✅ CLOSED — 14/14

M5 — Advanced Data Science & Robustness               ✅ CLOSED — 16/16

M6 — Productionization & MLOps                        ✅ CLOSED — 16/16

M7 — Prospective Validation                           ◐ ACTIVE — evidence pending

M8 — NLP + Graph + Anomaly + Survival                 ✅ CLOSED — NO PROMOTION

M9 — Plataforma Analítica / Frontend                  ◐ ACTIVE — serving complete / frontend integrated
```

M7 permanece como experimento longitudinal independiente y solo puede cerrarse cuando existan cohorts prospectivos maduros. El desarrollo de producto continúa en M9 sin alterar el protocolo de M7, sin reabrir TEST/OOT y sin modificar la decisión de M8.

M9 ya cuenta con una capa backend de serving materializada y validada. El build actual preservó **529,054 contratos** del batch `a8865bfed9374218183eb302` en `data/serving/m9/argos-serving.duckdb`, con `scientific backend mutated: NO`. El serving se construye exclusivamente desde artefactos existentes y opera como capa read-only para el frontend.

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

### Interpretación profesional del cierre M5

M5 resolvió las obligaciones de robustez previstas para ARGOS V1 y cerró con **16/16 checks bloqueantes**. El fresh OOT 2026, evaluado con el modelo/calibrador congelados y sin reselección posterior, contiene 529,054 contratos, prevalencia 1.3713%, PR-AUC 0.053274, ROC-AUC 0.744544 y Lift@1% 6.257x.

La evidencia confirma capacidad de priorización por encima de random fuera del periodo usado en M4, pero también muestra degradación temporal material respecto a TEST 2025. M5 no oculta ese resultado: lo convierte en requisito explícito de monitoreo y gobernanza para M6. El OOT 2026 es además partial-year (`2026-01-01` a `2026-03-13`), por lo que no soporta una afirmación de estabilidad anual completa.

M5 también dejó persistidos explainability, incertidumbre mediante block bootstrap, drift/calibration monitoring, revalidación de familias, ranking determinista, robustness card y monitoring spec. TEST 2025 y OOT 2026 quedan consumidos para ARGOS V1.

Documentos de autoridad:
```text
docs/decisions/M1_GATE.md

docs/decisions/M2_GATE.md

docs/decisions/M3_GATE.md

docs/decisions/M4_GATE.md

docs/decisions/M4_CLOSURE_REVIEW_2026-09-23.md

docs/models/ARGOS_V1_MODEL_CARD.md

docs/decisions/M5_GATE.md

docs/decisions/M5_CLOSURE_REVIEW_2026-09-23.md

docs/models/ARGOS_V1_ROBUSTNESS_CARD.md

docs/monitoring/ARGOS_V1_MONITORING_SPEC.md

docs/M6_HANDOFF.md

docs/decisions/M6_GATE.md

docs/decisions/M6_CLOSURE_REVIEW_2026-09-23.md

docs/operations/ARGOS_V1_OPERATIONAL_RUNBOOK.md
```

### Interpretación profesional del cierre M6

M6 cerró con **16/16 condiciones bloqueantes satisfechas** al reconciliar la evidencia final de `50–56` con el contrato implementado por el gate. El pipeline operacional demostró runtime/registry reproducible, contrato de scoring congelado, scoring batch idempotente, ranking determinista, monitoreo ejecutable, cola Top-K para revisión humana, audit log encadenado por SHA-256 y rollback no destructivo.

El replay operacional materializó **529,054 scores** y una cola del **1% = 5,291 contratos**. Monitoring persistió **14 alertas**, de las cuales **6 son `high`**, y el score PSI fue **1.089164**. Por diseño, esas señales no se silencian: `promotion_blocked=true` y el estado final de M6 es:
```text
OPERATIONALLY_READY_PROMOTION_BLOCKED
```

Esto es un cierre correcto del milestone operacional: la plataforma funciona y sus controles impiden promover un modelo cuando la evidencia de drift no lo justifica. No equivale a autorización de decisiones autónomas ni a promoción irrestricta a producción.

El output cacheado anterior de `57_m6_gate.ipynb` quedó desfasado porque se ejecutó antes de los últimos reruns exitosos de componentes. La reconciliación está documentada en `docs/decisions/M6_CLOSURE_REVIEW_2026-09-23.md`; la decisión previa se preserva como evidencia histórica.

# 9. Notebooks y gates de M1–M6

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

$$

Coverage =

\frac{MatchedLeftRows}{LeftRows}

$$

### Expansion

$$

Expansion =

\frac{RowsAfterJoin}{RowsBeforeJoin}

$$

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

## `50_runtime_and_registry.ipynb`

Valida M5 como prerequisito, runtime compatible con el modelo serializado, hashes de modelo/calibrador y crea el model registry operacional. **No autoriza promoción automática a producción.**

## `51_data_contracts_and_preflight.ipynb`

Materializa el scoring contract de las 41 features congeladas y ejecuta preflight de schema, grain, `t0` y privacidad sobre un batch inmutable.

## `52_batch_scoring_and_idempotency.ipynb`

Ejecuta scoring batch out-of-core con ARGOS V1. El idempotency key depende de input + modelo + calibrador + contrato y la segunda ejecución debe reutilizar exactamente el mismo batch.

## `53_monitoring_execution.ipynb`

Operationaliza thresholds M5 para feature drift, missingness y score drift. Las alertas `high` bloquean promoción; detectar drift no se transforma artificialmente en un fallo del motor de monitoreo.

## `54_human_review_and_audit.ipynb`

Materializa la cola Top-K para analistas, separa evidencia del modelo de decisiones humanas y valida el audit log encadenado por SHA-256.

## `55_shadow_and_rollback_drill.ipynb`

Prueba de forma no destructiva `candidate → shadow → paused → candidate` y verifica que no exista una transición directa a `production`.

## `56_operational_readiness.ipynb`

Sintetiza evidencia de operación, container/CI, monitoring, audit y runbooks de incident response, human review, retraining y seguridad.

## `57_m6_gate.ipynb`

Gate computable de M6. El cierre valida la plataforma operacional; reporta por separado si el estado es `SHADOW_READY` o `OPERATIONALLY_READY_PROMOTION_BLOCKED`.

## Notebooks M7 — validación prospectiva

La secuencia `60–67` implementa el protocolo prospectivo congelado. Su implementación está completa, pero la evidencia no puede madurarse artificialmente:

- `60_prospective_protocol_freeze.ipynb`: congela protocolo y umbrales;
- `61_prospective_shadow_cohorts.ipynb`: materializa cohorts futuras de scoring en shadow;
- `62_outcome_maturation_and_label_lock.ipynb`: bloquea outcomes cuando existe follow-up suficiente;
- `63_prospective_model_performance.ipynb`: evalúa desempeño estadístico prospectivo;
- `64_human_review_operational_utility.ipynb`: mide utilidad de revisión humana;
- `65_longitudinal_monitoring_and_incidents.ipynb`: consolida monitoring e incidentes longitudinales;
- `66_operational_decision.ipynb`: produce una decisión gobernada sin promoción automática;
- `67_m7_gate.ipynb`: autoridad formal de cierre cuando existan cohorts maduras suficientes.

**Estado:** `ACTIVE / EVIDENCE PENDING`.

---

## Notebooks M8 — inteligencia avanzada y supervivencia

La secuencia `70–77` está cerrada:

- `70_semantic_intelligence.ipynb`: embeddings semánticos y peers temporales;
- `71_temporal_graph_intelligence.ipynb`: features de grafo temporales;
- `72_contextual_anomaly_detection.ipynb`: anomalías contextuales con entrenamiento restringido;
- `73_m8_matrix_and_pit_audit.ipynb`: matriz M8 y auditoría point-in-time;
- `74_temporal_ablation.ipynb`: comparación de familias bajo protocolo temporal común;
- `75_survival_outcomes.ipynb`: outcomes y censura administrativa;
- `76_survival_analysis.ipynb`: Kaplan–Meier, Cox PH penalizado y evaluación de supervivencia;
- `77_m8_gate.ipynb`: gate formal M8.

**Resultado:** `M8 ✅ CLOSED — RESEARCH_COMPLETE_NO_PROMOTION`.

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
from argos.profiling.inventory *import* build_inventory
```

Este diseño permite:

- reutilización;

- unit testing;

- pipelines posteriores;

- menor duplicación;

- migración a producción;

- ejecución fuera de Jupyter.

---

M9 añade una frontera explícita entre ciencia y producto:
```text
ARGOS científico
Bronze → Silver → Gold → Features → Modelo → Scoring
                                  │
                                  │ solo lectura
                                  ▼
                             M9 serving
                                  │
                                  ▼
                         API HTTP read-only
                                  │
                                  ▼
                             Next.js / UI
```

El frontend no importa módulos científicos, no abre Bronze/Silver/Gold desde el navegador y no escribe sobre artefactos de M1–M8.

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

├── robustness.toml

└── production.toml
```

`datasets.toml` describe fuentes y relaciones candidatas; `silver.toml` y `gold.toml` congelan contratos de datos; `modeling.toml` congela el protocolo M4 antes de TEST; `robustness.toml` congela M5; y `production.toml` congela M6: runtime compatible, registry, scoring contract, idempotencia, ranking, monitoring, audit, human review y política de deployment.

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

## Ejecución actual de M8 y M9

M8 ya está cerrado y **no debe reejecutarse por rutina**. Su pipeline soporta reanudación por etapa cuando es necesario:
```bash
uv run --no-sync python pipelines/run_advanced_m8.py --start-stage 76
```

La capa M9 serving se puede reconstruir sin modificar evidencia científica:
```bash
PYTHONPATH=src uv run --no-sync python scripts/build_m9_serving.py
```

Salida verificada del build actual:
```text
M9 serving ✅ BUILT
batch=a8865bfed9374218183eb302
rows=529,054
scientific backend mutated: NO
```

Para levantar la API read-only directamente desde el backend:
```bash
PYTHONPATH=src uv run --no-sync python scripts/serve_m9.py
```

La API utiliza `data/serving/m9/argos-serving.duckdb` en modo de solo lectura. En el repositorio frontend, `yarn dev:argos` orquesta el serving y Next.js conjuntamente.

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

### Artefactos M7–M9

M7 y M8 añadieron manifests y reportes específicos para validación prospectiva, NLP, grafos, anomalías, ablation y supervivencia. M8 cerró con **8/8 manifests presentes**.

M9 añade exclusivamente artefactos **derivados de serving**:
```text
data/serving/m9/
├── argos-serving.duckdb
├── overview.json
└── manifest.json

reports/serving/
└── m9_serving_validation.parquet

artifacts/contracts/
└── m9_serving_contract.json
```

Estos artefactos pueden regenerarse desde las fuentes gobernadas. Su eliminación no invalida ni modifica la evidencia científica M1–M8.

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

## Validación estructural de notebooks
```bash
uv run --no-sync python scripts/check_notebooks.py
```

Estado verificado:
```text
Notebook validation ✅ 62 notebooks
```

Compilación estructural adicional:
```bash
uv run --no-sync python -m compileall -q src pipelines scripts
```

## QA específico de M9 serving
```bash
uv run --no-sync pytest -q \
  tests/unit/test_m9_serving_contract.py \
  tests/integration/test_m9_serving.py
```

Los invariantes M9 verifican, como mínimo:

- cardinalidad preservada respecto al scored batch;
- `contract_id` único y no nulo;
- `score`, `raw_score`, `rank` y `t0` inalterados;
- ausencia de target, estado mutable post-`t0` y PII configurada;
- serving derivado exclusivamente desde fuentes read-only.

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

## M5 — cierre

M5 cerró con **16/16 checks bloqueantes**. El fresh OOT 2026 mantiene señal predictiva por encima de random, pero evidencia degradación temporal material frente a TEST 2025; esa evidencia se convirtió en monitoring y gobernanza.

## M6 — cierre

M6 cerró con **16/16 condiciones bloqueantes** y estado `OPERATIONALLY_READY_PROMOTION_BLOCKED`. El replay operacional materializó 529,054 scores, una cola Top 1% de 5,291 contratos, 14 alertas y 6 alertas `high`.

## M7 — estado

M7 tiene implementación completa y protocolo congelado, pero permanece `ACTIVE / EVIDENCE PENDING`. No existe un cierre legítimo hasta que maduren suficientes cohorts futuras.

## M8 — cierre

M8 cerró formalmente con `RESEARCH_COMPLETE_NO_PROMOTION`. La ausencia de promoción de nuevas familias es un resultado científico válido y preserva ARGOS V1 como modelo gobernado.

## M9 — serving

M9 no altera gates científicos. Su contrato de aceptación exige que la capa serving preserve exactamente la población y los outputs de scoring y que cualquier enriquecimiento sea read-only y PIT-safe.

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

**Estado:** ✅ CLOSED — 16/16 checks bloqueantes.

M5 fortaleció la evidencia del ARGOS V1 congelado sin reutilizar TEST 2025 para selección. El protocolo `m5-robustness-v1` ejecutó notebooks `40–47` y dejó trazabilidad completa de backtesting temporal, explicabilidad, incertidumbre, drift, valor de familias, fresh OOT 2026, monitoreo y gate.

Resultados principales del fresh OOT 2026 plenamente observable (`2026-01-01` → `2026-03-13`):
```text
rows             529,054

positives           7,255

prevalence         1.3713%

PR-AUC             0.053274

ROC-AUC            0.744544

Brier              0.013238

ECE                0.003093

Precision@1%       8.5806%

Recall@1%          6.2578%

Lift@1%            6.257x
```

El OOT 2026 confirma señal predictiva útil por encima de revisión aleatoria, pero también evidencia degradación temporal material frente al TEST 2025. Por ello el cierre de M5 **no equivale a autorización de producción**. La degradación, el drift observado y la limitación estacional del holdout parcial de 2026 pasan como requisitos explícitos a M6.

M5 también congeló un ranking determinista:
```text
calibrated_score DESC

raw_score DESC

contract_id ASC
```

y un contrato de monitoreo para drift, missingness, score shift, prevalencia, calibración y Lift@K.

Autoridades de cierre:
```text
docs/decisions/M5_GATE.md

docs/decisions/M5_CLOSURE_REVIEW_2026-09-23.md

docs/models/ARGOS_V1_ROBUSTNESS_CARD.md

docs/monitoring/ARGOS_V1_MONITORING_SPEC.md
```

---

## M6 — Productionization & MLOps

**Estado:** ✅ CLOSED — 16/16 condiciones bloqueantes.

**Deployment status:** `OPERATIONALLY_READY_PROMOTION_BLOCKED`.

M6 corresponde a la **operacionalización controlada** del sistema: pipelines reproducibles, packaging/serving, registry, CI/CD, observabilidad, monitoreo, seguridad, rollback, auditoría y validación de despliegue.

M6 no convierte ARGOS en un sistema de decisión jurídica autónoma. El patrón operativo previsto continúa siendo:
```text
modelo → score/ranking → cola priorizada → revisión humana
```

La automatización puede abarcar ingestión, scoring, monitoreo y generación de colas, pero no conclusiones de corrupción/fraude, sanciones, elegibilidad o decisiones legales automáticas.

El contrato de entrada `docs/M6_HANDOFF.md` ya fue consumido. El protocolo ejecutado está definido en `docs/M6_RUNBOOK.md` y `configs/production.toml`; la decisión formal vive en `docs/decisions/M6_GATE.md` y la revisión senior en `docs/decisions/M6_CLOSURE_REVIEW_2026-09-23.md`.

M6 cierra la infraestructura operacional V1, pero **no levanta el bloqueo de promoción**: el replay produjo 6 alertas `high` y el estado de deployment conserva `promotion_blocked=true`. Ese estado es el punto de partida congelado de **M7 — Prospective Validation & Operational Evaluation**, que acumula evidencia futura sin reabrir ni reescribir M6.

---

---

## M7 — Prospective Validation & Operational Evaluation

**Estado:** ◐ ACTIVE — implementación completa / evidencia prospectiva pendiente.

M7 evalúa ARGOS V1 congelado sobre cohorts genuinamente posteriores al freeze. El protocolo está íntegro y no debe cerrarse con evidencia retrospectiva ya consumida. Su cierre depende de outcomes maduros a 180 días, reporting lag, múltiples cohorts prospectivos, evidencia de revisión humana y monitoring longitudinal.

Autoridad: `docs/decisions/M7_GATE.md`. Protocolo: `docs/M7_RUNBOOK.md`.

---

## M8 — Advanced Intelligence & Survival

**Estado:** ✅ CLOSED — `RESEARCH_COMPLETE_NO_PROMOTION`.

M8 completó NLP semántico, grafos temporales, detección contextual de anomalías, ablation temporal y análisis de supervivencia. La investigación avanzada cerró sin promover una nueva familia de features: el resultado `NO_PROMOTION` es una conclusión experimental válida y conserva ARGOS V1 como referencia gobernada.

M8 no reabre TEST 2025 ni OOT 2026 y no modifica M7. Autoridad: `docs/decisions/M8_GATE.md`.

---

## M9 — Plataforma Analítica / Frontend

**Estado:** ◐ ACTIVE — backend serving completo / frontend integrado.

M9 transforma los artefactos científicos y operativos de ARGOS en una interfaz profesional para exploración, priorización, trazabilidad y revisión humana. La capa de serving backend ya está implementada y materializada; el frontend se desarrolla como producto separado del pipeline de Ciencia de Datos.

Objetivos principales:
```text
Next.js + TypeScript

UX analítica y responsive

ranking de contratos

contract / supplier / entity intelligence

explicación de señales

exploración de grafos

anomalías y contexto temporal

survival / evolución temporal

monitoring y gobernanza

estado explícito de M7
```

M9 **no recalcula ni reentrena modelos en el navegador**, no promueve señales M8 descartadas y no convierte scores en acusaciones. El contrato detallado está en `docs/M9_FRONTEND_PLAN.md`.

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

Ejemplo histórico de checkpoint utilizado durante M2:
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
from argos.profiling.inventory *import* build_inventory
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

---

# 21. M7 — Prospective Validation & Operational Evaluation

M1–M6 están formalmente cerrados. ARGOS entra ahora en su séptimo y último milestone de V1:
```text
M7 — Prospective Validation & Operational Evaluation

Status: ACTIVE / implementation complete / prospective evidence pending

Schema: m7-prospective-v2
```

M7 evalúa si el **ARGOS V1 congelado** conserva señal útil, calibrada y operativamente manejable en cohorts que ocurren únicamente después de congelar el protocolo prospectivo.

El protocolo se congela el **2026-09-23** y los cohorts M7 comienzan el **2026-09-24**. TEST 2025 y OOT 2026 permanecen consumidos y no pueden reutilizarse para selección o tuning.

The sequence is:
```text
60 protocol freeze

   ↓

61 future shadow cohorts

   ↓

62 180-day outcome maturation + label lock

   ↓

63 prospective statistical performance

   ↓

64 human-review operational utility

   ↓

65 longitudinal monitoring + incidents

   ↓

66 governed operational decision

   ↓

67 M7 gate
```

M7 no puede cerrarse inmediatamente: el target exige 180 días completos de follow-up, un buffer conservador de maduración de outcomes y múltiples cohorts genuinamente prospectivos. Un cambio de modelo motivado por M7 crea una nueva versión y requiere un nuevo holdout futuro.

ARGOS permanece **batch-first, shadow y human-in-the-loop**. Ningún resultado de M7 promueve automáticamente el modelo ni convierte un risk score en una conclusión jurídica o de corrupción/fraude.

---

# 22. M8 — Advanced Intelligence & Survival

ARGOS M8 completa el alcance técnico avanzado como una línea separada de desarrollo V2: **NLP semántico, grafos temporales, detección contextual de anomalías y análisis de supervivencia**, seguidos por auditoría PIT, ablation temporal y gate formal. No modifica la evidencia congelada de ARGOS V1/M6/M7 y no reutiliza TEST 2025 u OOT 2026 para selección.

Secuencia:
```text
70 semantic NLP

71 temporal graph intelligence

72 contextual anomaly detection

73 M8 development matrix + PIT audit

74 temporal ablation

75 survival outcomes + administrative censoring

76 Kaplan-Meier + penalized Cox PH

77 M8 gate
```

Con los directorios reales `data/silver` y `data/gold` presentes:
```bash
uv sync --frozen

uv pip install -r requirements-m8.txt

uv run --no-sync python pipelines/run_advanced_m8.py
```

La ablation utiliza la misma semilla para todas las familias. Puede cerrar con `PROMOTE_M8_FEATURES` o `RESEARCH_COMPLETE_NO_PROMOTION`; un no-promote es científicamente válido si la evidencia está completa. Survival se evalúa por separado con Kaplan–Meier, Cox PH penalizado, Harrell C-index, Brier/calibración a 30/90/180 días y diagnóstico de proportional hazards.

Resultado empírico final:
```text
M8 gate                     CLOSED
Decision                    RESEARCH_COMPLETE_NO_PROMOTION
Selected family             none
Survival validation C-index ≈ 0.779
Mean validation Brier       ≈ 0.0083
Survival horizons           30 / 90 / 180 días
```

La conclusión no es que NLP, grafos o anomalías “fallen”, sino que bajo el protocolo temporal congelado no demostraron una mejora suficiente y consistente para justificar promoción frente al baseline gobernado.

Ver `docs/M8_RUNBOOK.md`, `docs/decisions/M8_GATE.md` y `docs/PROJECT_COMPLETION_AND_TESTING.md`.

---

# 23. Cierre técnico y estado científico

El alcance científico/técnico definido para ARGOS está implementado y verificado:
```text
M1–M6  ✅ CLOSED

M7     ◐ ACTIVE / EVIDENCE PENDING

M8     ✅ CLOSED — RESEARCH_COMPLETE_NO_PROMOTION

Technical implementation evidence: COMPLETE

Prospective validation: ACTIVE
```

El cierre de M8 completa la implementación de Data Engineering, Data Quality, point-in-time correctness, Machine Learning, MLOps, NLP, grafos, detección de anomalías y supervivencia. El resultado `RESEARCH_COMPLETE_NO_PROMOTION` indica que las familias avanzadas fueron evaluadas rigurosamente pero no justificaron promoción bajo el protocolo congelado.

M7 permanece abierto por diseño. No representa deuda de código: representa una validación longitudinal que necesita cohorts futuros y outcomes maduros. Por tanto, el estado científicamente correcto es:

> **Implementación técnica completa; validación prospectiva en curso.**

El desarrollo de producto puede continuar sin modificar M7.

---

# 24. M9 — Plataforma Analítica / Frontend

M9 desarrolla la **plataforma de inteligencia analítica para priorización de riesgo en contratación pública** sobre la evidencia gobernada de ARGOS. El frontend debe convertir la evidencia ya gobernada en una experiencia de análisis y revisión humana, no en un sistema autónomo de acusación.

## Arquitectura objetivo
```text
SECOP II / artefactos gobernados

        ↓

ARGOS Data Science + MLOps

        ↓

Gold / M5 OOT / M6 scoring / monitoring / manifests

        │
        │ solo lectura
        ▼

M9 Serving (`m9-serving-v1`)

        ↓

DuckDB derivado + API HTTP read-only

        ↓

Next.js + TypeScript

        ↓

analista / revisor humano
```

La primera versión es **read-only y batch-first**. El frontend no ejecuta entrenamiento, tuning ni inferencia experimental desde el cliente. La integración evolucionó desde un snapshot monolítico hacia una capa de serving consultable y paginada.

## Superficies previstas
```text
Overview ejecutivo

Prioridad de revisión / ranking

Contract Intelligence

Supplier Intelligence

Entity Intelligence

Network / Graph Explorer

Anomaly Explorer

Survival / temporal intelligence

Model & Data Monitoring

Methodology / Governance
```

## Reglas no negociables

- mostrar **prioridad de revisión**, no “probabilidad de corrupción”;

- distinguir score gobernado de señales experimentales M8;

- mostrar el estado `M7 ACTIVE` sin presentarlo como validación prospectiva concluida;

- preservar `t0`, lineage, versión de modelo y fecha de scoring cuando estén disponibles;

- mantener visible el disclaimer analítico/jurídico;

- no consumir TEST/OOT para selección desde la capa de producto;

- no modificar artefactos científicos desde el frontend.

Plan y criterios de aceptación: `docs/M9_FRONTEND_PLAN.md`. Decisión de inicio: `docs/decisions/M9_START_2026-09-25.md`.

---

# 25. M9 Serving — integración read-only backend ↔ frontend

M9 Serving es la frontera de producto entre el backend científico y la interfaz de ARGOS. Su objetivo es **exponer información útil para análisis sin modificar la evidencia científica que la originó**.

## 25.1 Estado verificado

El build materializado actual produjo:
```text
M9 serving ✅ BUILT
batch=a8865bfed9374218183eb302
rows=529,054
db=data/serving/m9/argos-serving.duckdb
overview=data/serving/m9/overview.json
validation=reports/serving/m9_serving_validation.parquet
scientific backend mutated: NO
```

El schema de serving es `m9-serving-v1`.

## 25.2 Fuentes read-only

La población autoritativa proviene del scored batch M6. Para el batch OOT 2026, el enriquecimiento PIT correcto proviene de `data/m5/fresh_oot_2026.parquet`; Silver aporta dimensiones descriptivas cuando están disponibles.
```text
M6 scored batch
├── contract_id
├── t0
├── score
├── raw_score
└── rank
        +
M5 fresh_oot_2026
├── departamento
├── ciudad
├── modalidad_de_contratacion
├── historical supplier/entity/pair features
├── tenure
└── competition context <= t0
        +
Silver contracts / suppliers
├── entity_name
├── supplier_name
├── contract_object
├── process_id
└── identifiers
        ↓
M9 serving
```

Para 2026 no se utiliza `data/gold/ml/argos_v1.parquet` como fuente de enriquecimiento contractual del batch, porque esa matriz corresponde al diseño TRAIN/VALIDATION/TEST hasta 2025. El serving usa la misma cohorte 2026 que realmente fue puntuada.

## 25.3 Invariantes de seguridad metodológica

El builder aborta si ocurre cualquiera de estas condiciones:
```text
row_count serving != row_count scored batch
contract_id duplicado o nulo
score modificado
raw_score modificado
rank modificado
t0 modificado
join many-to-many accidental
target exportado
estado mutable post-t0 exportado
PII configurada exportada
```

La población M6 es la tabla dominante y los enriquecimientos son `LEFT JOIN`.

## 25.4 Campos seguros para Contract Intelligence

La API puede exponer, según cobertura real de las fuentes:
```text
Identidad
├── contract_id
├── process_id
├── entity_id / entity_name
├── supplier_code / supplier_name
└── contract_object

Contexto contractual
├── departamento
├── ciudad
├── sector
├── rama
├── orden
├── tipo_de_contrato
├── modalidad_de_contratacion
└── justificacion_modalidad_de_contratacion

Scoring gobernado
├── score
├── raw_score
├── rank
├── percentile
└── priority

Contexto previo a t0
├── prior_supplier_contract_count
├── prior_entity_contract_count
├── prior_supplier_entity_contract_count
├── prior_supplier_addition_event_count
├── prior_entity_addition_event_count
├── prior_supplier_entity_addition_event_count
├── prior_supplier_contracts_with_addition
├── observed_supplier_addition_contract_share_before_t0
├── supplier_tenure_days
├── entity_tenure_days
├── days_since_supplier_last_contract
├── days_since_entity_last_contract
├── bidder_count_before_t0
├── unique_resolved_supplier_count_before_t0
└── bidder_entity_resolution_rate_before_t0
```

El frontend traduce estos nombres técnicos a etiquetas de negocio sin modificar su significado.

## 25.5 API read-only

`serve_m9.py` abre DuckDB con `read_only=True` y expone:
```text
GET /health
GET /api/v1/overview
GET /api/v1/monitoring
GET /api/v1/contracts?page=1&pageSize=25
GET /api/v1/contracts?priority=Alta
GET /api/v1/contracts?q=<texto>
GET /api/v1/contracts/<contract_id>
```

Next.js actúa como BFF/proxy. El navegador no abre DuckDB ni Parquet directamente.

## 25.6 Materialización

Desde la raíz de `argos-code`:
```bash
PYTHONPATH=src uv run --no-sync python scripts/build_m9_serving.py
```

Desde el repositorio frontend:
```bash
yarn sync:argos
yarn dev:argos
```

`yarn sync:argos` reconstruye únicamente la capa derivada M9. `yarn dev:argos` levanta la API read-only y Next.js para desarrollo local.

## 25.7 Frontera científica

M9 puede mejorar presentación, búsqueda, filtros, navegación, visualización, paginación y experiencia del analista. No puede:

- alterar scores o rankings producidos por M6;
- reentrenar o recalibrar ARGOS V1;
- cambiar el target `y_addition_180d`;
- reutilizar TEST 2025 u OOT 2026 como nuevos holdouts de selección;
- promover features M8 descartadas;
- cerrar M7 sin evidencia prospectiva madura;
- escribir sobre Gold, Silver, modelos o manifests científicos.

La relación final es:
```text
ARGOS Science
     │
     │ read-only
     ▼
ARGOS Serving
     │
     ▼
Next.js BFF
     │
     ▼
ARGOS Analytical Platform
```

El serving convierte resultados gobernados en un producto consultable; **no convierte la capa de producto en una nueva fuente de verdad científica**.
