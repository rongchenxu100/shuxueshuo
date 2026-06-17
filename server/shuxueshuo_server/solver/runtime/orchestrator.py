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
from shuxueshuo_server.solver.runtime.executor import (
    DeclarationValidator,
    InvocationExecutor,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
from shuxueshuo_server.solver.runtime.models import PlanExecutionResult, PlannerOutput
from shuxueshuo_server.solver.runtime.planner import (
    GenericPlanner,
    Nankai25DeterministicPlannerAdapter,
    PlannerInputs,
)
from shuxueshuo_server.solver.runtime.result_builder import ResultBuilder
from shuxueshuo_server.solver.runtime.session import (
    LLMCallRecord,
    SolveAttemptRecord,
    SolveSession,
    StructuredSolveError,
    structured_error_from_exception,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    strategy_planner_provider,
)


PlannerProvider = Callable[[RuntimeContext], GenericPlanner]


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
    QUADRATIC_PATH_MINIMUM_FAMILY.family_id: _nankai25_planner_provider,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id: _hexi25_planner_provider,
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
        """求解 ProblemIR，并返回统一 SolverResult。"""
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
        provider = (
            self.planner_providers.get(family.family_id)
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
            attempt_started = time.perf_counter()
            stage = "context"
            planner: GenericPlanner | None = None
            llm_call: LLMCallRecord | None = None
            try:
                # Repair 采用整体重生成 plan，因此每轮都从干净 RuntimeContext 开始。
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
                    problem=problem,
                    original_text=dict(problem.original_text),
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
                        problem,
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
                    problem_id=problem.problem_id,
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
            self.last_success_artifacts = RuntimeSuccessArtifacts(
                problem=problem,
                family=family,
                planner=planner,
                planner_output=planner_output,
                context=context,
                execution=execution,
                question_goals=tuple(question_goals),
                solver_result=result,
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
    """判断 previous_attempt 是否包含 effective draft + diagnostic。"""
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get("effective_draft"), dict) and isinstance(payload.get("diagnostic"), dict)


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
    raw_response = getattr(planner, "last_raw_response", None)
    if raw_response is not None:
        (debug_dir / f"{prefix}.raw-response.txt").write_text(
            str(raw_response),
            encoding="utf-8",
        )
    raw_draft = getattr(planner, "last_raw_draft", None)
    if raw_draft is not None:
        _write_json(debug_dir / f"{prefix}.raw-draft.json", _safe_json(raw_draft))
    validation_report = getattr(planner, "last_validation_report", None)
    if validation_report is not None:
        _write_json(
            debug_dir / f"{prefix}.validation-report.json",
            _safe_json(validation_report),
        )
    draft = getattr(planner, "last_draft", None)
    if draft is not None:
        _write_json(debug_dir / f"{prefix}.parsed-draft.json", _safe_json(draft))
    effective_draft = getattr(planner, "last_effective_draft", None)
    if effective_draft is not None:
        _write_json(
            debug_dir / f"{prefix}.effective-draft.json",
            _safe_json(effective_draft),
        )
    diagnostic = getattr(planner, "last_execution_diagnostic", None)
    if diagnostic is not None:
        _write_json(
            debug_dir / f"{prefix}.execution-diagnostic.json",
            _safe_json(diagnostic),
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
    path.write_text(
        json.dumps(_safe_json(payload), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _safe_json(value: Any) -> Any:
    """把 dataclass、tuple、复杂对象转成 debug JSON 友好形态。"""
    if is_dataclass(value):
        return _safe_json(asdict(value))
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    return value
