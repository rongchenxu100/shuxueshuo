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
from dataclasses import asdict, dataclass, is_dataclass
import json
from pathlib import Path
import time
from typing import Any

from shuxueshuo_server.solver.extraction.problem_planner_authority import (
    VerifiedPlannerProblemAuthority,
)
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalog,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    VerifiedSolverProblemBundle,
)

from shuxueshuo_server.solver.family import (
    DEFAULT_FAMILY_REGISTRY,
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
    FamilyRegistry,
)
from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.problem_models import ProblemIR, QuestionGoal
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.result_models import DerivationTrace, SolverResult
from shuxueshuo_server.solver.runtime.context import RuntimeContext, ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventoryBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FUNCTIONAL_GOAL_EXECUTION_CHECKPOINT_CONTRACT,
    VerifiedFunctionalPlanExecution,
)
from shuxueshuo_server.solver.runtime.macro_plan_materialization import (
    MacroExpansionRecord,
)
from shuxueshuo_server.solver.runtime.executor import (
    DeclarationValidator,
    InvocationExecutor,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
from shuxueshuo_server.solver.runtime.models import (
    PlanExecutionResult,
    PlannerOutput,
    StepExecutionResult,
)
from shuxueshuo_server.solver.runtime.planner import (
    GenericPlanner,
    Nankai25DeterministicPlannerAdapter,
    PlannerInputs,
)
from shuxueshuo_server.solver.runtime.result_builder import ResultBuilder
from shuxueshuo_server.solver.runtime.planner_state_context import PlannerStateContext
from shuxueshuo_server.solver.runtime.session import (
    LLMCallRecord,
    PlannerExecutionError,
    SolveAttemptRecord,
    SolveSession,
    StructuredSolveError,
    structured_error_from_exception,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    strategy_planner_provider,
)


PlannerProvider = Callable[..., GenericPlanner]


@dataclass(frozen=True)
class RuntimeSuccessArtifacts:
    """ExplanationBuilder 使用的内存成功产物。"""

    problem: ProblemIR
    family: SolverFamilySpec
    planner: GenericPlanner
    planner_output: PlannerOutput
    context: RuntimeContext
    execution: PlanExecutionResult
    question_goals: tuple[QuestionGoal, ...]
    solver_result: SolverResult
    problem_authority: VerifiedPlannerProblemAuthority | None = None
    problem_binding_catalog: ProblemPlanningBindingCatalog | None = None
    planner_state_context: PlannerStateContext | None = None
    verified_functional_execution: VerifiedFunctionalPlanExecution | None = None
    macro_expansions: tuple[MacroExpansionRecord, ...] = ()


def _planner_macro_expansions(
    planner_artifacts: Any | None,
) -> tuple[MacroExpansionRecord, ...]:
    scoped_retry = getattr(planner_artifacts, "scoped_retry_result", None)
    final_execution = getattr(scoped_retry, "final_execution", None)
    return tuple(getattr(final_execution, "macro_expansions", ()))


def _nankai25_planner_provider(context: RuntimeContext) -> GenericPlanner:
    """Phase 4 临时 provider：把南开 deterministic planner 包装成通用接口。"""
    return Nankai25DeterministicPlannerAdapter(context)


def _hexi25_planner_provider(context: RuntimeContext) -> GenericPlanner:
    """河西 25 provider：第二道 E2E 的 weighted deterministic planner。"""
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    return Hexi25WeightedPathPlannerV15(context)


DEBUG_DETERMINISTIC_PLANNER_PROVIDERS: dict[str, PlannerProvider] = {
    "tj-2026-nankai-yimo-25": _nankai25_planner_provider,
    "tj-2026-hexi-yimo-25": _hexi25_planner_provider,
}

DEFAULT_PLANNER_PROVIDERS: dict[str, PlannerProvider] = {}
DEFAULT_STRATEGY_PLANNER_PROVIDER: PlannerProvider = strategy_planner_provider(
    mode="recorded"
)


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
        default_planner_provider: PlannerProvider | None = DEFAULT_STRATEGY_PLANNER_PROVIDER,
        kernel: SympyKernel | None = None,
        max_attempts: int = 1,
        debug_dir: str | Path | None = None,
    ) -> None:
        self.family_registry = family_registry
        # ``None`` 表示使用生产默认 provider map。Strategy 生产化后，默认 map 不再
        # 注册 per-family deterministic provider，而是通过 default provider fallback
        # 使用 recorded StrategyPlanner。显式传入空 dict 且关闭 default provider 可
        # 测试“provider 缺失”。
        self.planner_providers = (
            dict(DEFAULT_PLANNER_PROVIDERS)
            if planner_providers is None
            else dict(planner_providers)
        )
        self.default_planner_provider = default_planner_provider
        self.kernel = kernel
        self.max_attempts = max(1, int(max_attempts))
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.last_session: SolveSession | None = None
        self.last_success_artifacts: RuntimeSuccessArtifacts | None = None

    def solve(self, problem: ProblemIR) -> SolverResult:
        """运行显式配置的deterministic/debug ProblemIR链路。

        该低层方法没有Problem Bundle authority，不能用于Strategy生产求解。使用
        默认Strategy provider调用时会稳定失败；生产调用方必须使用
        ``solve_verified()``，公开API则使用``engine.solve_problem()``。
        """
        return self._solve(problem, problem_authority=None)

    def solve_verified(
        self,
        bundle: VerifiedSolverProblemBundle,
    ) -> SolverResult:
        """从authenticated Bundle运行唯一的Strategy cold path。"""
        authority = VerifiedPlannerProblemAuthority.from_bundle(bundle)
        return self._solve_verified_scope_native(bundle, authority=authority)

    def _solve_verified_scope_native(
        self,
        bundle: VerifiedSolverProblemBundle,
        *,
        authority: VerifiedPlannerProblemAuthority,
    ) -> SolverResult:
        """Execute the public Bundle entry through content/v2 and Goal retry.

        The scoped service already owns semantic retries, transactions, and
        checkpoint restore.  This boundary only turns its verified final
        transaction into the public ``SolverResult``; it must never execute
        the derived v1 ``PlannerOutput`` a second time.
        """

        self.last_success_artifacts = None
        problem = bundle.build_solver_problem()
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
        if family.family_id != bundle.verified_problem.family_id:
            from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
                ProblemBundleAuthorityError,
            )

            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.family_id",
                "runtime family differs from the authenticated problem bundle",
            )
        provider = (
            self.planner_providers.get(problem.problem_id)
            or self.planner_providers.get(family.family_id)
            or self.default_planner_provider
        )
        if provider is None:
            return SolverResult(
                problem_id=problem.problem_id,
                status="failed",
                solver_family=family.family_id,
                errors=[
                    f"planner provider not found for family_id={family.family_id}"
                ],
            )

        started = time.perf_counter()
        session = SolveSession(
            problem_id=problem.problem_id,
            family_id=family.family_id,
            max_attempts=self.max_attempts,
        )
        self.last_session = session
        stage = "context"
        planner: GenericPlanner | None = None
        try:
            kernel = self.kernel or SympyKernel()
            context = ContextBuilder(kernel).build(problem)
            specs = MethodSpecRegistry.load_from_code()
            question_goals = extract_question_goals(problem)
            planner = provider(context, problem_authority=authority)
            run_scoped = getattr(planner, "run_scoped", None)
            if not callable(run_scoped):
                raise TypeError(
                    "planner.scope_native_entry_required: verified Bundle "
                    "providers must implement run_scoped()"
                )
            planner_inputs = PlannerInputs(
                problem_id=problem.problem_id,
                family_spec=family,
                question_goals=question_goals,
                context_inventory=ContextInventoryBuilder().build(
                    context,
                    specs,
                ),
                method_specs=specs,
                problem=problem,
                original_text=dict(problem.original_text),
                previous_errors=[],
            )
            stage = "scoped_planner"
            scoped_result = run_scoped(
                planner_inputs,
                max_attempts=self.max_attempts,
            )
            llm_call = _llm_call_from_planner(planner)
            _write_debug_attempt(
                self.debug_dir,
                max(1, len(scoped_result.attempts)),
                planner,
                getattr(getattr(planner, "artifacts", None), "output", None),
                None,
            )
            if scoped_result.status != "accepted":
                raise PlannerExecutionError(
                    _scoped_run_failure(scoped_result),
                )
            final_execution = scoped_result.final_execution
            if final_execution is None or final_execution.replay is None:
                raise ValueError(
                    "planner.scope_native_final_execution_missing"
                )
            checkpoint = final_execution.checkpoint
            if (
                checkpoint is None
                or checkpoint.schema_version
                != FUNCTIONAL_GOAL_EXECUTION_CHECKPOINT_CONTRACT
                or not checkpoint.all_required_goals_verified
            ):
                raise ValueError(
                    "planner.goal_checkpoint_v4_required: accepted scoped "
                    "execution has no verified checkpoint v3"
                )
            verified_execution = scoped_result.verified_execution
            if verified_execution is None:
                raise ValueError(
                    "planner.verified_functional_execution_missing"
                )
            transaction = final_execution.replay.transactional_attempt_result
            if (
                transaction is None
                or transaction.failed_call_ids
                or transaction.blocked_call_ids
                or transaction.root_issues
            ):
                raise ValueError(
                    "planner.scope_native_transaction_incomplete"
                )
            report = transaction.execution_report
            final_context = report.runtime_context
            if final_context is None:
                raise ValueError(
                    "planner.scope_native_runtime_context_missing"
                )
            planner_output = final_execution.replay.output
            if planner_output is None:
                planner_output = transaction.compiled_output
            planner_output = PlannerOutput.from_legacy(planner_output)
            execution = _plan_execution_from_transaction(report)
            failed_checks = [check for check in execution.checks if not check.ok]
            if failed_checks:
                raise PlannerExecutionError(
                    _structured_error_from_failed_checks(failed_checks)
                )
            stage = "result_builder"
            answers = ResultBuilder().build_from_verified_goal_results(
                final_context,
                question_goals,
                _verified_goal_runtime_results(
                    scoped_result,
                    report,
                ),
            )
        except Exception as exc:
            error = structured_error_from_exception(stage=stage, exc=exc)
            _write_debug_attempt(
                self.debug_dir,
                1,
                planner,
                None,
                error,
            )
            session.add_attempt(
                _attempt_record(
                    1,
                    "failed",
                    stage,
                    started,
                    [],
                    error,
                    _llm_call_from_planner(planner),
                )
            )
            session.final_status = "failed"
            return SolverResult(
                problem_id=problem.problem_id,
                status="failed",
                solver_family=family.family_id,
                errors=[error.message],
                run_log=_run_log(session),
            )

        session.add_attempt(
            _attempt_record(
                max(1, len(scoped_result.attempts)),
                "ok",
                stage,
                started,
                [],
                None,
                llm_call,
            )
        )
        session.final_status = "ok"
        trace = DerivationTrace(
            problem_id=problem.problem_id,
            pattern=problem.pattern,
            methods=execution.methods_used,
            steps=execution.trace_fragments,
        )
        result = SolverResult(
            problem_id=problem.problem_id,
            status="ok",
            solver_family=family.family_id,
            methods_used=execution.methods_used,
            facts=[],
            trace=trace,
            answers=answers,
            checks=execution.checks,
            errors=[],
            run_log=_run_log(session),
        )
        planner_artifacts = getattr(planner, "artifacts", None)
        self.last_success_artifacts = RuntimeSuccessArtifacts(
            problem=problem,
            family=family,
            planner=planner,
            planner_output=planner_output,
            context=final_context,
            execution=execution,
            question_goals=tuple(question_goals),
            solver_result=result,
            problem_authority=authority,
            problem_binding_catalog=getattr(
                planner_artifacts,
                "problem_binding_catalog",
                None,
            ),
            planner_state_context=getattr(
                planner_artifacts,
                "initial_planner_state_context",
                None,
            ),
            verified_functional_execution=verified_execution,
            macro_expansions=_planner_macro_expansions(planner_artifacts),
        )
        return result

    def _solve(
        self,
        problem: ProblemIR,
        *,
        problem_authority: VerifiedPlannerProblemAuthority | None,
    ) -> SolverResult:
        """运行共享runtime循环；Strategy调用必须携带Problem authority。"""
        self.last_success_artifacts = None
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
        if (
            problem_authority is not None
            and family.family_id != problem_authority.bundle.verified_problem.family_id
        ):
            from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
                ProblemBundleAuthorityError,
            )

            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.family_id",
                "runtime family differs from the authenticated problem bundle",
            )
        provider = (
            self.planner_providers.get(problem.problem_id)
            or self.planner_providers.get(family.family_id)
            or self.default_planner_provider
        )
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
        session = SolveSession(
            problem_id=problem.problem_id,
            family_id=family.family_id,
            max_attempts=self.max_attempts,
        )
        self.last_session = session
        previous_errors: list[object] = []

        for attempt_index in range(1, self.max_attempts + 1):
            attempt_problem = (
                problem_authority.bundle.build_solver_problem()
                if problem_authority is not None
                else problem
            )
            attempt_started = time.perf_counter()
            stage = "context"
            planner: GenericPlanner | None = None
            llm_call: LLMCallRecord | None = None
            try:
                # Repair 采用整体重生成 plan，因此每轮都从干净 RuntimeContext 开始。
                context = ContextBuilder(kernel).build(attempt_problem)
                specs = MethodSpecRegistry.load_from_code()
                context_inventory = ContextInventoryBuilder().build(context, specs)
                question_goals = extract_question_goals(attempt_problem)
                planner = (
                    provider(context, problem_authority=problem_authority)
                    if problem_authority is not None
                    else provider(context)
                )
                if not isinstance(planner, GenericPlanner):
                    raise TypeError(
                        f"planner provider for family_id={family.family_id} returned invalid planner"
                    )
                planner_inputs = PlannerInputs(
                    problem_id=attempt_problem.problem_id,
                    family_spec=family,
                    question_goals=question_goals,
                    context_inventory=context_inventory,
                    method_specs=specs,
                    problem=attempt_problem,
                    original_text=dict(attempt_problem.original_text),
                    previous_errors=list(previous_errors),
                )
                stage = "planner"
                planner_output = PlannerOutput.from_legacy(planner.plan(planner_inputs))
                llm_call = _llm_call_from_planner(planner)
                _write_debug_attempt(
                    self.debug_dir,
                    attempt_index,
                    planner,
                    planner_output,
                    None,
                )

                stage = "declaration_validation"
                DeclarationValidator().validate_declarations(
                    context,
                    planner_output.context_declarations,
                )
                context.apply_declarations(planner_output.context_declarations)

                stage = "execution"
                executor = InvocationExecutor(
                    specs,
                    methods=default_stateless_registry(),
                    kernel=kernel,
                )
                execution = executor.execute_plan(context, planner_output.step_plans)
                failed_checks = [check for check in execution.checks if not check.ok]
                if failed_checks:
                    error = _structured_error_from_failed_checks(failed_checks)
                    _write_debug_attempt(
                        self.debug_dir,
                        attempt_index,
                        planner,
                        planner_output,
                        error,
                    )
                    session.add_attempt(
                        _attempt_record(
                            attempt_index,
                            "failed",
                            stage,
                            attempt_started,
                            previous_errors,
                            error,
                            llm_call,
                        )
                    )
                    if attempt_index < self.max_attempts and error.retryable:
                        previous_errors = _next_previous_errors(
                            previous_errors,
                            planner,
                            attempt_index,
                            error,
                        )
                        continue
                    session.final_status = "failed"
                    return _failed_result_from_execution(
                        attempt_problem,
                        family.family_id,
                        execution,
                        [error.message],
                        session,
                    )

                stage = "result_builder"
                answers = ResultBuilder().build(context, execution, question_goals)
            except Exception as exc:  # pragma: no cover - 集成测试会覆盖错误内容
                llm_call = llm_call or _llm_call_from_planner(planner)
                error = structured_error_from_exception(stage=stage, exc=exc)
                _write_debug_attempt(
                    self.debug_dir,
                    attempt_index,
                    planner,
                    None,
                    error,
                )
                session.add_attempt(
                    _attempt_record(
                        attempt_index,
                        "failed",
                        stage,
                        attempt_started,
                        previous_errors,
                        error,
                        llm_call,
                    )
                )
                if attempt_index < self.max_attempts and error.retryable:
                    previous_errors = _next_previous_errors(
                        previous_errors,
                        planner,
                        attempt_index,
                        error,
                    )
                    continue
                session.final_status = "failed"
                return SolverResult(
                    problem_id=attempt_problem.problem_id,
                    status="failed",
                    solver_family=family.family_id,
                    errors=[error.message],
                    run_log=_run_log(session),
                )

            session.add_attempt(
                _attempt_record(
                    attempt_index,
                    "ok",
                    stage,
                    attempt_started,
                    previous_errors,
                    None,
                    llm_call,
                )
            )
            session.final_status = "ok"
            trace = DerivationTrace(
                problem_id=attempt_problem.problem_id,
                pattern=attempt_problem.pattern,
                methods=execution.methods_used,
                steps=execution.trace_fragments,
            )
            result = SolverResult(
                problem_id=attempt_problem.problem_id,
                status="ok",
                solver_family=family.family_id,
                methods_used=execution.methods_used,
                facts=[],
                trace=trace,
                answers=answers,
                checks=execution.checks,
                errors=[],
                run_log=_run_log(session),
            )
            self.last_success_artifacts = RuntimeSuccessArtifacts(
                problem=attempt_problem,
                family=family,
                planner=planner,
                planner_output=planner_output,
                context=context,
                execution=execution,
                question_goals=tuple(question_goals),
                solver_result=result,
                problem_authority=problem_authority,
                problem_binding_catalog=getattr(
                    getattr(planner, "artifacts", None),
                    "problem_binding_catalog",
                    None,
                ),
                planner_state_context=getattr(
                    getattr(
                        getattr(planner, "artifacts", None),
                        "retry_replay_result",
                        None,
                    ),
                    "planner_state_context",
                    None,
                ),
                verified_functional_execution=getattr(
                    getattr(planner, "artifacts", None),
                    "verified_execution",
                    None,
                ),
                macro_expansions=_planner_macro_expansions(
                    getattr(planner, "artifacts", None)
                ),
            )
            return result

        session.final_status = "failed"
        return SolverResult(
            problem_id=problem.problem_id,
            status="failed",
            solver_family=family.family_id,
            errors=["solver attempts exhausted"],
            run_log=_run_log(session),
        )


