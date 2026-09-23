# ARGOS — Formulación Analítica y Configuración del Workspace

> **Proyecto:** ARGOS — Plataforma de inteligencia de riesgo para contratación pública  
> **Versión:** 1.1  
> **Estado:** M1 ✅ CLOSED · M2 ✅ CLOSED · M3 ▶ IN PROGRESS  
> **Documento relacionado:** `docs/problem-definition.md`

---

# 1. PROBLEMA REAL

La contratación pública produce millones de registros asociados con procesos, contratos, proveedores, proponentes, modificaciones, pagos y sanciones.

El problema real no es únicamente el volumen de datos. Es la combinación de:

- gran cantidad de contratos potencialmente revisables;
- capacidad humana limitada para analizarlos en profundidad;
- necesidad de identificar qué casos merecen atención primero;
- información histórica y relacional que puede contener señales útiles para priorización.

ARGOS busca responder:

> **¿Cómo priorizar contratos para revisión analítica adicional utilizando únicamente información que habría estado disponible al momento de tomar la decisión?**

ARGOS **no pretende determinar corrupción, fraude o culpabilidad**. Una salida del sistema debe interpretarse como un score de riesgo, probabilidad estimada, anomalía estadística, patrón relacional atípico o prioridad de revisión.

---

# 2. CONTEXTO DE NEGOCIO

El dominio corresponde a contratación pública registrada en SECOP II.

Actores y objetos principales:

```text
ENTIDAD
   ↓
PROCESO DE CONTRATACIÓN
   ↓
PROPONENTES
   ↓
ADJUDICACIÓN
   ↓
CONTRATO
   ↓
EJECUCIÓN
   ├── ADICIONES
   ├── PAGOS
   └── SANCIONES
```

Características relevantes del dominio:

1. **Alto volumen:** millones de registros.
2. **Capacidad de revisión limitada:** no todos los contratos pueden revisarse con igual profundidad.
3. **Naturaleza temporal:** un contrato cambia después de su firma.
4. **Relaciones complejas:** existen relaciones 1:N y N:M entre entidades, procesos, proveedores y contratos.
5. **Heterogeneidad:** contratos de diferentes sectores, regiones, modalidades, categorías, valores y duraciones.
6. **Información mutable:** un snapshot actual puede contener estados posteriores al momento que se pretende modelar.
7. **Señal histórica potencial:** comportamiento previo de proveedores, entidades y relaciones puede aportar información predictiva.

---

# 3. DECISIÓN QUE SE QUIERE MEJORAR

La decisión principal es:

> **Dado un conjunto de contratos y una capacidad limitada de análisis humano, ¿cuáles deberían revisarse primero?**

Esto convierte ARGOS en un problema de **priorización/ranking de riesgo**.

Ejemplo:

```text
10.000 contratos
      ↓
capacidad humana: 500 revisiones
      ↓
ARGOS asigna score
      ↓
se priorizan los 500 contratos con mayor score
```

Por esta razón, el éxito no debe medirse únicamente mediante accuracy.

Métricas de decisión relevantes:

```text
Precision@K
Recall@K
Lift@K
Cumulative Gain
```

Métricas técnicas complementarias:

```text
PR-AUC
ROC-AUC
Brier Score
Calibration
Log Loss
```

---

# 4. TIPO DE PROBLEMA ANALÍTICO

ARGOS contiene varios problemas analíticos, pero deben desarrollarse por etapas.

## 4.1 Predictivo — problema principal inicial

> **Dada la información disponible hasta `t0`, ¿cuál es la probabilidad de que un contrato presente una modificación contractual relevante dentro de los siguientes 180 días?**

Formalmente:

\[
P(Y_{180}=1 \mid X_{t0})
\]

## 4.2 Descriptivo

- volumen de contratación;
- distribución por entidad, sector, modalidad, región y categoría;
- evolución temporal;
- concentración por proveedor;
- comportamiento histórico.

## 4.3 Diagnóstico

- características asociadas con modificaciones posteriores;
- diferencias entre segmentos;
- cambios de captura y calidad;
- cambios de prevalencia del evento.

## 4.4 Anomalías

- valores contractuales atípicos;
- relaciones entidad–proveedor inusuales;
- co-participación poco frecuente;
- comportamiento temporal extremo.

## 4.5 Supervivencia

> **¿Cuánto tiempo transcurre hasta la primera modificación o sanción?**

