\
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def bronze(self) -> Path:
        return self.root / "data" / "bronze"

    @property
    def silver(self) -> Path:
        return self.root / "data" / "silver"

    @property
    def gold(self) -> Path:
        return self.root / "data" / "gold"

    @property
    def configs(self) -> Path:
        return self.root / "configs"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @classmethod
    def discover(cls, start: Path | None = None) -> "ProjectPaths":
        current = (start or Path.cwd()).resolve()
        for candidate in [current, *current.parents]:
            if (candidate / "pyproject.toml").exists():
                return cls(candidate)
        raise FileNotFoundError(
            "Could not locate project root. Expected a parent directory containing pyproject.toml."
        )

    def ensure_runtime_dirs(self) -> None:
        for path in [
            self.reports / "profiling",
            self.reports / "quality",
            self.reports / "figures",
            self.reports / "experiments",
        ]:
            path.mkdir(parents=True, exist_ok=True)
