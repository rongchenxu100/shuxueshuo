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
    FunctionalProjectionEntry,
    FunctionalReturnAllocation,
    FunctionalScope,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    FunctionalPlanProjector,
    FunctionalPlanReconciler,
)
from shuxueshuo_server.solver.runtime.functional_plan_retry import (
    prepare_functional_plan_raw_response,
)
from shuxueshuo_server.solver.runtime.functional_plan_validation import (
    FUNCTIONAL_PLAN_JSON_SCHEMA,
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.strategy_models import PlannerOutputFormat


__all__ = [
    "FUNCTIONAL_PLAN_JSON_SCHEMA",
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
    "FunctionalPlanProjector",
    "FunctionalPlanReconciler",
    "FunctionalPlanReconciliationResult",
    "FunctionalPlanValidationReport",
    "FunctionalPlanValidator",
    "FunctionalProjectionEntry",
    "FunctionalReturnAllocation",
    "FunctionalScope",
    "PlannerOutputFormat",
    "ResolvedFunctionalValue",
    "functional_capability_catalog_payload",
    "prepare_functional_plan_raw_response",
]
