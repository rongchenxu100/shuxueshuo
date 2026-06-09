"""SolverFamily 规格层公开导出。

family 包只承载题型级 spec 和 registry，不执行求解。通用 RuntimeOrchestrator 会以
这里的 FamilySpec 作为 planner 上下文。
"""

from shuxueshuo_server.solver.family.models import (
    FamilyMatchRule,
    FamilyRegistry,
    MethodBindingRuleSpec,
    MethodCompanionOutputSpec,
    MethodInputBindingSpec,
    MethodPrepInvocationSpec,
    RecipeExecutionSpec,
    SolverFamilySpec,
    StepRecipeSpec,
)
from shuxueshuo_server.solver.family.quadratic_path_minimum import (
    QUADRATIC_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.family.quadratic_equal_length_ray_path_minimum import (
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.family.quadratic_weighted_path_minimum import (
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
)

DEFAULT_FAMILY_REGISTRY = FamilyRegistry((
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
))

__all__ = [
    "DEFAULT_FAMILY_REGISTRY",
    "FamilyMatchRule",
    "FamilyRegistry",
    "MethodBindingRuleSpec",
    "MethodCompanionOutputSpec",
    "MethodInputBindingSpec",
    "MethodPrepInvocationSpec",
    "QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY",
    "QUADRATIC_PATH_MINIMUM_FAMILY",
    "QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY",
    "RecipeExecutionSpec",
    "SolverFamilySpec",
    "StepRecipeSpec",
]
