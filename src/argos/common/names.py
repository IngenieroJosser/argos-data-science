\
from __future__ import annotations

import re
import unicodedata


def normalize_name(value: str) -> str:
    """Normalize labels/filenames to deterministic snake_case ASCII."""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def normalized_mapping(columns: list[str]) -> dict[str, str]:
    """Map normalized column name -> original name, rejecting collisions."""
    mapping: dict[str, str] = {}
    for original in columns:
        normalized = normalize_name(original)
        if normalized in mapping and mapping[normalized] != original:
            raise ValueError(
                f"Column normalization collision: {mapping[normalized]!r} and "
                f"{original!r} both become {normalized!r}."
            )
        mapping[normalized] = original
    return mapping
