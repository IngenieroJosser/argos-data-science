from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


ASSET_BOOTSTRAP_IMPLEMENTATION = "m6-deployment-assets-bootstrap-v1"


@dataclass(frozen=True, slots=True)
class DeploymentAssetStatus:
    asset: str
    target: str
    template: str
    action: str
    exists: bool
    matches_template: bool
    sha256: str | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy_text(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def ensure_deployment_assets(root: Path) -> list[dict[str, object]]:
    """Materialize repository deployment assets if they are missing.

    This function is intentionally narrow and idempotent:
    - it validates that ``root`` is an ARGOS repository;
    - it only creates missing deployment metadata files;
    - it never overwrites an existing target;
    - source content comes from normal, versioned templates so hidden-file
      extraction behavior cannot silently remove the canonical definition.
    """
    root = Path(root).expanduser().resolve()
    if not (root / "pyproject.toml").is_file():
        raise FileNotFoundError(f"Not an ARGOS repository root: {root}")

    assets = [
        ("dockerignore", root / "deploy" / "templates" / "dockerignore", root / ".dockerignore"),
        ("github_ci", root / "deploy" / "templates" / "github_ci.yml", root / ".github" / "workflows" / "ci.yml"),
    ]

    statuses: list[dict[str, object]] = []
    for name, template, target in assets:
        if not template.is_file():
            raise FileNotFoundError(f"Canonical deployment template missing: {template}")
        action = "preserved"
        if not target.exists():
            _atomic_copy_text(template, target)
            action = "created"
        matches = target.is_file() and _sha256(target) == _sha256(template)
        status = DeploymentAssetStatus(
            asset=name,
            target=str(target.relative_to(root)),
            template=str(template.relative_to(root)),
            action=action,
            exists=target.is_file(),
            matches_template=matches,
            sha256=_sha256(target) if target.is_file() else None,
        )
        statuses.append(asdict(status))
    return statuses
