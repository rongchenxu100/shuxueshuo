from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonGoal,
    LessonIR,
    LessonScope,
    LessonStep,
)
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingScope,
)
from shuxueshuo_server.solver.visual import (
    BranchVisualState,
    RecursiveVisualStateResolver,
    VisualFrame,
    VisualGoal,
    VisualObject,
    VisualScope,
    VisualStep,
    VisualStepIR,
    VisualStepIRValidationError,
    VisualStepIRValidator,
    VisualStepResolution,
    forward_compile,
    visual_step_ir_from_payload,
)
from shuxueshuo_server.solver.visual.compiler import reverse_compile
from shuxueshuo_server.solver.visual.models import VisualStepIRModelError


ROOT = Path(__file__).resolve().parents[3]
HASH = "0" * 64


def _lesson_step(step_id: str) -> LessonStep:
    return LessonStep(
        lesson_step_id=step_id,
        source_step_ids=(f"source_{step_id}",),
        capability_ids=("demo",),
        teaching_unit_keys=("demo/default",),
        title=step_id,
        nav_title=step_id,
        goal=step_id,
        derive=(("∴", step_id),),
        box=(),
    )


def _lesson() -> LessonIR:
    return LessonIR(
        problem_id="visual-v2-demo",
        problem_revision="problem-revision:visual-v2-demo",
        source_snapshot_hash=HASH,
        root_scope=LessonScope(
            scope_ref="problem",
            children=(
                LessonScope(
                    scope_ref="i",
                    steps=(_lesson_step("shared"),),
                    goals=(
                        LessonGoal("i.a", (_lesson_step("goal_a"),)),
                        LessonGoal("i.b", (_lesson_step("goal_b"),)),
                    ),
                    children=(
                        LessonScope(
                            scope_ref="i_1",
                            steps=(_lesson_step("child"),),
                        ),
                    ),
                ),
            ),
        ),
    )


def _visual_object(
    name: str,
    *,
    state: str = "focus",
    geometry_ref: str | None = None,
) -> VisualObject:
    ref = geometry_ref or name
    return VisualObject(
        visual_object_id=f"visual:point:{name}",
        component="Point",
        role=f"point:{name}",
        source_refs=({"kind": "source", "ref": name},),
        geometry_refs=(ref,),
        state=state,
        component_payload={"at": ref, "labelText": name},
        display_label=name,
    )


def _visual_step(step_id: str, *, frame_id: str | None = None) -> VisualStep:
    return VisualStep(
        visual_step_id=f"visual:{step_id}",
        lesson_step_id=step_id,
        visual_mode="scene",
        frames=(
            VisualFrame(
                frame_id=frame_id or f"frame:{step_id}",
                teaching_unit_keys=("demo/default",),
                viewport={"minX": -2, "maxX": 2, "minY": -2, "maxY": 2},
                objects=(_visual_object(step_id, geometry_ref="A"),),
            ),
        ),
    )


