"""Data models for VisualStepIR.

VS0 intentionally keeps the model close to the existing authored lesson JSON so
we can prove round-trip coverage before adding method/recipe-driven generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import copy


JsonObject = dict[str, Any]


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


@dataclass(frozen=True)
class VisualStep:
    """One visual step aligned to an existing lesson/decoration step."""

    visual_step_id: str
    lesson_step_id: str
    scope_id: str | None
    geometry_context: JsonObject = field(default_factory=dict)
    scene: JsonObject = field(default_factory=dict)
    interactions: tuple[JsonObject, ...] = ()
    timeline: JsonObject | None = None
    metadata: JsonObject = field(default_factory=dict)

    def to_payload(self) -> JsonObject:
        payload: JsonObject = {
            "visual_step_id": self.visual_step_id,
            "lesson_step_id": self.lesson_step_id,
            "scope_id": self.scope_id,
            "geometry_context": _clone(self.geometry_context),
            "scene": _clone(self.scene),
            "interactions": _clone(list(self.interactions)),
        }
        if self.timeline is not None:
            payload["timeline"] = _clone(self.timeline)
        if self.metadata:
            payload["metadata"] = _clone(self.metadata)
        return payload


@dataclass(frozen=True)
class VisualStepIR:
    """A VS0 VisualStepIR document.

    ``geometry_spec`` and ``lesson_data`` are preserved for VS0 round-tripping.
    Product generation in VS1 can start replacing these preserved authored views
    with generated views.
    """

    version: int
    problem_id: str
    geometry_spec: JsonObject
    lesson_data: JsonObject
    layers: dict[str, JsonObject]
    layer_registry: dict[str, str]
    steps: tuple[VisualStep, ...]
    metadata: JsonObject = field(default_factory=dict)

    def to_payload(self) -> JsonObject:
        return {
            "version": self.version,
            "problem_id": self.problem_id,
            "geometry_spec": _clone(self.geometry_spec),
            "lesson_data": _clone(self.lesson_data),
            "layers": _clone(self.layers),
            "layer_registry": dict(self.layer_registry),
            "steps": [step.to_payload() for step in self.steps],
            "metadata": _clone(self.metadata),
        }


def visual_step_from_payload(payload: JsonObject) -> VisualStep:
    return VisualStep(
        visual_step_id=str(payload["visual_step_id"]),
        lesson_step_id=str(payload["lesson_step_id"]),
        scope_id=payload.get("scope_id"),
        geometry_context=_clone(payload.get("geometry_context") or {}),
        scene=_clone(payload.get("scene") or {}),
        interactions=tuple(_clone(payload.get("interactions") or [])),
        timeline=_clone(payload.get("timeline")) if payload.get("timeline") is not None else None,
        metadata=_clone(payload.get("metadata") or {}),
    )


def visual_step_ir_from_payload(payload: JsonObject) -> VisualStepIR:
    return VisualStepIR(
        version=int(payload.get("version") or 1),
        problem_id=str(payload["problem_id"]),
        geometry_spec=_clone(payload.get("geometry_spec") or {}),
        lesson_data=_clone(payload.get("lesson_data") or {}),
        layers=_clone(payload.get("layers") or {}),
        layer_registry=dict(payload.get("layer_registry") or {}),
        steps=tuple(visual_step_from_payload(item) for item in payload.get("steps") or ()),
        metadata=_clone(payload.get("metadata") or {}),
    )
