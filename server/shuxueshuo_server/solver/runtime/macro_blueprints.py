"""Transparent mathematical descriptions for reusable Macro expansions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MacroSemanticBlueprint:
    """Planner-visible mathematical mechanism behind one transparent Macro."""

    macro_id: str
    summary: str
    applicable_structure: tuple[str, ...]
    role_invariants: tuple[str, ...]
    construction_purpose: tuple[str, ...]
    proof_obligations: tuple[str, ...]
    reduction_strategies: tuple[str, ...]
    attainment_checks: tuple[str, ...]
    function_capability_ids: tuple[str, ...]
    blueprint_version: str = "macro-semantic-blueprint/v1"

    def __post_init__(self) -> None:
        for name in ("macro_id", "summary", "blueprint_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in (
            "applicable_structure",
            "role_invariants",
            "construction_purpose",
            "proof_obligations",
            "reduction_strategies",
            "attainment_checks",
            "function_capability_ids",
        ):
            values = tuple(getattr(self, name))
            if not values or any(not item for item in values):
                raise ValueError(f"{name} must contain non-empty values")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must not contain duplicates")
            object.__setattr__(self, name, values)

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "version": self.blueprint_version,
            "summary": self.summary,
            "applicable_structure": list(self.applicable_structure),
            "role_invariants": list(self.role_invariants),
            "construction_purpose": list(self.construction_purpose),
            "proof_obligations": list(self.proof_obligations),
            "reduction_strategies": list(self.reduction_strategies),
            "attainment_checks": list(self.attainment_checks),
            "expandable_functions": list(self.function_capability_ids),
        }

    def authority_payload(self) -> dict[str, Any]:
        return {"macro_id": self.macro_id, **self.to_prompt_payload()}


EQUAL_LENGTH_RAY_PATH_BLUEPRINT = MacroSemanticBlueprint(
    macro_id="equal_length_ray_path_reduction",
    summary=(
        "Use an equal-length construction on a ray to replace one moving "
        "segment, then minimize the resulting two-segment path by direct, "
        "reflection, or endpoint attainment."
    ),
    applicable_structure=(
        "one moving point lies on a closed segment",
        "one moving point lies on a ray",
        "a structured equality links the two moving lengths",
        "the objective is a sum of two Euclidean distances with any fixed endpoint",
    ),
    role_invariants=(
        "the ray anchor is shared by the ray membership and equal-length relation",
        "the fixed endpoint may be any visible fixed Point",
        "all role objects and Conditions must be lexically visible",
    ),
    construction_purpose=(
        "construct a ray point whose distance from the anchor equals the reference segment",
        "replace the linked moving segment only after proving distance equality",
    ),
    proof_obligations=(
        "verify the auxiliary point lies on the positive ray",
        "verify the constructed and reference distances are equal",
        "publish the path rewrite only from a verified Condition",
    ),
    reduction_strategies=(
        "direct intersection of the reduced path with the legal locus",
        "reflection straightening across a supporting line",
        "attainment at either closed-segment endpoint",
    ),
    attainment_checks=(
        "the segment moving point lies on the closed segment",
        "the ray moving point lies in the positive ray direction",
        "the candidate expression equals the original objective under verified Conditions",
    ),
    function_capability_ids=(
        "construct_point_on_ray_at_reference_distance",
        "verify_point_on_ray",
        "verify_distance_equality",
        "prove_distance_equality_from_conditions",
        "rewrite_expression_by_condition",
        "certify_minimum_expression",
        "reflect_point_across_line",
        "line_intersection_point",
        "verify_point_on_closed_segment",
        "distance_between_points",
        "distance_sum_expression",
        "verify_two_segment_path_attainment",
    ),
)


def default_macro_blueprints() -> dict[str, MacroSemanticBlueprint]:
    return {
        EQUAL_LENGTH_RAY_PATH_BLUEPRINT.macro_id: (
            EQUAL_LENGTH_RAY_PATH_BLUEPRINT
        )
    }


__all__ = [
    "EQUAL_LENGTH_RAY_PATH_BLUEPRINT",
    "MacroSemanticBlueprint",
    "default_macro_blueprints",
]
