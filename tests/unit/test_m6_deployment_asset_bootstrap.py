from pathlib import Path
import shutil

from argos.production.deployment_assets import ensure_deployment_assets


def _repo_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "deploy" / "templates").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')
    source_root = Path(__file__).resolve().parents[2]
    shutil.copy2(source_root / "deploy" / "templates" / "dockerignore", root / "deploy" / "templates" / "dockerignore")
    shutil.copy2(source_root / "deploy" / "templates" / "github_ci.yml", root / "deploy" / "templates" / "github_ci.yml")
    return root


def test_bootstrap_creates_missing_hidden_assets(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    status = ensure_deployment_assets(root)
    assert (root / ".dockerignore").is_file()
    assert (root / ".github" / "workflows" / "ci.yml").is_file()
    assert all(item["exists"] for item in status)
    assert all(item["matches_template"] for item in status)


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    first = ensure_deployment_assets(root)
    second = ensure_deployment_assets(root)
    assert {item["action"] for item in first} == {"created"}
    assert {item["action"] for item in second} == {"preserved"}


def test_bootstrap_never_overwrites_existing_asset(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    custom = root / ".dockerignore"
    custom.write_text("CUSTOM\n")
    status = ensure_deployment_assets(root)
    assert custom.read_text() == "CUSTOM\n"
    docker = next(item for item in status if item["asset"] == "dockerignore")
    assert docker["action"] == "preserved"
    assert docker["matches_template"] is False
