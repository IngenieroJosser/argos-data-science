# Decision — Temporal split freeze M3 V1

**Estado:** FROZEN FOR V1  
**Gold schema:** `m3-gold-v1`

## Periodos

```text
TRAIN       2015-01-01 .. 2023-12-31
VALIDATION  2024-01-01 .. 2024-12-31
TEST        2025-01-01 .. 2025-12-31
```

Los contratos elegibles de 2026 quedan `eligible_out_of_split` para V1. No se mezclan con Test porque el snapshot de eventos de 2026 no representa un año calendario completo.

## Regla de uso

- Train: EDA, feature engineering, fitting.
- Validation: selección/tuning/calibración preliminar.
- Test: evaluación final congelada.

Modificar estos límites después de observar resultados de Test requiere una nueva decisión documentada y una nueva versión del experimento.
