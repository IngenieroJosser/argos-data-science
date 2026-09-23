# ARGOS — Problem Definition

> **Documento de definición del problema**
>
> Proyecto: ARGOS — Plataforma de inteligencia de riesgo para contratación pública  
> Versión: 1.4  
> Estado: M1 ✅ CLOSED · M2 ✅ CLOSED · M3 ✅ CLOSED · M4 ✅ CLOSED · M5 ✅ CLOSED · M6 ▶ READY

---

## 1. Contexto

ARGOS es un proyecto de ciencia de datos orientado al análisis de contratación pública a partir de datos abiertos de SECOP II.

El propósito del proyecto no es determinar si un contrato, proveedor o entidad es "corrupto". Los datasets disponibles no proporcionan una etiqueta confiable de corrupción y una inferencia de ese tipo sería metodológicamente incorrecta.

ARGOS busca construir un sistema de **priorización analítica de riesgo** que permita identificar contratos, procesos, proveedores, relaciones o comportamientos que presenten características históricas, estadísticas, temporales, semánticas o relacionales asociadas con eventos contractuales adversos o con patrones atípicos.

El sistema deberá distinguir explícitamente entre:

- riesgo predictivo;
- anomalía estadística;
- asociación;
- evidencia causal;
- alerta para revisión humana.

Una alerta generada por ARGOS debe interpretarse como una señal para análisis posterior, no como una acusación.

---

## 2. Problema de decisión

### 2.1 Decisión que el sistema pretende apoyar

Dado un conjunto grande de contratos y procesos públicos, existe una capacidad limitada para revisarlos manualmente.

ARGOS debe ayudar a responder:

> **¿Qué contratos deberían ser priorizados para revisión analítica adicional, utilizando únicamente información disponible hasta el momento de evaluación?**

Por lo tanto, el sistema no se optimizará solamente para obtener una métrica de clasificación elevada. También deberá producir un ranking útil bajo una capacidad de revisión limitada.

---

## 3. Unidad principal de análisis

La unidad primaria propuesta es:

> **un contrato en un instante de evaluación determinado.**

Identificador conceptual:

```text
(contract_id, snapshot_date)
```

Esto permite construir observaciones históricas correctas y evita utilizar información futura accidentalmente.

En etapas posteriores se podrán construir unidades de análisis adicionales:

- proceso de contratación;
- proveedor;
- entidad compradora;
- pareja entidad–proveedor;
- categoría UNSPSC;
- red de participantes;
- entidad–categoría–periodo.

---

## 4. Momento de predicción

Se debe definir explícitamente un momento `t0`.

Definición V1 congelada en M3:

> `t0 = fecha_de_firma` del contrato electrónico.

M1 validó su cobertura y parseabilidad; M2 preservó el campo tipado en Silver; M3 lo utilizó como prediction timestamp, construyó el dataset Gold y auditó su consistencia point-in-time.

Toda variable utilizada por un modelo predictivo deberá satisfacer:

```text
feature_timestamp <= prediction_timestamp
```

No se permitirá información generada después de `t0`.

---

## 5. Pregunta predictiva inicial

La primera pregunta de modelado será:

> **Dada la información conocida hasta `t0`, ¿cuál es la probabilidad de que el contrato presente una modificación contractual relevante durante los siguientes 180 días?**

Formalmente:

\[
P(Y_{180}=1 \mid X_{t0})
\]

con una etiqueta binaria definida únicamente para contratos con ventana de observación completa.

Para M3 V1, la definición operacional queda restringida a un evento canónico `ADICION EN EL VALOR` registrado en la fuente Silver de Adiciones.

---

## 6. Targets candidatos

El proyecto será multiobjetivo, pero no se desarrollarán todos los targets simultáneamente.

### Target inicial

`y_addition_180d`

Definición M3 V1:

- `t0 = fecha_de_firma`;
- evento positivo: `ADICION EN EL VALOR`;
- ventana: `t0 < event_at <= t0 + 180 días`;
- contratos con horizonte incompleto quedan censurados y reciben label `NULL`;
- la especificación autoritativa vive en `docs/target-specs/y_addition_180d.md`.

