from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


def normalize_name(value: str) -> str:
    """Normalize a label to deterministic lowercase ASCII snake_case.

    The normalization is intentionally lossy. Accents and punctuation are
    removed so configuration can refer to source columns consistently.

    Because it is lossy, two different raw labels may normalize to the same
    value. Callers that need to resolve a normalized name back to a physical
    column must handle that ambiguity explicitly.
    """
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def normalized_groups(columns: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Group physical column names by their normalized representation.

    Example:
        ["Fecha de emision", "Fecha de emisión", "ID"]

    becomes:
        {
            "fecha_de_emision": ("Fecha de emision", "Fecha de emisión"),
            "id": ("ID",),
        }

    This function never drops or arbitrarily chooses colliding columns.
    """
    groups: dict[str, list[str]] = {}

    for original in columns:
        normalized = normalize_name(original)
        groups.setdefault(normalized, []).append(original)

    return {
        normalized: tuple(originals)
        for normalized, originals in groups.items()
    }


def normalization_collisions(
    columns: Iterable[str],
) -> dict[str, tuple[str, ...]]:
    """Return only normalized labels that map to multiple physical columns."""
    return {
        normalized: originals
        for normalized, originals in normalized_groups(columns).items()
        if len(originals) > 1
    }


def normalized_mapping(columns: list[str]) -> dict[str, str]:
    """Map normalized name -> original name, rejecting collisions.

    This strict helper is retained for use cases where the complete source
    schema is required to be one-to-one after normalization.

    Profiling code should generally prefer ``resolve_normalized_names`` so an
    unrelated collision does not prevent analysis of otherwise unambiguous
    candidate keys.
    """
    groups = normalized_groups(columns)
    collisions = {
        normalized: originals
        for normalized, originals in groups.items()
        if len(originals) > 1
    }

    if collisions:
        normalized, originals = next(iter(collisions.items()))
        quoted = ", ".join(repr(value) for value in originals)
        raise ValueError(
            f"Column normalization collision: {quoted} all become "
            f"{normalized!r}."
        )

    return {
        normalized: originals[0]
        for normalized, originals in groups.items()
    }


def resolve_normalized_names(
    columns: Iterable[str],
    requested: Iterable[str],
) -> tuple[dict[str, str], list[str], dict[str, tuple[str, ...]]]:
    """Resolve requested normalized names against a physical schema safely.

    Returns:
        ``(resolved, missing, ambiguous)`` where:

        - ``resolved`` maps requested normalized names to one physical column;
        - ``missing`` contains requested names with no matching column;
        - ``ambiguous`` maps requested names to all matching physical columns.

    A normalization collision that is unrelated to ``requested`` is not an
    error. This is important for heterogeneous SECOP schemas where columns such
    as ``Fecha de emision`` and ``Fecha de emisión`` may coexist.
    """
    groups = normalized_groups(columns)

    resolved: dict[str, str] = {}
    missing: list[str] = []
    ambiguous: dict[str, tuple[str, ...]] = {}

    for name in requested:
        normalized = normalize_name(name)
        matches = groups.get(normalized, ())

        if len(matches) == 0:
            missing.append(normalized)
        elif len(matches) == 1:
            resolved[normalized] = matches[0]
        else:
            ambiguous[normalized] = matches

    return resolved, missing, ambiguous
