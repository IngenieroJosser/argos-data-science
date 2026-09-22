from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from argos.common.names import normalize_name


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    source_id: str
    name: str
    match_tokens: tuple[str, ...]
    source_url: str
    candidate_keys: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class RelationshipSpec:
    key: str
    left_dataset: str
    right_dataset: str
    left_keys: tuple[str, ...]
    right_keys: tuple[str, ...]


@dataclass(frozen=True)
class RelationshipCandidateSpec:
    key: str
    left_dataset: str
    right_dataset: str
    left_keys: tuple[str, ...]
    right_key_candidates: tuple[tuple[str, ...], ...]


def load_registry(path: Path) -> tuple[dict[str, DatasetSpec], dict[str, RelationshipSpec]]:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    datasets: dict[str, DatasetSpec] = {}
    for key, cfg in raw["datasets"].items():
        datasets[key] = DatasetSpec(
            key=key,
            source_id=cfg["source_id"],
            name=cfg["name"],
            match_tokens=tuple(normalize_name(value) for value in cfg["match_tokens"]),
            source_url=cfg["source_url"],
            candidate_keys=tuple(
                tuple(normalize_name(column) for column in columns)
                for columns in cfg.get("candidate_keys", [])
            ),
        )

    relationships: dict[str, RelationshipSpec] = {}
    for key, cfg in raw.get("relationships", {}).items():
        relationships[key] = RelationshipSpec(
            key=key,
            left_dataset=cfg["left_dataset"],
            right_dataset=cfg["right_dataset"],
            left_keys=tuple(normalize_name(value) for value in cfg["left_keys"]),
            right_keys=tuple(normalize_name(value) for value in cfg["right_keys"]),
        )
    return datasets, relationships


def load_relationship_candidates(path: Path) -> dict[str, RelationshipCandidateSpec]:
    """Load relationship hypotheses that require empirical key resolution."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    result: dict[str, RelationshipCandidateSpec] = {}
    for key, cfg in raw.get("relationship_candidates", {}).items():
        result[key] = RelationshipCandidateSpec(
            key=key,
            left_dataset=cfg["left_dataset"],
            right_dataset=cfg["right_dataset"],
            left_keys=tuple(normalize_name(value) for value in cfg["left_keys"]),
            right_key_candidates=tuple(
                tuple(normalize_name(column) for column in candidate)
                for candidate in cfg["right_key_candidates"]
            ),
        )
    return result


def discover_dataset_files(
    bronze_dir: Path,
    specs: dict[str, DatasetSpec],
) -> dict[str, Path]:
    """Resolve one local CSV snapshot per dataset using normalized filename tokens."""
    files = sorted(bronze_dir.glob("*.csv"))
    resolved: dict[str, Path] = {}

    normalized_files = {path: normalize_name(path.stem) for path in files}
    for key, spec in specs.items():
        matches = [
            path
            for path, normalized in normalized_files.items()
            if all(token in normalized for token in spec.match_tokens)
        ]
        if len(matches) == 0:
            raise FileNotFoundError(
                f"No CSV matched dataset={key!r}, tokens={spec.match_tokens}. "
                f"Available files: {[path.name for path in files]}"
            )
        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple CSV snapshots matched dataset={key!r}: "
                f"{[path.name for path in matches]}. Keep one active snapshot per "
                "source in data/bronze or make match_tokens more specific."
            )
        resolved[key] = matches[0]
    return resolved
