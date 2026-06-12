"""Runtime recipe specs.

Recipe specs are the code source for composite capability metadata, including
teaching/explanation templates. Execution still uses the existing recipe compiler
during the migration.
"""

from __future__ import annotations

from ._spec import RecipeExplanationSpec, RecipeSpec, RecipeSpecSource, TeachingSubstepSpec
from .broken_path_straightening_minimum_expression import (
    SPEC as BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION_SPEC,
)
from .equal_length_ray_path_reduction import SPEC as EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC
from .registry import RecipeSpecRegistry, recipe_spec_payloads


ALL_RECIPE_SPEC_SOURCES = (
    EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC,
    BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION_SPEC,
)


__all__ = [
    "ALL_RECIPE_SPEC_SOURCES",
    "BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION_SPEC",
    "EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC",
    "RecipeExplanationSpec",
    "RecipeSpec",
    "RecipeSpecRegistry",
    "RecipeSpecSource",
    "TeachingSubstepSpec",
    "recipe_spec_payloads",
]