def _plan_execution_from_transaction(report: object) -> PlanExecutionResult:
    """Project the already executed transaction into public result artifacts."""

    step_results: list[StepExecutionResult] = []
    for call_result in getattr(report, "call_results", ()):
        if getattr(call_result, "status", None) != "verified":
            continue
        invocation_steps = tuple(getattr(call_result, "step_results", ()))
        step_results.append(
            StepExecutionResult(
                step_id=str(call_result.call_id),
                method_results=[
                    method_result
                    for item in invocation_steps
                    for method_result in item.method_results
                ],
                checks=[
                    check
                    for item in invocation_steps
                    for check in item.checks
                ],
                trace_fragments=[
                    fragment
                    for item in invocation_steps
                    for fragment in item.trace_fragments
                ],
            )
        )
    return PlanExecutionResult(
        step_results=step_results,
        checks=[
            check
            for step_result in step_results
            for check in step_result.checks
        ],
        trace_fragments=[
            fragment
            for step_result in step_results
            for fragment in step_result.trace_fragments
        ],
    )


def _verified_goal_runtime_results(
    scoped_result: object,
    report: object,
) -> dict[str, Any]:
    """Resolve each canonical Goal answer from the exact transaction return."""

    final_execution = getattr(scoped_result, "final_execution", None)
    plan = (
        getattr(final_execution, "canonical_plan", None)
        or getattr(scoped_result, "final_plan", None)
    )
    if plan is None:
        raise ValueError("planner.scope_native_final_plan_missing")
    runtime_values = getattr(report, "runtime_result_values", {})
    compiled_by_call = {
        item.call_id: item
        for item in getattr(report, "compiled_calls", ())
    }
    results: dict[str, Any] = {}

    def visit(scope: object) -> None:
        for goal in getattr(scope, "goals", ()):
            answer_from = goal.answer_from
            compiled = compiled_by_call.get(answer_from.step_id)
            public_return = next(
                (
                    item
                    for item in getattr(compiled, "public_returns", ())
                    if item.return_name == answer_from.return_name
                ),
                None,
            )
            output_key = (
                public_return.expected_write.output_key
                if public_return is not None
                and public_return.expected_write is not None
                else answer_from.return_name
            )
            key = (answer_from.step_id, output_key)
            typed_value = runtime_values.get(key)
            if typed_value is None:
                raise ValueError(
                    "planner.scope_native_answer_result_missing: "
                    f"goal={goal.goal_ref}, producer="
                    f"{answer_from.step_id}.{answer_from.return_name}, "
                    f"runtime_output={output_key}"
                )
            results[goal.goal_ref] = typed_value
        for child in getattr(scope, "children", ()):
            visit(child)

    visit(plan.root_scope)
    return results


