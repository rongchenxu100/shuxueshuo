"""Weight-generic structural facts for weighted-axis triangle transforms.

This runtime module deliberately knows nothing about student teaching profiles.
For every constant real weight ``w > 1`` it derives the same right-triangle
construction coefficients. Familiar 45° and 30°/60° narratives are selected
later by the explanation layer from these verified facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import sympy as sp


class WeightedTriangleGeometryDomainError(ValueError):
    """The weight cannot define the required real right triangle."""

    def __init__(self, weight: sp.Expr) -> None:
        self.weight = sp.simplify(weight)
        super().__init__(
            "weighted triangle geometry requires a constant real weight > 1: "
            f"weight={self.weight}"
        )


class WeightedTriangleGeometryContractError(ValueError):
    """A materialized transformation drifts from its structural facts."""

    def __init__(self, field: str, expected: Any, observed: Any) -> None:
        self.field = field
        self.expected = expected
        self.observed = observed
        super().__init__(
            "weighted transformation geometry drift: "
            f"field={field}; expected={expected}; observed={observed}"
        )


@dataclass(frozen=True)
class WeightedTriangleGeometryFacts:
    """Algebraic coefficients shared by every legal weighted construction."""

    weight: sp.Expr
    radicand: sp.Expr
    leg_factor: sp.Expr
    height_factor: sp.Expr

    @property
    def direction_value(self) -> tuple[sp.Expr, sp.Expr]:
        return (sp.sqrt(self.radicand), sp.Integer(1))

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": "weighted_right_triangle",
            "right_angle_vertex_role": "auxiliary_point",
            "hypotenuse_role": "fixed_to_moving",
            "scaled_leg_role": "auxiliary_to_moving",
            "hypotenuse_to_leg_scale": sp.sstr(self.weight),
            "leg_factor": sp.sstr(self.leg_factor),
            "height_factor": sp.sstr(self.height_factor),
            "locus_direction": [
                sp.sstr(item) for item in self.direction_value
            ],
        }


def weighted_triangle_geometry_for_weight(
    weight: sp.Expr,
) -> WeightedTriangleGeometryFacts:
    """Derive the structural construction for any constant real ``w > 1``."""

    simplified = sp.simplify(weight)
    if (
        simplified.free_symbols
        or simplified.is_real is False
        or sp.simplify(simplified - 1).is_positive is not True
    ):
        raise WeightedTriangleGeometryDomainError(simplified)
    weight_squared = sp.simplify(simplified**2)
    radicand = sp.simplify(weight_squared - 1)
    return WeightedTriangleGeometryFacts(
        weight=simplified,
        radicand=radicand,
        leg_factor=sp.simplify(radicand / weight_squared),
        height_factor=sp.simplify(sp.sqrt(radicand) / weight_squared),
    )


def weighted_triangle_geometry_for_transformation(
    transformation: Mapping[str, Any],
) -> WeightedTriangleGeometryFacts:
    """Validate only the structural fields consumed by the minimum kernel."""

    if transformation.get("type") != "weighted_axis_triangle_transform":
        raise WeightedTriangleGeometryContractError(
            "type",
            "weighted_axis_triangle_transform",
            transformation.get("type"),
        )
    if "scale" not in transformation:
        raise WeightedTriangleGeometryContractError(
            "scale",
            "constant real weight > 1",
            None,
        )
    facts = weighted_triangle_geometry_for_weight(
        sp.sympify(transformation["scale"])
    )
    geometry = transformation.get("geometry")
    if not isinstance(geometry, Mapping):
        raise WeightedTriangleGeometryContractError(
            "geometry",
            "structured weighted-right-triangle facts",
            geometry,
        )
    expected = facts.to_payload()
    for field in (
        "kind",
        "right_angle_vertex_role",
        "hypotenuse_role",
        "scaled_leg_role",
    ):
        if geometry.get(field) != expected[field]:
            raise WeightedTriangleGeometryContractError(
                field,
                expected[field],
                geometry.get(field),
            )
    for field in (
        "hypotenuse_to_leg_scale",
        "leg_factor",
        "height_factor",
    ):
        try:
            matches = sp.simplify(
                sp.sympify(geometry.get(field))
                - sp.sympify(expected[field])
            ) == 0
        except (TypeError, ValueError, sp.SympifyError):
            matches = False
        if not matches:
            raise WeightedTriangleGeometryContractError(
                field,
                expected[field],
                geometry.get(field),
            )
    return facts


__all__ = [
    "WeightedTriangleGeometryContractError",
    "WeightedTriangleGeometryDomainError",
    "WeightedTriangleGeometryFacts",
    "weighted_triangle_geometry_for_transformation",
    "weighted_triangle_geometry_for_weight",
]
