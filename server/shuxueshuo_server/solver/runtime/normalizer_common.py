"""Shared data structures and helper functions for StepIntent normalization."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Protocol

from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    SolverFamilySpec,
)
from shuxueshuo_server.solver.question_goals import QuestionGoal
from shuxueshuo_server.solver.runtime.handle_registry import (
    _semantic_name,
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    StepIntent,
    StepIntentNormalizationAction,
    StepIntentScope,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import _produced_output_type

__all__ = (
'NormalizationRuleContext',
'_PublishedOutput',
'NormalizationRuleResult',
'NormalizationRule',
'_rewrite_step_reads',
'_handle_available',
'_available_handles',
'_unique_tuple',
'_unique_read_handles',
'_rewrite_step_reads_many',
'_angle_sum_existing_point_target',
'_step_has_point_target',
'_axis_intercept_target_point_handle',
'_point_name_from_coordinate_fact',
'_step_with_angle_sum_target',
'_step_with_read',
'_step_without_create',
'_handle_scope_from_point_handle',
'_rewrite_generic_angle_equality_handle',
'_structured_angle_equality_handle',
'_point_name_from_point_handle',
'_step_with_read_rewrite',
'_visible_fact_handle_by_type',
'_single_point_answer_goal',
'_previous_axis_answer_step_for_fact',
'_point_name_from_goal_target',
'_point_scope_from_goal_target',
'_is_specific_point_coordinate_name',
'_is_generic_point_coordinate_name',
'_recipe_output_types',
'_recipe_required_creates',
'_append_unique_produces',
'_append_unique',
'_unique_ordered',
'_valid_scope_visible_from',
)

@dataclass
class NormalizationRuleContext:
    """单个 normalizer rule 执行时可读取/更新的上下文。"""

    handle_registry: CanonicalHandleRegistry
    question_goal_map: dict[str, QuestionGoal]
    recipe_output_types: dict[str, tuple[str, ...]]
    recipe_required_creates: dict[str, tuple[str, ...]] = field(default_factory=dict)
    context_resolvers_by_capability: dict[
        str,
        tuple[CapabilityContextResolver, ...],
    ] = field(default_factory=dict)
    handle_rewrites: dict[str, str] = field(default_factory=dict)
    previous_steps: list[StepIntent] = field(default_factory=list)
    published_outputs: list["_PublishedOutput"] = field(default_factory=list)
    normalized_scopes: list[StepIntentScope] = field(default_factory=list)
    current_scope_index: int = 0


@dataclass(frozen=True)
class _PublishedOutput:
    """已发布并可被后续 scope 读取的 produced output 索引项。"""

    scope_index: int
    step_index: int
    step_id: str
    step_scope_id: str
    item: ProducedFact
    identity: str
    state: str
    source_step: StepIntent


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


def _rewrite_step_reads(step: StepIntent, rewrites: dict[str, str]) -> StepIntent:
    """把前序 normalizer 产生的 handle 改名同步到当前 reads。"""
    if not rewrites:
        return step
    reads = tuple(rewrites.get(handle, handle) for handle in step.reads)
    target = rewrites.get(step.target, step.target)
    return replace(step, reads=reads, target=target)


def _handle_available(
    handle: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> bool:
    """判断 handle 当前是否已经可读或即将由当前 step 读取。"""
    if handle in step.reads:
        return True
    if handle in context.handle_registry.initial_handles:
        return True
    return handle in _available_handles(context)


def _available_handles(context: NormalizationRuleContext) -> set[str]:
    """返回 normalizer 当前已知的 initial/produced handles。"""
    handles = set(context.handle_registry.initial_handles)
    handles.update(context.handle_rewrites.values())
    for scope in context.normalized_scopes:
        for step in scope.steps:
            handles.update(item.handle for item in step.produces)
            handles.update(item.handle for item in step.creates)
    for step in context.previous_steps:
        handles.update(item.handle for item in step.produces)
        handles.update(item.handle for item in step.creates)
    return handles


def _unique_tuple(items: tuple[str, ...]) -> tuple[str, ...]:
    """保持顺序去重。"""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


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
    name = re.sub(
        r"_(?:numeric|numerical|value)_coordinate\b",
        "_coordinate",
        _semantic_name(handle),
        flags=re.IGNORECASE,
    )
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9_]*?)_coordinate(?:_[A-Za-z0-9_]+)?",
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


def _step_without_create(step: StepIntent, handle: str) -> StepIntent:
    """Remove a create handle that has been moved to an earlier step."""
    if not any(item.handle == handle for item in step.creates):
        return step
    return replace(
        step,
        creates=tuple(item for item in step.creates if item.handle != handle),
    )


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


def _visible_fact_handle_by_type(
    fact_type: str,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
    *,
    preferred: tuple[str, ...] = (),
) -> str | None:
    visible_scopes = set(handle_registry.ancestor_scopes(scope_id))
    candidates = [
        handle
        for handle in preferred
        if handle_registry.fact_types.get(handle) == fact_type
        and handle_registry.handle_valid_scopes.get(handle) in visible_scopes
    ]
    candidates.extend(
        handle
        for handle in sorted(handle_registry.fact_handles)
        if handle_registry.fact_types.get(handle) == fact_type
        and handle_registry.handle_valid_scopes.get(handle) in visible_scopes
    )
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None


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
    return bool(re.fullmatch(
        rf"{re.escape(point_name)}_"
        r"(?:(?:param|parametric|parameterized)_(?:coord|coordinate)"
        r"|(?:coord|coordinate))(?:_[A-Za-z0-9_]+)?",
        name,
        flags=re.IGNORECASE,
    ))


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


def _recipe_output_types(family_spec: SolverFamilySpec) -> dict[str, tuple[str, ...]]:
    """读取 family recipe 声明的输出类型。"""
    result: dict[str, tuple[str, ...]] = {}
    for recipe in family_spec.step_recipes:
        if recipe.execution is None:
            result[recipe.recipe_id] = ()
            continue
        result[recipe.recipe_id] = tuple(
            output_type
            for output in recipe.execution.output_aliases
            for output_type in (output.runtime_type,)
        )
    return result


def _recipe_required_creates(family_spec: SolverFamilySpec) -> dict[str, tuple[str, ...]]:
    """读取 family recipe execution 声明的 required creates。"""
    result: dict[str, tuple[str, ...]] = {}
    for recipe in family_spec.step_recipes:
        if recipe.execution is None:
            result[recipe.recipe_id] = ()
            continue
        result[recipe.recipe_id] = tuple(recipe.execution.creates)
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


def _append_unique(
    current: tuple[str, ...],
    additions: tuple[str, ...],
) -> tuple[str, ...]:
    """按顺序追加字符串项并去重。"""
    return _unique_ordered((*current, *additions))


def _unique_ordered(items: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """稳定去重，保留首次出现顺序。"""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _valid_scope_visible_from(
    valid_scope: str,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """valid_scope 是否对当前 scope 可见。"""
    return valid_scope in handle_registry.ancestor_scopes(scope_id)
