from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def serialize_observed(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def add_validation(
    records: list[dict[str, Any]],
    *,
    check_id: str,
    category: str,
    passed: bool,
    observed: Any,
    requirement: str,
    blocking: bool = True,
) -> None:
    records.append(
        {
            "check_id": check_id,
            "category": category,
            "blocking": bool(blocking),
            "passed": bool(passed),
            "observed": serialize_observed(observed),
            "requirement": requirement,
        }
    )


def write_manifest(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    enriched = {
        **payload,
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path
