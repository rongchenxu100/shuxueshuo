from __future__ import annotations

import copy
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
from typing import Any

import pytest
import sympy as sp

from shuxueshuo_server.solver import load_problem_ir
from shuxueshuo_server.solver.explanation import (
    ExplanationBuilder,
    ExplanationSnapshotBuilder,
    LLMLessonPlanner,
    LessonIRValidator,
    lesson_ir_from_payload,
    write_explanation_debug_artifacts,
)
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot, LessonIR, LessonSection, LessonStep
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.visual import (
    AnimationTimelineBuilder,
    LLMVisualStepOptimizer,
    BaseSceneBuilder,
    GeometrySpecBuilder,
    ParametricExpressionResolver,
    VisualStepBuilder,
    VisualStepIRValidator,
    forward_compile,
)
from shuxueshuo_server.solver.visual import animation as visual_animation
from shuxueshuo_server.solver.visual import builder as visual_builder
from shuxueshuo_server.solver.visual import llm as visual_llm
from shuxueshuo_server.solver.visual import parametric as visual_parametric
from shuxueshuo_server.solver.visual import role_binders as visual_role_binders
from shuxueshuo_server.solver.visual.geometry_naming import GeometryPointScopeNamer, scope_root
from shuxueshuo_server.solver.visual.models import visual_step_ir_from_payload
from shuxueshuo_server.solver.visual.role_binders import VisualGeometryIndex, VisualRoleBindings
from shuxueshuo_server.solver.visual.sympy_helpers import sympy_pair
from shuxueshuo_server.solver.visual.validator import VisualStepIRValidationError


ROOT = Path(__file__).resolve().parents[3]
HEPING_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-yimo-25.json"
HEPING_RECORDED_LESSON_IR = ROOT / "internal/solver-fixtures/tj-2026-heping-yimo-25.lesson-ir.json"
DEBUG_DIR = ROOT / "internal/solver-runs/visual-builder-deepseek-heping"
RECORDED_LESSON_DEBUG_DIR = ROOT / "internal/solver-runs/visual-builder-deepseek-heping-recorded-lesson"
RUN_DEEPSEEK_HEPING_VISUAL = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_VISUAL_BUILDER") == "1"
    and os.getenv("RUN_DEEPSEEK_HEPING_VISUAL") == "1"
)


def test_visual_sympy_pair_uses_shared_axis_parameter_and_power_normalization() -> None:
    pair = sympy_pair(
        ["_axis_param_i^2 + abs(x)", "y*y + sqrt(4)"],
        axis_parameter_alias="u",
    )
    assert pair is not None
    assert sp.simplify(pair[0] - (sp.Symbol("u") ** 2 + sp.Abs(sp.Symbol("x")))) == 0
    assert sp.simplify(pair[1] - (sp.Symbol("y") ** 2 + 2)) == 0

    raw_pair = sympy_pair(["_axis_param_i + 1", "0"])
    assert raw_pair is not None
    assert sp.Symbol("_axis_param_i") in raw_pair[0].free_symbols

    assert "sp.sympify" not in inspect.getsource(visual_builder._sympy_pair_value)
    assert "sp.sympify" not in inspect.getsource(visual_role_binders._sympy_pair)
    assert "sp.sympify" not in inspect.getsource(visual_parametric._sympy_pair)


def test_method_and_recipe_visual_template_dispatch_uses_component_registry() -> None:
    method_registry = MethodSpecRegistry.load_from_code()
    method_components = {
        str(template.get("component") or "")
        for spec in method_registry.specs.values()
        if spec.visual is not None
        for template in spec.visual.scene_templates
    }
    recipe_registry = RecipeSpecRegistry.load_from_code()
    recipe_components = {
        str(template.get("component") or "")
        for spec in recipe_registry.specs.values()
        if spec.visual is not None
        for templates in spec.visual.teaching_substep_templates.values()
        for template in templates
    }

    assert method_components <= set(visual_builder._METHOD_VISUAL_TEMPLATE_RENDERERS)
    assert recipe_components <= set(visual_builder._RECIPE_VISUAL_TEMPLATE_RENDERERS)
    assert "CurvePointCandidateMarker" in visual_builder._METHOD_VISUAL_TEMPLATE_RENDERERS
    assert "BrokenPathStraighteningMarker" in visual_builder._RECIPE_VISUAL_TEMPLATE_RENDERERS
    assert "elif" not in inspect.getsource(visual_builder._method_visual_template_items)
    assert "elif" not in inspect.getsource(visual_builder._recipe_visual_template_items)


def test_visual_rgba_literals_are_palette_backed() -> None:
    assert "rgba(" not in inspect.getsource(visual_builder)
    assert "rgba(" not in inspect.getsource(visual_animation)


def test_scope_root_keeps_later_roman_questions_distinct() -> None:
    assert scope_root("i") == "i"
    assert scope_root("i_2") == "i"
    assert scope_root("ii") == "ii"
    assert scope_root("ii_3") == "ii"
    assert scope_root("iii") == "iii"
    assert scope_root("iii_1") == "iii"
    assert scope_root("iv") == "iv"


def test_parametric_control_label_without_roles_does_not_default_to_named_points() -> None:
    assert (
        visual_parametric._control_label(
            {},
            moving_role="moving",
            anchor_role="anchor",
            endpoint_role="endpoint",
        )
        == "动点参数"
    )


def test_visual_step_builder_generates_from_lesson_ir_directly() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()

    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)

    assert len(visual_ir.steps) == len(lesson.steps)
    assert visual_ir.metadata["base_source"] == "generated"
    for step in visual_ir.steps:
        assert step.scene["add"], step.lesson_step_id
        assert not any(item.get("component") == "VisualGap" for item in step.scene["add"])
    VisualStepIRValidator().validate(visual_ir)


def test_geometry_spec_builder_extracts_points_curves_and_domain() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()

    geometry = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)

    assert geometry["fixedPoints"]["A"] == ["-1", "0"]
    assert geometry["fixedPoints"]["C"] == ["0", "-3"]
    assert geometry["fixedPoints"]["D"] == ["2", "-3"]
    assert geometry["fixedPoints"]["B1"] == ["3", "0"]
    assert geometry["movingPoints"]["B"] == ["3/a", "0"]
    assert geometry["movingPoints"]["G"] == ["3*sqrt((a*a)+1)/abs(a)", "-3"]
    assert geometry["pointMeta"]["B1"] == {
        "label": "B",
        "scopeId": "i_2",
        "scopeRoot": "i",
    }
    assert geometry["pointMeta"]["B"] == {
        "label": "B",
        "scopeId": "ii",
        "scopeRoot": "ii",
    }

    curves_by_root = {curve["scopeRoot"]: curve for curve in geometry["curves"]}
    assert curves_by_root["i"]["sourceHandle"] == "runtime:i:outputs:parabola"
    assert {
        key: curves_by_root["i"][key]
        for key in ("a", "b", "c")
    } == {"a": "1", "b": "-2", "c": "-3"}
    assert curves_by_root["ii"]["sourceHandle"] == "runtime:ii:outputs:parametric_parabola"
    assert {
        key: curves_by_root["ii"][key]
        for key in ("a", "b", "c")
    } == {"a": "a", "b": "a-3", "c": "-3"}

    domain = geometry["domain"]
    assert domain["minX"] < -1
    assert domain["maxX"] > 3
    assert domain["minY"] < -3
    assert domain["maxY"] > 0


def test_geometry_builder_names_equal_length_auxiliary_from_path_equation() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    payload = lesson.to_payload()
    for step in payload["steps"]:
        if "equal_length_ray_path_reduction" not in step.get("capability_ids", ()):
            continue
        if "path_reduction" in step.get("teaching_substep_ids", ()):
            step["title"] = "构造全等三角形，把两动点问题转化为单动点"
            step["derive"] = [["∴", "OM+BN=OM+MG"]]
            step["box"] = ["OM+BN=OM+MG"]
        if "minimum_by_segment" in step.get("teaching_substep_ids", ()):
            step["title"] = "将军饮马得到最小值表达式"
            step["derive"] = [["∴", "路径最小值 = 3√(2a²+1)/|a|"]]
            step["box"] = ["路径最小值 = 3√(2a²+1)/|a|"]
    lesson_without_auxiliary_name = lesson_ir_from_payload(payload)

    visual_ir = VisualStepBuilder().build(
        snapshot=snapshot,
        lesson=lesson_without_auxiliary_name,
    )
    compiled = forward_compile(visual_ir)

    assert compiled.geometry_spec["movingPoints"]["G"] == ["3*sqrt((a*a)+1)/abs(a)", "-3"]
    path_step = _visual_step_for_substep(
        visual_ir,
        lesson_without_auxiliary_name,
        "path_reduction",
    )
    assert path_step.interactions
    assert compiled.step_decorations["steps"][path_step.lesson_step_id]["pointOverrides"]


def test_vs1_distance_step_generates_static_visual_components() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    minimum_step = _visual_step_for_substep(visual_ir, lesson, "minimum_by_segment")

    components = [item["component"] for item in minimum_step.scene["add"]]

    assert "Point" in components
    assert "ColoredLine" in components
    assert "DistanceMarker" in components
    assert "OutlineRegion" in components
    assert any(item.get("label") == "OG" for item in minimum_step.scene["add"])


def test_vs1_recipe_substep_uses_only_path_reduction_visual_templates() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")

    serialized = json.dumps(path_step.scene["add"], ensure_ascii=False)
    components = [item["component"] for item in path_step.scene["add"]]

    assert "VisualGap" not in components
    assert "Point" in components
    assert "ColoredLine" in components
    assert '"at": "G"' in serialized
    assert '"at": "M"' in serialized
    assert '"at": "N"' in serialized
    assert "BN=MG" in serialized
    assert "OG" not in serialized

    compiled = forward_compile(visual_ir)
    raw_add = compiled.step_decorations["steps"][path_step.lesson_step_id]["add"]
    assert compiled.step_decorations["steps"][path_step.lesson_step_id]["pointOverrides"]
    assert any(
        item.get("type") == "point" and item.get("at") == "G" and item.get("labelText") == "G"
        for item in raw_add
    )
    assert any(item.get("type") == "coloredLine" and item.get("from") == "C" and item.get("to") == "G" for item in raw_add)
    assert any(item.get("at") == "M" for item in raw_add)
    assert any(item.get("at") == "N" for item in raw_add)
    assert any(item.get("type") == "segment" and item.get("label") in {"BN", "MG"} for item in raw_add)


