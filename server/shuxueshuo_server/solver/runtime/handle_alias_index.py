"""Shared deterministic handle alias candidate index.

This module owns pure alias/candidate mechanics used by both semantic reads and
canonical handle resolution. It does not know about StepIntent fields or emit
corrections; callers decide whether a unique candidate should be accepted.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

ENTITY_KIND_ORDER = (
    "point",
    "line",
    "segment",
    "ray",
    "function",
    "symbol",
    "angle",
    "circle",
    "polygon",
)
SEMANTIC_READ_KIND_ORDER = (*ENTITY_KIND_ORDER, "fact", "answer")
ENTITY_KINDS = frozenset(ENTITY_KIND_ORDER)
SEMANTIC_READ_KINDS = frozenset(SEMANTIC_READ_KIND_ORDER)
NON_CANONICAL_PREFIXES = (
    "relation:",
    "condition:",
    "constraint:",
    "value:",
)
COORDINATE_FACT_SUFFIXES = (
    "_coordinate",
    "_coordinate_expr",
    "_coordinate_value",
)


class HandleAliasIndex:
    """Compute exact alias candidates for visible handles/items."""

    def __init__(
        self,
        *,
        registry: Any,
        available: Iterable[str],
        handle_valid_scopes: dict[str, str],
    ) -> None:
        self.registry = registry
        self.available = set(available)
        self.handle_valid_scopes = handle_valid_scopes

    def visible_bare_read_alias_handles(
        self,
        alias: str,
        *,
        scope_id: str,
    ) -> tuple[str, ...]:
        """Return visible handles matching exact ``name`` or ``scope:name``."""
        visible_scopes = self.registry.ancestor_scopes(scope_id)
        return tuple(
            candidate
            for candidate in self.available
            if bare_read_alias_matches(candidate, alias)
            and self.handle_valid_scopes.get(candidate) in visible_scopes
        )

    def visible_ancestor_handles(
        self,
        *,
        kind: str,
        written_scope: str,
        name: str,
        scope_id: str,
        include_written_scope: bool = False,
    ) -> tuple[str, ...]:
        """Return visible ancestor handles for a scoped alias."""
        visible_scopes = self.registry.ancestor_scopes(scope_id)
        if written_scope not in visible_scopes:
            return ()
        written_index = visible_scopes.index(written_scope)
        start = written_index if include_written_scope else written_index + 1
        return tuple(
            handle
            for ancestor_scope in visible_scopes[start:]
            if (handle := f"{kind}:{ancestor_scope}:{name}") in self.available
        )

    def point_entity_handles_for_fact_alias(
        self,
        *,
        written_scope: str,
        name: str,
        scope_id: str,
    ) -> tuple[str, ...]:
        """Return visible point entities for ``fact:<scope>:<PointName>`` aliases."""
        return self.visible_ancestor_handles(
            kind="point",
            written_scope=written_scope,
            name=name,
            scope_id=scope_id,
            include_written_scope=True,
        )

    @staticmethod
    def scoped_ref_handle(
        *,
        kind: str,
        ref: str,
        allowed_kinds: Iterable[str],
    ) -> str | None:
        """Map ``kind + scope:name`` shorthand to a canonical handle."""
        if looks_like_canonical_ref(ref, allowed_kinds=allowed_kinds):
            return None
        parts = ref.split(":")
        if len(parts) != 2 or not all(parts):
            return None
        scope, name = parts
        if kind == "answer":
            return f"answer:{scope}.{name}"
        if kind in set(allowed_kinds):
            return f"{kind}:{scope}:{name}"
        return None

    @staticmethod
    def missing_scope_prefix_items(
        *,
        ref: str,
        kind: str,
        scope_id: str,
        items: Iterable[Any],
        registry: Any,
        source_matches: Callable[[Any], bool],
        value_type_matches: Callable[[Any], bool],
    ) -> list[Any]:
        """Return visible ``scope.ref`` items when LLM omitted the scope prefix."""
        if "." in ref:
            return []
        suffix = f".{ref}"
        return [
            item for item in items
            if getattr(item, "kind", None) == kind
            and str(getattr(item, "ref", "")).endswith(suffix)
            and source_matches(item)
            and value_type_matches(item)
            and visible_from_valid_scope(
                str(getattr(item, "valid_scope", "")),
                scope_id=scope_id,
                registry=registry,
            )
        ]

    @staticmethod
    def point_coordinate_fact_items(
        *,
        kind: str,
        ref: str,
        from_step: str | None,
        scope_id: str,
        items: Iterable[Any],
        registry: Any,
        value_type_matches: Callable[[Any], bool],
    ) -> list[Any]:
        """Return dynamic coordinate facts matching a semantic point ref."""
        if kind != "point" or from_step is None:
            return []
        point_name = semantic_point_ref_name(ref)
        if point_name is None:
            return []
        return [
            item for item in items
            if getattr(item, "kind", None) == "fact"
            and getattr(item, "source_step_id", None) == from_step
            and coordinate_fact_point_name(
                str(getattr(item, "ref", "")),
                str(getattr(item, "handle", "")),
            ) == point_name
            and value_type_matches(item)
            and visible_from_valid_scope(
                str(getattr(item, "valid_scope", "")),
                scope_id=scope_id,
                registry=registry,
            )
        ]


def namespace_alias_handle(handle: str) -> str:
    """Convert common namespace abbreviations into canonical-looking handles."""
    if handle.startswith("facts:"):
        return "fact:" + handle[len("facts:"):]
    if handle.startswith("seg:"):
        return "segment:" + handle[len("seg:"):]
    return handle


def looks_canonical_or_namespaced(handle: str) -> bool:
    """Return whether a read should use stricter canonical/namespace paths."""
    if parse_scoped_non_answer_handle(handle) is not None:
        return True
    if handle.startswith("answer:"):
        return True
    prefix = handle.split(":", 1)[0]
    return (
        prefix in ENTITY_KINDS
        or prefix in {"fact", "facts", "seg", "answer"}
        or any(handle.startswith(item) for item in NON_CANONICAL_PREFIXES)
    )


def bare_read_alias_matches(candidate: str, alias: str) -> bool:
    """Match ``name`` or ``scope:name`` against a canonical non-answer handle."""
    parsed = parse_scoped_non_answer_handle(candidate)
    if parsed is None:
        return False
    _kind, scope_id, name = parsed
    if ":" not in alias:
        return name == alias
    parts = alias.split(":")
    if len(parts) != 2 or not all(parts):
        return False
    written_scope, written_name = parts
    return scope_id == written_scope and name == written_name


def looks_like_canonical_ref(
    ref: str,
    *,
    allowed_kinds: Iterable[str],
) -> bool:
    """Return whether a semantic ref is already a canonical handle."""
    if ref.startswith("answer:"):
        return bool(ref.removeprefix("answer:"))
    parts = ref.split(":")
    return (
        len(parts) == 3
        and parts[0] in set(allowed_kinds)
        and parts[0] != "answer"
        and all(parts)
    )


def parse_scoped_non_answer_handle(handle: str) -> tuple[str, str, str] | None:
    """Parse entity/fact handles as ``(kind, scope, name)``."""
    match = re.fullmatch(
        r"(?P<kind>[A-Za-z]+):(?P<scope>[A-Za-z0-9_]+):(?P<name>[A-Za-z0-9_]+)",
        handle,
    )
    if match is None:
        return None
    kind = match.group("kind")
    if kind == "answer":
        return None
    return kind, match.group("scope"), match.group("name")


def visible_from_valid_scope(
    valid_scope: str,
    *,
    scope_id: str,
    registry: Any,
) -> bool:
    """Return whether ``valid_scope`` is readable from ``scope_id``."""
    if not valid_scope:
        return False
    try:
        return valid_scope in registry.ancestor_scopes(scope_id)
    except Exception:
        return False


def coordinate_fact_point_name(ref: str, handle: str) -> str | None:
    """Read point name from ``*_coordinate`` semantic refs or fact handles."""
    for text in (ref, semantic_name(handle)):
        point_name = strip_coordinate_fact_suffix(text)
        if point_name is not None:
            return point_name
    return None


def strip_coordinate_fact_suffix(text: str) -> str | None:
    """Strip supported coordinate fact suffixes."""
    for suffix in COORDINATE_FACT_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return None


def semantic_point_ref_name(ref: str) -> str | None:
    """Return the point name represented by a semantic point ref."""
    if looks_like_canonical_ref(ref, allowed_kinds=ENTITY_KINDS | {"fact", "answer"}):
        if ref.startswith("point:"):
            parsed = parse_scoped_non_answer_handle(ref)
            return parsed[2] if parsed is not None else None
        return None
    if ":" in ref:
        parts = ref.split(":")
        if len(parts) == 2 and all(parts):
            return parts[1]
        return None
    if "." in ref:
        parts = ref.rsplit(".", 1)
        if all(parts):
            return parts[1]
        return None
    return ref or None


def semantic_name(handle: str) -> str:
    """Return canonical non-answer handle semantic name segment."""
    parsed = parse_scoped_non_answer_handle(handle)
    return parsed[2] if parsed is not None else handle.rsplit(":", 1)[-1]
