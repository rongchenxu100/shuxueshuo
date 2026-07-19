"""Scene carry-forward resolution for VS1 VisualStepIR.

The builder emits per-step visual intent.  Product VS1 pages use a section-local
accumulator so durable objects introduced in one lesson step remain visible in
later steps without requiring each method visual spec to redraw all context.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
import copy

from .geometry_naming import scope_root
from .models import JsonObject, VisualStep
from .palette import COLOR_ACCENT, COLOR_MUTED, COLOR_RESULT, COLOR_TEXT


VALID_PERSISTENCE = {"step_only", "carry_forward"}
DEFAULT_DECAY_STATE = "muted"
MUTED_COLOR = COLOR_MUTED
STATEFUL_COMPONENTS = {
    "AxisOfSymmetry",
    "ColoredLine",
    "DashedLine",
    "Parabola",
    "Point",
    "RightAngle",
}


def resolved_steps_with_carry_forward(steps: tuple[VisualStep, ...]) -> tuple[VisualStep, ...]:
    """Return VisualSteps whose ``scene.add`` contains section-resolved items."""

    carry_by_handle: dict[str, JsonObject] = {}
    current_scope_root: str | None = None
    resolved: list[VisualStep] = []
    for step in steps:
        step_scope_root = scope_root(step.scope_id) if step.scope_id else None
        if step_scope_root != current_scope_root:
            carry_by_handle = {}
            current_scope_root = step_scope_root
        scene = copy.deepcopy(step.scene or {})
        hidden = {str(item) for item in scene.get("hide") or ()}
        for handle in hidden:
            carry_by_handle.pop(handle, None)

        overrides = {
            str(item.get("handle")): str(item.get("state"))
            for item in scene.get("state_overrides") or ()
            if isinstance(item, dict) and item.get("handle") and item.get("state")
        }
        current_items = _dedupe_current_items_by_handle(
            [copy.deepcopy(item) for item in scene.get("add") or ()]
        )
        current_handles = {
            str(item.get("handle"))
            for item in current_items
            if isinstance(item, dict) and item.get("handle")
        }

        resolved_add: list[JsonObject] = []
        for handle, stored in carry_by_handle.items():
            if handle in hidden or handle in current_handles:
                continue
            resolved_add.append(_with_override(stored, overrides))
        resolved_add.extend(_with_override(item, overrides) for item in current_items)

        next_store = dict(carry_by_handle)
        for item in current_items:
            if not isinstance(item, dict) or item.get("persistence") != "carry_forward":
                continue
            handle = str(item.get("handle") or "")
            if not handle or handle in hidden:
                continue
            next_store[handle] = _decayed_for_next_step(_with_override(item, overrides))
        for handle, stored in list(next_store.items()):
            if handle in hidden:
                next_store.pop(handle, None)
            elif handle in overrides:
                next_store[handle] = _decayed_for_next_step(_with_override(stored, overrides))
        carry_by_handle = next_store

        scene["add"] = resolved_add
        resolved.append(replace(step, scene=scene))
    return tuple(resolved)


def _dedupe_current_items_by_handle(items: list[JsonObject]) -> list[JsonObject]:
    best_by_handle: dict[str, tuple[int, int]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        handle = str(item.get("handle") or "")
        if handle:
            score = _current_item_priority(item)
            previous = best_by_handle.get(handle)
            if previous is None or (score, index) > previous:
                best_by_handle[handle] = (score, index)
    if not best_by_handle:
        return items
    out: list[JsonObject] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            out.append(item)
            continue
        handle = str(item.get("handle") or "")
        if handle and best_by_handle.get(handle, (-1, -1))[1] != index:
            continue
        out.append(item)
    return out


def _current_item_priority(item: JsonObject) -> int:
    state = str(item.get("state") or "")
    if state in {"active", "highlight", "result"}:
        return 100
    color = str(item.get("color") or "").lower()
    if color in {COLOR_ACCENT.lower(), COLOR_RESULT.lower()}:
        return 90
    if color and color not in {COLOR_TEXT.lower(), COLOR_MUTED.lower()}:
        return 80
    return 50


def _with_override(item: JsonObject, overrides: dict[str, str]) -> JsonObject:
    out = copy.deepcopy(item)
    handle = str(out.get("handle") or "")
    if handle and handle in overrides:
        _apply_state(out, overrides[handle])
    return out


def _decayed_for_next_step(item: JsonObject) -> JsonObject:
    out = copy.deepcopy(item)
    decay_state = str(out.get("decay_state") or DEFAULT_DECAY_STATE)
    _apply_state(out, decay_state)
    return out


def _apply_state(item: JsonObject, state: str) -> None:
    item["state"] = state
    component = str(item.get("component") or "")
    if component not in STATEFUL_COMPONENTS or "color" not in item:
        return
    metadata = item.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata.setdefault("active_color", item.get("color"))
    if state in {"muted", "context"}:
        item["color"] = MUTED_COLOR
    elif state in {"active", "highlight", "result"} and isinstance(metadata, dict):
        item["color"] = metadata.get("active_color") or item.get("color")