def test_vs2_equal_length_recipe_generates_local_controls_and_point_overrides() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")
    minimum_step = _visual_step_for_substep(visual_ir, lesson, "minimum_by_segment")

    assert path_step.interactions
    assert path_step.interactions[0]["component"] == "LinkedControls"
    assert minimum_step.interactions
    assert minimum_step.interactions[0]["component"] == "LocalSlider"
    assert path_step.interactions[0]["domain"]["default"] == pytest.approx(5 / 9, abs=1e-6)

    compiled = forward_compile(visual_ir)
    path_deco = compiled.step_decorations["steps"][path_step.lesson_step_id]
    min_deco = compiled.step_decorations["steps"][minimum_step.lesson_step_id]
    path_lesson = next(step for step in compiled.lesson_data["steps"] if step["id"] == path_step.lesson_step_id)
    min_lesson = next(step for step in compiled.lesson_data["steps"] if step["id"] == minimum_step.lesson_step_id)

    assert set(path_deco["pointOverrides"]) == {"M", "N"}
    assert set(min_deco["pointOverrides"]) == {"M", "N"}
    assert path_deco["pointOverrides"]["M"] == ["3*u/a", "3*u-3"]
    assert path_deco["pointOverrides"]["N"] == ["3*u*sqrt((a*a)+1)/abs(a)", "-3"]
    assert len(path_lesson["localControls"]["controls"]) == 2
    assert len(min_lesson["localControls"]["controls"]) == 1
    assert path_lesson["localControls"]["values"]["u"] == pytest.approx(5 / 9, abs=1e-6)
    assert "M" not in compiled.geometry_spec["movingPoints"]
    assert "N" not in compiled.geometry_spec["movingPoints"]


def test_vs2_equal_length_point_overrides_preserve_equal_length_constraint() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")
    compiled = forward_compile(visual_ir)
    overrides = compiled.step_decorations["steps"][path_step.lesson_step_id]["pointOverrides"]

    def evaluate(pair: list[str], *, a_value: float, u_value: float) -> tuple[float, float]:
        locals_ = {"sqrt": sp.sqrt, "abs": sp.Abs}
        env = {sp.Symbol("a"): a_value, sp.Symbol("u"): u_value}
        x = sp.sympify(pair[0], locals=locals_).subs(env)
        y = sp.sympify(pair[1], locals=locals_).subs(env)
        return (float(sp.N(x)), float(sp.N(y)))

    for u_value in (0.2, 5 / 9, 0.8):
        m = evaluate(overrides["M"], a_value=0.75, u_value=u_value)
        n = evaluate(overrides["N"], a_value=0.75, u_value=u_value)
        cm = ((m[0] - 0) ** 2 + (m[1] + 3) ** 2) ** 0.5
        cn = ((n[0] - 0) ** 2 + (n[1] + 3) ** 2) ** 0.5
        assert cn == pytest.approx(cm)


def test_vs2_parametric_expression_resolver_falls_back_to_midpoint_default() -> None:
    resolver = ParametricExpressionResolver(
        geometry_spec={
            "movingParam": "a",
            "fixedPoints": {
                "A": ["0", "0"],
                "B": ["2", "0"],
                "G": ["2", "2"],
            },
            "movingPoints": {},
        }
    )
    marker = {
        "roles": {
            "anchor": "A",
            "segment_reference_point": "B",
            "segment_moving_point": "M",
            "ray_moving_point": "N",
            "auxiliary_point": "G",
        },
        "role_point_refs": {"A": "A", "B": "B", "G": "G", "M": "M", "N": "N"},
    }
    lesson_step = LessonStep(
        id="demo",
        scope_id="ii",
        source_step_ids=("s",),
        capability_ids=("equal_length_ray_path_reduction",),
        trace_refs=(),
        title="demo",
        goal="demo",
        nav_title=None,
        derive=(),
        box=(),
        teaching_substep_ids=("path_reduction",),
    )

    interaction = resolver.interactions_for_step(
        lesson_step,
        bindings=VisualRoleBindings(equal_length_path_markers=(marker,)),
    )[0]

    assert interaction["parameterized_points"]["M"]["expression"] == ["2*u", "0"]
    assert interaction["parameterized_points"]["N"]["expression"] == ["2*u", "2*u"]
    assert interaction["domain"]["default"] == 0.5


def test_vs2_page_expr_expands_integer_powers_beyond_quadratic() -> None:
    assert visual_parametric._page_expr("a**2 + b**3") == "(a*a)+(b*b*b)"
    assert visual_parametric._page_expr("(a + 1)**3") == "((a+1)*(a+1)*(a+1))"
    assert visual_builder._page_expr("x**4") == "(x*x*x*x)"


def test_vs3_animation_timeline_builder_generates_supported_timelines() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    d_step = _visual_step_for_capability(visual_ir, lesson, "translated_point")
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")
    minimum_step = _visual_step_for_substep(visual_ir, lesson, "minimum_by_segment")

    assert d_step.timeline["mode"] == "manual_then_interactive"
    assert len(d_step.timeline["beats"]) == 3
    assert "frames" not in d_step.timeline
    assert any(
        item.get("component") == "TranslationMarker"
        for beat in d_step.timeline["beats"]
        for item in beat["scene_patch"]["add"]
    )
    assert any(
        item.get("component") == "MovingPoint"
        for beat in d_step.timeline["beats"]
        for item in beat["scene_patch"]["add"]
    )
    assert d_step.timeline["beats"][0]["caption"] == "C(0,-3)"
    assert d_step.timeline["beats"][1]["caption"] == "C → D"
    assert d_step.timeline["beats"][2]["caption"] == "D(2,-3)"
    assert "源点" not in json.dumps(d_step.timeline, ensure_ascii=False)
    assert all(beat.get("transition") for beat in d_step.timeline["beats"])

    assert path_step.timeline["mode"] == "manual_then_interactive"
    assert path_step.timeline["trigger"]["label"] == "播放演示"
    assert len(path_step.timeline["beats"]) >= 6
    assert path_step.timeline["beats"][0]["scene_patch"].get("replace_add") is True
    assert not any(
        item.get("component") == "Point" and item.get("at") == "G"
        for item in path_step.timeline["beats"][0]["scene_patch"]["add"]
    )
    assert any(
        item.get("component") == "Point" and item.get("at") == "G"
        for beat in path_step.timeline["beats"]
        for item in beat["scene_patch"]["add"]
    )
    assert any(
        item.get("component") == "DistanceMarker" and item.get("label") in {"CB", "CG"}
        for beat in path_step.timeline["beats"]
        for item in beat["scene_patch"]["add"]
    )
    assert any(
        item.get("component") == "CongruentTriangleMarker"
        for beat in path_step.timeline["beats"]
        for item in beat["scene_patch"]["add"]
    )
    assert any(
        item.get("component") == "EquivalentSegmentMarker"
        for beat in path_step.timeline["beats"]
        for item in beat["scene_patch"]["add"]
    )
    path_timeline_text = json.dumps(path_step.timeline, ensure_ascii=False)
    assert "沿CD所在方向作辅助线" in path_timeline_text
    assert "沿CG所在方向作辅助线" not in path_timeline_text
    assert "取点G，使CG=CB" in path_timeline_text
    assert "辅助点G确定" not in path_timeline_text
    assert "共线" not in path_timeline_text
    assert any(
        beat.get("transition", {}).get("local_vars", {}).get("u")
        for beat in path_step.timeline["beats"]
    )
    replacement_index = next(
        index
        for index, beat in enumerate(path_step.timeline["beats"])
        if str(beat.get("id") or "").endswith("path-replacement-reveal")
    )
    assert any(
        beat.get("transition", {}).get("type") == "tween"
        and beat.get("transition", {}).get("local_vars", {}).get("u")
        for beat in path_step.timeline["beats"][replacement_index + 1 :]
    )
    path_sweep = next(
        beat
        for beat in path_step.timeline["beats"][replacement_index + 1 :]
        if beat.get("transition", {}).get("type") == "tween"
        and beat.get("transition", {}).get("local_vars", {}).get("u")
    )
    path_keyframes = path_sweep["transition"]["local_vars"]["u"]["keyframes"]
    assert [frame["value"] for frame in path_keyframes] == pytest.approx(
        [5 / 9, 0.8756, 0.25, 5 / 9],
        abs=1e-4,
    )

    assert minimum_step.timeline["mode"] == "manual_then_interactive"
    assert not minimum_step.timeline["beats"][0]["scene_patch"].get("replace_add")
    assert any(
        item.get("component") == "DistanceMarker" and item.get("label") == "OG"
        for beat in minimum_step.timeline["beats"]
        for item in beat["scene_patch"]["add"]
    )
    minimum_sweep = next(
        beat for beat in minimum_step.timeline["beats"]
        if str(beat.get("id") or "").endswith("path-minimum-sweep")
    )
    minimum_keyframes = minimum_sweep["transition"]["local_vars"]["u"]["keyframes"]
    minimum_values = [frame["value"] for frame in minimum_keyframes]
    assert minimum_values == pytest.approx([5 / 9, 0.8756, 0.25, 5 / 9], abs=1e-4)
    assert minimum_values[0] == pytest.approx(minimum_values[-1])
    assert max(minimum_values) > minimum_values[0] > min(minimum_values)


def test_vs3_animation_timeline_builder_returns_none_when_roles_missing() -> None:
    lesson_step = LessonStep(
        id="demo",
        scope_id="ii",
        source_step_ids=("s",),
        capability_ids=("equal_length_ray_path_reduction",),
        trace_refs=(),
        title="demo",
        goal="demo",
        nav_title=None,
        derive=(),
        box=(),
        teaching_substep_ids=("path_reduction",),
    )

    timeline = AnimationTimelineBuilder().timeline_for_step(
        lesson_step,
        VisualRoleBindings(),
        interactions=(),
    )

    assert timeline == {"mode": "none"}