Permite modelar observaciones censuradas correctamente.

## 4.6 NLP

- embeddings del objeto/descripción;
- contratos semánticamente similares;
- clustering temático;
- comparación de valor contra vecinos semánticos.

## 4.7 Grafos

- proveedor–entidad–proceso;
- concentración;
- comunidades;
- co-participación;
- métricas relacionales;
- Graph ML en fases posteriores.

## 4.8 Forecasting

- gasto esperado por entidad/categoría/periodo;
- desviaciones frente al comportamiento esperado.

## 4.9 Causal

- estudiar efectos potenciales de modalidades, competencia u otras condiciones;
- separar correlación de evidencia causal;
- exigir diseño causal explícito antes de afirmar efectos.

---

# 5. PREGUNTAS ANALÍTICAS

## 5.1 Principal

> ¿Cuál es la probabilidad de que un contrato tenga una adición relevante dentro de los 180 días posteriores a `t0`?

## 5.2 Contrato

- ¿El valor es atípico frente a contratos comparables?
- ¿La modalidad contiene señal predictiva?
- ¿La categoría tiene diferente tasa histórica de modificaciones?
- ¿La duración inicial aporta información?
- ¿El texto contractual contiene patrones asociados al evento?

## 5.3 Proveedor

- ¿Cuántos contratos previos tenía antes de `t0`?
- ¿Cuál era su valor contratado acumulado?
- ¿Cuál era su tasa histórica de modificaciones?
- ¿Con cuántas entidades había contratado?
- ¿Qué tan concentrada estaba su contratación?

## 5.4 Entidad

- ¿Cuántos contratos históricos tenía?
- ¿Cuál era su tasa histórica de modificaciones?
- ¿Con cuántos proveedores contrataba?
- ¿Qué concentración presentaba?

## 5.5 Relación entidad–proveedor

- ¿Cuántas relaciones previas existían?
- ¿Cuánto valor había sido adjudicado previamente?
- ¿Qué participación del gasto de la entidad correspondía al proveedor?
- ¿Qué participación del negocio público del proveedor dependía de esa entidad?

## 5.6 Competencia

- ¿Cuántos proponentes tuvo el proceso?
- ¿La competencia fue baja frente a procesos similares?
- ¿Los mismos proveedores compiten repetidamente?
- ¿Existen patrones persistentes de co-participación?

## 5.7 Temporalidad

- ¿La tasa de modificaciones cambia por año?
- ¿Hay cambios estructurales en SECOP II?
- ¿Existen periodos con peor calidad?
- ¿Existe covariate shift o concept drift?

---

# 6. UNIDAD DE ANÁLISIS + GRANULARIDAD

## 6.1 Unidad principal

> **Un contrato evaluado en un instante específico.**

Representación conceptual:

```text
(contract_id, snapshot_date)
```

Para la primera versión:

```text
(contract_id, t0)
```

## 6.2 Dataset de Machine Learning

```text
1 fila = 1 contrato evaluado en t0
```

Ejemplo:

| contract_id | t0 | contract_value | supplier_previous_contracts | y_addition_180d |
|---|---|---:|---:|---:|
| C001 | 2023-03-15 | 250000000 | 18 | 1 |
| C002 | 2023-03-16 | 87000000 | 4 | 0 |

## 6.3 Granularidad esperada de las fuentes

Hipótesis iniciales:

```text
Procesos      ≈ 1 fila por proceso
Contratos     ≈ 1 fila por contrato
Proponentes   ≈ 1 proveedor participante en 1 proceso
Proveedores   ≈ 1 fila por proveedor
Adiciones     ≈ 1 evento de adición/modificación
Pagos         ≈ 1 registro asociado a pago/factura/plan
Sanciones     ≈ 1 evento sancionatorio
```

Estas granularidades deben **verificarse empíricamente** antes de construir JOINs.

---

# 7. LÓGICA TEMPORAL

## 7.1 Timeline conceptual

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
    │ solo información conocida hasta aquí
    │
    ├──────── +30 días
    ├──────── +90 días
    └──────── +180 días
                 ↑
          ventana del target
