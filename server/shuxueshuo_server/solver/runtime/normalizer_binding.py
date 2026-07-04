"""Handle, visibility, and binding-oriented normalization rules."""

from __future__ import annotations

from dataclasses import replace
import re

from shuxueshuo_server.solver.question_goals import QuestionGoal
from shuxueshuo_server.solver.runtime.handle_registry import (
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
from shuxueshuo_server.solver.runtime.normalizer_common import (
    NormalizationRuleContext,
    NormalizationRuleResult,
    _PublishedOutput,
    _append_unique_produces,
    _point_name_from_coordinate_fact,
    _point_name_from_goal_target,
    _point_scope_from_goal_target,
    _rewrite_step_reads,
    _valid_scope_visible_from,
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

class _PublicOutputAliasMergeRule:
    """合并后续 scope 重复产生的已可见同状态 output alias。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        merges = _visible_public_output_alias_merges(step, context)
        if merges is None:
            return NormalizationRuleResult(step=step)

        actions: list[StepIntentNormalizationAction] = []
        for item, published in merges:
            merged_step = _append_produce_to_published_step(context, published, item)
            _register_published_item(
                context,
                item=item,
                step=merged_step,
                scope_index=published.scope_index,
                step_index=published.step_index,
            )
            actions.append(
                StepIntentNormalizationAction(
                    action="merge_visible_public_output_alias_step",
                    step_id=step.step_id,
                    target_step_id=published.step_id,
                    handle=item.handle,
                    reason=(
                        f"{published.item.handle} 已在 valid_scope={published.item.valid_scope} "
                        f"发布同一 {published.identity} 的 {published.state}；"
                        f"{item.handle} 是后续 scope 中的重复 alias，合并到前序 step。"
                    ),
                )
            )
        return NormalizationRuleResult(
            step=step,
            actions=tuple(actions),
            append_step=False,
        )

class _CommonScopeOutputPromotionRule:
    """把 sibling 复用的公共中间量提升到父 scope。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, rewrites, actions = _promote_common_scope_outputs_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(
            step=step,
            rewrites=rewrites,
            actions=tuple(actions),
        )

class _FactHandleValidScopeRule:
    """让 fact handle 的 scope 与 produces.valid_scope 保持一致。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _align_fact_handle_valid_scope_step(
            step,
            handle_registry=context.handle_registry,
        )
        return NormalizationRuleResult(step=step, actions=tuple(actions))

def _promote_common_scope_outputs_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, dict[str, str], list[StepIntentNormalizationAction]]:
    """把 ii_1 内产生、但语义属于 ii 公共状态的 fact 提升到父 scope。"""
    parent_scope = _parent_scope(step.scope_id, context.handle_registry)
    if parent_scope is None or parent_scope == "problem":
        return step, {}, []
    if not _step_reads_visible_from_scope(step, parent_scope, context):
        return step, {}, []
    rewrites: dict[str, str] = {}
    actions: list[StepIntentNormalizationAction] = []
    new_produces: list[ProducedFact] = []
    for item in step.produces:
        promoted = _promoted_common_scope_output(
            item,
            current_scope=step.scope_id,
            parent_scope=parent_scope,
        )
        if promoted is None:
            new_produces.append(item)
            continue
        rewrites[item.handle] = promoted.handle
        if promoted.handle not in {existing.handle for existing in new_produces}:
            new_produces.append(promoted)
        actions.append(
            StepIntentNormalizationAction(
                action="promote_common_scope_output",
                step_id=step.step_id,
                handle=item.handle,
                target_step_id=None,
                reason=(
                    f"{item.handle} 是可被 sibling 子问复用的公共中间状态；"
                    f"将其提升到父 scope {parent_scope}，改写为 {promoted.handle}。"
                ),
            )
        )
    if not rewrites:
        return step, {}, []
    return (
        replace(
            step,
            target=rewrites.get(step.target, step.target),
            produces=tuple(new_produces),
        ),
        rewrites,
        actions,
    )

def _parent_scope(
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """返回直接父 scope。"""
    try:
        ancestors = handle_registry.ancestor_scopes(scope_id)
    except Exception:
        return None
    if len(ancestors) < 2:
        return None
    return ancestors[1]

def _promoted_common_scope_output(
    item: ProducedFact,
    *,
    current_scope: str,
    parent_scope: str,
) -> ProducedFact | None:
    """若 produced fact 语义适合父 scope 复用，返回提升后的 item。"""
    if not item.handle.startswith("fact:"):
        return None
    handle_scope = _handle_scope(item.handle)
    if handle_scope != current_scope or item.valid_scope != current_scope:
        return None
    if handle_scope == parent_scope:
        return None
    semantic_name = _semantic_name(item.handle)
    if not _is_common_scope_semantic_name(semantic_name, item.output_type):
        return None
    return replace(
        item,
        handle=f"fact:{parent_scope}:{semantic_name}",
        valid_scope=parent_scope,
    )

def _is_common_scope_semantic_name(
    semantic_name: str,
    output_type: str | None,
) -> bool:
    """判断该 fact 是否是子问共享的中间状态，而非最终答案局部状态。"""
    if output_type == "Point" and re.fullmatch(
        r"[A-Z][A-Za-z0-9]*_coordinate(?:_expr|_expression|_parametric)?",
        semantic_name,
    ):
        return True
    if output_type == "Point" and re.fullmatch(
        r"optimal_[A-Z][A-Za-z0-9]*_coordinate(?:_expr|_expression|_parametric)?",
        semantic_name,
    ):
        return True
    if output_type == "Parabola" and any(
        token in semantic_name
        for token in ("with_param", "parametric", "_in_")
    ):
        return True
    if output_type == "PathTransformation" and "path" in semantic_name:
        return True
    if output_type == "StraighteningCandidate" and any(
        token in semantic_name for token in ("straightened", "straightening", "scheme")
    ):
        return True
    if output_type == "MinimumExpression" and "minimum" in semantic_name:
        return True
    return False

def _step_reads_visible_from_scope(
    step: StepIntent,
    scope_id: str,
    context: NormalizationRuleContext,
) -> bool:
    """只有当 step 依赖本身对父 scope 可见时，产物才可提升到父 scope。"""
    for handle in step.reads:
        read_scope = _known_handle_valid_scope(handle, context)
        if read_scope is None:
            continue
        try:
            if read_scope not in context.handle_registry.ancestor_scopes(scope_id):
                return False
        except Exception:
            return False
    return True

def _known_handle_valid_scope(
    handle: str,
    context: NormalizationRuleContext,
) -> str | None:
    """读取 normalizer 当前已知 handle 的 valid_scope。"""
    if handle in context.handle_registry.handle_valid_scopes:
        return context.handle_registry.handle_valid_scopes[handle]
    for scope in context.normalized_scopes:
        for step in scope.steps:
            for item in (*step.creates, *step.produces):
                if item.handle == handle:
                    return item.valid_scope
    for step in context.previous_steps:
        for item in (*step.creates, *step.produces):
            if item.handle == handle:
                return item.valid_scope
    return None

def _align_fact_handle_valid_scope_step(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """若 fact handle 已声明父 scope，则同步 produces.valid_scope。"""
    new_produces: list[ProducedFact] = []
    actions: list[StepIntentNormalizationAction] = []
    for item in step.produces:
        if not item.handle.startswith("fact:"):
            new_produces.append(item)
            continue
        handle_scope = _handle_scope(item.handle)
        if handle_scope == item.valid_scope:
            new_produces.append(item)
            continue
        if handle_scope not in handle_registry.ancestor_scopes(item.valid_scope):
            new_produces.append(item)
            continue
        new_produces.append(replace(item, valid_scope=handle_scope))
        actions.append(
            StepIntentNormalizationAction(
                action="align_fact_handle_valid_scope",
                step_id=step.step_id,
                handle=item.handle,
                target_step_id=None,
                reason=(
                    f"{item.handle} 的 handle scope 是 {handle_scope}，"
                    f"但 valid_scope={item.valid_scope}；按 handle scope 发布，"
                    "保证 sibling 子问可见性与 canonical handle 一致。"
                ),
            )
        )
    if not actions:
        return step, []
    return replace(step, produces=tuple(new_produces)), actions

def _visible_public_output_alias_merges(
    step: StepIntent,
    context: NormalizationRuleContext,
) -> tuple[tuple[ProducedFact, _PublishedOutput], ...] | None:
    """判断当前 step 是否只是重复发布已可见的同状态 output alias。"""
    if step.creates or not step.produces:
        return None
    if any(item.handle.startswith("answer:") for item in step.produces):
        return None

    merges: list[tuple[ProducedFact, _PublishedOutput]] = []
    for item in step.produces:
        signature = _output_identity_state(
            item,
            question_goal_map=context.question_goal_map,
            handle_registry=context.handle_registry,
        )
        if signature is None:
            return None
        published = _find_visible_public_output(
            signature,
            step=step,
            context=context,
        )
        if published is None:
            return None
        merges.append((item, published))
    return tuple(merges)

def _find_visible_public_output(
    signature: tuple[str, str],
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> _PublishedOutput | None:
    """查找对当前 step 可见且状态兼容的前序 output。"""
    identity, state = signature
    for published in reversed(context.published_outputs):
        if published.identity != identity:
            continue
        if not _output_states_compatible(published.state, state):
            continue
        if not _valid_scope_visible_from(
            published.item.valid_scope,
            step.scope_id,
            context.handle_registry,
        ):
            continue
        if not _reads_state_compatible(published.source_step, step):
            continue
        return published
    return None

def _output_identity_state(
    item: ProducedFact,
    *,
    question_goal_map: dict[str, QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, str] | None:
    """返回 produced output 的 canonical identity 与状态类型。"""
    output_type = _produced_output_type(item, handle_registry)
    if output_type != "Point":
        return None
    identity = _point_output_identity(
        item,
        question_goal_map=question_goal_map,
        handle_registry=handle_registry,
    )
    if identity is None:
        return None
    return identity, _point_coordinate_state(item)

def _point_output_identity(
    item: ProducedFact,
    *,
    question_goal_map: dict[str, QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """将 Point answer/fact 映射到 canonical point identity。"""
    if item.handle.startswith("answer:"):
        goal = question_goal_map.get(item.handle)
        if goal is None or goal.value_type != "Point":
            return None
        point_name = _point_name_from_goal_target(goal)
        point_scope = _point_scope_from_goal_target(goal)
        if point_name is None or point_scope is None:
            return None
        return f"point:{point_scope}:{point_name}"

    point_name = _point_name_from_coordinate_fact(item.handle)
    if point_name is None:
        return None
    handle_scope = _handle_scope(item.handle)
    direct = f"point:{handle_scope}:{point_name}"
    if direct in handle_registry.entity_handles:
        return direct
    visible_entities = [
        f"point:{scope}:{point_name}"
        for scope in handle_registry.ancestor_scopes(item.valid_scope)
        if f"point:{scope}:{point_name}" in handle_registry.entity_handles
    ]
    if len(visible_entities) == 1:
        return visible_entities[0]
    return direct

def _point_coordinate_state(item: ProducedFact) -> str:
    """区分同一点坐标的泛化、含参表达式和数值状态。"""
    if not item.handle.startswith("fact:"):
        return "point_coordinate"
    name = _semantic_name(item.handle).lower()
    if any(token in name for token in ("expr", "expression", "parametric")):
        return "point_coordinate_expr"
    if any(token in name for token in ("value", "numeric", "numerical")):
        return "point_coordinate_value"
    return "point_coordinate"

def _output_states_compatible(left: str, right: str) -> bool:
    """判断两个 output 状态是否可视为同一别名。"""
    if left == right:
        return True
    generic = "point_coordinate"
    return left == generic or right == generic

def _reads_state_compatible(previous: StepIntent, current: StepIntent) -> bool:
    """当前 step 不能比前序 output 多读取会改变状态的条件。"""
    return _stateful_reads(current).issubset(_stateful_reads(previous))

def _stateful_reads(step: StepIntent) -> set[str]:
    """去掉不会改变 output 状态的符号读入。"""
    return {
        handle
        for handle in step.reads
        if not handle.startswith("symbol:")
    }

def _append_produce_to_published_step(
    context: NormalizationRuleContext,
    published: _PublishedOutput,
    item: ProducedFact,
) -> StepIntent:
    """把重复 alias 追加到已发布 output 所在的 step。"""
    target_step = _published_step(context, published)
    merged = replace(
        target_step,
        produces=_append_unique_produces(target_step.produces, (item,)),
    )
    _replace_published_step(context, published, merged)
    return merged

def _published_step(
    context: NormalizationRuleContext,
    published: _PublishedOutput,
) -> StepIntent:
    """读取 published output 所属 step。"""
    if published.scope_index == context.current_scope_index:
        return context.previous_steps[published.step_index]
    return context.normalized_scopes[published.scope_index].steps[published.step_index]

def _replace_published_step(
    context: NormalizationRuleContext,
    published: _PublishedOutput,
    step: StepIntent,
) -> None:
    """替换 published output 所属 step。"""
    if published.scope_index == context.current_scope_index:
        context.previous_steps[published.step_index] = step
        return
    scope = context.normalized_scopes[published.scope_index]
    steps = list(scope.steps)
    steps[published.step_index] = step
    context.normalized_scopes[published.scope_index] = replace(
        scope,
        steps=tuple(steps),
    )

def _register_published_outputs(
    context: NormalizationRuleContext,
    step: StepIntent,
    *,
    step_index: int,
) -> None:
    """把保留 step 的 output 注册为后续可见 output。"""
    for item in step.produces:
        _register_published_item(
            context,
            item=item,
            step=step,
            scope_index=context.current_scope_index,
            step_index=step_index,
        )

def _register_published_item(
    context: NormalizationRuleContext,
    *,
    item: ProducedFact,
    step: StepIntent,
    scope_index: int,
    step_index: int,
) -> None:
    """注册单个 produced output。"""
    signature = _output_identity_state(
        item,
        question_goal_map=context.question_goal_map,
        handle_registry=context.handle_registry,
    )
    if signature is None:
        return
    identity, state = signature
    context.published_outputs.append(
        _PublishedOutput(
            scope_index=scope_index,
            step_index=step_index,
            step_id=step.step_id,
            step_scope_id=step.scope_id,
            item=item,
            identity=identity,
            state=state,
            source_step=step,
        )
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
