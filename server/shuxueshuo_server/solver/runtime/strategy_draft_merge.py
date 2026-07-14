"""Draft merge and raw StepIntent payload repair for planner retries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from typing import Any

from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.strategy_models import (
    STEP_INTENT_OUTPUT_TYPES,
    StepIntent,
    StepIntentDraft,
    StepIntentScope,
)
from shuxueshuo_server.solver.runtime.strategy_retry_state import retry_state_from_attempt
from shuxueshuo_server.solver.runtime.strategy_validator import StepIntentValidator
def prepare_step_intent_raw_response(
    raw_response: str,
    *,
    previous_attempts: list[object],
) -> str:
    """在 strict validator 前应用确定性 retry 修复。

    LLM 在 retry 时仍输出完整 StepIntent JSON，所以它可能重写已经被
    ``preserve_prefix`` 固定的前缀。本函数只在 raw payload 层做两类安全修复：

    - 把 ``produces[].entity_type`` 这种 creates/produces schema 混淆修成
      ``output_type``，或在已有 ``output_type`` 时移除多余字段。
    - 按最新 ``PlannerRetryState`` 把 stable prefix/step/handles 从
      ``baseline_draft`` 覆盖回 raw payload。

    解析失败时保持原始 raw，让 validator 继续产出原有 invalid JSON 错误。
    """
    data = _parse_raw_json_object(raw_response)
    if data is None:
        return raw_response
    prepared = sanitize_step_intent_raw_payload(data)
    prepared = overlay_previous_retry_state_raw_payload(
        prepared,
        previous_attempts=previous_attempts,
    )
    return json.dumps(prepared, ensure_ascii=False)

def sanitize_step_intent_raw_payload(data: dict[str, Any]) -> dict[str, Any]:
    """修复 LLM 常见的 StepIntent 浅层 schema 噪音。"""
    sanitized = deepcopy(data)
    for scope in _iter_scope_payloads(sanitized):
        for step in _iter_step_payloads(scope):
            produces = step.get("produces")
            if not isinstance(produces, list):
                continue
            for item in produces:
                if not isinstance(item, dict) or "entity_type" not in item:
                    continue
                entity_type = item.get("entity_type")
                output_type = item.get("output_type")
                if isinstance(output_type, str) and output_type.strip():
                    item.pop("entity_type", None)
                    continue
                coerced = _coerce_output_type(entity_type)
                if coerced is None:
                    continue
                item["output_type"] = coerced
                item.pop("entity_type", None)
    return sanitized

def overlay_previous_retry_state_raw_payload(
    data: dict[str, Any],
    *,
    previous_attempts: list[object],
) -> dict[str, Any]:
    """按最新 PlannerRetryState 在 raw JSON 层冻结稳定 draft。"""
    previous = _last_previous_attempt(previous_attempts)
    if previous is None:
        return data
    retry_state = retry_state_from_attempt(previous)
    if retry_state is None:
        return data
    return _overlay_retry_state_raw_payload(data, retry_state=retry_state)

def _overlay_retry_state_raw_payload(
    data: dict[str, Any],
    *,
    retry_state: dict[str, Any],
) -> dict[str, Any]:
    """执行 raw payload 层的 preserve policy。

    Phase 1b 的 ``build_planner_retry_state`` 只会自动生成
    ``preserve_prefix`` 或 ``none``。``preserve_handles``、``preserve_step`` 和
    ``preserve_all`` 是 Phase 2 兼容契约：当外部/测试显式传入这些 policy 时，
    merge 层保持可执行且有单元测试覆盖，但当前 builder 不会主动启用它们。
    """
    policy = retry_state.get("preserve_policy")
    if policy not in {"preserve_prefix", "preserve_handles", "preserve_step", "preserve_all"}:
        return data
    baseline = retry_state.get("baseline_draft")
    if not isinstance(baseline, dict):
        return data
    if policy == "preserve_all":
        return deepcopy(baseline)
    accepted_ids = _accepted_ids_for_policy(retry_state, policy)
    if not accepted_ids:
        return data
    if policy == "preserve_handles":
        return _overlay_preserved_handle_fields(
            data,
            baseline=baseline,
            accepted_ids=accepted_ids,
        )
    if policy == "preserve_step":
        return _overlay_selected_raw_steps(
            data,
            baseline=baseline,
            accepted_ids=accepted_ids,
        )
    return _overlay_accepted_prefix_raw_steps(
        data,
        baseline=baseline,
        accepted_ids=accepted_ids,
    )

def _overlay_accepted_prefix_raw_steps(
    data: dict[str, Any],
    *,
    baseline: dict[str, Any],
    accepted_ids: set[str],
) -> dict[str, Any]:
    """把 baseline 中已接受的 prefix steps 覆盖回 raw payload。"""
    merged = deepcopy(data)
    baseline_scopes = _scopes_by_id(baseline)
    emitted_scope_ids: set[str] = set()
    raw_scopes = merged.get("scopes")
    if not isinstance(raw_scopes, list):
        return merged

    for raw_scope in raw_scopes:
        if not isinstance(raw_scope, dict):
            continue
        scope_id = _scope_id(raw_scope)
        baseline_scope = baseline_scopes.get(scope_id)
        if baseline_scope is None:
            if scope_id is not None:
                emitted_scope_ids.add(scope_id)
            continue
        frozen_prefix = _frozen_prefix_steps(baseline_scope, accepted_ids)
        if not frozen_prefix:
            emitted_scope_ids.add(scope_id)
            continue
        frozen_ids = {_step_id(step) for step in frozen_prefix}
        current_steps = raw_scope.get("steps")
        if not isinstance(current_steps, list):
            current_steps = []
        raw_scope["steps"] = [
            *deepcopy(frozen_prefix),
            *(
                step
                for step in current_steps
                if _step_id(step) not in frozen_ids
            ),
        ]
        emitted_scope_ids.add(scope_id)

    for scope_id, baseline_scope in baseline_scopes.items():
        if scope_id in emitted_scope_ids:
            continue
        frozen_prefix = _frozen_prefix_steps(baseline_scope, accepted_ids)
        if not frozen_prefix:
            continue
        appended = deepcopy(baseline_scope)
        appended["steps"] = deepcopy(frozen_prefix)
        raw_scopes.append(appended)
    return merged

def _overlay_selected_raw_steps(
    data: dict[str, Any],
    *,
    baseline: dict[str, Any],
    accepted_ids: set[str],
) -> dict[str, Any]:
    """按 step_id 用 baseline 完整替换指定 steps。"""
    return _overlay_selected_raw_step_fields(
        data,
        baseline=baseline,
        accepted_ids=accepted_ids,
        preserve_fields=None,
    )

def _overlay_preserved_handle_fields(
    data: dict[str, Any],
    *,
    baseline: dict[str, Any],
    accepted_ids: set[str],
) -> dict[str, Any]:
    """只冻结稳定 step 的 dataflow/target/capability 字段。"""
    return _overlay_selected_raw_step_fields(
        data,
        baseline=baseline,
        accepted_ids=accepted_ids,
        preserve_fields=("recipe_hint", "target", "reads", "creates", "produces"),
    )

def _overlay_selected_raw_step_fields(
    data: dict[str, Any],
    *,
    baseline: dict[str, Any],
    accepted_ids: set[str],
    preserve_fields: tuple[str, ...] | None,
) -> dict[str, Any]:
    """用 baseline 替换指定 step，或只替换指定字段。"""
    merged = deepcopy(data)
    baseline_steps = _steps_by_id(baseline)
    emitted: set[str] = set()
    for scope in _iter_scope_payloads(merged):
        steps = scope.get("steps")
        if not isinstance(steps, list):
            continue
        for index, raw_step in enumerate(steps):
            step_id = _step_id(raw_step)
            if step_id not in accepted_ids:
                continue
            baseline_step = baseline_steps.get(step_id)
            if baseline_step is None:
                continue
            if preserve_fields is None:
                steps[index] = deepcopy(baseline_step)
            elif isinstance(raw_step, dict):
                for field in preserve_fields:
                    if field in baseline_step:
                        raw_step[field] = deepcopy(baseline_step[field])
                    else:
                        raw_step.pop(field, None)
                raw_step.pop("semantic_reads", None)
            emitted.add(step_id)

    missing = [
        step
        for step_id, step in baseline_steps.items()
        if step_id in accepted_ids and step_id not in emitted
    ]
    if missing:
        _append_missing_steps(merged, baseline=baseline, steps=missing)
    return merged

def _append_missing_steps(
    data: dict[str, Any],
    *,
    baseline: dict[str, Any],
    steps: list[dict[str, Any]],
) -> None:
    """把模型漏掉的冻结 step 补回对应 scope。"""
    raw_scopes = data.get("scopes")
    if not isinstance(raw_scopes, list):
        return
    baseline_scope_by_step = _scope_by_step_id(baseline)
    for step in steps:
        step_id = _step_id(step)
        baseline_scope = baseline_scope_by_step.get(step_id)
        if baseline_scope is None:
            continue
        scope_id = _scope_id(baseline_scope)
        target_scope = next(
            (
                scope
                for scope in raw_scopes
                if isinstance(scope, dict) and _scope_id(scope) == scope_id
            ),
            None,
        )
        if target_scope is None:
            target_scope = {
                "scope_id": scope_id,
                "label": baseline_scope.get("label", f"scope {scope_id}"),
                "steps": [],
            }
            raw_scopes.append(target_scope)
        current_steps = target_scope.get("steps")
        if not isinstance(current_steps, list):
            current_steps = []
            target_scope["steps"] = current_steps
        current_steps.append(deepcopy(step))

def _parse_raw_json_object(raw_response: str) -> dict[str, Any] | None:
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None

def _iter_scope_payloads(data: dict[str, Any]) -> list[dict[str, Any]]:
    scopes = data.get("scopes")
    if not isinstance(scopes, list):
        return []
    return [scope for scope in scopes if isinstance(scope, dict)]

def _iter_step_payloads(scope: dict[str, Any]) -> list[dict[str, Any]]:
    steps = scope.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]

def _scopes_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        scope_id: scope
        for scope in _iter_scope_payloads(data)
        if (scope_id := _scope_id(scope)) is not None
    }

def _steps_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        step_id: step
        for scope in _iter_scope_payloads(data)
        for step in _iter_step_payloads(scope)
        if (step_id := _step_id(step)) is not None
    }

def _scope_by_step_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        step_id: scope
        for scope in _iter_scope_payloads(data)
        for step in _iter_step_payloads(scope)
        if (step_id := _step_id(step)) is not None
    }

def _frozen_prefix_steps(
    baseline_scope: dict[str, Any],
    accepted_ids: set[str],
) -> list[dict[str, Any]]:
    frozen: list[dict[str, Any]] = []
    for step in _iter_step_payloads(baseline_scope):
        if _step_id(step) not in accepted_ids:
            break
        frozen.append(step)
    return frozen

def _scope_id(scope: dict[str, Any]) -> str | None:
    value = scope.get("scope_id")
    return value if isinstance(value, str) and value else None

def _step_id(step: object) -> str | None:
    if not isinstance(step, dict):
        return None
    value = step.get("step_id")
    return value if isinstance(value, str) and value else None

def _coerce_output_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    by_lower = {item.lower(): item for item in STEP_INTENT_OUTPUT_TYPES}
    return by_lower.get(normalized.lower())

def merge_previous_accepted_prefix(
    draft: StepIntentDraft,
    *,
    previous_attempts: list[object],
    handle_registry: CanonicalHandleRegistry,
    inputs: PlannerInputs,
) -> StepIntentDraft:
    """按 previous retry state 的 preserve policy 合并稳定基线。"""
    previous = _last_previous_attempt(previous_attempts)
    if previous is None:
        return draft
    retry_state = retry_state_from_attempt(previous)
    if retry_state is not None:
        merged = _merge_previous_retry_state(
            draft,
            retry_state=retry_state,
            handle_registry=handle_registry,
            inputs=inputs,
        )
        # A formal PlannerRetryState is authoritative even when its policy is
        # ``none``. Falling through to the legacy diagnostic in that case can
        # resurrect an obsolete accepted suffix beside the model's replacement.
        return merged if merged is not None else draft
    return _merge_legacy_attempt_prefix(
        draft,
        previous=previous,
        handle_registry=handle_registry,
        inputs=inputs,
    )

def _last_previous_attempt(previous_attempts: list[object]) -> dict[str, Any] | None:
    """返回最近一个 rich repair context payload。"""
    for item in reversed(previous_attempts):
        if (
            isinstance(item, dict)
            and (
                isinstance(item.get("planner_retry_state"), dict)
                or isinstance(item.get("context_derived_retry_state"), dict)
                or (
                    isinstance(item.get("effective_draft"), dict)
                    and isinstance(item.get("diagnostic"), dict)
                )
            )
        ):
            return item
    return None

def _merge_previous_retry_state(
    draft: StepIntentDraft,
    *,
    retry_state: dict[str, Any],
    handle_registry: CanonicalHandleRegistry,
    inputs: PlannerInputs,
) -> StepIntentDraft | None:
    """执行 PlannerRetryState preserve policy。

    Phase 1b 只由 builder 自动产生 ``preserve_prefix`` / ``none``。其余 policy
    保留为 Phase 2 兼容入口，供测试或后续更细粒度 replay state 显式请求。
    """
    policy = retry_state.get("preserve_policy")
    if policy not in {"preserve_prefix", "preserve_handles", "preserve_step", "preserve_all"}:
        return None
    baseline_payload = retry_state.get("baseline_draft")
    if not isinstance(baseline_payload, dict):
        return None
    try:
        previous_draft = StepIntentValidator().validate(
            baseline_payload,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )
    except Exception:
        return None
    if policy == "preserve_all":
        return previous_draft
    accepted_ids = _accepted_ids_for_policy(retry_state, policy)
    if not accepted_ids:
        return None
    if policy == "preserve_handles":
        return _merge_preserved_handles(
            draft,
            previous_draft=previous_draft,
            accepted_ids=accepted_ids,
        )
    if policy == "preserve_step":
        return _merge_selected_full_steps(
            draft,
            previous_draft=previous_draft,
            accepted_ids=accepted_ids,
        )
    return _merge_accepted_prefix_steps(
        draft,
        previous_draft=previous_draft,
        accepted_ids=accepted_ids,
    )

def _accepted_ids_for_policy(
    retry_state: dict[str, Any],
    policy: object,
) -> set[str]:
    stable_prefix = retry_state.get("stable_prefix")
    if not isinstance(stable_prefix, list):
        return set()
    ids = [
        str(item.get("step_id"))
        for item in stable_prefix
        if isinstance(item, dict) and item.get("step_id")
    ]
    if policy == "preserve_step":
        return {ids[-1]} if ids else set()
    return set(ids)

def _merge_legacy_attempt_prefix(
    draft: StepIntentDraft,
    *,
    previous: dict[str, Any],
    handle_registry: CanonicalHandleRegistry,
    inputs: PlannerInputs,
) -> StepIntentDraft:
    effective_payload = previous.get("effective_draft")
    diagnostic = previous.get("diagnostic")
    if not isinstance(effective_payload, dict) or not isinstance(diagnostic, dict):
        return draft
    accepted_items = diagnostic.get("accepted_prefix")
    if not isinstance(accepted_items, list) or not accepted_items:
        return draft
    accepted_ids = {
        str(item.get("step_id"))
        for item in accepted_items
        if isinstance(item, dict) and item.get("step_id")
    }
    if not accepted_ids:
        return draft
    try:
        previous_draft = StepIntentValidator().validate(
            effective_payload,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )
    except Exception:
        return draft
    return _merge_accepted_prefix_steps(
        draft,
        previous_draft=previous_draft,
        accepted_ids=accepted_ids,
    )

def _merge_accepted_prefix_steps(
    draft: StepIntentDraft,
    *,
    previous_draft: StepIntentDraft,
    accepted_ids: set[str],
) -> StepIntentDraft:
    """把 previous_draft 中已接受的 prefix 完整覆盖回当前 draft。"""
    previous_scopes = {scope.scope_id: scope for scope in previous_draft.scopes}
    merged_scopes: list[StepIntentScope] = []
    emitted_scope_ids: set[str] = set()
    for current_scope in draft.scopes:
        previous_scope = previous_scopes.get(current_scope.scope_id)
        if previous_scope is None:
            merged_scopes.append(current_scope)
            emitted_scope_ids.add(current_scope.scope_id)
            continue
        frozen_prefix = []
        for step in previous_scope.steps:
            if step.step_id not in accepted_ids:
                break
            frozen_prefix.append(step)
        if not frozen_prefix:
            merged_scopes.append(current_scope)
            emitted_scope_ids.add(current_scope.scope_id)
            continue
        frozen_ids = {step.step_id for step in frozen_prefix}
        merged_scopes.append(
            StepIntentScope(
                scope_id=current_scope.scope_id,
                label=current_scope.label,
                steps=tuple(
                    [
                        *frozen_prefix,
                        *(step for step in current_scope.steps if step.step_id not in frozen_ids),
                    ]
                ),
            )
        )
        emitted_scope_ids.add(current_scope.scope_id)

    for previous_scope in previous_draft.scopes:
        if previous_scope.scope_id in emitted_scope_ids:
            continue
        frozen_steps = tuple(
            step for step in previous_scope.steps if step.step_id in accepted_ids
        )
        if frozen_steps:
            merged_scopes.append(
                StepIntentScope(
                    scope_id=previous_scope.scope_id,
                    label=previous_scope.label,
                    steps=frozen_steps,
                )
            )
    return StepIntentDraft(scopes=tuple(merged_scopes))

def _merge_preserved_handles(
    draft: StepIntentDraft,
    *,
    previous_draft: StepIntentDraft,
    accepted_ids: set[str],
) -> StepIntentDraft:
    """只冻结稳定 step 的 dataflow/target/capability 相关字段。"""
    previous_steps = {step.step_id: step for step in previous_draft.steps}
    merged_scopes: list[StepIntentScope] = []
    emitted_step_ids: set[str] = set()
    for scope in draft.scopes:
        merged_steps: list[StepIntent] = []
        for step in scope.steps:
            previous = previous_steps.get(step.step_id)
            if previous is not None and step.step_id in accepted_ids:
                step = replace(
                    step,
                    recipe_hint=previous.recipe_hint,
                    target=previous.target,
                    reads=previous.reads,
                    creates=previous.creates,
                    produces=previous.produces,
                )
                emitted_step_ids.add(step.step_id)
            merged_steps.append(step)
        merged_scopes.append(replace(scope, steps=tuple(merged_steps)))
    missing_steps = [
        step
        for step in previous_draft.steps
        if step.step_id in accepted_ids and step.step_id not in emitted_step_ids
    ]
    if missing_steps:
        merged_scopes.append(
            StepIntentScope(
                scope_id=missing_steps[0].scope_id,
                label=f"preserved {missing_steps[0].scope_id}",
                steps=tuple(missing_steps),
            )
        )
    return StepIntentDraft(scopes=tuple(merged_scopes))

def _merge_selected_full_steps(
    draft: StepIntentDraft,
    *,
    previous_draft: StepIntentDraft,
    accepted_ids: set[str],
) -> StepIntentDraft:
    """按 step_id 精确冻结指定稳定 step。"""
    previous_steps = {step.step_id: step for step in previous_draft.steps}
    merged_scopes: list[StepIntentScope] = []
    emitted_step_ids: set[str] = set()
    for scope in draft.scopes:
        merged_steps: list[StepIntent] = []
        for step in scope.steps:
            replacement = previous_steps.get(step.step_id)
            if replacement is not None and step.step_id in accepted_ids:
                step = replacement
                emitted_step_ids.add(step.step_id)
            merged_steps.append(step)
        merged_scopes.append(replace(scope, steps=tuple(merged_steps)))
    missing_steps = [
        step
        for step in previous_draft.steps
        if step.step_id in accepted_ids and step.step_id not in emitted_step_ids
    ]
    if missing_steps:
        merged_scopes.append(
            StepIntentScope(
                scope_id=missing_steps[0].scope_id,
                label=f"preserved {missing_steps[0].scope_id}",
                steps=tuple(missing_steps),
            )
        )
    return StepIntentDraft(scopes=tuple(merged_scopes))

__all__ = [
    "merge_previous_accepted_prefix",
    "overlay_previous_retry_state_raw_payload",
    "prepare_step_intent_raw_response",
    "sanitize_step_intent_raw_payload",
]
