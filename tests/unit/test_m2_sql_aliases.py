from pathlib import Path
import re


M2_MODULES = [
    Path("src/argos/silver/suppliers_bidders.py"),
    Path("src/argos/silver/events.py"),
    Path("src/argos/silver/entity_resolution.py"),
    Path("src/argos/silver/validation.py"),
]


def test_m2_aggregate_queries_do_not_use_rows_as_implicit_alias() -> None:
    pattern = re.compile(r"COUNT\(\*\)\s+rows\b", re.IGNORECASE)
    offenders = []
    for path in M2_MODULES:
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(str(path))
    assert not offenders, f"Reserved SQL alias 'rows' remains in: {offenders}"


def test_m2_modules_use_expected_repaired_implementation_versions() -> None:
    expected = {
        "suppliers_bidders.py": "m2-11-suppliers-bidders-v2",
        "events.py": "m2-12-addition-events-out-of-core-v2",
        "entity_resolution.py": "m2-13-deterministic-entity-resolution-v2",
        "validation.py": "m2-14-cross-silver-validation-v2",
    }
    for path in M2_MODULES:
        text = path.read_text(encoding="utf-8")
        assert expected[path.name] in text
