"""Compressed StepIntent retry diagnostics.

This module does not rewrite drafts or recommend method chains. It translates
candidate/runtime failures for over-compressed steps into a structured repair
work order so the next LLM attempt can expand the suffix itself.

Some prerequisite extraction below still uses best-effort parsing of legacy
free-form diagnostic messages. Treat that as a transition shim: resolver and
runtime diagnostics should eventually expose structured missing-state fields
instead of requiring this module to reverse-engineer wording.
"""

from __future__ import annotations

import re
from typing import Any

from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _handle_name,
    _handle_scope,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    StepIntent,
    StepIntentDraft,
)


def compressed_step_retry_issue(
    *,
    step: StepIntent | None,
    layer: str,
    messages: tuple[str, ...],
    handle_registry: CanonicalHandleRegistry | None = None,
) -> PlannerRetryIssue | None:
    """Return a structured issue when a failed step is likely over-compressed.

    The diagnostic is intentionally conservative: it requires a target write and
    at least two missing prerequisite signals. It never suggests a fixed method
    chain; method guidance remains empty unless a later contract solver can
    prove a unique producer.
    """
    if step is None or not messages:
        return None
    target_write = _target_write(step)
    if target_write is None:
        return None
    missing = _missing_prerequisites(
        messages,
        step=step,
        handle_registry=handle_registry,
    )
    if len(missing) < 2:
        return None
    if not _looks_like_compressed_failure(messages, step):
        return None
    available_states = tuple(
        _state_payload_for_read(handle, handle_registry)
        for handle in step.reads
    )
    return PlannerRetryIssue(
        layer=layer,  # type: ignore[arg-type]
        code="compressed_step_missing_prerequisites",
        step_id=step.step_id,
        scope_id=step.scope_id,
        repair_target="expand_step",
        message=(
            "This step appears to compress multiple mathematical actions into "
            "one non-executable StepIntent. Keep the stable prefix and expand "
            "this step into executable steps that produce the missing states."
        ),
        hints=(
            "不要把数学推理链自动藏进一个 step；从该 step 开始重写 suffix。",
            "先让前序 step 产生 missing_prerequisites 中的状态，再让目标 step 读取它们。",
            "method_guidance.items 为空表示系统不能确定唯一 method；请从当前 catalog 自行选择。",
        ),
        related_handles=tuple(step.reads),
        details={
            "repair_protocol": "expand_compressed_step",
            "target_write": target_write,
            "available_states": [item for item in available_states if item is not None],
            "missing_prerequisites": list(missing),
            "method_guidance": {
                "policy": "only_when_unique_contract_match",
                "items": [],
            },
            "original_step": {
                "step_id": step.step_id,
                "scope_id": step.scope_id,
                "recipe_hint": step.recipe_hint,
                "goal_type": step.goal_type,
                "target": step.target,
                "produced_types": _produced_types(step),
            },
            "failure_messages": list(messages),
        },
    )


def find_step(draft: StepIntentDraft | None, step_id: str | None) -> StepIntent | None:
    """Find a step by id in a draft."""
    if draft is None or step_id is None:
        return None
    for step in draft.steps:
        if step.step_id == step_id:
            return step
    return None


def _target_write(step: StepIntent) -> dict[str, Any] | None:
    produced_types = _produced_types(step)
    if not step.produces and not step.target:
        return None
    primary = next(
        (item for item in step.produces if item.handle == step.target),
        step.produces[0] if step.produces else None,
    )
    handle = primary.handle if primary is not None else step.target
    runtime_type = (
        primary.output_type
        if primary is not None and primary.output_type is not None
        else (produced_types[0] if produced_types else None)
    )
    return {
        "handle": handle,
        "ref": _semantic_ref(handle),
        "state": _state_kind_for_output_type(runtime_type, handle),
        "runtime_type": runtime_type,
        "all_produced_handles": [item.handle for item in step.produces],
    }


def _produced_types(step: StepIntent) -> list[str]:
    return [
        item.output_type
        for item in step.produces
        if item.output_type is not None
    ]


def _missing_prerequisites(
    messages: tuple[str, ...],
    *,
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry | None,
) -> tuple[dict[str, str], ...]:
    text = " | ".join(messages)
    lowered = text.lower()
    items: list[dict[str, str]] = []
    if "parabola" in lowered and "missing" in lowered:
        items.append({
            "state": "solved_parabola",
            "why": "a curve-intersection or quadratic capability requires a solved Parabola state",
        })
    if "missing_curve_intersection_target_pointref" in lowered or "target pointref" in lowered:
        items.append({
            "state": "target_point_ref",
            "why": "curve-intersection capabilities need the target point identity, not only a coordinate answer handle",
        })
    if "missing_line_parabola_inputs" in lowered or (
        "line" in lowered and "missing" in lowered
    ):
        items.append({
            "state": "line_defining_state",
            "why": "a line-parabola intersection needs a determined line or enough points on that line",
        })
    for runtime_type in _missing_runtime_types(text):
        items.append({
            "state": _state_kind_for_output_type(runtime_type, ""),
            "runtime_type": runtime_type,
            "why": f"candidate reported a missing {runtime_type} runtime state",
        })
    if _reads_fact_type_or_name(step, handle_registry, "angle_sum") and _writes_point(step):
        items.append({
            "state": "angle_relation_state",
            "why": "an angle-sum condition is available, but a target point should not directly consume it without an intermediate angle/line relation state",
        })
    return _unique_prerequisites(items)