```

## 7.2 Información potencialmente conocida antes de `t0`

- características del proceso;
- modalidad;
- entidad;
- sector;
- categoría;
- objeto contractual;
- valor inicial;
- proveedor adjudicado;
- proponentes del proceso;
- historial previo del proveedor;
- historial previo de la entidad;
- historial previo de la relación entidad–proveedor;
- estadísticas históricas de contratos comparables.

## 7.3 Información posterior a `t0`

- pagos;
- facturación;
- adiciones;
- prórrogas;
- cambios de estado;
- liquidación;
- sanciones;
- días adicionados;
- valor ejecutado;
- saldos posteriores.

No puede utilizarse como feature si ocurrió después de `t0`.

## 7.4 `t0` candidato

Candidato inicial:

```text
t0 = fecha de firma / formalización
```

Debe compararse contra:

```text
fecha de adjudicación
fecha de firma
fecha de inicio
```

La selección final debe considerar cobertura, consistencia, significado de negocio, disponibilidad real de features y riesgo de leakage.

## 7.5 Point-in-Time Correctness

Toda feature debe cumplir:

```text
feature_timestamp <= t0
```

Correcto:

```text
supplier_previous_contracts(t0)
```

Incorrecto:

```text
supplier_total_contracts_2018_2026
```

para un contrato de 2021.

---

# 8. TARGET

## 8.1 Target inicial

```text
y_addition_180d
```

Definición conceptual:

> Existe una adición/modificación válida dentro de los 180 días posteriores a `t0`.

Formalmente:

\[
Y_{180} =
\begin{cases}
1 & \text{evento válido dentro de } (t0,t0+180d] \\
0 & \text{sin evento y con ventana completamente observada}
\end{cases}
\]

## 8.2 Validaciones antes de congelarlo

- granularidad real de `Adiciones`;
- tipos de modificación;
- calidad de la fecha del evento;
- cobertura temporal;
- relación con `id_contrato`;
- duplicados;
- eventos previos a `t0`;
- censoring.

## 8.3 Censoring

Condición:

```text
eligible_for_label = t0 + 180 days <= label_cutoff
```

Un contrato sin 180 días completos de seguimiento no es automáticamente `0`.

Debe quedar como:

```text
y_addition_180d = UNKNOWN
```

para clasificación.

## 8.4 Targets futuros

```text
y_addition_365d
y_sanction_365d
y_payment_delay
y_large_value_increase

