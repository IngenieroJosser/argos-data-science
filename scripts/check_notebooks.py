from __future__ import annotations

import ast
import json
from pathlib import Path

from argos.common.paths import ProjectPaths


def main() -> None:
    root = ProjectPaths.discover().root
    notebooks = sorted((root / "notebooks").glob("*.ipynb"))
    failures: list[str] = []
    for path in notebooks:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for index, cell in enumerate(payload.get("cells", [])):
                if cell.get("cell_type") != "code":
                    continue
                if cell.get("execution_count") is not None:
                    failures.append(
                        f"{path.name}:cell{index}: execution_count must be null"
                    )
                if cell.get("outputs", []):
                    failures.append(f"{path.name}:cell{index}: outputs must be empty")
                source = "".join(cell.get("source", []))
                if source.strip().startswith(("%", "!")):
                    continue
                ast.parse(source, filename=f"{path.name}:cell{index}")
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
    if failures:
        raise SystemExit("Notebook validation failed:\n" + "\n".join(failures))
    print(f"Notebook validation ✅ {len(notebooks)} notebooks")


if __name__ == "__main__":
    main()
