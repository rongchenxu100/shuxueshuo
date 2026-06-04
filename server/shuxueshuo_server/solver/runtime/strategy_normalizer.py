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
            for step in scope.steps:
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
    _PointAnswerCoordinateRule(),
    _MergeRedundantParameterAnswerRule(),
)


def _rewrite_step_reads(step: StepIntent, rewrites: dict[str, str]) -> StepIntent:
    """把前序 normalizer 产生的 handle 改名同步到当前 reads。"""
    if not rewrites:
        return step
    reads = tuple(rewrites.get(handle, handle) for handle in step.reads)
    target = rewrites.get(step.target, step.target)
    return replace(step, reads=reads, target=target)


def _normalize_quadratic_from_constraints_step(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, dict[str, str], list[StepIntentNormalizationAction]]:
    """把二次函数化简 step 的 utility fact 归一化成当前问抛物线 fact。

    DeepSeek 常把 ``quadratic_from_constraints`` 的产物写成 ``c_expr_in_b``。
    执行层真正需要的是当前问的含参抛物线，而不是把 ``c=...`` 当成独立 fact。
    这里只在 method hint 已经明确为 ``quadratic_from_constraints`` 时做改名。
    """
    if step.recipe_hint != "quadratic_from_constraints":
        return step, {}, []
    if any(item.handle.startswith("answer:") for item in step.produces):
        return step, {}, []

    parabola_items = [
        item for item in step.produces
        if _produced_name_suggests_parabola(item)
    ]
    utility_items = [
        item for item in step.produces
        if item not in parabola_items and _produced_name_suggests_quadratic_utility(item)
    ]
    if not utility_items:
        return step, {}, []

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
        )
    )
    rewrites = {item.handle: target_handle for item in utility_items}
    new_produces = tuple(
        item for item in step.produces
        if item in parabola_items
    )
    if target_item not in new_produces:
        new_produces = (*new_produces, target_item)
    actions = [
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
    return replace(step, produces=new_produces), rewrites, actions


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


def _produced_name_suggests_parabola(item: ProducedFact) -> bool:
    """判断 produced fact 名称是否已经明确是抛物线。"""
    name = _semantic_name(item.handle).lower()
    text = f"{item.handle}\n{item.description}".lower()
    return any(value in name for value in ("parabola", "quadratic")) or "抛物线" in text


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
            "coefficients_expr",
            "expr_in_",
            "常数项",
        )
    ) or any(
        value in name
        for value in (
            "c_expr",
            "coefficient_relation",
            "coefficients_expr",
            "relation",
            "equation",
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
