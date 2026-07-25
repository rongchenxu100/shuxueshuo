"""SolverFamily 规格层公开导出。

family 包只承载题型级 spec 和 registry，不执行求解。通用 RuntimeOrchestrator 会以
这里的 FamilySpec 作为 planner 上下文。
"""

from shuxueshuo_server.solver.family.models import (
    CapabilityCardinality,
    CapabilityContractSource,
    CapabilityContractSpec,
    ConditionPattern,
    CapabilityPackRegistry,
    CapabilityPackSpec,
    GoalEvidenceTag,
    CapabilityScopePolicy,
    FamilyMatchRule,
    FamilyRegistry,
    MethodBindingRuleSpec,
    MethodCompanionOutputSpec,
    MethodInputBindingSpec,
    MethodPrepInvocationSpec,
    RecipeExecutionSpec,
    SolverFamilySpec,
    StateIdentityConstraintSpec,
    StateObjectRoleProjectionSpec,
    StateSlotPattern,
    StateWriteMode,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family.capability_packs import (
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
from shuxueshuo_server.solver.family.quadratic_path_minimum import (
    QUADRATIC_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.family.quadratic_equal_length_ray_path_minimum import (
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.family.quadratic_square_reflection_path_minimum import (
    QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.family.quadratic_weighted_path_minimum import (
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
)

DEFAULT_FAMILY_REGISTRY = FamilyRegistry((
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
))

__all__ = [
    "DEFAULT_FAMILY_REGISTRY",
    "DEFAULT_CAPABILITY_PACK_REGISTRY",
    "CapabilityContractSpec",
    "CapabilityContractSource",
    "CapabilityCardinality",
    "CapabilityPackRegistry",
    "CapabilityPackSpec",
    "GoalEvidenceTag",
    "CapabilityScopePolicy",
    "ConditionPattern",
    "FamilyMatchRule",
    "FamilyRegistry",
    "MethodBindingRuleSpec",
    "MethodCompanionOutputSpec",
    "MethodInputBindingSpec",
    "MethodPrepInvocationSpec",
    "QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY",
    "QUADRATIC_PATH_MINIMUM_FAMILY",
    "QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY",
    "QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY",
    "RecipeExecutionSpec",
    "SolverFamilySpec",
    "StateIdentityConstraintSpec",
    "StateObjectRoleProjectionSpec",
    "StateSlotPattern",
    "StateWriteMode",
    "StepRecipeSpec",
    "expand_family_spec",
]