time_to_first_addition
time_to_first_sanction
```

---

# 9. HIPÓTESIS

Las siguientes son hipótesis de investigación, no conclusiones.

## H1 — Competencia

> Procesos con menor competencia histórica presentan tasas diferentes de modificaciones posteriores.

## H2 — Historial del proveedor

> El historial contractual previo del proveedor aporta señal predictiva adicional frente a usar únicamente características del contrato.

## H3 — Concentración entidad–proveedor

> Una relación más concentrada entre entidad y proveedor contiene información predictiva sobre modificaciones posteriores.

## H4 — Anomalía de valor

> Contratos cuyo valor se desvía significativamente de contratos comparables presentan tasas diferentes de eventos posteriores.

## H5 — Texto

> El objeto y la descripción contractual contienen señal incremental frente a un modelo tabular.

## H6 — Grafo

> Variables relacionales del grafo proveedor–entidad–proceso aportan señal incremental sobre el modelo tabular.

## H7 — Persistencia temporal

> Parte del comportamiento histórico de proveedores y entidades se mantiene en periodos posteriores y generaliza fuera de muestra.

---

# 10. DATOS NECESARIOS

Idealmente ARGOS necesitaría:

## Contrato

- identificador estable;
- valor inicial;
- modalidad;
- categoría;
- objeto;
- duración;
- entidad;
- proveedor;
- timestamps del ciclo de vida.

## Proceso

- identificador;
- publicación;
- adjudicación;
- modalidad;
- categoría;
- presupuesto;
- entidad;
- estado.

## Proveedor

- identificador estable;
- información registral;
- fecha de registro;
- localización;
- historial.

## Proponentes

- proceso;
- proveedor;
- fecha;
- resultado;
- valor ofertado, si existe y es utilizable.

## Adiciones

- contrato;
- fecha;
- tipo;
- valor;
- días;
- descripción.

## Pagos

- contrato;
- fecha;
- monto;
- factura;
- estado.

## Sanciones

- contrato y/o proveedor;
- fecha;
- tipo;
- entidad;
- estado.

## Historial de snapshots

Idealmente debería existir una historia completa del estado de cada contrato en el tiempo para reconstruir exactamente qué valor tenía cada columna en `t0`.

---

# 11. DATOS DISPONIBLES

Actualmente se dispone de siete fuentes SECOP II descargadas en `data/bronze/`.

## 11.1 Procesos de Contratación

Uso potencial:

- contexto del proceso;
- entidad;
- modalidad;
- fechas;
- categoría;
- presupuesto;
- información previa a adjudicación.

## 11.2 Contratos Electrónicos

Uso potencial:

- `id_contrato`;
- proceso asociado;
- proveedor;
- entidad;
- valor;
- fechas;
- objeto contractual;
- modalidad;
- categoría.

También contiene variables posteriores a firma que deben clasificarse por riesgo de leakage.

## 11.3 Proponentes por Proceso

Uso potencial:

- número de competidores;
- intensidad competitiva;
- relaciones proveedor–proceso;
- co-participación;
- futura construcción de grafos.

## 11.4 Proveedores Registrados

Uso potencial:

- entidad canónica de proveedor;
- identificadores;
- atributos registrales;
- entity resolution.

## 11.5 Adiciones

Uso potencial:

- target inicial;
- análisis de modificaciones;
- survival analysis.

## 11.6 Multas y Sanciones

Uso potencial:

- targets posteriores;
- historial previo de proveedor;
- análisis de eventos adversos.

## 11.7 Plan de Pagos

Uso potencial:

- análisis de ejecución;
- futuros targets de retraso;
- comportamiento financiero posterior;
- variables históricas para contratos futuros.

---

# 12. SUPUESTOS + RIESGOS

## 12.1 Data leakage

Riesgo crítico.

Columnas como:

```text
dias_adicionados
valor_pagado
valor_facturado
valor_pendiente_de_ejecucion
fecha_fin_liquidacion
```

pueden representar información posterior a `t0`.

## 12.2 Snapshot actual vs estado histórico

Un contrato firmado en 2020 puede observarse dentro de un snapshot descargado en 2026.

Una columna mutable puede contener información que no existía en 2020.

Se requiere un **mutability audit**.

## 12.3 Right censoring

Contratos recientes pueden no tener seguimiento suficiente para conocer el target.

No deben considerarse negativos por defecto.

## 12.4 Sesgo de cobertura

SECOP II representa los registros capturados en el sistema; no debe asumirse cobertura perfecta del fenómeno real.

Pueden existir diferencias por:

- año;
- modalidad;
- tipo de entidad;
- cambios regulatorios;
- adopción del sistema;
- calidad de captura.

## 12.5 Entity Resolution

Nombres e identificadores pueden presentar inconsistencias, cambios de razón social, consorcios, uniones temporales y duplicados.

Un falso merge puede contaminar todo el historial de una entidad.

## 12.6 Sesgo temporal

Un patrón histórico puede no generalizar al presente.

Debe evaluarse:

```text
covariate shift
concept drift
changes in data capture
```

## 12.7 Representatividad

Los contratos con datos completos pueden ser sistemáticamente distintos de los incompletos.

Eliminar faltantes indiscriminadamente puede producir selection bias.

## 12.8 Target imperfecto

Una adición contractual no equivale a irregularidad.

```text
adición ≠ corrupción
adición ≠ fraude
```

El target representa un evento contractual posterior.

## 12.9 Asociación vs causalidad

Un modelo predictivo puede aprender asociaciones útiles sin identificar causas.

## 12.10 Disponibilidad en producción

Una feature solo es válida si puede calcularse en entrenamiento, validación, test y en el momento real de inferencia.

## 12.11 Join explosion

Cada JOIN debe auditar:

```text
coverage
uniqueness
multiplicity
expansion_factor
```

## 12.12 Privacidad y minimización

Campos personales o de alta cardinalidad no deben convertirse automáticamente en features solo porque aparezcan en la fuente pública.

---

# 13. CRITERIO DE SALIDA DE LA FASE DE FORMULACIÓN

Antes de modelar se debe poder responder con evidencia:

```text
¿Qué representa una fila de cada dataset?
¿Cuál es la PK candidata?
¿Cuáles son las relaciones 1:1, 1:N y N:M?
¿Qué porcentaje de contratos puede relacionarse entre fuentes?
¿Cuál es la cobertura temporal?
¿Cuál será t0?
¿Qué columnas existían realmente en t0?
¿Qué columnas son leakage?
¿Puede construirse y_addition_180d?
¿Cuántos contratos son elegibles para label?
¿Cuál es la prevalencia?
¿Qué periodos conformarán train/validation/test?
```

---

# 14. PRINCIPIO RECTOR

> **Primero reconstruir correctamente el mundo histórico. Después intentar predecirlo.**

---

# 15. CONFIGURACIÓN DEL WORKSPACE

Para la primera versión no se necesita Spark, Kubernetes, Kafka, MinIO ni Neo4j.

Stack inicial recomendado:

```text
Python 3.12
uv
Polars
DuckDB
PyArrow
Pandas (compatibilidad puntual)
Pandera
scikit-learn
Jupyter
Matplotlib
Plotly
pytest
Ruff
MyPy
Git
```

---

# 16. ESTRUCTURA OBJETIVO

```text
argos-code/
├── data/
│   ├── bronze/
│   ├── silver/
│   └── gold/
├── docs/
│   ├── problem-definition.md
│   ├── analytical-framing.md
│   ├── data-manifest.md
│   ├── data-model.md
│   ├── leakage-audit.md
│   ├── decision-log.md
│   ├── data-dictionary/
│   └── target-specs/
├── notebooks/
│   ├── 01_data_inventory.ipynb
│   ├── 02_structural_profiling.ipynb
│   ├── 03_keys_and_cardinality.ipynb
│   ├── 04_temporal_analysis.ipynb
│   ├── 05_join_analysis.ipynb
│   └── 06_target_feasibility.ipynb
├── reports/
│   ├── profiling/
│   ├── quality/
│   ├── figures/
│   └── experiments/
├── src/
│   └── argos/
│       ├── ingestion/
│       ├── profiling/
│       ├── quality/
│       ├── entities/
│       ├── targets/
│       ├── features/
│       ├── models/
│       └── evaluation/
├── tests/
├── configs/
├── .gitignore
├── .python-version
├── pyproject.toml
└── README.md
```

---

# 17. COMANDOS — BOOTSTRAP DEL PROYECTO

Comandos pensados para macOS + zsh.

## 17.1 Entrar al proyecto

```bash
cd /ruta/a/argos-code
```

## 17.2 Instalar `uv`

```bash
brew install uv
uv --version
```

## 17.3 Python 3.12

```bash
uv python install 3.12
uv python pin 3.12
```

## 17.4 Inicializar proyecto si no existe `pyproject.toml`

```bash
uv init --bare
```

## 17.5 Crear entorno

```bash
uv venv
source .venv/bin/activate
```

## 17.6 Dependencias principales

```bash
uv add \
  polars \
  duckdb \
  pyarrow \
  pandas \
  numpy \
  scipy \
  scikit-learn \
  pandera \
  pydantic \
  matplotlib \
  plotly \
  ipykernel \
  jupyterlab \
  tqdm \
  rich