def test_vs3_forward_compile_writes_animation_to_lesson_data() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")

    compiled = forward_compile(visual_ir)
    lesson_step = next(
        step for step in compiled.lesson_data["steps"]
        if step["id"] == path_step.lesson_step_id
    )
    raw_deco = compiled.step_decorations["steps"][path_step.lesson_step_id]

    assert "animation" in lesson_step
    assert lesson_step["animation"]["mode"] == "manual_then_interactive"
    assert "beats" in lesson_step["animation"]
    assert "frames" not in lesson_step["animation"]
    assert "animation" not in raw_deco
    minimum_step = _visual_step_for_substep(visual_ir, lesson, "minimum_by_segment")
    minimum_raw_deco = compiled.step_decorations["steps"][minimum_step.lesson_step_id]
    assert _count_segment_label(minimum_raw_deco, "O", "G", "OG") == 1
    minimum_lesson_step = next(
        step for step in compiled.lesson_data["steps"]
        if step["id"] == minimum_step.lesson_step_id
    )
    reduced_beat = next(
        beat for beat in minimum_lesson_step["animation"]["beats"]
        if str(beat.get("id") or "").endswith("path-minimum-reduced-path")
    )
    assert {"line:O:G", "distance:O:G:OG"}.issubset(
        set(reduced_beat["scene_patch"]["hide"])
    )
    result_beat = next(
        beat for beat in minimum_lesson_step["animation"]["beats"]
        if str(beat.get("id") or "").endswith("path-minimum-result")
    )
    assert _count_segment_label(
        {"add": result_beat["scene_patch"]["add"]},
        "O",
        "G",
        "OG",
    ) == 1
    assert any(
        item.get("type") == "outlineRegion"
        for beat in lesson_step["animation"]["beats"]
        for item in beat["scene_patch"]["add"]
    )


def test_vs3_visual_step_ir_validator_rejects_invalid_timeline_local_var() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")
    payload = visual_ir.to_payload()
    step_payload = next(
        step for step in payload["steps"]
        if step["lesson_step_id"] == path_step.lesson_step_id
    )
    step_payload["timeline"]["beats"][0]["transition"]["local_vars"] = {
        "unknown": {"from": 0.2, "to": 0.3}
    }
    bad = visual_step_ir_from_payload(payload)

    with pytest.raises(VisualStepIRValidationError, match="unknown local var"):
        VisualStepIRValidator().validate(bad)


def test_vs3_visual_step_ir_validator_rejects_empty_non_none_timeline() -> None:
    visual_ir, _, _ = _build_heping_vs1_visual_ir()
    payload = visual_ir.to_payload()
    payload["steps"][0]["timeline"] = {"mode": "manual_then_interactive", "beats": []}
    bad = visual_step_ir_from_payload(payload)

    with pytest.raises(VisualStepIRValidationError, match="requires beats"):
        VisualStepIRValidator().validate(bad)


def test_vs3_visual_step_ir_validator_rejects_legacy_frames_timeline() -> None:
    visual_ir, _, _ = _build_heping_vs1_visual_ir()
    payload = visual_ir.to_payload()
    payload["steps"][0]["timeline"] = {"mode": "manual_then_interactive", "frames": []}
    bad = visual_step_ir_from_payload(payload)

    with pytest.raises(VisualStepIRValidationError, match="frames are no longer supported"):
        VisualStepIRValidator().validate(bad)


def test_vs1_recipe_minimum_substep_uses_only_minimum_visual_templates() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    minimum_step = _visual_step_for_substep(visual_ir, lesson, "minimum_by_segment")

    serialized = json.dumps(minimum_step.scene["add"], ensure_ascii=False)

    assert "OG" in serialized
    assert '"label": "BN"' not in serialized
    assert '"label": "MG"' not in serialized
    assert any(
        item.get("component") == "OutlineRegion"
        and item.get("vertices") == ["O", "M", "G"]
        for item in minimum_step.scene["add"]
    )
    assert any(
        item.get("component") == "ColoredLine"
        and item.get("from") == "C"
        and item.get("to") == "G"
        and item.get("color") == "#0f766e"
        and item.get("width") == 2.0
        for item in minimum_step.scene["add"]
    )


def test_vs1_parameter_step_carries_minimum_expression_visual_context() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    parameter_step = _visual_step_for_capability(visual_ir, lesson, "parameter_from_expression_value")

    refs = _refs(parameter_step.scene["add"])

    assert {"O", "G"}.issubset(refs)
    assert any(item.get("component") == "DistanceMarker" and item.get("label") == "OG" for item in parameter_step.scene["add"])
    assert any(item.get("component") == "Point" and item.get("at") == "G" for item in parameter_step.scene["add"])
    assert "E1" not in refs
    assert "F1" not in refs


def test_vs1_scope_specific_geometry_mapping_does_not_cross_part_i_and_part_ii() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    angle_step = _visual_step_for_capability(visual_ir, lesson, "angle_sum_equal_angle_candidates")
    ii_parabola_step = _visual_step_for_scope_and_capability(
        visual_ir,
        lesson,
        scope_id="ii",
        capability_id="quadratic_from_constraints",
    )

    angle_marker = next(
        item for item in angle_step.scene["add"]
        if item.get("component") == "AngleEqualityMarker"
    )
    angle_arcs = angle_marker["angles"]
    curve_ids = [
        item.get("curveId") for item in ii_parabola_step.scene["add"]
        if item.get("component") == "Parabola"
    ]
    curves_by_root = {
        curve["scopeRoot"]: curve["id"]
        for curve in visual_ir.geometry_spec["curves"]
    }

    assert any(item.get("vertex") == "B1" for item in angle_arcs)
    assert not any(item.get("vertex") == "B" for item in angle_arcs)
    assert not any(item.get("rayB") == "F1" for item in angle_arcs)
    assert curve_ids == [curves_by_root["ii"]]
    assert curves_by_root["ii"] != curves_by_root["i"]


def test_vs1_angle_sum_method_declares_angle_equality_visual_spec() -> None:
    spec = MethodSpecRegistry.load_from_code().require("angle_sum_equal_angle_candidates")

    assert spec.visual is not None
    assert spec.visual.role_binder_id == "angle_sum_equal_angle_candidates"
    assert spec.visual.scene_templates[0]["component"] == "AngleEqualityMarker"


def test_vs1_axis_intercept_method_declares_equal_acute_intercept_visual_spec() -> None:
    spec = MethodSpecRegistry.load_from_code().require("axis_intercept_from_equal_acute_angles")

    assert spec.visual is not None
    assert spec.visual.role_binder_id == "axis_intercept_from_equal_acute_angles"
    assert spec.visual.scene_templates[0]["component"] == "EqualAcuteAngleInterceptMarker"
    assert spec.visual.scene_templates[0]["show_angles"] is False
    assert spec.visual.scene_templates[0]["show_right_angles"] is False


def test_vs1_equal_length_recipe_declares_congruent_triangle_visual_spec() -> None:
    spec = RecipeSpecRegistry.load_from_code().get("equal_length_ray_path_reduction")

    assert spec is not None
    assert spec.visual is not None
    assert spec.visual.role_binder_id == "equal_length_ray_path_reduction"
    templates = spec.visual.teaching_substep_templates["path_reduction"]
    assert [template["component"] for template in templates] == [
        "CongruentTriangleMarker",
        "EquivalentSegmentMarker",
    ]
    assert [
        template["component"]
        for template in spec.visual.teaching_substep_templates["minimum_by_segment"]
    ] == [
        "PathMinimumTriangleMarker",
        "AuxiliaryRayGuideMarker",
    ]


def test_vs1_angle_equality_static_step_uses_be_guide_not_future_f() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    angle_step = _visual_step_for_capability(visual_ir, lesson, "angle_sum_equal_angle_candidates")
    compiled = forward_compile(visual_ir)
    raw_step = compiled.step_decorations["steps"][angle_step.lesson_step_id]
    serialized = json.dumps(angle_step.scene["add"], ensure_ascii=False)

    assert "F1" not in serialized
    marker = next(item for item in angle_step.scene["add"] if item["component"] == "AngleEqualityMarker")
    assert {angle["name"] for angle in marker["angles"]} == {"OBE", "ACO"}
    assert any(guide.get("handle") == "line:i_2:BE" for guide in marker["guide_arms"])
    assert "E1" not in marker["guide_only_refs"]
    assert any(item.get("component") == "Point" and item.get("at") == "E1" for item in angle_step.scene["add"])
    assert any(
        item.get("component") == "CoordinateLabel"
        and item.get("at") == "C"
        and item.get("text") in {"C(0,-3)", "C(0, -3)"}
        for item in angle_step.scene["add"]
    )
    assert not any(
        item.get("component") == "CoordinateLabel"
        and item.get("at") == "E1"
        for item in angle_step.scene["add"]
    )
    assert any(
        item.get("component") == "AngleArc"
        and item.get("vertex") == "B1"
        and item.get("rayA") == "C"
        and item.get("rayB") == "O"
        and item.get("label") == "45°"
        for item in angle_step.scene["add"]
    )
    assert not any(
        item.get("component") == "AngleArc"
        and item.get("vertex") == "C"
        and item.get("label") == "45°"
        for item in angle_step.scene["add"]
    )
    assert any(
        item.get("type") == "dashedLine"
        and item.get("from") == "B1"
        and item.get("to") == "E1"
        for item in raw_step["add"]
    )
    assert any(item.get("type") == "point" and item.get("at") == "E1" for item in raw_step["add"])
    assert not any(item.get("type") == "point" and item.get("at") == "F1" for item in raw_step["add"])
    assert not any(item.get("type") == "coordinateLabel" and item.get("at") == "E1" for item in raw_step["add"])


def test_vs1_angle_sum_visual_ignores_llm_future_f_box_text() -> None:
    snapshot = _solve_heping_snapshot()
    payload = _load_recorded_heping_lesson_ir().to_payload()
    for step in payload["steps"]:
        if "angle_sum_equal_angle_candidates" not in step.get("capability_ids", []):
            continue
        step["title"] = "第2步：由∠CBE+∠ACO=45°推出等角关系"
        step["derive"] = [
            ["∵", "∠CBE + ∠ACO = 45°，且 ∠CBE + ∠EBF = ∠CBO = 45°"],
            ["∴", "∠EBF = ∠ACO，即 ∠OBF = ∠ACO"],
        ]
        step["box"] = ["∠OBF = ∠ACO"]
    lesson = lesson_ir_from_payload(payload)

    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    angle_step = _visual_step_for_capability(visual_ir, lesson, "angle_sum_equal_angle_candidates")
    compiled = forward_compile(visual_ir)
    raw_step = compiled.step_decorations["steps"][angle_step.lesson_step_id]
    serialized = json.dumps(angle_step.scene["add"], ensure_ascii=False)

    assert "F1" not in serialized
    marker = next(item for item in angle_step.scene["add"] if item["component"] == "AngleEqualityMarker")
    assert {angle["name"] for angle in marker["angles"]} == {"OBE", "ACO"}
    assert any(guide.get("handle") == "line:i_2:BE" for guide in marker["guide_arms"])
    assert any(item.get("component") == "Point" and item.get("at") == "E1" for item in angle_step.scene["add"])
    assert not any(
        item.get("component") == "CoordinateLabel" and item.get("at") == "O"
        for item in angle_step.scene["add"]
    )
    assert any(
        item.get("type") == "dashedLine"
        and item.get("from") == "B1"
        and item.get("to") == "E1"
        for item in raw_step["add"]
    )


