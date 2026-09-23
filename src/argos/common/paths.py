from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Canonical filesystem locations used by ARGOS."""

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
        """Discover the repository root from cwd or the installed package path.

        Jupyter kernels can retain a working directory that has been replaced on
        disk. In that state ``Path.cwd()`` raises ``FileNotFoundError``. Falling
        back to this module's location keeps project discovery deterministic.
        """
        starting_points: list[Path] = []

        if start is not None:
            starting_points.append(Path(start).expanduser().resolve(strict=False))
        else:
            try:
                starting_points.append(Path.cwd().resolve())
            except FileNotFoundError:
                pass

        package_project_root = Path(__file__).resolve().parents[3]
        if package_project_root not in starting_points:
            starting_points.append(package_project_root)

        searched: list[Path] = []
        for starting_point in starting_points:
            for candidate in (starting_point, *starting_point.parents):
                if candidate in searched:
                    continue
                searched.append(candidate)
                if (candidate / "pyproject.toml").is_file():
                    return cls(candidate)

        searched_text = "\n".join(f"  - {path}" for path in searched)
        raise FileNotFoundError(
            "Could not locate ARGOS project root. Expected pyproject.toml under:\n"
            f"{searched_text}"
        )

    def ensure_runtime_dirs(self) -> None:
        for path in [
            self.silver,
            self.gold,
            self.reports / "profiling",
            self.reports / "quality",
            self.reports / "figures",
            self.reports / "experiments",
            self.reports / "silver",
            self.reports / "gold",
            self.gold / "labels",
            self.gold / "splits",
            self.gold / "features",
            self.gold / "ml",
            self.root / ".cache" / "duckdb",
            self.root / "artifacts" / "models",
            self.root / "artifacts" / "manifests",
        ]:
            path.mkdir(parents=True, exist_ok=True)
