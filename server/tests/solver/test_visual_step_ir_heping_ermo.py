from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
import re
import subprocess
from typing import Any

import pytest
import sympy as sp

from _problem_planning_support import cached_planning_binding_fixture

from shuxueshuo_server.solver import load_expected_answers
from shuxueshuo_server.solver.explanation import (
    ExplanationSnapshotBuilder,
    LessonIR,
    RecursiveLessonIRAssembler,
)
from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.explanation.scope_lesson import LessonScopeContentValidator
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.visual import (
    VisualFrame,
    VisualObject,
    VisualStep,
    VisualStepBuilder,
    VisualStepIRValidator,
    forward_compile,
)
from shuxueshuo_server.solver.visual import builder as visual_builder
from shuxueshuo_server.solver.visual.viewport import SemanticViewportResolver


ROOT = Path(__file__).resolve().parents[3]
HEPING_ERMO_EXPECTED = "tests/solver/expected/tj-2026-heping-ermo-25.expected.json"
HEPING_ERMO_APPROVED_SCOPE_CONTENT = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
    "heping_ermo_b3/scope-content.json"
)


@dataclass(frozen=True)
class HepingErmoPage:
    snapshot: ExplanationSnapshot
    lesson: LessonIR
    visual_ir: Any
    compiled: Any


@pytest.fixture(scope="module")
def heping_ermo_page() -> HepingErmoPage:
    snapshot = _solve_heping_ermo_snapshot()
    lesson = _build_approved_heping_ermo_lesson(snapshot)
    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir, lesson=lesson)
    return HepingErmoPage(
        snapshot=snapshot,
        lesson=lesson,
        visual_ir=visual_ir,
        compiled=forward_compile(visual_ir),
    )


def test_b4v_heping_ermo_is_recursive_and_has_expected_frame_count(
    heping_ermo_page: HepingErmoPage,
) -> None:
    page = heping_ermo_page
    traversal = page.visual_ir.traversal

    assert page.visual_ir.schema_version == "visual-step-ir/v2"
    assert page.visual_ir.metadata["scene_model"] == "recursive_complete_frames"
    assert len(traversal.scope_by_ref) == 5
    assert len(traversal.goal_by_ref) == 4
    assert len(page.lesson.steps) == 12
    assert len(page.visual_ir.steps) == 12
    assert sum(len(step.frames) for step in page.visual_ir.steps) == 12
    assert page.snapshot.answers == load_expected_answers(HEPING_ERMO_EXPECTED)
    assert [step.lesson_step_id for step in page.visual_ir.steps] == [
        step.id for step in page.lesson.steps
    ]


def test_b4v_visual_generation_is_snapshot_round_trip_stable(
    heping_ermo_page: HepingErmoPage,
) -> None:
    """Serialized v3 is the complete visual authority, not an in-memory sidecar."""

    hydrated = explanation_snapshot_from_payload(
        heping_ermo_page.snapshot.to_payload()
    )
    rebuilt = VisualStepBuilder().build(
        snapshot=hydrated,
        lesson=heping_ermo_page.lesson,
    )

    assert rebuilt.to_payload() == heping_ermo_page.visual_ir.to_payload()


def test_b4v_merged_curve_and_intercept_materials_share_one_complete_frame(
    heping_ermo_page: HepingErmoPage,
) -> None:
    curve_frame = _frame_for_source(heping_ermo_page, "derive_parabola_i")
    intercept_frame = _frame_for_source(
        heping_ermo_page,
        "derive_x_intercept_A_i",
    )
    curve_refs = _geometry_refs(curve_frame)
    intercept_refs = _geometry_refs(intercept_frame)

    assert curve_frame.frame_id == intercept_frame.frame_id
    assert curve_refs == intercept_refs
    assert {"curve_i_parabola", "point_A_i", "point_B_i"} <= curve_refs
    assert not intercept_refs.intersection(
        {
            "M_axis_i",
            "K_axis_i_2",
            "point_P_problem",
            "E_axis_i_2",
            "G_axis_i_2",
        }
    )
    assert _states_for_ref(curve_frame, "curve_i_parabola") == {"focus"}
    assert _states_for_ref(intercept_frame, "point_A_i") == {"focus"}
    assert _states_for_ref(intercept_frame, "point_B_i") == {"context"}


