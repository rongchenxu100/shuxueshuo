"""通用 Runtime Orchestrator。

Phase 4 开始，solver 主入口不再直接实例化某个 concrete SolverFamily 执行类。
Orchestrator 负责把通用运行时组件串起来：

``FamilyRegistry -> RuntimeContext -> ContextInventory -> GenericPlanner
-> InvocationExecutor -> ResultBuilder``。

这里仍然保留一个临时的静态 planner provider 映射，用 canonical 南开 25 的
deterministic planner 跑通现有黄金用例。这个映射属于运行器配置，不属于
``SolverFamilySpec``，避免 FamilySpec 退回“指定 planner”的设计。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from shuxueshuo_server.solver.family import (
    DEFAULT_FAMILY_REGISTRY,
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
    FamilyRegistry,
)
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.result_models import DerivationTrace, SolverResult
from shuxueshuo_server.solver.runtime.context import RuntimeContext, ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventoryBuilder
from shuxueshuo_server.solver.runtime.executor import (
    DeclarationValidator,
    InvocationExecutor,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
from shuxueshuo_server.solver.runtime.models import PlannerOutput
from shuxueshuo_server.solver.runtime.planner import (
    GenericPlanner,
    Nankai25DeterministicPlannerAdapter,
    PlannerInputs,
)
from shuxueshuo_server.solver.runtime.result_builder import ResultBuilder


PlannerProvider = Callable[[RuntimeContext], GenericPlanner]


def _nankai25_planner_provider(context: RuntimeContext) -> GenericPlanner:
    """Phase 4 临时 provider：把南开 deterministic planner 包装成通用接口。"""
    return Nankai25DeterministicPlannerAdapter(context)


def _hexi25_planner_provider(context: RuntimeContext) -> GenericPlanner:
    """河西 25 provider：第二道 E2E 的 weighted deterministic planner。"""
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    return Hexi25WeightedPathPlannerV15(context)


DEFAULT_PLANNER_PROVIDERS: dict[str, PlannerProvider] = {
    QUADRATIC_PATH_MINIMUM_FAMILY.family_id: _nankai25_planner_provider,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id: _hexi25_planner_provider,
}


class RuntimeOrchestrator:
    """通用 solver 编排器。

    Orchestrator 不保存题型步骤，也不理解具体 method 数学含义。它只负责：

    - 通过 FamilyRegistry 匹配题型；
    - 构建 planner 输入；
    - 调用 GenericPlanner 生成 StepPlan；
    - 执行计划并按 QuestionGoal 收集答案。
    """

    def __init__(
        self,
        *,
        family_registry: FamilyRegistry = DEFAULT_FAMILY_REGISTRY,
        planner_providers: Mapping[str, PlannerProvider] | None = None,
        kernel: SympyKernel | None = None,
    ) -> None:
        self.family_registry = family_registry
        # ``None`` 表示使用默认 provider；显式传入空 dict 表示测试“provider 缺失”。
        self.planner_providers = (
            dict(DEFAULT_PLANNER_PROVIDERS)
            if planner_providers is None
            else dict(planner_providers)
        )
        self.kernel = kernel

    def solve(self, problem: ProblemIR) -> SolverResult:
        """求解 ProblemIR，并返回统一 SolverResult。"""
        family = self.family_registry.match(problem)
        if family is None:
            return SolverResult(
                problem_id=problem.problem_id,
                status="unsupported",
                solver_family=None,
                errors=[
                    f"no solver for pattern={problem.pattern}, type={problem.problem_type}"
                ],
            )
        provider = self.planner_providers.get(family.family_id)
        if provider is None:
            return SolverResult(
                problem_id=problem.problem_id,
                status="failed",
                solver_family=family.family_id,
                errors=[
                    f"planner provider not found for family_id={family.family_id}"
                ],
            )
        kernel = self.kernel or SympyKernel()
        try:
            context = ContextBuilder(kernel).build(problem)
            specs = MethodSpecRegistry.load_from_code()
            context_inventory = ContextInventoryBuilder().build(context, specs)
            question_goals = extract_question_goals(problem)
            planner = provider(context)
            if not isinstance(planner, GenericPlanner):
                raise TypeError(
                    f"planner provider for family_id={family.family_id} returned invalid planner"
                )
            planner_inputs = PlannerInputs(
                problem_id=problem.problem_id,
                family_spec=family,
                question_goals=question_goals,
                context_inventory=context_inventory,
                method_specs=specs,
            )
            planner_output = PlannerOutput.from_legacy(planner.plan(planner_inputs))
            DeclarationValidator().validate_declarations(
                context,
                planner_output.context_declarations,
            )
            context.apply_declarations(planner_output.context_declarations)
            executor = InvocationExecutor(
                specs,
                methods=default_stateless_registry(),
                kernel=kernel,
            )
            execution = executor.execute_plan(context, planner_output.step_plans)
            answers = ResultBuilder().build(context, execution, question_goals)
        except Exception as exc:  # pragma: no cover - 集成测试会覆盖错误内容
            return SolverResult(
                problem_id=problem.problem_id,
                status="failed",
                solver_family=family.family_id,
                errors=[str(exc)],
            )

        trace = DerivationTrace(
            problem_id=problem.problem_id,
            pattern=problem.pattern,
            methods=execution.methods_used,
            steps=execution.trace_fragments,
        )
        status = "ok" if all(check.ok for check in execution.checks) else "failed"
        return SolverResult(
            problem_id=problem.problem_id,
            status=status,
            solver_family=family.family_id,
            methods_used=execution.methods_used,
            facts=[],
            trace=trace,
            answers=answers,
            checks=execution.checks,
            errors=[] if status == "ok" else ["one or more runtime checks failed"],
        )
