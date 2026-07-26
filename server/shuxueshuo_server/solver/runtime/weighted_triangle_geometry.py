"""Declarative geometry profiles for weighted-axis path transforms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sympy as sp


@dataclass(frozen=True)
class WeightedTriangleGeometryProfile:
    profile_id: str
    weight_expression: str
    construction: str
    geometry: str
    title: str
    angle_label: str
    direction: tuple[str, str]

    @property
    def weight(self) -> sp.Expr:
        return sp.sympify(self.weight_expression)

    @property
    def direction_value(self) -> tuple[sp.Expr, sp.Expr]:
        dx, dy = self.direction
        return (sp.sympify(dx), sp.sympify(dy))

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "weight_expression": self.weight_expression,
            "construction": self.construction,
            "geometry": self.geometry,
            "title": self.title,
            "angle_label": self.angle_label,
            "direction": list(self.direction),
        }


WEIGHTED_TRIANGLE_GEOMETRY_PROFILES = (
    WeightedTriangleGeometryProfile(
        profile_id="sqrt2_right_isosceles",
        weight_expression="sqrt(2)",
        construction="right_isosceles_triangle",
        geometry="45_45_90",
        title="等腰直角三角形",
        angle_label="45 度",
        direction=("1", "1"),
    ),
    WeightedTriangleGeometryProfile(
        profile_id="weight2_30_60",
        weight_expression="2",
        construction="right_triangle_30_60",
        geometry="30_60_90",
        title="30°/60° 直角三角形",
        angle_label="30 度",
        direction=("3", "sqrt(3)"),
    ),
)


def weighted_triangle_geometry_for_weight(
    weight: sp.Expr,
) -> WeightedTriangleGeometryProfile:
    simplified = sp.simplify(weight)
    matches = tuple(
        profile
        for profile in WEIGHTED_TRIANGLE_GEOMETRY_PROFILES
        if sp.simplify(simplified - profile.weight) == 0
    )
    if len(matches) != 1:
        supported = ", ".join(
            profile.weight_expression
            for profile in WEIGHTED_TRIANGLE_GEOMETRY_PROFILES
        )
        raise ValueError(
            "weighted triangle geometry is not registered: "
            f"weight={simplified}; supported={supported}"
        )
    return matches[0]


def weighted_triangle_geometry_for_transformation(
    transformation: dict[str, Any],
) -> WeightedTriangleGeometryProfile:
    if "scale" not in transformation or "geometry" not in transformation:
        raise ValueError(
            "weighted transformation requires scale and geometry profile"
        )
    profile = weighted_triangle_geometry_for_weight(
        sp.sympify(transformation["scale"])
    )
    if str(transformation["geometry"]) != profile.geometry:
        raise ValueError(
            "weighted transformation geometry does not match registered "
            f"profile: expected={profile.geometry}, "
            f"actual={transformation['geometry']}"
        )
    profile_id = transformation.get("geometry_profile_id")
    if profile_id is not None and str(profile_id) != profile.profile_id:
        raise ValueError(
            "weighted transformation profile id does not match registered "
            f"profile: expected={profile.profile_id}, actual={profile_id}"
        )
    construction = transformation.get("construction")
    if construction is not None and str(construction) != profile.construction:
        raise ValueError(
            "weighted transformation construction does not match registered "
            f"profile: expected={profile.construction}, actual={construction}"
        )
    return profile


def weighted_triangle_geometry_payloads() -> tuple[dict[str, Any], ...]:
    return tuple(
        profile.to_payload()
        for profile in WEIGHTED_TRIANGLE_GEOMETRY_PROFILES
    )


__all__ = [
    "WEIGHTED_TRIANGLE_GEOMETRY_PROFILES",
    "WeightedTriangleGeometryProfile",
    "weighted_triangle_geometry_for_transformation",
    "weighted_triangle_geometry_for_weight",
    "weighted_triangle_geometry_payloads",
]
