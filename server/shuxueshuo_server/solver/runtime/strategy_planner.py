"""Strategy Planner 兼容 facade。

实际实现已按职责拆到 focused modules；本文件只 re-export 旧公开符号，
保证现有 ``shuxueshuo_server.solver.runtime.strategy_planner`` 导入路径不变。
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    HandleCorrection,
    HandleResolutionReport,
    HandleResolver,
)
from shuxueshuo_server.solver.runtime.strategy_compiler import (
    CanonicalRuntimeBindingIndex,
    MethodBindingRuleRegistry,
    RecipeExecutionSpecRegistry,
    RecipeTrialExecutor,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ExecutableCapabilitySpec,
    ExecutablePlanResolutionReport,
    ProducedFact,
    PlannerRetryIssue,
    PlannerRetryState,
    RecipeAlignmentReport,
    STEP_INTENT_JSON_SCHEMA,
    SemanticReadFallback,
    SemanticReadResolution,
    SemanticReadResolutionError,
    SemanticReadResolutionReport,
    SemanticRef,
    StepIntent,
    StepIntentAcceptedStep,
    StepIntentAppliedFill,
    StepIntentDraft,
    StepIntentExecutionBlocker,
    StepIntentExecutionDiagnostic,
    StepIntentNormalizationAction,
    StepIntentNormalizationReport,
    StepIntentPlannerInsight,
    StepIntentPreflightIssue,
    StepIntentRepairAttempt,
    StepIntentResolutionCandidate,
    StepIntentResolutionStepReport,
    StepIntentSkippedStep,
    StepIntentValidationReport,
    StrategyDraftValidationError,
    StrategyPrompt,
)
from shuxueshuo_server.solver.runtime.semantic_reads import (
    ContextSemanticReadResolver,
    SemanticReadResolver,
    build_semantic_read_catalog_payload,
)
from shuxueshuo_server.solver.runtime.strategy_raw_outputs import (
    RawStepOutputNormalizationResult,
    normalize_raw_outputs,
)
from shuxueshuo_server.solver.runtime.strategy_normalizer import (
    StepIntentNormalizer,
)
from shuxueshuo_server.solver.runtime.strategy_preflight import (
    StepIntentPreflightAnalyzer,
)
from shuxueshuo_server.solver.runtime.strategy_repair_feedback import (
    RepairFeedbackBuilder,
    RepairHintRegistry,
    RepairHintSpec,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
    write_strategy_debug_artifacts,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    AliasIndex,
    Condition,
    ContextManifest,
    DraftSnapshots,
    MathObject,
    PlannerState,
    PlannerStateContext,
    PlannerStateContextBuilder,
    RetryMemory,
    ScopeGraph,
    StableStep,
    StateRewriteEvent,
    StateSlot,
    StepState,
)
from shuxueshuo_server.solver.runtime.planner_retry_projection import (
    PlannerRetryStateProjector,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    StepIntentCandidateResolver,
    build_executable_capabilities,
)
from shuxueshuo_server.solver.runtime.strategy_draft_merge import (
    merge_previous_accepted_prefix,
    prepare_step_intent_raw_response,
    sanitize_step_intent_raw_payload,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayResult,
    PlannerRetryReplayService,
    repair_attempt_payload_from_replay,
)
from shuxueshuo_server.solver.runtime.strategy_retry_state import (
    build_planner_retry_state,
    retry_state_from_attempt,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    StrategyPlanner,
    StrategyPlannerArtifacts,
    strategy_planner_provider,
)
from shuxueshuo_server.solver.runtime.strategy_validator import (
    StepIntentValidator,
)

__all__ = [
    "CanonicalHandleRegistry",
    "CanonicalRuntimeBindingIndex",
    "CreatedEntity",
    "ExecutableCapabilitySpec",
    "ExecutablePlanResolutionReport",
    "HandleCorrection",
    "HandleResolutionReport",
    "HandleResolver",
    "ProducedFact",
    "PlannerRetryIssue",
    "PlannerRetryReplayResult",
    "PlannerRetryReplayService",
    "PlannerRetryState",
    "PlannerState",
    "PlannerStateContext",
    "PlannerStateContextBuilder",
    "ContextManifest",
    "DraftSnapshots",
    "ScopeGraph",
    "MathObject",
    "Condition",
    "ContextSemanticReadResolver",
    "PlannerRetryStateProjector",
    "RetryMemory",
    "StateSlot",
    "StepState",
    "StableStep",
    "AliasIndex",
    "StateRewriteEvent",
    "prepare_step_intent_raw_response",
    "RecipeExecutionSpecRegistry",
    "RecipeAlignmentReport",
    "RepairFeedbackBuilder",
    "RepairHintRegistry",
    "RepairHintSpec",
    "RecipeTrialExecutor",
    "STEP_INTENT_JSON_SCHEMA",
    "SemanticReadFallback",
    "SemanticReadResolution",
    "SemanticReadResolutionError",
    "SemanticReadResolutionReport",
    "SemanticReadResolver",
    "SemanticRef",
    "StepIntentCandidateResolver",
    "StepIntent",
    "StepIntentAcceptedStep",
    "StepIntentAppliedFill",
    "StepIntentDraft",
    "StepIntentExecutionBlocker",
    "StepIntentExecutionDiagnostic",
    "StepIntentNormalizationAction",
    "StepIntentNormalizationReport",
    "StepIntentNormalizer",
    "StepIntentPlannerInsight",
    "StepIntentPreflightAnalyzer",
    "StepIntentPreflightIssue",
    "StepIntentRepairAttempt",
    "StepIntentResolutionCandidate",
    "StepIntentResolutionStepReport",
    "StepIntentSkippedStep",
    "StepIntentValidationReport",
    "StepIntentValidator",
    "StrategyDraftValidationError",
    "StrategyPlanner",
    "StrategyPlannerArtifacts",
    "StrategyPayloadBuilder",
    "StrategyPrompt",
    "StrategyPromptRenderer",
    "sanitize_step_intent_raw_payload",
    "RawStepOutputNormalizationResult",
    "MethodBindingRuleRegistry",
    "build_semantic_read_catalog_payload",
    "build_planner_retry_state",
    "build_strategy_probe_inputs",
    "merge_previous_accepted_prefix",
    "repair_attempt_payload_from_replay",
    "retry_state_from_attempt",
    "normalize_raw_outputs",
    "strategy_planner_provider",
    "write_strategy_debug_artifacts",
]
