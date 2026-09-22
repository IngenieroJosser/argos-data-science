#!/usr/bin/env bash
set -euo pipefail

mkdir -p \
  configs \
  data/{bronze,silver,gold,external,samples} \
  docs/{data-dictionary,target-specs,decisions} \
  reports/{profiling,quality,figures,experiments} \
  src/argos/{ingestion,profiling,quality,entities,targets,features,models,evaluation,common} \
  pipelines sql scripts tests/{unit,integration} artifacts/models

for d in \
  src/argos \
  src/argos/{ingestion,profiling,quality,entities,targets,features,models,evaluation,common}; do
  touch "$d/__init__.py"
done

for d in \
  data/{bronze,silver,gold,external,samples} \
  docs/{data-dictionary,target-specs,decisions} \
  reports/{profiling,quality,figures,experiments} \
  pipelines sql tests/{unit,integration} artifacts/models; do
  touch "$d/.gitkeep"
done

echo "ARGOS workspace structure is ready."
