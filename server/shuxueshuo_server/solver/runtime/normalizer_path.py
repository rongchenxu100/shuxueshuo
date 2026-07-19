"""Path-minimum, square-reduction, and midpoint normalization rules."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any, Mapping

from shuxueshuo_server.solver.runtime.auxiliary_points import fresh_auxiliary_point_handle
from shuxueshuo_server.solver.runtime.handle_registry import (
    _handle_name,
    _handle_scope,
    _semantic_name,
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.output_type_inference import (
    produced_semantic_role,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    StepIntent,
    StepIntentNormalizationAction,
)
from shuxueshuo_server.solver.runtime.straightening_metadata import (
    STRAIGHTENING_ENDPOINT_POINT_1,
    STRAIGHTENING_ENDPOINT_POINT_2,
    collect_straightening_endpoint_handles,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import _produced_output_type
from shuxueshuo_server.solver.runtime.normalizer_binding import _register_published_outputs
from shuxueshuo_server.solver.runtime.normalizer_common import (
    NormalizationRuleContext,
    NormalizationRuleResult,
    _available_handles,
    _handle_available,
    _point_name_from_coordinate_fact,
    _rewrite_step_reads_many,
    _step_with_read,
    _unique_ordered,
    _unique_read_handles,
    _unique_tuple,
    _valid_scope_visible_from,
    _visible_fact_handle_by_type,
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

class _RecipeRequiredCreatesRule:
    """根据 recipe execution contract 自动补齐必需的辅助实体。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _ensure_required_recipe_creates(
            step,
            context=context,
        )
        return NormalizationRuleResult(step=step, actions=tuple(actions))

class _BrokenPathMinimumEndpointProducesRule:
    """让将军饮马 recipe 显式暴露最短线段端点。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, actions = _ensure_broken_path_minimum_endpoint_produces(
            step,
            handle_registry=context.handle_registry,
        )
        return NormalizationRuleResult(step=step, actions=tuple(actions))

class _PathTransformationBackfillRule:
    """为折线拉直/最值 recipe 补齐 PathTransformation prerequisite。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        backfill_step, output_handle, action = _path_transformation_backfill_for_step(
            step,
            context=context,
        )
        if output_handle is None or action is None:
            return NormalizationRuleResult(step=step)
        if backfill_step is not None:
            context.previous_steps.append(backfill_step)
            _register_published_outputs(
                context,
                backfill_step,
                step_index=len(context.previous_steps) - 1,
            )
        return NormalizationRuleResult(
            step=_step_with_read(step, output_handle),
            actions=(action,),
        )

class _StraightenedDistanceEndpointReadsRule:
    """让拉直后求距离 step 读取前序 recipe 已确定的最短线段端点。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, action = _add_straightened_distance_endpoint_reads(
            step,
            context=context,
        )
        return NormalizationRuleResult(
            step=step,
            actions=(action,) if action is not None else (),
        )

class _SquarePathLocusBackfillRule:
    """在 normalizer 层补齐 square 降维后进入将军饮马所需的轨迹线 prerequisite。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        backfill_step, output_handle, action = _square_path_locus_backfill_for_step(
            step,
            context=context,
        )
        if output_handle is None or action is None:
            return NormalizationRuleResult(step=step)
        if backfill_step is not None:
            context.previous_steps.append(backfill_step)
            _register_published_outputs(
                context,
                backfill_step,
                step_index=len(context.previous_steps) - 1,
            )
        return NormalizationRuleResult(
            step=_step_with_read(step, output_handle),
            actions=(action,),
        )

