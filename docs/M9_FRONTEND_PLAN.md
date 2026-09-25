# ARGOS — M9 Plataforma Analítica / Frontend

## 1. Propósito

M9 convierte ARGOS en una experiencia de producto para **priorización y revisión analítica de contratación pública**. La interfaz debe hacer comprensibles, explorables y trazables los resultados ya producidos por la capa de Ciencia de Datos y MLOps.

M9 no es un nuevo experimento de modelado. Es una capa de producto separada que consume evidencia gobernada.

## 2. Estado científico de entrada

```text
M1–M6  ✅ CLOSED
M7     ◐ ACTIVE / EVIDENCE PENDING
M8     ✅ CLOSED — RESEARCH_COMPLETE_NO_PROMOTION
Technical implementation evidence: COMPLETE
```

Implicaciones:

- ARGOS V1 continúa siendo la referencia gobernada para score/ranking;
- M8 aporta contexto analítico avanzado, pero sus familias no fueron promovidas;
- M7 continúa acumulando evidencia futura y no debe presentarse como cerrado.

## 3. Principios de producto

1. **Human-in-the-loop.** La UI prioriza y contextualiza; la decisión final pertenece al analista.
2. **No acusatorio.** Nunca usar “corrupto”, “fraudulento” o equivalentes como resultado del modelo.
3. **Trazabilidad.** Toda vista de scoring debe poder identificar versión, fecha de scoring, `t0` y lineage cuando existan.
4. **Separación de evidencia.** Diferenciar claramente score gobernado, señal experimental y monitoring.
5. **Temporal correctness visible.** La interfaz no debe sugerir que información posterior a `t0` estaba disponible al puntuar.
6. **Read-only primero.** La primera versión no modifica datos científicos ni dispara reentrenamientos.
7. **Batch-first.** La UI consume snapshots/materializaciones reproducibles; tiempo real no es requisito de M9.
8. **Accesibilidad y densidad analítica.** Diseño sobrio, responsive y apto para trabajar con tablas, filtros, gráficos y redes complejas.

## 4. Stack objetivo

```text
Next.js (App Router)
TypeScript
React
Tailwind CSS
componentes accesibles y reutilizables
visualización tabular y temporal
visualización de grafos
pruebas unitarias + e2e del frontend
```

La selección final de librerías de componentes, charts y graph visualization debe documentarse al iniciar la implementación y mantenerse desacoplada del contrato de datos.

## 5. Arquitectura lógica

```text
SECOP II / datos gobernados
        ↓
ARGOS pipelines
        ↓
Gold + scoring + monitoring + manifests
        ↓
M9 presentation/export contract
        ↓
Next.js server layer / BFF
        ↓
React UI
        ↓
Analista humano
```

### Regla

El navegador no debe leer Bronze/Silver directamente ni ejecutar notebooks/modelos. La capa M9 recibirá objetos de presentación derivados de artefactos gobernados.

## 6. Navegación propuesta

### 6.1 Overview

Resumen ejecutivo del snapshot:

- contratos evaluados;
- distribución de prioridad;
- volumen en top-K;
- evolución temporal;
- estado de datos/modelo;
- estado de M7;
- alertas de monitoring.

### 6.2 Prioridad de revisión

Tabla principal de trabajo con:

- ranking determinista;
- score de priorización;
- percentil;
- contrato/proceso;
- proveedor y entidad;
- valor contractual;
- fecha `t0`;
- señales relevantes;
- filtros, búsqueda, orden y paginación.

### 6.3 Contract Intelligence

Vista detallada de un contrato:

- resumen contractual;
- score y posición relativa;
- factores/señales disponibles;
- contexto histórico anterior a `t0`;
- competencia observable;
- anomalías;
- vecinos semánticos;
- relaciones de grafo;
- curva/estimaciones survival cuando aplique;
- lineage y metodología.

### 6.4 Supplier Intelligence

- historial agregado PIT-compatible;
- concentración y recurrencia;
- contratos asociados;
- relaciones de red;
- señales analíticas agregadas sin emitir acusaciones.

### 6.5 Entity Intelligence

- actividad contractual;
- proveedores recurrentes;
- concentración;
- relaciones temporales;
- distribución de prioridades.

### 6.6 Network / Graph Explorer

Exploración visual de relaciones proveedor–entidad y co-participación. Debe distinguir métricas descriptivas de conclusiones causales.

### 6.7 Anomaly Explorer

