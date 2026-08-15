"""Public facade for the strict opt-in FunctionalPlan candidate protocol."""

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
    functional_capability_catalog_payload,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    CanonicalStateHandleFactory,
    FunctionalCall,
    FunctionalCallPlacement,
    FunctionalCallReconciliation,
    FunctionalCapability,
    FunctionalCapabilityArg,
    FunctionalCapabilityReturn,
    FunctionalPlan,
    FunctionalPlanIssue,
    FunctionalPlanReconciliationResult,
    FunctionalPlanValidationReport,
    FunctionalReturnAllocation,
    FunctionalScope,
    PublishedGoalCallResultRef,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    FunctionalPlanReconciler,
)
from shuxueshuo_server.solver.runtime.functional_plan_retry import (
    prepare_functional_plan_raw_response,
)
from shuxueshuo_server.solver.runtime.functional_plan_validation import (
    FUNCTIONAL_PLAN_JSON_SCHEMA,
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    SCOPED_FUNCTIONAL_PLAN_CONTRACT,
    FunctionalStepScopeAuthority,
    ScopedFunctionalAnswerSource,
    ScopedFunctionalGoalPlan,
    ScopedFunctionalPlan,
    ScopedFunctionalPlanAuthority,
    ScopedFunctionalPlanAuthorityAdapter,
    ScopedFunctionalPlanError,
    ScopedFunctionalPlanIssue,
    ScopedFunctionalPlanValidationReport,
    ScopedFunctionalPlanValidator,
    ScopedFunctionalScope,
    ScopedFunctionalStep,
    ScopedPublishedGoalResultRef,
    ScopedStepResultRef,
    scoped_functional_plan_schema,
)


__all__ = [
    "FUNCTIONAL_PLAN_JSON_SCHEMA",
    "SCOPED_FUNCTIONAL_PLAN_CONTRACT",
    "CallResultRef",
    "CanonicalStateHandleFactory",
    "FunctionalCall",
    "FunctionalCallPlacement",
    "FunctionalCallReconciliation",
    "FunctionalCapability",
    "FunctionalCapabilityArg",
    "FunctionalCapabilityCatalog",
    "FunctionalCapabilityReturn",
    "FunctionalPlan",
    "FunctionalPlanIssue",
    "FunctionalPlanReconciler",
    "FunctionalPlanReconciliationResult",
    "FunctionalPlanValidationReport",
    "FunctionalPlanValidator",
    "FunctionalReturnAllocation",
    "FunctionalScope",
    "PublishedGoalCallResultRef",
    "ResolvedFunctionalValue",
    "FunctionalStepScopeAuthority",
    "ScopedFunctionalAnswerSource",
    "ScopedFunctionalGoalPlan",
    "ScopedFunctionalPlan",
    "ScopedFunctionalPlanAuthority",
    "ScopedFunctionalPlanAuthorityAdapter",
    "ScopedFunctionalPlanError",
    "ScopedFunctionalPlanIssue",
    "ScopedFunctionalPlanValidationReport",
    "ScopedFunctionalPlanValidator",
    "ScopedFunctionalScope",
    "ScopedFunctionalStep",
    "ScopedPublishedGoalResultRef",
    "ScopedStepResultRef",
    "functional_capability_catalog_payload",
    "prepare_functional_plan_raw_response",
    "scoped_functional_plan_schema",
]