def test_vs1_reference_angle_without_bound_value_has_no_implicit_45_label() -> None:
    items = visual_builder._angle_reference_items(
        VisualRoleBindings(
            angle_references=(
                {
                    "vertex": "B",
                    "rayA": "A",
                    "rayB": "C",
                },
            )
        )
    )

    assert items == [
        {
            "component": "AngleArc",
            "vertex": "B",
            "rayA": "A",
            "rayB": "C",
            "color": "#0f766e",
            "radius": 43,
            "metadata": {"low_level_type": "angleArc"},
        }
    ]
    assert '"45°"' not in inspect.getsource(visual_role_binders._reference_angles_from_method_output)


def test_visual_axis_arm_detection_uses_problem_origin_label_not_literal_o() -> None:
    assert visual_role_binders._axis_arm("Z", "A", frozenset({"Z"})) is True
    assert visual_role_binders._axis_arm("A", "Z", frozenset({"Z"})) is True
    assert visual_role_binders._axis_arm("O", "A", frozenset({"Z"})) is False

    index = VisualGeometryIndex(
        {"fixedPoints": {"Z": ["0", "0"]}, "movingPoints": {}},
        {
            "entities": [
                {
                    "entity_type": "point",
                    "handle": "point:origin",
                    "name": "Z",
                    "definition": "coordinate_origin",
                }
            ]
        },
    )

    assert index.origin_labels == frozenset({"Z"})


def test_visual_projection_helper_label_falls_forward_after_conflicts() -> None:
    used = set(visual_role_binders.PROJECTION_HELPER_LABEL_CANDIDATES)

    assert visual_role_binders._fresh_projection_label(used) == "Q1"
    used.add("Q1")
    assert visual_role_binders._fresh_projection_label(used) == "R1"


def test_vs1_reference_angle_marker_comes_from_method_output_not_derive_text() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    payload = lesson.to_payload()
    for step in payload["steps"]:
        if "angle_sum_equal_angle_candidates" not in step.get("capability_ids", []):
            continue
        step["derive"] = [
            item
            for item in step["derive"]
            if "∠CBO=45°" not in item[1]
        ]
    lesson = lesson_ir_from_payload(payload)

    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    angle_step = _visual_step_for_capability(visual_ir, lesson, "angle_sum_equal_angle_candidates")

    assert any(
        item.get("component") == "AngleArc"
        and item.get("vertex") == "B1"
        and item.get("rayA") == "C"
        and item.get("rayB") == "O"
        and item.get("label") == "45°"
        for item in angle_step.scene["add"]
    )


def test_vs1_generated_layers_use_exact_step_ids_to_avoid_prefix_collision() -> None:
    snapshot = _solve_heping_snapshot()
    payload = _load_recorded_heping_lesson_ir().to_payload()
    last_id = payload["steps"][-1]["id"]
    payload["steps"][-1]["id"] = "step_10"
    for section in payload["sections"]:
        section["steps"] = ["step_10" if step_id == last_id else step_id for step_id in section["steps"]]
    lesson = lesson_ir_from_payload(payload)

    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    compiled = forward_compile(visual_ir)
    layers = compiled.step_decorations["layers"]

    assert "step_10" in layers["partII"]["stepIds"]
    assert "step_10" not in layers["partI"]["stepIds"]
    assert "step_1" in layers["partI"]["stepStartsWith"]


def test_vs1_axis_intercept_step_reuses_be_visual_handle_and_adds_f() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    f_step = _visual_step_for_capability(visual_ir, lesson, "axis_intercept_from_equal_acute_angles")
    compiled = forward_compile(visual_ir)
    raw_step = compiled.step_decorations["steps"][f_step.lesson_step_id]

    assert {
        "handle": "line:i_2:BE",
        "state": "highlight",
    } in f_step.scene["state_overrides"]
    marker = next(
        item for item in f_step.scene["add"]
        if item.get("component") == "EqualAcuteAngleInterceptMarker"
    )
    assert {
        ("A", "O", "C"),
        ("B1", "O", "F1"),
    }.issubset(
        {tuple(region.get("vertices") or ()) for region in marker["triangle_regions"]}
    )
    assert any(
        line.get("handle") == "line:i_2:BE"
        and line.get("from") == "B1"
        and line.get("to") == "E1"
        and line.get("style") == "solid"
        for line in marker["lines"]
    )
    assert any(
        line.get("handle") == "line:i_2:CA"
        and line.get("from") == "C"
        and line.get("to") == "A"
        and line.get("style") == "dashed"
        for line in marker["lines"]
    )
    assert marker["angles"] == []
    assert marker["right_angles"] == []
    assert any(item.get("component") == "Point" and item.get("at") == "F1" for item in f_step.scene["add"])
    assert any(item.get("component") == "Point" and item.get("at") == "E1" for item in f_step.scene["add"])
    coordinate_labels = {
        item.get("at"): item.get("text")
        for item in f_step.scene["add"]
        if item.get("component") == "CoordinateLabel"
    }
    assert coordinate_labels["A"] == "A(-1,0)"
    assert coordinate_labels["B1"] == "B(3, 0)"
    assert coordinate_labels["C"] == "C(0, -3)"
    assert coordinate_labels["F1"] == "F(0, -1)"
    assert "E1" not in coordinate_labels
    assert any(
        item.get("type") == "outlineRegion"
        and item.get("vertices") == ["A", "O", "C"]
        for item in raw_step["add"]
    )
    assert any(
        item.get("type") == "outlineRegion"
        and item.get("vertices") == ["B1", "O", "F1"]
        for item in raw_step["add"]
    )
    assert any(
        item.get("type") == "coloredLine"
        and item.get("from") == "B1"
        and item.get("to") == "E1"
        for item in raw_step["add"]
    )
    assert any(
        item.get("type") == "dashedLine"
        and item.get("from") == "C"
        and item.get("to") == "A"
        for item in raw_step["add"]
    )
    assert not any(item.get("type") == "rightAngle" for item in raw_step["add"])
    assert not any(
        item.get("type") == "angleArc"
        and item.get("label") == "α"
        for item in raw_step["add"]
    )


def test_vs1_missing_roles_generate_visual_gap() -> None:
    snapshot = ExplanationSnapshot(
        problem_id="gap-case",
        family_id="demo",
        problem={"entities": [], "facts": []},
        effective_steps=(),
        teaching_trace=(),
        fact_index={},
    )
    lesson = LessonIR(
        problem_id="gap-case",
        family_id="demo",
        sections=(LessonSection(scope_id="ii", title="ii", steps=("gap_step",)),),
        steps=(
            LessonStep(
                id="gap_step",
                scope_id="ii",
                source_step_ids=(),
                capability_ids=("distance_between_points",),
                trace_refs=(),
                title="缺少距离角色",
                goal="触发 VisualGap",
            ),
        ),
    )

    visual_ir = VisualStepBuilder().build(
        snapshot=snapshot,
        lesson=lesson,
    )

    assert visual_ir.steps[0].scene["add"] == [
        {
            "component": "VisualGap",
            "expected_role": "visual_role",
            "reason": "No static visual spec matched this Lesson step.",
            "state": "gap",
        }
    ]
    VisualStepIRValidator().validate(visual_ir)


def test_vs1_annotation_text_source_is_checked() -> None:
    visual_ir, _, _ = _build_heping_vs1_visual_ir()
    VisualStepIRValidator().validate(visual_ir)

    payload = visual_ir.to_payload()
    payload["steps"][0]["scene"]["annotations"][0]["text"] = "wrong"
    bad = visual_step_ir_from_payload(payload)

    with pytest.raises(VisualStepIRValidationError, match="conflicts with lesson_step.box"):
        VisualStepIRValidator().validate(bad)


def test_vs2_visual_step_ir_validator_rejects_invalid_local_interaction() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")
    payload = visual_ir.to_payload()
    step_payload = next(step for step in payload["steps"] if step["lesson_step_id"] == path_step.lesson_step_id)
    step_payload["interactions"][0]["parameterized_points"]["M"]["expression"] = ["u"]
    bad = visual_step_ir_from_payload(payload)

    with pytest.raises(VisualStepIRValidationError, match="expression must be a 2-item list"):
        VisualStepIRValidator().validate(bad)


def test_vs1_visual_role_binding_uses_known_geometry_handles() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")
    serialized = json.dumps(path_step.scene["add"], ensure_ascii=False)

    assert '"at": "G"' in serialized
    assert '"from": "C"' in serialized
    assert '"to": "G"' in serialized
    assert '"at": "M"' in serialized
    assert '"at": "N"' in serialized