class _MidpointCoordinateBackfillRule:
    """根据 midpoint definition 自动补齐路径最值需要的中点坐标 step。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        midpoint_step, output_handle, action = _midpoint_backfill_for_step(
            step,
            context=context,
        )
        if output_handle is None or action is None:
            return NormalizationRuleResult(step=step)
        if midpoint_step is not None:
            context.previous_steps.append(midpoint_step)
            _register_published_outputs(
                context,
                midpoint_step,
                step_index=len(context.previous_steps) - 1,
            )
        return NormalizationRuleResult(
            step=_step_with_read(step, output_handle),
            actions=(action,),
        )

class _MidpointDefinitionReadCompletionRule:
    """midpoint_point 少读 midpoint_definition 时自动补齐结构事实。"""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        step, action = _add_midpoint_definition_read_for_step(
            step,
            context=context,
        )
        return NormalizationRuleResult(
            step=step,
            actions=(action,) if action is not None else (),
        )

def _ensure_required_recipe_creates(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """按 recipe execution contract 补齐 LLM 省略的辅助 entity creates。"""
    if step.recipe_hint is None:
        return step, []
    required = context.recipe_required_creates.get(step.recipe_hint, ())
    if not required:
        return step, []

    creates = list(step.creates)
    actions: list[StepIntentNormalizationAction] = []
    for entity_type in required:
        if any(item.entity_type == entity_type for item in creates):
            continue
        created = _fresh_required_created_entity(
            entity_type,
            step=step,
            context=context,
            pending_creates=tuple(creates),
        )
        if created is None:
            continue
        creates.append(created)
        actions.append(
            StepIntentNormalizationAction(
                action="auto_create_required_recipe_entity",
                step_id=step.step_id,
                handle=created.handle,
                target_step_id=None,
                reason=(
                    f"{step.recipe_hint} 的 execution contract 声明需要创建 "
                    f"{entity_type}；LLM 未提供 creates，系统自动补齐辅助实体。"
                ),
            )
        )
    if not actions:
        return step, []
    return replace(step, creates=tuple(creates)), actions


def _fresh_required_created_entity(
    entity_type: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
    pending_creates: tuple[CreatedEntity, ...],
) -> CreatedEntity | None:
    """构造当前 scope 下未占用的辅助 entity。"""
    if entity_type != "point":
        return None
    scope_id = _required_create_scope(step)
    used = set(context.handle_registry.entity_handles)
    for previous in context.previous_steps:
        used.update(item.handle for item in previous.creates)
    for scope in context.normalized_scopes:
        for previous in scope.steps:
            used.update(item.handle for item in previous.creates)
    used.update(item.handle for item in pending_creates)
    handle = fresh_auxiliary_point_handle(scope_id, used)
    if handle is None:
        return None
    return CreatedEntity(
        handle=handle,
        entity_type="point",
        valid_scope=scope_id,
        description=f"{step.recipe_hint} 自动创建的辅助点",
    )


def _required_create_scope(step: StepIntent) -> str:
    """辅助 entity 跟随 recipe 主要非 answer 产物的可见 scope。"""
    for item in step.produces:
        if item.handle.startswith("answer:"):
            continue
        if item.valid_scope:
            return item.valid_scope
    return step.scope_id


def _midpoint_backfill_for_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent | None, str | None, StepIntentNormalizationAction | None]:
    """若路径步骤需要 midpoint 点但坐标未产出，插入 midpoint_point step。"""
    if not _step_can_need_midpoint_backfill(step):
        return None, None, None
    midpoint_fact = _visible_midpoint_fact(step, context)
    if midpoint_fact is None:
        return None, None, None
    output_scope = _handle_scope(midpoint_fact)
    midpoint_name, endpoint_names = _parse_midpoint_fact(
        midpoint_fact,
        handle_registry=context.handle_registry,
        point_names=_visible_point_names(scope_id=output_scope, context=context),
    )
    if midpoint_name is None or endpoint_names is None:
        return None, None, None
    output_handle = f"fact:{output_scope}:{midpoint_name}_coordinate_expr"
    if _handle_available(output_handle, step=step, context=context):
        return None, None, None
    existing_coordinate = _visible_point_coordinate_handle_by_name(
        midpoint_name,
        scope_id=output_scope,
        context=context,
    )
    if existing_coordinate is not None:
        return (
            None,
            existing_coordinate,
            StepIntentNormalizationAction(
                action="reuse_existing_midpoint_coordinate_fact",
                step_id=step.step_id,
                target_step_id=None,
                handle=existing_coordinate,
                reason=(
                    f"{midpoint_name} 的坐标状态已由前序可见 fact "
                    f"{existing_coordinate} 表达；复用该 read，避免再插入重复的"
                    " midpoint_point backfill step。"
                ),
            ),
        )
    point_handle = _visible_point_handle_by_name(
        midpoint_name,
        scope_id=output_scope,
        context=context,
    )
    if point_handle is None:
        return None, None, None
    endpoint_point_handles: list[str] = []
    endpoint_coordinate_handles: list[str] = []
    for name in endpoint_names:
        endpoint_point = _visible_point_handle_by_name(
            name,
            scope_id=output_scope,
            context=context,
        )
        endpoint_coordinate = _visible_point_coordinate_handle_by_name(
            name,
            scope_id=output_scope,
            context=context,
        )
        if endpoint_point is None or endpoint_coordinate is None:
            return None, None, None
        endpoint_point_handles.append(endpoint_point)
        endpoint_coordinate_handles.append(endpoint_coordinate)
    reads = _unique_tuple((
        *endpoint_point_handles,
        *endpoint_coordinate_handles,
        midpoint_fact,
    ))
    midpoint_step = StepIntent(
        step_id=f"derive_{midpoint_name}_coordinate_expr",
        scope_id=step.scope_id,
        goal_type="derive_midpoint",
        target=output_handle,
        strategy=f"由 {midpoint_name} 是 {''.join(endpoint_names)} 的中点求坐标",
        reason="路径最值步骤需要该中点坐标，题面已经给出 midpoint definition。",
        recipe_hint="midpoint_point",
        reads=reads,
        creates=(),
        produces=(
            ProducedFact(
                handle=output_handle,
                valid_scope=output_scope,
                description=f"{midpoint_name} 坐标（由中点定义自动补齐）",
                output_type="Point",
            ),
        ),
    )
    action = StepIntentNormalizationAction(
        action="insert_midpoint_coordinate_backfill_step",
        step_id=midpoint_step.step_id,
        target_step_id=step.step_id,
        handle=output_handle,
        reason=(
            f"{step.step_id} 需要路径最值端点 {midpoint_name} 的坐标；"
            f"根据 {midpoint_fact} 和已可见端点坐标自动插入 midpoint_point step。"
        ),
    )
    return midpoint_step, output_handle, action

def _add_midpoint_definition_read_for_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, StepIntentNormalizationAction | None]:
    """为显式 midpoint_point step 补齐同目标点的 midpoint_definition read。"""
    if step.recipe_hint != "midpoint_point":
        return step, None
    if any(context.handle_registry.fact_types.get(handle) == "midpoint_definition" for handle in step.reads):
        return step, None
    midpoint_name = _midpoint_output_point_name(step)
    if midpoint_name is None:
        return step, None
    midpoint_fact = _visible_midpoint_fact_for_name(
        midpoint_name,
        step=step,
        context=context,
    )
    if midpoint_fact is None:
        return step, None
    return (
        _step_with_read(step, midpoint_fact),
        StepIntentNormalizationAction(
            action="add_midpoint_definition_read",
            step_id=step.step_id,
            target_step_id=None,
            handle=midpoint_fact,
            reason=(
                f"{step.recipe_hint} 的目标点是 {midpoint_name}；"
                "题面存在唯一可见 midpoint_definition，自动补齐该结构 read。"
            ),
        ),
    )

def _midpoint_output_point_name(step: StepIntent) -> str | None:
    """从 midpoint_point 的 target/produces 推断中点名。"""
    candidates: list[str] = []
    target_name = _point_name_from_coordinate_fact(step.target)
    if target_name is not None:
        candidates.append(target_name)
    for item in step.produces:
        name = _point_name_from_coordinate_fact(item.handle)
        if name is not None:
            candidates.append(name)
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None

def _visible_midpoint_fact_for_name(
    midpoint_name: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    """查找当前 step 可见且指向指定中点的 midpoint_definition。"""
    candidates: list[str] = []
    for handle, fact_type in context.handle_registry.fact_types.items():
        if fact_type != "midpoint_definition":
            continue
        if not _valid_scope_visible_from(
            context.handle_registry.handle_valid_scopes.get(handle, _handle_scope(handle)),
            step.scope_id,
            context.handle_registry,
        ):
            continue
        name, _endpoint_names = _parse_midpoint_fact(
            handle,
            handle_registry=context.handle_registry,
        )
        if name == midpoint_name:
            candidates.append(handle)
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None

def _step_can_need_midpoint_backfill(step: StepIntent) -> bool:
    """判断当前 step 是否属于会消费中点坐标的路径/最值链路。"""
    return step.recipe_hint in {
        "two_moving_points_path_reduction",
        "broken_path_straightening_and_select",
        "broken_path_straightening_minimum_expression",
        "path_minimum_by_straightened_distance",
        "distance_between_points",
    }

def _visible_midpoint_fact(
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    """返回当前 scope 可见且最可能相关的 midpoint fact。"""
    candidates = [
        handle for handle, fact_type in context.handle_registry.fact_types.items()
        if fact_type == "midpoint_definition"
        and _valid_scope_visible_from(_handle_scope(handle), step.scope_id, context.handle_registry)
    ]
    if not candidates:
        return None
    point_reads = {
        _handle_name(handle)
        for handle in step.reads
        if handle.startswith("point:")
    }
    for handle in candidates:
        midpoint_name, _endpoint_names = _parse_midpoint_fact(
            handle,
            handle_registry=context.handle_registry,
        )
        if midpoint_name in point_reads:
            return handle
    return candidates[0] if len(candidates) == 1 else None

def _parse_midpoint_fact(
    handle: str,
    *,
    handle_registry: CanonicalHandleRegistry | None = None,
    point_names: set[str] | None = None,
) -> tuple[str | None, tuple[str, str] | None]:
    """解析 midpoint_definition，优先读结构化 payload，命名只作为兼容 fallback。"""
    if not handle.startswith("fact:"):
        return None, None
    midpoint_name, endpoint_names = _parse_midpoint_fact_payload(
        handle,
        handle_registry=handle_registry,
        point_names=point_names,
    )
    if midpoint_name is not None and endpoint_names is not None:
        return midpoint_name, endpoint_names
    semantic_name = _semantic_name(handle)
    prefix, separator, endpoint_text = semantic_name.partition("_midpoint_of_")
    if not separator or not _point_name_looks_valid(prefix):
        return None, None
    endpoint_names = _parse_midpoint_endpoint_names(endpoint_text, point_names=point_names)
    if endpoint_names is not None:
        return prefix, endpoint_names
    compact_match = re.fullmatch(
        r"(?P<mid>[A-Za-z][A-Za-z0-9]*)_midpoint_of_(?P<a>[A-Za-z])(?P<b>[A-Za-z])",
        semantic_name,
    )
    if compact_match is not None:
        return compact_match.group("mid"), (compact_match.group("a"), compact_match.group("b"))
    return prefix, None

def _parse_midpoint_fact_payload(
    handle: str,
    *,
    handle_registry: CanonicalHandleRegistry | None,
    point_names: set[str] | None,
) -> tuple[str | None, tuple[str, str] | None]:
    """从 canonical midpoint_definition payload 读取中点和两个端点。"""
    if handle_registry is None:
        return None, None
    if handle_registry.fact_types.get(handle) != "midpoint_definition":
        return None, None
    payload = handle_registry.fact_payloads.get(handle)
    if not isinstance(payload, Mapping):
        return None, None
    midpoint_name = _point_name_from_payload_ref(payload.get("point"))
    raw_endpoints = payload.get("of")
    if (
        midpoint_name is None
        or not isinstance(raw_endpoints, list)
        or len(raw_endpoints) != 2
    ):
        return None, None
    endpoint_names = tuple(
        _point_name_from_payload_ref(item) for item in raw_endpoints
    )
    if endpoint_names[0] is None or endpoint_names[1] is None:
        return None, None
    endpoints = (endpoint_names[0], endpoint_names[1])
    if point_names is not None and not all(name in point_names for name in endpoints):
        return midpoint_name, None
    return midpoint_name, endpoints

def _point_name_from_payload_ref(value: Any) -> str | None:
    """Return a point name from either ``point:<scope>:<name>`` or a bare name."""
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("point:"):
        parts = value.split(":", 2)
        if len(parts) != 3:
            return None
        name = parts[2]
        return name if _point_name_looks_valid(name) else None
    return value if _point_name_looks_valid(value) else None

def _parse_midpoint_endpoint_names(
    endpoint_text: str,
    *,
    point_names: set[str] | None = None,
) -> tuple[str, str] | None:
    """解析 midpoint_of 后面的两个端点名。"""
    if len(endpoint_text) == 2 and endpoint_text.isalpha():
        endpoints = (endpoint_text[0], endpoint_text[1])
        if point_names is None or all(name in point_names for name in endpoints):
            return endpoints
    if "_" not in endpoint_text:
        return None
    parts = endpoint_text.split("_")
    candidates: list[tuple[str, str]] = []
    for split_index in range(1, len(parts)):
        left = "_".join(parts[:split_index])
        right = "_".join(parts[split_index:])
        if _point_name_looks_valid(left) and _point_name_looks_valid(right):
            candidates.append((left, right))
    if point_names is not None:
        visible_candidates = [
            candidate for candidate in candidates
            if candidate[0] in point_names and candidate[1] in point_names
        ]
        return visible_candidates[0] if len(visible_candidates) == 1 else None
    return candidates[0] if candidates else None

def _point_name_looks_valid(name: str) -> bool:
    return re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is not None

def _visible_point_handle_by_name(
    name: str,
    *,
    scope_id: str,
    context: NormalizationRuleContext,
) -> str | None:
    """按当前 scope 可见性查找点 handle。"""
    for scope in context.handle_registry.ancestor_scopes(scope_id):
        handle = f"point:{scope}:{name}"
        if handle in context.handle_registry.entity_handles:
            return handle
    return None

def _visible_point_names(
    *,
    scope_id: str,
    context: NormalizationRuleContext,
) -> set[str]:
    """返回当前 scope 可见的点实体名。"""
    visible_scopes = set(context.handle_registry.ancestor_scopes(scope_id))
    return {
        _handle_name(handle)
        for handle in context.handle_registry.entity_handles
        if handle.startswith("point:")
        and _handle_scope(handle) in visible_scopes
    }

def _visible_point_coordinate_handle_by_name(
    name: str,
    *,
    scope_id: str,
    context: NormalizationRuleContext,
) -> str | None:
    """查找当前 scope 可见的某点坐标 fact。"""
    candidates: list[str] = []
    for handle in _available_handles(context):
        if not handle.startswith("fact:"):
            continue
        point_name = _point_name_from_coordinate_fact(handle)
        if point_name != name:
            continue
        try:
            if not _valid_scope_visible_from(
                _handle_scope(handle),
                scope_id,
                context.handle_registry,
            ):
                continue
        except Exception:
            continue
        candidates.append(handle)
    return _preferred_coordinate_handle(candidates)

def _preferred_coordinate_handle(candidates: list[str]) -> str | None:
    """优先选择泛化/含参坐标，而不是 value-only alias。"""
    if not candidates:
        return None
    for handle in candidates:
        name = _semantic_name(handle).lower()
        if name.endswith("_coordinate") or name.endswith("_coordinate_expr"):
            return handle
    return candidates[0]

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
    point_1 = _minimum_point_fact(scope_id, STRAIGHTENING_ENDPOINT_POINT_1, "拉直后最短线段的第一个端点")
    point_2 = _minimum_point_fact(scope_id, STRAIGHTENING_ENDPOINT_POINT_2, "拉直后最短线段的第二个端点")
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
    reduction_read_rewrites: dict[str, tuple[str, ...]] = {}
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
            structural_facts = _square_pre_reduction_structural_fact_reads(
                step,
                handle_registry,
            )
            if not structural_facts:
                continue
            if not (
                any(handle in reduction_reads for handle in produced_handles)
                or all(handle in reduction_reads for handle in structural_facts)
            ):
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
            for handle in produced_handles:
                if handle in reduction_reads:
                    reduction_read_rewrites[handle] = structural_facts
            actions.append(
                StepIntentNormalizationAction(
                    action="drop_square_pre_reduction_point_utility_step",
                    step_id=step.step_id,
                    target_step_id=reduction_step.step_id,
                    handle=",".join((*produced_handles, *structural_facts)),
                    reason=(
                        "square_path_dimension_reduction 只需要正方形/中点/中心/路径结构 fact；"
                        "该 Point utility step 只是提前计算结构点坐标，删除后让降维先执行并通过 "
                        "planner insight 告诉后续真实 moving_point。"
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
                reads=_rewrite_square_reduction_reads(
                    step.reads,
                    dropped_handles=dropped_handles,
                    rewrites=reduction_read_rewrites,
                ),
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
    if step.recipe_hint not in {None, "midpoint_point"} or step.creates:
        return False
    if not step.produces:
        return False
    if any(item.handle.startswith("answer:") for item in step.produces):
        return False
    if not all(_produced_output_type(item, handle_registry) == "Point" for item in step.produces):
        return False
    return bool(_square_pre_reduction_structural_fact_reads(step, handle_registry))

def _square_pre_reduction_structural_fact_reads(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """返回 square reduction 可直接消费的结构事实 reads。"""
    structural_fact_types = {"midpoint_definition", "square_center"}
    return tuple(
        handle
        for handle in step.reads
        if handle_registry.fact_types.get(handle) in structural_fact_types
    )

def _rewrite_square_reduction_reads(
    reads: tuple[str, ...],
    *,
    dropped_handles: set[str],
    rewrites: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """把 reduction 对结构点坐标的 reads 改回 midpoint/center 结构 facts。"""
    result: list[str] = []
    seen: set[str] = set()
    for handle in reads:
        replacements = rewrites.get(handle)
        if replacements is None and handle in dropped_handles:
            continue
        for replacement in replacements or (handle,):
            if replacement in seen:
                continue
            seen.add(replacement)
            result.append(replacement)
    return tuple(result)

def _fold_internal_equation_utility_steps_for_scope(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
    """把无 hint 的中间 Equation/Expression utility 合并到唯一消费者 step。"""
    if len(steps) < 2:
        return steps, []
    replacements: dict[str, tuple[str, ...]] = {}
    dropped_step_ids: set[str] = set()
    actions: list[StepIntentNormalizationAction] = []
    for index, step in enumerate(steps):
        if not _is_internal_equation_utility_step(step, handle_registry):
            continue
        produced = step.produces[0].handle
        consumer_indices = [
            later_index for later_index, later in enumerate(steps[index + 1:], start=index + 1)
            if produced in later.reads
        ]
        if len(consumer_indices) != 1:
            continue
        consumer = steps[consumer_indices[0]]
        if not _can_absorb_internal_equation_utility(consumer):
            continue
        replacements[produced] = step.reads
        dropped_step_ids.add(step.step_id)
        actions.append(
            StepIntentNormalizationAction(
                action="fold_internal_equation_utility_step",
                step_id=step.step_id,
                target_step_id=consumer.step_id,
                handle=produced,
                reason=(
                    "该无 recipe_hint 的 Equation/Expression 是后续可执行参数求解 step "
                    "的内部中间关系；将其 reads 合并到消费者并删除 utility step。"
                ),
            )
        )

    if not dropped_step_ids:
        return steps, []

    result: list[StepIntent] = []
    for step in steps:
        if step.step_id in dropped_step_ids:
            continue
        reads = _rewrite_reads_with_tuple_replacements(step.reads, replacements)
        result.append(replace(step, reads=reads) if reads != step.reads else step)
    return tuple(result), actions


def _is_internal_equation_utility_step(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否是可折叠的中间代数关系 utility。"""
    if step.recipe_hint is not None:
        return False
    if step.creates:
        return False
    if len(step.produces) != 1:
        return False
    produced = step.produces[0]
    if produced.handle.startswith("answer:"):
        return False
    output_type = _produced_output_type(produced, handle_registry) or produced.output_type
    return output_type in {"Equation", "Expression"}


