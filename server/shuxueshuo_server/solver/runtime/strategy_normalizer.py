"""StepIntent 草稿的确定性整理。

Normalizer 位于 validator 之后、candidate resolver 之前。它只处理代码可以明确
判断的结构问题，例如 LLM 多输出了一个“由最小值再求参数”的冗余 answer step，
而前序 weighted recipe 已经能够产生同一个参数答案。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Protocol

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.question_goals import QuestionGoal
from shuxueshuo_server.solver.runtime.handle_registry import _semantic_name
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    StepIntent,
    StepIntentDraft,
    StepIntentNormalizationAction,
    StepIntentNormalizationReport,
    StepIntentScope,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import _produced_output_type


@dataclass
class NormalizationRuleContext:
    """单个 normalizer rule 执行时可读取/更新的上下文。"""

    handle_registry: CanonicalHandleRegistry
    question_goal_map: dict[str, QuestionGoal]
    recipe_output_types: dict[str, tuple[str, ...]]
    handle_rewrites: dict[str, str] = field(default_factory=dict)
    previous_steps: list[StepIntent] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizationRuleResult:
    """Normalizer rule 的统一返回值。"""

    step: StepIntent
    rewrites: dict[str, str] = field(default_factory=dict)
    actions: tuple[StepIntentNormalizationAction, ...] = ()
    append_step: bool = True


class NormalizationRule(Protocol):
    """StepIntent normalizer rule 接口。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        """返回 rule 处理后的 step、handle rewrite 与 action。"""
        ...


class StepIntentNormalizer:
    """对 StepIntentDraft 做安全、可解释的结构整理。"""

    def __init__(
        self,
        rules: tuple[NormalizationRule, ...] | None = None,
    ) -> None:
        self.rules = rules or DEFAULT_NORMALIZATION_RULES

    def normalize(
        self,
        draft: StepIntentDraft,
        *,
        family_spec: SolverFamilySpec,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
        handle_registry: CanonicalHandleRegistry,
    ) -> tuple[StepIntentDraft, StepIntentNormalizationReport]:
        """返回整理后的 draft 与报告。

        目前只合并冗余的 ParameterValue answer step：若某个 ``recipe_hint=null`` 的
        step 只 produces 参数答案，而同 scope 前序 recipe 已声明能输出
        ``ParameterValue``，则把该 answer handle 并入前序 recipe step。
        """
        question_goal_map = {f"answer:{goal.id}": goal for goal in question_goals}
        recipe_output_types = _recipe_output_types(family_spec)
        actions: list[StepIntentNormalizationAction] = []
        warnings: list[str] = []
        normalized_scopes: list[StepIntentScope] = []
        context = NormalizationRuleContext(
            handle_registry=handle_registry,
            question_goal_map=question_goal_map,
            recipe_output_types=recipe_output_types,
        )

        for scope in draft.scopes:
            context.previous_steps = []
            scope_steps, scope_actions = _normalize_angle_sum_axis_intercept_targets_for_scope(
                scope.steps,
                handle_registry=handle_registry,
            )
            actions.extend(scope_actions)
            scope_steps, scope_actions = _drop_unreferenced_path_transformation_steps_for_scope(
                scope_steps,
                handle_registry=handle_registry,
            )
            actions.extend(scope_actions)
            scope_steps, scope_actions = _fold_broken_path_internal_sequence_for_scope(
                scope_steps,
                handle_registry=handle_registry,
            )
            actions.extend(scope_actions)
            scope_steps, scope_actions = _drop_square_pre_reduction_point_utility_steps_for_scope(
                scope_steps,
                handle_registry=handle_registry,
            )
            actions.extend(scope_actions)
            for step in scope_steps:
                append_step = True
                for rule in self.rules:
                    result = rule.apply(step, context)
                    step = result.step
                    context.handle_rewrites.update(result.rewrites)
                    actions.extend(result.actions)
                    if not result.append_step:
                        append_step = False
                        break
                if append_step:
                    context.previous_steps.append(step)
            normalized_scopes.append(replace(scope, steps=tuple(context.previous_steps)))

        # 目前没有需要保留但不改写的场景；预留 warnings 便于后续扩展。
        _ = warnings
        return (
            StepIntentDraft(scopes=tuple(normalized_scopes)),
            StepIntentNormalizationReport(actions=tuple(actions), warnings=tuple(warnings)),
        )


class _RewriteStepReadsRule:
    """把前序 rule 产生的 handle 改名同步到当前 step。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        return NormalizationRuleResult(
            step=_rewrite_step_reads(step, context.handle_rewrites),
        )


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


class _WeightedAuxiliaryLocusTypeRule:
    """修正 weighted transform 辅助轨迹的 output_type alias。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _normalize_weighted_auxiliary_locus_type_step(step)
        return NormalizationRuleResult(step=step, actions=tuple(actions))