def test_vs1_recorded_heping_compiles_three_json_files_and_page(tmp_path: Path) -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()

    assert len(visual_ir.steps) == len(lesson.steps)
    VisualStepIRValidator().validate(visual_ir)

    compiled = forward_compile(visual_ir)
    assert any(step.get("localControls") for step in compiled.lesson_data["steps"])
    assert any(
        step.get("pointOverrides")
        for step in compiled.step_decorations["steps"].values()
        if isinstance(step, dict)
    )
    lesson_data = copy.deepcopy(compiled.lesson_data)
    html_path = tmp_path / "heping-vs1.html"
    lesson_data["meta"]["outputPath"] = str(html_path)
    _write_compiled_artifacts(
        tmp_path,
        geometry_spec=compiled.geometry_spec,
        step_decorations=compiled.step_decorations,
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
    assert "STEPS" in html
    assert "localControls" in html
    assert "pointOverrides" in html
    for step in lesson.steps:
        assert step.id in compiled.step_decorations["steps"]
        assert step.id in html


def test_vs1_lesson_data_uses_student_titles_and_distributed_answer_boxes() -> None:
    visual_ir, _, _ = _build_heping_vs1_visual_ir()
    compiled = forward_compile(visual_ir)
    meta = compiled.lesson_data["meta"]
    problem = compiled.lesson_data["problem"]
    steps = compiled.lesson_data["steps"]
    titles = [step["title"] for step in steps]
    sections = [step["section"] for step in steps]
    boxes_by_id = {step["id"]: step.get("box", []) for step in steps}

    assert meta["pageTitle"] == "2026 年天津市和平区一模 第 25 题（二次函数综合）"
    assert meta["breadcrumbTitle"] == "2026 天津市和平区一模 第 25 题"
    assert problem["summary"] == "第 25 题（2026 天津市和平区一模）二次函数综合：解析式、角度条件与 OM+BN 路径最值。"
    assert problem["lines"][0]["text"].startswith("（25）（本小题 10 分）")
    assert "连接 BC" in problem["lines"][0]["text"]
    assert problem["lines"][1]["answerId"] == "answer_i_1_parabola"
    assert problem["lines"][1]["answer"] == "y＝x²－2x－3"
    assert problem["lines"][2]["answerId"] == "answer_i_2_E"
    assert problem["lines"][2]["answer"] == "E(－2/3, －11/9)"
    assert problem["lines"][3]["answerId"] == "answer_ii_a"
    assert problem["lines"][3]["answer"] == "a＝3/4"
    assert all(not title.startswith(("fact:", "answer:")) for title in titles)
    assert any(section.startswith("第（Ⅰ）①问") for section in sections)
    assert any(section.startswith("第（Ⅰ）②问") for section in sections)
    assert any(section.startswith("第（Ⅱ）问") for section in sections)
    serialized_boxes = json.dumps(boxes_by_id, ensure_ascii=False)
    assert "i_1.parabola =" not in serialized_boxes
    assert "i_2.E =" not in serialized_boxes
    assert "answer:" not in serialized_boxes
    assert "fact:" not in serialized_boxes
    assert "y=x²-2x-3" in serialized_boxes
    assert "E(-2/3,-11/9)" in serialized_boxes
    final_boxes = boxes_by_id["explain_solve_ii_a_from_minimum_value"]
    assert any("a=3/4" in box for box in final_boxes)
    assert not any("parabola =" in box or ".E =" in box or ".a =" in box for box in final_boxes)


def test_vs1_recorded_lesson_fixture_uses_nav_title_and_student_readable_box() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    LessonIRValidator().validate(lesson, snapshot)
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    compiled = forward_compile(visual_ir)

    step_1 = compiled.lesson_data["steps"][0]
    boxes = step_1["box"]

    assert step_1["title"] == "第1步：求 C、D 点坐标，代入求函数解析式"
    assert compiled.lesson_data["stepLabels"]["step_1"] == "1 代入已知点求解析式"
    assert boxes == ["C(0,-3)", "D(2,-3)", "y=x²-2x-3"]
    assert "i_1.parabola" not in json.dumps(compiled.lesson_data, ensure_ascii=False)


def test_vs1_problem_answer_chips_use_question_goals_not_line_keywords() -> None:
    lines = visual_builder._problem_lines_with_answers(
        title="demo",
        display={},
        problem={
            "question_goals": [
                {
                    "handle": "answer:alpha_root",
                    "scope_id": "alpha",
                    "answer_key": "root",
                    "value_type": "Point",
                },
                {
                    "handle": "answer:alpha_vertex",
                    "scope_id": "alpha",
                    "answer_key": "V",
                    "value_type": "Point",
                },
                {
                    "handle": "answer:beta_k",
                    "scope_id": "beta",
                    "answer_key": "k",
                    "value_type": "ParameterValue",
                },
                {
                    "handle": "answer:gamma_E",
                    "scope_id": "gamma",
                    "answer_key": "E",
                    "value_type": "PointList",
                },
            ],
        },
        lines=[
            "公共条件：给出若干点和函数。",
            "求第一个目标。",
            "继续求第二个目标。",
            "求候选点。",
        ],
        answers={
            "alpha": {"root": ["1", "2"], "V": ["3", "4"]},
            "beta": {"k": "5"},
            "gamma": {"E": [["-1", "2 + sqrt(6)"], ["-1", "2 - sqrt(6)"]]},
        },
    )

    assert "answerId" not in lines[0]
    assert lines[1]["answerId"] == "answer_alpha"
    assert lines[1]["answer"] == "点(1, 2)，V(3, 4)"
    assert lines[2]["answerId"] == "answer_beta_k"
    assert lines[2]["answer"] == "k＝5"
    assert lines[3]["answerId"] == "answer_gamma_E"
    assert lines[3]["answer"] == "E(－1, 2＋√6) 或 E(－1, 2－√6)"


def test_vs1_problem_line_merge_uses_generic_parent_child_markers() -> None:
    lines = visual_builder._merge_condition_with_first_subquestion(
        [
            "（二）已知函数图象经过点 A。",
            "1. 求函数解析式；",
            "（三）继续求参数。",
            "① 求参数值。",
        ]
    )

    assert lines == [
        "（二）已知函数图象经过点 A，1. 求函数解析式；",
        "（三）继续求参数，① 求参数值。",
    ]


def test_vs1_problem_summary_prefers_problem_ir_summary_over_keyword_fallback() -> None:
    lesson = LessonIR(
        problem_id="summary-case",
        family_id="demo",
        sections=(),
        steps=(),
    )
    snapshot = ExplanationSnapshot(
        problem_id="summary-case",
        family_id="demo",
        problem={
            "title": "Demo 第 1 题",
            "summary": "结构化 ProblemIR 摘要。",
            "original_text": ["求解析式，并求路径最小值。"],
        },
        effective_steps=(),
        teaching_trace=(),
        fact_index={},
    )

    shell = visual_builder._generated_lesson_shell(
        snapshot=snapshot,
        lesson=lesson,
        default_t=0.5,
    )

    assert shell["problem"]["summary"] == "结构化 ProblemIR 摘要。"
    assert shell["meta"]["pageDescription"] == "结构化 ProblemIR 摘要。"


def test_vs1_lesson_data_renumbers_titles_and_nav_labels_per_section() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    payload = lesson.to_payload()
    payload["steps"][4]["title"] = "第1步：用参数 a 表示第（Ⅱ）问的抛物线和点 B"
    payload["steps"][4]["nav_title"] = "1 参数表示函数和B"
    lesson = lesson_ir_from_payload(payload)

    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    compiled = forward_compile(visual_ir)

    assert compiled.lesson_data["steps"][4]["title"] == "第1步：用参数 a 表示第（Ⅱ）问的抛物线和点 B"
    assert compiled.lesson_data["stepLabels"]["step_5"] == "1 参数表示函数和B"


def test_vs1_old_lesson_payload_without_nav_title_still_loads() -> None:
    payload = json.loads(HEPING_RECORDED_LESSON_IR.read_text(encoding="utf-8"))
    payload["steps"][0].pop("nav_title")

    lesson = lesson_ir_from_payload(payload)

    assert lesson.steps[0].nav_title is None


def test_vs1_visual_builder_uses_verified_runtime_coordinates_for_labels() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    c_step = _visual_step_for_capability(visual_ir, lesson, "quadratic_y_axis_intercept_point")
    d_step = _visual_step_for_capability(visual_ir, lesson, "translated_point")
    f_step = _visual_step_for_capability(visual_ir, lesson, "axis_intercept_from_equal_acute_angles")
    e_step = _visual_step_for_capability(visual_ir, lesson, "line_parabola_second_intersection_point")

    labels = [
        item
        for step in (c_step, d_step, f_step, e_step)
        for item in step.scene["add"]
        if item.get("component") == "CoordinateLabel"
    ]

    assert any(item.get("text") == "C(0, -3)" for item in labels)
    assert any(item.get("text") == "D(2, -3)" for item in labels)
    assert any(item.get("text") == "F(0, -1)" for item in labels)
    assert any(item.get("text") == "E(-2/3, -11/9)" for item in labels)


def test_vs1_alignment_with_reverse_golden_key_objects() -> None:
    visual_ir, lesson, _ = _build_heping_vs1_visual_ir()
    path_step = _visual_step_for_substep(visual_ir, lesson, "path_reduction")
    minimum_step = _visual_step_for_substep(visual_ir, lesson, "minimum_by_segment")

    path_refs = _refs(path_step.scene["add"])
    minimum_refs = _refs(minimum_step.scene["add"])

    assert {"C", "G", "M", "N"}.issubset(path_refs)
    assert {"O", "G", "M"}.issubset(minimum_refs)


def test_vs1_llm_visual_optimizer_applies_safe_patch_and_writes_debug(tmp_path: Path) -> None:
    visual_ir, lesson, snapshot = _build_heping_vs1_visual_ir()
    client = _FakeVisualOptimizationClient()
    optimizer = LLMVisualStepOptimizer(client=client, debug_dir=tmp_path)

    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)

    assert client.calls == 1
    VisualStepIRValidator().validate(optimized)
    patched_step = next(step for step in optimized.steps if step.lesson_step_id == "explain_reduce_ii_equal_length_ray_path_minimum_by_segment")
    assert any(item.get("label") == "OG_min" for item in patched_step.scene["add"])
    assert (tmp_path / "payload.visual.json").exists()
    assert (tmp_path / "prompt.system.txt").exists()
    assert (tmp_path / "prompt.user.txt").exists()
    assert (tmp_path / "raw-response.txt").exists()
    assert (tmp_path / "parsed-visual-optimization.json").exists()
    assert (tmp_path / "optimized-visual-step-ir.json").exists()
    prompt = (tmp_path / "prompt.user.txt").read_text(encoding="utf-8")
    assert "代码生成的 Visual Steps" in prompt
    assert "allowed_geometry_refs" in (tmp_path / "payload.visual.json").read_text(encoding="utf-8")
    assert "base_layers" in (tmp_path / "payload.visual.json").read_text(encoding="utf-8")


def test_vs1_visual_llm_parse_json_object_handles_wrappers() -> None:
    assert visual_llm._parse_json_object(
        '```json\n{"visual_step_patches": []}\n```'
    ) == {"visual_step_patches": []}
    assert visual_llm._parse_json_object(
        '说明文字 {"visual_step_patches": [], "layer_patches": []} 结束'
    ) == {"visual_step_patches": [], "layer_patches": []}

    with pytest.raises(visual_llm.VisualOptimizationError, match="JSON object"):
        visual_llm._parse_json_object("[1, 2, 3]")


