# M9 — Integración backend ↔ frontend

ARGOS M9 usa un **presentation snapshot** versionado (`m9-presentation-v1`). Next.js no lee Bronze/Silver, no ejecuta notebooks y no recalcula modelos.

## Flujo

```text
Gold / scoring / monitoring / manifests
                ↓
scripts/export_m9_presentation.py
                ↓
frontend/data/argos-presentation.json
                ↓
Next.js BFF /api/argos/snapshot
                ↓
UI
```

## Sincronización

Desde `argos-code`:

```bash
uv run --no-sync python scripts/export_m9_presentation.py \
  --output ../frontend/data/argos-presentation.json
```

Luego en `frontend`:

```bash
yarn dev
```

El exportador usa exclusivamente artefactos gobernados. La cola se enriquece con features PIT-safe de `data/gold/ml/argos_v1.parquet` cuando ese artefacto está disponible. Señales M8 se adjuntan solo como contexto complementario y nunca sustituyen el score ARGOS V1.

Si los Parquet productivos no están disponibles, el snapshot sigue exportando manifests, estado de gobernanza y métricas documentadas en modo `metadata-only`.