def test_b4v_s2_uses_branch_correct_axis_foot_and_never_shows_k(
    heping_ermo_page: HepingErmoPage,
) -> None:
    frame = _frame_for_source(heping_ermo_page, "derive_vertex_P_i")
    refs = _geometry_refs(frame)
    geometry = heping_ermo_page.visual_ir.geometry_registry

    assert {
        "curve_i_parabola",
        "point_A_i",
        "point_B_i",
        "point_P_problem",
        "M_axis_i",
    } <= refs
    assert not refs.intersection({"M_axis_ii", "K_axis_i_2", "K_axis_ii", "E_axis_i_2"})
    assert geometry["fixedPoints"]["M_axis_i"] == ["-1", "0"]
    assert geometry["movingPoints"]["M_axis_ii"] == ["1/2-c/2", "0"]
    assert geometry["pointMeta"]["M_axis_i"]["scopeId"] == "i"
    assert geometry["pointMeta"]["M_axis_ii"]["scopeId"] == "ii"
    assert "A1" not in geometry["fixedPoints"]
    assert "A1" not in geometry["movingPoints"]


def test_b4v_quadratic_square_macro_selects_square_by_witness_roles(
    heping_ermo_page: HepingErmoPage,
) -> None:
    snapshot = heping_ermo_page.snapshot
    witness = next(
        item
        for item in snapshot.macro_evidence
        if item.get("macro_id") == "quadratic_square_path_minimum"
    )
    role_values = {
        str(item.get("role") or ""): str(item.get("chosen_ref") or "")
        for item in witness.get("role_resolutions") or ()
        if isinstance(item, dict)
    }
    expected = next(
        fact
        for fact in snapshot.problem["facts"]
        if fact.get("type") == "square"
    )
    problem = copy.deepcopy(snapshot.problem)
    problem["facts"].insert(
        0,
        {
            "type": "square",
            "handle": "fact:problem:decoy_square",
            "scope_id": "problem",
            "vertices": [
                "point:problem:A",
                "point:problem:B",
                "point:problem:C",
                "point:problem:P",
            ],
        },
    )

    selected = visual_builder._square_fact_for_witness_roles(
        replace(snapshot, problem=problem),
        role_values=role_values,
        scope_id="ii",
    )

    assert selected is not None
    assert selected["handle"] == expected["handle"]


def test_b4v_parameter_frames_use_local_time_correct_controls(
    heping_ermo_page: HepingErmoPage,
) -> None:
    s3 = _frame_for_source(heping_ermo_page, "parameterize_axis_point_E_i")
    s6 = _frame_for_source(heping_ermo_page, "derive_parametric_parabola_ii")
    s8 = _frame_for_source(heping_ermo_page, "solve_parameter_c_ii")
    s9 = _frame_for_source(heping_ermo_page, "evaluate_point_A_ii")

    t_contract = _parameter(s3, "t")
    assert t_contract["mathematical_domain"]["kind"] == "real"
    assert len(t_contract["controls"]) == 1
    assert "E_axis_i_2" in t_contract["parameterized_points"]

    c_symbolic = _parameter(s6, "c")
    assert c_symbolic["mathematical_domain"] == {
        "kind": "inequality",
        "expression": "c>1",
    }
    assert c_symbolic["controls"] == []
    assert c_symbolic["default_value"] != 5
    geometry = heping_ermo_page.visual_ir.geometry_registry
    assert geometry["movingPoints"]["point_A_ii"] == ["-c", "0"]
    assert geometry["movingPoints"]["point_G_ii"] == [
        "1/4-3*c/4",
        "-c/2-1/2",
    ]
    assert "point_A_ii" not in geometry["fixedPoints"]
    assert "point_G_ii" not in geometry["fixedPoints"]

    s6_visual = _visual_step_for_source(
        heping_ermo_page,
        "derive_parametric_parabola_ii",
    )
    s6_lesson = next(
        item
        for item in heping_ermo_page.compiled.lesson_data["steps"]
        if item["id"] == s6_visual.lesson_step_id
    )
    assert "localControls" not in s6_lesson

    for frame in (s8, s9):
        c_exact = _parameter(frame, "c")
        assert c_exact["mathematical_domain"] == {"kind": "exact", "value": "5"}
        assert c_exact["controls"] == []
        assert c_exact["default_value"] == 5.0