def test_vs1_visual_llm_filter_safe_append_add_removes_coordinate_labels() -> None:
    safe = visual_llm._filter_safe_append_add(
        [
            {"component": "CoordinateLabel", "at": "A", "text": "A(0,0)"},
            {"component": "Point", "at": "A"},
        ]
    )

    assert safe == [{"component": "Point", "at": "A"}]


def test_vs1_visual_llm_filter_safe_append_add_normalizes_dashed_segments() -> None:
    safe = visual_llm._filter_safe_append_add(
        [
            {
                "component": "Segment",
                "from": "A",
                "to": "B",
                "color": "#9ca3af",
                "width": 1.2,
                "dashed": True,
                "metadata": {"low_level_type": "segment"},
            }
        ]
    )

    assert safe == [
        {
            "component": "DashedLine",
            "from": "A",
            "to": "B",
            "color": "#9ca3af",
            "width": 1.2,
        }
    ]


def test_vs1_visual_llm_filter_safe_append_add_normalizes_line_at_pairs() -> None:
    safe = visual_llm._filter_safe_append_add(
        [
            {
                "component": "Segment",
                "at": ["point:A", "point:G"],
                "color": "#ff6347",
                "dashed": True,
            }
        ]
    )

    assert safe == [
        {
            "component": "DashedLine",
            "from": "A",
            "to": "G",
            "color": "#ff6347",
        }
    ]


def test_vs1_visual_llm_filter_safe_append_add_rejects_carry_forward_items() -> None:
    with pytest.raises(visual_llm.VisualOptimizationError, match="carry_forward"):
        visual_llm._filter_safe_append_add(
            [
                {
                    "component": "ColoredLine",
                    "from": "A",
                    "to": "B",
                    "handle": "line:i:AB",
                    "persistence": "carry_forward",
                }
            ]
        )


def test_vs1_visual_llm_assert_scene_item_refs_checks_geometry_and_labels() -> None:
    allowed = {"A", "B", "C", "O"}

    visual_llm._assert_scene_item_refs(
        {
            "component": "AngleEqualityMarker",
            "angles": [
                {"vertex": "B", "rayA": "A", "rayB": "O", "label": "α"},
                {"vertex": "C", "rayA": "A", "rayB": "O", "label": "α"},
            ],
        },
        allowed,
    )

    with pytest.raises(visual_llm.VisualOptimizationError, match="UnknownPoint"):
        visual_llm._assert_scene_item_refs({"component": "Point", "at": "UnknownPoint"}, allowed)
    with pytest.raises(visual_llm.VisualOptimizationError, match="Chinese prose"):
        visual_llm._assert_scene_item_refs(
            {"component": "DistanceMarker", "from": "A", "to": "B", "label": "右移"},
            allowed,
        )
    with pytest.raises(visual_llm.VisualOptimizationError, match="unknown visual component"):
        visual_llm._assert_scene_item_refs({"component": "MadeUpComponent", "at": "A"}, allowed)


def test_vs1_generated_geometry_and_base_layers_do_not_read_authored_specs() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()

    generated_geometry = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)
    generated_layers = BaseSceneBuilder().build(
        geometry_spec=generated_geometry,
        lesson=lesson,
        snapshot=snapshot,
    )
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)

    assert visual_ir.metadata["base_source"] == "generated"
    assert generated_geometry["id"] == snapshot.problem_id
    assert "A" in generated_geometry["fixedPoints"]
    curve_roots = {curve["scopeRoot"] for curve in generated_geometry["curves"]}
    assert curve_roots == {"i", "ii"}
    assert all(str(curve["id"]).startswith(f"curve_{curve['scopeRoot']}_") for curve in generated_geometry["curves"])
    assert {"parabolaPart1", "parabolaMain"}.isdisjoint(
        {curve["id"] for curve in generated_geometry["curves"]}
    )
    assert all(curve.get("sourceHandle") for curve in generated_geometry["curves"])
    assert generated_geometry["pointMeta"]["B1"]["label"] == "B"
    assert generated_geometry["pointMeta"]["B1"]["scopeRoot"] == "i"
    assert generated_geometry["pointMeta"]["B"]["label"] == "B"
    assert generated_geometry["pointMeta"]["B"]["scopeRoot"] == "ii"
    assert "M" not in generated_geometry["movingPoints"]
    assert "N" not in generated_geometry["movingPoints"]
    assert any(
        entity.get("handle") == "segment:problem:BC"
        for entity in (snapshot.problem or {}).get("entities", [])
    )
    assert generated_layers["section:i"]["elements"]
    assert generated_layers["section:ii"]["elements"]
    assert visual_ir.layers["global"]["elements"]
    assert visual_ir.layers["section:i"]["elements"]
    assert visual_ir.layers["section:ii"]["elements"]
    part_i_elements = visual_ir.layers["section:i"]["elements"]
    assert any(item.get("type") == "point" and item.get("at") == "B1" and item.get("labelText") == "B" for item in part_i_elements)
    assert any(item.get("type") == "coloredLine" and item.get("from") == "B1" and item.get("to") == "C" for item in part_i_elements)
    assert not any(item.get("type") == "point" and item.get("at") == "O" for item in part_i_elements)
    assert "E1" not in {
        item.get("at")
        for layer_key in ("section:i", "section:ii")
        for item in visual_ir.layers[layer_key].get("elements", [])
        if isinstance(item, dict)
    }


def test_vs1_scene_add_uses_rule_table_not_capability_if_chain() -> None:
    source = inspect.getsource(visual_builder._scene_add_for_lesson_step)
    spec_source = inspect.getsource(visual_builder._scene_items_from_visual_specs)

    assert "_scene_items_from_visual_specs" in source
    assert "_scene_visual_rules()" in spec_source
    assert "_uses_any" not in source


def test_vs1_angle_and_axis_visual_handlers_use_bound_refs_not_point_name_literals() -> None:
    angle_source = inspect.getsource(visual_builder._angle_sum_visual_items)
    axis_source = inspect.getsource(visual_builder._axis_intercept_visual_items)

    assert "_point_marker_refs_from_scene_items" in angle_source
    assert "_point_marker_refs_from_scene_items" in axis_source
    assert "('E',)" not in angle_source
    assert '("E",)' not in angle_source
    assert "('E',)" not in axis_source
    assert '("E",)' not in axis_source
    assert "('F',)" not in axis_source
    assert '("F",)' not in axis_source


def test_vs1_equal_length_visual_handlers_use_marker_payloads_not_fixed_point_names() -> None:
    reduction_source = inspect.getsource(visual_builder._equal_length_reduction_visual_items)
    minimum_source = inspect.getsource(visual_builder._minimum_distance_items)

    assert reduction_source.strip().endswith("return []")
    assert "equal_length_path_markers" in minimum_source
    for fixed_pair in (
        '("O", "M"',
        '("B", "N"',
        '("M", "G"',
        '("C", "G"',
        '"OG"',
    ):
        assert fixed_pair not in minimum_source


def test_vs1_point_style_and_focus_are_not_label_whitelists() -> None:
    point_source = inspect.getsource(visual_builder._point_items)
    focus_source = inspect.getsource(visual_builder._focus_handles)

    assert '{"F", "G"}' not in point_source
    assert '{"B", "E", "F", "G", "M", "N"}' not in focus_source
    assert "scene_add" in inspect.signature(visual_builder._focus_handles).parameters


def test_vs1_legacy_layer_mapping_uses_registry_not_part_names() -> None:
    source = inspect.getsource(visual_builder._layers_for_lesson)

    assert "semantic_for_layer_key" in source
    assert "partI" not in source
    assert "partII" not in source


def test_vs1_visual_geometry_index_maps_canonical_b_per_section() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    geometry = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)
    index = VisualGeometryIndex.default(geometry, snapshot.problem)

    assert index.point_for_handle("point:problem:B", "i") == "B1"
    assert index.point_for_handle("point:problem:B", "ii") == "B"
    assert index.point_for_handle("point:problem:C", "i") == "C"
    assert index.point_for_handle("point:problem:C", "ii") == "C"


def test_vs1_geometry_point_scope_namer_is_shared_by_builder_and_role_index() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    geometry = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)
    shared_namer = GeometryPointScopeNamer.from_geometry_spec(geometry, snapshot.problem)
    index = VisualGeometryIndex.default(geometry, snapshot.problem)

    assert shared_namer.geometry_id("B", "i") == "B1"
    assert shared_namer.geometry_id("B", "ii") == "B"
    assert index.point_for_handle("point:problem:B", "i") == shared_namer.geometry_id("B", "i")
    assert index.point_for_handle("point:problem:B", "ii") == shared_namer.geometry_id("B", "ii")


def test_vs1_geometry_point_namer_uses_scope_rules_not_specific_runtime_keys() -> None:
    snapshot = ExplanationSnapshot(
        problem_id="scope-point-naming",
        family_id="demo",
        problem={
            "entities": [
                {
                    "handle": "point:problem:C",
                    "entity_type": "point",
                    "scope_id": "problem",
                    "name": "C",
                }
            ],
        },
        effective_steps=(),
        teaching_trace=(),
        fact_index={
            "runtime:i:outputs:Q_coordinate_value": {
                "handle": "runtime:i:outputs:Q_coordinate_value",
                "scope_id": "i",
                "name": "Q_coordinate_value",
                "type": "Point",
                "value": ["1", "0"],
            },
            "runtime:ii:outputs:Q_coordinate_expr": {
                "handle": "runtime:ii:outputs:Q_coordinate_expr",
                "scope_id": "ii",
                "name": "Q_coordinate_expr",
                "type": "Point",
                "value": ["t", "0"],
            },
            "runtime:i:outputs:C_coordinate": {
                "handle": "runtime:i:outputs:C_coordinate",
                "scope_id": "i",
                "name": "C_coordinate",
                "type": "Point",
                "value": ["0", "-3"],
            },
            "runtime:i_2:points:R": {
                "handle": "runtime:i_2:points:R",
                "scope_id": "i_2",
                "name": "R",
                "type": "Point",
                "value": ["2", "1"],
            },
        },
    )
    lesson = LessonIR(problem_id="scope-point-naming", family_id="demo", sections=(), steps=())

    geometry = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)

    assert geometry["fixedPoints"]["Q1"] == ["1", "0"]
    assert geometry["movingPoints"]["Q"] == ["t", "0"]
    assert geometry["fixedPoints"]["C"] == ["0", "-3"]
    assert "C1" not in geometry["fixedPoints"]
    assert geometry["fixedPoints"]["R1"] == ["2", "1"]