class _BrokenPathMinimumEndpointProducesRule:
    """让通用将军饮马最值 recipe 显式暴露最短线段端点。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _ensure_broken_path_minimum_endpoint_produces(step)
        return NormalizationRuleResult(step=step, actions=tuple(actions))


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


class _MergeRedundantParameterAnswerRule:
    """把冗余参数 answer step 合并到前序 recipe step。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        merge_target_index = _merge_target_index(
            step,
            previous_steps=context.previous_steps,
            recipe_output_types=context.recipe_output_types,
            question_goal_map=context.question_goal_map,
            handle_registry=context.handle_registry,
        )
        if merge_target_index is None:
            return NormalizationRuleResult(step=step)

        target_step = context.previous_steps[merge_target_index]
        merged_produces = _append_unique_produces(
            target_step.produces,
            step.produces,
        )
        context.previous_steps[merge_target_index] = replace(
            target_step,
            produces=merged_produces,
        )
        actions = tuple(
            StepIntentNormalizationAction(
                action="merge_redundant_parameter_answer_step",
                step_id=step.step_id,
                target_step_id=target_step.step_id,
                handle=produced.handle,
                reason=(
                    "前序 recipe 已能输出 ParameterValue；该 step 只是在收集同一个参数答案，"
                    "合并到前序 recipe，避免无 method 的 utility step。"
                ),
            )
            for produced in step.produces
        )
        return NormalizationRuleResult(
            step=step,
            actions=actions,
            append_step=False,
        )


DEFAULT_NORMALIZATION_RULES: tuple[NormalizationRule, ...] = (
    _RewriteStepReadsRule(),
    _QuadraticFromConstraintsRule(),
    _CandidatePointFactsRule(),
    _WeightedAuxiliaryLocusTypeRule(),
    _BrokenPathMinimumEndpointProducesRule(),
    _PointAnswerCoordinateRule(),
    _AxisPointAliasRule(),
    _KnownPointCoordinateUtilityRule(),
    _MergeRedundantParameterAnswerRule(),
)


def _rewrite_step_reads(step: StepIntent, rewrites: dict[str, str]) -> StepIntent:
    """把前序 normalizer 产生的 handle 改名同步到当前 reads。"""
    if not rewrites:
        return step
    reads = tuple(rewrites.get(handle, handle) for handle in step.reads)
    target = rewrites.get(step.target, step.target)
    return replace(step, reads=reads, target=target)