def _missing_runtime_types(text: str) -> tuple[str, ...]:
    values: list[str] = []
    for pattern in (
        r"missing_readable_type:([A-Za-z0-9_|]+)",
        r"missing_runtime_type[=:]([A-Za-z0-9_|]+)",
        r"missing ([A-Z][A-Za-z0-9_|]+)",
    ):
        for match in re.finditer(pattern, text):
            value = match.group(1).strip()
            if value and value not in values:
                values.append(value)
    return tuple(values)


def _unique_prerequisites(items: list[dict[str, str]]) -> tuple[dict[str, str], ...]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in items:
        key = item.get("state", "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)


def _looks_like_compressed_failure(messages: tuple[str, ...], step: StepIntent) -> bool:
    text = " | ".join(messages).lower()
    if not step.produces:
        return False
    if "no_executable_candidate" in text:
        return True
    if _missing_runtime_types(text):
        return True
    structured_missing_markers = (
        "missing_readable_type:",
        "missing_runtime_type",
        "missing_line_parabola_inputs",
        "missing_curve_intersection_target_pointref",
    )
    return step.recipe_hint is None and any(
        marker in text for marker in structured_missing_markers
    )


def _state_payload_for_read(
    handle: str,
    handle_registry: CanonicalHandleRegistry | None,
) -> dict[str, Any] | None:
    kind = handle.split(":", 1)[0] if ":" in handle else "unknown"
    payload: dict[str, Any] = {
        "handle": handle,
        "kind": kind,
        "ref": _semantic_ref(handle),
    }
    if kind != "answer":
        payload["scope"] = _handle_scope(handle)
    if handle_registry is not None:
        fact_type = handle_registry.fact_types.get(handle)
        answer_type = handle_registry.answer_value_types.get(handle)
        if fact_type is not None:
            payload["state"] = _state_kind_for_fact_type(fact_type, handle)
            payload["fact_type"] = fact_type
        elif answer_type is not None:
            payload["state"] = _state_kind_for_output_type(answer_type, handle)
            payload["runtime_type"] = answer_type
    if "state" not in payload:
        payload["state"] = _state_kind_for_handle(handle)
    return payload


def _state_kind_for_fact_type(fact_type: str, handle: str) -> str:
    if fact_type == "point_coordinate" or _coordinate_semantic_name(handle):
        return "point_coordinate"
    if fact_type in {"angle_sum", "angle_equality"}:
        return fact_type
    if fact_type == "parabola":
        return "solved_parabola"
    if fact_type in {"symbol_value", "parameter_value"}:
        return "parameter_value"
    return fact_type


def _state_kind_for_output_type(runtime_type: str | None, handle: str) -> str:
    if runtime_type in {"Point", "PointList"} or _coordinate_semantic_name(handle):
        return "point_coordinate"
    if runtime_type == "Line":
        return "line_state"
    if runtime_type == "Parabola":
        return "solved_parabola"
    if runtime_type == "ParameterValue":
        return "parameter_value"
    if runtime_type == "AngleEquality":
        return "angle_relation_state"
    if runtime_type:
        return runtime_type[:1].lower() + runtime_type[1:]
    return _state_kind_for_handle(handle)


def _state_kind_for_handle(handle: str) -> str:
    if handle.startswith("point:"):
        return "point_entity"
    if handle.startswith("function:"):
        return "function_entity"
    if _coordinate_semantic_name(handle):
        return "point_coordinate"
    return "read_handle"


def _coordinate_semantic_name(handle: str) -> bool:
    if not handle.startswith("fact:"):
        return False
    name = _semantic_name(handle).lower()
    return "_coordinate" in name


def _semantic_ref(handle: str) -> str:
    if handle.startswith("answer:"):
        return handle.removeprefix("answer:")
    if ":" in handle:
        try:
            return _handle_name(handle)
        except Exception:
            return handle.rsplit(":", 1)[-1]
    return handle


def _reads_fact_type_or_name(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry | None,
    target: str,
) -> bool:
    for handle in step.reads:
        fact_type = (
            handle_registry.fact_types.get(handle)
            if handle_registry is not None
            else None
        )
        if fact_type == target:
            return True
        if handle.startswith("fact:") and target in _semantic_name(handle).lower():
            return True
    return False


def _writes_point(step: StepIntent) -> bool:
    if any(item.output_type in {"Point", "PointList"} for item in step.produces):
        return True
    return any(_coordinate_semantic_name(item.handle) for item in step.produces)


__all__ = ["compressed_step_retry_issue", "find_step"]