def _scoped_run_failure(scoped_result: object) -> StructuredSolveError:
    """Select the prompt-safe blocker from a completed scoped retry run."""

    attempts = tuple(getattr(scoped_result, "attempts", ()))
    if attempts:
        error = getattr(attempts[-1], "error", None)
        if error is not None:
            return StructuredSolveError(
                stage="scoped_planner",
                code=str(getattr(error, "code", "planner.goal_retry_failed")),
                message=str(getattr(error, "message", error)),
                retryable=bool(getattr(error, "retryable", False)),
                path=getattr(error, "path", None),
                details=dict(getattr(error, "details", {}) or {}),
            )
    execution = getattr(scoped_result, "final_execution", None)
    checkpoint = getattr(execution, "checkpoint", None)
    root_issues = tuple(getattr(checkpoint, "root_issues", ()))
    if root_issues:
        issue = dict(root_issues[0])
        return StructuredSolveError(
            stage=str(issue.get("layer") or issue.get("stage") or "scoped_planner"),
            code=str(issue.get("code") or "planner.goal_retry_failed"),
            message=str(issue.get("message") or "scope-native Goal retry failed"),
            retryable=False,
            step_id=(str(issue["step_id"]) if issue.get("step_id") else None),
            details={"root_issues": [dict(item) for item in root_issues]},
        )
    return StructuredSolveError(
        stage="scoped_planner",
        code="planner.goal_retry_exhausted",
        message="scope-native Goal retry exhausted without a verified execution",
        retryable=False,
        details={"no_progress": bool(getattr(scoped_result, "no_progress", False))},
    )