def test_b4v_context_distance_markers_hide_prior_relation_labels(
    heping_ermo_page: HepingErmoPage,
) -> None:
    frame = _frame_for_source(heping_ermo_page, "solve_parameter_c_ii")
    context_labels = {
        str(item.component_payload.get("label"))
        for item in frame.objects
        if item.component == "DistanceMarker"
        and item.state == "context"
        and item.component_payload.get("label")
    }
    visual_step = _visual_step_for_source(heping_ermo_page, "solve_parameter_c_ii")
    compiled_frame = heping_ermo_page.compiled.step_decorations["steps"][
        visual_step.lesson_step_id
    ]["visualFrames"][0]
    compiled_labels = {
        str(item.get("label"))
        for item in compiled_frame["add"]
        if item.get("label")
    }

    assert context_labels
    assert context_labels.isdisjoint(compiled_labels)


def test_b4v_imports_only_the_prior_verified_curve_vertex_across_siblings(
    heping_ermo_page: HepingErmoPage,
) -> None:
    s3 = _frame_for_source(heping_ermo_page, "parameterize_axis_point_E_i")
    s6 = _frame_for_source(heping_ermo_page, "derive_parametric_parabola_ii")
    refs_s3 = _geometry_refs(s3)
    refs_s6 = _geometry_refs(s6)

    assert "point_P_problem" in refs_s3
    vertex_context = next(
        item
        for item in s3.objects
        if item.role == "curve_vertex"
        and item.geometry_refs == ("point_P_problem",)
    )
    assert vertex_context.source_refs == (
        {"kind": "functional_step", "step_id": "derive_vertex_P_i"},
    )
    assert not any(ref.endswith("_ii") for ref in refs_s3)
    assert refs_s6 == {"curve_ii_parabola", "point_A_ii"}
    assert not refs_s6.intersection(
        {
            "curve_i_parabola",
            "point_A_i",
            "point_B_i",
            "point_P_problem",
            "E_axis_i_2",
            "G_axis_i_2",
            "K_axis_i_2",
            "M_axis_i",
        }
    )


def test_b4v_goal_increment_retains_scope_and_symbolic_square_scene(
    heping_ermo_page: HepingErmoPage,
) -> None:
    s4 = _frame_for_source(heping_ermo_page, "derive_square_vertex_G_i")
    s5 = _frame_for_source(heping_ermo_page, "solve_axis_point_candidates_i")
    refs_s4 = _geometry_refs(s4)
    refs_s5 = _geometry_refs(s5)

    assert {
        "point_A_i",
        "E_axis_i_2",
        "G_axis_i_2",
        "K_axis_i_2",
        "M_axis_i",
        "point_P_problem",
    } <= refs_s4
    assert "point_B_i" in refs_s4
    assert any(
        item.component == "Point"
        and item.geometry_refs == ("M_axis_i",)
        and item.state == "context"
        for item in s4.objects
    )
    assert any(
        item.component == "AxisOfSymmetry"
        and item.geometry_refs == ("curve_i_parabola",)
        and item.state == "context"
        for item in s4.objects
    )
    assert {
        "E_axis_i_2_candidate_1",
        "E_axis_i_2_candidate_2",
        "E_axis_i_2",
        "G_axis_i_2",
        "K_axis_i_2",
        "curve_i_parabola",
        "point_A_i",
        "point_B_i",
        "M_axis_i",
    } <= refs_s5
    s5_by_id = {item.visual_object_id: item for item in s5.objects}
    square_refs = {
        "point_A_i",
        "E_axis_i_2",
        "G_axis_i_2",
        "K_axis_i_2",
    }
    persistent_s4 = {
        item.visual_object_id
        for item in s4.objects
        if item.geometry_refs
        and set(item.geometry_refs) <= square_refs
        and item.component in {"Point", "ColoredLine", "OutlineRegion"}
    }
    assert persistent_s4 <= set(s5_by_id)
    assert all(
        s5_by_id[object_id].state == "context"
        for object_id in persistent_s4
    )
    assert _states_for_ref(s5, "E_axis_i_2_candidate_1") == {"focus"}
    assert _states_for_ref(s5, "E_axis_i_2_candidate_2") == {"focus"}


