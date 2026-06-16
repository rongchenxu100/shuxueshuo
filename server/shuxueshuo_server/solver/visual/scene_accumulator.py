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


VALID_PERSISTENCE = {"step_only", "carry_forward"}
DEFAULT_DECAY_STATE = "muted"


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
        current_items = [copy.deepcopy(item) for item in scene.get("add") or ()]
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


def _with_override(item: JsonObject, overrides: dict[str, str]) -> JsonObject:
    out = copy.deepcopy(item)
    handle = str(out.get("handle") or "")
    if handle and handle in overrides:
        out["state"] = overrides[handle]
    return out


def _decayed_for_next_step(item: JsonObject) -> JsonObject:
    out = copy.deepcopy(item)
    decay_state = str(out.get("decay_state") or DEFAULT_DECAY_STATE)
    out["state"] = decay_state
    return out