def _can_absorb_internal_equation_utility(step: StepIntent) -> bool:
    """只让明确可执行的参数求解 step 吸收内部代数关系。"""
    return step.recipe_hint is not None and step.recipe_hint.startswith("parameter_from_")


def _rewrite_reads_with_tuple_replacements(
    reads: tuple[str, ...],
    replacements: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for handle in reads:
        for replacement in replacements.get(handle, (handle,)):
            if replacement in seen:
                continue
            seen.add(replacement)
            result.append(replacement)
    return tuple(result)


def _ensure_broken_path_minimum_endpoint_produces(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntent, list[StepIntentNormalizationAction]]:
    """给将军饮马 recipe step 补端点 Point fact。"""
    if step.recipe_hint not in {
        "broken_path_straightening_minimum_expression",
        "broken_path_straightening_and_select",
    }:
        return step, []
    existing_roles = {
        role
        for item in step.produces
        if _produced_output_type(item, handle_registry) == "Point"
        for role in (
            STRAIGHTENING_ENDPOINT_POINT_1,
            STRAIGHTENING_ENDPOINT_POINT_2,
        )
        if produced_semantic_role(item) == role
        or produced_semantic_role(item).endswith(f"_{role}")
    }
    output_scope = _straightening_endpoint_output_scope(
        step,
        handle_registry=handle_registry,
    )
    point_1 = _minimum_point_fact(output_scope, STRAIGHTENING_ENDPOINT_POINT_1, "拉直后最短线段的第一个端点")
    point_2 = _minimum_point_fact(output_scope, STRAIGHTENING_ENDPOINT_POINT_2, "拉直后最短线段的第二个端点")
    additions = tuple(
        item for item in (point_1, point_2)
        if _semantic_name(item.handle) not in existing_roles
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
                    "将军饮马 recipe 内部会选择拉直方案并确定最短线段；"
                    "补充暴露最短线段端点，供后续最小值表达式或最短状态点读取。"
                ),
            )
        ],
    )