def test_b4v_candidate_outputs_drive_reachable_landmarks_and_focus_viewport(
    heping_ermo_page: HepingErmoPage,
) -> None:
    frame = _frame_for_source(heping_ermo_page, "solve_axis_point_candidates_i")
    parameter = _parameter(frame, "t")
    landmarks = parameter["landmarks"]
    expected = sorted([float(2 - sp.sqrt(6)), float(2 + sp.sqrt(6))])

    assert sorted(item["value"] for item in landmarks) == pytest.approx(expected)
    assert parameter["display_window"]["min"] < expected[0]
    assert parameter["display_window"]["max"] > expected[1]
    assert {item["display"] for item in landmarks} == {"2-√6", "2+√6"}
    assert all(
        {"E_axis_i_2", "G_axis_i_2", "K_axis_i_2"}
        <= set(item["highlight_geometry_refs"])
        for item in landmarks
    )
    _assert_visible_points_inside_viewport(frame, heping_ermo_page.visual_ir.geometry_registry)

    visual_step = _visual_step_for_source(
        heping_ermo_page,
        "solve_axis_point_candidates_i",
    )
    compiled_frame = heping_ermo_page.compiled.step_decorations["steps"][
        visual_step.lesson_step_id
    ]["visualFrames"][0]
    assert len(compiled_frame["parameterLandmarks"]) == 2
    lesson_step = next(
        item
        for item in heping_ermo_page.compiled.lesson_data["steps"]
        if item["id"] == visual_step.lesson_step_id
    )
    assert len(lesson_step["localControls"]["controls"][0]["landmarks"]) == 2


def test_semantic_viewport_ignores_unbounded_geometry_extent() -> None:
    source = ({"kind": "functional_step", "step_id": "s"},)
    focus = VisualObject(
        visual_object_id="focus",
        component="Segment",
        role="focus:segment",
        source_refs=source,
        geometry_refs=("P", "Q"),
        state="focus",
        component_payload={"from": "P", "to": "Q"},
    )
    curve = VisualObject(
        visual_object_id="curve",
        component="Parabola",
        role="curve",
        source_refs=source,
        geometry_refs=("curve",),
        state="context",
        component_payload={"curveId": "curve"},
    )
    locus = VisualObject(
        visual_object_id="locus",
        component="LocusLine",
        role="locus:line",
        source_refs=source,
        geometry_refs=("L1", "L2"),
        state="context",
        component_payload={"from": "L1", "to": "L2"},
    )
    geometry = {
        "fixedPoints": {
            "P": [0, 0],
            "Q": [2, 1],
            "L1": [-1000, -1000],
            "L2": [1000, 1000],
        },
        "movingPoints": {},
        "curves": [{"id": "curve", "a": 1000, "b": 0, "c": 1000}],
    }
    resolver = SemanticViewportResolver()
    baseline = resolver.resolve(
        objects=(focus,),
        geometry_spec=geometry,
        local_parameters=(),
        parameter_values={},
    )
    assert resolver.resolve(
        objects=(focus, curve, locus),
        geometry_spec=geometry,
        local_parameters=(),
        parameter_values={},
    ) == baseline


