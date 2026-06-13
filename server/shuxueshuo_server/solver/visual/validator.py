"""Validation for VisualStepIR VS0 documents."""

from __future__ import annotations

from typing import Any

from .models import VisualStep, VisualStepIR
from .registry import ComponentTypeSpecRegistry, LayerRegistry, default_component_registry, default_layer_registry


class VisualStepIRValidationError(ValueError):
    """VisualStepIR validation failed."""


VALID_STATES = {
    "constructed",
    "emphasized",
    "gap",
    "hidden",
    "highlight",
    "moving",
    "muted",
    "result",
    "visible",
}

VALID_INTERACTION_COMPONENTS = {"LinkedControls", "LocalSlider", "MainSlider"}
VALID_TIMELINE_MODES = {"auto_then_interactive", "manual_then_interactive", "none"}


class VisualStepIRValidator:
    def __init__(
        self,
        *,
        component_registry: ComponentTypeSpecRegistry | None = None,
        layer_registry: LayerRegistry | None = None,
    ) -> None:
        self.component_registry = component_registry or default_component_registry()
        self.layer_registry = layer_registry or default_layer_registry()

    def validate(self, visual_ir: VisualStepIR) -> None:
        lesson_steps = _lesson_steps_by_id(visual_ir.lesson_data)
        layer_registry = self._layer_registry_for(visual_ir)
        for step in visual_ir.steps:
            self._validate_step(step, lesson_steps, layer_registry)

    def _validate_step(
        self,
        step: VisualStep,
        lesson_steps: dict[str, dict[str, Any]],
        layer_registry: LayerRegistry,
    ) -> None:
        label = f"visual_step:{step.visual_step_id}"
        if not step.lesson_step_id:
            raise VisualStepIRValidationError(f"{label}: missing lesson_step_id")
        if step.lesson_step_id not in lesson_steps:
            raise VisualStepIRValidationError(
                f"{label}: unknown lesson_step_id: {step.lesson_step_id}"
            )
        scene = step.scene or {}
        inherits_from = scene.get("inherits_from", "global")
        try:
            layer_registry.require_layer_key(str(inherits_from))
        except KeyError as exc:
            raise VisualStepIRValidationError(f"{label}: {exc}") from exc

        for index, item in enumerate(scene.get("add") or ()):
            self._validate_scene_item(item, f"{label}.scene.add[{index}]")
        for index, item in enumerate(scene.get("state_overrides") or ()):
            self._validate_state_override(item, f"{label}.scene.state_overrides[{index}]")
        for index, hidden in enumerate(scene.get("hide") or ()):
            self._validate_hidden_ref(str(hidden), f"{label}.scene.hide[{index}]", layer_registry)
        for index, item in enumerate(scene.get("annotations") or ()):
            self._validate_annotation(item, lesson_steps[step.lesson_step_id], f"{label}.scene.annotations[{index}]")
        for index, item in enumerate(step.interactions or ()):
            self._validate_interaction(item, f"{label}.interactions[{index}]")
        self._validate_timeline(step.timeline, f"{label}.timeline")

    def _validate_scene_item(self, item: dict[str, Any], label: str) -> None:
        component = item.get("component")
        if not component:
            raise VisualStepIRValidationError(f"{label}: missing component")
        spec = self.component_registry.get(str(component))
        if spec is None:
            raise VisualStepIRValidationError(f"{label}: unknown component: {component}")
        state = item.get("state")
        if state is not None and state not in VALID_STATES:
            raise VisualStepIRValidationError(f"{label}: invalid state: {state}")
        if component == "VisualGap":
            self._validate_visual_gap(item, label)
        for role in spec.required_roles:
            if role not in item:
                raise VisualStepIRValidationError(f"{label}: missing required role: {role}")

    def _validate_visual_gap(self, item: dict[str, Any], label: str) -> None:
        allowed = {"component", "expected_role", "reason", "state", "metadata"}
        extra = sorted(set(item) - allowed)
        if extra:
            raise VisualStepIRValidationError(
                f"{label}: VisualGap cannot carry geometry fields: {extra}"
            )
        if not item.get("expected_role"):
            raise VisualStepIRValidationError(f"{label}: VisualGap missing expected_role")

    def _validate_state_override(self, item: dict[str, Any], label: str) -> None:
        if not item.get("handle"):
            raise VisualStepIRValidationError(f"{label}: missing handle")
        state = item.get("state")
        if state not in VALID_STATES:
            raise VisualStepIRValidationError(f"{label}: invalid state: {state}")

    def _validate_annotation(self, item: dict[str, Any], lesson_step: dict[str, Any], label: str) -> None:
        if "text_source" not in item and "text" not in item:
            raise VisualStepIRValidationError(f"{label}: annotation requires text_source or text")
        if "text_source" not in item:
            return
        source = item["text_source"]
        if source not in {"lesson_step.box", "lesson_step.derive"}:
            raise VisualStepIRValidationError(f"{label}: unsupported text_source: {source}")
        index = item.get("index", 0)
        if not isinstance(index, int) or index < 0:
            raise VisualStepIRValidationError(f"{label}: invalid text_source index: {index}")
        source_text = _text_from_lesson_step(lesson_step, source, index, label)
        explicit_text = item.get("text")
        if explicit_text is not None and str(explicit_text) != source_text:
            raise VisualStepIRValidationError(
                f"{label}: annotation text conflicts with {source}"
            )

    def _validate_hidden_ref(self, hidden: str, label: str, layer_registry: LayerRegistry) -> None:
        if hidden in layer_registry.semantic_to_layer:
            return
        if hidden in layer_registry.semantic_to_layer.values():
            return
        if ":" in hidden:
            return
        raise VisualStepIRValidationError(f"{label}: unknown hide target: {hidden}")

    def _validate_interaction(self, item: dict[str, Any], label: str) -> None:
        component = item.get("component")
        if component not in VALID_INTERACTION_COMPONENTS:
            raise VisualStepIRValidationError(f"{label}: unknown interaction component: {component}")

    def _validate_timeline(self, timeline: dict[str, Any] | None, label: str) -> None:
        if timeline is None:
            return
        mode = timeline.get("mode", "none")
        if mode not in VALID_TIMELINE_MODES:
            raise VisualStepIRValidationError(f"{label}: invalid timeline mode: {mode}")

    def _layer_registry_for(self, visual_ir: VisualStepIR) -> LayerRegistry:
        if not visual_ir.layer_registry:
            return self.layer_registry
        merged = dict(self.layer_registry.semantic_to_layer)
        merged.update(visual_ir.layer_registry)
        return LayerRegistry(merged)


def _lesson_steps_by_id(lesson_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in lesson_data.get("steps") or ():
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def _text_from_lesson_step(lesson_step: dict[str, Any], source: str, index: int, label: str) -> str:
    if source == "lesson_step.box":
        values = lesson_step.get("box") or []
        if index >= len(values):
            raise VisualStepIRValidationError(f"{label}: lesson_step.box index out of range: {index}")
        return str(values[index])
    values = lesson_step.get("derive") or []
    if index >= len(values):
        raise VisualStepIRValidationError(f"{label}: lesson_step.derive index out of range: {index}")
    item = values[index]
    if not isinstance(item, list) or len(item) < 2:
        raise VisualStepIRValidationError(f"{label}: invalid lesson_step.derive item at index {index}")
    return str(item[1])
