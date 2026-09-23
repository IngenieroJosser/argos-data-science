FROM python:3.12-slim

ARG UV_VERSION=0.8.22
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir "uv==${UV_VERSION}"
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY configs ./configs
COPY artifacts/models/m4 ./artifacts/models/m4
COPY reports/gold/26_feature_registry.parquet ./reports/gold/26_feature_registry.parquet
COPY docs/models ./docs/models
COPY docs/monitoring ./docs/monitoring
RUN uv sync --frozen --no-dev

# Writable operational paths should normally be mounted as persistent volumes.
RUN mkdir -p /app/data/production /app/reports/production /app/artifacts/manifests /app/artifacts/registry /app/artifacts/contracts /app/artifacts/audit \
    && chown -R nobody:nogroup /app/data/production /app/reports/production /app/artifacts/manifests /app/artifacts/registry /app/artifacts/contracts /app/artifacts/audit

USER nobody
ENTRYPOINT ["/app/.venv/bin/python", "-m", "argos.production.cli"]
CMD ["--help"]
