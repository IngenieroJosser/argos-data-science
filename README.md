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
- [9. Notebooks y gates de M1–M3](#9-notebooks-y-gates-de-m1m3)
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

Contendrá datasets preparados para consumo analítico y Machine Learning.

Ejemplos:

```text
labels/
features/
splits/
datasets/
```

La granularidad prevista para el primer dataset de ML es:

```text
1 fila = 1 contrato evaluado en t0
```

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
│   └── gold.toml
│
├── data/
│   ├── bronze/
│   ├── silver/
│   └── gold/
│
├── docs/
│   ├── problem-definition.md
│   ├── ARGOS_analytical_framing_workspace.md
│   ├── M1_RUNBOOK.md
│   ├── M2_RUNBOOK.md
│   ├── M3_HANDOFF.md
│   ├── M3_RUNBOOK.md
│   ├── M4_HANDOFF.md
│   ├── README.md
│   ├── data-dictionary/
│   ├── decisions/
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
│   └── 27_m3_gate.ipynb
│
├── pipelines/
│   ├── build_silver_contracts_processes.py
│   └── build_gold_m3.py
│
├── reports/
│   ├── experiments/
│   ├── figures/
│   ├── profiling/
│   ├── quality/
│   ├── silver/
│   └── gold/
│
├── scripts/
│   ├── bootstrap_workspace.sh
│   ├── evaluate_m1_gate.py
│   └── evaluate_m3_gate.py
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

ARGOS completó la construcción y auditoría de su primera capa analítica point-in-time. El siguiente milestone autorizado es:

```text
M4 — Modeling & Evaluation
```

Estado de milestones:

```text
M1 — Bronze Data Understanding & Target Feasibility   ✅ CLOSED — 19/19
M2 — Silver / Canonical Data Model                    ✅ CLOSED — 10/10
M3 — Gold / Point-in-Time Analytical Layer            ✅ CLOSED — 13/13
M4 — Modeling & Evaluation                            ▶ READY
```

M3 quedó cerrado por `27_m3_gate.ipynb` con **13/13 checks bloqueantes aprobados**. El gate verifica los checks de `20`–`26`, la presencia de los 7 artefactos Gold canónicos, manifests completos, consistencia de schema `m3-gold-v1`, target spec congelado, split temporal congelado y cero issues Gold bloqueantes.

La capa Gold V1 queda **congelada como contrato de entrada a Modeling**. El dataset auditado para M4 es `data/gold/ml/argos_v1.parquet`, con **4,783,128 contratos asignados** y **41 features** autorizadas por el feature registry. Ningún modelo de M4 debe reconstruir features directamente desde Bronze ni reinterpretar Silver.

La semántica del target V1 quedó validada empíricamente:

```text
target = y_addition_180d
t0 = fecha_de_firma
horizon = 180 días
evento positivo = ADICION EN EL VALOR
ventana = (t0, t0 + 180d]
right censoring = label NULL
```

Split temporal congelado para evaluación:

| split | periodo | filas | positivos | prevalencia |
|---|---|---:|---:|---:|
| train | 2015-06-11 .. 2023-12-31 | 2,781,601 | 58,446 | 2.1012% |
| validation | 2024-01-01 .. 2024-12-31 | 950,670 | 9,180 | 0.9656% |
| test | 2025-01-01 .. 2025-12-31 | 1,050,857 | 10,983 | 1.0451% |

La caída de prevalencia entre TRAIN y 2024–2025 es una propiedad empírica que M4 debe tratar como **prior probability / temporal shift**, no corregir alterando los conjuntos de evaluación.

Deudas y restricciones que permanecen explícitas:

- bidder→supplier continúa parcialmente resuelto; los estados `unresolved` y `ambiguous` se preservan y no se imputan de forma forzada;
- `payments` y `sanctions` continúan fuera del target V1;
- el test 2025 está congelado y no participa en feature design, selección de modelo ni tuning;
- cambios a target, split, schema Gold o feature registry requieren decisión documentada y reejecución de los gates afectados;
- M4 debe reportar ranking, discriminación y calibración; `accuracy` no es una métrica primaria debido al desbalance del target.

Documentos de autoridad:

```text
docs/decisions/M1_GATE.md
docs/decisions/M2_GATE.md
docs/decisions/M3_GATE.md
docs/decisions/M3_CLOSURE_REVIEW_2026-09-23.md
docs/M4_HANDOFF.md
docs/data-dictionary/gold_m3_catalog.md
```


# 9. Notebooks y gates de M1–M3

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

La configuración está externalizada en:

```text
configs/
├── datasets.toml
└── project.toml
```

## `datasets.toml`

Contiene metadata y supuestos iniciales relacionados con:

```text
source IDs
file matching
candidate keys
join hypotheses
```

Las claves y relaciones allí declaradas son **candidatas** hasta ser verificadas empíricamente.

---

## `project.toml`

Actualmente define parámetros como:

```toml
[profiling]
csv_sample_size = 100000
example_rows = 2000
compute_sha256 = false

[target]
name = "y_addition_180d"
horizon_days = 180
candidate_t0_dataset = "contracts"
candidate_t0_column = "fecha_de_firma"
contract_id_column = "id_contrato"
addition_contract_id_column = "id_contrato"
addition_event_column = "fecharegistro"
```

El uso de configuración externa evita hardcodear decisiones metodológicas dentro de los notebooks.

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

Los CSV originales deben ubicarse en:

```text
data/bronze/
```

Los datos no forman parte del código fuente del proyecto.

La secuencia histórica cerrada del proyecto es:

```text
00 → 01 → 02 → 03 → 04 → 05 → 06 → 07_m1_gate
                                      │
                                      └── M1 ✅ CLOSED

10 → 11 → 12 → 13 → 14 → 15_m2_gate
                         │
                         └── M2 ✅ CLOSED

20 → 21 → 22 → 23 → 24 → 25 → 26 → 27_m3_gate
                                        │
                                        └── M3 ✅ CLOSED
```

M1, M2 y M3 se consideran **congelados**. No deben reejecutarse por rutina al iniciar Modeling. Solo se reabren si cambia una fuente, una regla canónica, target/split, schema o artefacto que invalide su evidencia.

M4 puede consumir exclusivamente el contrato Gold auditado descrito en `docs/M4_HANDOFF.md`. El test 2025 permanece sellado para evaluación final.

> Los primeros análisis Bronze realizan scans completos sobre CSV de varios GB. Silver ya materializa Parquet canónico para evitar repetir esos scans durante Gold.

---

# 14. Artefactos generados

Los notebooks generan evidencia persistente en lugar de depender únicamente de outputs visuales.

```text
reports/
├── profiling/                 # evidencia M1
├── quality/                   # evidencia M1
├── silver/                    # validaciones y gate M2
└── gold/                      # validaciones, feature registry y gate M3

artifacts/manifests/           # lineage de componentes Silver y Gold

docs/decisions/
├── M1_GATE.md
├── M2_GATE.md
├── M3_START_2026-09-23.md
├── M3_TEMPORAL_SPLIT_FREEZE.md
├── M3_CODE_READINESS_2026-09-23.md
├── M3_GATE.md
└── M3_CLOSURE_REVIEW_2026-09-23.md
```

M2 materializa 12 artefactos canónicos bajo `data/silver/`. M3 materializa 7 artefactos Gold canónicos y el model matrix auditado `data/gold/ml/argos_v1.parquet`. Sus contratos de datos están documentados en `docs/data-dictionary/silver_m2_catalog.md` y `docs/data-dictionary/gold_m3_catalog.md`.

Estos reportes y manifests se consideran **evidencia analítica generada**. Los artefactos de gate son parte del contrato de reproducibilidad del milestone y deben conservarse junto con la versión de código que los produjo.

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

## Regla de transición a M4

Modeling consume `data/gold/ml/argos_v1.parquet` y su feature registry. No debe leer Bronze para features ni reconstruir historiales desde el snapshot completo. El conjunto TEST 2025 está congelado y no puede utilizarse para selección de variables, selección de modelo o tuning. El contrato formal de entrada está en `docs/M4_HANDOFF.md`.

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

**Estado:** ▶ READY.

Secuencia prevista:

```text
30_baseline_heuristics.ipynb
31_logistic_regression_baseline.ipynb
32_boosting_models.ipynb
33_calibration_and_ranking.ipynb
34_error_analysis_and_explainability.ipynb
35_ablation_studies.ipynb
36_business_impact.ipynb
37_m4_gate.ipynb
```

M4 debe comparar referencias simples y modelos supervisados bajo el split temporal congelado. Métricas primarias: PR-AUC y métricas de ranking bajo capacidad (`Precision@K`, `Recall@K`, `Lift@K`, cumulative gain), complementadas por ROC-AUC, log loss, Brier y calibración.

---

## M5 — Advanced Data Science

Solo después de validar el problema base:

```text
Survival Analysis
Anomaly Detection
NLP
Graph Analytics
Graph ML
Causal Analysis
Forecasting
Risk Fusion
```

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