def _attempt_record(
    attempt_index: int,
    status: str,
    stage: str,
    started: float,
    previous_errors: list[object],
    error: StructuredSolveError | None,
    llm_call: LLMCallRecord | None,
) -> SolveAttemptRecord:
    """创建 attempt 摘要，统一计算耗时。"""
    return SolveAttemptRecord(
        attempt_index=attempt_index,
        status=status,
        stage=stage,
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        previous_error_count=len(previous_errors),
        error=error,
        llm_call=llm_call,
    )


def _llm_call_from_planner(planner: GenericPlanner | None) -> LLMCallRecord | None:
    """从 planner/client 上读取最近一次 LLM 调用摘要。

    Provider 协议仍保持 ``complete(...) -> str``，usage/model 由 provider client 以
    ``last_*`` 属性暴露。没有 client 的 deterministic planner 返回 ``None``。
    """
    client = getattr(planner, "client", None) if planner is not None else None
    if client is None:
        return None
    provider = getattr(client, "provider_name", client.__class__.__name__)
    usage = getattr(client, "last_usage", None)
    response_model = getattr(client, "last_response_model", None)
    return LLMCallRecord(
        provider=str(provider),
        model=getattr(client, "model", None),
        response_model=str(response_model) if response_model else None,
        usage=dict(usage) if isinstance(usage, dict) else usage,
    )