def _visual_ir(lesson: LessonIR | None = None) -> VisualStepIR:
    lesson = lesson or _lesson()
    visual_root = VisualScope(
        scope_ref="problem",
        children=(
            VisualScope(
                scope_ref="i",
                steps=(_visual_step("shared"),),
                goals=(
                    VisualGoal("i.a", (_visual_step("goal_a"),)),
                    VisualGoal("i.b", (_visual_step("goal_b"),)),
                ),
                children=(
                    VisualScope(
                        scope_ref="i_1",
                        steps=(_visual_step("child"),),
                    ),
                ),
            ),
        ),
    )
    lesson_hash = hashlib.sha256(
        json.dumps(
            lesson.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return VisualStepIR(
        problem_id=lesson.problem_id,
        source_snapshot_hash=lesson.source_snapshot_hash,
        source_lesson_hash=lesson_hash,
        geometry_registry={
            "fixedPoints": {"A": [0, 0], "unused": [1, 1]},
            "movingPoints": {},
            "pointMeta": {
                "A": {"label": "A", "scopeId": "problem"},
                "unused": {"label": "U", "scopeId": "problem"},
            },
            "curves": [],
            "domain": {"minX": -2, "maxX": 2, "minY": -2, "maxY": 2},
        },
        root_scope=visual_root,
        compile_lesson_data={
            "steps": [{"id": item.lesson_step_id} for item in lesson.steps]
        },
    )


def test_visual_step_ir_v2_round_trip_and_checked_in_schema() -> None:
    visual_ir = _visual_ir()
    payload = visual_ir.to_payload()

    restored = visual_step_ir_from_payload(payload)
    schema = json.loads(
        (ROOT / "internal/schemas/visual-step-ir.schema.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator(schema).validate(payload)
    assert restored.to_payload() == payload
    assert "steps" not in payload
    assert "layers" not in payload
    assert "scope_id" not in json.dumps(payload)


def test_visual_step_ir_v2_validator_matches_recursive_lesson_topology() -> None:
    lesson = _lesson()
    visual_ir = _visual_ir(lesson)

    VisualStepIRValidator().validate(visual_ir, lesson=lesson)

    first_scope = visual_ir.root_scope.children[0]
    wrong_child = replace(first_scope, scope_ref="ii")
    wrong = replace(visual_ir.root_scope, children=(wrong_child,))
    with pytest.raises(
        VisualStepIRValidationError,
        match="visual_scope_topology_mismatch",
    ):
        VisualStepIRValidator().validate(
            replace(visual_ir, root_scope=wrong),
            lesson=lesson,
        )


def test_visual_step_ir_v2_rejects_old_flat_contract_and_unknown_fields() -> None:
    with pytest.raises(
        VisualStepIRModelError,
        match="visual_step_ir_legacy_or_unknown_contract",
    ):
        visual_step_ir_from_payload({"version": 1, "steps": []})

    payload = _visual_ir().to_payload()
    payload["steps"] = []
    with pytest.raises(VisualStepIRModelError, match="visual_step_ir_keys_invalid"):
        visual_step_ir_from_payload(payload)


def test_visual_object_has_only_focus_or_context_state() -> None:
    with pytest.raises(VisualStepIRModelError, match="visual_object_state_invalid"):
        _visual_object("A", state="hidden")


def test_validator_rejects_unknown_geometry_and_duplicate_frame_identity() -> None:
    visual_ir = _visual_ir()
    first_scope = visual_ir.root_scope.children[0]
    bad_shared = replace(
        first_scope.steps[0],
        frames=(
            replace(
                first_scope.steps[0].frames[0],
                objects=(_visual_object("X", geometry_ref="missing"),),
            ),
        ),
    )
    with pytest.raises(VisualStepIRValidationError, match="unknown geometry refs"):
        VisualStepIRValidator().validate(
            replace(
                visual_ir,
                root_scope=replace(
                    visual_ir.root_scope,
                    children=(replace(first_scope, steps=(bad_shared,)),),
                ),
            )
        )

    duplicate = _visual_step("goal_a", frame_id="frame:shared")
    goals = (
        replace(first_scope.goals[0], steps=(duplicate,)),
        first_scope.goals[1],
    )
    with pytest.raises(VisualStepIRValidationError, match="frame_id duplicated"):
        VisualStepIRValidator().validate(
            replace(
                visual_ir,
                root_scope=replace(
                    visual_ir.root_scope,
                    children=(replace(first_scope, goals=goals),),
                ),
            )
        )


def test_geometry_registry_never_implies_visibility() -> None:
    compiled = forward_compile(_visual_ir())
    first = compiled.step_decorations["steps"]["shared"]
    serialized = json.dumps(first, ensure_ascii=False)

    assert "unused" not in serialized
    assert "layers" not in compiled.step_decorations
    assert "add" not in first
    assert "domain" not in first
    assert [item["type"] for item in first["visualFrames"][0]["add"]] == [
        "grid",
        "point",
    ]


def test_context_distance_marker_becomes_an_unlabelled_support_line() -> None:
    visual_ir = _visual_ir()
    first_scope = visual_ir.root_scope.children[0]
    source_step = first_scope.steps[0]
    distance = VisualObject(
        visual_object_id="visual:distance:A:unused",
        component="DistanceMarker",
        role="distance:equal-halves",
        source_refs=({"kind": "source", "ref": "midpoint-relation"},),
        geometry_refs=("A", "unused"),
        state="context",
        component_payload={"from": "A", "to": "unused", "label": "="},
        display_label="=",
    )
    revised_step = replace(
        source_step,
        frames=(replace(source_step.frames[0], objects=(distance,)),),
    )
    revised_ir = replace(
        visual_ir,
        root_scope=replace(
            visual_ir.root_scope,
            children=(replace(first_scope, steps=(revised_step,)),),
        ),
    )

    additions = forward_compile(revised_ir).step_decorations["steps"]["shared"][
        "visualFrames"
    ][0]["add"]
    support_line = next(item for item in additions if item["type"] == "coloredLine")

    assert support_line["from"] == "A"
    assert support_line["to"] == "unused"
    assert "label" not in support_line


def test_point_yields_its_name_to_coordinate_label_by_geometry_identity() -> None:
    visual_ir = _visual_ir()
    first_scope = visual_ir.root_scope.children[0]
    source_step = first_scope.steps[0]
    point = _visual_object("unrelated-point-name", geometry_ref="A")
    coordinate = VisualObject(
        visual_object_id="visual:coordinate:A",
        component="CoordinateLabel",
        role="coordinate:A",
        source_refs=({"kind": "source", "ref": "coordinate-fact"},),
        geometry_refs=("A",),
        state="focus",
        component_payload={"at": "A", "text": "完全不同的显示文本"},
        display_label="完全不同的显示文本",
    )
    revised_step = replace(
        source_step,
        frames=(replace(source_step.frames[0], objects=(point, coordinate)),),
    )
    revised_scope = replace(first_scope, steps=(revised_step,))
    revised_ir = replace(
        visual_ir,
        root_scope=replace(visual_ir.root_scope, children=(revised_scope,)),
    )

    compiled = forward_compile(revised_ir)
    additions = compiled.step_decorations["steps"]["shared"]["visualFrames"][0][
        "add"
    ]
    compiled_point = next(item for item in additions if item["type"] == "point")
    compiled_label = next(
        item for item in additions if item["type"] == "coordinateLabel"
    )

    assert compiled_point["at"] == compiled_label["at"] == "A"
    assert compiled_point["showLabel"] is False
    assert compiled_point["labelText"] == "unrelated-point-name"
    assert compiled_label["text"] == "完全不同的显示文本"


def test_reverse_compile_and_flat_scene_accumulator_are_retired() -> None:
    with pytest.raises(ValueError, match="visual_step_ir_v1_reverse_compile_retired"):
        reverse_compile({}, {}, {})

    import shuxueshuo_server.solver.visual as visual

    assert not hasattr(visual, "resolved_steps_with_carry_forward")
    assert not hasattr(visual, "LLMVisualStepOptimizer")
    assert not hasattr(visual, "BaseSceneBuilder")


def test_recursive_state_clones_goal_branches_without_backflow() -> None:
    lesson = _lesson()
    snapshot = ExplanationSnapshot(
        problem_id=lesson.problem_id,
        family_id="demo",
        problem_revision=lesson.problem_revision,
        problem_semantic_hash=HASH,
        canonical_plan_hash=HASH,
        verified_execution_hash=HASH,
        problem={"entities": [], "facts": []},
        root_scope=TeachingScope(scope_ref="problem"),
    )

    def resolve(step, state: BranchVisualState) -> VisualStepResolution:
        visual = _visual_step(step.lesson_step_id)
        produced = visual.frames[0].objects
        return VisualStepResolution(
            step=visual,
            published_objects=produced,
            visibility_reasons={item.visual_object_id: "test" for item in produced},
        )

    result = RecursiveVisualStateResolver(snapshot).resolve(lesson, resolve)
    authority = result.authority["steps"]

    assert authority["goal_a"]["available_before"] == ["visual:point:shared"]
    assert authority["goal_b"]["available_before"] == ["visual:point:shared"]
    assert "visual:point:goal_a" not in authority["goal_b"]["available_before"]
    assert "visual:point:goal_b" not in authority["goal_a"]["available_before"]
    assert authority["child"]["available_before"] == ["visual:point:shared"]


def test_recursive_state_exposes_direct_scope_and_previous_goal_frame_only() -> None:
    lesson = LessonIR(
        problem_id="visual-increment-demo",
        problem_revision="problem-revision:visual-increment-demo",
        source_snapshot_hash=HASH,
        root_scope=LessonScope(
            scope_ref="problem",
            children=(
                LessonScope(
                    scope_ref="i",
                    steps=(_lesson_step("shared"),),
                    goals=(
                        LessonGoal(
                            "i.a",
                            (
                                _lesson_step("goal_a_1"),
                                _lesson_step("goal_a_2"),
                            ),
                        ),
                        LessonGoal("i.b", (_lesson_step("goal_b_1"),)),
                    ),
                ),
            ),
        ),
    )
    snapshot = ExplanationSnapshot(
        problem_id=lesson.problem_id,
        family_id="demo",
        problem_revision=lesson.problem_revision,
        problem_semantic_hash=HASH,
        canonical_plan_hash=HASH,
        verified_execution_hash=HASH,
        problem={"entities": [], "facts": []},
        root_scope=TeachingScope(scope_ref="problem"),
    )
    seen: dict[str, tuple[list[str], str | None]] = {}

    def resolve(step, state: BranchVisualState) -> VisualStepResolution:
        seen[step.lesson_step_id] = (
            [item.visual_object_id for item in state.last_frame],
            state.last_container_ref,
        )
        visual = _visual_step(step.lesson_step_id)
        return VisualStepResolution(
            step=visual,
            published_objects=visual.frames[0].objects,
            visibility_reasons={
                item.visual_object_id: "test"
                for item in visual.frames[0].objects
            },
        )

    RecursiveVisualStateResolver(snapshot).resolve(lesson, resolve)

    assert seen["goal_a_1"] == (["visual:point:shared"], "scope:i")
    assert seen["goal_a_2"] == (["visual:point:goal_a_1"], "goal:i.a")
    assert seen["goal_b_1"] == (["visual:point:shared"], "scope:i")
