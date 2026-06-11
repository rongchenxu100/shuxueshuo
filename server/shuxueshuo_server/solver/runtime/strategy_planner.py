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
    RecipeAlignmentReport,
    STEP_INTENT_JSON_SCHEMA,
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
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    StepIntentCandidateResolver,
    build_executable_capabilities,
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
    "RecipeExecutionSpecRegistry",
    "RecipeAlignmentReport",
    "RepairFeedbackBuilder",
    "RepairHintRegistry",
    "RepairHintSpec",
    "RecipeTrialExecutor",
    "STEP_INTENT_JSON_SCHEMA",
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
    "MethodBindingRuleRegistry",
    "build_strategy_probe_inputs",
    "strategy_planner_provider",
    "write_strategy_debug_artifacts",
]
