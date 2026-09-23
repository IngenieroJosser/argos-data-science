from pathlib import Path
import json


EXPECTED_NOTEBOOKS = [
    "20_target_engineering.ipynb",
    "21_temporal_split_design.ipynb",
    "22_train_eda.ipynb",
    "23_contract_features.ipynb",
    "24_historical_features.ipynb",
    "25_competition_relationship_features.ipynb",
    "26_gold_point_in_time_audit.ipynb",
    "27_m3_gate.ipynb",
]


def test_m3_notebooks_exist_are_clean_and_parseable() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in EXPECTED_NOTEBOOKS:
        path = root / "notebooks" / name
        assert path.exists(), name
        notebook = json.loads(path.read_text(encoding="utf-8"))
        code = "\n\n".join(
            "".join(cell.get("source", []))
            if isinstance(cell.get("source", []), list)
            else str(cell.get("source", ""))
            for cell in notebook.get("cells", [])
            if cell.get("cell_type") == "code"
        )
        compile(code, str(path), "exec")
        for cell in notebook.get("cells", []):
            if cell.get("cell_type") == "code":
                assert cell.get("execution_count") is None
                assert cell.get("outputs", []) == []


def test_m3_operational_docs_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = [
        root / "configs" / "gold.toml",
        root / "docs" / "M3_RUNBOOK.md",
        root / "docs" / "M3_HANDOFF.md",
        root / "docs" / "target-specs" / "y_addition_180d.md",
        root / "docs" / "decisions" / "M3_TEMPORAL_SPLIT_FREEZE.md",
        root / "docs" / "decisions" / "M3_CODE_READINESS_2026-09-23.md",
        root / "pipelines" / "build_gold_m3.py",
        root / "scripts" / "evaluate_m3_gate.py",
    ]
    assert [str(path) for path in expected if not path.exists()] == []
