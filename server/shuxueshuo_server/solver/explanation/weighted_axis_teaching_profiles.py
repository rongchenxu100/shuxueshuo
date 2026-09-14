"""Optional student narratives for familiar weighted-axis triangles.

Runtime accepts every mathematically legal constant weight greater than one
and publishes structural side/angle facts.  This module is the only registry
of special classroom narratives.  If no profile matches, callers retain the
verified computation and use a generic Pythagorean explanation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import sympy as sp


@dataclass(frozen=True)
class WeightedAxisReductionNarrative:
    construction: str
    equivalence_reason: str
    locus_angle: str


@dataclass(frozen=True)
class WeightedAxisTeachingProfile:
    profile_id: str
    weight_expression: str
    projection_relation_kind: str
    locus_angle: str

    @property
    def weight(self) -> sp.Expr:
        return sp.sympify(self.weight_expression)

    def matches(
        self,
        *,
        weight: sp.Expr,
        geometry: Mapping[str, Any],
    ) -> bool:
        relation = geometry.get("projection_triangle_relation")
        return (
            sp.simplify(weight - self.weight) == 0
            and isinstance(relation, Mapping)
            and relation.get("kind") == self.projection_relation_kind
        )

    def reduction_narrative(
        self,
        *,
        fixed: str,
        auxiliary: str,
        moving: str,
        axis_side: str,
    ) -> WeightedAxisReductionNarrative:
        fixed_moving = f"{fixed}{moving}"
        auxiliary_moving = f"{auxiliary}{moving}"
        if self.profile_id == "right_isosceles_45":
            return WeightedAxisReductionNarrative(
                construction=(
                    f"在 x 轴{axis_side}作等腰直角三角形 "
                    f"{fixed}{auxiliary}{moving}，使 "
                    f"{fixed}{auxiliary}＝{auxiliary_moving}，"
                    f"∠{fixed}{auxiliary}{moving}＝90°"
                ),
                equivalence_reason=(
                    f"{fixed_moving} 是 Rt△{fixed}{auxiliary}{moving} 的斜边"
                ),
                locus_angle=self.locus_angle,
            )
        if self.profile_id == "right_triangle_30_60":
            return WeightedAxisReductionNarrative(
                construction=(
                    f"在 x 轴{axis_side}作 Rt△{fixed}{auxiliary}{moving}，"
                    f"使 ∠{fixed}{auxiliary}{moving}＝90°，"
                    f"∠{auxiliary}{fixed}{moving}＝30°"
                ),
                equivalence_reason=(
                    f"在 Rt△{fixed}{auxiliary}{moving} 中，"
                    f"30° 角所对的边为 {auxiliary_moving}"
                ),
                locus_angle=self.locus_angle,
            )
        raise ValueError(f"weighted teaching renderer missing: {self.profile_id}")

    def projection_lines(
        self,
        *,
        fixed_auxiliary: str,
        curve: str,
        projection: str,
        moving: str,
        curve_point: str,
        curve_projection: str,
        projection_moving: str,
        curve_moving: str,
        vertical: str,
        horizontal: str,
        curve_to_moving: str,
    ) -> tuple[str, ...]:
        if self.profile_id == "right_isosceles_45":
            return (
                f"∵{fixed_auxiliary} 与 x 轴成 45°",
                f"∴△{curve}{projection}{moving} 是等腰直角三角形",
                f"∵{curve_point}",
                f"∴{curve_projection}＝{projection_moving}＝{vertical}",
                f"∴{curve_moving}＝√2·{vertical}",
            )
        if self.profile_id == "right_triangle_30_60":
            return (
                f"∵{fixed_auxiliary} 与 x 轴成 30°",
                f"∴在 Rt△{curve}{projection}{moving} 中，"
                f"∠{curve}{moving}{projection}＝60°",
                f"∵{curve_point}",
                f"∴{curve_projection}＝{vertical}，"
                f"{projection_moving}＝{horizontal}",
                f"∴{curve_moving}＝{curve_to_moving}",
            )
        raise ValueError(f"weighted teaching renderer missing: {self.profile_id}")


WEIGHTED_AXIS_TEACHING_PROFILES = (
    WeightedAxisTeachingProfile(
        profile_id="right_isosceles_45",
        weight_expression="sqrt(2)",
        projection_relation_kind="equal_legs",
        locus_angle="45°",
    ),
    WeightedAxisTeachingProfile(
        profile_id="right_triangle_30_60",
        weight_expression="2",
        projection_relation_kind="vertical_squared_multiple_of_horizontal",
        locus_angle="30°",
    ),
)


def select_weighted_axis_teaching_profile(
    *,
    weight: sp.Expr,
    geometry: Mapping[str, Any],
) -> WeightedAxisTeachingProfile | None:
    matches = tuple(
        profile
        for profile in WEIGHTED_AXIS_TEACHING_PROFILES
        if profile.matches(weight=weight, geometry=geometry)
    )
    return matches[0] if len(matches) == 1 else None


__all__ = [
    "WEIGHTED_AXIS_TEACHING_PROFILES",
    "WeightedAxisReductionNarrative",
    "WeightedAxisTeachingProfile",
    "select_weighted_axis_teaching_profile",
]