def test_vs1_equal_length_auxiliary_point_label_comes_from_lesson_role_text() -> None:
    snapshot = ExplanationSnapshot(
        problem_id="auxiliary-point-naming",
        family_id="demo",
        problem={},
        effective_steps=(
            {
                "step_id": "reduce_alpha",
                "scope_id": "ii",
                "recipe_hint": "equal_length_ray_path_reduction",
                "goal_type": "derive_path_minimum_expression",
            },
        ),
        teaching_trace=(),
        fact_index={
            "runtime:reduce_alpha:temp:equal_length_auxiliary_point": {
                "handle": "runtime:reduce_alpha:temp:equal_length_auxiliary_point",
                "scope_id": "reduce_alpha",
                "name": "equal_length_auxiliary_point",
                "type": "Point",
                "value": ["t", "0"],
                "source": "equal_length_ray_point",
            },
        },
    )
    lesson = LessonIR(
        problem_id="auxiliary-point-naming",
        family_id="demo",
        sections=(),
        steps=(
            LessonStep(
                id="step_aux",
                scope_id="ii",
                source_step_ids=("reduce_alpha",),
                capability_ids=("equal_length_ray_path_reduction",),
                trace_refs=(),
                title="构造辅助点",
                goal="路径降维",
                derive=(("作", "在射线 CD 上构造点 P，使 CP=CB"),),
            ),
        ),
    )

    geometry = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)

    assert geometry["movingPoints"]["P"] == ["t", "0"]
    assert "G" not in geometry["movingPoints"]


def test_vs1_first_step_marks_known_condition_point_a_and_derived_c_d() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    step = next(item for item in visual_ir.steps if item.lesson_step_id == lesson.steps[0].id)
    coordinate_labels = {
        item.get("at"): item.get("text")
        for item in step.scene["add"]
        if item.get("component") == "CoordinateLabel"
    }

    assert coordinate_labels["A"] == "A(-1,0)"
    assert coordinate_labels["C"] == "C(0, -3)"
    assert coordinate_labels["D"] == "D(2, -3)"


def test_vs1_translated_point_uses_method_visual_spec_translation_marker() -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    d_step = _visual_step_for_capability(visual_ir, lesson, "translated_point")

    spec = MethodSpecRegistry.load_from_code().require("translated_point").visual
    assert spec is not None
    assert spec.scene_templates[0]["component"] == "TranslationMarker"

    marker = next(
        item for item in d_step.scene["add"]
        if item.get("component") == "TranslationMarker"
    )
    assert marker["source"] == "C"
    assert marker["target"] == "D"
    assert marker["vector"] == ["2", "0"]
    assert marker["label"] == "+2"

    compiled = forward_compile(visual_ir)
    step_add = compiled.step_decorations["steps"][d_step.lesson_step_id]["add"]
    assert any(
        item.get("type") == "dashedLine" and item.get("from") == "C" and item.get("to") == "D"
        for item in step_add
    )
    assert any(
        item.get("type") == "coordinateLabel" and item.get("at") == "D" and item.get("text") == "+2"
        for item in step_add
    )


def test_vs1_compiled_visual_labels_use_math_not_chinese_prose() -> None:
    visual_ir, _, _ = _build_heping_vs1_visual_ir()
    compiled = forward_compile(visual_ir)
    visual_texts: list[str] = []
    for layer in (compiled.step_decorations.get("layers") or {}).values():
        for item in layer.get("elements") or ():
            for key in ("label", "labelText", "text"):
                if isinstance(item.get(key), str):
                    visual_texts.append(item[key])
    for step in (compiled.step_decorations.get("steps") or {}).values():
        for item in step.get("add") or ():
            for key in ("label", "labelText", "text"):
                if isinstance(item.get(key), str):
                    visual_texts.append(item[key])

    assert visual_texts
    assert not any(re.search(r"[\u4e00-\u9fff]", text) for text in visual_texts)


def test_vs1_llm_visual_optimizer_rejects_unknown_geometry_ref(tmp_path: Path) -> None:
    visual_ir, lesson, snapshot = _build_heping_vs1_visual_ir()
    optimizer = LLMVisualStepOptimizer(client=_BadVisualOptimizationClient(), debug_dir=tmp_path)

    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)

    assert optimized.to_payload()["metadata"]["visual_optimizer"]["applied"] is False
    assert (tmp_path / "visual-optimization-error.txt").exists()
    assert "UnknownPoint" in (tmp_path / "visual-optimization-error.txt").read_text(encoding="utf-8")


def test_vs1_llm_visual_optimizer_ignores_coordinate_label_patches(tmp_path: Path) -> None:
    visual_ir, lesson, snapshot = _build_heping_vs1_visual_ir()
    optimizer = LLMVisualStepOptimizer(client=_UnsafeCoordinateLabelClient(), debug_dir=tmp_path)

    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)

    assert optimized.to_payload()["metadata"]["visual_optimizer"]["applied"] is True
    serialized = json.dumps(optimized.to_payload(), ensure_ascii=False)
    assert "F(0, 1)" not in serialized
    patched_step = next(
        step for step in optimized.steps
        if step.lesson_step_id == "explain_derive_i_2_F_coordinate"
    )
    assert patched_step.scene["focus"]["primary"] == ["point:B1", "point:F1"]


def test_vs1_llm_visual_optimizer_rejects_chinese_visual_labels(tmp_path: Path) -> None:
    visual_ir, lesson, snapshot = _build_heping_vs1_visual_ir()
    optimizer = LLMVisualStepOptimizer(client=_ChineseVisualLabelClient(), debug_dir=tmp_path)

    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)

    assert optimized.to_payload()["metadata"]["visual_optimizer"]["applied"] is False
    assert "Chinese prose" in (tmp_path / "visual-optimization-error.txt").read_text(encoding="utf-8")


def test_vs1_llm_visual_optimizer_rejects_future_point_in_angle_step(tmp_path: Path) -> None:
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    optimizer = LLMVisualStepOptimizer(client=_FuturePointInAngleStepClient(), debug_dir=tmp_path)

    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)

    assert optimized.to_payload()["metadata"]["visual_optimizer"]["applied"] is False
    error = (tmp_path / "visual-optimization-error.txt").read_text(encoding="utf-8")
    assert "F1" in error


def test_vs2_llm_visual_optimizer_cannot_mutate_interactions(tmp_path: Path) -> None:
    visual_ir, lesson, snapshot = _build_heping_vs1_visual_ir()
    optimizer = LLMVisualStepOptimizer(client=_InteractionMutationClient(), debug_dir=tmp_path)

    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)

    assert optimized.to_payload()["metadata"]["visual_optimizer"]["applied"] is False
    assert "interactions" in (tmp_path / "visual-optimization-error.txt").read_text(encoding="utf-8")


def test_vs3_llm_visual_optimizer_cannot_mutate_timeline(tmp_path: Path) -> None:
    visual_ir, lesson, snapshot = _build_heping_vs1_visual_ir()
    optimizer = LLMVisualStepOptimizer(client=_TimelineMutationClient(), debug_dir=tmp_path)

    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)

    assert optimized.to_payload()["metadata"]["visual_optimizer"]["applied"] is False
    assert "timeline" in (tmp_path / "visual-optimization-error.txt").read_text(encoding="utf-8")


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HEPING_VISUAL,
    reason="DeepSeek Heping visual optimizer integration is opt-in",
)
def test_deepseek_explanation_and_visual_optimizer_heping_loop() -> None:
    """产品级链路：DeepSeek 先优化 LessonIR，再优化 VisualStepIR。"""
    _reset_debug_dir(DEBUG_DIR)
    snapshot = _solve_heping_snapshot()
    lesson = _build_heping_lesson_with_deepseek(snapshot, DEBUG_DIR)

    assert len(lesson.steps) <= 10
    assert any(len(step.source_step_ids) > 1 for step in lesson.steps)

    _optimize_and_write_visual_page(
        snapshot=snapshot,
        lesson=lesson,
        debug_dir=DEBUG_DIR,
        html_name="heping-visual-optimized.html",
    )

    assert (DEBUG_DIR / "explanation" / "payload.explanation.json").exists()
    assert (DEBUG_DIR / "payload.visual.json").exists()
    assert (DEBUG_DIR / "lesson-ir.json").exists()
    assert (DEBUG_DIR / "visual-step-ir.before-optimization.json").exists()
    assert (DEBUG_DIR / "visual-step-ir.after-optimization.json").exists()
    assert (DEBUG_DIR / "heping-visual-optimized.html").exists()
    _assert_animation_artifacts(DEBUG_DIR, "heping-visual-optimized.html")


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HEPING_VISUAL,
    reason="DeepSeek Heping visual optimizer integration is opt-in",
)
def test_deepseek_visual_optimizer_with_recorded_lesson_ir_fixture() -> None:
    """Visual-only 链路：读取 recorded LessonIR fixture，只调用一次 DeepSeek 优化视觉。"""
    _reset_debug_dir(RECORDED_LESSON_DEBUG_DIR)
    snapshot = _solve_heping_snapshot()
    lesson = _load_recorded_heping_lesson_ir()

    LessonIRValidator().validate(lesson, snapshot)
    assert len(lesson.steps) == 8

    _optimize_and_write_visual_page(
        snapshot=snapshot,
        lesson=lesson,
        debug_dir=RECORDED_LESSON_DEBUG_DIR,
        html_name="heping-visual-recorded-lesson.html",
    )

    assert not (RECORDED_LESSON_DEBUG_DIR / "explanation").exists()
    assert (RECORDED_LESSON_DEBUG_DIR / "lesson-ir.json").exists()
    assert (RECORDED_LESSON_DEBUG_DIR / "payload.visual.json").exists()
    assert (RECORDED_LESSON_DEBUG_DIR / "heping-visual-recorded-lesson.html").exists()
    _assert_animation_artifacts(RECORDED_LESSON_DEBUG_DIR, "heping-visual-recorded-lesson.html")


def _build_heping_vs1_visual_ir():
    snapshot = _solve_heping_snapshot()
    lesson = ExplanationBuilder().build_lesson(snapshot)
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    return visual_ir, lesson, snapshot