def _straightening_endpoint_output_scope(
    step: StepIntent,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> str:
    """端点 metadata 跟随 recipe 的公共产物 scope。"""
    for item in step.produces:
        if _produced_output_type(item, handle_registry) in {
            "MinimumExpression",
            "StraighteningCandidate",
        }:
            return item.valid_scope
    return step.scope_id

def _path_transformation_backfill_for_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent | None, str | None, StepIntentNormalizationAction | None]:
    """为依赖路径降维的 recipe 复用或插入 PathTransformation step。"""
    if step.recipe_hint not in {
        "broken_path_straightening_and_select",
        "broken_path_straightening_minimum_expression",
    }:
        return None, None, None
    existing = _visible_path_transformation_handle(step, context)
    if existing is not None:
        if existing in step.reads:
            return None, None, None
        return (
            None,
            existing,
            StepIntentNormalizationAction(
                action="add_path_transformation_read",
                step_id=step.step_id,
                target_step_id=None,
                handle=existing,
                reason=(
                    f"{step.recipe_hint} 需要 PathTransformation；"
                    "前序已存在唯一可见路径降维状态，自动加入 read。"
                ),
            ),
        )
    if step.recipe_hint != "broken_path_straightening_minimum_expression":
        return None, None, None
    if _step_reads_path_or_straightening_state(step, context):
        return None, None, None
    path_target = _visible_fact_handle_by_type(
        "path_minimum_target",
        step.scope_id,
        context.handle_registry,
        preferred=step.reads,
    )
    if path_target is None:
        return None, None, None
    output_scope = _primary_non_answer_output_scope(step)
    output_handle = f"fact:{output_scope}:path_transformation"
    if _handle_available(output_handle, step=step, context=context):
        return (
            None,
            output_handle,
            StepIntentNormalizationAction(
                action="add_path_transformation_read",
                step_id=step.step_id,
                target_step_id=None,
                handle=output_handle,
                reason=(
                    "当前 recipe 需要 PathTransformation；"
                    f"{output_handle} 已可见，自动加入 read。"
                ),
            ),
        )
    backfill_step = StepIntent(
        scope_id=step.scope_id,
        step_id=_unique_generated_step_id(
            f"{step.step_id}_reduce_path",
            (*context.previous_steps, step),
        ),
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target=output_handle,
        strategy="先把两动点路径降维为单动点折线路径，供后续折线拉直最值 recipe 使用。",
        reads=_unique_tuple((*step.reads, path_target)),
        creates=(),
        produces=(
            ProducedFact(
                output_handle,
                output_scope,
                "由 path_minimum_target 和动点约束得到的路径降维状态",
                output_type="PathTransformation",
            ),
        ),
        reason=(
            "broken_path_straightening_minimum_expression 需要 PathTransformation；"
            "当前 draft 省略了路径降维 prerequisite，系统插入公开 recipe step。"
        ),
    )
    return (
        backfill_step,
        output_handle,
        StepIntentNormalizationAction(
            action="insert_path_transformation_backfill_step",
            step_id=step.step_id,
            target_step_id=backfill_step.step_id,
            handle=output_handle,
            reason=(
                "当前折线最值 recipe 缺少 PathTransformation read；"
                "根据可见 path_minimum_target 插入 two_moving_points_path_reduction prerequisite。"
            ),
        ),
    )

