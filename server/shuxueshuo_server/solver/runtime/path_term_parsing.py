"""Shared parsing for structured and legacy path-segment expressions.

Structured ``terms`` are authoritative. Legacy strings remain a compatibility
surface for existing ProblemIR, but endpoint names are resolved against the
visible point inventory instead of being assumed to be single characters.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class ParsedPathTerm:
    scale: str
    start: str
    end: str


class PathTermParseError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def parse_path_terms(
    payload: Mapping[str, Any],
    *,
    point_names: Iterable[str],
    resolve_point: Callable[[str], str],
) -> tuple[ParsedPathTerm, ...]:
    """Parse canonical ``terms`` first, then the legacy ``path`` string."""

    structured = payload.get("terms")
    if structured is None and isinstance(payload.get("path"), list):
        structured = payload.get("path")
    if isinstance(structured, list):
        return tuple(
            _structured_path_term(item, index=index)
            for index, item in enumerate(structured)
        )

    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        raise PathTermParseError(
            "path_terms.path_missing",
            "path target must provide structured terms or a legacy path string",
        )
    return parse_legacy_path_expression(
        path,
        point_names=point_names,
        resolve_point=resolve_point,
    )


def parse_legacy_path_expression(
    value: str,
    *,
    point_names: Iterable[str],
    resolve_point: Callable[[str], str],
) -> tuple[ParsedPathTerm, ...]:
    """Parse an additive legacy path expression using known point names.

    Legacy concatenation is accepted only when every term has one unique
    endpoint split. Ambiguous text must migrate to structured ``terms``.
    """

    raw_terms = tuple(item.strip() for item in value.split("+") if item.strip())
    if not raw_terms:
        raise PathTermParseError(
            "path_terms.expression_invalid",
            f"cannot parse path expression: {value}",
        )
    names = unique_ordered(name for name in point_names if name)
    return tuple(
        _legacy_path_term(
            item,
            point_names=names,
            resolve_point=resolve_point,
        )
        for item in raw_terms
    )


def _structured_path_term(value: Any, *, index: int) -> ParsedPathTerm:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
        or not all(_is_point_handle(item) for item in value)
    ):
        raise PathTermParseError(
            "path_terms.structured_term_invalid",
            f"structured path term {index} must contain two point handles",
            details={"index": index},
        )
    return ParsedPathTerm("1", str(value[0]), str(value[1]))


def _legacy_path_term(
    value: str,
    *,
    point_names: tuple[str, ...],
    resolve_point: Callable[[str], str],
) -> ParsedPathTerm:
    compact = "".join(value.split())
    candidates: list[tuple[str, str, str]] = []
    for start in point_names:
        for end in point_names:
            for suffix in (f"{start}{end}", f"{start}-{end}"):
                if not compact.endswith(suffix):
                    continue
                prefix = compact[: -len(suffix)]
                scale = _legacy_scale(prefix)
                if scale is not None:
                    candidates.append((start, end, scale))
    candidates = list(unique_ordered(candidates))
    if len(candidates) != 1:
        raise PathTermParseError(
            (
                "path_terms.legacy_term_unresolved"
                if not candidates
                else "path_terms.legacy_term_ambiguous"
            ),
            "legacy path term must have one unique split against visible point names",
            details={
                "term": value,
                "candidates": [
                    {"start": start, "end": end, "scale": scale}
                    for start, end, scale in candidates
                ],
            },
        )
    start, end, scale = candidates[0]
    return ParsedPathTerm(
        scale=scale,
        start=resolve_point(start),
        end=resolve_point(end),
    )


def _legacy_scale(prefix: str) -> str | None:
    if not prefix:
        return "1"
    if prefix.endswith("*") and prefix[:-1]:
        return prefix[:-1]
    # Keep compatibility with compact numeric coefficients such as ``2DM``.
    if all(character in "0123456789./()" for character in prefix):
        return prefix
    return None


def _is_point_handle(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("point:")


__all__ = [
    "ParsedPathTerm",
    "PathTermParseError",
    "parse_legacy_path_expression",
    "parse_path_terms",
]
