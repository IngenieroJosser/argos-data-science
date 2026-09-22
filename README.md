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
- [9. Notebooks de M1](#9-notebooks-de-m1)
- [10. Arquitectura del código](#10-arquitectura-del-código)
- [11. Configuración](#11-configuración)
- [12. Instalación](#12-instalación)
- [13. Ejecución](#13-ejecución)
- [14. Artefactos generados](#14-artefactos-generados)
- [15. Calidad, pruebas y estilo](#15-calidad-pruebas-y-estilo)
- [16. Criterio de finalización de M1](#16-criterio-de-finalización-de-m1)
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

Su definición definitiva **todavía no se considera congelada**. Antes debe demostrarse que:

- existe un timestamp confiable para las adiciones;
- existe una relación suficientemente confiable entre contratos y adiciones;
- puede definirse un `t0` consistente;
- existe seguimiento suficiente para observar 180 días;
- el evento puede construirse sin leakage.

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

Contendrá representaciones limpias y canónicas.

Ejemplos futuros:

```text
contracts
processes
suppliers
bidders
additions
payments
sanctions
```

Las transformaciones Bronze → Silver deberán ser:

- reproducibles;
- auditables;
- tipadas;
- validadas;
- idempotentes cuando sea posible.

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
│   └── models/
│
├── configs/
│   ├── datasets.toml
│   └── project.toml
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
│   └── 06_target_feasibility.ipynb
│
├── pipelines/
│
├── reports/
│   ├── experiments/
│   ├── figures/
│   ├── profiling/
│   └── quality/
│
├── scripts/
│   └── bootstrap_workspace.sh
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
│       ├── ingestion/
│       ├── models/
│       ├── profiling/
│       ├── quality/
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

El proyecto se encuentra en:

```text
M1 — Data Understanding & Target Feasibility
```

La prioridad actual **no es entrenar modelos**.

Antes de avanzar a Silver o al modelado, M1 debe responder con evidencia:

```text
¿Qué datos existen realmente?

¿Qué representa una fila de cada fuente?

¿Cuáles son las claves candidatas?

¿Qué duplicados existen?

¿Cómo se relacionan las fuentes?

¿Cuál es el coverage de cada join?

¿Cuánto expande cada join?

¿Cómo funciona la temporalidad?

¿Cuál puede ser t0?

¿Qué columnas podrían generar leakage?

¿Es viable construir y_addition_180d?

¿Cuál es la prevalencia?

¿Cuántos contratos están censurados?
```

---

# 9. Notebooks de M1

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

Ejecuta los notebooks desde la raíz del repositorio y en este orden:

```text
00_bronze_inventory.ipynb
        ↓
01_schema_and_semantic_profiling.ipynb
        ↓
02_grain_keys_and_duplicates.ipynb
        ↓
03_relationships_and_join_coverage.ipynb
        ↓
04_temporal_audit.ipynb
        ↓
05_data_quality_audit.ipynb
        ↓
06_target_feasibility.ipynb
```

> Algunos análisis realizan scans completos sobre CSV de varios GB. Esto es esperado durante la primera auditoría de gobernanza y puede ser intensivo en I/O.

Una vez que exista Silver en Parquet, gran parte de estos análisis podrá ejecutarse de manera considerablemente más eficiente.

---

# 14. Artefactos generados

Los notebooks generan evidencia persistente en lugar de depender únicamente de outputs visuales.

```text
reports/
├── profiling/
│   ├── dataset_inventory.parquet
│   ├── column_profile.parquet
│   ├── key_analysis.parquet
│   ├── join_analysis.parquet
│   ├── temporal_profile.parquet
│   ├── temporal_rules.parquet
│   ├── target_feasibility_horizons.parquet
│   ├── target_feasibility_diagnostics.parquet
│   └── target_feasibility_by_year.parquet
│
└── quality/
    ├── money_profile.parquet
    └── quality_issue_register.parquet
```

Estos artefactos se consideran **evidencia analítica generada**, no código fuente.

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

# 16. Criterio de finalización de M1

M1 no termina porque los notebooks ejecuten sin error.

Termina cuando existe evidencia suficiente para responder las preguntas metodológicas críticas.

## Definition of Done

- [ ] Los siete snapshots Bronze están inventariados.
- [ ] El schema físico y semántico está perfilado.
- [ ] La granularidad de cada fuente está documentada.
- [ ] Las claves candidatas han sido medidas.
- [ ] Las relaciones han sido auditadas por coverage, multiplicidad y expansión.
- [ ] La cobertura temporal está cuantificada.
- [ ] Las reglas de orden temporal están auditadas.
- [ ] Las columnas potencialmente mutables o con leakage están identificadas.
- [ ] Existe un registro de problemas de calidad.
- [ ] El candidato `t0` está respaldado por evidencia.
- [ ] La viabilidad de `y_addition_180d` está cuantificada.
- [ ] El censoring está medido.
- [ ] Existe una decisión documentada: `GO` o `REDEFINE`.

Solo después debe comenzar la construcción formal de Silver.

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

**Estado actual.**

---

## M2 — Silver / Canonical Data Model

Objetivo:

```text
Bronze
   ↓
typing
normalization
entity resolution
quality rules
   ↓
Silver
```

Entidades previstas:

```text
contracts
processes
suppliers
bidders
additions
payments
sanctions
```

---

## M3 — Target & Gold Dataset

Objetivos:

```text
target engineering
temporal split
EDA sobre train
point-in-time features
Gold dataset
leakage audit
```

---

## M4 — Baseline

```text
prevalence
heuristics
Logistic Regression
```

---

## M5 — Machine Learning

Candidatos:

```text
LightGBM
XGBoost
CatBoost
```

Evaluados mediante validación temporal y métricas de ranking/calibración.

---

## M6 — Advanced Data Science

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

## M7 — Producción y MLOps

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

No deben versionarse datasets masivos ni artefactos generados innecesariamente.

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