def _normalize_angle_sum_axis_intercept_targets_for_scope(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
    """为“角和找等角 -> 等角求轴截点”链路补齐目标 PointRef。

    DeepSeek 有时把 ``angle_sum_equal_angle_candidates`` 的 target 写成它要
    produces 的 ``AngleEquality`` fact。执行层实际需要的 target 是后续
    ``axis_intercept_from_equal_acute_angles`` 要计算的轴截点 PointRef。若后续
    step 明确读取了该 AngleEquality 且 produces 唯一 Point fact，我们可以从该
    point fact 的 canonical handle 反推出目标点，并把它声明为前一步 creates。
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
        for angle_handle in angle_handles:
            angle_index = produced_to_step[angle_handle]
            angle_step = result[angle_index]
            if angle_step.recipe_hint != "angle_sum_equal_angle_candidates":
                continue
            if _step_has_point_target(angle_step):
                target_handle = _angle_sum_existing_point_target(angle_step)
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


def _drop_unreferenced_path_transformation_steps_for_scope(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
    """删除未参与数据流的 PathTransformation 解释 step。

    ``PathTransformation`` 只有在后续 step 读取它时才是可执行数据流的一部分。
    若 LLM 额外输出了一个 ``recipe_hint=null``、不创建实体、产物也没有被任何
    后续 step 读取的路径转化说明，它更适合进入 ExplanationBuilder，而不是阻断
    Method Solver 的 executable plan。
    """
    if not steps:
        return steps, []
    future_reads_by_index: list[set[str]] = []
    suffix_reads: set[str] = set()
    for step in reversed(steps):
        future_reads_by_index.append(set(suffix_reads))
        suffix_reads.update(step.reads)
    future_reads_by_index.reverse()

    kept: list[StepIntent] = []
    actions: list[StepIntentNormalizationAction] = []
    for index, step in enumerate(steps):
        produced_handles = tuple(item.handle for item in step.produces)
        if (
            step.recipe_hint is None
            and not step.creates
            and produced_handles
            and all(
                _produced_output_type(item, handle_registry) == "PathTransformation"
                for item in step.produces
            )
            and not any(handle in future_reads_by_index[index] for handle in produced_handles)
        ):
            actions.append(
                StepIntentNormalizationAction(
                    action="drop_unreferenced_path_transformation_step",
                    step_id=step.step_id,
                    handle=",".join(produced_handles),
                    reason=(
                        "该 PathTransformation 没有 recipe/method hint，且产物未被后续 "
                        "step 读取；视为讲解性路径转化说明，不进入 executable dataflow。"
                    ),
                )
            )
            continue
        kept.append(step)
    return tuple(kept), actions


def _fold_broken_path_internal_sequence_for_scope(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
    """把 LLM 拆开的将军饮马内部 method 序列折叠回 recipe step。

    square family 对外暴露的是 ``broken_path_straightening_minimum_expression``。
    DeepSeek 偶尔会直接选择 recipe 内部的三个 method；这不是数学路线错误，
    只是执行颗粒度偏差，可以确定性折叠。
    """
    if len(steps) < 3:
        return steps, []

    result: list[StepIntent] = []
    actions: list[StepIntentNormalizationAction] = []
    read_rewrites: dict[str, tuple[str, ...]] = {}
    index = 0
    while index < len(steps):
        if index + 2 >= len(steps):
            result.append(_rewrite_step_reads_many(steps[index], read_rewrites))
            index += 1
            continue
        candidate_step = _rewrite_step_reads_many(steps[index], read_rewrites)
        select_step = _rewrite_step_reads_many(steps[index + 1], read_rewrites)
        distance_step = _rewrite_step_reads_many(steps[index + 2], read_rewrites)
        folded = _fold_broken_path_sequence(
            candidate_step,
            select_step,
            distance_step,
            handle_registry=handle_registry,
        )
        if folded is None:
            result.append(candidate_step)
            index += 1
            continue
        folded_step, rewrites, action = folded
        result.append(folded_step)
        read_rewrites.update(rewrites)
        actions.append(action)
        index += 3

    return tuple(result), actions


def _fold_broken_path_sequence(
    candidate_step: StepIntent,
    select_step: StepIntent,
    distance_step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, dict[str, tuple[str, ...]], StepIntentNormalizationAction] | None:
    """若三个连续 step 是拉直候选、选择、距离计算，返回折叠结果。"""
    if candidate_step.scope_id != select_step.scope_id or select_step.scope_id != distance_step.scope_id:
        return None
    if candidate_step.recipe_hint != "broken_path_straightening_candidates":
        return None
    if select_step.recipe_hint != "select_straightening_candidate":
        return None
    if distance_step.recipe_hint != "distance_between_points":
        return None

    candidate_handles = tuple(item.handle for item in candidate_step.produces)
    selected_handles = tuple(item.handle for item in select_step.produces)
    if not candidate_handles or not selected_handles:
        return None
    if not any(handle in select_step.reads for handle in candidate_handles):
        return None
    if not any(handle in distance_step.reads for handle in selected_handles):
        return None
    minimum_produces = tuple(
        item for item in distance_step.produces
        if _produced_output_type(item, handle_registry) == "MinimumExpression"
    )
    if not minimum_produces:
        return None

    scope_id = distance_step.scope_id
    point_1 = _minimum_point_fact(scope_id, "path_minimum_point_1", "拉直后最短线段的第一个端点")
    point_2 = _minimum_point_fact(scope_id, "path_minimum_point_2", "拉直后最短线段的第二个端点")
    existing_handles = {item.handle for item in distance_step.produces}
    point_produces = tuple(
        item for item in (point_1, point_2)
        if item.handle not in existing_handles
    )

    reads = _unique_read_handles(
        (
            *candidate_step.reads,
            *select_step.reads,
            *distance_step.reads,
        ),
        exclude={*candidate_handles, *selected_handles},
    )
    folded_step = replace(
        distance_step,
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_path_minimum_expression",
        target=minimum_produces[0].handle,
        reads=reads,
        creates=tuple(
            created
            for step in (candidate_step, select_step, distance_step)
            for created in step.creates
        ),
        produces=(*distance_step.produces, *point_produces),
        strategy=(
            "对单动点折线路径生成拉直候选、选择可计算方案，并计算最小值表达式。"
        ),
        reason=(
            "LLM 将通用将军饮马 recipe 拆成内部 method；系统折叠为一个 "
            "broken_path_straightening_minimum_expression step。"
        ),
    )
    rewrites = {
        handle: (point_1.handle, point_2.handle)
        for handle in selected_handles
    }
    action = StepIntentNormalizationAction(
        action="fold_broken_path_internal_sequence",
        step_id=candidate_step.step_id,
        target_step_id=distance_step.step_id,
        handle=",".join((*candidate_handles, *selected_handles)),
        reason=(
            "连续的 broken_path_straightening_candidates / select_straightening_candidate / "
            "distance_between_points 是 recipe 内部实现，折叠为对外 recipe step。"
        ),
    )
    return folded_step, rewrites, action


def _drop_square_pre_reduction_point_utility_steps_for_scope(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
    """删除 square 降维前不必要的 midpoint/center 坐标 utility step。

    ``square_path_dimension_reduction`` 读取的是正方形、中点、中心和路径结构 fact；
    不需要 LLM 先把中点/中心坐标算出来。若 LLM 在降维前输出了空 hint 的 Point
    utility step，且该 step 没有被降维前的其它步骤使用，可以删除它，让降维 step
    先执行并产生 planner insight。
    """
    if len(steps) < 2:
        return steps, []

    reduction_indices = [
        index for index, step in enumerate(steps)
        if step.recipe_hint == "square_path_dimension_reduction"
    ]
    if not reduction_indices:
        return steps, []

    drop_indices: set[int] = set()
    dropped_handles: set[str] = set()
    actions: list[StepIntentNormalizationAction] = []
    for reduction_index in reduction_indices:
        reduction_step = steps[reduction_index]
        reduction_reads = set(reduction_step.reads)
        for index, step in enumerate(steps[:reduction_index]):
            produced_handles = tuple(item.handle for item in step.produces)
            if not produced_handles:
                continue
            if not _is_square_pre_reduction_point_utility_step(step, handle_registry):
                continue
            if _produced_handles_used_before_index(
                produced_handles,
                steps,
                start_index=index + 1,
                stop_index=reduction_index,
            ):
                continue
            drop_indices.add(index)
            dropped_handles.update(produced_handles)
            actions.append(
                StepIntentNormalizationAction(
                    action="drop_square_pre_reduction_point_utility_step",
                    step_id=step.step_id,
                    target_step_id=reduction_step.step_id,
                    handle=",".join(produced_handles),
                    reason=(
                        "square_path_dimension_reduction 只需要正方形/中点/中心/路径结构 fact；"
                        "该空 hint Point utility step 只是提前猜测降维动点相关坐标，删除后让降维"
                        "先执行并通过 planner insight 告诉后续真实 moving_point。"
                    ),
                )
            )

    if not drop_indices:
        return steps, []

    result: list[StepIntent] = []
    for index, step in enumerate(steps):
        if index in drop_indices:
            continue
        if step.recipe_hint == "square_path_dimension_reduction":
            step = replace(
                step,
                reads=tuple(handle for handle in step.reads if handle not in dropped_handles),
            )
        result.append(step)
    return tuple(result), actions


def _produced_handles_used_before_index(
    handles: tuple[str, ...],
    steps: tuple[StepIntent, ...],
    *,
    start_index: int,
    stop_index: int,
) -> bool:
    """判断 produced handles 是否被 stop_index 前的其它 step 消费。"""
    produced = set(handles)
    for step in steps[start_index:stop_index]:
        if any(handle in produced for handle in step.reads):
            return True
    return False


def _is_square_pre_reduction_point_utility_step(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否是 square 降维前可删除的结构点坐标 utility step。"""
    if step.recipe_hint is not None or step.creates:
        return False
    if not step.produces:
        return False
    if any(item.handle.startswith("answer:") for item in step.produces):
        return False
    if not all(_produced_output_type(item, handle_registry) == "Point" for item in step.produces):
        return False
    structural_fact_types = {"midpoint_definition", "square_center"}
    return any(
        handle_registry.fact_types.get(handle) in structural_fact_types
        for handle in step.reads
    )


def _ensure_broken_path_minimum_endpoint_produces(
    step: StepIntent,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """给 ``broken_path_straightening_minimum_expression`` step 补端点 Point fact。"""
    if step.recipe_hint != "broken_path_straightening_minimum_expression":
        return step, []
    existing_handles = {item.handle for item in step.produces}
    point_1 = _minimum_point_fact(step.scope_id, "path_minimum_point_1", "拉直后最短线段的第一个端点")
    point_2 = _minimum_point_fact(step.scope_id, "path_minimum_point_2", "拉直后最短线段的第二个端点")
    additions = tuple(
        item for item in (point_1, point_2)
        if item.handle not in existing_handles
    )
    if not additions:
        return step, []
    return (
        replace(step, produces=(*step.produces, *additions)),
        [
            StepIntentNormalizationAction(
                action="add_broken_path_minimum_endpoint_outputs",
                step_id=step.step_id,
                handle=",".join(item.handle for item in additions),
                reason=(
                    "broken_path_straightening_minimum_expression recipe 内部会选择拉直方案并"
                    "计算最短线段；补充暴露最短线段端点，供后续 line_locus_minimum_point 读取。"
                ),
            )
        ],
    )


def _minimum_point_fact(scope_id: str, name: str, description: str) -> ProducedFact:
    """构造拉直 recipe 暴露的最短线段端点 fact。"""
    return ProducedFact(
        handle=f"fact:{scope_id}:{name}",
        valid_scope=scope_id,
        description=description,
        output_type="Point",
    )


def _unique_read_handles(
    handles: tuple[str, ...],
    *,
    exclude: set[str],
) -> tuple[str, ...]:
    """合并 reads，去掉被 recipe 内部折叠的临时候选 handle。"""
    result: list[str] = []
    seen: set[str] = set()
    for handle in handles:
        if handle in exclude or handle in seen:
            continue
        seen.add(handle)
        result.append(handle)
    return tuple(result)


def _rewrite_step_reads_many(
    step: StepIntent,
    rewrites: dict[str, tuple[str, ...]],
) -> StepIntent:
    """把一个 read handle 替换成多个 handle，保持顺序与去重。"""
    if not rewrites:
        return step
    reads: list[str] = []
    seen: set[str] = set()
    for handle in step.reads:
        replacements = rewrites.get(handle, (handle,))
        for replacement in replacements:
            if replacement in seen:
                continue
            seen.add(replacement)
            reads.append(replacement)
    target_replacements = rewrites.get(step.target)
    return replace(
        step,
        reads=tuple(reads),
        target=target_replacements[0] if target_replacements else step.target,
    )


def _angle_sum_existing_point_target(step: StepIntent) -> str | None:
    """读取已有 angle_sum step 的 point target。"""
    if step.target.startswith("point:"):
        return step.target
    for item in step.creates:
        if item.entity_type == "point":
            return item.handle
    return None


def _step_has_point_target(step: StepIntent) -> bool:
    """判断 step 是否已经有 point target 或 point creates。"""
    if step.target.startswith("point:"):
        return True
    return any(item.entity_type == "point" for item in step.creates)


def _axis_intercept_target_point_handle(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """从等角求轴截点 step 的输出中反推目标 point handle。"""
    if step.target.startswith("point:"):
        return step.target
    for item in step.creates:
        if item.entity_type == "point":
            return item.handle
    point_items = [
        item for item in step.produces
        if _produced_output_type(item, handle_registry) == "Point"
    ]
    if len(point_items) != 1:
        return None
    point_name = _point_name_from_coordinate_fact(point_items[0].handle)
    if point_name is None:
        return None
    return f"point:{point_items[0].valid_scope}:{point_name}"


def _point_name_from_coordinate_fact(handle: str) -> str | None:
    """从 ``fact:scope:F_coordinate_value`` 读取点名 F。"""
    if not handle.startswith("fact:"):
        return None
    name = _semantic_name(handle)
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9]*)_coordinate(?:_[A-Za-z0-9_]+)?",
        name,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group("point")


def _step_with_angle_sum_target(
    step: StepIntent,
    *,
    target_handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> StepIntent:
    """返回补齐 target/creates 的 angle_sum step。"""
    creates = list(step.creates)
    if (
        target_handle not in handle_registry.entity_handles
        and target_handle not in {item.handle for item in creates}
    ):
        creates.append(
            CreatedEntity(
                handle=target_handle,
                entity_type="point",
                valid_scope=_handle_scope_from_point_handle(target_handle),
                description="由角和等角链路确定的轴截点目标",
            )
        )
    return replace(step, target=target_handle, creates=tuple(creates))


def _step_with_read(step: StepIntent, handle: str) -> StepIntent:
    """给 step 追加一个 read handle，保持幂等。"""
    if handle in step.reads:
        return step
    return replace(step, reads=(*step.reads, handle))


def _handle_scope_from_point_handle(handle: str) -> str:
    """读取 point handle 的 scope。"""
    match = re.fullmatch(r"point:(?P<scope>[A-Za-z0-9_]+):[A-Za-z0-9_]+", handle)
    if match is None:
        raise ValueError(f"not a point handle: {handle}")
    return match.group("scope")


def _rewrite_generic_angle_equality_handle(
    steps: list[StepIntent],
    *,
    angle_index: int,
    old_handle: str,
    target_handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[list[StepIntent], list[StepIntentNormalizationAction]]:
    """把泛化 AngleEquality handle 改写成可解析的 angle_XXX_eq_YYY。"""
    angle_step = steps[angle_index]
    produced = next((item for item in angle_step.produces if item.handle == old_handle), None)
    if produced is None:
        return steps, []
    if re.fullmatch(r"fact:[A-Za-z0-9_]+:angle_[A-Za-z]{3}_eq_[A-Za-z]{3}", old_handle):
        return steps, []
    if _produced_output_type(produced, handle_registry) != "AngleEquality":
        return steps, []
    new_handle = _structured_angle_equality_handle(
        angle_step,
        target_handle=target_handle,
        produced=produced,
        handle_registry=handle_registry,
    )
    if new_handle is None or new_handle == old_handle:
        return steps, []

    new_produces = tuple(
        replace(item, handle=new_handle)
        if item.handle == old_handle
        else item
        for item in angle_step.produces
    )
    rewritten_steps: list[StepIntent] = []
    for index, step in enumerate(steps):
        if index == angle_index:
            rewritten_steps.append(replace(step, produces=new_produces))
            continue
        rewritten_steps.append(_step_with_read_rewrite(step, old_handle, new_handle))
    return rewritten_steps, [
        StepIntentNormalizationAction(
            action="normalize_angle_equality_fact_handle",
            step_id=angle_step.step_id,
            target_step_id=None,
            handle=new_handle,
            reason=(
                "AngleEquality produced handle 过于泛化；根据 angle_sum 条件和目标点 "
                f"将 {old_handle} 改写为 {new_handle}，供后续等角 selector 解析。"
            ),
        )
    ]


def _structured_angle_equality_handle(
    step: StepIntent,
    *,
    target_handle: str,
    produced: ProducedFact,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """由 angle_sum fact + 目标点生成结构化等角 handle。"""
    angle_sum_fact = next(
        (
            handle for handle in step.reads
            if handle_registry.fact_types.get(handle) == "angle_sum"
        ),
        None,
    )
    if angle_sum_fact is None:
        return None
    payload = handle_registry.fact_payloads.get(angle_sum_fact)
    terms = payload.get("angle_terms") if payload is not None else None
    if not (
        isinstance(terms, list)
        and len(terms) == 2
        and all(isinstance(item, str) and re.fullmatch(r"[A-Za-z]{3}", item) for item in terms)
    ):
        return None
    shared, reference = terms[0], terms[1]
    target_name = _point_name_from_point_handle(target_handle)
    if target_name is None:
        return None
    left_angle = f"{reference[2]}{shared[1]}{target_name}"
    return f"fact:{produced.valid_scope}:angle_{left_angle}_eq_{reference}"


def _point_name_from_point_handle(handle: str) -> str | None:
    """读取 point handle 的点名。"""
    match = re.fullmatch(r"point:[A-Za-z0-9_]+:(?P<name>[A-Za-z0-9_]+)", handle)
    if match is None:
        return None
    return match.group("name")


def _step_with_read_rewrite(step: StepIntent, old_handle: str, new_handle: str) -> StepIntent:
    """把 step reads 中的 old handle 替换为 new handle。"""
    if old_handle not in step.reads:
        return step
    return replace(
        step,
        reads=tuple(new_handle if handle == old_handle else handle for handle in step.reads),
        target=new_handle if step.target == old_handle else step.target,
    )


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
    """
    if not _step_can_normalize_quadratic_utility(step):
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
        if item not in parabola_items and utility_detector(item)
    ]
    if not utility_items:
        return step, {}, type_actions

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
    rewrites = {item.handle: target_handle for item in utility_items}
    new_produces = tuple(
        item for item in step.produces
        if item in parabola_items
    )
    if target_item not in new_produces:
        new_produces = (*new_produces, target_item)
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
        for item in utility_items
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


def _step_can_normalize_quadratic_utility(step: StepIntent) -> bool:
    """判断 step 是否可视作 quadratic_from_constraints 的化简动作。"""
    if step.recipe_hint == "quadratic_from_constraints":
        return True
    if step.recipe_hint not in {None, "parameter_from_expression_value"}:
        return False
    if not any(_produced_name_suggests_quadratic_utility(item) for item in step.produces):
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
    return replace(step, produces=(target_item,)), rewrites, actions


def _normalize_weighted_auxiliary_locus_type_step(
    step: StepIntent,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """把 weighted transform 的辅助轨迹类型别名归一化为 Line。

    LLM 常把“辅助点运动轨迹/射线”误标成折线拉直选项
    ``StraighteningCandidate``。在 ``weighted_axis_path_triangle_transform`` 中，
    该 companion output 的 runtime 类型固定是 ``Line``，可以确定性修正。
    """
    if step.recipe_hint != "weighted_axis_path_triangle_transform":
        return step, []
    new_produces: list[ProducedFact] = []
    actions: list[StepIntentNormalizationAction] = []
    changed = False
    for item in step.produces:
        if item.output_type == "StraighteningCandidate" and _is_weighted_auxiliary_locus_item(item):
            new_produces.append(replace(item, output_type="Line"))
            changed = True
            actions.append(
                StepIntentNormalizationAction(
                    action="normalize_weighted_auxiliary_locus_type",
                    step_id=step.step_id,
                    handle=item.handle,
                    target_step_id=None,
                    reason=(
                        "weighted_axis_path_triangle_transform 的 auxiliary_locus "
                        "companion output 是 Line；将辅助轨迹/射线的 "
                        "StraighteningCandidate 类型别名修正为 Line。"
                    ),
                )
            )
            continue
        new_produces.append(item)
    if not changed:
        return step, []
    return replace(step, produces=tuple(new_produces)), actions


def _is_weighted_auxiliary_locus_item(item: ProducedFact) -> bool:
    """判断 produced fact 是否指向 weighted transform 的辅助轨迹/射线。"""
    text = f"{item.handle}\n{item.description}".lower()
    return any(
        token in text
        for token in (
            "aux_locus",
            "auxiliary_locus",
            "locus",
            "轨迹",
            "射线",
            "辅助点运动轨迹",
        )
    )


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


def _single_point_answer_goal(
    step: StepIntent,
    question_goal_map: dict[str, QuestionGoal],
) -> QuestionGoal | None:
    """返回 step 中唯一 Point answer goal。"""
    goals = [
        question_goal_map[item.handle]
        for item in step.produces
        if item.handle in question_goal_map
        and question_goal_map[item.handle].value_type == "Point"
    ]
    return goals[0] if len(goals) == 1 else None


def _previous_axis_answer_step_for_fact(
    step: StepIntent,
    previous_steps: list[StepIntent],
    question_goal_map: dict[str, QuestionGoal],
) -> tuple[int, str, str] | None:
    """若当前 step 是重复 axis coordinate fact，找到前序同点 answer step。"""
    point_names = {
        name
        for item in step.produces
        if (name := _point_name_from_coordinate_fact(item.handle)) is not None
    }
    if len(point_names) != 1:
        return None
    point_name = next(iter(point_names))
    for index in range(len(previous_steps) - 1, -1, -1):
        previous = previous_steps[index]
        if previous.recipe_hint != "quadratic_axis_from_relation":
            continue
        goal = _single_point_answer_goal(previous, question_goal_map)
        if goal is None:
            continue
        point_scope = _point_scope_from_goal_target(goal)
        if _point_name_from_goal_target(goal) == point_name and point_scope is not None:
            return index, point_name, point_scope
    return None


def _known_point_coordinate_rewrites(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[dict[str, str], list[StepIntentNormalizationAction]]:
    """识别“重新求已知点坐标”的 utility step。

    这类 step 只是在把 ProblemIR 已经定义清楚的点（例如坐标原点 O）再 produced
    成一个坐标 fact。执行层可直接读取 point handle，不需要一个额外 method。
    """
    if step.recipe_hint is not None or step.creates or not step.produces:
        return {}, []
    rewrites: dict[str, str] = {}
    actions: list[StepIntentNormalizationAction] = []
    for produced in step.produces:
        if _produced_output_type(produced, handle_registry) != "Point":
            return {}, []
        point_name = _point_name_from_coordinate_fact(produced.handle)
        if point_name is None:
            return {}, []
        point_handle = _matching_known_point_read(step, point_name, handle_registry)
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


def _matching_known_point_read(
    step: StepIntent,
    point_name: str,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """从 step reads 中找同名且定义已知坐标的 point entity。"""
    for handle in step.reads:
        if not handle.startswith("point:") or _point_name_from_point_handle(handle) != point_name:
            continue
        payload = handle_registry.entity_payloads.get(handle, {})
        definition = str(payload.get("definition", "")).lower()
        description = str(payload.get("description", "")).lower()
        if definition in {"coordinate_origin", "known_coordinate"}:
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


def _produced_name_suggests_quadratic_utility(item: ProducedFact) -> bool:
    """判断 produced fact 是否是可归一化的二次函数 utility fact。"""
    if not item.handle.startswith("fact:"):
        return False
    name = _semantic_name(item.handle).lower()
    text = f"{item.handle}\n{item.description}".lower()
    return any(
        value in text
        for value in (
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
    ) or any(
        value in name
        for value in (
            "c_expr",
            "coefficient_relation",
            "coefficients_with",
            "coefficients_expr",
            "parabola_coefficients",
            "quadratic_coefficients",
            "relation",
            "equation",
        )
    )


def _produced_name_suggests_quadratic_alias_utility(item: ProducedFact) -> bool:
    """判断同 step 已有 Parabola 时，produced fact 是否只是抛物线别名缓存。"""
    if not item.handle.startswith("fact:"):
        return False
    name = _semantic_name(item.handle).lower()
    text = f"{item.handle}\n{item.description}".lower()
    if _produced_name_suggests_quadratic_utility(item):
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


def _candidate_point_base_name(items: list[ProducedFact]) -> str | None:
    """从 ``D1_coordinate`` / ``D2_coordinate`` 这类候选语义中提取共同点名。"""
    bases: set[str] = set()
    for item in items:
        name = _semantic_name(item.handle)
        match = re.fullmatch(
            r"(?P<base>[A-Za-z][A-Za-z0-9]*?)(?:_?candidate)?[0-9]+_coordinate(?:_[A-Za-z0-9_]+)?",
            name,
            flags=re.IGNORECASE,
        )
        if match is not None:
            bases.add(match.group("base"))
            continue
        match = re.fullmatch(
            r"(?P<base>[A-Za-z][A-Za-z0-9]*)_candidate[0-9]*(?:_coordinate(?:_[A-Za-z0-9_]+)?)?",
            name,
            flags=re.IGNORECASE,
        )
        if match is not None:
            bases.add(match.group("base"))
    return next(iter(bases)) if len(bases) == 1 else None


def _point_name_from_goal_target(goal: QuestionGoal) -> str | None:
    """从 Point QuestionGoal target_path 读取目标点名。"""
    try:
        path = ContextPath.parse(goal.target_path)
    except ValueError:
        return None
    if path.container != "points":
        return None
    return path.key


def _point_scope_from_goal_target(goal: QuestionGoal) -> str | None:
    """从 Point QuestionGoal target_path 读取目标点所在 scope。"""
    try:
        path = ContextPath.parse(goal.target_path)
    except ValueError:
        return None
    if path.container != "points":
        return None
    return path.scope_id


def _is_specific_point_coordinate_name(name: str, point_name: str) -> bool:
    """判断 semantic name 是否已经是目标点的坐标 fact。"""
    return name.lower().startswith(f"{point_name.lower()}_coordinate")


def _is_generic_point_coordinate_name(name: str) -> bool:
    """判断 semantic name 是否为角色型坐标 fact，而非真实点名坐标 fact。"""
    lowered = name.lower()
    if "coordinate" not in lowered and "coord" not in lowered:
        return False
    return any(
        token in lowered
        for token in (
            "axis",
            "point",
            "target",
            "result",
            "selected",
            "constructed",
            "intersection",
        )
    )


def _merge_target_index(
    step: StepIntent,
    *,
    previous_steps: list[StepIntent],
    recipe_output_types: dict[str, tuple[str, ...]],
    question_goal_map: dict[str, QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> int | None:
    """判断当前 step 是否应并入同 scope 前序 ParameterValue recipe。"""
    if step.recipe_hint is not None:
        return None
    if step.creates:
        return None
    if not step.produces or any(not item.handle.startswith("answer:") for item in step.produces):
        return None
    if not all(_is_parameter_answer(item, question_goal_map, handle_registry) for item in step.produces):
        return None
    for index in range(len(previous_steps) - 1, -1, -1):
        previous = previous_steps[index]
        if previous.scope_id != step.scope_id:
            continue
        if not previous.recipe_hint:
            continue
        if "ParameterValue" not in recipe_output_types.get(previous.recipe_hint, ()):
            continue
        # 只允许并入 recipe step；普通 method 的后续参数 step 仍应显式可执行。
        return index
    return None


def _is_parameter_answer(
    produced: ProducedFact,
    question_goal_map: dict[str, QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 produced 是否为最终参数答案。"""
    goal = question_goal_map.get(produced.handle)
    if goal is not None:
        return goal.value_type == "ParameterValue"
    return handle_registry.answer_value_types.get(produced.handle) == "ParameterValue"


def _recipe_output_types(family_spec: SolverFamilySpec) -> dict[str, tuple[str, ...]]:
    """读取 family recipe 声明的输出类型。"""
    result: dict[str, tuple[str, ...]] = {}
    for recipe in family_spec.step_recipes:
        if recipe.execution is None:
            result[recipe.recipe_id] = ()
            continue
        result[recipe.recipe_id] = tuple(
            output_type
            for _alias, output_type in recipe.execution.output_aliases
        )
    return result


def _append_unique_produces(
    current: tuple[ProducedFact, ...],
    additions: tuple[ProducedFact, ...],
) -> tuple[ProducedFact, ...]:
    """按 handle 追加 produces，保持原顺序。"""
    seen = {item.handle for item in current}
    result = list(current)
    for item in additions:
        if item.handle in seen:
            continue
        seen.add(item.handle)
        result.append(item)
    return tuple(result)