def test_b4v_macro_units_are_two_lesson_steps_with_one_complete_frame_each(
    heping_ermo_page: HepingErmoPage,
) -> None:
    steps = _visual_steps_for_source(
        heping_ermo_page,
        "derive_path_minimum_ii",
    )
    assert len(steps) == 2
    assert [len(step.frames) for step in steps] == [1, 1]
    reduction, reflection = (step.frames[0] for step in steps)

    assert reduction.caption == "化简路径"
    assert reflection.caption == "轨迹与反射"
    assert reduction.teaching_unit_keys == (
        "quadratic_square_path_minimum/path_reduction",
    )
    assert reflection.teaching_unit_keys == (
        "quadratic_square_path_minimum/reflection_minimum",
    )
    reduction_refs = _geometry_refs(reduction)
    reflection_refs = _geometry_refs(reflection)
    assert {
        "point_A_ii",
        "E_axis_ii",
        "K_axis_ii",
        "point_G_ii",
        "point_F_ii",
        "point_H_ii",
        "M_axis_ii",
    } <= reduction_refs
    assert {
        "G_locus_ii_start",
        "G_locus_ii_end",
        "point_A_prime_ii",
        "point_G_ii",
        "M_axis_ii",
    } <= reflection_refs
    assert not reflection_refs.intersection(
        {"E_axis_ii", "K_axis_ii", "point_F_ii", "point_H_ii"}
    )
    assert any(
        item.component == "Point" and item.geometry_refs == ("M_axis_ii",)
        for item in reduction.objects
    )
    assert any(
        item.component == "AxisOfSymmetry"
        and item.geometry_refs == ("curve_ii_parabola",)
        for item in reduction.objects
    )
    assert any(
        item.component == "Point" and item.geometry_refs == ("M_axis_ii",)
        for item in reflection.objects
    )
    assert any(
        item.component == "AxisOfSymmetry"
        and item.geometry_refs == ("curve_ii_parabola",)
        for item in reflection.objects
    )
    assert "constraint_carriers" not in json.dumps(
        heping_ermo_page.visual_ir.to_payload(),
        ensure_ascii=False,
    )
    assert _parameter(reduction, "c")["default_value"] == _parameter(
        reflection, "c"
    )["default_value"]

    reduction_motion = next(
        item for item in reduction.local_parameters if item.get("controls")
    )
    reflection_motion = next(
        item for item in reflection.local_parameters if item.get("controls")
    )
    assert reduction_motion["name"] == reflection_motion["name"] == "u"
    assert reduction_motion["mathematical_domain"] == {"kind": "real"}
    assert reflection_motion["mathematical_domain"] == {"kind": "real"}
    assert "动点 G" in reduction_motion["controls"][0]["label"]
    assert {
        "E_axis_ii",
        "K_axis_ii",
        "point_G_ii",
        "point_F_ii",
        "point_H_ii",
    } <= set(reduction_motion["parameterized_points"])
    assert "point_G_ii" in reflection_motion["parameterized_points"]

    expressions = reduction_motion["parameterized_points"]
    geometry = heping_ermo_page.visual_ir.geometry_registry
    a_pair = tuple(sp.sympify(item) for item in geometry["movingPoints"]["point_A_ii"])
    e_pair = tuple(
        sp.sympify(item)
        for item in expressions["E_axis_ii"]["expression"]
    )
    g_pair = tuple(
        sp.sympify(item)
        for item in expressions["point_G_ii"]["expression"]
    )
    ae = tuple(sp.simplify(e - a) for a, e in zip(a_pair, e_pair, strict=True))
    ag = tuple(sp.simplify(g - a) for a, g in zip(a_pair, g_pair, strict=True))
    assert sp.simplify(ae[0] * ag[0] + ae[1] * ag[1]) == 0
    assert sp.simplify(ae[0] ** 2 + ae[1] ** 2 - ag[0] ** 2 - ag[1] ** 2) == 0

    compiled_by_id = {
        item["id"]: item for item in heping_ermo_page.compiled.lesson_data["steps"]
    }
    for visual_step in steps:
        controls = compiled_by_id[visual_step.lesson_step_id]["localControls"]
        assert controls["controls"][0]["var"] == "u"


