from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from argos.common.paths import ProjectPaths


GROUPS = {
    "m1": range(0, 8),
    "m2": range(10, 16),
    "m3": range(20, 28),
    "m4": range(30, 38),
    "m5": range(40, 48),
    "m6": range(50, 58),
    "m7": range(60, 68),
    "m8": range(70, 78),
}


def notebook_number(path: Path) -> int | None:
    prefix = path.name.split("_", 1)[0]
    return int(prefix) if prefix.isdigit() else None


def selected_notebooks(root: Path, group: str) -> list[Path]:
    notebooks = sorted((root / "notebooks").glob("*.ipynb"))
    if group == "all":
        return notebooks
    allowed = set(GROUPS[group])
    return [path for path in notebooks if notebook_number(path) in allowed]


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute ARGOS notebooks sequentially")
    parser.add_argument("--group", choices=[*GROUPS, "all"], default="m8")
    parser.add_argument("--timeout", type=int, default=-1)
    args = parser.parse_args()

    paths = ProjectPaths.discover()
    notebooks = selected_notebooks(paths.root, args.group)
    if not notebooks:
        raise SystemExit(f"No notebooks found for group={args.group}")

    for index, notebook in enumerate(notebooks, start=1):
        print(f"[{index}/{len(notebooks)}] executing {notebook.name}", flush=True)
        command = [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--inplace",
            f"--ExecutePreprocessor.timeout={args.timeout}",
            str(notebook),
        ]
        subprocess.run(command, cwd=paths.root, check=True)
    print(f"Notebook execution PASS — group={args.group}, count={len(notebooks)}")


if __name__ == "__main__":
    main()