### Targets posteriores

- `y_addition_365d`
- `y_sanction_365d`
- `y_payment_delay`
- `y_large_value_increase`
- `time_to_first_addition`
- `time_to_sanction`

Cada target deberá tener un documento de definición independiente que incluya:

- fuente;
- reglas;
- timestamps;
- horizonte;
- censoring;
- exclusiones;
- tasa de positivos;
- posibles sesgos.

---

## 7. Datasets disponibles

Actualmente se dispone, como mínimo, de las siguientes fuentes SECOP II en la capa `bronze`:

1. Procesos de contratación.
2. Contratos electrónicos.
3. Proponentes por proceso.
4. Proveedores registrados.
5. Adiciones.
6. Plan de pagos.
7. Multas y sanciones.

Estos archivos contienen millones de registros y no se asumirán relaciones, claves, tipos ni calidad hasta validarlos empíricamente.

---

## 8. Relaciones conceptuales esperadas

Modelo conceptual inicial:

```text
ENTITY
   |
   | publica
   v
PROCESS
   |
   | recibe propuestas
   v
BID / PROPONENT
   |
   | adjudica
   v
CONTRACT
   |
   +----------> ADDITION
   |
   +----------> PAYMENT
   |
   +----------> SANCTION

SUPPLIER
   |
   +----------> BID
   |
   +----------> CONTRACT
```

Este modelo comenzó como hipótesis de Data Understanding. M1 y M2 verificaron las relaciones y cardinalidades necesarias para V1 y materializaron relaciones canónicas para contracts, processes, suppliers, bidders y additions. `payments` y `sanctions` permanecen explícitamente diferidos del scope V1.

---

## 9. Familias de variables candidatas

### 9.1 Contrato

- valor inicial;
- modalidad;
- tipo;
- duración;
- categoría;
- ubicación;
- entidad;
- características del proceso.

### 9.2 Historial del proveedor

Calculado exclusivamente antes de `t0`:

- número de contratos anteriores;
- valor contratado acumulado;
- valor medio y mediano;
- frecuencia de adjudicación;
- historial de adiciones;
- historial de sanciones;
- diversidad de entidades;
- diversidad de categorías;
- concentración de ingresos contractuales.

### 9.3 Historial de la entidad

- contratos anteriores;
- gasto histórico;
- tasa histórica de adiciones;
- cantidad de proveedores;
- concentración por proveedor;
- comportamiento por categoría.

### 9.4 Relación entidad–proveedor

- número de relaciones previas;
- valor previamente adjudicado;
- porcentaje del gasto de la entidad hacia el proveedor;
- porcentaje del negocio público del proveedor proveniente de la entidad;
- recencia de relaciones previas.

### 9.5 Competencia

- número de proponentes;
- historial competitivo;
- repetición de conjuntos de competidores;
- concentración de adjudicaciones;
- tasa histórica de éxito de cada participante.

### 9.6 Texto

A partir de objeto/descripción contractual:

- embeddings;
- similitud semántica;
- cluster semántico;
- desviación del valor respecto a contratos semánticamente similares.

### 9.7 Grafo

- degree;
- weighted degree;
- PageRank;
- betweenness;
- comunidades;
- concentración;
- patrones de co-participación;
- embeddings de nodos.

---

## 10. Restricción crítica: Point-in-Time Correctness

ARGOS debe garantizar que cada feature represente únicamente conocimiento disponible en el momento de predicción.

Ejemplo correcto:

```text
supplier_previous_contracts(t0)
```

Ejemplo incorrecto:

```text
supplier_total_contracts_calculated_using_all_years
```

aunque ambos describan al mismo proveedor.

Esta restricción aplica a:

- agregaciones;
- joins;
- variables de red;
- estadísticas por categoría;
- embeddings derivados de datos históricos;
- tasas de eventos;
- datos de pagos;
- sanciones;
- adiciones.

---