def test_b4v_exact_result_frames_focus_updates_and_retain_goal_context(
    heping_ermo_page: HepingErmoPage,
) -> None:
    s9 = _frame_for_source(heping_ermo_page, "evaluate_point_A_ii")
    s10 = _frame_for_source(heping_ermo_page, "evaluate_minimum_point_G_ii")
    s11 = _frame_for_source(heping_ermo_page, "recover_target_point_E_ii")

    reflection_refs = {
        "curve_ii_parabola",
        "G_locus_ii_start",
        "G_locus_ii_end",
        "M_axis_ii",
        "point_A_ii",
        "point_A_prime_ii",
        "point_G_ii",
    }
    assert reflection_refs <= _geometry_refs(s9)
    assert reflection_refs <= _geometry_refs(s10)
    assert reflection_refs <= _geometry_refs(s11)
    assert any(
        item.component == "Point"
        and item.geometry_refs == ("point_A_ii",)
        and item.state == "focus"
        for item in s9.objects
    )
    assert _states_for_ref(s9, "point_G_ii") == {"context"}
    assert any(
        item.component == "Point"
        and item.geometry_refs == ("point_G_ii",)
        and item.state == "focus"
        for item in s10.objects
    )
    assert {"point_E_ii", "K_axis_ii"} <= _geometry_refs(s11)
    assert any(
        item.component == "Point"
        and item.geometry_refs == ("point_E_ii",)
        and item.state == "focus"
        for item in s11.objects
    )


def test_b4v_frames_have_unique_lines_public_labels_and_visible_points(
    heping_ermo_page: HepingErmoPage,
) -> None:
    geometry = heping_ermo_page.visual_ir.geometry_registry
    for step in heping_ermo_page.visual_ir.steps:
        for frame in step.frames:
            line_keys: list[tuple[str, str, str]] = []
            for item in frame.objects:
                payload = item.component_payload
                if item.component in {"ColoredLine", "DashedLine", "Segment"}:
                    endpoints = sorted((str(payload.get("from")), str(payload.get("to"))))
                    line_keys.append((endpoints[0], endpoints[1], str(payload.get("label") or "")))
                for key in ("labelText", "text", "label"):
                    value = payload.get(key)
                    if isinstance(value, str):
                        assert not re.search(r"(?:point_|_axis_|_problem|_i_2|_ii)", value)
            assert len(line_keys) == len(set(line_keys)), frame.frame_id
            _assert_visible_points_inside_viewport(frame, geometry)


def test_b4v_compiler_emits_only_complete_visual_frames(
    heping_ermo_page: HepingErmoPage,
    tmp_path: Path,
) -> None:
    page = heping_ermo_page
    decorations = page.compiled.step_decorations
    assert "layers" not in decorations
    assert set(decorations) == {"steps"}
    for lesson_step_id, step in decorations["steps"].items():
        assert set(step) == {"visualMode", "visualFrames"}
        assert step["visualFrames"]
        for frame in step["visualFrames"]:
            assert frame["add"][0] == {"type": "grid"}
            assert "inherits_from" not in frame
            assert "hideLayers" not in frame
        source = next(item for item in page.visual_ir.steps if item.lesson_step_id == lesson_step_id)
        assert len(step["visualFrames"]) == len(source.frames)

    lesson_data = copy.deepcopy(page.compiled.lesson_data)
    html_path = tmp_path / "heping-ermo-b4v.html"
    lesson_data["meta"]["outputPath"] = str(html_path)
    _write_compiled_artifacts(
        tmp_path,
        geometry_spec=page.compiled.geometry_spec,
        step_decorations=decorations,
        lesson_data=lesson_data,
    )
    subprocess.run(
        ["node", str(ROOT / "tools/validate-geometry-spec.mjs"), str(tmp_path)],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["node", str(ROOT / "tools/build-lesson-page.mjs"), str(tmp_path)],
        cwd=ROOT,
        check=True,
    )
    html = html_path.read_text(encoding="utf-8")
    assert "化简路径" in html
    assert "轨迹与反射" in html
    assert "visualFrames" in html
    assert '<figcaption class="lesson-visual-frame-caption">' not in html


def test_b4v_compiler_visually_distinguishes_focus_and_context(
    heping_ermo_page: HepingErmoPage,
) -> None:
    page = heping_ermo_page
    source_step = _visual_step_for_source(page, "derive_x_intercept_A_i")
    compiled_frame = page.compiled.step_decorations["steps"][
        source_step.lesson_step_id
    ]["visualFrames"][0]

    point_a = next(
        item
        for item in compiled_frame["add"]
        if item.get("type") == "point" and item.get("at") == "point_A_i"
    )
    point_b = next(
        item
        for item in compiled_frame["add"]
        if item.get("type") == "point" and item.get("at") == "point_B_i"
    )

    assert "opacity" not in point_a
    assert point_a["showLabel"] is False
    assert point_b["color"] == "#64748b"
    assert point_b["opacity"] == pytest.approx(0.58)
    assert point_b["showLabel"] is False


