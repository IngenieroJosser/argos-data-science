from pathlib import Path
import json


def test_notebooks_30_to_35_do_not_request_test_split() -> None:
    root = Path(__file__).resolve().parents[2]
    for number in range(30, 36):
        notebook = next((root / "notebooks").glob(f"{number}_*.ipynb"))
        payload = json.loads(notebook.read_text(encoding="utf-8"))
        source = "\n".join("".join(c.get("source", [])) for c in payload["cells"])
        assert 'split="test"' not in source
        assert "split='test'" not in source
