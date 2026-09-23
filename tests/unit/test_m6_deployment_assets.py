from pathlib import Path


def test_m6_deployment_assets_are_versioned() -> None:
    root = Path(__file__).resolve().parents[2]
    required = [
        root / "Dockerfile",
        root / ".dockerignore",
        root / ".github" / "workflows" / "ci.yml",
        root / "configs" / "production.toml",
        root / "docs" / "M6_RUNBOOK.md",
    ]
    assert all(path.exists() for path in required)
