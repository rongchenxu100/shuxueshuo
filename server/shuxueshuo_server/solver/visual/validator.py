"""Validation for recursive ``visual-step-ir/v2`` documents."""

from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import TYPE_CHECKING, Any

from .models import VisualFrame, VisualStep, VisualStepIR
from .recursive_state import geometry_refs_from_scene_item
from .registry import ComponentTypeSpecRegistry, default_component_registry
from .math_state import validate_frame_math_state

if TYPE_CHECKING:
    from shuxueshuo_server.solver.explanation.lesson_ir import LessonIR, LessonScope


class VisualStepIRValidationError(ValueError):
    """VisualStepIR validation failed."""


VALID_TRANSIENT_STATES = {
    "constructed",
    "emphasized",
    "focus",
    "hidden",
    "highlight",
    "moving",
    "muted",
    "result",
    "visible",
}

VALID_TIMELINE_MODES = {"manual_then_interactive", "none"}
VALID_TRANSITION_TYPES = {"cut", "fade", "draw", "fade_draw", "tween"}
VALID_TRANSITION_EASINGS = {"linear", "easeInOutCubic"}


class VisualStepIRValidator:
    def __init__(
        self,
        *,
        component_registry: ComponentTypeSpecRegistry | None = None,
    ) -> None:
        self.component_registry = component_registry or default_component_registry()

    def validate(
        self,
        visual_ir: VisualStepIR,
        *,
        lesson: "LessonIR | None" = None,
    ) -> None:
        self._seen_visual_step_ids: set[str] = set()
        self._seen_frame_ids: set[str] = set()
        if lesson is not None:
            self._validate_lesson_authority(visual_ir, lesson)
        lesson_steps = _lesson_steps_by_id(visual_ir.lesson_data)
        observed = {step.lesson_step_id for step in visual_ir.steps}
        expected = set(lesson_steps)
        if expected and observed != expected:
            raise VisualStepIRValidationError(
                "visual_lesson_step_topology_mismatch: "
                f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
            )
        for step in visual_ir.steps:
            self._validate_step(step, lesson_steps, visual_ir.geometry_registry)

    def _validate_lesson_authority(
        self,
        visual_ir: VisualStepIR,
        lesson: "LessonIR",
    ) -> None:
        if visual_ir.problem_id != lesson.problem_id:
            raise VisualStepIRValidationError("visual_lesson_problem_identity_mismatch")
        if visual_ir.source_snapshot_hash != lesson.source_snapshot_hash:
            raise VisualStepIRValidationError("visual_lesson_snapshot_hash_mismatch")
        expected_hash = sha256(
            json.dumps(
                lesson.to_payload(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if visual_ir.source_lesson_hash != expected_hash:
            raise VisualStepIRValidationError("visual_lesson_hash_mismatch")
        _validate_recursive_topology(
            lesson.root_scope,
            visual_ir.root_scope,
            label="root_scope",
        )

    def _validate_step(
        self,
        step: VisualStep,
        lesson_steps: dict[str, dict[str, Any]],
        geometry_registry: dict[str, Any],
    ) -> None:
        label = f"visual_step:{step.visual_step_id}"
        if step.visual_step_id in self._seen_visual_step_ids:
            raise VisualStepIRValidationError(
                f"{label}: visual_step_id duplicated"
            )
        self._seen_visual_step_ids.add(step.visual_step_id)
        if not step.lesson_step_id:
            raise VisualStepIRValidationError(f"{label}: missing lesson_step_id")
        if step.lesson_step_id not in lesson_steps:
            raise VisualStepIRValidationError(
                f"{label}: unknown lesson_step_id: {step.lesson_step_id}"
            )
        from .teaching_diagrams import validate_diagram_block
        for block in step.diagram_blocks:
            validate_diagram_block(block)
        if step.visual_mode == "none":
            return
        for frame_index, frame in enumerate(step.frames):
            if frame.frame_id in self._seen_frame_ids:
                raise VisualStepIRValidationError(
                    f"{label}: frame_id duplicated: {frame.frame_id}"
                )
            self._seen_frame_ids.add(frame.frame_id)
            self._validate_frame(
                frame,
                f"{label}.frames[{frame_index}]",
                geometry_registry=geometry_registry,
            )

    def _validate_frame(
        self,
        frame: VisualFrame,
        label: str,
        *,
        geometry_registry: dict[str, Any],
    ) -> None:
        viewport = frame.viewport
        if set(viewport) != {"minX", "maxX", "minY", "maxY"}:
            raise VisualStepIRValidationError(f"{label}: viewport fields invalid")
        if float(viewport["minX"]) >= float(viewport["maxX"]):
            raise VisualStepIRValidationError(f"{label}: viewport x range invalid")
        if float(viewport["minY"]) >= float(viewport["maxY"]):
            raise VisualStepIRValidationError(f"{label}: viewport y range invalid")
        known_geometry = set((geometry_registry.get("fixedPoints") or {}).keys())
        known_geometry.update((geometry_registry.get("movingPoints") or {}).keys())
        known_geometry.update(
            str(item.get("id"))
            for item in geometry_registry.get("curves") or ()
            if isinstance(item, dict) and item.get("id")
        )
        for index, visual_object in enumerate(frame.objects):
            item_label = f"{label}.objects[{index}]"
            self._validate_scene_item(visual_object.to_scene_item(), item_label)
            unknown = sorted(set(visual_object.geometry_refs) - known_geometry)
            if unknown:
                raise VisualStepIRValidationError(
                    f"{item_label}: unknown geometry refs: {unknown}"
                )
        frame_geometry_refs = {
            ref for item in frame.objects for ref in item.geometry_refs
        }
        for index, item in enumerate(frame.local_parameters):
            self._validate_local_parameter(
                item,
                f"{label}.local_parameters[{index}]",
                known_geometry=known_geometry,
                frame_geometry_refs=frame_geometry_refs,
            )
        self._validate_timeline(
            frame.timeline,
            f"{label}.timeline",
            interaction_vars={
                str(item.get("name") or "") for item in frame.local_parameters
            },
            frame_geometry_refs=frame_geometry_refs,
        )
        try:
            validate_frame_math_state(frame, geometry_registry)
        except ValueError as exc:
            raise VisualStepIRValidationError(f"{label}: {exc}") from exc

    def _validate_scene_item(self, item: dict[str, Any], label: str) -> None:
        component = item.get("component")
        if not component:
            raise VisualStepIRValidationError(f"{label}: missing component")
        spec = self.component_registry.get(str(component))
        if spec is None:
            raise VisualStepIRValidationError(f"{label}: unknown component: {component}")
        for role in spec.required_roles:
            if role not in item or item.get(role) in (None, "", []):
                raise VisualStepIRValidationError(f"{label}: missing required role: {role}")

    def _validate_local_parameter(
        self,
        item: dict[str, Any],
        label: str,
        *,
        known_geometry: set[str],
        frame_geometry_refs: set[str],
    ) -> None:
        required = {
            "name",
            "mathematical_domain",
            "display_window",
            "default_value",
            "source_refs",
            "controls",
            "parameterized_points",
            "landmarks",
            "note",
        }
        if set(item) != required:
            raise VisualStepIRValidationError(f"{label}: fields invalid")
        name = str(item.get("name") or "")
        if not name:
            raise VisualStepIRValidationError(f"{label}: name missing")
        window = item.get("display_window")
        if not isinstance(window, dict):
            raise VisualStepIRValidationError(f"{label}: display_window missing")
        mathematical_domain = item.get("mathematical_domain")
        exact = (
            isinstance(mathematical_domain, dict)
            and mathematical_domain.get("kind") == "exact"
        )
        controls = item.get("controls")
        self._validate_parameter_landmarks(
            item.get("landmarks"),
            f"{label}.landmarks",
            known_geometry=known_geometry,
            frame_geometry_refs=frame_geometry_refs,
        )
        if exact:
            if controls != []:
                raise VisualStepIRValidationError(
                    f"{label}: exact parameter must not expose controls"
                )
            if window.get("min") != window.get("max"):
                raise VisualStepIRValidationError(
                    f"{label}: exact parameter window must be a point"
                )
            if item.get("default_value") != window.get("min"):
                raise VisualStepIRValidationError(
                    f"{label}: exact parameter value mismatch"
                )
            return
        domain = {
            "min": window.get("min"),
            "max": window.get("max"),
            "step": window.get("step"),
            "default": item.get("default_value"),
        }
        self._validate_interaction_domain(domain, f"{label}.display_window")
        if not isinstance(controls, list):
            raise VisualStepIRValidationError(f"{label}: controls must be an array")
        for index, control in enumerate(controls):
            self._validate_interaction_control(
                control,
                name,
                f"{label}.controls[{index}]",
            )
        parameterized = item.get("parameterized_points")
        if not isinstance(parameterized, dict):
            raise VisualStepIRValidationError(f"{label}: parameterized_points invalid")
        for point_id, payload in parameterized.items():
            self._validate_parameterized_point(
                payload,
                f"{label}.parameterized_points[{point_id}]",
            )

    def _validate_parameter_landmarks(
        self,
        landmarks: Any,
        label: str,
        *,
        known_geometry: set[str],
        frame_geometry_refs: set[str],
    ) -> None:
        if not isinstance(landmarks, list):
            raise VisualStepIRValidationError(f"{label}: must be an array")
        required = {
            "value",
            "exact_value",
            "display",
            "epsilon",
            "candidate_geometry_refs",
            "highlight_geometry_refs",
        }
        for index, landmark in enumerate(landmarks):
            item_label = f"{label}[{index}]"
            if not isinstance(landmark, dict) or set(landmark) != required:
                raise VisualStepIRValidationError(f"{item_label}: fields invalid")
            try:
                value = float(landmark["value"])
                epsilon = float(landmark["epsilon"])
            except Exception as exc:
                raise VisualStepIRValidationError(
                    f"{item_label}: value and epsilon must be numeric"
                ) from exc
            if not math.isfinite(value) or not math.isfinite(epsilon) or epsilon <= 0:
                raise VisualStepIRValidationError(
                    f"{item_label}: value/epsilon must be finite and epsilon positive"
                )
            if not str(landmark.get("exact_value") or "").strip():
                raise VisualStepIRValidationError(f"{item_label}: exact_value missing")
            if not str(landmark.get("display") or "").strip():
                raise VisualStepIRValidationError(f"{item_label}: display missing")
            for key in ("candidate_geometry_refs", "highlight_geometry_refs"):
                refs = landmark.get(key)
                if not isinstance(refs, list) or not all(
                    isinstance(ref, str) and ref for ref in refs
                ):
                    raise VisualStepIRValidationError(f"{item_label}.{key}: invalid")
                unknown = sorted(set(refs) - known_geometry)
                invisible = sorted(set(refs) - frame_geometry_refs)
                if unknown:
                    raise VisualStepIRValidationError(
                        f"{item_label}.{key}: unknown geometry refs: {unknown}"
                    )
                if invisible:
                    raise VisualStepIRValidationError(
                        f"{item_label}.{key}: refs outside frame: {invisible}"
                    )

    def _validate_state_override(self, item: dict[str, Any], label: str) -> None:
        if not item.get("handle"):
            raise VisualStepIRValidationError(f"{label}: missing handle")
        state = item.get("state")
        if state not in VALID_TRANSIENT_STATES:
            raise VisualStepIRValidationError(f"{label}: invalid state: {state}")

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
        frame_geometry_refs: set[str],
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
                frame_geometry_refs=frame_geometry_refs,
            )

    def _validate_timeline_beat(
        self,
        beat: Any,
        label: str,
        *,
        seen_beat_ids: set[str],
        interaction_vars: set[str],
        frame_geometry_refs: set[str],
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
            undeclared = sorted(
                set(geometry_refs_from_scene_item(item)) - frame_geometry_refs
            )
            if undeclared:
                raise VisualStepIRValidationError(
                    f"{label}.scene_patch.add[{index}]: timeline geometry "
                    f"not declared by frame: {undeclared}"
                )
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

def _lesson_steps_by_id(lesson_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in lesson_data.get("steps") or ():
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def _validate_recursive_topology(
    lesson_scope: "LessonScope",
    visual_scope: Any,
    *,
    label: str,
) -> None:
    if visual_scope.scope_ref != lesson_scope.scope_ref:
        raise VisualStepIRValidationError(
            f"visual_scope_topology_mismatch: {label}: "
            f"{visual_scope.scope_ref} != {lesson_scope.scope_ref}"
        )
    lesson_scope_steps = [item.lesson_step_id for item in lesson_scope.steps]
    visual_scope_steps = [item.lesson_step_id for item in visual_scope.steps]
    if visual_scope_steps != lesson_scope_steps:
        raise VisualStepIRValidationError(
            f"visual_scope_step_order_mismatch: {label}: "
            f"expected={lesson_scope_steps}, observed={visual_scope_steps}"
        )
    lesson_goals = [item.goal_ref for item in lesson_scope.goals]
    visual_goals = [item.goal_ref for item in visual_scope.goals]
    if visual_goals != lesson_goals:
        raise VisualStepIRValidationError(
            f"visual_goal_topology_mismatch: {label}: "
            f"expected={lesson_goals}, observed={visual_goals}"
        )
    for lesson_goal, visual_goal in zip(
        lesson_scope.goals,
        visual_scope.goals,
        strict=True,
    ):
        lesson_steps = [item.lesson_step_id for item in lesson_goal.steps]
        visual_steps = [item.lesson_step_id for item in visual_goal.steps]
        if visual_steps != lesson_steps:
            raise VisualStepIRValidationError(
                f"visual_goal_step_order_mismatch: goal:{lesson_goal.goal_ref}: "
                f"expected={lesson_steps}, observed={visual_steps}"
            )
    if len(visual_scope.children) != len(lesson_scope.children):
        raise VisualStepIRValidationError(
            f"visual_child_scope_count_mismatch: {label}"
        )
    for index, (lesson_child, visual_child) in enumerate(
        zip(lesson_scope.children, visual_scope.children, strict=True)
    ):
        _validate_recursive_topology(
            lesson_child,
            visual_child,
            label=f"{label}.children[{index}]",
        )