Exploración de observaciones con `anomaly_score` y contexto de variables. La anomalía se presenta como **rareza estadística/contextual**, no como fraude.

### 6.8 Survival / Temporal Intelligence

Mostrar probabilidades/curvas a horizontes configurados y métricas del análisis de supervivencia con lenguaje descriptivo.

### 6.9 Monitoring

- drift;
- score distribution;
- missingness;
- calibración cuando haya outcomes;
- alertas;
- estado de promoción;
- versión/model lineage.

### 6.10 Methodology & Governance

Debe explicar:

- qué predice ARGOS;
- qué significa `t0`;
- qué significa un score;
- qué no significa;
- estado M1–M9;
- M7 prospectivo activo;
- disclaimer jurídico/analítico.

## 7. Contrato semántico de UI

### Lenguaje permitido

```text
prioridad de revisión
score de priorización
señal analítica
contexto atípico
anomalía estadística
relación histórica
riesgo analítico / prioridad
```

### Lenguaje prohibido como conclusión automática

```text
contrato corrupto
proveedor fraudulento
entidad corrupta
culpable
ilegal
fraude confirmado
```

Disclaimer recomendado y persistente:

> **ARGOS prioriza casos para revisión analítica adicional. Sus scores, anomalías y relaciones no constituyen una acusación ni una conclusión jurídica de fraude o corrupción.**

## 8. Score gobernado vs. inteligencia M8

El frontend debe representar explícitamente:

```text
ARGOS V1 score           → señal gobernada de priorización
NLP / graph / anomaly    → contexto analítico complementario
Survival                 → análisis temporal complementario
M7                       → evidencia prospectiva en curso
```

Como M8 cerró `RESEARCH_COMPLETE_NO_PROMOTION`, ninguna señal M8 debe reemplazar silenciosamente el score principal.

## 9. Contrato de datos de presentación

La implementación debe crear un contrato versionado, por ejemplo `m9-presentation-v1`, con objetos desacoplados de la forma física de Parquet. Familias mínimas:

```text
overview_snapshot
review_queue_item
contract_detail
supplier_detail
entity_detail
graph_subgraph
anomaly_detail
survival_detail
monitoring_snapshot
governance_status
```

Cada objeto debe declarar cuando aplique:

- `snapshot_at`;
- `model_version`;
- `data_version` / manifest hash;
- `contract_id`;
- `t0`;
- `score`;
- `rank` / `percentile`;
- provenance/lineage.

## 10. Fases de implementación

### M9.1 — Design system + shell

- layout;
- navegación;
- tokens;
- responsive;
- estados loading/error/empty;
- disclaimer global.

### M9.2 — Presentation contract + fixture data

- tipos TypeScript;
- schema validation;
- fixtures realistas derivados del contrato;
- server data-access abstraction.

### M9.3 — Core analytical workflow

- Overview;
- Prioridad de revisión;
- Contract Intelligence.

### M9.4 — Intelligence modules

- Supplier / Entity;
- Graph Explorer;
- Anomaly Explorer;
- Survival.

### M9.5 — Monitoring + Governance

- monitoring;
- model/data status;
- methodology;
- M7 status.

### M9.6 — QA de producto

- responsive;
- accessibility;
- unit/component tests;
- e2e de flujos críticos;
- performance;
- revisión de lenguaje no acusatorio;
- reconciliación contra artefactos de origen.

## 11. Criterios de aceptación de M9

M9 podrá cerrarse cuando:

1. el frontend sea reproducible desde instalación limpia;
2. exista un design system coherente y responsive;
3. el workflow Overview → ranking → contrato sea completamente navegable;
4. los datos mostrados sean trazables al contrato de presentación;
5. score gobernado y señales M8 estén visualmente diferenciados;
6. M7 aparezca correctamente como activo;
7. el disclaimer sea visible en superficies de riesgo;
8. no exista inferencia/entrenamiento científico en el cliente;
9. tests de frontend y e2e críticos estén en verde;
10. exista documentación de arquitectura, ejecución y decisiones de UX.

## 12. Fuera de alcance inicial de M9

- autenticación empresarial completa;
- roles/RBAC complejos;
- edición de fuentes SECOP;
- reentrenamiento desde la UI;
- decisiones jurídicas automatizadas;
- infraestructura cloud obligatoria;
- streaming/real-time obligatorio;
- cierre artificial de M7.

Estas capacidades pueden evaluarse después de validar el producto analítico.