## 11. Data leakage

Se considerará leakage cualquier información que:

1. sea posterior a `t0`;
2. sea consecuencia directa del target;
3. incorpore estadísticas calculadas utilizando el periodo de validación/test;
4. permita inferir indirectamente un resultado futuro;
5. haya sido actualizada retrospectivamente en la fuente.

Las variables sospechosas deberán registrarse en un `leakage-audit`.

---

## 12. Censoring

Un contrato reciente no puede clasificarse automáticamente como negativo si todavía no han transcurrido los 180 días necesarios para observar el target.

Para `y_addition_180d`:

```text
eligible_for_label = observation_end_date >= t0 + 180 days
```

Los contratos sin seguimiento suficiente deberán:

- excluirse del problema de clasificación, o
- modelarse explícitamente mediante técnicas de supervivencia.

---

## 13. Validación

No se utilizará como evaluación principal un split aleatorio tradicional.

ARGOS utilizará validación temporal.

Ejemplo conceptual:

```text
Train       -> periodos históricos
Validation  -> periodo posterior
Test        -> periodo futuro no utilizado durante desarrollo
```

Las fechas definitivas dependerán de:

- cobertura temporal real;
- calidad;
- disponibilidad completa del target;
- cambios estructurales en SECOP.

También se evaluará estabilidad por:

- entidad;
- departamento;
- sector;
- modalidad;
- categoría;
- tamaño contractual.

---

## 14. Métricas técnicas

Debido al posible desbalance, `accuracy` no será una métrica principal.

Métricas candidatas:

- PR-AUC;
- ROC-AUC;
- log loss;
- Brier Score;
- Expected Calibration Error;
- precision;
- recall;
- F1 cuando sea pertinente;
- Precision@K;
- Recall@K;
- lift;
- gain.

---

## 15. Métricas de decisión

El sistema se concibe como herramienta de priorización bajo capacidad limitada.

Ejemplo:

> Si solo pueden revisarse los 500 contratos con score más alto, ¿qué porcentaje de eventos futuros está contenido en esos 500 contratos?

Por tanto, se evaluarán especialmente:

```text
Precision@K
Recall@K
Lift@K
Cumulative Gain
```

para diferentes valores de `K`.

---

## 16. Baseline

Antes de utilizar modelos avanzados se construirán:

### Baseline no-ML

- prevalencia global;
- reglas heurísticas simples;
- ranking por una o dos variables históricas.

### Baseline ML

- Logistic Regression.

El baseline debe ser reproducible, interpretable y temporalmente correcto.

Un modelo complejo solo se considerará útil si supera de forma consistente al baseline en el test temporal y aporta valor suficiente para justificar su complejidad.

---

## 17. Modelos candidatos

### Fase supervisada

- Logistic Regression;
- LightGBM;
- XGBoost;
- CatBoost.

### Anomalías

- Isolation Forest;
- Local Outlier Factor;
- métodos estadísticos robustos;
- Autoencoders, si existe justificación.

### Supervivencia

- Kaplan-Meier;
- Cox Proportional Hazards;
- Random Survival Forest;
- modelos boosting de supervivencia.

### NLP

- Sentence Transformers;
- clustering semántico;
- nearest neighbors.

### Grafos

- NetworkX inicialmente;
- Node2Vec;
- GraphSAGE;
- GAT;
- link prediction, si el problema lo justifica.

Los modelos avanzados no forman parte de la primera iteración.

---

## 18. Riesgos metodológicos

ARGOS deberá controlar explícitamente:

- data leakage;
- target leakage;
- survivorship bias;
- right censoring;
- duplicated entities;
- cambios de identificadores;
- valores monetarios atípicos;
- missingness no aleatorio;
- cambios regulatorios o de captura;
- concept drift;
- covariate shift;
- sesgo por cobertura del sistema;
- asociaciones interpretadas incorrectamente como causalidad.

---

## 19. Entity Resolution

Los proveedores y entidades pueden presentar:

- NIT inconsistentes;
- nombres escritos de formas distintas;
- cambios de razón social;
- caracteres especiales;
- abreviaciones;
- datos faltantes.

Se deberá construir una estrategia de identidad con niveles:

1. identificador oficial confiable;
2. identificador normalizado;
3. reglas determinísticas;
4. matching probabilístico/fuzzy cuando sea necesario.

Nunca se fusionarán registros únicamente porque los nombres sean similares sin medir el riesgo de falso match.

---

## 20. Ética e interpretación

ARGOS no deberá utilizar expresiones como:

- "contrato corrupto";
- "proveedor corrupto";
- "entidad fraudulenta";

a partir de una predicción o anomalía.

Terminología aceptada:

- score de riesgo;
- patrón atípico;
- evento contractual predicho;
- anomalía;
- señal analítica;
- prioridad de revisión.

Las decisiones finales requieren evaluación humana y contexto adicional.

---

## 21. Criterios de éxito de la primera versión

La versión 1 se considerará científicamente satisfactoria si:

1. los datasets principales están perfilados y documentados;
2. las claves y cardinalidades están verificadas;
3. existe un modelo de datos reproducible Bronze → Silver → Gold;
4. existe una definición reproducible del target;
5. el dataset ML es point-in-time correct;
6. existe validación temporal;
7. existe un baseline reproducible;
8. las probabilidades pueden evaluarse en calibración;
9. se documentan errores y segmentos problemáticos;
10. todo experimento puede reconstruirse desde código y datos versionados.

**Estado tras el cierre de M3:** los criterios 1–6 están materializados y auditados; la infraestructura de reproducibilidad para el criterio 10 está establecida mediante manifests, gates y configuración versionada. Los criterios 7–9 son responsabilidad central de M4 Modeling & Evaluation.

---

## 22. Fuera de alcance de la primera versión

No pertenecen a la primera iteración:

- acusaciones o clasificación de corrupción;
- GNNs;
- LLMs;
- modelos multimodales complejos;
- microservicios distribuidos;
- infraestructura cloud;
- streaming en tiempo real;
- dashboards empresariales completos;
- inferencia causal definitiva.

Se incorporarán únicamente después de validar que el problema base, las etiquetas y el dataset histórico son correctos.

---

## 23. Preguntas de Data Understanding — resolución actual

Las preguntas originales de Data Understanding se mantienen como trazabilidad, pero después de M1–M3 varias ya tienen una resolución operativa V1.

| pregunta | estado V1 | resolución / tratamiento |
|---|---|---|
| ¿Cuál es la mejor fecha para representar `t0`? | RESUELTA V1 | `fecha_de_firma`; validada y utilizada por Gold |
| ¿Cuál es la clave más confiable entre proceso y contrato? | RESUELTA V1 | `contracts.proceso_de_compra → processes.id_del_portafolio` |
| ¿Las adiciones poseen timestamp suficientemente confiable? | RESUELTA V1 | `event_at` canónico validado; cutoff observado 2026-09-09 |
| ¿Cómo se representa una modificación contractual? | RESUELTA V1 | Silver preserva tipos; target V1 usa exclusivamente `ADICION EN EL VALOR` |
| ¿Existen contratos con múltiples proveedores? | ABIERTA / DOMINIO | no se fuerza una interpretación adicional en V1 |
| ¿Cómo se representan consorcios/uniones temporales? | PARCIAL | se preservan atributos disponibles; entity resolution no fuerza identidades ambiguas |
| ¿Qué tan estable es el NIT? | PARCIAL | resolución determinística solo cuando la evidencia es única; ambiguos permanecen explícitos |
| ¿Existe información modificada retrospectivamente? | CONTROLADA V1 | campos snapshot/mutables fueron segregados y excluidos del model matrix |
| ¿Cuál es la cobertura temporal de cada dataset? | PERFILADA | M1/M2 documentan cobertura; M3 congela el periodo analítico V1 |
| ¿Existen periodos con cambios abruptos de calidad? | MONITOREAR M5 | M4 confirmó cambios materiales de prevalencia entre TRAIN, VALIDATION H1/H2 y TEST; M5 debe ampliar drift/backtesting temporal |
| ¿Qué porcentaje puede unirse correctamente entre datasets? | MEDIDO | relaciones canónicas y coberturas están persistidas en M2 |
| ¿Qué proporción tiene seguimiento suficiente para labels? | RESUELTA V1 | 5,312,182 contratos elegibles para 180 días |
| ¿Cuál es la prevalencia del target por año? | RESUELTA V1 | perfil anual persistido en `reports/gold/20_target_by_year.parquet` |
| ¿Hay segmentos que requieran un modelo separado? | PARCIAL M4 | M4 persistió error analysis por segmentos; no hay evidencia suficiente para promover modelos separados y M5 debe evaluar estabilidad temporal/operativa |
| ¿Qué variables son conocidas en `t0`? | RESUELTA V1 | feature registry Gold de 41 features auditadas |

