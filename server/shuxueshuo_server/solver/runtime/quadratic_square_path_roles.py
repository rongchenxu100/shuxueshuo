"""Structured roles for quadratic-function square path minima.

The resolver works from canonical geometry relations.  It intentionally knows
nothing about problem ids, display labels, parameter names, or one recorded
formula such as ``HF+FM+MG``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.path_term_parsing import (
    PathTermParseError,
    parse_path_terms,
)


@dataclass(frozen=True)
class QuadraticSquarePathRoles:
    path_minimum_target: str
    square: str
    midpoint_definition: str
    square_center: str
    axis_membership: str
    side_start: str
    axis_point: str
    moving_point: str
    fixed_endpoint: str

    @property
    def candidate_id(self) -> str:
        return stable_hash(self.to_payload())[:20]

    def to_payload(self) -> dict[str, str]:
        return {
            "path_minimum_target": self.path_minimum_target,
            "square": self.square,
            "midpoint_definition": self.midpoint_definition,
            "square_center": self.square_center,
            "axis_membership": self.axis_membership,
            "side_start": self.side_start,
            "axis_point": self.axis_point,
            "moving_point": self.moving_point,
            "fixed_endpoint": self.fixed_endpoint,
        }


class QuadraticSquarePathRoleError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def build_quadratic_square_path_role_candidates(
    *,
    path_minimum_target: str,
    square: str,
    parabola_ref: str,
    scope_id: str,
    registry: CanonicalHandleRegistry,
) -> tuple[QuadraticSquarePathRoles, ...]:
    """Enumerate structurally valid midpoint/center square reductions."""

    square_payload = registry.fact_payloads.get(square, {})
    vertices = tuple(str(item) for item in square_payload.get("vertices", ()))
    if len(vertices) != 4 or len(set(vertices)) != 4:
        raise QuadraticSquarePathRoleError(
            "square_vertices_invalid",
            "the selected square must contain four distinct ordered vertices",
            details={"square": square, "vertices": list(vertices)},
        )

    point_names = _visible_points_by_name(scope_id=scope_id, registry=registry)
    try:
        terms = parse_path_terms(
            registry.fact_payloads.get(path_minimum_target, {}),
            point_names=point_names,
            resolve_point=lambda name: _resolve_unique_point(name, point_names),
        )
    except PathTermParseError as exc:
        raise QuadraticSquarePathRoleError(
            "path_terms_invalid",
            str(exc),
            details=getattr(exc, "details", {}),
        ) from exc
    if len(terms) != 3:
        raise QuadraticSquarePathRoleError(
            "path_shape_invalid",
            "quadratic square path minimum requires a three-segment source path",
            details={"segment_count": len(terms)},
        )

    midpoints = _visible_facts(registry, "midpoint_definition", scope_id)
    centers = _visible_facts(registry, "square_center", scope_id)
    memberships = _visible_facts(registry, "axis_membership", scope_id)
    candidates: list[QuadraticSquarePathRoles] = []
    for midpoint_handle in midpoints:
        midpoint_payload = registry.fact_payloads[midpoint_handle]
        midpoint = str(midpoint_payload.get("point", ""))
        side = tuple(str(item) for item in midpoint_payload.get("of", ()))
        if len(side) != 2 or not _is_square_side(side, vertices):
            continue
        for center_handle in centers:
            center_payload = registry.fact_payloads[center_handle]
            if str(center_payload.get("square", "")) != square:
                continue
            center = str(center_payload.get("point", ""))
            if not _has_segment(terms, center, midpoint):
                continue
            for side_start in side:
                axis_point = next(item for item in side if item != side_start)
                axis_handles = tuple(
                    handle
                    for handle in memberships
                    if registry.fact_payloads[handle].get("point") == axis_point
                    and registry.fact_payloads[handle].get("axis_of")
                    == parabola_ref
                )
                if len(axis_handles) != 1:
                    continue
                moving_point = _external_square_neighbor(
                    side_start,
                    side_other=axis_point,
                    vertices=vertices,
                )
                if moving_point is None:
                    continue
                midpoint_terms = tuple(
                    term
                    for term in terms
                    if midpoint in (term.start, term.end)
                    and center not in (term.start, term.end)
                )
                if len(midpoint_terms) != 1:
                    continue
                midpoint_term = midpoint_terms[0]
                fixed_endpoint = (
                    midpoint_term.end
                    if midpoint_term.start == midpoint
                    else midpoint_term.start
                )
                if not _has_segment(terms, fixed_endpoint, moving_point):
                    continue
                fixed_payload = registry.entity_payloads.get(fixed_endpoint, {})
                if (
                    fixed_payload.get("definition") != "axis_x_intercept"
                    or fixed_payload.get("of") != parabola_ref
                ):
                    continue
                candidates.append(
                    QuadraticSquarePathRoles(
                        path_minimum_target=path_minimum_target,
                        square=square,
                        midpoint_definition=midpoint_handle,
                        square_center=center_handle,
                        axis_membership=axis_handles[0],
                        side_start=side_start,
                        axis_point=axis_point,
                        moving_point=moving_point,
                        fixed_endpoint=fixed_endpoint,
                    )
                )
    return tuple(
        sorted(
            {item.candidate_id: item for item in candidates}.values(),
            key=lambda item: item.candidate_id,
        )
    )


def _visible_facts(
    registry: CanonicalHandleRegistry,
    fact_type: str,
    scope_id: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            handle
            for handle, current_type in registry.fact_types.items()
            if current_type == fact_type
            and visible_from_valid_scope(
                registry.handle_valid_scopes.get(handle, "problem"),
                scope_id=scope_id,
                registry=registry,
            )
        )
    )


def _visible_points_by_name(
    *,
    scope_id: str,
    registry: CanonicalHandleRegistry,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for handle, payload in registry.entity_payloads.items():
        if not handle.startswith("point:") or not visible_from_valid_scope(
            registry.handle_valid_scopes.get(handle, "problem"),
            scope_id=scope_id,
            registry=registry,
        ):
            continue
        name = str(payload.get("name", "")).strip()
        if name:
            result.setdefault(name, []).append(handle)
    return {name: tuple(sorted(handles)) for name, handles in result.items()}


def _resolve_unique_point(
    name: str,
    point_names: Mapping[str, tuple[str, ...]],
) -> str:
    matches = point_names.get(name, ())
    if len(matches) != 1:
        raise QuadraticSquarePathRoleError(
            "point_name_ambiguous" if matches else "point_name_unresolved",
            "a path point label must resolve to one visible object",
            details={"name": name, "candidates": list(matches)},
        )
    return matches[0]


def _is_square_side(side: tuple[str, str], vertices: tuple[str, ...]) -> bool:
    if any(item not in vertices for item in side):
        return False
    first = vertices.index(side[0])
    second = vertices.index(side[1])
    return (first - second) % 4 in {1, 3}


def _external_square_neighbor(
    endpoint: str,
    *,
    side_other: str,
    vertices: tuple[str, ...],
) -> str | None:
    index = vertices.index(endpoint)
    neighbors = (vertices[(index - 1) % 4], vertices[(index + 1) % 4])
    if side_other not in neighbors:
        return None
    return next(item for item in neighbors if item != side_other)


def _has_segment(terms: tuple[object, ...], first: str, second: str) -> bool:
    return any({term.start, term.end} == {first, second} for term in terms)


__all__ = [
    "QuadraticSquarePathRoleError",
    "QuadraticSquarePathRoles",
    "build_quadratic_square_path_role_candidates",
]
