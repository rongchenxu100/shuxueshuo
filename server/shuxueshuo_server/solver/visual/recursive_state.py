"""Recursive branch state for ``visual-step-ir/v2``.

This module deliberately separates three concepts which the retired flat
pipeline conflated:

* the geometry registry says what *can* be drawn;
* branch state says which public mathematical objects are available here;
* a frame says which of those objects are actually visible now.

Goal and child branches receive clones of their parent's completed scope
state.  Their changes are never merged back into the parent or a sibling.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import copy
import json
import re
from typing import Any, Callable, Mapping

from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonGoal,
    LessonIR,
    LessonScope,
    OwnedLessonStep,
)
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingSource,
    iter_teaching_sources,
)

from .models import (
    JsonObject,
    VisualFrame,
    VisualGoal,
    VisualObject,
    VisualScope,
    VisualStep,
)


VISUAL_STATE_AUTHORITY_CONTRACT = "visual-state-authority/v1"


class RecursiveVisualStateError(ValueError):
    """A visual state cannot be resolved without crossing branch authority."""


@dataclass
class BranchVisualState:
    """Mutable state local to one resolver branch.

    ``available`` is the complete visible scene at the current branch
    position, keyed by semantic visual-object identity rather than a
    student-facing label.  ``last_frame`` preserves the same scene in render
    order.  ``parameters`` contains only values produced by steps already
    executed on this branch.
    """

    available: dict[str, VisualObject] = field(default_factory=dict)
    parameters: dict[str, str] = field(default_factory=dict)
    last_frame: tuple[VisualObject, ...] = ()
    last_container_ref: str | None = None

    def clone(self) -> "BranchVisualState":
        return BranchVisualState(
            available=copy.deepcopy(self.available),
            parameters=dict(self.parameters),
            last_frame=copy.deepcopy(self.last_frame),
            last_container_ref=self.last_container_ref,
        )

    def publish(self, objects: tuple[VisualObject, ...]) -> None:
        """Commit one complete Frame as the next branch-visible scene."""

        self.available = {
            item.visual_object_id: replace(item, state="context")
            for item in objects
        }


@dataclass(frozen=True)
class VisualStepResolution:
    step: VisualStep
    published_objects: tuple[VisualObject, ...]
    visibility_reasons: Mapping[str, str]


VisualStepResolver = Callable[
    [OwnedLessonStep, BranchVisualState],
    VisualStepResolution,
]


@dataclass(frozen=True)
class RecursiveVisualStateResult:
    root_scope: VisualScope
    authority: JsonObject


class RecursiveVisualStateResolver:
    """Resolve visual steps in the exact recursive LessonIR topology."""

    def __init__(self, snapshot: ExplanationSnapshot) -> None:
        self.snapshot = snapshot
        self.sources = {
            source.source_step_id: source
            for source in iter_teaching_sources(snapshot.root_scope)
        }
        self._authority_steps: dict[str, JsonObject] = {}
        self._containers: dict[str, JsonObject] = {}

    def resolve(
        self,
        lesson: LessonIR,
        step_resolver: VisualStepResolver,
    ) -> RecursiveVisualStateResult:
        self._authority_steps = {}
        self._containers = {}
        root = self._resolve_scope(
            lesson.root_scope,
            BranchVisualState(),
            step_resolver,
        )
        authority = {
            "schema_version": VISUAL_STATE_AUTHORITY_CONTRACT,
            "source_snapshot_hash": lesson.source_snapshot_hash,
            "containers": self._containers,
            "steps": self._authority_steps,
        }
        return RecursiveVisualStateResult(root_scope=root, authority=authority)

    def _resolve_scope(
        self,
        scope: LessonScope,
        inherited: BranchVisualState,
        step_resolver: VisualStepResolver,
    ) -> VisualScope:
        shared = inherited.clone()
        scope_steps = self._resolve_steps(
            scope.steps,
            scope_ref=scope.scope_ref,
            goal_ref=None,
            state=shared,
            step_resolver=step_resolver,
        )
        entry = shared.clone()

        goals: list[VisualGoal] = []
        for goal in scope.goals:
            goal_state = entry.clone()
            goal_steps = self._resolve_goal(
                goal,
                scope_ref=scope.scope_ref,
                state=goal_state,
                step_resolver=step_resolver,
            )
            goals.append(VisualGoal(goal_ref=goal.goal_ref, steps=goal_steps))

        children = tuple(
            self._resolve_scope(child, entry.clone(), step_resolver)
            for child in scope.children
        )
        self._containers.setdefault(
            f"scope:{scope.scope_ref}",
            {
                "available_before": sorted(inherited.available),
                "available_after_scope_steps": sorted(shared.available),
                "branch_entry": sorted(entry.available),
                "parameter_values": dict(sorted(entry.parameters.items())),
            },
        )
        return VisualScope(
            scope_ref=scope.scope_ref,
            steps=scope_steps,
            goals=tuple(goals),
            children=children,
        )

    def _resolve_goal(
        self,
        goal: LessonGoal,
        *,
        scope_ref: str,
        state: BranchVisualState,
        step_resolver: VisualStepResolver,
    ) -> tuple[VisualStep, ...]:
        before = sorted(state.available)
        steps = self._resolve_steps(
            goal.steps,
            scope_ref=scope_ref,
            goal_ref=goal.goal_ref,
            state=state,
            step_resolver=step_resolver,
        )
        self._containers[f"goal:{goal.goal_ref}"] = {
            "available_before": before,
            "available_after": sorted(state.available),
            "parameter_values": dict(sorted(state.parameters.items())),
        }
        return steps

    def _resolve_steps(
        self,
        steps: tuple[Any, ...],
        *,
        scope_ref: str,
        goal_ref: str | None,
        state: BranchVisualState,
        step_resolver: VisualStepResolver,
    ) -> tuple[VisualStep, ...]:
        result: list[VisualStep] = []
        for raw_step in steps:
            owned = OwnedLessonStep(raw_step, scope_ref, goal_ref)
            container_ref = (
                f"goal:{goal_ref}" if goal_ref is not None else f"scope:{scope_ref}"
            )
            before = set(state.available)
            parameter_before = dict(state.parameters)
            resolution = step_resolver(owned, state.clone())
            if resolution.step.lesson_step_id != owned.lesson_step_id:
                raise RecursiveVisualStateError(
                    "visual_step_resolution_lesson_identity_mismatch: "
                    f"{owned.lesson_step_id}"
                )
            state.publish(resolution.published_objects)
            if resolution.step.frames:
                state.last_frame = tuple(
                    context_copy(item)
                    for item in resolution.published_objects
                )
                state.last_container_ref = container_ref
            self._publish_parameter_outputs(owned, state)
            after = set(state.available)
            frame_objects = {
                item.visual_object_id: item
                for frame in resolution.step.frames
                for item in frame.objects
            }
            self._authority_steps[owned.lesson_step_id] = {
                "container_ref": container_ref,
                "available_before": sorted(before),
                "visible": [
                    {
                        "visual_object_id": object_id,
                        "state": item.state,
                        "reason": resolution.visibility_reasons.get(
                            object_id,
                            "current_visual_spec",
                        ),
                        "source_refs": copy.deepcopy(list(item.source_refs)),
                        "geometry_refs": list(item.geometry_refs),
                    }
                    for object_id, item in frame_objects.items()
                ],
                "introduced": sorted(after - before),
                "retained": sorted(after & before),
                "removed": sorted(before - after),
                "available_after": sorted(after),
                "parameter_values_before": parameter_before,
                "parameter_values_after": dict(state.parameters),
            }
            result.append(resolution.step)
        return tuple(result)

    def _publish_parameter_outputs(
        self,
        lesson_step: OwnedLessonStep,
        state: BranchVisualState,
    ) -> None:
        for step_id in lesson_step.source_step_ids:
            source = self.sources.get(step_id)
            if source is None:
                continue
            for return_name, output in source.outputs.items():
                runtime_type = str(output.get("runtime_type") or "")
                if runtime_type != "ParameterValue":
                    continue
                value = output.get("value")
                if value is None:
                    continue
                name = str(source.output_targets.get(return_name) or "")
                if not name:
                    name = _symbol_name_from_parameter_output(output)
                if name:
                    state.parameters[name] = str(value)


def visual_objects_from_scene_items(
    items: list[JsonObject],
    *,
    owner_scope_ref: str,
    source_step_ids: tuple[str, ...],
    focus: bool = True,
) -> tuple[VisualObject, ...]:
    """Normalize low-level scene items into semantic visible objects.

    IDs intentionally ignore transient handles and styling.  This makes line
    deduplication and state replacement independent of rendering cosmetics.
    """

    result: list[VisualObject] = []
    by_id: dict[str, int] = {}
    point_states: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        component = str(item.get("component") or "")
        if not component:
            continue
        geometry_refs = tuple(geometry_refs_from_scene_item(item))
        state = _visual_state_for_item(item, focus=focus)
        if component == "Point" and geometry_refs:
            point_states[geometry_refs[0]] = state
        if component == "CoordinateLabel" and geometry_refs:
            state = point_states.get(geometry_refs[0], state)
        role = _visual_role(item, component, geometry_refs)
        object_id = _visual_object_id(
            component=component,
            role=role,
            geometry_refs=geometry_refs,
            owner_scope_ref=owner_scope_ref,
            item=item,
        )
        payload = {
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key
            not in {
                "component",
                "state",
                "persistence",
                "decay_state",
                "metadata",
                "handle",
                "_source_step_ids",
            }
        }
        item_source_steps = tuple(
            str(step_id)
            for step_id in item.get("_source_step_ids") or source_step_ids
            if str(step_id)
        )
        source_refs = tuple(
            {
                "kind": "functional_step",
                "step_id": step_id,
            }
            for step_id in item_source_steps
        ) or (
            {
                "kind": "visual_auxiliary",
                "owner_scope_ref": owner_scope_ref,
                "role": role,
            },
        )
        visual = VisualObject(
            visual_object_id=object_id,
            component=component,
            role=role,
            source_refs=source_refs,
            geometry_refs=geometry_refs,
            state=state,
            component_payload=payload,
            display_label=_display_label(item),
        )
        previous_index = by_id.get(object_id)
        if previous_index is None:
            by_id[object_id] = len(result)
            result.append(visual)
        else:
            result[previous_index] = _prefer_visual_object(
                result[previous_index],
                visual,
            )
    return tuple(result)


def context_copy(item: VisualObject) -> VisualObject:
    return replace(item, state="context")


def _symbol_name_from_parameter_output(output: Mapping[str, Any]) -> str:
    display = str(output.get("display") or "")
    value = str(output.get("value") or "")
    for candidate in (display, value):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", candidate):
            return candidate
    return ""


def geometry_refs_from_scene_item(item: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, (Mapping, list, tuple)):
            return
        text = str(value or "")
        if text and text not in refs:
            refs.append(text)

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key in (
                "at",
                "from",
                "to",
                "source",
                "target",
                "vertex",
                "rayA",
                "rayB",
                "curveId",
                "lineStart",
                "lineEnd",
            ):
                add(value.get(key))
            for key in ("vertices", "points", "path"):
                sequence = value.get(key)
                if isinstance(sequence, (list, tuple)):
                    for part in sequence:
                        add(part)
            # Composite components carry their geometry inside structures
            # such as triangles[], segments[] and right_angles[].  Traverse
            # every nested container so the public geometry_refs contract is
            # exhaustive instead of being component-name dependent.
            for nested in value.values():
                if isinstance(nested, (Mapping, list, tuple)):
                    visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                if isinstance(nested, (Mapping, list, tuple)):
                    visit(nested)

    visit(item)
    return refs


def _visual_state_for_item(item: Mapping[str, Any], *, focus: bool) -> str:
    if not focus:
        return "context"
    raw_state = str(item.get("state") or "")
    if raw_state in {"muted", "context"}:
        return "context"
    color = str(item.get("color") or "")
    if color in {"#1f2937", "#64748b", "#94a3b8"}:
        return "context"
    return "focus"


def _visual_role(
    item: Mapping[str, Any],
    component: str,
    geometry_refs: tuple[str, ...],
) -> str:
    explicit = str(item.get("role") or "")
    if explicit:
        return explicit
    label = str(item.get("labelText") or item.get("label") or "")
    if component == "Point":
        return f"point:{label or (geometry_refs[0] if geometry_refs else 'unknown')}"
    if component == "CoordinateLabel":
        return f"coordinate:{geometry_refs[0] if geometry_refs else label or 'unknown'}"
    if component == "Parabola":
        return "curve:parabola"
    if component == "AxisOfSymmetry":
        return "curve:axis"
    return component.replace("Marker", "").replace(" ", "_").lower()


def _visual_object_id(
    *,
    component: str,
    role: str,
    geometry_refs: tuple[str, ...],
    owner_scope_ref: str,
    item: Mapping[str, Any],
) -> str:
    refs = geometry_refs
    if component in {"ColoredLine", "DashedLine", "DistanceMarker"} and len(refs) == 2:
        refs = tuple(sorted(refs))
    semantic = {
        "component": component,
        "role": role,
        "geometry_refs": refs,
        "owner": owner_scope_ref if not refs else "",
    }
    # A coordinate annotation is identified by the mathematical point, not by
    # punctuation or by whichever merged source step happened to format the
    # label.  Keeping the text in the identity produced two labels for the
    # same point when adjacent teaching materials were merged.
    digest = sha256(
        json.dumps(semantic, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"visual:{component.lower()}:{digest}"


def _display_label(item: Mapping[str, Any]) -> str | None:
    text = str(
        item.get("labelText")
        or item.get("label")
        or item.get("text")
        or ""
    ).strip()
    return text or None


def _prefer_visual_object(left: VisualObject, right: VisualObject) -> VisualObject:
    combined_sources = tuple(
        dict(item)
        for item in {
            json.dumps(item, ensure_ascii=False, sort_keys=True): item
            for item in (*left.source_refs, *right.source_refs)
        }.values()
    )
    if left.state == "focus" and right.state == "context":
        return replace(left, source_refs=combined_sources)
    if right.state == "focus" and left.state == "context":
        return replace(right, source_refs=combined_sources)
    # Preserve the first deterministic presentation, but retain provenance
    # from every merged source that requested the same semantic object.
    return replace(left, source_refs=combined_sources)


__all__ = [
    "BranchVisualState",
    "RecursiveVisualStateError",
    "RecursiveVisualStateResolver",
    "RecursiveVisualStateResult",
    "VisualStepResolution",
    "context_copy",
    "visual_objects_from_scene_items",
]
