"""Source-owned family guidance for the ``problem-math-notation/v1`` chain.

This catalog intentionally has no import from ``solver.family``.  Extraction
needs source matching hints, while runtime execution owns a separate registry.
Keeping the two catalogs independent prevents a new extraction family from
silently becoming executable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .candidate_common import strict_json

ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = ROOT / "internal/llm-prompts/problem-math-notation-families.json"

_ENTRY_KEYS = {
    "family_id",
    "title",
    "use_when",
    "required_source_primitives",
    "conditional_source_requirements",
    "do_not_use_when",
}


class NotationFamilyCatalogError(ValueError):
    """The source matching catalog is malformed or ambiguous."""


def _text_list(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _load() -> tuple[dict[str, Any], ...]:
    try:
        document = strict_json(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NotationFamilyCatalogError("notation.invalid_family_catalog") from exc
    if not isinstance(document, dict) or set(document) != {"families"}:
        raise NotationFamilyCatalogError("notation.invalid_family_catalog")
    families = document["families"]
    if not isinstance(families, list) or not families:
        raise NotationFamilyCatalogError("notation.invalid_family_catalog")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for family in families:
        if not isinstance(family, dict) or set(family) != _ENTRY_KEYS:
            raise NotationFamilyCatalogError("notation.invalid_family_catalog")
        if any(
            not isinstance(family[key], str) or not family[key].strip()
            for key in ("family_id", "title", "use_when")
        ):
            raise NotationFamilyCatalogError("notation.invalid_family_catalog")
        if any(
            not _text_list(
                family[key], allow_empty=key == "conditional_source_requirements"
            )
            for key in (
                "required_source_primitives",
                "conditional_source_requirements",
                "do_not_use_when",
            )
        ):
            raise NotationFamilyCatalogError("notation.invalid_family_catalog")
        family_id = family["family_id"]
        if family_id in seen:
            raise NotationFamilyCatalogError("notation.duplicate_family_id")
        seen.add(family_id)
        result.append(family)
    return tuple(result)


def notation_family_catalog() -> tuple[dict[str, Any], ...]:
    """Return the immutable-in-practice source catalog used by notation prompts."""

    return _load()


def notation_family_ids() -> tuple[str, ...]:
    return tuple(item["family_id"] for item in notation_family_catalog())