def _planner_repair_attempt_payload(
    planner: GenericPlanner | None,
    attempt_index: int,
    errors: list[str],
) -> dict[str, object] | None:
    """从 StrategyPlanner 等 planner 上读取下一轮 LLM repair context。"""
    if planner is None:
        return None
    method = getattr(planner, "repair_attempt_payload", None)
    if not callable(method):
        return None
    payload = method(attempt=attempt_index, errors=errors)
    return payload if isinstance(payload, dict) else None


def _next_previous_errors(
    previous_errors: list[object],
    planner: GenericPlanner | None,
    attempt_index: int,
    error: StructuredSolveError,
) -> list[object]:
    """合并下一轮 repair context，避免 validation 早失败覆盖 rich context。"""
    fallback = error.to_payload()
    payload = _planner_repair_attempt_payload(planner, attempt_index, [error.message])
    if payload is None:
        return [*previous_errors, fallback] if _has_rich_repair_context(previous_errors) else [fallback]
    if _is_rich_repair_context(payload):
        return [payload]
    if _has_rich_repair_context(previous_errors):
        return [*previous_errors, payload]
    return [payload]


def _is_rich_repair_context(payload: object) -> bool:
    """判断 previous_attempt 是否包含 Functional retry state。"""
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get("planner_retry_state"), dict)