def _visible_path_transformation_handle(
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    """查找当前 step 唯一可见的 PathTransformation output。"""
    candidates: list[str] = []
    for previous in context.previous_steps:
        for item in previous.produces:
            if _produced_output_type(item, context.handle_registry) != "PathTransformation":
                continue
            if not _valid_scope_visible_from(
                item.valid_scope,
                step.scope_id,
                context.handle_registry,
            ):
                continue
            candidates.append(item.handle)
    for scope in context.normalized_scopes:
        for previous in scope.steps:
            for item in previous.produces:
                if _produced_output_type(item, context.handle_registry) != "PathTransformation":
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

def _step_reads_path_or_straightening_state(
    step: StepIntent,
    context: NormalizationRuleContext,
) -> bool:
    """判断 LLM 是否已经显式读取某种路径降维/拉直中间状态。

    ``fact_type`` is the authoritative path. The semantic-name token fallback is
    a conservative compatibility shim for legacy/dynamic facts not yet surfaced
    with structured runtime type metadata; false negatives only insert an extra
    backfill candidate. Long-term this should use shared output type inference.
    """
    for handle in step.reads:
        fact_type = context.handle_registry.fact_types.get(handle, "")
        if fact_type in {"path_transformation", "straightening_candidate"}:
            return True
        name = _semantic_name(handle).lower() if handle.startswith("fact:") else handle.lower()
        if any(
            token in name
            for token in (
                "path_transformation",
                "path_reduction",
                "reduced_path",
                "straightened",
                "straightening",
                "selected_candidate",
                "straightened_scheme",
            )
        ):
            return True
    return False

def _primary_non_answer_output_scope(step: StepIntent) -> str:
    """读取 step 主要非 answer 产物 scope，作为 prerequisite 输出 scope。"""
    for item in step.produces:
        if item.handle.startswith("answer:"):
            continue
        return item.valid_scope
    return step.scope_id

def _add_straightened_distance_endpoint_reads(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent, StepIntentNormalizationAction | None]:
    """让 split minimum step 使用前序 selected candidate 的端点，而不是重猜点 reads。"""
    if step.recipe_hint != "path_minimum_by_straightened_distance":
        return step, None
    endpoints = _visible_straightening_endpoint_handles(step, context)
    if endpoints is None:
        return step, None
    missing = tuple(handle for handle in endpoints if handle not in step.reads)
    if not missing:
        return step, None
    return (
        replace(step, reads=_unique_tuple((*step.reads, *missing))),
        StepIntentNormalizationAction(
            action="add_straightened_distance_endpoint_reads",
            step_id=step.step_id,
            handle=",".join(missing),
            reason=(
                "前序折线拉直 recipe 已确定最短线段端点；"
                "拉直后距离求最小值应读取这些 endpoint metadata，避免继续使用旧的手写点 reads。"
            ),
        ),
    )

def _visible_straightening_endpoint_handles(
    step: StepIntent,
    context: NormalizationRuleContext,
) -> tuple[str, str] | None:
    """返回当前 step 可见的 path_minimum_point_1/2 fact handles。"""
    candidates: list[tuple[str, str]] = []
    for previous in context.previous_steps:
        for item in previous.produces:
            if not item.handle.startswith("fact:"):
                continue
            semantic_name = _semantic_name(item.handle)
            if item.output_type != "Point":
                continue
            if not _valid_scope_visible_from(
                item.valid_scope,
                step.scope_id,
                context.handle_registry,
            ):
                continue
            candidates.append((semantic_name, item.handle))
    return collect_straightening_endpoint_handles(candidates)

def _minimum_point_fact(scope_id: str, name: str, description: str) -> ProducedFact:
    """构造拉直 recipe 暴露的最短线段端点 fact。"""
    return ProducedFact(
        handle=f"fact:{scope_id}:{name}",
        valid_scope=scope_id,
        description=description,
        output_type="Point",
    )

def _square_path_locus_backfill_for_step(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[StepIntent | None, str | None, StepIntentNormalizationAction | None]:
    """由已明确的 square 降维状态补出 moving point 轨迹线 step。

    这条规则只消费 normalized draft 中已经存在的结构事实和参数化点状态：
    ``square_path_dimension_reduction`` 必须已被当前 minimum step 读取，且
    path target、square vertices、前序参数化点状态三者只能共同指向一个 moving point。
    无法唯一确定时不猜测，留给 candidate/runtime feedback。
    """
    if step.recipe_hint != "broken_path_straightening_minimum_expression":
        return None, None, None
    reduction_step = _latest_read_square_reduction_step(step, context)
    if reduction_step is None:
        return None, None, None
    candidate = _square_reduction_locus_candidate(
        reduction_step,
        step=step,
        context=context,
    )
    if candidate is None:
        return None, None, None
    point_name, point_handle, parametric_handle = candidate
    output_handle = f"fact:{step.scope_id}:{point_name}_locus_line"
    if output_handle in step.reads:
        return None, None, None
    if _handle_available(output_handle, step=step, context=context):
        return (
            None,
            output_handle,
            StepIntentNormalizationAction(
                action="add_square_path_locus_line_read",
                step_id=step.step_id,
                handle=output_handle,
                reason=(
                    "前序已产生 square 降维 moving point 的轨迹线；"
                    "将军饮马最值 step 应显式读取该 Line prerequisite。"
                ),
            ),
        )
    existing_steps = (*context.previous_steps, step)
    backfill_step = StepIntent(
        scope_id=step.scope_id,
        step_id=_unique_generated_step_id(
            f"derive_{point_name}_locus_line",
            existing_steps,
        ),
        recipe_hint="parameterized_point_locus_line",
        goal_type="derive_parameterized_point_locus_line",
        target=output_handle,
        strategy="由 square 降维后的 moving point 参数化坐标，先求进入折线拉直所需的轨迹直线。",
        reads=tuple(
            _unique_ordered(
                [
                    parametric_handle,
                    point_handle,
                ]
            )
        ),
        produces=(
            ProducedFact(
                output_handle,
                step.scope_id,
                "由参数化动点坐标得到的轨迹直线",
                output_type="Line",
            ),
        ),
        reason=(
            "square_path_dimension_reduction 已把多段路径降为单动点折线；"
            "broken_path_straightening_minimum_expression 需要先读取该动点的 Line 轨迹。"
        ),
    )
    return (
        backfill_step,
        output_handle,
        StepIntentNormalizationAction(
            action="insert_square_path_locus_line_backfill_step",
            step_id=step.step_id,
            target_step_id=backfill_step.step_id,
            handle=output_handle,
            reason=(
                "当前 draft 已唯一给出 square 降维 moving point 的参数化坐标；"
                "在将军饮马最值 step 前插入 parameterized_point_locus_line prerequisite。"
            ),
        ),
    )

def _latest_read_square_reduction_step(
    step: StepIntent,
    context: NormalizationRuleContext,
) -> StepIntent | None:
    """返回当前 minimum step 显式读取的最近 square_path_dimension_reduction step。"""
    for previous in reversed(context.previous_steps):
        if previous.recipe_hint != "square_path_dimension_reduction":
            continue
        produced = {
            item.handle
            for item in previous.produces
            if _produced_output_type(item, context.handle_registry) == "PathTransformation"
        }
        if any(handle in step.reads for handle in produced):
            return previous
    return None

def _square_reduction_locus_candidate(
    reduction_step: StepIntent,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> tuple[str, str, str] | None:
    """从 square/path/parametric state 三者交集确定唯一 moving point。"""
    square_fact = _unique_fact_read_by_type(
        reduction_step.reads,
        "square",
        step=step,
        context=context,
    )
    target_fact = _unique_fact_read_by_type(
        reduction_step.reads,
        "path_minimum_target",
        step=step,
        context=context,
    )
    if square_fact is None or target_fact is None:
        return None
    square_vertices = _square_vertex_handles(square_fact, context.handle_registry)
    path_points = _path_target_point_handles(target_fact, step=step, context=context)
    if not square_vertices or not path_points:
        return None
    candidates: list[tuple[str, str, str]] = []
    for previous in context.previous_steps:
        for item in previous.produces:
            if _produced_output_type(item, context.handle_registry) != "Point":
                continue
            point_name = _parameterized_point_state_name(_semantic_name(item.handle))
            if point_name is None:
                continue
            point_handle = _visible_point_handle_by_name(
                point_name,
                scope_id=step.scope_id,
                context=context,
            )
            if point_handle is None:
                continue
            if point_handle not in square_vertices or point_handle not in path_points:
                continue
            if not _valid_scope_visible_from(
                item.valid_scope,
                step.scope_id,
                context.handle_registry,
            ):
                continue
            candidates.append((point_name, point_handle, item.handle))
    unique = _unique_locus_candidates(candidates)
    return unique[0] if len(unique) == 1 else None

def _unique_fact_read_by_type(
    reads: tuple[str, ...],
    fact_type: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    candidates = [
        handle
        for handle in reads
        if context.handle_registry.fact_types.get(handle) == fact_type
        and _valid_scope_visible_from(
            context.handle_registry.handle_valid_scopes.get(handle, _handle_scope(handle)),
            step.scope_id,
            context.handle_registry,
        )
    ]
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None

def _square_vertex_handles(
    square_fact: str,
    handle_registry: CanonicalHandleRegistry,
) -> set[str]:
    payload = handle_registry.fact_payloads.get(square_fact, {})
    vertices = payload.get("vertices")
    if not isinstance(vertices, list):
        return set()
    return {handle for handle in vertices if isinstance(handle, str)}

def _path_target_point_handles(
    target_fact: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> set[str]:
    payload = context.handle_registry.fact_payloads.get(target_fact, {})
    path = payload.get("path")
    handles: list[str] = []
    if isinstance(path, list):
        for item in path:
            if (
                isinstance(item, list)
                and len(item) == 2
                and all(isinstance(handle, str) for handle in item)
            ):
                handles.extend(item)
        return set(handles)
    if isinstance(path, str):
        for token in re.findall(r"[A-Za-z]{2}", path):
            for name in token:
                handle = _visible_point_handle_by_name(
                    name,
                    scope_id=step.scope_id,
                    context=context,
                )
                if handle is not None:
                    handles.append(handle)
    return set(handles)

def _parameterized_point_state_name(semantic_name: str) -> str | None:
    """识别 ``G_parametric_coordinate`` / ``G_parameterized_point`` 类状态名。"""
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9]*)_"
        r"(?:parametric|parameterized|param)_"
        r"(?:coord|coordinate|point)(?:_[A-Za-z0-9_]+)?",
        semantic_name,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    point = match.group("point")
    return point[:1].upper() + point[1:]

def _unique_locus_candidates(
    candidates: list[tuple[str, str, str]],
) -> tuple[tuple[str, str, str], ...]:
    result: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return tuple(result)

def _unique_generated_step_id(
    base: str,
    existing_steps: tuple[StepIntent, ...],
) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_")
    if not normalized:
        normalized = "generated_step"
    existing = {step.step_id for step in existing_steps}
    if normalized not in existing:
        return normalized
    suffix = 2
    while f"{normalized}_{suffix}" in existing:
        suffix += 1
    return f"{normalized}_{suffix}"

def _normalize_square_final_recovery_for_scope(
    steps: tuple[StepIntent, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
    """Rewrite square-path final param substitution into square vertex recovery.

    Path-minimum square problems often determine the reduced moving point first.
    If the draft then tries to finish the target point by parameter substitution,
    the dynamic axis parameter may remain unresolved. Once a prior
    ``line_locus_minimum_point`` has produced the extremal square vertex, the
    executable recovery is the existing square-adjacent-vertex method.
    """
    normalized: list[StepIntent] = []
    actions: list[StepIntentNormalizationAction] = []
    for index, step in enumerate(steps):
        rewritten = _square_final_recovery_step(
            step,
            previous_steps=tuple(normalized),
            remaining_steps=steps[index + 1 :],
            handle_registry=handle_registry,
        )
        if rewritten is None:
            normalized.append(step)
            continue
        normalized.append(rewritten)
        actions.append(
            StepIntentNormalizationAction(
                action="rewrite_square_final_parameter_substitution_to_vertex_recovery",
                step_id=step.step_id,
                target_step_id=rewritten.step_id,
                handle=step.target,
                reason=(
                    "已有 line_locus_minimum_point 求出最短状态 moving point；"
                    "最终 square 顶点答案应由 square_adjacent_vertex_from_side 恢复，"
                    "而不是直接代入仍含动点参数的坐标。"
                ),
            )
        )
    return tuple(normalized), actions

def _square_final_recovery_step(
    step: StepIntent,
    *,
    previous_steps: tuple[StepIntent, ...],
    remaining_steps: tuple[StepIntent, ...],
    handle_registry: CanonicalHandleRegistry,
) -> StepIntent | None:
    if step.recipe_hint != "evaluate_point_at_parameter":
        return None
    if not _step_produces_point_answer(step, handle_registry):
        return None
    extremal_point = _latest_line_locus_point_output(previous_steps, handle_registry)
    if extremal_point is None:
        return None
    square_fact = _visible_fact_handle_by_type(
        "square",
        step.scope_id,
        handle_registry,
        preferred=step.reads,
    )
    if square_fact is None:
        return None
    side_start_state = _visible_point_state_fact_by_name(
        _square_start_name(square_fact, handle_registry),
        step.scope_id,
        handle_registry,
    )
    parameter_value = _latest_parameter_value_read(step, previous_steps)
    reads = _unique_ordered(
        [
            item
            for item in (
                square_fact,
                side_start_state,
                extremal_point,
                parameter_value,
            )
            if item is not None
        ]
    )
    if len(reads) < 3:
        return None
    return replace(
        step,
        recipe_hint="square_adjacent_vertex_from_side",
        goal_type="derive_square_adjacent_vertex",
        reads=tuple(reads),
        strategy=(
            "最短状态 moving point 已确定；由正方形关系从已知顶点恢复最终答案点。"
        ),
        reason=(
            "最终答案点不是降维后的 moving point，需用正方形相邻顶点关系恢复。"
        ),
    )

def _step_produces_point_answer(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    if step.target.startswith("answer:"):
        value_type = handle_registry.answer_value_types.get(step.target)
        if value_type == "Point":
            return True
    return any(
        produced.handle.startswith("answer:")
        and (
            produced.output_type == "Point"
            or handle_registry.answer_value_types.get(produced.handle) == "Point"
        )
        for produced in step.produces
    )

def _latest_line_locus_point_output(
    steps: tuple[StepIntent, ...],
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    for step in reversed(steps):
        if step.recipe_hint != "line_locus_minimum_point":
            continue
        for produced in step.produces:
            if _produced_output_type(produced, handle_registry) == "Point":
                return produced.handle
    return None

def _square_start_name(
    square_fact: str,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    payload = handle_registry.fact_payloads.get(square_fact, {})
    vertices = payload.get("vertices")
    if not isinstance(vertices, list) or not vertices:
        return None
    return _handle_name(str(vertices[0]))

def _visible_point_state_fact_by_name(
    point_name: str | None,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    if not point_name:
        return None
    visible_scopes = set(handle_registry.ancestor_scopes(scope_id))
    candidates: list[str] = []
    for handle in sorted(handle_registry.fact_handles):
        if handle_registry.handle_valid_scopes.get(handle) not in visible_scopes:
            continue
        if handle_registry.fact_types.get(handle) != "point_coordinate":
            continue
        semantic = _semantic_name(handle)
        if semantic.startswith(f"{point_name}_"):
            candidates.append(handle)
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None

def _latest_parameter_value_read(
    step: StepIntent,
    previous_steps: tuple[StepIntent, ...],
) -> str | None:
    for handle in reversed(step.reads):
        if handle.startswith("fact:") and _semantic_name(handle).endswith("_value"):
            return handle
    for previous in reversed(previous_steps):
        for produced in reversed(previous.produces):
            if (
                produced.output_type == "ParameterValue"
                and _semantic_name(produced.handle).endswith("_value")
            ):
                return produced.handle
    return None

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
