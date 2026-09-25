# ARGOS — M8 Runbook

> **Milestone:** M8 — Advanced Intelligence & Survival  
> **Scope:** NLP semántico + Graph Intelligence + Contextual Anomaly Detection + Survival Analysis  
> **Schema:** `m8-advanced-intelligence-v2`  
> **Baseline:** ARGOS V1/M6 congelado; M7 continúa prospectivamente en paralelo

## Objetivo

M8 completa el alcance técnico avanzado de ARGOS sin reabrir M4–M7 ni reutilizar TEST 2025 u OOT 2026 para selección:

```text
70 semantic NLP
        ↓
71 temporal graph intelligence
        ↓
72 contextual anomaly detection
        ↓
73 M8 development matrix + PIT audit + M7 hash verification
        ↓
74 temporal ablation / feature-family decision
        ↓
75 survival outcomes + administrative censoring
        ↓
76 Kaplan-Meier + penalized Cox PH + survival evaluation
        ↓
77 formal M8 gate
```

M8 no presupone que mayor complejidad mejore el predictor tabular. La parte de feature engineering puede cerrar con `PROMOTE_M8_FEATURES` o `RESEARCH_COMPLETE_NO_PROMOTION`; Survival se evalúa como una pregunta complementaria de tiempo al evento.

## Precondiciones

- `M6 ✅ CLOSED`.
- `artifacts/manifests/m7_protocol_freeze.json` existe y sus hashes siguen coincidiendo.
- En el workspace real existen `data/silver/` y `data/gold/` generados por M2/M3.
- TEST 2025 y fresh OOT 2026 permanecen consumidos.
- Python 3.12 y runtime base instalados desde `uv.lock`.

## Runtime NLP

Las dependencias pesadas de NLP se mantienen fuera del `uv.lock` congelado de ARGOS V1 para no alterar el runtime que M7 está validando:

```bash
uv sync --frozen
uv pip install -r requirements-m8.txt
```

El gate exige Sentence Transformers + FAISS. El manifest persiste modelo, revisión configurada, versiones de paquetes y un `embedding_fingerprint` determinista para auditoría de reproducibilidad.

## Ejecución completa

```bash
uv run --no-sync python pipelines/run_advanced_m8.py
```

O ejecutar secuencialmente los notebooks `70`–`77`.

### 70 — Semantic Intelligence

Fuente por defecto: `objeto_del_contrato` en `data/silver/contracts.parquet`.

Features principales:

- similitud media/máxima/desviación con vecinos anteriores;
- novelty semántica;
- número de vecinos;
- tasa histórica de adiciones en peers solo cuando el label de 180 días ya estaba maduro antes del `t0` actual;
- cobertura/calidad del texto.

PIT obligatorio:

```text
peer_t0 < current_month_start <= current_t0
peer_label_available_at = peer_t0 + 180d
peer_label_available_at < current_t0  (si se usa el target del peer)
```

### 71 — Graph Intelligence

Grafo temporal bipartito proveedor–entidad y red de co-participación.

Features principales: degree, weighted degree, relación proveedor–entidad, HHI, PageRank, componentes conexas, co-bid degree, co-bid weighted degree y repeated-partner share.

Cada snapshot mensual usa únicamente relaciones de meses anteriores. Los bidder edges requieren `publication_at` anterior al snapshot.

### 72 — Contextual Anomaly Detection

`IsolationForest` se ajusta exclusivamente en TRAIN. El output `anomaly_score ∈ [0,1]` es un percentil relativo a TRAIN y permanece separado de `risk_score`.

Una anomalía es una señal de priorización, no evidencia de fraude, corrupción o ilegalidad.

### 73 — Development Matrix + PIT Audit

Materializa:

```text
data/gold/ml/argos_m8_dev.parquet
```

Solo contiene `train` y `validation`. El audit exige cero peers/labels/relaciones futuras, anomaly fit exclusivamente TRAIN, ausencia de TEST/OOT e integridad de los hashes de M7.

### 74 — Temporal Ablation

Compara bajo exactamente la misma semilla de modelado:

```text
tabular
tabular + NLP
tabular + graph
tabular + anomaly
tabular + NLP + graph + anomaly
```

La selección usa únicamente VALIDATION. Incluso si se promueve una familia, el resultado sigue siendo `argos-v2-dev-m8`: cualquier afirmación final de generalización necesita un nuevo future holdout.

### 75 — Survival Outcomes & Administrative Censoring

El problema de supervivencia conserva el mismo evento que el target V1:

```text
t0 = fecha_de_firma
evento = primera ADICION EN EL VALOR dentro de (t0, t0+180d]
```

Para un positivo:

```text
event_observed = 1
duration_days = días hasta la primera adición
```

Para un contrato sin evento dentro del horizonte:

```text
event_observed = 0
duration_days = 180
```

Esto representa censura administrativa al final del horizonte; no significa que el contrato jamás pueda tener una adición después del día 180.

### 76 — Survival Analysis

Modelos:

- Kaplan–Meier para la función de supervivencia no paramétrica;
- Cox Proportional Hazards penalizado con L2.

El encoder y el Cox se ajustan exclusivamente en TRAIN. VALIDATION se utiliza para evaluación.

Salidas principales:

```text
S(30 | X)
S(90 | X)
S(180 | X)
P(event <= 30d | X)
P(event <= 90d | X)
P(event <= 180d | X)
```

Métricas/diagnósticos:

- Harrell C-index;
- Brier de probabilidad de evento a 30/90/180 días;
- tablas de calibración;
- curvas Kaplan–Meier;
- diagnóstico de proportional hazards mediante correlación temporal de residuos tipo Schoenfeld.

Survival no reemplaza el clasificador V1: responde una pregunta complementaria sobre tiempo al evento.

### 77 — Formal Gate

Autoridad: `src/argos/evaluation/m8_gate.py`.

El gate exige evidencia persistida y válida de 70–76, manifests completos, schema consistente, aislamiento de holdouts, protocolo M7 intacto y decisión explícita de feature families.

Solo entonces genera:

```text
docs/decisions/M8_GATE.md
M8 ✅ CLOSED
```

## Regla de gobernanza M7/M8

M7 continúa midiendo prospectivamente **ARGOS V1 congelado**. M8 desarrolla **ARGOS V2-dev**. Ningún resultado M8 modifica los hashes, modelo, calibrador, scoring contract o protocolo prospectivo V1.

El proyecto técnico puede quedar completo con M8 cerrado mientras M7 continúa recolectando evidencia prospectiva. El cierre científico de M7 solo ocurre cuando sus cohorts futuros maduran según `configs/prospective.toml`.

## Resume after an interrupted stage

`pipelines/run_advanced_m8.py` supports `--start-stage 70-77`. Earlier stages are not recomputed.
The runner verifies the persisted semantic and graph artifacts before allowing a resume past stages 70/71.

Example after successful stages 70 and 71:

```bash
uv run --no-sync python pipelines/run_advanced_m8.py --start-stage 72
```

Do not delete the completed semantic or graph artifacts before resuming.
