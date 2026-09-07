"""Runtime recipe specs.

Recipe specs are the code source for composite capability metadata, including
public TeachingUnitSpec paths and visual templates.
"""

from __future__ import annotations

from ._spec import (
    MacroTeachingSpec,
    RecipeSpec,
    RecipeSpecSource,
    TeachingVariantSpec,
)
from .coupled_segment_path_minimum import (
    SPEC as COUPLED_SEGMENT_PATH_MINIMUM_SPEC,
)
from .curve_candidate_parameter_solve import (
    SPEC as CURVE_CANDIDATE_PARAMETER_SOLVE_SPEC,
)
from .equal_length_ray_path_reduction import SPEC as EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC
from .quadratic_square_path_minimum import SPEC as QUADRATIC_SQUARE_PATH_MINIMUM_SPEC
from .right_angle_equal_length_construct_and_select import (
    SPEC as RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT_SPEC,
)
from .weighted_axis_path_minimum import SPEC as WEIGHTED_AXIS_PATH_MINIMUM_SPEC
from .registry import RecipeSpecRegistry, recipe_spec_payloads


ALL_RECIPE_SPEC_SOURCES = (
    EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC,
    COUPLED_SEGMENT_PATH_MINIMUM_SPEC,
    QUADRATIC_SQUARE_PATH_MINIMUM_SPEC,
    WEIGHTED_AXIS_PATH_MINIMUM_SPEC,
    RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT_SPEC,
    CURVE_CANDIDATE_PARAMETER_SOLVE_SPEC,
)


__all__ = [
    "ALL_RECIPE_SPEC_SOURCES",
    "COUPLED_SEGMENT_PATH_MINIMUM_SPEC",
    "CURVE_CANDIDATE_PARAMETER_SOLVE_SPEC",
    "EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC",
    "QUADRATIC_SQUARE_PATH_MINIMUM_SPEC",
    "RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT_SPEC",
    "WEIGHTED_AXIS_PATH_MINIMUM_SPEC",
    "MacroTeachingSpec",
    "RecipeSpec",
    "RecipeSpecRegistry",
    "RecipeSpecSource",
    "TeachingVariantSpec",
    "recipe_spec_payloads",
]