```

## 17.7 Dependencias de desarrollo

```bash
uv add --dev \
  pytest \
  pytest-cov \
  ruff \
  mypy \
  pre-commit
```

## 17.8 Crear estructura

```bash
mkdir -p \
  data/bronze \
  data/silver \
  data/gold \
  docs/data-dictionary \
  docs/target-specs \
  notebooks \
  reports/profiling \
  reports/quality \
  reports/figures \
  reports/experiments \
  src/argos/ingestion \
  src/argos/profiling \
  src/argos/quality \
  src/argos/entities \
  src/argos/targets \
  src/argos/features \
  src/argos/models \
  src/argos/evaluation \
  tests \
  configs
```

## 17.9 Crear paquetes Python

```bash
touch \
  src/argos/__init__.py \
  src/argos/ingestion/__init__.py \
  src/argos/profiling/__init__.py \
  src/argos/quality/__init__.py \
  src/argos/entities/__init__.py \
  src/argos/targets/__init__.py \
  src/argos/features/__init__.py \
  src/argos/models/__init__.py \
  src/argos/evaluation/__init__.py
```

## 17.10 Documentación base

```bash
touch \
  docs/data-manifest.md \
  docs/data-model.md \
  docs/leakage-audit.md \
  docs/decision-log.md
```

## 17.11 `.gitignore`

```bash
cat > .gitignore <<'GITIGNORE'
# Python
__pycache__/
*.py[cod]
*.egg-info/

# Virtual env
.venv/
venv/

# Jupyter
.ipynb_checkpoints/