def _visual_step_for_source(page: HepingErmoPage, source_step_id: str) -> VisualStep:
    rows = _visual_steps_for_source(page, source_step_id)
    assert len(rows) == 1
    return rows[0]


def _visual_steps_for_source(
    page: HepingErmoPage,
    source_step_id: str,
) -> list[VisualStep]:
    lesson_step_ids = [
        step.id
        for step in page.lesson.steps
        if source_step_id in step.source_step_ids
    ]
    return [
        step
        for lesson_step_id in lesson_step_ids
        for step in page.visual_ir.steps
        if step.lesson_step_id == lesson_step_id
    ]


def _frame_for_source(page: HepingErmoPage, source_step_id: str) -> VisualFrame:
    step = _visual_step_for_source(page, source_step_id)
    assert len(step.frames) == 1
    return step.frames[0]


def _geometry_refs(frame: VisualFrame) -> set[str]:
    return {
        geometry_ref
        for item in frame.objects
        for geometry_ref in item.geometry_refs
    }


def _states_for_ref(frame: VisualFrame, geometry_ref: str) -> set[str]:
    return {
        item.state
        for item in frame.objects
        if geometry_ref in item.geometry_refs
    }


def _parameter(frame: VisualFrame, name: str) -> dict[str, Any]:
    return next(item for item in frame.local_parameters if item.get("name") == name)


def _assert_visible_points_inside_viewport(
    frame: VisualFrame,
    geometry: dict[str, Any],
) -> None:
    base_environment = {
        str(item["name"]): float(item["default_value"])
        for item in frame.local_parameters
    }
    environments = [base_environment]
    for parameter in frame.local_parameters:
        if not parameter.get("controls"):
            continue
        name = str(parameter["name"])
        window = parameter["display_window"]
        environments.extend(
            {
                **base_environment,
                name: float(value),
            }
            for value in (window["min"], window["max"])
        )
    viewport = frame.viewport
    eligible_refs = SemanticViewportResolver().attention_geometry_refs(
        objects=frame.objects,
        geometry_spec=geometry,
        local_parameters=frame.local_parameters,
    )
    for geometry_ref in eligible_refs:
        pair = (geometry.get("fixedPoints") or {}).get(geometry_ref)
        if pair is None:
            pair = (geometry.get("movingPoints") or {}).get(geometry_ref)
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        for environment in environments:
            try:
                substitutions = {
                    sp.Symbol(name): value for name, value in environment.items()
                }
                x = float(sp.N(sp.sympify(str(pair[0])).subs(substitutions)))
                y = float(sp.N(sp.sympify(str(pair[1])).subs(substitutions)))
            except Exception:
                continue
            assert viewport["minX"] <= x <= viewport["maxX"], (
                frame.frame_id,
                geometry_ref,
                environment,
                x,
            )
            assert viewport["minY"] <= y <= viewport["maxY"], (
                frame.frame_id,
                geometry_ref,
                environment,
                y,
            )


@cache
def _solve_heping_ermo_snapshot() -> ExplanationSnapshot:
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture("tj-2026-heping-ermo-25")
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    assert result.answers == load_expected_answers(HEPING_ERMO_EXPECTED)
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def _build_approved_heping_ermo_lesson(snapshot: ExplanationSnapshot) -> LessonIR:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validation = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    ).validate_payload(
        json.loads(HEPING_ERMO_APPROVED_SCOPE_CONTENT.read_text(encoding="utf-8"))
    )
    assert validation.direct_acceptance, validation.to_payload()
    assert not validation.independent_material_merge_repaired
    return RecursiveLessonIRAssembler().assemble(
        snapshot,
        projection,
        validation,
    ).lesson


def _write_compiled_artifacts(
    path: Path,
    *,
    geometry_spec: dict[str, Any],
    step_decorations: dict[str, Any],
    lesson_data: dict[str, Any],
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("geometry-spec.json", geometry_spec),
        ("step-decorations.json", step_decorations),
        ("lesson-data.json", lesson_data),
    ):
        (path / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
