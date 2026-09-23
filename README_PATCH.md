# ARGOS M6 deployment assets installer

Run this from the repository root (`argos-code`):

```bash
bash /path/to/install_m6_deployment_assets.sh
```

It creates the two hidden repository-root assets required by notebook 56:

- `.dockerignore`
- `.github/workflows/ci.yml`

It does not modify model artifacts, M1–M5 outputs, production scores, audit logs, or M6 notebooks.
