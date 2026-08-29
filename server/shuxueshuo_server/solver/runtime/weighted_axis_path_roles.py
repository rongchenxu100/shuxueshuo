"""Structured roles for the atomic weighted-axis path minimum Macro.

The selected path target is the only public authority.  Its typed terms own
the endpoint identities and weights; related point/symbol constraints are
resolved mechanically inside the same visible scope chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import sympy as sp

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.path_term_parsing import (
    PathTermParseError,
    parse_path_terms,
)
from shuxueshuo_server.solver.runtime.weighted_triangle_geometry import (
    WeightedTriangleGeometryUnsupportedError,
    weighted_triangle_geometry_for_weight,
)


@dataclass(frozen=True)
class WeightedAxisPathRoles:
    path_minimum_target: str
    curve_point: str
    moving_point: str
    fixed_point: str
    parameter: str
    dynamic_parameter: str
    parameter_constraint: str
    dynamic_constraint: str
    weight_expression: str
    geometry_profile_id: str

    @property
    def candidate_id(self) -> str:
        return stable_hash(self.to_payload())[:20]

    def role_payload(self) -> dict[str, str]:
        return {
            "curve_point": self.curve_point,
            "moving_point": self.moving_point,
            "fixed_point": self.fixed_point,
            "parameter": self.parameter,
            "dynamic_parameter": self.dynamic_parameter,
            "parameter_constraint": self.parameter_constraint,
            "dynamic_constraint": self.dynamic_constraint,
        }

    def to_payload(self) -> dict[str, str]:
        return {
            "path_minimum_target": self.path_minimum_target,
            **self.role_payload(),
            "weight_expression": self.weight_expression,
            "geometry_profile_id": self.geometry_profile_id,
        }


class WeightedAxisPathRoleError(ValueError):
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


def build_weighted_axis_path_role_candidates(
    *,
    path_minimum_target: str,
    scope_id: str,
    registry: CanonicalHandleRegistry,
) -> tuple[WeightedAxisPathRoles, ...]:
    """Resolve one weighted two-term path graph from typed source authority."""

    if registry.fact_types.get(path_minimum_target) != "path_minimum_target":
        raise WeightedAxisPathRoleError(
            "public_input_invalid",
            "weighted path Macro requires one path_minimum_target Fact",
            details={"path_minimum_target": path_minimum_target},
        )
    if not visible_from_valid_scope(
        registry.handle_valid_scopes.get(path_minimum_target, "problem"),
        scope_id=scope_id,
        registry=registry,
    ):
        raise WeightedAxisPathRoleError(
            "public_input_not_visible",
            "the selected path target is not visible from the Macro scope",
            details={
                "path_minimum_target": path_minimum_target,
                "scope_id": scope_id,
            },
        )

    points_by_name = _visible_objects_by_name(
        prefix="point:",
        scope_id=scope_id,
        registry=registry,
    )

    def resolve_point(name: str) -> str:
        candidates = points_by_name.get(name, ())
        if len(candidates) != 1:
            raise PathTermParseError(
                (
                    "path_terms.point_unresolved"
                    if not candidates
                    else "path_terms.point_ambiguous"
                ),
                "legacy weighted path point name has no unique visible identity",
                details={
                    "name": name,
                    "candidate_count": len(candidates),
                    "candidates": list(candidates),
                },
            )
        return candidates[0]

    try:
        terms = parse_path_terms(
            registry.fact_payloads.get(path_minimum_target, {}),
            point_names=tuple(points_by_name),
            resolve_point=resolve_point,
        )
    except PathTermParseError as exc:
        raise WeightedAxisPathRoleError(
            exc.code,
            str(exc),
            details=exc.details,
        ) from exc
    if len(terms) != 2:
        raise WeightedAxisPathRoleError(
            "term_count_invalid",
            "weighted axis path must contain exactly two distance terms",
            details={"term_count": len(terms)},
        )

    parsed_scales: list[sp.Expr] = []
    for index, term in enumerate(terms):
        try:
            parsed_scales.append(sp.simplify(sp.sympify(term.scale)))
        except (TypeError, ValueError, sp.SympifyError) as exc:
            raise WeightedAxisPathRoleError(
                "weight_invalid",
                "weighted path scale is not a canonical expression",
                details={"term_index": index, "scale": term.scale},
            ) from exc
    weighted_indexes = tuple(
        index
        for index, scale in enumerate(parsed_scales)
        if sp.simplify(scale - 1) != 0
    )
    if len(weighted_indexes) != 1:
        raise WeightedAxisPathRoleError(
            "weighted_term_not_unique",
            "weighted axis path must contain exactly one non-unit term",
            details={"scales": [str(item) for item in parsed_scales]},
        )
    weighted_index = weighted_indexes[0]
    unit_index = 1 - weighted_index
    if sp.simplify(parsed_scales[unit_index] - 1) != 0:
        raise WeightedAxisPathRoleError(
            "unit_term_missing",
            "the second weighted path term must have unit scale",
        )
    try:
        geometry = weighted_triangle_geometry_for_weight(
            parsed_scales[weighted_index]
        )
    except WeightedTriangleGeometryUnsupportedError as exc:
        raise WeightedAxisPathRoleError(
            "weight_unsupported",
            str(exc),
            details={
                "weight": str(exc.weight),
                "supported_weights": list(exc.supported),
            },
        ) from exc

    weighted_pair = (terms[weighted_index].start, terms[weighted_index].end)
    unit_pair = (terms[unit_index].start, terms[unit_index].end)
    shared = tuple(item for item in weighted_pair if item in unit_pair)
    if len(shared) != 1:
        raise WeightedAxisPathRoleError(
            "moving_point_not_unique",
            "weighted and unit path terms must share exactly one moving point",
            details={
                "weighted_term": list(weighted_pair),
                "unit_term": list(unit_pair),
            },
        )
    moving_point = shared[0]
    curve_point = _other_endpoint(weighted_pair, moving_point)
    fixed_point = _other_endpoint(unit_pair, moving_point)

    moving_payload = registry.entity_payloads.get(moving_point, {})
    dynamic_names = _free_symbol_names(moving_payload.get("coordinate", ()))
    if len(dynamic_names) != 1:
        raise WeightedAxisPathRoleError(
            "dynamic_parameter_not_unique",
            "the shared moving point must expose exactly one coordinate parameter",
            details={
                "moving_point": moving_point,
                "free_symbols": sorted(dynamic_names),
            },
        )
    dynamic_parameter = _unique_visible_symbol(
        next(iter(dynamic_names)),
        scope_id=scope_id,
        registry=registry,
        role="dynamic_parameter",
    )

    curve_payload = registry.entity_payloads.get(curve_point, {})
    parameter_names = _free_symbol_names(
        (
            curve_payload.get("x"),
            curve_payload.get("coordinate"),
        )
    ) - dynamic_names
    if len(parameter_names) != 1:
        raise WeightedAxisPathRoleError(
            "parameter_not_unique",
            (
                "the weighted curve endpoint must identify exactly one primary "
                "parameter before the path Macro runs"
            ),
            details={
                "curve_point": curve_point,
                "free_symbols": sorted(parameter_names),
                "repair_action": "materialize_single_parameter_curve_endpoint",
            },
        )
    parameter = _unique_visible_symbol(
        next(iter(parameter_names)),
        scope_id=scope_id,
        registry=registry,
        role="parameter",
    )

    parameter_constraint = _unique_symbol_constraint(
        parameter,
        scope_id=scope_id,
        registry=registry,
        role="parameter_constraint",
    )
    dynamic_constraint = _unique_symbol_constraint(
        dynamic_parameter,
        scope_id=scope_id,
        registry=registry,
        role="dynamic_constraint",
    )

    return (
        WeightedAxisPathRoles(
            path_minimum_target=path_minimum_target,
            curve_point=curve_point,
            moving_point=moving_point,
            fixed_point=fixed_point,
            parameter=parameter,
            dynamic_parameter=dynamic_parameter,
            parameter_constraint=parameter_constraint,
            dynamic_constraint=dynamic_constraint,
            weight_expression=sp.sstr(parsed_scales[weighted_index]),
            geometry_profile_id=geometry.profile_id,
        ),
    )


def _visible_objects_by_name(
    *,
    prefix: str,
    scope_id: str,
    registry: CanonicalHandleRegistry,
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for handle, payload in registry.entity_payloads.items():
        if not handle.startswith(prefix) or not visible_from_valid_scope(
            registry.handle_valid_scopes.get(handle, "problem"),
            scope_id=scope_id,
            registry=registry,
        ):
            continue
        name = str(payload.get("name", "")).strip()
        if name:
            grouped.setdefault(name, []).append(handle)
    return {
        name: tuple(sorted(handles))
        for name, handles in sorted(grouped.items())
    }


def _other_endpoint(pair: tuple[str, str], shared: str) -> str:
    remaining = tuple(item for item in pair if item != shared)
    if len(remaining) != 1:
        raise WeightedAxisPathRoleError(
            "endpoint_not_unique",
            "path term does not contain one endpoint other than the moving point",
            details={"term": list(pair), "moving_point": shared},
        )
    return remaining[0]


def _free_symbol_names(values: Any) -> set[str]:
    result: set[str] = set()
    for value in _flatten(values):
        if value is None or isinstance(value, Mapping):
            continue
        try:
            result.update(
                symbol.name for symbol in sp.sympify(value).free_symbols
            )
        except (TypeError, ValueError, sp.SympifyError):
            continue
    return result


def _flatten(value: Any) -> Iterable[Any]:
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten(item)
        return
    yield value


def _unique_visible_symbol(
    name: str,
    *,
    scope_id: str,
    registry: CanonicalHandleRegistry,
    role: str,
) -> str:
    candidates = tuple(
        sorted(
            handle
            for handle, payload in registry.entity_payloads.items()
            if handle.startswith("symbol:")
            and str(payload.get("name", "")) == name
            and visible_from_valid_scope(
                registry.handle_valid_scopes.get(handle, "problem"),
                scope_id=scope_id,
                registry=registry,
            )
        )
    )
    if len(candidates) != 1:
        raise WeightedAxisPathRoleError(
            f"{role}_identity_invalid",
            f"{role} has no unique visible Symbol identity",
            details={
                "symbol_name": name,
                "candidate_count": len(candidates),
                "candidates": list(candidates),
            },
        )
    return candidates[0]


def _unique_symbol_constraint(
    symbol_handle: str,
    *,
    scope_id: str,
    registry: CanonicalHandleRegistry,
    role: str,
) -> str:
    candidates = tuple(
        sorted(
            handle
            for handle, payload in registry.fact_payloads.items()
            if registry.fact_types.get(handle) == "symbol_constraint"
            and str(payload.get("subject", "")) == symbol_handle
            and visible_from_valid_scope(
                registry.handle_valid_scopes.get(handle, "problem"),
                scope_id=scope_id,
                registry=registry,
            )
        )
    )
    if len(candidates) != 1:
        raise WeightedAxisPathRoleError(
            f"{role}_invalid",
            f"{role} must resolve to exactly one visible symbolic domain",
            details={
                "symbol": symbol_handle,
                "candidate_count": len(candidates),
                "candidates": list(candidates),
            },
        )
    return candidates[0]


__all__ = [
    "WeightedAxisPathRoleError",
    "WeightedAxisPathRoles",
    "build_weighted_axis_path_role_candidates",
]