La existencia de una resolución V1 no implica que la decisión sea universal o definitiva; cualquier cambio de target, snapshot o fuente exige revalidación.

---

## 24. Hipótesis iniciales

Estas hipótesis son preguntas de investigación, no conclusiones.

### H1
Una menor competencia histórica se asocia con una mayor probabilidad de modificaciones contractuales posteriores.

### H2
Una alta concentración entidad–proveedor contiene información predictiva adicional después de controlar por valor, sector y modalidad.

### H3
Contratos cuyo valor se desvía considerablemente de contratos semánticamente comparables presentan una tasa diferente de eventos contractuales posteriores.

### H4
El historial temporal de un proveedor aporta señal predictiva adicional frente a utilizar únicamente atributos del contrato actual.

### H5
Las variables relacionales de grafo aportan señal incremental frente a un modelo tabular correctamente construido.

Cada hipótesis deberá probarse utilizando un diseño de evaluación previamente definido.

---

## 25. Resultado predictivo V1

M4 validó el primer experimento supervisado completo sin reabrir el contrato Gold. El modelo seleccionado fue `hist_gradient_boosting` con calibración isotónica. Sobre TEST temporal 2025 obtuvo PR-AUC `0.135250`, ROC-AUC `0.872745`, Brier `0.009638`, ECE `0.002843` y Lift@1% `25.274x`. El gate M4 cerró con 14/14 checks bloqueantes.

M5 amplió esta evidencia con rolling-origin backtesting, explainability, incertidumbre, drift/calibración, revalidación de familias y un fresh OOT 2026 ya consumido. El OOT confirma señal útil por encima de random, pero con degradación temporal material. Por ello M5 cierra la evidencia de robustez y M6 queda encargado de la operacionalización controlada; no se autoriza decisión jurídica autónoma.

Limitaciones transportadas: drift de prevalencia, calibración de cola alta, ausencia de atribución explícita por feature y falta de evidencia monotónica de valor incremental para todas las familias de features.

---

## 26. Principio rector

> **Primero construir una representación histórica correcta del mundo; después intentar predecirlo.**

En ARGOS, la calidad del modelado temporal, las entidades y las etiquetas tiene prioridad sobre la complejidad algorítmica.


---

## 24. Estado posterior a M5

M5 cerró con 16/16 checks bloqueantes y conserva ARGOS V1 como benchmark histórico congelado. La evidencia adicional incluye backtesting 2021–2024, explainability, bootstrap temporal, drift/calibración, revalidación de familias y fresh OOT 2026.

El fresh OOT 2026 obtuvo PR-AUC 0.053274 y Lift@1% 6.257x sobre una prevalencia de 1.3713%. Existe generalización útil, pero con degradación frente a TEST 2025 y con cobertura parcial del año.

La siguiente fase, M6, corresponde a productionization/MLOps: operacionalizar pipelines, serving, registry, observabilidad, monitoreo, rollback y auditoría. ARGOS continúa siendo una ayuda para priorización y revisión humana; no se redefine como sistema autónomo de sanción, elegibilidad o decisión legal.