# Data
data/bronze/*
data/silver/*
data/gold/*
!data/bronze/.gitkeep
!data/silver/.gitkeep
!data/gold/.gitkeep

# Generated reports
reports/profiling/*
reports/quality/*
reports/figures/*
reports/experiments/*
!reports/profiling/.gitkeep
!reports/quality/.gitkeep
!reports/figures/.gitkeep
!reports/experiments/.gitkeep

# Local databases
*.duckdb
*.db

# Model artifacts
*.pkl
*.joblib
*.onnx

# Secrets
.env
.env.*

# OS
.DS_Store
GITIGNORE
```

## 17.12 Mantener directorios vacíos

```bash
touch \
  data/silver/.gitkeep \
  data/gold/.gitkeep \
  reports/profiling/.gitkeep \
  reports/quality/.gitkeep \
  reports/figures/.gitkeep \
  reports/experiments/.gitkeep
```

No necesitas `.gitkeep` en `data/bronze/` si ya contiene tus CSV.

---

# 18. JUPYTER

Registrar kernel:

```bash
uv run python -m ipykernel install \
  --user \
  --name argos \
  --display-name "Python (ARGOS)"
```

Ejecutar:

```bash
uv run jupyter lab
```

En VS Code selecciona `Python (ARGOS)` como kernel.

---

# 19. DUCKDB CLI

Opcional pero recomendable:

```bash
brew install duckdb
duckdb --version
```

Prueba:

```bash
duckdb
```

Dentro de DuckDB:

```sql
SELECT COUNT(*)
FROM read_csv_auto('data/bronze/archivo.csv');
```

---

# 20. RUFF

Añadir a `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.ruff.format]
quote-style = "double"
```

Ejecutar:

```bash
uv run ruff check .
uv run ruff format .
```

---

# 21. MYPY

Añadir a `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false
ignore_missing_imports = true
```

Ejecutar:

```bash
uv run mypy src
```

---

# 22. PYTEST

Añadir a `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-ra -q"
```

Ejecutar:

```bash
uv run pytest
```

---

# 23. PRE-COMMIT

Crear configuración:

```bash
cat > .pre-commit-config.yaml <<'PRECOMMIT'
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.13.1
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
PRECOMMIT
```

Instalar hooks:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

> Si esa revisión concreta de Ruff ya no existe cuando ejecutes el comando, actualiza `rev` a una versión disponible.

---

# 24. MAKEFILE OPCIONAL

```bash
cat > Makefile <<'MAKEFILE'
.PHONY: install test lint format typecheck lab quality

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src

lab:
	uv run jupyter lab

quality: lint typecheck test
MAKEFILE
```

Uso:

```bash
make quality
```

---

# 25. PRIMEROS NOTEBOOKS

Créelos desde VS Code/Jupyter con estos nombres:

```text
notebooks/01_data_inventory.ipynb
notebooks/02_structural_profiling.ipynb
notebooks/03_keys_and_cardinality.ipynb
notebooks/04_temporal_analysis.ipynb
notebooks/05_join_analysis.ipynb
notebooks/06_target_feasibility.ipynb
```

No uses `touch` para crear notebooks reales porque un `.ipynb` requiere JSON válido.

---

# 26. PRIMEROS MÓDULOS REUTILIZABLES

```bash
touch \
  src/argos/profiling/inventory.py \
  src/argos/profiling/schema.py \
  src/argos/profiling/keys.py \
  src/argos/profiling/temporal.py \
  src/argos/quality/checks.py
```

Los notebooks deben consumir funciones de `src/argos/` en vez de acumular toda la lógica de transformación.

---

# 27. CHECKPOINT ACTUAL RECOMENDADO

M2 está formalmente cerrado. El checkpoint recomendado es:

```bash
git add .
git commit -m "feat(silver): completa la capa canónica y cierra M2"
git tag m2-cerrado
```

---

# 28. MILESTONE ACTUAL

```text
M3 — Gold / Point-in-Time Analytical Layer
```

Prioridades de entrada:

```text
[x] congelar la semántica V1 del target (`ADICION EN EL VALOR`, 180 días)
[ ] construir labels con censoring explícito
[ ] diseñar split temporal antes de EDA/modelado
[ ] crear features únicamente con información <= t0
[ ] auditar leakage y point-in-time correctness
[ ] materializar Gold reproducible
[ ] cerrar M3 con gate antes de Modeling
```

Contrato de entrada: `docs/M3_HANDOFF.md`. Runbook operativo: `docs/M3_RUNBOOK.md`.

No se debe entrenar ningún modelo antes de completar el audit Gold point-in-time y el gate de M3.