def _solve_heping_snapshot():
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    result = orchestrator.solve(load_problem_ir(HEPING_FIXTURE))
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def _build_heping_lesson_with_deepseek(snapshot: ExplanationSnapshot, debug_dir: Path) -> LessonIR:
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
    )
    explanation_debug_dir = debug_dir / "explanation"
    planner = LLMLessonPlanner(
        client=config.build_llm_client(),
        debug_dir=explanation_debug_dir,
        allow_same_problem_few_shot=False,
    )
    lesson = ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)
    assert planner.last_prompt is not None
    write_explanation_debug_artifacts(
        explanation_debug_dir,
        payload=planner.last_payload or {},
        prompt=planner.last_prompt,
        raw_response=planner.last_raw_response or "",
        parsed=planner.last_parsed,
        lesson=lesson,
    )
    _write_json(debug_dir / "lesson-ir.json", lesson.to_payload())
    return lesson


def _load_recorded_heping_lesson_ir() -> LessonIR:
    payload = json.loads(HEPING_RECORDED_LESSON_IR.read_text(encoding="utf-8"))
    return lesson_ir_from_payload(payload)


def _build_visual_ir_from_lesson(*, snapshot: ExplanationSnapshot, lesson: LessonIR):
    return VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)


def _optimize_and_write_visual_page(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    debug_dir: Path,
    html_name: str,
) -> None:
    visual_ir = _build_visual_ir_from_lesson(snapshot=snapshot, lesson=lesson)
    _write_json(debug_dir / "lesson-ir.json", lesson.to_payload())
    _write_json(debug_dir / "visual-step-ir.before-optimization.json", visual_ir.to_payload())
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
    )
    optimizer = LLMVisualStepOptimizer(
        client=config.build_llm_client(),
        debug_dir=debug_dir,
    )
    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)
    VisualStepIRValidator().validate(optimized)
    _write_json(debug_dir / "visual-step-ir.after-optimization.json", optimized.to_payload())
    compiled = forward_compile(optimized)
    lesson_data = copy.deepcopy(compiled.lesson_data)
    lesson_data["meta"]["outputPath"] = str(debug_dir / html_name)
    _write_compiled_artifacts(
        debug_dir,
        geometry_spec=compiled.geometry_spec,
        step_decorations=compiled.step_decorations,
        lesson_data=lesson_data,
    )
    subprocess.run(
        ["node", str(ROOT / "tools/validate-geometry-spec.mjs"), str(debug_dir)],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["node", str(ROOT / "tools/build-lesson-page.mjs"), str(debug_dir)],
        cwd=ROOT,
        check=True,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _assert_animation_artifacts(debug_dir: Path, html_name: str) -> None:
    lesson_data = json.loads((debug_dir / "lesson-data.json").read_text(encoding="utf-8"))
    animated_steps = [
        step for step in lesson_data.get("steps") or ()
        if isinstance(step.get("animation"), dict)
        and step["animation"].get("mode") == "manual_then_interactive"
        and step["animation"].get("beats")
    ]
    html = (debug_dir / html_name).read_text(encoding="utf-8")
    runtime_js = (ROOT / "site/assets/js/lesson-page-runtime.js").read_text(encoding="utf-8")
    geometry_js = (ROOT / "site/assets/js/geometry-lesson-from-spec.js").read_text(encoding="utf-8")
    runtime_css = (ROOT / "site/assets/css/interactive-geometry-page.css").read_text(encoding="utf-8")

    assert len(animated_steps) >= 2
    assert all("frames" not in step["animation"] for step in animated_steps)
    assert any(
        any((beat.get("transition") or {}).get("local_vars") for beat in step["animation"]["beats"])
        for step in animated_steps
    )
    assert any(step.get("localControls") for step in lesson_data.get("steps") or ())
    assert '"animation"' in html
    assert "diagramMarkupForFrame" in html
    assert "step-animation-button" in runtime_js
    assert "lessonAnimationModal" in runtime_js
    assert "cumulativeAnimationDerive" in runtime_js
    assert "derive.scrollTop = derive.scrollHeight" in runtime_js
    assert "lessonAnimationTitle" not in runtime_js
    assert "lesson-animation-caption" not in runtime_js
    assert "cumulativeAnimationBeat" in runtime_js
    assert "patch.replace_add && beatIndex === 0" in runtime_js
    assert "lockAnimationPageScroll" in runtime_js
    assert "unlockAnimationPageScroll" in runtime_js
    assert "itemMatchesHideRef" in geometry_js
    assert 'modal.addEventListener("wheel"' in runtime_js
    assert "{ passive: false }" in runtime_js
    assert 'esc(content)' in runtime_js
    assert '"</span><p>"' not in runtime_js
    assert ".animation-derive-line span" in runtime_css
    assert "display: flex;" in runtime_css
    assert "align-self: stretch;" in runtime_css
    assert "grid-template-rows: minmax(0, 1fr)" in runtime_css
    assert "min-height: 420px" in runtime_css


def _count_segment_label(payload: dict[str, Any], from_id: str, to_id: str, label: str) -> int:
    return sum(
        1
        for item in payload.get("add", ())
        if isinstance(item, dict)
        and item.get("type") == "segment"
        and item.get("from") == from_id
        and item.get("to") == to_id
        and item.get("label") == label
    )


def _visual_step_for_substep(visual_ir, lesson, substep_id: str):
    lesson_step = next(
        step for step in lesson.steps if substep_id in step.teaching_substep_ids
    )
    return next(step for step in visual_ir.steps if step.lesson_step_id == lesson_step.id)


def _visual_step_for_capability(visual_ir, lesson, capability_id: str):
    lesson_step = next(
        step for step in lesson.steps if capability_id in step.capability_ids
    )
    return next(step for step in visual_ir.steps if step.lesson_step_id == lesson_step.id)


def _visual_step_for_scope_and_capability(visual_ir, lesson, *, scope_id: str, capability_id: str):
    lesson_step = next(
        step
        for step in lesson.steps
        if step.scope_id == scope_id and capability_id in step.capability_ids
    )
    return next(step for step in visual_ir.steps if step.lesson_step_id == lesson_step.id)


def _write_compiled_artifacts(
    path: Path,
    *,
    geometry_spec: dict,
    step_decorations: dict,
    lesson_data: dict,
) -> None:
    (path / "geometry-spec.json").write_text(
        json.dumps(geometry_spec, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / "step-decorations.json").write_text(
        json.dumps(step_decorations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / "lesson-data.json").write_text(
        json.dumps(lesson_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _refs(items: list[dict]) -> set[str]:
    refs: set[str] = set()
    for item in items:
        for key in ("at", "from", "to", "vertex", "rayA", "rayB"):
            value = item.get(key)
            if isinstance(value, str):
                refs.add(value)
        for triangle in item.get("triangles") or ():
            if isinstance(triangle, dict):
                refs.update(str(ref) for ref in triangle.get("vertices") or () if ref)
        for segment in item.get("segments") or ():
            if isinstance(segment, dict):
                for key in ("from", "to"):
                    value = segment.get(key)
                    if isinstance(value, str):
                        refs.add(value)
    return refs


def _reset_debug_dir(path: Path) -> None:
    if path.exists():
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


class _FakeVisualOptimizationClient:
    provider_name = "fake-visual"
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        self.calls += 1
        return json.dumps(
            {
                "visual_step_patches": [
                    {
                        "lesson_step_id": "explain_reduce_ii_equal_length_ray_path_minimum_by_segment",
                        "append_add": [
                            {
                                "component": "DistanceMarker",
                                "from": "O",
                                "to": "G",
                                "label": "OG_min",
                                "color": "#b45309",
                                "width": 3,
                                "offsetPx": 24,
                            }
                        ],
                        "focus": {"primary": ["point:O", "point:G"], "dim": []},
                    }
                ]
            },
            ensure_ascii=False,
        )


class _BadVisualOptimizationClient:
    provider_name = "fake-visual"
    model = "fake"

    def __init__(self) -> None:
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        return json.dumps(
            {
                "visual_step_patches": [
                    {
                        "lesson_step_id": "explain_reduce_ii_equal_length_ray_path_minimum_by_segment",
                        "append_add": [
                            {
                                "component": "Point",
                                "at": "UnknownPoint",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )


class _UnsafeCoordinateLabelClient:
    provider_name = "fake-visual"
    model = "fake"

    def __init__(self) -> None:
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        return json.dumps(
            {
                "visual_step_patches": [
                    {
                        "lesson_step_id": "explain_derive_i_2_F_coordinate",
                        "append_add": [
                            {
                                "component": "CoordinateLabel",
                                "at": "F1",
                                "text": "F(0, 1)",
                            }
                        ],
                        "focus": {"primary": ["point:B1", "point:F1"], "dim": []},
                    }
                ]
            },
            ensure_ascii=False,
        )


class _ChineseVisualLabelClient:
    provider_name = "fake-visual"
    model = "fake"

    def __init__(self) -> None:
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        return json.dumps(
            {
                "visual_step_patches": [
                    {
                        "lesson_step_id": "explain_reduce_ii_equal_length_ray_path_minimum_by_segment",
                        "append_add": [
                            {
                                "component": "DistanceMarker",
                                "from": "O",
                                "to": "G",
                                "label": "关键最短线段",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )


class _FuturePointInAngleStepClient:
    provider_name = "fake-visual"
    model = "fake"

    def __init__(self) -> None:
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        return json.dumps(
            {
                "visual_step_patches": [
                    {
                        "lesson_step_id": "step_2",
                        "append_add": [
                            {
                                "component": "Point",
                                "at": "F1",
                                "labelText": "F",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )


class _InteractionMutationClient:
    provider_name = "fake-visual"
    model = "fake"

    def __init__(self) -> None:
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        return json.dumps(
            {
                "visual_step_patches": [
                    {
                        "lesson_step_id": "explain_reduce_ii_equal_length_ray_path_path_reduction",
                        "interactions": [],
                    }
                ]
            },
            ensure_ascii=False,
        )


class _TimelineMutationClient:
    provider_name = "fake-visual"
    model = "fake"

    def __init__(self) -> None:
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        return json.dumps(
            {
                "visual_step_patches": [
                    {
                        "lesson_step_id": "explain_reduce_ii_equal_length_ray_path_path_reduction",
                        "timeline": {"mode": "none"},
                    }
                ]
            },
            ensure_ascii=False,
        )
