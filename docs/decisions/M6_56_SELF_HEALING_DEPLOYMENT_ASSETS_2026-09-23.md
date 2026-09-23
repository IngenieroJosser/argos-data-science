# M6-56 — Materialización segura de deployment assets

## Contexto
El gate 56 falló repetidamente porque `.dockerignore` y `.github/workflows/ci.yml` no estaban presentes en el root efectivo del repositorio, aun cuando el código del proyecto y el Dockerfile eran válidos. Los archivos ocultos son especialmente susceptibles a perderse durante copias/overlays manuales.

## Decisión
ARGOS conserva definiciones canónicas visibles en `deploy/templates/` y el notebook 56 ejecuta un bootstrap estrecho e idempotente antes del readiness check.

El bootstrap:
- solo crea assets faltantes;
- nunca sobrescribe un archivo existente;
- usa escritura atómica;
- valida que el destino sea un repositorio ARGOS mediante `pyproject.toml`;
- no toca datos, modelos, manifests, scores, thresholds, audit logs ni estado de deployment.

El gate 56 sigue validando la existencia física de los assets finales. No se redujo ningún criterio de aceptación.
