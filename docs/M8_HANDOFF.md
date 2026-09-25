# ARGOS — M8 Handoff

M8 completa el alcance técnico avanzado definido para ARGOS: NLP semántico, grafos temporales, anomalías contextuales y análisis de supervivencia.

## Contrato de salida

Cuando `docs/decisions/M8_GATE.md` marque `M8 ✅ CLOSED`, deben existir:

- `data/gold/features/m8_semantic_features.parquet`;
- `data/gold/features/m8_graph_features.parquet`;
- `data/gold/features/m8_anomaly_features.parquet`;
- `data/gold/ml/argos_m8_dev.parquet`;
- `data/gold/survival/m8_survival_outcomes.parquet`;
- `artifacts/models/m8/isolation_forest.joblib`;
- `artifacts/models/m8/cox_ph.joblib`;
- manifests `m8_semantic`, `m8_graph`, `m8_anomaly`, `m8_pit_audit`, `m8_ablation`, `m8_feature_selection`, `m8_survival_outcomes`, `m8_survival`;
- métricas de ablation y supervivencia en `reports/advanced/`;
- decisión explícita `PROMOTE_M8_FEATURES` o `RESEARCH_COMPLETE_NO_PROMOTION`;
- protocolo M7 sin cambios.

## Lo que M8 no autoriza

- no re-selecciona usando TEST 2025;
- no re-selecciona usando fresh OOT 2026;
- no modifica ARGOS V1/M6/M7;
- no convierte anomaly/graph/semantic/risk scores en conclusiones de corrupción o legalidad;
- no constituye por sí mismo validación prospectiva independiente de ARGOS V2.

## Estado posterior a M8

M8 cerró con:

```text
M8 ✅ CLOSED — RESEARCH_COMPLETE_NO_PROMOTION
Technical implementation: COMPLETE
M7 prospective validation: ACTIVE until future cohorts mature
```

El resultado `RESEARCH_COMPLETE_NO_PROMOTION` preserva ARGOS V1 como referencia gobernada: NLP, grafos y anomalías pueden exponerse como contexto analítico, pero no deben presentarse como una nueva versión promovida del modelo.

La siguiente fase es **M9 — Plataforma Analítica / Frontend**. M9 es posterior al cierre científico/técnico y no modifica la evidencia M8 ni el protocolo M7. Ver `docs/M9_FRONTEND_PLAN.md`.
