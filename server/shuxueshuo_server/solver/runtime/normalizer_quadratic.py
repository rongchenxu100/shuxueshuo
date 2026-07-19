"""Quadratic-function and parameter-oriented normalization rules."""

from __future__ import annotations

from dataclasses import replace
import re

from shuxueshuo_server.solver.question_goals import QuestionGoal
from shuxueshuo_server.solver.runtime.handle_registry import (
    _handle_name,
    _handle_scope,
    _semantic_name,
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProducedFact,
    StepIntent,
    StepIntentNormalizationAction,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import _produced_output_type
from shuxueshuo_server.solver.runtime.normalizer_binding import _register_published_outputs
from shuxueshuo_server.solver.runtime.normalizer_common import (
    NormalizationRuleContext,
    NormalizationRuleResult,
    _angle_sum_existing_point_target,
    _append_unique_produces,
    _append_unique,
    _available_handles,
    _axis_intercept_target_point_handle,
    _is_generic_point_coordinate_name,
    _is_specific_point_coordinate_name,
    _point_name_from_coordinate_fact,
    _point_name_from_goal_target,
    _point_name_from_point_handle,
    _point_scope_from_goal_target,
    _previous_axis_answer_step_for_fact,
    _rewrite_generic_angle_equality_handle,
    _rewrite_step_reads_many,
    _single_point_answer_goal,
    _step_has_point_target,
    _step_with_angle_sum_target,
    _step_with_read,
    _step_without_create,
    _unique_ordered,
    _unique_read_handles,
    _valid_scope_visible_from,
    _visible_fact_handle_by_type,
)

class _DropUnavailableQuadraticCoefficientReadsRule:
    """删除已被归一化为 coefficients 伴随输出的系数值 reads。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _drop_unavailable_quadratic_coefficient_reads_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(step=step, actions=tuple(actions))

class _QuadraticFromConstraintsRule:
    """归一化 quadratic_from_constraints 的 utility fact。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, rewrites, actions = _normalize_quadratic_from_constraints_step(
            step,
            handle_registry=context.handle_registry,
        )
        return NormalizationRuleResult(
            step=step,
            rewrites=rewrites,
            actions=tuple(actions),
        )

class _MixedQuadraticOutputSplitRule:
    """把 LLM 合并到 quadratic step 的参数/点坐标输出拆成 executable steps。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _split_mixed_quadratic_outputs_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(step=step, actions=tuple(actions))

class _ParameterSolverOutputAliasRule:
    """删除参数求解 step 中夹带的二次函数系数值别名。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _normalize_parameter_solver_outputs_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(step=step, actions=tuple(actions))

class _MultiPointEvaluationSplitRule:
    """把一个参数代入 step 中的多个点坐标输出拆成多个单点代入 step。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        append_step, actions = _split_multi_point_evaluation_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(
            step=step,
            actions=tuple(actions),
            append_step=append_step,
        )

class _AxisPointMethodAliasRule:
    """把轴点 answer 的相邻 method alias 收敛到 family 可执行 method。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _normalize_axis_point_method_alias_step(
            step,
            question_goal_map=context.question_goal_map,
            handle_registry=context.handle_registry,
        )
        return NormalizationRuleResult(step=step, actions=tuple(actions))

class _CandidatePointFactsRule:
    """归一化候选点散列 fact 为候选列表 fact。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, rewrites, actions = _normalize_candidate_point_facts_step(
            step,
            handle_registry=context.handle_registry,
        )
        return NormalizationRuleResult(
            step=step,
            rewrites=rewrites,
            actions=tuple(actions),
        )

class _PointAnswerCoordinateRule:
    """用唯一 Point answer 目标点名归一化泛化坐标 fact。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, rewrites, actions = _normalize_point_answer_coordinate_step(
            step,
            question_goal_map=context.question_goal_map,
            handle_registry=context.handle_registry,
        )
        return NormalizationRuleResult(
            step=step,
            rewrites=rewrites,
            actions=tuple(actions),
        )

class _AxisPointAliasRule:
    """把 axis point answer 与可复用坐标 fact 归一化为同一 Point alias。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        result = _normalize_axis_point_alias_step(
            step,
            previous_steps=context.previous_steps,
            question_goal_map=context.question_goal_map,
            handle_registry=context.handle_registry,
        )
        normalized, rewrites, actions, append_step, merge_target_index = result
        if merge_target_index is not None:
            target_step = context.previous_steps[merge_target_index]
            existing = {item.handle for item in target_step.produces}
            additions = tuple(
                item for item in normalized.produces
                if item.handle not in existing
            )
            if additions:
                context.previous_steps[merge_target_index] = replace(
                    target_step,
                    produces=(*target_step.produces, *additions),
                )
        return NormalizationRuleResult(
            step=normalized,
            rewrites=rewrites,
            actions=tuple(actions),
            append_step=append_step,
        )

class _AnswerPointAliasRule:
    """把裸 Point answer step 合并到前序同点坐标状态。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        append_step, actions = _merge_point_answer_alias_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(
            step=step,
            actions=tuple(actions),
            append_step=append_step,
        )

class _EvaluateParameterizedOutputAliasRule:
    """把“代入参数求结构化输出”的自然写法改成可执行 capability。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _normalize_evaluate_parameterized_output_alias_step(step)
        return NormalizationRuleResult(step=step, actions=tuple(actions))

class _DropParameterizedParabolaUtilityRule:
    """删除仅供后续代入的公共含参抛物线缓存 step。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        rewrites, actions = _parameterized_parabola_utility_rewrites(step)
        if not rewrites:
            return NormalizationRuleResult(step=step)
        return NormalizationRuleResult(
            step=step,
            rewrites=rewrites,
            actions=tuple(actions),
            append_step=False,
        )

class _MinimumAnswerParameterReadRule:
    """最终最小值 answer 若已有参数值，自动读取以完成代入。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, action = _add_parameter_read_for_minimum_answer_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(
            step=step,
            actions=(action,) if action is not None else (),
        )

class _KnownSymbolValueReadCompletionRule:
    """为 quadratic_from_constraints 自动补齐已知系数值 reads。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _complete_known_symbol_value_reads_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(step=step, actions=tuple(actions))

class _KnownPointCoordinateUtilityRule:
    """删除已知点坐标 utility step，并把后续 reads 改为已有 point handle。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        rewrites, actions = _known_point_coordinate_rewrites(
            step,
            handle_registry=context.handle_registry,
        )
        if not rewrites:
            return NormalizationRuleResult(step=step)
        if len(rewrites) != len(step.produces):
            return NormalizationRuleResult(step=step)
        return NormalizationRuleResult(
            step=step,
            rewrites=rewrites,
            actions=tuple(actions),
            append_step=False,
        )

def _drop_unavailable_quadratic_coefficient_reads_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """删除不可用的 a/b/c 系数值 reads，保留题面或前序真实产物。"""
    dropped = tuple(
        handle
        for handle in step.reads
        if _is_unavailable_quadratic_coefficient_read(handle, context)
    )
    if not dropped:
        return step, []
    dropped_set = set(dropped)
    return (
        replace(
            step,
            reads=tuple(handle for handle in step.reads if handle not in dropped_set),
        ),
        [
            StepIntentNormalizationAction(
                action="drop_unavailable_quadratic_coefficient_read",
                step_id=step.step_id,
                handle=handle,
                target_step_id=None,
                reason=(
                    "a/b/c 系数值在当前执行层不是可读 ParameterValue；"
                    "若它只是 quadratic_from_constraints 的伴随 coefficients，"
                    "后续 step 不应单独 reads 这个 fact。"
                ),
            )
            for handle in dropped
        ],
    )

def _is_unavailable_quadratic_coefficient_read(
    handle: str,
    context: NormalizationRuleContext,
) -> bool:
    if not handle.startswith("fact:"):
        return False
    if handle in _available_handles(context):
        return False
    return _semantic_name(handle).lower() in {"a_value", "b_value", "c_value"}

def _normalize_axis_point_method_alias_step(
    step: StepIntent,
    *,
    question_goal_map: dict[str, QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """LLM 常把轴点 D 写成“由抛物线求轴截点”，这里改成可执行的系数关系 method。"""
    if step.recipe_hint != "quadratic_axis_x_intercept_point":
        return step, []
    axis_goal = _single_point_answer_goal(step, question_goal_map)
    if axis_goal is None:
        return step, []
    answer_text = "\n".join(
        (step.target, *(item.handle for item in step.produces))
    ).lower()
    if not any(token in answer_text for token in ("axis_point", "axis_x_intercept")):
        return step, []
    step = replace(
        step,
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
    )
    coefficient_relation = _visible_fact_handle_by_type(
        "coefficient_relation",
        step.scope_id,
        handle_registry,
        preferred=tuple(step.reads),
    )
    if coefficient_relation is not None:
        step = _step_with_read(step, coefficient_relation)
    return step, [
        StepIntentNormalizationAction(
            action="normalize_axis_point_method_alias",
            step_id=step.step_id,
            handle=axis_goal.id,
            target_step_id=None,
            reason=(
                "该 step produces axis point answer；当前 family 的可执行 method 是 "
                "quadratic_axis_from_relation，自动把相邻 alias "
                "quadratic_axis_x_intercept_point 改写为该 method。"
            ),
        )
    ]

def _normalize_evaluate_parameterized_output_alias_step(
    step: StepIntent,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """将 LLM 的“evaluate_expression_at_parameter -> 结构化答案”改成可执行 method。"""
    if not _is_parameterized_output_evaluation_step(step):
        return step, []
    output_types = {
        item.output_type
        for item in step.produces
        if item.output_type is not None
    }
    if output_types == {"Parabola"}:
        reads = tuple(
            handle for handle in step.reads
            if not _is_parameterized_parabola_read(handle)
        )
        return (
            replace(
                step,
                recipe_hint="quadratic_from_constraints",
                goal_type="derive_parabola",
                reads=reads,
            ),
            [
                StepIntentNormalizationAction(
                    action="normalize_parameterized_parabola_evaluation",
                    step_id=step.step_id,
                    handle=",".join(item.handle for item in step.produces),
                    target_step_id=None,
                    reason=(
                        "该 step 用 evaluate_expression_at_parameter 产出 Parabola；"
                        "结构化抛物线应由 quadratic_from_constraints 在读取参数值后直接求出。"
                    ),
                )
            ],
        )
    if output_types == {"MinimumExpression"}:
        return (
            replace(
                step,
                recipe_hint="evaluate_expression_at_parameter",
                goal_type="evaluate_expression_at_parameter",
            ),
            [
                StepIntentNormalizationAction(
                    action="normalize_parameterized_minimum_evaluation",
                    step_id=step.step_id,
                    handle=",".join(item.handle for item in step.produces),
                    target_step_id=None,
                    reason=(
                        "该 step 表达的是将参数值代入最小值表达式；"
                        "使用 evaluate_expression_at_parameter 直接产出 evaluated_minimum_expression。"
                    ),
                )
            ],
        )
    return step, []

def _is_parameterized_output_evaluation_step(step: StepIntent) -> bool:
    """判断 step 是否表达“代入参数求结构化输出”。"""
    return (
        step.recipe_hint == "evaluate_expression_at_parameter"
        or step.goal_type == "evaluate_expression_at_parameter"
    )

def _is_parameterized_parabola_read(handle: str) -> bool:
    """判断 read 是否只是前序含参抛物线缓存。"""
    if not handle.startswith("fact:"):
        return False
    semantic_name = _semantic_name(handle).lower()
    return "parabola" in semantic_name and any(
        token in semantic_name for token in ("with_param", "_in_")
    )

def _parameterized_parabola_utility_rewrites(
    step: StepIntent,
) -> tuple[dict[str, str], list[StepIntentNormalizationAction]]:
    """删除后续会直接重算的含参抛物线缓存 step。"""
    if step.recipe_hint != "quadratic_from_constraints":
        return {}, []
    if any(item.handle.startswith("answer:") for item in step.produces):
        return {}, []
    parameterized_items = [
        item for item in step.produces
        if item.output_type == "Parabola" and _is_droppable_parameterized_parabola(item.handle)
    ]
    if not parameterized_items:
        return {}, []
    rewrites = {
        item.handle: "function:problem:parabola"
        for item in parameterized_items
    }
    actions = [
        StepIntentNormalizationAction(
            action="drop_parameterized_parabola_utility_step",
            step_id=step.step_id,
            handle=item.handle,
            target_step_id=None,
            reason=(
                "含参抛物线缓存是讲解性 utility；后续最终抛物线 step 会读取参数值并用 "
                "quadratic_from_constraints 直接求 answer，当前 utility step 不进入 runtime。"
            ),
        )
        for item in parameterized_items
    ]
    return rewrites, actions

def _is_droppable_parameterized_parabola(handle: str) -> bool:
    """只删除 LLM 显式写作 ``*_with_param`` 的缓存，不删除 parametric_parabola。"""
    if not handle.startswith("fact:"):
        return False
    semantic_name = _semantic_name(handle).lower()
    return "parabola" in semantic_name and "with_param" in semantic_name

def _add_parameter_read_for_minimum_answer_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, StepIntentNormalizationAction | None]:
    """最终最小值 answer 若前序已有参数值，自动补 read 以完成代入。"""
    if not _step_outputs_minimum_answer(step):
        return step, None
    if _parameter_value_read_for_mixed_quadratic(step, context) is not None:
        return step, None
    parameter_handle = _visible_runtime_parameter_value_handle(step, context)
    if parameter_handle is None or parameter_handle in step.reads:
        return step, None
    return (
        _step_with_read(step, parameter_handle),
        StepIntentNormalizationAction(
            action="add_parameter_read_for_minimum_answer",
            step_id=step.step_id,
            target_step_id=None,
            handle=parameter_handle,
            reason=(
                "该 step produces 最终最小值 answer，且前序已有唯一可见运行参数值；"
                "自动加入参数 read，使 distance/path minimum 在输出前完成代入。"
            ),
        ),
    )

def _complete_known_symbol_value_reads_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """为二次函数约束 step 补齐 LLM 省略的已知 symbol value fact。"""
    if step.recipe_hint != "quadratic_from_constraints":
        return step, []
    symbol_reads = tuple(handle for handle in step.reads if handle.startswith("symbol:"))
    if not symbol_reads:
        return step, []

    additions: list[str] = []
    actions: list[StepIntentNormalizationAction] = []
    for symbol_handle in symbol_reads:
        if _step_already_reads_symbol_value(step, symbol_handle, context):
            continue
        value_handle = _visible_symbol_value_fact_for_symbol(
            symbol_handle,
            step=step,
            context=context,
        )
        if value_handle is None or value_handle in step.reads:
            continue
        additions.append(value_handle)
        actions.append(
            StepIntentNormalizationAction(
                action="add_known_symbol_value_read",
                step_id=step.step_id,
                handle=value_handle,
                target_step_id=None,
                reason=(
                    f"{step.recipe_hint} 读取了 {symbol_handle}，且题面存在唯一可见的"
                    " symbol_value fact；自动补齐该已知值 read，减少 LLM 区分"
                    " symbol entity 与 value fact 的负担。"
                ),
            )
        )
    if not additions:
        return step, []
    return replace(step, reads=_append_unique(step.reads, tuple(additions))), actions

def _step_already_reads_symbol_value(
    step: StepIntent,
    symbol_handle: str,
    context: NormalizationRuleContext,
) -> bool:
    """判断 step 是否已经读取了某 symbol 对应的 value fact。"""
    return any(
        _symbol_value_fact_subject(handle, context) == symbol_handle
        for handle in step.reads
    )

def _visible_symbol_value_fact_for_symbol(
    symbol_handle: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    """查找当前 step 可见且唯一的 symbol_value fact。"""
    candidates = [
        handle
        for handle in sorted(context.handle_registry.fact_handles)
        if _symbol_value_fact_subject(handle, context) == symbol_handle
        and _valid_scope_visible_from(
            context.handle_registry.handle_valid_scopes.get(handle, step.scope_id),
            step.scope_id,
            context.handle_registry,
        )
    ]
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None

def _symbol_value_fact_subject(
    handle: str,
    context: NormalizationRuleContext,
) -> str | None:
    """读取 symbol_value fact 的 subject symbol handle。"""
    if context.handle_registry.fact_types.get(handle) != "symbol_value":
        return None
    payload = context.handle_registry.fact_payloads.get(handle, {})
    subject = payload.get("subject")
    if isinstance(subject, str) and subject.startswith("symbol:"):
        return subject
    subjects = payload.get("subjects")
    if isinstance(subjects, list):
        symbol_subjects = [
            item for item in subjects
            if isinstance(item, str) and item.startswith("symbol:")
        ]
        unique = _unique_ordered(symbol_subjects)
        return unique[0] if len(unique) == 1 else None
    semantic = _semantic_name(handle).lower()
    match = re.fullmatch(r"(?P<symbol>[A-Za-z][A-Za-z0-9_]*)_value", semantic)
    if match is None:
        return None
    symbol_name = match.group("symbol")
    scope = context.handle_registry.handle_valid_scopes.get(handle)
    if scope is not None:
        candidate = f"symbol:{scope}:{symbol_name}"
        if candidate in context.handle_registry.entity_handles:
            return candidate
    problem_candidate = f"symbol:problem:{symbol_name}"
    if problem_candidate in context.handle_registry.entity_handles:
        return problem_candidate
    return None

def _step_outputs_minimum_answer(step: StepIntent) -> bool:
    """判断 step 是否产出最终最小值 answer。"""
    for item in step.produces:
        if not item.handle.startswith("answer:"):
            continue
        text = f"{item.handle}\n{item.description}\n{item.output_type or ''}".lower()
        if "minimum" in text or "min_value" in text or item.output_type == "MinimumExpression":
            return True
    return False

def _visible_runtime_parameter_value_handle(
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    """查找对当前 step 唯一可见的运行参数值 output。"""
    candidates: list[str] = []
    for previous in context.previous_steps:
        for item in previous.produces:
            if item.output_type != "ParameterValue":
                continue
            if not _is_runtime_parameter_value_name(_semantic_name(item.handle).lower()):
                continue
            if not _valid_scope_visible_from(
                item.valid_scope,
                step.scope_id,
                context.handle_registry,
            ):
                continue
            candidates.append(item.handle)
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None

def _normalize_angle_sum_axis_intercept_targets_for_scope(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
    """为“角和找等角 -> 等角求轴截点”链路补齐目标 PointRef。

    DeepSeek 有时把 ``angle_sum_equal_angle_candidates`` 的 target 写成它要
    produces 的 ``AngleEquality`` fact。执行层实际需要的 target 是后续
    ``axis_intercept_from_equal_acute_angles`` 要计算的轴截点 PointRef。若后续
    step 明确读取了该 AngleEquality，或二者是相邻链路但 LLM 漏写了 reads，
    我们可以从 axis step 的 target/creates/Point output 反推出目标点，并把
    它声明为前一步 creates。
    """
    if not steps:
        return steps, []

    result = list(steps)
    actions: list[StepIntentNormalizationAction] = []
    produced_to_step: dict[str, int] = {}
    for index, step in enumerate(result):
        for produced in step.produces:
            produced_to_step[produced.handle] = index

    for axis_index, axis_step in enumerate(list(result)):
        if axis_step.recipe_hint != "axis_intercept_from_equal_acute_angles":
            continue
        angle_handles = [
            handle for handle in axis_step.reads
            if produced_to_step.get(handle, axis_index) < axis_index
        ]
        inferred_missing_read = False
        if not angle_handles:
            inferred = _nearest_previous_angle_sum_output(
                result,
                axis_index=axis_index,
                handle_registry=handle_registry,
            )
            if inferred is not None:
                _, inferred_handle = inferred
                angle_handles = [inferred_handle]
                inferred_missing_read = True
        for angle_handle in angle_handles:
            angle_index = produced_to_step[angle_handle]
            angle_step = result[angle_index]
            if angle_step.recipe_hint != "angle_sum_equal_angle_candidates":
                continue
            if _step_has_point_target(angle_step):
                target_handle = _angle_sum_existing_point_target(angle_step)
                if target_handle is not None:
                    result[angle_index] = _step_with_angle_sum_target(
                        angle_step,
                        target_handle=target_handle,
                        handle_registry=handle_registry,
                    )
                    angle_step = result[angle_index]
            else:
                target_handle = _axis_intercept_target_point_handle(axis_step, handle_registry)
                if target_handle is None:
                    continue
                result[angle_index] = _step_with_angle_sum_target(
                    angle_step,
                    target_handle=target_handle,
                    handle_registry=handle_registry,
                )
                result[axis_index] = _step_with_read(axis_step, target_handle)
                actions.append(
                    StepIntentNormalizationAction(
                        action="infer_angle_sum_target_from_axis_intercept_step",
                        step_id=angle_step.step_id,
                        target_step_id=axis_step.step_id,
                        handle=target_handle,
                        reason=(
                            "后续 axis_intercept step 明确读取当前等角 fact 并输出一个点；"
                            "将 angle_sum step 的 target 补成该轴截点 PointRef。"
                        ),
                    )
                )
                angle_step = result[angle_index]
                axis_step = result[axis_index]
            if target_handle is None:
                continue
            result[axis_index] = _step_without_create(result[axis_index], target_handle)
            axis_step = result[axis_index]
            if inferred_missing_read:
                result[axis_index] = _step_with_read(result[axis_index], angle_handle)
                axis_step = result[axis_index]
                actions.append(
                    StepIntentNormalizationAction(
                        action="link_adjacent_angle_sum_to_axis_intercept_step",
                        step_id=angle_step.step_id,
                        target_step_id=axis_step.step_id,
                        handle=angle_handle,
                        reason=(
                            "相邻 axis_intercept step 未显式读取前序 AngleEquality；"
                            "根据 angle_sum -> axis_intercept 标准链路补齐 reads。"
                        ),
                    )
                )
            result, rewrite_actions = _rewrite_generic_angle_equality_handle(
                result,
                angle_index=angle_index,
                old_handle=angle_handle,
                target_handle=target_handle,
                handle_registry=handle_registry,
            )
            actions.extend(rewrite_actions)
            break

    return tuple(result), actions

def _nearest_previous_angle_sum_output(
    steps: list[StepIntent],
    *,
    axis_index: int,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[int, str] | None:
    """Return the immediately preceding angle_sum step and its unique output."""
    for index in range(axis_index - 1, -1, -1):
        step = steps[index]
        if step.recipe_hint == "angle_sum_equal_angle_candidates":
            handle = _single_angle_equality_output_handle(step, handle_registry)
            return (index, handle) if handle is not None else None
        if step.recipe_hint is not None or step.produces or step.creates:
            return None
    return None

def _single_angle_equality_output_handle(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """Return the single AngleEquality produced handle, if unambiguous."""
    handles = [
        item.handle
        for item in step.produces
        if _produced_output_type(item, handle_registry) == "AngleEquality"
    ]
    if len(handles) != 1:
        return None
    return handles[0]

def _fold_curve_candidate_parameter_internal_sequence_for_scope(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
    """把“候选点逐个代入曲线求参再筛选”折叠回公开 recipe。

    ``curve_candidate_parameter_solve`` 对外就是候选点列表 + 含参曲线 + 参数约束
    选出最终点。LLM 有时会把内部过程展开成“候选1求 b、候选2求 b、再筛选”；
    只要后续没有继续读取这些内部候选产物，就可以确定性收束为 public recipe。
    """
    if len(steps) < 4:
        return steps, []

    result: list[StepIntent] = []
    actions: list[StepIntentNormalizationAction] = []
    read_rewrites: dict[str, tuple[str, ...]] = {}
    index = 0
    while index < len(steps):
        tail = tuple(
            _rewrite_step_reads_many(step, read_rewrites)
            for step in steps[index:]
        )
        folded = _fold_curve_candidate_parameter_sequence(
            tail,
            handle_registry=handle_registry,
        )
        if folded is None:
            result.append(tail[0])
            index += 1
            continue
        candidate_step, folded_step, rewrites, fold_actions, consumed = folded
        result.append(candidate_step)
        result.append(folded_step)
        read_rewrites.update(rewrites)
        actions.extend(fold_actions)
        index += consumed

    return tuple(result), actions

def _fold_curve_candidate_parameter_sequence(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    StepIntent,
    StepIntent,
    dict[str, tuple[str, ...]],
    list[StepIntentNormalizationAction],
    int,
] | None:
    """若开头连续 steps 是候选点求参筛选链路，返回折叠后的两步。"""
    if len(steps) < 4:
        return None
    candidate_step = steps[0]
    candidate_handles = _candidate_step_point_outputs(candidate_step, handle_registry)
    if len(candidate_handles) < 2:
        return None

    solve_steps: list[StepIntent] = []
    used_candidate_reads: set[str] = set()
    cursor = 1
    while cursor < len(steps):
        step = steps[cursor]
        candidate_reads = _candidate_reads_for_step(step, candidate_handles)
        if not _is_curve_candidate_parameter_internal_step(
            step,
            candidate_reads=candidate_reads,
            candidate_step=candidate_step,
            handle_registry=handle_registry,
        ):
            break
        solve_steps.append(step)
        used_candidate_reads.update(candidate_reads)
        cursor += 1

    if len(solve_steps) < 2 or len(used_candidate_reads) < 2 or cursor >= len(steps):
        return None

    select_step = steps[cursor]
    if not _is_curve_candidate_parameter_select_step(
        select_step,
        solve_steps=tuple(solve_steps),
        candidate_step=candidate_step,
        handle_registry=handle_registry,
    ):
        return None

    internal_handles = set(candidate_handles)
    for step in solve_steps:
        internal_handles.update(item.handle for item in step.produces)
    if _later_steps_read_any(steps[cursor + 1:], internal_handles):
        return None

    normalized_candidate, candidate_rewrites, candidate_actions = (
        _normalize_candidate_point_facts_step(
            candidate_step,
            handle_registry=handle_registry,
        )
    )
    point_list_handle = _candidate_step_point_list_output(
        normalized_candidate,
        handle_registry,
    )
    if point_list_handle is None:
        return None

    reads = _unique_read_handles(
        (
            point_list_handle,
            *(
                handle
                for step in solve_steps
                for handle in step.reads
            ),
            *select_step.reads,
        ),
        exclude=internal_handles,
    )
    folded_step = replace(
        select_step,
        recipe_hint="curve_candidate_parameter_solve",
        goal_type=select_step.goal_type or "derive_constructed_point",
        reads=reads,
        creates=select_step.creates,
        produces=select_step.produces,
        strategy=(
            "用候选点列表、当前含参抛物线和参数约束筛选最终点，并反求参数。"
        ),
        reason=(
            "LLM 将 curve_candidate_parameter_solve 展开为逐候选求参和筛选；"
            "系统折叠为一个公开 recipe step。"
        ),
    )
    rewrites = {
        handle: (target,)
        for handle, target in candidate_rewrites.items()
    }
    fold_action = StepIntentNormalizationAction(
        action="fold_curve_candidate_parameter_internal_sequence",
        step_id=candidate_step.step_id,
        target_step_id=select_step.step_id,
        handle=",".join(sorted(internal_handles)),
        reason=(
            "连续的候选点生成 / 多个 parameter_from_curve_point_on_quadratic / "
            "最终筛选 step 是 curve_candidate_parameter_solve 的内部展开，折叠为公开 recipe。"
        ),
    )
    return (
        normalized_candidate,
        folded_step,
        rewrites,
        [*candidate_actions, fold_action],
        cursor + 1,
    )

def _candidate_step_point_outputs(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """读取候选生成 step 中拆散的候选点输出。"""
    if not step.recipe_hint or "candidate" not in step.recipe_hint.lower():
        return ()
    return tuple(
        item.handle for item in step.produces
        if _produced_output_type(item, handle_registry) == "Point"
    )

def _candidate_step_point_list_output(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """读取候选生成 step 归一化后的 PointList 输出。"""
    candidates = [
        item.handle for item in step.produces
        if _produced_output_type(item, handle_registry) == "PointList"
    ]
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None

def _candidate_reads_for_step(
    step: StepIntent,
    candidate_handles: tuple[str, ...],
) -> tuple[str, ...]:
    """返回当前 step 读取的候选点 handle。"""
    candidate_set = set(candidate_handles)
    return tuple(handle for handle in step.reads if handle in candidate_set)

def _is_curve_candidate_parameter_internal_step(
    step: StepIntent,
    *,
    candidate_reads: tuple[str, ...],
    candidate_step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否是 recipe 内部的“某个候选点代入曲线求参”。"""
    if step.scope_id != candidate_step.scope_id:
        return False
    if step.recipe_hint != "parameter_from_curve_point_on_quadratic":
        return False
    if len(candidate_reads) != 1:
        return False
    produced_types = {
        _produced_output_type(item, handle_registry)
        for item in step.produces
    }
    if "ParameterValue" not in produced_types:
        return False
    return any(
        _reads_parabola_like_handle(handle, handle_registry)
        for handle in step.reads
    )

def _is_curve_candidate_parameter_select_step(
    step: StepIntent,
    *,
    solve_steps: tuple[StepIntent, ...],
    candidate_step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否是在多候选求参后选择最终点。"""
    if step.scope_id != candidate_step.scope_id:
        return False
    if step.recipe_hint not in {None, "select_point_by_quadrant_constraint"}:
        return False
    produced_types = {
        _produced_output_type(item, handle_registry)
        for item in step.produces
    }
    if "Point" not in produced_types:
        return False

    parameter_handles = {
        item.handle
        for solve_step in solve_steps
        for item in solve_step.produces
        if _produced_output_type(item, handle_registry) == "ParameterValue"
    }
    solved_point_handles = {
        item.handle
        for solve_step in solve_steps
        for item in solve_step.produces
        if _produced_output_type(item, handle_registry) == "Point"
    }
    reads = set(step.reads)
    return bool(reads & parameter_handles) and bool(reads & solved_point_handles)

def _reads_parabola_like_handle(
    handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 read 是否提供抛物线/二次函数状态。"""
    if handle_registry.fact_types.get(handle) == "parabola":
        return True
    if handle.startswith("answer:") and handle_registry.answer_value_types.get(handle) == "Parabola":
        return True
    semantic = _semantic_name(handle).lower() if handle.startswith("fact:") else handle.lower()
    return "parabola" in semantic and "coefficient" not in semantic

def _later_steps_read_any(
    steps: tuple[StepIntent, ...],
    handles: set[str],
) -> bool:
    """若后续仍读取内部候选产物，则不能安全折叠。"""
    if not handles:
        return False
    return any(handle in handles for step in steps for handle in step.reads)

def _normalize_quadratic_from_constraints_step(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, dict[str, str], list[StepIntentNormalizationAction]]:
    """把二次函数化简 step 的 utility fact 归一化成当前问抛物线 fact。

    DeepSeek 常把 ``quadratic_from_constraints`` 的产物写成 ``c_expr_in_b``。
    执行层真正需要的是当前问的含参抛物线，而不是把 ``c=...`` 当成独立 fact。
    若 hint 已经明确为 ``quadratic_from_constraints``，或 LLM 错把这类二次函数
    化简 step 标成空 hint / 参数求解 hint，但 produces 明显是系数关系 utility，
    都可以归一化成当前问的含参抛物线。

    这是 LLM 合并 internal method 输出的兼容层；长期应把这类 fold 下沉到
    recipe/compiler metadata 的 declared sub-steps。这里必须保留 recipe/goal/output
    contract guard，避免把合法的独立 Equation/Relation fact 误归并成抛物线。
    """
    if not _step_can_normalize_quadratic_utility(
        step,
        handle_registry=handle_registry,
    ):
        return step, {}, []

    parabola_items = [
        item for item in step.produces
        if _produced_name_suggests_parabola(item)
    ]
    corrected_items: list[ProducedFact] = []
    type_actions: list[StepIntentNormalizationAction] = []
    for item in parabola_items:
        if item.output_type == "Parabola":
            corrected_items.append(item)
            continue
        if item.output_type not in {None, "Equation", "Expression"}:
            corrected_items.append(item)
            continue
        corrected_items.append(replace(item, output_type="Parabola"))
        type_actions.append(
            StepIntentNormalizationAction(
                action="normalize_parabola_equation_output_type",
                step_id=step.step_id,
                handle=item.handle,
                target_step_id=None,
                reason=(
                    "quadratic_from_constraints 产出的抛物线解析式缺少类型或被标成 Equation/Expression；"
                    "根据 handle/goal/recipe 语义修正为 Parabola。"
                ),
            )
        )
    if type_actions:
        by_handle = {item.handle: item for item in corrected_items}
        new_produces = tuple(by_handle.get(item.handle, item) for item in step.produces)
        step = replace(step, produces=new_produces)
        parabola_items = [
            item for item in step.produces
            if _produced_name_suggests_parabola(item)
        ]
    utility_detector = (
        _produced_name_suggests_quadratic_alias_utility
        if parabola_items
        else _produced_name_suggests_quadratic_utility
    )
    utility_items = [
        item for item in step.produces
        if item not in parabola_items
        and utility_detector(
            item,
            step=step,
            handle_registry=handle_registry,
        )
    ]
    if not utility_items:
        return step, {}, type_actions
    folded_items = _quadratic_utility_fold_items(
        step.produces,
        parabola_items=tuple(parabola_items),
        utility_items=tuple(utility_items),
        handle_registry=handle_registry,
    )

    target_handle = (
        parabola_items[0].handle
        if parabola_items
        else f"fact:{step.scope_id}:parametric_parabola"
    )
    target_item = (
        parabola_items[0]
        if parabola_items
        else ProducedFact(
            handle=target_handle,
            valid_scope=step.scope_id,
            description="当前问由 quadratic_from_constraints 化简得到的含参抛物线",
            output_type="Parabola",
        )
    )
    rewrites = {item.handle: target_handle for item in folded_items}
    new_produces = tuple(item for item in step.produces if item in parabola_items)
    if target_item not in new_produces:
        new_produces = (*new_produces, target_item)
    retained_items = tuple(
        item
        for item in step.produces
        if item not in parabola_items and item not in folded_items
    )
    new_produces = (*new_produces, *retained_items)
    actions = type_actions + [
        StepIntentNormalizationAction(
            action="normalize_quadratic_utility_fact_to_parabola",
            step_id=step.step_id,
            handle=item.handle,
            target_step_id=None,
            reason=(
                "quadratic_from_constraints 输出执行层需要的当前问抛物线；"
                f"将 utility fact {item.handle} 归一化为 {target_handle}。"
            ),
        )
        for item in folded_items
    ]
    return (
        replace(
            step,
            recipe_hint="quadratic_from_constraints",
            target=rewrites.get(step.target, step.target),
            produces=new_produces,
        ),
        rewrites,
        actions,
    )


def _quadratic_utility_fold_items(
    produces: tuple[ProducedFact, ...],
    *,
    parabola_items: tuple[ProducedFact, ...],
    utility_items: tuple[ProducedFact, ...],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[ProducedFact, ...]:
    """Return fact outputs that must alias the normalized Parabola state.

    Once a quadratic simplification step is folded to the executable
    ``quadratic_from_constraints`` contract, stray Expression/Equation facts
    emitted by the same step cannot remain standalone runtime outputs.  They
    are aliases of the Parabola/Coefficients state and must get an explicit
    rewrite instead of being silently dropped.
    """
    result: list[ProducedFact] = []
    seen: set[str] = set()
    for item in (*utility_items, *produces):
        if (
            item in parabola_items
            or item.handle in seen
            or not item.handle.startswith("fact:")
        ):
            continue
        output_type = _produced_output_type(item, handle_registry)
        if item in utility_items or output_type in {
            None,
            "Coefficients",
            "Equation",
            "Expression",
        }:
            seen.add(item.handle)
            result.append(item)
    return tuple(result)


def _split_mixed_quadratic_outputs_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """把 quadratic_from_constraints 中混入的参数值/点坐标输出拆出。

    DeepSeek 在真实首轮里容易把“由长度求 m、代入 m 求 M/N 坐标、再求抛物线”
    合并成一个 ``quadratic_from_constraints`` step。runtime 的 method 颗粒度更细：
    参数值应由 ``parameter_from_segment_length`` 产生，点坐标代入应由
    ``evaluate_point_at_parameter`` 产生，当前 step 只保留 Parabola/Coefficients。
    """
    if step.recipe_hint != "quadratic_from_constraints":
        return step, []
    if not step.produces:
        return step, []

    output_types = {
        item.handle: _normalizer_output_type(item, context)
        for item in step.produces
    }
    parabola_items = [
        item for item in step.produces
        if output_types[item.handle] == "Parabola"
    ]
    if not parabola_items:
        return step, []

    extra_items = [
        item for item in step.produces
        if output_types[item.handle] not in {"Parabola", "Coefficients"}
    ]
    if not extra_items:
        return step, []
    if any(output_types[item.handle] not in {"ParameterValue", "Point"} for item in extra_items):
        return step, []

    parameter_item = _primary_parameter_output_item(extra_items, context=context)
    parameter_handle = _parameter_value_read_for_mixed_quadratic(step, context)
    parameter_step: StepIntent | None = None
    if parameter_item is not None and parameter_handle is None:
        parameter_recipe_hint = _parameter_recipe_hint_for_mixed_quadratic(
            step,
            context.handle_registry,
        )
        if parameter_recipe_hint is None:
            return step, []
        parameter_handle = parameter_item.handle
        parameter_step = _mixed_quadratic_parameter_step(
            step,
            parameter_item=parameter_item,
            recipe_hint=parameter_recipe_hint,
            context=context,
        )

    point_steps: list[StepIntent] = []
    point_items = [
        item for item in extra_items
        if output_types[item.handle] == "Point"
    ]
    if point_items:
        if parameter_handle is None:
            return step, []
        for item in point_items:
            source = _source_point_read_for_mixed_quadratic_point(
                item,
                step=step,
                context=context,
            )
            if source is None:
                return step, []
            point_steps.append(
                _mixed_quadratic_point_evaluation_step(
                    step,
                    point_item=item,
                    source_handle=source,
                    parameter_handle=parameter_handle,
                    context=context,
                )
            )

    retained_produces = tuple(
        item for item in step.produces
        if output_types[item.handle] in {"Parabola", "Coefficients"}
    )
    if len(retained_produces) == len(step.produces):
        return step, []

    actions: list[StepIntentNormalizationAction] = []
    if parameter_step is not None:
        _append_generated_normalized_step(context, parameter_step)
        actions.append(
            StepIntentNormalizationAction(
                action="split_mixed_quadratic_parameter_step",
                step_id=step.step_id,
                handle=parameter_item.handle if parameter_item is not None else parameter_handle,
                target_step_id=parameter_step.step_id,
                reason=(
                    "quadratic_from_constraints 同时产出运行参数值；"
                    f"将参数求解拆为 {parameter_step.recipe_hint} 前置 step。"
                ),
            )
        )
    for point_step in point_steps:
        _append_generated_normalized_step(context, point_step)
        actions.append(
            StepIntentNormalizationAction(
                action="split_mixed_quadratic_point_evaluation",
                step_id=step.step_id,
                handle=point_step.produces[0].handle,
                target_step_id=point_step.step_id,
                reason=(
                    "quadratic_from_constraints 同时产出代入参数后的点坐标；"
                    "将点坐标代入拆为 evaluate_point_at_parameter 前置 step。"
                ),
            )
        )

    for item in extra_items:
        if output_types[item.handle] == "ParameterValue" and (
            parameter_item is None or item.handle != parameter_item.handle
        ):
            actions.append(
                StepIntentNormalizationAction(
                    action="drop_quadratic_coefficient_value_alias",
                    step_id=step.step_id,
                    handle=item.handle,
                    target_step_id=None,
                    reason=(
                        "quadratic_from_constraints 的 a/b/c 系数值属于 coefficients "
                        "伴随输出，不作为独立 ParameterValue capability output。"
                    ),
                )
            )

    reads = step.reads
    if parameter_handle is not None:
        reads = _append_unique(reads, (parameter_handle,))
    retained_handles = {item.handle for item in retained_produces}
    target = step.target if step.target in retained_handles else parabola_items[0].handle
    return (
        replace(
            step,
            target=target,
            reads=reads,
            produces=retained_produces,
        ),
        actions,
    )

def _normalize_parameter_solver_outputs_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """参数求解 method 只保留运行参数值，不承载 a/b/c 系数别名。

    LLM 有时把“由长度/表达式求运行参数”和“后续由 constraints 求二次函数系数”
    合并到同一个 parameter solver step，例如同时 produces ``m_value`` 与
    ``a_value``。执行层的 ``parameter_from_*`` method 只有一个语义输出：
    题目运行参数。二次函数系数应由 ``quadratic_from_constraints`` 的
    Coefficients/Parabola 输出表达。
    """
    if not _is_parameter_solver_hint(step.recipe_hint):
        return step, []
    if len(step.produces) < 2:
        return step, []

    output_types = {
        item.handle: _normalizer_output_type(item, context)
        for item in step.produces
    }
    if any(output_types[item.handle] != "ParameterValue" for item in step.produces):
        return step, []

    runtime_items = [
        item for item in step.produces
        if _is_runtime_parameter_value_name(_semantic_name(item.handle).lower())
    ]
    if len(runtime_items) != 1:
        return step, []

    retained = runtime_items[0]
    dropped = tuple(item for item in step.produces if item.handle != retained.handle)
    if not dropped:
        return step, []

    actions = [
        StepIntentNormalizationAction(
            action="drop_parameter_solver_coefficient_value_alias",
            step_id=step.step_id,
            handle=item.handle,
            target_step_id=None,
            reason=(
                f"{step.recipe_hint} 只产出题目运行参数值；"
                "a/b/c 等二次函数系数值属于 quadratic_from_constraints 的"
                "系数状态，不作为独立 ParameterValue 输出。"
            ),
        )
        for item in dropped
    ]
    target = step.target if step.target == retained.handle else retained.handle
    return replace(step, target=target, produces=(retained,)), actions

def _normalizer_output_type(
    item: ProducedFact,
    context: NormalizationRuleContext,
) -> str | None:
    """读取 produced item 的有效 output_type。"""
    return _produced_output_type(item, context.handle_registry) or item.output_type

def _primary_parameter_output_item(
    items: list[ProducedFact],
    *,
    context: NormalizationRuleContext,
) -> ProducedFact | None:
    """从 mixed quadratic outputs 中找运行参数值，而不是 a/b/c 系数值。"""
    for item in items:
        if _normalizer_output_type(item, context) != "ParameterValue":
            continue
        if _is_runtime_parameter_value_name(_semantic_name(item.handle).lower()):
            return item
    return None

def _is_parameter_solver_hint(recipe_hint: str | None) -> bool:
    """判断 step 是否使用参数求解类 method。"""
    if recipe_hint is None:
        return False
    return recipe_hint.startswith("parameter_from_")

def _is_runtime_parameter_value_name(name: str) -> bool:
    """判断 ``*_value`` 是否表示题目运行参数，而非二次函数系数。"""
    if name == "parameter_value":
        return True
    match = re.fullmatch(r"(?P<symbol>[a-z])_value", name)
    return match is not None and match.group("symbol") not in {"a", "b", "c", "x", "y"}

def _parameter_value_read_for_mixed_quadratic(
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    """从 reads 中找已由前序 step 产生的运行参数值。"""
    for handle in step.reads:
        if not handle.startswith("fact:"):
            continue
        if not _is_runtime_parameter_value_name(_semantic_name(handle).lower()):
            continue
        if _known_produced_output_type(handle, context) == "ParameterValue":
            return handle
    return None

def _known_produced_output_type(
    handle: str,
    context: NormalizationRuleContext,
) -> str | None:
    """读取前序 dynamic output 的类型；题面 symbol_value 不视为运行参数值。"""
    for step in context.previous_steps:
        for item in step.produces:
            if item.handle == handle:
                return item.output_type
    for scope in context.normalized_scopes:
        for step in scope.steps:
            for item in step.produces:
                if item.handle == handle:
                    return item.output_type
    return None

def _step_reads_length_condition(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否读取长度类条件。"""
    return any(
        handle_registry.fact_types.get(handle) in {"length_squared", "segment_length_relation"}
        for handle in step.reads
    )

def _parameter_recipe_hint_for_mixed_quadratic(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """根据条件类型选择 mixed quadratic 参数求解 method。"""
    if _step_reads_length_condition(step, handle_registry):
        return "parameter_from_segment_length"
    if (
        _step_reads_minimum_expression(step, handle_registry)
        and _step_reads_given_minimum_value(step, handle_registry)
    ):
        return "parameter_from_minimum_value"
    return None

def _step_reads_minimum_expression(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否读取了可用于反求参数的最小值表达式。"""
    for handle in step.reads:
        if handle.startswith("answer:"):
            if handle_registry.answer_value_types.get(handle) == "MinimumExpression":
                return True
            continue
        fact_type = handle_registry.fact_types.get(handle, "")
        if fact_type in {"minimum_expression", "minimum_value_expression"}:
            return True
        name = _semantic_name(handle).lower()
        if "given" in name:
            continue
        if "minimum" in name and ("expr" in name or "expression" in name):
            return True
    return False

def _step_reads_given_minimum_value(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否读取题设给定的最小值事实。"""
    for handle in step.reads:
        if handle.startswith("answer:"):
            continue
        fact_type = handle_registry.fact_types.get(handle, "")
        name = _semantic_name(handle).lower()
        if fact_type == "minimum_value":
            return True
        if "minimum" in name and ("given" in name or "value_given" in name):
            return True
    return False

def _mixed_quadratic_parameter_step(
    step: StepIntent,
    *,
    parameter_item: ProducedFact,
    recipe_hint: str,
    context: NormalizationRuleContext,
) -> StepIntent:
    """为 mixed quadratic step 生成前置参数求解 step。"""
    goal_type_by_hint = {
        "parameter_from_segment_length": "derive_parameter",
        "parameter_from_minimum_value": "derive_parameter_from_minimum_value",
        "parameter_from_expression_value": "derive_parameter_from_expression_value",
    }
    return StepIntent(
        scope_id=step.scope_id,
        step_id=_unique_generated_step_id(f"{step.step_id}_solve_parameter", context),
        recipe_hint=recipe_hint,
        goal_type=goal_type_by_hint.get(recipe_hint, "derive_parameter"),
        target=parameter_item.handle,
        strategy="由当前条件先求运行参数，再交给后续抛物线求解使用。",
        reads=step.reads,
        creates=(),
        produces=(parameter_item,),
        reason="原 quadratic_from_constraints step 同时承担参数求解；拆出为可执行参数 step。",
    )

def _source_point_read_for_mixed_quadratic_point(
    item: ProducedFact,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    """为 ``M_numeric_coordinate`` 这类输出找到含参源点坐标 read。"""
    point_name = _point_name_from_coordinate_fact(item.handle)
    if point_name is None:
        return None
    for handle in step.reads:
        if _point_coordinate_read_name(handle) == point_name:
            return handle
    for handle in step.reads:
        if handle.startswith("point:") and _handle_name(handle) == point_name:
            return handle
    return _visible_point_coordinate_fact_read(point_name, step.scope_id, context)

def _point_coordinate_read_name(handle: str) -> str | None:
    """从 point coordinate fact read 中提取点名。"""
    if not handle.startswith("fact:"):
        return None
    name = _semantic_name(handle)
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9]*)_"
        r"(?:(?:param|parametric|parameterized)_(?:coord|coordinate)"
        r"|(?:coord|coordinate))(?:_[A-Za-z0-9_]+)?",
        name,
        flags=re.IGNORECASE,
    )
    if match is not None:
        return match.group("point")
    if "_coordinate" not in name:
        return None
    return name.split("_coordinate", 1)[0].removesuffix("_numeric")

def _visible_point_coordinate_fact_read(
    point_name: str,
    scope_id: str,
    context: NormalizationRuleContext,
) -> str | None:
    """在当前可见范围里找已发布的点坐标 fact。"""
    visible_scopes = set(context.handle_registry.ancestor_scopes(scope_id))
    candidates: list[str] = []
    for handle in context.handle_registry.fact_handles:
        if context.handle_registry.handle_valid_scopes.get(handle) not in visible_scopes:
            continue
        if _point_coordinate_read_name(handle) == point_name:
            candidates.append(handle)
    for scope in context.normalized_scopes:
        for previous in scope.steps:
            for produced in previous.produces:
                if produced.valid_scope not in visible_scopes:
                    continue
                if _point_coordinate_read_name(produced.handle) == point_name:
                    candidates.append(produced.handle)
    for previous in context.previous_steps:
        for produced in previous.produces:
            if produced.valid_scope not in visible_scopes:
                continue
            if _point_coordinate_read_name(produced.handle) == point_name:
                candidates.append(produced.handle)
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None

def _mixed_quadratic_point_evaluation_step(
    step: StepIntent,
    *,
    point_item: ProducedFact,
    source_handle: str,
    parameter_handle: str,
    context: NormalizationRuleContext,
) -> StepIntent:
    """为 mixed quadratic step 生成前置点坐标代入 step。"""
    point_name = _point_name_from_coordinate_fact(point_item.handle) or "point"
    step_id = _unique_generated_step_id(
        f"{step.step_id}_evaluate_{point_name.lower()}_coordinate",
        context,
    )
    return StepIntent(
        scope_id=step.scope_id,
        step_id=step_id,
        recipe_hint="evaluate_point_at_parameter",
        goal_type="evaluate_point_at_parameter",
        target=point_item.handle,
        strategy="把已求出的运行参数代入含参点坐标。",
        reads=_append_unique((source_handle,), (parameter_handle,)),
        creates=(),
        produces=(point_item,),
        reason="原 quadratic_from_constraints step 混入点坐标代入；拆出为可执行点坐标 step。",
    )

def _split_multi_point_evaluation_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[bool, list[StepIntentNormalizationAction]]:
    """拆分 ``evaluate_point_at_parameter`` 的多点输出。

    ``evaluate_point_at_parameter`` 是单输入、单输出 method。LLM 有时会把
    “把同一个参数值分别代入多个点”写成一个 step；若不拆分，compiler 会把多个
    produced fact alias 到同一个 runtime output，后续曲线点约束会退化。
    """
    if step.recipe_hint != "evaluate_point_at_parameter":
        return True, []
    if len(step.produces) < 2:
        return True, []
    point_items = [
        item for item in step.produces
        if _normalizer_output_type(item, context) == "Point"
    ]
    if len(point_items) != len(step.produces):
        return True, []
    if any(item.handle.startswith("answer:") for item in point_items):
        return True, []

    point_names = tuple(_point_name_from_coordinate_fact(item.handle) for item in point_items)
    if any(name is None for name in point_names):
        return True, []
    if len(set(point_names)) < 2:
        return True, []

    parameter_handle = _parameter_value_read_for_mixed_quadratic(step, context)
    if parameter_handle is None:
        return True, []

    split_steps: list[StepIntent] = []
    for item in point_items:
        source = _source_point_read_for_mixed_quadratic_point(
            item,
            step=step,
            context=context,
        )
        if source is None:
            return True, []
        split_steps.append(
            replace(
                _mixed_quadratic_point_evaluation_step(
                    step,
                    point_item=item,
                    source_handle=source,
                    parameter_handle=parameter_handle,
                    context=context,
                ),
                strategy="把已求出的运行参数分别代入对应的含参点坐标。",
                reason=(
                    "原 evaluate_point_at_parameter step 同时产出多个点坐标；"
                    "拆成多个单点代入 step，避免多个 produced fact 绑定到同一个 runtime output。"
                ),
            )
        )

    actions: list[StepIntentNormalizationAction] = []
    for split_step in split_steps:
        _append_generated_normalized_step(context, split_step)
        actions.append(
            StepIntentNormalizationAction(
                action="split_multi_point_evaluation_step",
                step_id=step.step_id,
                handle=split_step.produces[0].handle,
                target_step_id=split_step.step_id,
                reason=(
                    "evaluate_point_at_parameter 是单点代入 method；"
                    "将多点 produces 拆成一组单点代入 step。"
                ),
            )
        )
    return False, actions

def _append_generated_normalized_step(
    context: NormalizationRuleContext,
    step: StepIntent,
) -> None:
    """把 synthetic step 追加到当前 scope，并注册为后续可读 output。"""
    context.previous_steps.append(step)
    _register_published_outputs(
        context,
        step,
        step_index=len(context.previous_steps) - 1,
    )

def _unique_generated_step_id(
    base: str,
    context: NormalizationRuleContext,
) -> str:
    """生成当前 scope 内不冲突的 synthetic step_id。"""
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_").lower()
    if not normalized:
        normalized = "generated_step"
    existing = {step.step_id for step in context.previous_steps}
    if normalized not in existing:
        return normalized
    suffix = 2
    while f"{normalized}_{suffix}" in existing:
        suffix += 1
    return f"{normalized}_{suffix}"

def _step_can_normalize_quadratic_utility(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否可视作 quadratic_from_constraints 的化简动作。"""
    if step.recipe_hint == "quadratic_from_constraints":
        return True
    if step.recipe_hint not in {None, "parameter_from_expression_value"}:
        return False
    if not any(
        _produced_name_suggests_quadratic_utility(
            item,
            step=step,
            handle_registry=handle_registry,
        )
        for item in step.produces
    ):
        return False
    return any(
        handle == "function:problem:parabola"
        or handle.startswith("function:")
        or "on_parabola" in handle
        or handle.endswith("_on_curve")
        for handle in step.reads
    )

def _normalize_candidate_point_facts_step(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, dict[str, str], list[StepIntentNormalizationAction]]:
    """把同一步拆散的多个候选点坐标 fact 合并成候选列表 fact。

    规则只看 capability 语义和输出类型：当 LLM 明确选择候选生成类 capability，
    且所有 produces 都是非 answer 的点坐标时，这些点坐标应作为一个
    ``PointList`` 输出进入后续筛选，而不是多个独立 Point 输出。
    """
    if not step.recipe_hint or "candidate" not in step.recipe_hint.lower():
        return step, {}, []
    if len(step.produces) < 2:
        return step, {}, []
    if any(item.handle.startswith("answer:") for item in step.produces):
        return step, {}, []
    point_items = [
        item for item in step.produces
        if _produced_output_type(item, handle_registry) == "Point"
    ]
    if len(point_items) != len(step.produces):
        return step, {}, []

    target_name = _candidate_point_base_name(point_items)
    semantic_name = f"{target_name}_candidates" if target_name else "point_candidates"
    target_handle = f"fact:{step.scope_id}:{semantic_name}"
    target_item = ProducedFact(
        handle=target_handle,
        valid_scope=step.scope_id,
        description="当前候选生成 step 输出的候选点列表",
    )
    rewrites = {item.handle: target_handle for item in point_items}
    dropped_creates = _candidate_point_create_handles(step, point_items)
    creates = tuple(
        created for created in step.creates
        if created.handle not in dropped_creates
    )
    actions = [
        StepIntentNormalizationAction(
            action="normalize_candidate_point_facts_to_point_list",
            step_id=step.step_id,
            handle=item.handle,
            target_step_id=None,
            reason=(
                "候选生成 method 输出的是 PointList；将拆散的候选点坐标 fact "
                f"{item.handle} 合并到 {target_handle}。"
            ),
        )
        for item in point_items
    ]
    actions.extend(
        StepIntentNormalizationAction(
            action="drop_internal_candidate_point_create",
            step_id=step.step_id,
            handle=handle,
            target_step_id=None,
            reason=(
                "候选生成 step 已归一化为 PointList 输出；单个候选点实体是 recipe "
                "内部细节，删除 creates 以匹配公开 capability 边界。"
            ),
        )
        for handle in sorted(dropped_creates)
    )
    return replace(step, creates=creates, produces=(target_item,)), rewrites, actions

def _normalize_point_answer_coordinate_step(
    step: StepIntent,
    *,
    question_goal_map: dict[str, QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, dict[str, str], list[StepIntentNormalizationAction]]:
    """用同 step 的 Point answer 目标点名归一化泛化坐标 fact。

    LLM 有时写 ``axis_point_coordinate`` 这类角色名，而 runtime 需要真实点名。
    如果同一步只有一个 Point answer，则 QuestionGoal.target_path 已经给出了唯一
    目标点名，可以安全归一化；否则不猜。
    """
    point_answer_goals = [
        question_goal_map[item.handle]
        for item in step.produces
        if item.handle in question_goal_map and question_goal_map[item.handle].value_type == "Point"
    ]
    if len(point_answer_goals) != 1:
        return step, {}, []
    point_name = _point_name_from_goal_target(point_answer_goals[0])
    if point_name is None:
        return step, {}, []

    rewrites: dict[str, str] = {}
    actions: list[StepIntentNormalizationAction] = []
    new_produces: list[ProducedFact] = []
    for item in step.produces:
        if item.handle.startswith("answer:") or _produced_output_type(item, handle_registry) != "Point":
            new_produces.append(item)
            continue
        semantic_name = _semantic_name(item.handle)
        if _is_specific_point_coordinate_name(semantic_name, point_name):
            new_produces.append(item)
            continue
        if not _is_generic_point_coordinate_name(semantic_name):
            new_produces.append(item)
            continue
        target_handle = f"fact:{item.valid_scope}:{point_name}_coordinate_value"
        rewrites[item.handle] = target_handle
        normalized_item = ProducedFact(
            handle=target_handle,
            valid_scope=item.valid_scope,
            description=item.description,
        )
        if normalized_item not in new_produces:
            new_produces.append(normalized_item)
        actions.append(
            StepIntentNormalizationAction(
                action="normalize_point_coordinate_answer_fact",
                step_id=step.step_id,
                handle=item.handle,
                target_step_id=None,
                reason=(
                    "同一步只有一个 Point answer；使用 QuestionGoal target_path "
                    f"确定真实点名，将 {item.handle} 归一化为 {target_handle}。"
                ),
            )
        )
    if not rewrites:
        return step, {}, []
    return replace(step, produces=tuple(new_produces)), rewrites, actions

def _normalize_axis_point_alias_step(
    step: StepIntent,
    *,
    previous_steps: list[StepIntent],
    question_goal_map: dict[str, QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, dict[str, str], list[StepIntentNormalizationAction], bool, int | None]:
    """归一化 axis point answer 的可复用坐标 alias。

    ``quadratic_axis_from_relation`` 稳定只输出一个 Point。LLM 常把这个输出同时
    写成最终 answer 和后续可复用 fact，或下一步再单独产生公共坐标 fact。两者都
    应视为同一 method output 的语义 alias，而不是新的 executable step。
    """
    if step.recipe_hint != "quadratic_axis_from_relation":
        return step, {}, [], True, None
    axis_goal = _single_point_answer_goal(step, question_goal_map)
    merge_target_index: int | None = None
    point_name: str | None = None
    point_scope: str | None = None
    if axis_goal is not None:
        point_name = _point_name_from_goal_target(axis_goal)
        point_scope = _point_scope_from_goal_target(axis_goal)
    if point_name is None:
        prior = _previous_axis_answer_step_for_fact(step, previous_steps, question_goal_map)
        if prior is None:
            return step, {}, [], True, None
        merge_target_index, point_name, point_scope = prior
    if point_name is None or point_scope is None:
        return step, {}, [], True, None

    canonical_handle = f"fact:{point_scope}:{point_name}_coordinate"
    rewrites: dict[str, str] = {}
    actions: list[StepIntentNormalizationAction] = []
    new_produces: list[ProducedFact] = []
    for item in step.produces:
        if item.handle.startswith("answer:"):
            new_produces.append(item)
            continue
        if _produced_output_type(item, handle_registry) != "Point":
            new_produces.append(item)
            continue
        item_point_name = _point_name_from_coordinate_fact(item.handle)
        if item_point_name != point_name and not _is_generic_point_coordinate_name(_semantic_name(item.handle)):
            new_produces.append(item)
            continue
        rewrites[item.handle] = canonical_handle
        normalized_item = ProducedFact(
            handle=canonical_handle,
            valid_scope="problem",
            description=item.description,
            output_type="Point",
        )
        if normalized_item.handle not in {existing.handle for existing in new_produces}:
            new_produces.append(normalized_item)
        actions.append(
            StepIntentNormalizationAction(
                action="normalize_axis_point_alias_fact",
                step_id=step.step_id,
                handle=item.handle,
                target_step_id=(
                    previous_steps[merge_target_index].step_id
                    if merge_target_index is not None
                    else None
                ),
                reason=(
                    "quadratic_axis_from_relation 的 Point 输出可同时作为 answer 和"
                    f"可复用坐标 fact；将 {item.handle} 归一化为 {canonical_handle}。"
                ),
            )
        )
    if not rewrites:
        return step, {}, [], True, None
    normalized = replace(
        step,
        target=rewrites.get(step.target, step.target),
        produces=tuple(new_produces),
    )
    # 如果当前 step 只是为前序 axis answer 重复产生同一个坐标 fact，则删除当前 step，
    # 并把 alias 合并到前序 step。
    append_step = not (
        merge_target_index is not None
        and all(item.handle == canonical_handle for item in normalized.produces)
    )
    return normalized, rewrites, actions, append_step, merge_target_index

def _merge_point_answer_alias_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[bool, list[StepIntentNormalizationAction]]:
    """把“读取已有点状态并产出最终 Point answer”的裸 step 合并到源 step。

    LLM 经常把最终答案写成一个 ``recipe_hint=null`` 的收口 step。若该答案的
    target_path 指向的点，已经由前序可见 Point 坐标状态唯一表达，则这个 step
    不需要进入 candidate resolver；它只是给已有状态加一个 answer alias。
    """
    if step.recipe_hint is not None or step.creates:
        return True, []
    if len(step.produces) != 1:
        return True, []
    answer = step.produces[0]
    goal = context.question_goal_map.get(answer.handle)
    if goal is None or goal.value_type != "Point":
        return True, []
    point_name = _point_name_from_goal_target(goal)
    if point_name is None:
        return True, []
    source = _point_answer_alias_source(
        point_name,
        step=step,
        context=context,
    )
    if source is None:
        return True, []
    source_scope_index, source_step_index, source_step, source_handle = source
    answer_item = ProducedFact(
        handle=answer.handle,
        valid_scope=answer.valid_scope,
        description=answer.description,
        output_type=answer.output_type or goal.value_type,
    )
    merged = replace(
        source_step,
        produces=_append_unique_produces(source_step.produces, (answer_item,)),
    )
    _replace_normalized_step(
        context,
        scope_index=source_scope_index,
        step_index=source_step_index,
        step=merged,
    )
    return False, [
        StepIntentNormalizationAction(
            action="merge_point_answer_alias_to_existing_state",
            step_id=step.step_id,
            target_step_id=source_step.step_id,
            handle=answer.handle,
            reason=(
                f"{answer.handle} 是点 {point_name} 的最终 answer；"
                f"前序可见状态 {source_handle} 已经表达同一点坐标，"
                "将 answer alias 合并到该 step，避免裸 Point answer 进入 resolver。"
            ),
        )
    ]

def _point_answer_alias_source(
    point_name: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> tuple[int, int, StepIntent, str] | None:
    """查找可合并 Point answer 的唯一前序坐标状态。"""
    candidates: list[tuple[int, int, StepIntent, str]] = []
    for scope_index, scope in enumerate(context.normalized_scopes):
        for step_index, previous in enumerate(scope.steps):
            _extend_point_answer_alias_candidates(
                candidates,
                scope_index=scope_index,
                step_index=step_index,
                previous=previous,
                point_name=point_name,
                current_step=step,
                context=context,
            )
    for step_index, previous in enumerate(context.previous_steps):
        _extend_point_answer_alias_candidates(
            candidates,
            scope_index=context.current_scope_index,
            step_index=step_index,
            previous=previous,
            point_name=point_name,
            current_step=step,
            context=context,
        )
    if not candidates:
        return None
    read_candidates = [
        candidate for candidate in candidates
        if candidate[3] in step.reads
    ]
    unique = _unique_point_answer_alias_candidates(read_candidates or candidates)
    return unique[0] if len(unique) == 1 else None

def _extend_point_answer_alias_candidates(
    candidates: list[tuple[int, int, StepIntent, str]],
    *,
    scope_index: int,
    step_index: int,
    previous: StepIntent,
    point_name: str,
    current_step: StepIntent,
    context: NormalizationRuleContext,
) -> None:
    for item in previous.produces:
        if _produced_output_type(item, context.handle_registry) != "Point":
            continue
        if _point_name_from_coordinate_fact(item.handle) != point_name:
            continue
        if not _valid_scope_visible_from(
            item.valid_scope,
            current_step.scope_id,
            context.handle_registry,
        ):
            continue
        candidates.append((scope_index, step_index, previous, item.handle))

def _unique_point_answer_alias_candidates(
    candidates: list[tuple[int, int, StepIntent, str]],
) -> tuple[tuple[int, int, StepIntent, str], ...]:
    result: list[tuple[int, int, StepIntent, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        handle = candidate[3]
        if handle in seen:
            continue
        seen.add(handle)
        result.append(candidate)
    return tuple(result)

def _replace_normalized_step(
    context: NormalizationRuleContext,
    *,
    scope_index: int,
    step_index: int,
    step: StepIntent,
) -> None:
    """替换当前或已完成 scope 中的 normalized step。"""
    if scope_index == context.current_scope_index:
        context.previous_steps[step_index] = step
        return
    scope = context.normalized_scopes[scope_index]
    steps = list(scope.steps)
    steps[step_index] = step
    context.normalized_scopes[scope_index] = replace(scope, steps=tuple(steps))

def _known_point_coordinate_rewrites(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[dict[str, str], list[StepIntentNormalizationAction]]:
    """识别“重新求已知点坐标”的 utility step。

    这类 step 只是在把 ProblemIR 已经定义清楚的点（例如坐标原点 O）再 produced
    成一个坐标 fact。执行层可直接读取 point handle，不需要一个额外 method。
    """
    if step.creates or not step.produces:
        return {}, []
    allow_axis_defined = step.recipe_hint == "quadratic_axis_from_relation"
    rewrites: dict[str, str] = {}
    actions: list[StepIntentNormalizationAction] = []
    for produced in step.produces:
        if _produced_output_type(produced, handle_registry) != "Point":
            return {}, []
        if not _step_reads_visible_from_output_scope(step, produced.valid_scope, handle_registry):
            return {}, []
        point_name = _point_name_from_coordinate_fact(produced.handle)
        if point_name is None:
            return {}, []
        point_handle = _matching_known_point_read(
            step,
            point_name,
            handle_registry,
            allow_axis_defined=allow_axis_defined,
        )
        if point_handle is None:
            return {}, []
        rewrites[produced.handle] = point_handle
        actions.append(
            StepIntentNormalizationAction(
                action="drop_known_point_coordinate_utility_step",
                step_id=step.step_id,
                handle=produced.handle,
                target_step_id=None,
                reason=(
                    f"{point_handle} 已是 ProblemIR 中定义明确的已知点；"
                    f"将 utility fact {produced.handle} 改写为直接读取该点。"
                ),
            )
        )
    return rewrites, actions


def _step_reads_visible_from_output_scope(
    step: StepIntent,
    output_scope: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """A reusable output must not depend on narrower child-scope reads."""
    for handle in step.reads:
        if ":" not in handle:
            continue
        read_scope = handle_registry.handle_valid_scopes.get(handle)
        if read_scope is None and not handle.startswith("answer:"):
            read_scope = _handle_scope(handle)
        if read_scope is None:
            continue
        if not _valid_scope_visible_from(read_scope, output_scope, handle_registry):
            return False
    return True


def _matching_known_point_read(
    step: StepIntent,
    point_name: str,
    handle_registry: CanonicalHandleRegistry,
    *,
    allow_axis_defined: bool = False,
) -> str | None:
    """找同名且定义可直接复用的 point entity。"""
    candidates = [
        handle for handle in step.reads
        if handle.startswith("point:")
        and _point_name_from_point_handle(handle) == point_name
    ]
    candidates.extend(
        handle for handle in sorted(handle_registry.entity_payloads)
        if handle.startswith("point:")
        and handle not in candidates
        and _point_name_from_point_handle(handle) == point_name
        and _valid_scope_visible_from(_handle_scope(handle), step.scope_id, handle_registry)
    )
    for handle in candidates:
        if not handle.startswith("point:"):
            continue
        payload = handle_registry.entity_payloads.get(handle, {})
        definition = str(payload.get("definition", "")).lower()
        description = str(payload.get("description", "")).lower()
        if definition in {"coordinate_origin", "known_coordinate"}:
            return handle
        if allow_axis_defined and definition in {"axis_x_intercept", "axis_intercept"}:
            return handle
        if "坐标原点" in description or "origin" in definition:
            return handle
    return None

def _produced_name_suggests_parabola(item: ProducedFact) -> bool:
    """判断 produced fact 名称是否已经明确是抛物线。"""
    name = (
        item.handle.removeprefix("answer:").lower()
        if item.handle.startswith("answer:")
        else _semantic_name(item.handle).lower()
    )
    if "coefficient" in name and item.output_type != "Parabola":
        return False
    text = f"{item.handle}\n{item.description}".lower()
    return (
        any(value in name for value in ("parabola", "quadratic"))
        or "抛物线解析式" in text
        or "二次函数表达式" in text
        or "二次函数解析式" in text
    )

_QUADRATIC_UTILITY_STRONG_MARKERS = (
    "c_expr",
    "coefficient_relation",
    "coefficients_with",
    "coefficients_expr",
    "parabola_coefficients",
    "quadratic_coefficients",
    "expr_in_",
    "常数项",
    "抛物线系数",
    "二次函数系数",
)

_QUADRATIC_UTILITY_WEAK_NAME_MARKERS = ("relation", "equation")


def _produced_name_suggests_quadratic_utility(
    item: ProducedFact,
    *,
    step: StepIntent | None = None,
    handle_registry: CanonicalHandleRegistry | None = None,
) -> bool:
    """判断 produced fact 是否是可归一化的二次函数 utility fact。"""
    if not item.handle.startswith("fact:"):
        return False
    output_type = (
        _produced_output_type(item, handle_registry)
        if handle_registry is not None
        else item.output_type
    )
    if output_type not in {None, "Coefficients", "Equation", "Expression"}:
        return False
    name = _semantic_name(item.handle).lower()
    text = f"{item.handle}\n{item.description}".lower()
    if any(value in text for value in _QUADRATIC_UTILITY_STRONG_MARKERS):
        return True
    if not any(value in name for value in _QUADRATIC_UTILITY_WEAK_NAME_MARKERS):
        return False
    return step is not None and _step_intends_quadratic_state(step)


def _produced_name_suggests_quadratic_alias_utility(
    item: ProducedFact,
    *,
    step: StepIntent | None = None,
    handle_registry: CanonicalHandleRegistry | None = None,
) -> bool:
    """判断同 step 已有 Parabola 时，produced fact 是否只是抛物线别名缓存。"""
    if not item.handle.startswith("fact:"):
        return False
    name = _semantic_name(item.handle).lower()
    text = f"{item.handle}\n{item.description}".lower()
    if _produced_name_suggests_quadratic_utility(
        item,
        step=step,
        handle_registry=handle_registry,
    ):
        return True
    alias_names = {
        "coefficients",
        "parabola_coefficients",
        "quadratic_coefficients",
        "coefficient_cache",
        "parabola_coefficient_cache",
    }
    if name in alias_names:
        return True
    return any(
        value in text
        for value in (
            "parabola_coefficients",
            "quadratic_coefficients",
            "抛物线系数",
            "二次函数系数",
        )
    )


def _step_intends_quadratic_state(step: StepIntent) -> bool:
    """判断弱 relation/equation 名称是否处在求二次函数状态的上下文里。"""
    text = "\n".join(
        value
        for value in (
            step.goal_type,
            step.target,
        )
        if value
    ).lower()
    return any(
        value in text
        for value in (
            "derive_parabola",
            "parabola",
            "quadratic",
            "抛物线",
            "二次函数",
        )
    )

def _candidate_point_base_name(items: list[ProducedFact]) -> str | None:
    """从 ``D1_coordinate`` / ``D2_coordinate`` 这类候选语义中提取共同点名。"""
    bases: set[str] = set()
    for item in items:
        name = _semantic_name(item.handle)
        match = re.fullmatch(
            r"(?P<base>[A-Za-z][A-Za-z0-9]*?)(?:_?(?:candidate|cand))?[0-9]+_coordinate(?:_[A-Za-z0-9_]+)?",
            name,
            flags=re.IGNORECASE,
        )
        if match is not None:
            bases.add(match.group("base"))
            continue
        match = re.fullmatch(
            r"(?P<base>[A-Za-z][A-Za-z0-9]*)_(?:candidate|cand)[0-9]*(?:_coordinate(?:_[A-Za-z0-9_]+)?)?",
            name,
            flags=re.IGNORECASE,
        )
        if match is not None:
            bases.add(match.group("base"))
    return next(iter(bases)) if len(bases) == 1 else None

def _candidate_point_create_handles(
    step: StepIntent,
    point_items: list[ProducedFact],
) -> set[str]:
    """返回可随 PointList 归一化删除的单个候选点 creates。"""
    candidate_names = {
        name for name in (
            _candidate_point_name_from_output(item.handle)
            for item in point_items
        )
        if name is not None
    }
    if not candidate_names:
        return set()
    return {
        created.handle for created in step.creates
        if created.entity_type == "point"
        and _handle_name(created.handle) in candidate_names
    }

def _candidate_point_name_from_output(handle: str) -> str | None:
    """从候选点坐标 fact 读取候选点实体名，如 ``D_cand1``。"""
    if not handle.startswith("fact:"):
        return None
    semantic = _semantic_name(handle)
    match = re.fullmatch(
        r"(?P<name>[A-Za-z][A-Za-z0-9_]*?)_coordinate(?:_[A-Za-z0-9_]+)?",
        semantic,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group("name")