def _has_rich_repair_context(items: list[object]) -> bool:
    """previous_errors 中是否已有 rich repair context。"""
    return any(_is_rich_repair_context(item) for item in items)


def _structured_error_from_failed_checks(checks: list[object]) -> StructuredSolveError:
    """把 failed checks 聚合成可 repair 的 execution 错误。"""
    first = checks[0]
    check_name = getattr(first, "name", None)
    details = [
        {
            "name": getattr(check, "name", ""),
            "detail": getattr(check, "detail", ""),
        }
        for check in checks
    ]
    return StructuredSolveError(
        stage="execution",
        code="runtime_check_failed",
        message="one or more runtime checks failed",
        retryable=True,
        check_name=str(check_name) if check_name else None,
        details={"failed_checks": details},
    )


def _failed_result_from_execution(
    problem: ProblemIR,
    family_id: str,
    execution: object,
    errors: list[str],
    session: SolveSession,
) -> SolverResult:
    """执行已产出 trace/checks 但最终失败时，保留这些上下文给调用方。"""
    trace = DerivationTrace(
        problem_id=problem.problem_id,
        pattern=problem.pattern,
        methods=getattr(execution, "methods_used", []),
        steps=getattr(execution, "trace_fragments", []),
    )
    return SolverResult(
        problem_id=problem.problem_id,
        status="failed",
        solver_family=family_id,
        methods_used=getattr(execution, "methods_used", []),
        trace=trace,
        checks=getattr(execution, "checks", []),
        errors=errors,
        run_log=_run_log(session),
    )


