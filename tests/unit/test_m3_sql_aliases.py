from pathlib import Path
import re


def test_gold_sql_does_not_reintroduce_rows_alias_regression() -> None:
    root = Path(__file__).resolve().parents[2]
    gold = root / "src" / "argos" / "gold"
    pattern = re.compile(r"COUNT\(\*\)\s+(?:AS\s+)?rows\b", re.IGNORECASE)
    offenders: list[str] = []
    for path in gold.glob("*.py"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == []
