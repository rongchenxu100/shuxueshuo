"""Code-owned atomic Macro boundaries.

The identifiers below are retired Planner-facing path components.  Atomic
path Macros may still reuse their mathematical implementations internally,
but an authored FunctionalPlan must never rebuild those private subgraphs.
Keeping this policy outside the prompt makes Pass 1, Scope Retry, recorded
fixtures and direct compiler callers share the same fail-loud contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Collection


MACRO_INLINE_EXPANSION_FORBIDDEN = (
    "functional.macro_inline_expansion_forbidden"
)

PRIVATE_PATH_RUNTIME_TYPES = frozenset(
    {
        "PathTransformation",
        "PathWitness",
        "StraighteningCandidate",
        "StraighteningCandidateList",
        "StraighteningCandidates",
    }
)

PRIVATE_PATH_PROJECTION_STRING_MARKERS = frozenset(
    {
        *PRIVATE_PATH_RUNTIME_TYPES,
        "#coupled-segment-reflection",
        "#quadratic-square-reflection",
        "#weighted-axis-triangle",
    }
)


RETIRED_PATH_COMPONENT_REPLACEMENTS = MappingProxyType(
    {
        "two_moving_points_path_reduction": (
            "coupled_segment_endpoint_replacement_path_minimum",
        ),
        "coupled_segment_endpoint_replacement_path_minimum_kernel": (
            "coupled_segment_endpoint_replacement_path_minimum",
        ),
        "broken_path_straightening_candidates": (
            "coupled_segment_endpoint_replacement_path_minimum",
            "quadratic_square_path_minimum",
        ),
        "select_straightening_candidate": (
            "coupled_segment_endpoint_replacement_path_minimum",
            "quadratic_square_path_minimum",
        ),
        "broken_path_straightening_and_select": (
            "coupled_segment_endpoint_replacement_path_minimum",
            "quadratic_square_path_minimum",
        ),
        "broken_path_straightening_minimum_expression": (
            "coupled_segment_endpoint_replacement_path_minimum",
            "quadratic_square_path_minimum",
        ),
        "path_minimum_by_straightened_distance": (
            "coupled_segment_endpoint_replacement_path_minimum",
            "quadratic_square_path_minimum",
        ),
        "parameterized_point_locus_line": (
            "quadratic_square_path_minimum",
        ),
        "line_locus_minimum_point": (
            "coupled_segment_endpoint_replacement_path_minimum",
            "quadratic_square_path_minimum",
        ),
        "square_path_dimension_reduction": (
            "quadratic_square_path_minimum",
        ),
        "quadratic_square_path_minimum_kernel": (
            "quadratic_square_path_minimum",
        ),
        "weighted_axis_path_triangle_transform": (
            "weighted_axis_path_minimum",
        ),
        "linked_broken_path_minimum_expression": (
            "weighted_axis_path_minimum",
        ),
        "linked_broken_path_geometric_minimum": (
            "weighted_axis_path_minimum",
        ),
        "weighted_axis_path_minimum_kernel": (
            "weighted_axis_path_minimum",
        ),
    }
)


def atomic_macro_replacements(
    capability_id: str,
    *,
    available_capability_ids: Collection[str] = (),
) -> tuple[str, ...]:
    """Return the family-valid atomic replacement for one retired component."""

    candidates = RETIRED_PATH_COMPONENT_REPLACEMENTS.get(capability_id, ())
    available = frozenset(available_capability_ids)
    visible = tuple(item for item in candidates if item in available)
    return visible or candidates


def contains_private_path_projection_marker(value: Any) -> bool:
    """Detect private path types or synthetic refs in a prompt-bound value."""

    if isinstance(value, Mapping):
        return any(
            contains_private_path_projection_marker(key)
            or contains_private_path_projection_marker(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(contains_private_path_projection_marker(item) for item in value)
    return isinstance(value, str) and any(
        marker in value for marker in PRIVATE_PATH_PROJECTION_STRING_MARKERS
    )


__all__ = [
    "MACRO_INLINE_EXPANSION_FORBIDDEN",
    "PRIVATE_PATH_PROJECTION_STRING_MARKERS",
    "PRIVATE_PATH_RUNTIME_TYPES",
    "RETIRED_PATH_COMPONENT_REPLACEMENTS",
    "atomic_macro_replacements",
    "contains_private_path_projection_marker",
]
