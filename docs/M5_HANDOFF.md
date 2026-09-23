# ARGOS — Handoff M4 → M5

> **Origen:** M4 — Modeling & Evaluation  
> **Estado de origen:** ✅ CLOSED — 14/14 checks bloqueantes  
> **Destino:** M5 — Advanced Data Science & Robustness  
> **Estado de destino:** ▶ READY  
> **Modelo de referencia:** ARGOS V1 — `hist_gradient_boosting + isotonic`

## 1. Propósito

M5 no comienza desde cero. Parte de un baseline predictivo temporalmente validado y debe responder una pregunta más exigente:

> ¿Qué componentes avanzados mejoran de forma reproducible la utilidad, robustez, explicabilidad o cobertura de ARGOS sin romper point-in-time correctness ni reutilizar el TEST consumido?

## 2. Contratos congelados de entrada

```text
Gold schema       m3-gold-v1
Model schema      m4-model-v1
target            y_addition_180d
t0                fecha_de_firma
horizon           180 días
model matrix      data/gold/ml/argos_v1.parquet
features V1       41 PIT-auditadas
V1 model          hist_gradient_boosting
calibration       isotonic
```

Los documentos de autoridad son:

```text
docs/decisions/M3_GATE.md
docs/decisions/M4_GATE.md
docs/decisions/M4_CLOSURE_REVIEW_2026-09-23.md
docs/models/ARGOS_V1_MODEL_CARD.md
docs/target-specs/y_addition_180d.md
```

## 3. TEST 2025 está consumido

Esta es la principal regla de gobernanza para M5.

El conjunto TEST 2025 ya produjo la evaluación final de ARGOS V1. Por lo tanto:

```text
NO: seleccionar features usando TEST 2025
NO: escoger modelos usando TEST 2025
NO: hacer tuning con TEST 2025
NO: escoger calibrador/threshold con TEST 2025
NO: declarar una nueva evaluación “out-of-sample” reutilizando TEST 2025
```

M5 puede conservar las métricas 2025 como **benchmark histórico de V1**, no como criterio de optimización.

Para una nueva afirmación final de generalización se requiere un holdout temporal posterior no utilizado durante el desarrollo, idealmente construido desde un snapshot futuro. Mientras ese holdout no exista, M5 debe apoyarse en rolling-origin / temporal backtesting dentro de periodos de desarrollo.

## 4. Baseline que M5 debe superar o complementar

TEST V1:

| métrica | valor |
|---|---:|
| PR-AUC | 0.135250 |
| ROC-AUC | 0.872745 |
| Brier | 0.009638 |
| ECE | 0.002843 |
| Precision@1% | 26.4155% |
| Recall@1% | 25.2754% |
| Lift@1% | 25.274x |

Estas cifras no se convierten en targets de tuning sobre 2025. Sirven como referencia histórica del sistema V1 ya cerrado.

## 5. Deuda metodológica prioritaria

### Robustez temporal

La prevalencia cambia sustancialmente entre TRAIN, VALIDATION H1/H2 y TEST. M5 debe introducir evaluación rolling-origin, estabilidad por cohortes y análisis de drift de features/scores.

### Explainability

M4 tiene diagnósticos por segmentos, pero no atribuciones explícitas por feature. M5 debe persistir como mínimo explicación global robusta y un mecanismo local interpretable para casos priorizados.

### Uncertainty

Las métricas actuales son estimaciones puntuales. M5 debe añadir intervalos de confianza o bootstrap temporal/estratificado para PR-AUC y métricas top-K cuando sea metodológicamente apropiado.

### Feature-family value

Los ablations M4 no muestran dominancia de `all`. Competition features requieren revalidación. Las conclusiones deben basarse en comparaciones con mismo presupuesto/algoritmo y múltiples ventanas temporales.

### Calibration de alto riesgo

Además de ECE global, medir calibration/reliability en top-K y en segmentos operativos relevantes.

### Tie handling del ranking

La calibración isotónica introduce probabilidades repetidas. M5 debe congelar una regla de desempate independiente del orden físico del Parquet, por ejemplo `calibrated_score DESC, raw_score DESC, contract_id ASC`, y medir sensibilidad de las métricas top-K.

### Portabilidad del modelo

Los artefactos `joblib` deben ejecutarse con el entorno versionado que los produjo (`uv.lock`, `scikit-learn 1.9.1` en M4) o con una estrategia de empaquetado/serving explícitamente validada.

## 6. Líneas avanzadas autorizadas

Después de establecer el protocolo de robustez, M5 puede explorar:

```text
CatBoost / LightGBM / XGBoost
Survival Analysis
Anomaly Detection
NLP de objeto/descripción
Graph Analytics
Graph ML
Causal Analysis
Forecasting
Risk Fusion
```

No todas deben entrar al modelo final. Cada componente debe demostrar valor incremental mediante ablation y evaluación temporal.

## 7. Reglas point-in-time

M5 hereda sin cambios:

```text
feature_timestamp <= t0
historical event timestamp < t0
no snapshot state posterior a t0
no full-history aggregation para observaciones antiguas
```

Si un experimento requiere una feature nueva, esta debe construirse en Gold, registrarse y pasar nuevamente por un audit PIT antes de modelarse.

## 8. Criterio de éxito de M5

M5 no debe cerrarse por producir modelos más complejos. Su gate deberá exigir evidencia de al menos:

- protocolo temporal de backtesting reproducible;
- comparación justa contra ARGOS V1;
- contribución incremental de cualquier componente avanzado;
- explicabilidad persistida;
- análisis de drift y calibración por cola/segmento;
- incertidumbre o sensibilidad de métricas operativas;
- separación clara entre benchmark 2025 consumido y un futuro holdout final;
- manifests y lineage de todos los experimentos promovidos.

## 9. Principio

> Complejidad adicional solo entra en ARGOS si aporta evidencia incremental bajo un protocolo temporal más fuerte que el utilizado para crearla.
