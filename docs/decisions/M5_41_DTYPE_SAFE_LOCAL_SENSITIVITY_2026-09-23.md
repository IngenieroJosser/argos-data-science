# M5.41 — Reparación de perturbaciones dtype-safe

**Fecha:** 2026-09-23  
**Componente:** `41_explainability.ipynb`  
**Estado:** corregido; requiere reejecución del notebook 41.

## Incidente

La fase de sensibilidad local intentaba sustituir un valor de referencia con:

```python
changed.at[changed.index[0], feature] = refs[feature]
```

Para features booleanas tratadas por el modelo como numéricas, el valor de referencia
podía ser `0.0`. Pandas 3.x rechaza esa asignación escalar porque convertir `bool` a
`float` de forma implícita sería un *lossy setitem*, produciendo:

```text
TypeError: Invalid value '0.0' for dtype 'bool'
```

El fallo ocurre en la capa de análisis de explicabilidad; no invalida el modelo M4,
los artefactos Gold ni el backtesting M5 del notebook 40.

## Corrección

Se introdujo `argos.robustness.perturbation` con dos responsabilidades:

1. `reference_values(...)` conserva semántica booleana cuando el dtype de la feature
   es booleano y usa mediana solo para features numéricas no booleanas.
2. `replace_feature_value(...)` reemplaza la columna completa en una copia del caso
   perturbado, en vez de forzar una asignación escalar sobre el dtype original.

Esto también evita el mismo problema para columnas enteras cuyo valor de referencia
sea fraccional.

## Invariantes

- El caso original no se muta.
- No se modifica el modelo ni el calibrador congelados de M4.
- No se utiliza TEST 2025.
- La interpretación continúa siendo sensibilidad por sustitución de una feature,
  no atribución causal.
- El manifest de `41` utilizará implementación
  `m5-41-permutation-local-sensitivity-v2`.

## Reejecución

`40_temporal_backtesting.ipynb` permanece válido. Reiniciar el kernel y ejecutar
`41_explainability.ipynb` desde el inicio. Los notebooks `42–47` deben permanecer
sin ejecutar hasta que `41` termine con todos sus checks bloqueantes en PASS.
