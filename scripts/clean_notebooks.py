from __future__ import annotations

import json
from pathlib import Path

from argos.common.paths import ProjectPaths


def main() -> None:
    root = ProjectPaths.discover().root
    notebooks = sorted((root / "notebooks").glob("*.ipynb"))
    cleaned = 0
    for path in notebooks:
        payload = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for cell in payload.get("cells", []):
            if cell.get("cell_type") != "code":
                continue
            if cell.get("execution_count") is not None:
                cell["execution_count"] = None
                changed = True
            if cell.get("outputs", []):
                cell["outputs"] = []
                changed = True
        if changed:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8",
            )
            cleaned += 1
    print(f"Notebook cleanup ✅ {cleaned}/{len(notebooks)} notebooks changed")


if __name__ == "__main__":
    main()
