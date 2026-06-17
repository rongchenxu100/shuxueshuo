"""Validation for VisualStepIR VS0 documents."""

from __future__ import annotations

from typing import Any

from .models import VisualStep, VisualStepIR
from .registry import ComponentTypeSpecRegistry, LayerRegistry, default_component_registry, default_layer_registry
from .scene_accumulator import VALID_PERSISTENCE


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
VALID_TIMELINE_MODES = {"manual_then_interactive", "none"}
VALID_TRANSITION_TYPES = {"cut", "fade", "draw", "fade_draw", "tween"}
VALID_TRANSITION_EASINGS = {"linear", "easeInOutCubic"}


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
        self._validate_timeline(
            step.timeline,
            f"{label}.timeline",
            interaction_vars=_interaction_vars(step.interactions),
        )

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
        persistence = item.get("persistence", "step_only")
        if persistence not in VALID_PERSISTENCE:
            raise VisualStepIRValidationError(f"{label}: invalid persistence: {persistence}")
        if persistence == "carry_forward" and not item.get("handle"):
            raise VisualStepIRValidationError(f"{label}: carry_forward item requires handle")
        decay_state = item.get("decay_state")
        if decay_state is not None and decay_state not in VALID_STATES:
            raise VisualStepIRValidationError(f"{label}: invalid decay_state: {decay_state}")
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
        if "text_source" not in item and not str(item.get("text") or "").strip():
            raise VisualStepIRValidationError(f"{label}: annotation text cannot be empty")
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
        if component == "MainSlider":
            return
        if isinstance(item.get("raw_local_controls"), dict):
            return
        interaction_id = str(item.get("id") or "")
        if not interaction_id:
            raise VisualStepIRValidationError(f"{label}: missing interaction id")
        parameter = str(item.get("parameter") or "")
        if not parameter:
            raise VisualStepIRValidationError(f"{label}: missing parameter")
        domain = item.get("domain")
        if not isinstance(domain, dict):
            raise VisualStepIRValidationError(f"{label}: missing domain")
        self._validate_interaction_domain(domain, f"{label}.domain")
        controls = item.get("controls")
        if not isinstance(controls, list) or not controls:
            raise VisualStepIRValidationError(f"{label}: controls must be a non-empty list")
        for index, control in enumerate(controls):
            self._validate_interaction_control(control, parameter, f"{label}.controls[{index}]")
        parameterized = item.get("parameterized_points")
        if not isinstance(parameterized, dict) or not parameterized:
            raise VisualStepIRValidationError(
                f"{label}: parameterized_points must be a non-empty object"
            )
        for point_id, payload in parameterized.items():
            self._validate_parameterized_point(payload, f"{label}.parameterized_points[{point_id}]")

    def _validate_interaction_domain(self, domain: dict[str, Any], label: str) -> None:
        for key in ("min", "max", "step", "default"):
            if key not in domain:
                raise VisualStepIRValidationError(f"{label}: missing {key}")
        try:
            min_value = float(domain["min"])
            max_value = float(domain["max"])
            step_value = float(domain["step"])
            default_value = float(domain["default"])
        except Exception as exc:
            raise VisualStepIRValidationError(f"{label}: domain values must be numeric") from exc
        if min_value >= max_value:
            raise VisualStepIRValidationError(f"{label}: min must be less than max")
        if step_value <= 0:
            raise VisualStepIRValidationError(f"{label}: step must be positive")
        if not (min_value <= default_value <= max_value):
            raise VisualStepIRValidationError(f"{label}: default must be inside domain")

    def _validate_interaction_control(
        self,
        control: Any,
        parameter: str,
        label: str,
    ) -> None:
        if not isinstance(control, dict):
            raise VisualStepIRValidationError(f"{label}: control must be an object")
        if str(control.get("var") or "") != parameter:
            raise VisualStepIRValidationError(f"{label}: control var must match parameter")
        if not str(control.get("label") or "").strip():
            raise VisualStepIRValidationError(f"{label}: missing label")
        for key in ("min", "max", "step"):
            if key not in control:
                raise VisualStepIRValidationError(f"{label}: missing {key}")

    def _validate_parameterized_point(self, payload: Any, label: str) -> None:
        if not isinstance(payload, dict):
            raise VisualStepIRValidationError(f"{label}: payload must be an object")
        expression = payload.get("expression")
        if not isinstance(expression, list) or len(expression) != 2:
            raise VisualStepIRValidationError(f"{label}: expression must be a 2-item list")
        if not all(str(item).strip() for item in expression):
            raise VisualStepIRValidationError(f"{label}: expression values cannot be empty")
        if not isinstance(payload.get("source"), dict):
            raise VisualStepIRValidationError(f"{label}: missing source provenance")

    def _validate_timeline(
        self,
        timeline: dict[str, Any] | None,
        label: str,
        *,
        interaction_vars: set[str],
    ) -> None:
        if timeline is None:
            return
        mode = timeline.get("mode", "none")
        if mode not in VALID_TIMELINE_MODES:
            raise VisualStepIRValidationError(f"{label}: invalid timeline mode: {mode}")
        if "frames" in timeline:
            raise VisualStepIRValidationError(f"{label}: frames are no longer supported; use beats")
        beats = timeline.get("beats") or []
        if mode == "none":
            if beats:
                raise VisualStepIRValidationError(f"{label}: mode none cannot define beats")
            return
        if not isinstance(beats, list) or not beats:
            raise VisualStepIRValidationError(f"{label}: non-none timeline requires beats")
        seen_beat_ids: set[str] = set()
        for index, beat in enumerate(beats):
            self._validate_timeline_beat(
                beat,
                f"{label}.beats[{index}]",
                seen_beat_ids=seen_beat_ids,
                interaction_vars=interaction_vars,
            )

    def _validate_timeline_beat(
        self,
        beat: Any,
        label: str,
        *,
        seen_beat_ids: set[str],
        interaction_vars: set[str],
    ) -> None:
        if not isinstance(beat, dict):
            raise VisualStepIRValidationError(f"{label}: beat must be an object")
        beat_id = str(beat.get("id") or "")
        if not beat_id:
            raise VisualStepIRValidationError(f"{label}: missing beat id")
        if beat_id in seen_beat_ids:
            raise VisualStepIRValidationError(f"{label}: duplicate beat id: {beat_id}")
        seen_beat_ids.add(beat_id)
        try:
            duration = int(beat.get("duration_ms", 0))
        except Exception as exc:
            raise VisualStepIRValidationError(f"{label}: duration_ms must be numeric") from exc
        if duration <= 0:
            raise VisualStepIRValidationError(f"{label}: duration_ms must be positive")
        patch = beat.get("scene_patch")
        if not isinstance(patch, dict):
            raise VisualStepIRValidationError(f"{label}: missing scene_patch")
        for index, item in enumerate(patch.get("add") or ()):
            self._validate_scene_item(item, f"{label}.scene_patch.add[{index}]")
        for index, item in enumerate(patch.get("state_overrides") or ()):
            self._validate_state_override(item, f"{label}.scene_patch.state_overrides[{index}]")
        self._validate_transition(beat.get("transition"), f"{label}.transition", interaction_vars)

    def _validate_transition(
        self,
        transition: Any,
        label: str,
        interaction_vars: set[str],
    ) -> None:
        if not isinstance(transition, dict):
            raise VisualStepIRValidationError(f"{label}: missing transition")
        transition_type = str(transition.get("type") or "")
        if transition_type not in VALID_TRANSITION_TYPES:
            raise VisualStepIRValidationError(f"{label}: invalid transition type: {transition_type}")
        easing = str(transition.get("easing") or "")
        if easing not in VALID_TRANSITION_EASINGS:
            raise VisualStepIRValidationError(f"{label}: invalid easing: {easing}")
        try:
            duration = int(transition.get("duration_ms", 0))
        except Exception as exc:
            raise VisualStepIRValidationError(f"{label}: duration_ms must be numeric") from exc
        if duration <= 0:
            raise VisualStepIRValidationError(f"{label}: duration_ms must be positive")
        local_vars = transition.get("local_vars") or {}
        if not isinstance(local_vars, dict):
            raise VisualStepIRValidationError(f"{label}: local_vars must be an object")
        for key, payload in local_vars.items():
            if str(key) not in interaction_vars:
                raise VisualStepIRValidationError(f"{label}: unknown local var: {key}")
            if not isinstance(payload, dict):
                raise VisualStepIRValidationError(f"{label}: local var tween must be an object")
            if "keyframes" in payload:
                self._validate_local_var_keyframes(payload["keyframes"], f"{label}.local_vars[{key}].keyframes")
                continue
            for bound in ("from", "to"):
                if bound not in payload:
                    raise VisualStepIRValidationError(f"{label}: local var tween missing {bound}")
                try:
                    float(payload[bound])
                except Exception as exc:
                    raise VisualStepIRValidationError(
                        f"{label}: local var tween values must be numeric"
                    ) from exc

    def _validate_local_var_keyframes(self, keyframes: Any, label: str) -> None:
        if not isinstance(keyframes, list) or len(keyframes) < 2:
            raise VisualStepIRValidationError(f"{label}: keyframes must contain at least two points")
        previous_at = -1.0
        for index, frame in enumerate(keyframes):
            if not isinstance(frame, dict):
                raise VisualStepIRValidationError(f"{label}[{index}]: keyframe must be an object")
            if "at" not in frame or "value" not in frame:
                raise VisualStepIRValidationError(f"{label}[{index}]: keyframe requires at and value")
            try:
                at = float(frame["at"])
                float(frame["value"])
            except Exception as exc:
                raise VisualStepIRValidationError(f"{label}[{index}]: keyframe values must be numeric") from exc
            if not (0 <= at <= 1):
                raise VisualStepIRValidationError(f"{label}[{index}]: keyframe at must be in [0, 1]")
            if at < previous_at:
                raise VisualStepIRValidationError(f"{label}[{index}]: keyframe at must be sorted")
            previous_at = at

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


def _interaction_vars(interactions: tuple[dict[str, Any], ...]) -> set[str]:
    out: set[str] = set()
    for item in interactions or ():
        if not isinstance(item, dict):
            continue
        parameter = str(item.get("parameter") or "")
        if parameter:
            out.add(parameter)
        for control in item.get("controls") or ():
            if isinstance(control, dict) and control.get("var"):
                out.add(str(control["var"]))
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
