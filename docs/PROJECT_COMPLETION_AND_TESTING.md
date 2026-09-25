# ARGOS — Project Completion & Full Verification

Este documento define cómo verificar **todo el alcance final declarado** del proyecto:

- Data Engineering;
- Data Quality;
- modelado temporal / point-in-time correctness;
- Machine Learning;
- MLOps;
- NLP;
- grafos;
- detección de anomalías;
- análisis de supervivencia;
- validación prospectiva M7 como experimento longitudinal.

No formaron parte del criterio obligatorio para cerrar la implementación científica/técnica: causal inference, FastAPI, Next.js o dashboard. Tras ese cierre, Next.js pasa a ser parte explícita de **M9 — Plataforma Analítica**, una fase de producto separada.

## 1. Preparar el entorno

Desde el root del repositorio:

```bash
uv sync --frozen
uv pip install -r requirements-m8.txt
```

Verificar:

```bash
uv run --no-sync python --version
uv run --no-sync python scripts/project_status.py
```

## 2. Validación estática

```bash
uv run --no-sync python -m compileall -q src pipelines scripts
uv run --no-sync python scripts/check_notebooks.py
uv run --no-sync ruff check .
uv run --no-sync mypy src
```

`check_notebooks.py` valida sintaxis/estructura de los 62 notebooks; no sustituye su ejecución.

## 3. Tests automatizados

Suite completa:

```bash
uv run --no-sync pytest -q
```

M8 aislado:

```bash
uv run --no-sync pytest -q tests/unit/test_m8_*.py
```

No avanzar al gate final si existen fallos bloqueantes no explicados.

## 4. Ejecutar notebooks M1–M6

Los notebooks son secuenciales y materializan evidencia persistida:

```bash
uv run --no-sync python scripts/execute_notebooks.py --group m1
uv run --no-sync python scripts/execute_notebooks.py --group m2
uv run --no-sync python scripts/execute_notebooks.py --group m3
uv run --no-sync python scripts/execute_notebooks.py --group m4
uv run --no-sync python scripts/execute_notebooks.py --group m5
uv run --no-sync python scripts/execute_notebooks.py --group m6
```

Después verificar que `docs/decisions/M1_GATE.md` ... `M6_GATE.md` permanezcan `CLOSED`.

## 5. M7 — qué se puede probar ahora

M7 está correctamente congelado desde 2026-09-23 y comienza cohorts genuinamente futuros el 2026-09-24.

Ahora se puede verificar el estado y revalidar el freeze (`60`) sin intentar fabricar cohorts futuros:

```bash
uv run --no-sync python scripts/project_status.py
uv run --no-sync python -m jupyter nbconvert --to notebook --execute --inplace notebooks/60_prospective_protocol_freeze.ipynb
```

Los notebooks `61`–`67` **no deben forzarse a pasar** antes de que existan cohorts y outcomes maduros. El protocolo exige 180 días de follow-up, reporting lag y múltiples cohorts. Que M7 siga `ACTIVE` durante este periodo es el resultado correcto.

Cuando exista evidencia futura suficiente, ejecutar:

```bash
uv run --no-sync python scripts/execute_notebooks.py --group m7
```

hasta obtener `M7 ✅ CLOSED` con datos reales.

## 6. M8 — ejecución completa

La vía recomendada es el pipeline único:

```bash
uv run --no-sync python pipelines/run_advanced_m8.py
```

Equivale metodológicamente a ejecutar:

```text
70 semantic NLP
71 temporal graph intelligence
72 contextual anomaly detection
73 M8 matrix + PIT audit
74 temporal ablation
75 survival outcomes/censoring
76 survival analysis
77 M8 gate
```

También puede validarse notebook por notebook:

```bash
uv run --no-sync python scripts/execute_notebooks.py --group m8
```

## 7. Evidencia obligatoria de M8

Antes de aceptar `M8 ✅ CLOSED` deben existir:

```text
data/gold/features/m8_semantic_features.parquet
data/gold/features/m8_graph_features.parquet
data/gold/features/m8_anomaly_features.parquet
data/gold/ml/argos_m8_dev.parquet
data/gold/survival/m8_survival_outcomes.parquet
artifacts/models/m8/isolation_forest.joblib
artifacts/models/m8/cox_ph.joblib
artifacts/manifests/m8_semantic.json
artifacts/manifests/m8_graph.json
artifacts/manifests/m8_anomaly.json
artifacts/manifests/m8_pit_audit.json
artifacts/manifests/m8_ablation.json
artifacts/manifests/m8_feature_selection.json
artifacts/manifests/m8_survival_outcomes.json
artifacts/manifests/m8_survival.json
reports/advanced/70_validation.parquet
reports/advanced/71_validation.parquet
reports/advanced/72_validation.parquet
reports/advanced/73_validation.parquet
reports/advanced/74_validation.parquet
reports/advanced/75_validation.parquet
reports/advanced/76_validation.parquet
reports/advanced/m8_gate_report.parquet
docs/decisions/M8_GATE.md
```

## 8. Interpretación del cierre M8

Son válidos ambos resultados de feature ablation:

```text
PROMOTE_M8_FEATURES
RESEARCH_COMPLETE_NO_PROMOTION
```

El segundo no es un fracaso: demuestra que NLP/grafos/anomalías fueron evaluados rigurosamente y no justificaron promoción bajo el protocolo de desarrollo.

Survival debe completar su propia evidencia independientemente del resultado del ablation.

## 9. Verificación final

Después de M8:

```bash
uv run --no-sync python scripts/project_status.py
uv run --no-sync pytest -q
uv run --no-sync python scripts/check_notebooks.py
uv run --no-sync ruff check .
uv run --no-sync mypy src
```

El estado correcto antes de que madure M7 puede ser:

```text
M1–M6  CLOSED
M7     ACTIVE / PROSPECTIVE EVIDENCE PENDING
M8     CLOSED
Technical project implementation: COMPLETE
Prospective longitudinal validation: ACTIVE
```

Cuando M7 cierre con cohorts futuros reales:

```text
M1–M8: evidencias de cierre completas
ARGOS: COMPLETE para el alcance declarado
```

### macOS / Apple Silicon note

M8 semantic closure forces Sentence Transformers to CPU, FAISS exact `IndexFlatIP`, and one native thread. This intentionally trades speed for deterministic/stable execution after native MPS/HNSW SIGSEGVs were observed during closure runs.


## 10. Handoff posterior al cierre técnico — M9

Después de verificar M8 y el QA del repositorio, el desarrollo continúa en una línea de producto independiente:

```text
M1–M6  CLOSED
M7     ACTIVE / PROSPECTIVE EVIDENCE PENDING
M8     CLOSED — RESEARCH_COMPLETE_NO_PROMOTION
M9     NEXT — Analytical Platform / Frontend
```

M9 no requiere volver a ejecutar M1–M8 para iniciar el trabajo de interfaz. Debe consumir artefactos persistidos y contratos de presentación derivados de la evidencia ya gobernada.

Antes de integrar cada pantalla con datos reales se debe validar:

- origen y versión del artefacto;
- semántica de cada métrica;
- separación entre score gobernado y señal experimental;
- ausencia de campos post-`t0` presentados como explicación causal;
- disclaimer de priorización/revisión;
- estado M7 visible como `ACTIVE`, no como validación concluida.

Ver `docs/M9_FRONTEND_PLAN.md`.
