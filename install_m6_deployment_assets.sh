#!/usr/bin/env bash
set -euo pipefail

EXPECTED_DIR_NAME="argos-code"

if [[ ! -f "pyproject.toml" || ! -d "src/argos" ]]; then
  echo "ERROR: ejecuta este script desde la raíz del repositorio ARGOS (donde están pyproject.toml y src/argos)." >&2
  exit 2
fi

mkdir -p .github/workflows

cat > .dockerignore <<'EODOCKER'
# ARGOS Docker build context
.git
.github
.venv
.cache
.pytest_cache
.ruff_cache
.mypy_cache
__pycache__
*.py[cod]
*.log
.DS_Store
.ipynb_checkpoints

# Local analytical data is never copied into the runtime image.
data/bronze
data/silver
data/gold
data/m5
data/production

# Local runtime/report outputs are not image inputs.
reports
artifacts/audit
artifacts/production

# Development-only material.
notebooks
tests
*.zip
EODOCKER

cat > .github/workflows/ci.yml <<'EOCI'
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install 3.12

      - name: Sync locked environment
        run: uv sync --frozen --all-groups

      - name: Compile Python sources
        run: uv run python -m compileall -q src scripts pipelines

      - name: Run unit tests
        run: uv run pytest -q tests/unit

  container-smoke:
    runs-on: ubuntu-latest
    needs: quality
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Build runtime image
        run: docker build -t argos-production:ci .

      - name: Smoke-test production CLI
        run: docker run --rm argos-production:ci argos-production --help
EOCI

printf '\nCreated:\n'
ls -la .dockerignore
ls -la .github/workflows/ci.yml
printf '\nVerification:\n'
test -f .dockerignore && echo '.dockerignore ✅'
test -f .github/workflows/ci.yml && echo 'CI workflow ✅'
test -f Dockerfile && echo 'Dockerfile ✅' || echo 'Dockerfile ❌ (required by notebook 56)'
