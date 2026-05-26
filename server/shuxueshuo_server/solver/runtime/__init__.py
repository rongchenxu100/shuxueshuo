"""Method Solver V1.5 运行时入口。

这个包是现有 V1 solver 之外的一条并行实验链路，用来验证：

1. Method 是否可以做到无状态；
2. 题目上下文是否可以拆成 problem/question/subquestion/step 多层作用域；
3. Planner 是否可以只输出 MethodInvocation，而不直接把答案写进 fixture。

这里统一导出 V1.5 的核心类型和组件，方便测试或后续调用方从一个入口引用。
当前 solver 主链路已经切到本包提供的 V1.5 runtime。
"""

from shuxueshuo_server.solver.runtime.context import ContextBuilder, RuntimeContext
from shuxueshuo_server.solver.runtime.config import (
    SolverRuntimeConfig,
    SolverRuntimeConfigError,
)
from shuxueshuo_server.solver.runtime.context_inventory import (
    ContextInventory,
    ContextInventoryBuilder,
    ConstraintInventoryEntry,
    MethodCandidateEntry,
    PlanningSignalEntry,
    RelationGraphEntry,
    VisibleContextPath,
)
from shuxueshuo_server.solver.runtime.executor import (
    DeclarationValidator,
    InvocationExecutor,
    PlanValidator,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.llm_step_planner import (
    AbstractStepPlan,
    AbstractStepPlanCompiler,
    FakeLLMPlannerClient,
    LLMPlannerError,
    LLMStepDecompositionPlanner,
    PlannerAttempt,
    PlannerMemory,
    hexi25_abstract_steps,
    llm_step_decomposition_planner_provider,
)
from shuxueshuo_server.solver.runtime.llm_clients import (
    DeepSeekPlannerClient,
    DoubaoPlannerClient,
    LLMClientConfigurationError,
    LLMPlannerClient,
    OpenAICompatiblePlannerClient,
)
from shuxueshuo_server.solver.runtime.methods import (
    RightAngleEqualLengthCandidatesMethod,
    SelectPointByQuadrantConstraintMethod,
    StatelessMethodRegistry,
    default_stateless_registry,
)
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
    ContextPath,
    MethodInvocation,
    MethodSpec,
    PlannerOutput,
    PointRef,
    RuntimeScope,
    StepGoal,
    StepPlan,
    TypedValue,
)
from shuxueshuo_server.solver.runtime.planner import (
    GenericPlanner,
    Nankai25DeterministicPlannerAdapter,
    PlannerInputs,
    RuleBasedStepPlannerV15,
)
from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
    QuadraticPathMinimumPlannerV15,
)
from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
    Hexi25WeightedPathPlannerV15,
)
from shuxueshuo_server.solver.runtime.result_builder import (
    ResultBuilder,
    ResultBuilderError,
)
from shuxueshuo_server.solver.runtime.orchestrator import (
    DEFAULT_PLANNER_PROVIDERS,
    RuntimeOrchestrator,
)

__all__ = [
    "ContextBuilder",
    "ContextDeclaration",
    "ContextInventory",
    "ContextInventoryBuilder",
    "ContextPath",
    "ConstraintInventoryEntry",
    "DEFAULT_PLANNER_PROVIDERS",
    "AbstractStepPlan",
    "AbstractStepPlanCompiler",
    "FakeLLMPlannerClient",
    "GenericPlanner",
    "Hexi25WeightedPathPlannerV15",
    "DeepSeekPlannerClient",
    "DeclarationValidator",
    "DoubaoPlannerClient",
    "LLMClientConfigurationError",
    "LLMPlannerClient",
    "LLMPlannerError",
    "LLMStepDecompositionPlanner",
    "OpenAICompatiblePlannerClient",
    "InvocationExecutor",
    "MethodCandidateEntry",
    "MethodInvocation",
    "MethodSpec",
    "MethodSpecRegistry",
    "Nankai25DeterministicPlannerAdapter",
    "PlanValidator",
    "PlannerOutput",
    "PlannerInputs",
    "PlannerAttempt",
    "PlannerMemory",
    "PlanningSignalEntry",
    "PointRef",
    "QuadraticPathMinimumPlannerV15",
    "RelationGraphEntry",
    "ResultBuilder",
    "ResultBuilderError",
    "RuntimeOrchestrator",
    "RuleBasedStepPlannerV15",
    "RuntimeContext",
    "RuntimeScope",
    "RightAngleEqualLengthCandidatesMethod",
    "SelectPointByQuadrantConstraintMethod",
    "StepGoal",
    "StepPlan",
    "StatelessMethodRegistry",
    "SolverRuntimeConfig",
    "SolverRuntimeConfigError",
    "TypedValue",
    "VisibleContextPath",
    "default_stateless_registry",
    "hexi25_abstract_steps",
    "llm_step_decomposition_planner_provider",
]
