from __future__ import annotations

import json

from argos.common.paths import ProjectPaths
from argos.production.deployment_assets import ensure_deployment_assets


def main() -> None:
    paths = ProjectPaths.discover()
    result = ensure_deployment_assets(paths.root)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not all(bool(item["exists"]) for item in result):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
