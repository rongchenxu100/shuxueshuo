"""Recursive ``visual-step-ir/v2`` data models.

The serialized document mirrors ``lesson-ir/v2``. A geometry definition being
present in ``geometry_registry`` never makes it visible: every frame carries a
complete, explicit list of visible objects. Flat traversal helpers are derived
in memory only for the pre-G1 page compiler.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterator, Mapping
import copy


JsonObject = dict[str, Any]
VISUAL_STEP_IR_CONTRACT = "visual-step-ir/v2"
VISIBLE_OBJECT_STATES = frozenset({"focus", "context"})
VISUAL_MODES = frozenset({"scene", "retain", "none"})


class VisualStepIRModelError(ValueError):
    """A serialized recursive visual document is malformed."""


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


@dataclass(frozen=True)
class VisualObject:
    """One explicitly visible semantic component in a resolved frame."""

    visual_object_id: str
    component: str
    role: str
    source_refs: tuple[JsonObject, ...]
    geometry_refs: tuple[str, ...]
    state: str
    component_payload: JsonObject = field(default_factory=dict)
    display_label: str | None = None

    def __post_init__(self) -> None:
        if not self.visual_object_id or not self.component or not self.role:
            raise VisualStepIRModelError("visual_object_identity_missing")
        if self.state not in VISIBLE_OBJECT_STATES:
            raise VisualStepIRModelError(
                f"visual_object_state_invalid: {self.visual_object_id}: {self.state}"
            )
        if not self.source_refs:
            raise VisualStepIRModelError(
                f"visual_object_source_refs_missing: {self.visual_object_id}"
            )
        if "component" in self.component_payload:
            raise VisualStepIRModelError(
                f"visual_object_payload_component_duplicated: {self.visual_object_id}"
            )

    def to_payload(self) -> JsonObject:
        payload: JsonObject = {
            "visual_object_id": self.visual_object_id,
            "component": self.component,
            "role": self.role,
            "source_refs": _clone(list(self.source_refs)),
            "geometry_refs": list(self.geometry_refs),
            "state": self.state,
            "component_payload": _clone(self.component_payload),
        }
        if self.display_label:
            payload["display_label"] = self.display_label
        return payload

    def to_scene_item(self) -> JsonObject:
        """Return the low-level compiler input without recursive ownership."""

        payload = _clone(self.component_payload)
        payload["component"] = self.component
        payload["state"] = self.state
        payload.setdefault("handle", self.visual_object_id)
        return payload


@dataclass(frozen=True)
class VisualFrame:
    """A complete, independently renderable scene for one teaching phase."""

    frame_id: str
    teaching_unit_keys: tuple[str, ...]
    viewport: JsonObject
    objects: tuple[VisualObject, ...]
    caption: str | None = None
    local_parameters: tuple[JsonObject, ...] = ()
    timeline: JsonObject | None = None
    metadata: JsonObject = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.frame_id:
            raise VisualStepIRModelError("visual_frame_id_missing")
        ids = [item.visual_object_id for item in self.objects]
        if len(ids) != len(set(ids)):
            raise VisualStepIRModelError(
                f"visual_frame_object_id_duplicated: {self.frame_id}"
            )

    def to_payload(self) -> JsonObject:
        payload: JsonObject = {
            "frame_id": self.frame_id,
            "teaching_unit_keys": list(self.teaching_unit_keys),
            "viewport": _clone(self.viewport),
            "objects": [item.to_payload() for item in self.objects],
            "local_parameters": _clone(list(self.local_parameters)),
        }
        if self.caption:
            payload["caption"] = self.caption
        if self.timeline is not None:
            payload["timeline"] = _clone(self.timeline)
        return payload

    @property
    def scene(self) -> JsonObject:
        """Temporary compiler view; never serialized in v2."""

        return {
            "add": [item.to_scene_item() for item in self.objects],
            "annotations": _clone(self.metadata.get("annotations") or []),
        }


@dataclass(frozen=True)
class VisualStep:
    """One visual step owned by its recursive container."""

    visual_step_id: str
    lesson_step_id: str
    visual_mode: str
    frames: tuple[VisualFrame, ...]
    metadata: JsonObject = field(default_factory=dict, repr=False, compare=False)
    owner_scope_ref: str = field(default="", repr=False, compare=False)
    owner_goal_ref: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.visual_step_id or not self.lesson_step_id:
            raise VisualStepIRModelError("visual_step_identity_missing")
        if self.visual_mode not in VISUAL_MODES:
            raise VisualStepIRModelError(
                f"visual_step_mode_invalid: {self.visual_step_id}: {self.visual_mode}"
            )
        if self.visual_mode == "none" and self.frames:
            raise VisualStepIRModelError(
                f"visual_step_none_has_frames: {self.visual_step_id}"
            )
        if self.visual_mode != "none" and not self.frames:
            raise VisualStepIRModelError(
                f"visual_step_frames_missing: {self.visual_step_id}"
            )
        frame_ids = [item.frame_id for item in self.frames]
        if len(frame_ids) != len(set(frame_ids)):
            raise VisualStepIRModelError(
                f"visual_frame_id_duplicated: {self.visual_step_id}"
            )

    def to_payload(self) -> JsonObject:
        return {
            "visual_step_id": self.visual_step_id,
            "lesson_step_id": self.lesson_step_id,
            "visual_mode": self.visual_mode,
            "frames": [item.to_payload() for item in self.frames],
        }

    @property
    def scope_id(self) -> str:
        """Derived pre-G1 adapter; ownership is not serialized here."""

        return self.owner_scope_ref

    @property
    def local_parameters(self) -> tuple[JsonObject, ...]:
        return self.frames[0].local_parameters if self.frames else ()

    @property
    def interactions(self) -> tuple[JsonObject, ...]:
        """Legacy name used by deterministic animation helpers."""

        return self.local_parameters

    @property
    def timeline(self) -> JsonObject | None:
        return self.frames[0].timeline if self.frames else None

    @property
    def scene(self) -> JsonObject:
        """Legacy single-frame view for diagnostics only."""

        return self.frames[0].scene if self.frames else {"add": [], "annotations": []}


@dataclass(frozen=True)
class VisualGoal:
    goal_ref: str
    steps: tuple[VisualStep, ...] = ()

    def to_payload(self) -> JsonObject:
        return {"steps": [item.to_payload() for item in self.steps]}


@dataclass(frozen=True)
class VisualScope:
    scope_ref: str
    steps: tuple[VisualStep, ...] = ()
    goals: tuple[VisualGoal, ...] = ()
    children: tuple["VisualScope", ...] = ()

    def to_payload(self) -> JsonObject:
        return {
            "scope_ref": self.scope_ref,
            "steps": [item.to_payload() for item in self.steps],
            "goals": {item.goal_ref: item.to_payload() for item in self.goals},
            "children": [item.to_payload() for item in self.children],
        }


@dataclass(frozen=True)
class VisualTraversalIndex:
    preorder_steps: tuple[VisualStep, ...]
    owner_by_step_id: Mapping[str, tuple[str, str | None]]
    scope_by_ref: Mapping[str, VisualScope]
    goal_by_ref: Mapping[str, VisualGoal]

    @classmethod
    def build(cls, root: VisualScope) -> "VisualTraversalIndex":
        rows: list[VisualStep] = []
        owners: dict[str, tuple[str, str | None]] = {}
        scopes: dict[str, VisualScope] = {}
        goals: dict[str, VisualGoal] = {}

        def append(step: VisualStep, scope_ref: str, goal_ref: str | None) -> None:
            if step.lesson_step_id in owners:
                raise VisualStepIRModelError(
                    f"visual_step_lesson_id_duplicated: {step.lesson_step_id}"
                )
            rows.append(
                replace(
                    step,
                    owner_scope_ref=scope_ref,
                    owner_goal_ref=goal_ref,
                )
            )
            owners[step.lesson_step_id] = (scope_ref, goal_ref)

        def visit(scope: VisualScope) -> None:
            if scope.scope_ref in scopes:
                raise VisualStepIRModelError(
                    f"visual_scope_duplicated: {scope.scope_ref}"
                )
            scopes[scope.scope_ref] = scope
            for step in scope.steps:
                append(step, scope.scope_ref, None)
            for goal in scope.goals:
                if goal.goal_ref in goals:
                    raise VisualStepIRModelError(
                        f"visual_goal_duplicated: {goal.goal_ref}"
                    )
                goals[goal.goal_ref] = goal
                for step in goal.steps:
                    append(step, scope.scope_ref, goal.goal_ref)
            for child in scope.children:
                visit(child)

        visit(root)
        return cls(tuple(rows), owners, scopes, goals)


@dataclass(frozen=True)
class VisualStepIR:
    """The persisted recursive visual document."""

    problem_id: str
    source_snapshot_hash: str
    source_lesson_hash: str
    geometry_registry: JsonObject
    root_scope: VisualScope
    metadata: JsonObject = field(default_factory=dict)
    compile_lesson_data: JsonObject = field(default_factory=dict, repr=False, compare=False)
    state_authority: JsonObject = field(default_factory=dict, repr=False, compare=False)
    schema_version: str = VISUAL_STEP_IR_CONTRACT

    def __post_init__(self) -> None:
        if self.schema_version != VISUAL_STEP_IR_CONTRACT:
            raise VisualStepIRModelError(
                f"visual_step_ir_schema_version_invalid: {self.schema_version}"
            )
        if not self.problem_id or not self.source_snapshot_hash or not self.source_lesson_hash:
            raise VisualStepIRModelError("visual_step_ir_identity_missing")
        VisualTraversalIndex.build(self.root_scope)

    def to_payload(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "problem_id": self.problem_id,
            "source_snapshot_hash": self.source_snapshot_hash,
            "source_lesson_hash": self.source_lesson_hash,
            "geometry_registry": _clone(self.geometry_registry),
            "root_scope": self.root_scope.to_payload(),
            "metadata": _clone(self.metadata),
        }

    @property
    def version(self) -> int:
        return 2

    @property
    def traversal(self) -> VisualTraversalIndex:
        return VisualTraversalIndex.build(self.root_scope)

    @property
    def steps(self) -> tuple[VisualStep, ...]:
        """Read-only preorder index; absent from ``to_payload``."""

        return self.traversal.preorder_steps

    @property
    def geometry_spec(self) -> JsonObject:
        """Temporary spelling consumed by existing role binders."""

        return self.geometry_registry

    @property
    def lesson_data(self) -> JsonObject:
        return self.compile_lesson_data


def visual_object_from_payload(payload: JsonObject) -> VisualObject:
    allowed = {
        "visual_object_id",
        "component",
        "role",
        "source_refs",
        "geometry_refs",
        "state",
        "component_payload",
        "display_label",
    }
    _require_exact_keys(payload, allowed, "visual_object", optional={"display_label"})
    return VisualObject(
        visual_object_id=str(payload["visual_object_id"]),
        component=str(payload["component"]),
        role=str(payload["role"]),
        source_refs=tuple(_clone(payload["source_refs"])),
        geometry_refs=tuple(str(item) for item in payload["geometry_refs"]),
        state=str(payload["state"]),
        component_payload=_clone(payload["component_payload"]),
        display_label=(str(payload["display_label"]) if payload.get("display_label") is not None else None),
    )


def visual_frame_from_payload(payload: JsonObject) -> VisualFrame:
    allowed = {
        "frame_id",
        "caption",
        "teaching_unit_keys",
        "viewport",
        "objects",
        "local_parameters",
        "timeline",
    }
    _require_exact_keys(payload, allowed, "visual_frame", optional={"caption", "timeline"})
    return VisualFrame(
        frame_id=str(payload["frame_id"]),
        caption=str(payload["caption"]) if payload.get("caption") is not None else None,
        teaching_unit_keys=tuple(str(item) for item in payload["teaching_unit_keys"]),
        viewport=_clone(payload["viewport"]),
        objects=tuple(visual_object_from_payload(item) for item in payload["objects"]),
        local_parameters=tuple(_clone(payload["local_parameters"])),
        timeline=_clone(payload.get("timeline")) if payload.get("timeline") is not None else None,
    )


def visual_step_from_payload(payload: JsonObject) -> VisualStep:
    _require_exact_keys(
        payload,
        {"visual_step_id", "lesson_step_id", "visual_mode", "frames"},
        "visual_step",
    )
    return VisualStep(
        visual_step_id=str(payload["visual_step_id"]),
        lesson_step_id=str(payload["lesson_step_id"]),
        visual_mode=str(payload["visual_mode"]),
        frames=tuple(visual_frame_from_payload(item) for item in payload["frames"]),
    )


def _visual_goal_from_payload(goal_ref: str, payload: JsonObject) -> VisualGoal:
    _require_exact_keys(payload, {"steps"}, f"visual_goal:{goal_ref}")
    return VisualGoal(
        goal_ref=goal_ref,
        steps=tuple(visual_step_from_payload(item) for item in payload["steps"]),
    )


def _visual_scope_from_payload(payload: JsonObject) -> VisualScope:
    _require_exact_keys(
        payload,
        {"scope_ref", "steps", "goals", "children"},
        "visual_scope",
    )
    goals = payload["goals"]
    if not isinstance(goals, dict):
        raise VisualStepIRModelError("visual_scope_goals_not_object")
    return VisualScope(
        scope_ref=str(payload["scope_ref"]),
        steps=tuple(visual_step_from_payload(item) for item in payload["steps"]),
        goals=tuple(_visual_goal_from_payload(str(key), value) for key, value in goals.items()),
        children=tuple(_visual_scope_from_payload(item) for item in payload["children"]),
    )


def visual_step_ir_from_payload(payload: JsonObject) -> VisualStepIR:
    if payload.get("schema_version") != VISUAL_STEP_IR_CONTRACT:
        observed = payload.get("schema_version") or payload.get("version") or "missing"
        raise VisualStepIRModelError(
            f"visual_step_ir_legacy_or_unknown_contract: {observed}"
        )
    allowed = {
        "schema_version",
        "problem_id",
        "source_snapshot_hash",
        "source_lesson_hash",
        "geometry_registry",
        "root_scope",
        "metadata",
    }
    _require_exact_keys(payload, allowed, "visual_step_ir", optional={"metadata"})
    return VisualStepIR(
        schema_version=str(payload["schema_version"]),
        problem_id=str(payload["problem_id"]),
        source_snapshot_hash=str(payload["source_snapshot_hash"]),
        source_lesson_hash=str(payload["source_lesson_hash"]),
        geometry_registry=_clone(payload["geometry_registry"]),
        root_scope=_visual_scope_from_payload(payload["root_scope"]),
        metadata=_clone(payload.get("metadata") or {}),
    )


def iter_visual_steps(scope: VisualScope) -> Iterator[tuple[str, str | None, VisualStep]]:
    for step in scope.steps:
        yield scope.scope_ref, None, step
    for goal in scope.goals:
        for step in goal.steps:
            yield scope.scope_ref, goal.goal_ref, step
    for child in scope.children:
        yield from iter_visual_steps(child)


def _require_exact_keys(
    payload: Any,
    allowed: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    if not isinstance(payload, dict):
        raise VisualStepIRModelError(f"{label}_not_object")
    optional = optional or set()
    required = allowed - optional
    missing = sorted(required - set(payload))
    extra = sorted(set(payload) - allowed)
    if missing or extra:
        raise VisualStepIRModelError(
            f"{label}_keys_invalid: missing={missing}, extra={extra}"
        )