def _run_log(session: SolveSession) -> dict[str, object] | None:
    """只有发生 LLM 调用或 retry 时才输出 run_log，保持 deterministic JSON 稳定。"""
    if not session.has_llm_activity and len(session.attempts) <= 1:
        return None
    return session.to_public_dict()


def _write_debug_attempt(
    debug_dir: Path | None,
    attempt_index: int,
    planner: GenericPlanner | None,
    planner_output: PlannerOutput | None,
    error: StructuredSolveError | None,
) -> None:
    """按 attempt 写出 prompt、raw response、draft、compiled output 和错误。

    debug 文件用于本地调 prompt，不进入 RuntimeContext，也不包含 API key。
    """
    if debug_dir is None or planner is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"attempt-{attempt_index}"
    prompt = getattr(planner, "last_prompt", None)
    payload = getattr(planner, "last_payload", None)
    if prompt is not None:
        messages = (
            prompt.as_messages()
            if hasattr(prompt, "as_messages")
            else getattr(prompt, "messages", None)
        )
        _write_json(
            debug_dir / f"{prefix}.prompt.json",
            {
                "messages": messages,
                "planner_payload": payload,
            },
        )
        (debug_dir / f"{prefix}.prompt.system.md").write_text(
            str(getattr(prompt, "system", "")),
            encoding="utf-8",
        )
        (debug_dir / f"{prefix}.prompt.user.md").write_text(
            str(getattr(prompt, "user", "")),
            encoding="utf-8",
        )
    if isinstance(payload, dict):
        for key, value in payload.items():
            _write_json(
                debug_dir / f"{prefix}.payload.{key}.json",
                value,
            )
    planner_artifacts = getattr(planner, "artifacts", None)
    problem_authority = getattr(planner_artifacts, "problem_authority", None)
    problem_binding_catalog = getattr(
        planner_artifacts,
        "problem_binding_catalog",
        None,
    )
    if problem_authority is not None:
        _write_json(
            debug_dir / f"{prefix}.problem-bundle-authority.json",
            problem_authority.authority_payload(),
        )
    if problem_binding_catalog is not None:
        _write_json(
            debug_dir / f"{prefix}.problem-planning-binding-catalog.json",
            problem_binding_catalog.authority_payload(),
        )
    raw_response = getattr(planner, "last_raw_response", None)
    if raw_response is not None:
        (debug_dir / f"{prefix}.raw-response.txt").write_text(
            str(raw_response),
            encoding="utf-8",
        )
        try:
            functional_payload = json.loads(str(raw_response))
        except json.JSONDecodeError:
            functional_payload = {"raw_response": str(raw_response)}
        _write_json(
            debug_dir / f"{prefix}.functional-plan.json",
            functional_payload,
        )
    client = getattr(planner, "client", None)
    if client is not None:
        scoped_attempts = tuple(
            getattr(
                getattr(
                    getattr(planner, "artifacts", None),
                    "scoped_retry_result",
                    None,
                ),
                "attempts",
                (),
            )
        )
        planner_protocol = (
            str(scoped_attempts[-1].planner_protocol)
            if scoped_attempts
            else "functional_plan/v1"
        )
        _write_json(
            debug_dir / f"{prefix}.llm-metadata.json",
            {
                "provider": getattr(
                    client,
                    "provider_name",
                    client.__class__.__name__,
                ),
                "request_model": getattr(client, "model", None),
                "response_model": getattr(
                    client,
                    "last_response_model",
                    None,
                ),
                "usage": getattr(client, "last_usage", None),
                "provider_attempts": getattr(
                    client,
                    "last_provider_attempts",
                    None,
                ),
                "planner_protocol": planner_protocol,
            },
        )
    validation_report = getattr(planner, "last_validation_report", None)
    if validation_report is not None:
        _write_json(
            debug_dir / f"{prefix}.validation-report.json",
            _safe_json(validation_report),
        )
    diagnostic = getattr(planner, "last_execution_diagnostic", None)
    if diagnostic is not None:
        _write_json(
            debug_dir / f"{prefix}.execution-diagnostic.json",
            _safe_json(diagnostic),
        )
    replay = getattr(
        getattr(planner, "artifacts", None),
        "retry_replay_result",
        None,
    )
    if replay is not None:
        replay_artifacts = {
            "functional-validation-report": getattr(
                replay,
                "functional_validation_report",
                None,
            ),
            "functional-reconciliation-report": getattr(
                replay,
                "functional_reconciliation",
                None,
            ),
            "normalization-report": getattr(
                replay,
                "normalization_report",
                None,
            ),
            "resolution-report": getattr(
                replay,
                "resolution_report",
                None,
            ),
            "planner-retry-state": getattr(replay, "retry_state", None),
            "planner-state-context": getattr(
                replay,
                "planner_state_context",
                None,
            ),
        }
        for artifact_name, artifact_payload in replay_artifacts.items():
            if artifact_payload is not None:
                if (
                    artifact_name == "functional-reconciliation-report"
                    and hasattr(artifact_payload, "to_payload")
                ):
                    artifact_payload = artifact_payload.to_payload()
                _write_json(
                    debug_dir / f"{prefix}.{artifact_name}.json",
                    _safe_json(artifact_payload),
                )
    repair_payload = _planner_repair_attempt_payload(
        planner,
        attempt_index,
        [error.message] if error is not None else [],
    )
    if repair_payload is not None:
        _write_json(
            debug_dir / f"{prefix}.previous-attempt-payload.json",
            repair_payload,
        )
    output = planner_output or getattr(planner, "last_output", None)
    if output is not None:
        _write_json(
            debug_dir / f"{prefix}.compiled-planner-output.json",
            _safe_json(output),
        )
    if error is not None:
        _write_json(
            debug_dir / f"{prefix}.structured-error.json",
            error.to_payload(),
        )


def _write_json(path: Path, payload: Any) -> None:
    """写入稳定格式的 debug JSON。"""
    from shuxueshuo_server.solver.runtime.llm_debug import write_debug_json

    write_debug_json(path, _safe_json(payload))


def _safe_json(value: Any) -> Any:
    """把 dataclass、tuple、复杂对象转成 debug JSON 友好形态。"""
    if is_dataclass(value):
        return _safe_json(asdict(value))
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    return value
