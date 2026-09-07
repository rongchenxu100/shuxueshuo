from __future__ import annotations

import copy
import inspect
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import pytest
import sympy as sp

from _problem_planning_support import cached_planning_binding_fixture

from shuxueshuo_server.solver.explanation import (
    ExplanationSnapshotBuilder,
    LessonAuthoringPipeline,
    LessonIR,
)
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.visual import (
    GeometrySpecBuilder,
    VisualFrame,
    VisualStepBuilder,
    VisualStepIRValidator,
    forward_compile,
)
from shuxueshuo_server.solver.visual import animation as visual_animation
from shuxueshuo_server.solver.visual import builder as visual_builder
from shuxueshuo_server.solver.visual import parametric as visual_parametric
from shuxueshuo_server.solver.visual import role_binders as visual_role_binders
from shuxueshuo_server.solver.visual.geometry_naming import scope_root
from shuxueshuo_server.solver.visual.role_binders import VisualRoleBinderRegistry
from shuxueshuo_server.solver.visual.sympy_helpers import sympy_pair


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class HepingYimoPage:
    snapshot: ExplanationSnapshot
    lesson: LessonIR
    visual_ir: Any
    compiled: Any


@pytest.fixture(scope="module")
def heping_yimo_page() -> HepingYimoPage:
    snapshot = _solve_heping_snapshot()
    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir, lesson=lesson)
    return HepingYimoPage(
        snapshot=snapshot,
        lesson=lesson,
        visual_ir=visual_ir,
        compiled=forward_compile(visual_ir),
    )


def test_visual_sympy_pair_uses_shared_axis_parameter_and_power_normalization() -> None:
    pair = sympy_pair(
        ["_axis_param_i^2 + abs(x)", "y*y + sqrt(4)"],
        axis_parameter_alias="u",
    )
    assert pair is not None
    assert sp.simplify(pair[0] - (sp.Symbol("u") ** 2 + sp.Abs(sp.Symbol("x")))) == 0
    assert sp.simplify(pair[1] - (sp.Symbol("y") ** 2 + 2)) == 0
    assert "sp.sympify" not in inspect.getsource(visual_builder._sympy_pair_value)
    assert "sp.sympify" not in inspect.getsource(visual_role_binders._sympy_pair)
    assert "sp.sympify" not in inspect.getsource(visual_parametric._sympy_pair)


def test_visual_specs_dispatch_only_through_component_registries() -> None:
    methods = MethodSpecRegistry.load_from_code()
    recipes = RecipeSpecRegistry.load_from_code()
    method_components = {
        str(template.get("component") or "")
        for spec in methods.specs.values()
        if spec.visual is not None
        for template in spec.visual.scene_templates
    }
    recipe_components = {
        str(template.get("component") or "")
        for spec in recipes.specs.values()
        if spec.visual is not None
        for templates in spec.visual.teaching_substep_templates.values()
        for template in templates
    }

    assert method_components <= set(visual_builder._METHOD_VISUAL_TEMPLATE_RENDERERS)
    assert recipe_components <= set(visual_builder._RECIPE_VISUAL_TEMPLATE_RENDERERS)
    assert "CurvePointCandidateMarker" in visual_builder._METHOD_VISUAL_TEMPLATE_RENDERERS
    assert "AtomicPathMinimumMarker" in visual_builder._RECIPE_VISUAL_TEMPLATE_RENDERERS
    assert "BrokenPathStraighteningMarker" not in visual_builder._RECIPE_VISUAL_TEMPLATE_RENDERERS
    for recipe_id in (
        "equal_length_ray_path_reduction",
        "quadratic_square_path_minimum",
        "coupled_segment_endpoint_replacement_path_minimum",
        "weighted_axis_path_minimum",
    ):
        assert recipes.specs[recipe_id].visual is not None


def test_visual_v2_has_no_public_flat_or_second_llm_api() -> None:
    import shuxueshuo_server.solver.visual as visual

    assert not hasattr(visual, "LLMVisualStepOptimizer")
    assert not hasattr(visual, "BaseSceneBuilder")
    assert not hasattr(visual, "resolved_steps_with_carry_forward")
    assert "rgba(" not in inspect.getsource(visual_builder)
    assert "rgba(" not in inspect.getsource(visual_animation)


def test_scope_root_keeps_later_roman_questions_distinct() -> None:
    assert scope_root("i_2") == "i"
    assert scope_root("ii_3") == "ii"
    assert scope_root("iii_1") == "iii"
    assert scope_root("iv") == "iv"


def test_parametric_control_label_without_roles_is_generic() -> None:
    assert (
        visual_parametric._control_label(
            {}, moving_role="moving", anchor_role="anchor", endpoint_role="endpoint"
        )
        == "动点参数"
    )


def test_visual_step_builder_mirrors_recursive_lesson_topology(
    heping_yimo_page: HepingYimoPage,
) -> None:
    page = heping_yimo_page
    traversal = page.visual_ir.traversal

    assert page.visual_ir.schema_version == "visual-step-ir/v2"
    assert page.visual_ir.metadata["scene_model"] == "recursive_complete_frames"
    assert list(traversal.scope_by_ref) == ["problem", "i", "i_1", "i_2", "ii"]
    assert list(traversal.goal_by_ref) == ["i_1.parabola", "i_2.E", "ii.a"]
    assert len(page.visual_ir.steps) == len(page.lesson.steps) == 12
    assert [item.lesson_step_id for item in page.visual_ir.steps] == [
        item.id for item in page.lesson.steps
    ]
    assert all(item.frames for item in page.visual_ir.steps)
    assert not any(
        obj.component == "VisualGap"
        for step in page.visual_ir.steps
        for frame in step.frames
        for obj in frame.objects
    )


def test_geometry_registry_has_scope_safe_problem_and_branch_objects(
    heping_yimo_page: HepingYimoPage,
) -> None:
    geometry = heping_yimo_page.visual_ir.geometry_registry

    assert geometry["fixedPoints"]["point_A_problem"] == ["-1", "0"]
    assert geometry["fixedPoints"]["point_C_problem"] == ["0", "-3"]
    assert geometry["fixedPoints"]["point_D_problem"] == ["2", "-3"]
    assert geometry["fixedPoints"]["point_B_i_2"] == ["3", "0"]
    assert geometry["movingPoints"]["point_B_ii"] == ["3/a", "0"]
    assert geometry["pointMeta"]["point_B_i_2"]["scopeRoot"] == "i"
    assert geometry["pointMeta"]["point_B_ii"]["scopeRoot"] == "ii"
    assert geometry["pointMeta"]["point_B_i_2"]["label"] == "B"
    assert geometry["pointMeta"]["point_B_ii"]["label"] == "B"
    curve_roots = {curve["scopeRoot"] for curve in geometry["curves"]}
    assert curve_roots == {"i", "ii"}


def test_equal_length_auxiliaries_are_runtime_bound_and_branch_scoped(
    heping_yimo_page: HepingYimoPage,
) -> None:
    geometry = heping_yimo_page.visual_ir.geometry_registry

    assert geometry["movingPoints"]["point_M_ii"] == ["3*u/a", "3*u-3"]
    assert geometry["movingPoints"]["point_N_ii"] == [
        "3*u*sqrt((a*a)+1)/abs(a)",
        "-3",
    ]
    assert geometry["pointMeta"]["point_M_ii"]["label"] == "M"
    assert geometry["pointMeta"]["point_N_ii"]["label"] == "N"
    assert geometry["pointMeta"]["point_M_ii"]["sourceStepIds"] == [
        "reduce_equal_length_ray_path_ii"
    ]
    serialized = json.dumps(heping_yimo_page.visual_ir.to_payload(), ensure_ascii=False)
    assert "equal_length_auxiliary_point" not in serialized
    assert "runtime:" not in serialized


def test_equal_length_units_have_distinct_complete_frames(
    heping_yimo_page: HepingYimoPage,
) -> None:
    path = _frame_for_unit(heping_yimo_page, "path_reduction")
    minimum = _frame_for_unit(heping_yimo_page, "minimum_by_segment")

    assert {"point_B_ii", "point_C_problem", "point_G_ii", "point_M_ii", "point_N_ii"} <= _refs(path)
    assert {"O", "point_M_ii", "point_G_ii"} <= _refs(minimum)
    assert "point_B_i_2" not in _refs(path)
    assert "point_B_i_2" not in _refs(minimum)
    assert {item["name"] for item in path.local_parameters} == {"a", "u"}
    assert {item["name"] for item in minimum.local_parameters} == {"a", "u"}
    assert any(obj.component == "CongruentTriangleMarker" for obj in path.objects)
    assert any(obj.component == "EquivalentSegmentMarker" for obj in path.objects)
    assert any(obj.component == "OutlineRegion" for obj in minimum.objects)


def test_equal_length_parameter_default_preserves_constructed_geometry(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(heping_yimo_page, "path_reduction")
    geometry = heping_yimo_page.visual_ir.geometry_registry
    environment = {
        str(item["name"]): sp.sympify(str(item["default_value"]))
        for item in frame.local_parameters
    }
    b = _point_pair(geometry, "point_B_ii", environment)
    c = _point_pair(geometry, "point_C_problem", environment)
    g = _point_pair(geometry, "point_G_ii", environment)
    m = _point_pair(geometry, "point_M_ii", environment)
    n = _point_pair(geometry, "point_N_ii", environment)

    assert sp.simplify(_distance(c, g) - _distance(c, b)) == 0
    assert sp.simplify(_distance(c, n) - _distance(c, m)) == 0


def test_recursive_branch_state_does_not_backflow_between_parts(
    heping_yimo_page: HepingYimoPage,
) -> None:
    authority = heping_yimo_page.visual_ir.state_authority
    part_i = authority["containers"]["scope:i"]
    part_ii = authority["containers"]["scope:ii"]
    serialized_ii = json.dumps(part_ii, ensure_ascii=False)

    assert part_i["available_before"] == part_ii["available_before"]
    assert "point_B_i_2" not in serialized_ii
    assert "point_E_i_2" not in serialized_ii
    assert "point_F_i_2" not in serialized_ii


def test_timeline_geometry_is_declared_by_its_own_complete_frame(
    heping_yimo_page: HepingYimoPage,
) -> None:
    known = _known_geometry(heping_yimo_page.visual_ir.geometry_registry)
    for step in heping_yimo_page.visual_ir.steps:
        for frame in step.frames:
            if frame.timeline is None:
                continue
            timeline_refs = _timeline_refs(frame.timeline, known)
            assert timeline_refs <= _refs(frame), (
                frame.frame_id,
                sorted(timeline_refs - _refs(frame)),
            )


def test_timeline_student_labels_do_not_expose_geometry_ids(
    heping_yimo_page: HepingYimoPage,
) -> None:
    for step in heping_yimo_page.visual_ir.steps:
        for frame in step.frames:
            if frame.timeline is None:
                continue
            for text in _text_values(frame.timeline):
                assert not re.search(r"(?:point_|_axis_|_problem|_i_2|_ii)", text)


def test_translated_point_uses_declared_visual_component(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(heping_yimo_page, "derive_translated_D_i")
    marker = next(obj for obj in frame.objects if obj.component == "TranslationMarker")
    assert marker.geometry_refs == ("point_C_problem", "point_D_problem")
    assert marker.component_payload["vector"] == ["2", "0"]
    assert marker.component_payload["label"] == "+2"


def test_angle_step_never_imports_future_intersection_point(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(heping_yimo_page, "derive_equal_angle_i")
    assert "point_F_i_2" not in _refs(frame)


def test_role_binder_resolves_same_label_by_current_branch(
    heping_yimo_page: HepingYimoPage,
) -> None:
    binder = VisualRoleBinderRegistry.default(
        heping_yimo_page.visual_ir.geometry_registry,
        heping_yimo_page.snapshot.problem,
    )
    assert binder.geometry_point_name("B", "i_2") == "point_B_i_2"
    assert binder.geometry_point_name("B", "ii") == "point_B_ii"
    assert binder.geometry_point_name("O", "ii") == "O"


def test_compiler_uses_only_frame_local_scene_payloads(
    heping_yimo_page: HepingYimoPage,
) -> None:
    decorations = heping_yimo_page.compiled.step_decorations
    assert set(decorations) == {"steps"}
    assert "layers" not in decorations
    for raw in decorations["steps"].values():
        assert set(raw) == {"visualMode", "visualFrames"}
        assert raw["visualFrames"]
        for frame in raw["visualFrames"]:
            assert frame["add"][0] == {"type": "grid"}
            assert "hide" not in frame
            assert "hideLayers" not in frame
            assert "inherits_from" not in frame


def test_generated_page_compiles_from_recursive_visual_ir(
    heping_yimo_page: HepingYimoPage,
    tmp_path: Path,
) -> None:
    lesson_data = copy.deepcopy(heping_yimo_page.compiled.lesson_data)
    output = tmp_path / "heping-yimo-b4v.html"
    lesson_data["meta"]["outputPath"] = str(output)
    _write_json(tmp_path / "geometry-spec.json", heping_yimo_page.compiled.geometry_spec)
    _write_json(tmp_path / "step-decorations.json", heping_yimo_page.compiled.step_decorations)
    _write_json(tmp_path / "lesson-data.json", lesson_data)

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
    html = output.read_text(encoding="utf-8")
    assert "visualFrames" in html
    assert "第（二）问" in html or "第（Ⅱ）问" in html


def test_compiled_visual_labels_are_mathematical_not_internal_or_prose(
    heping_yimo_page: HepingYimoPage,
) -> None:
    texts: list[str] = []
    for raw in heping_yimo_page.compiled.step_decorations["steps"].values():
        for frame in raw["visualFrames"]:
            for item in frame["add"]:
                for key in ("label", "labelText", "text"):
                    if isinstance(item.get(key), str):
                        texts.append(item[key])
    assert texts
    assert not any(re.search(r"(?:point_|_axis_|_problem|_i_2|_ii)", text) for text in texts)
    assert not any(re.search(r"[一-鿿]", text) for text in texts)


def _frame_for_source(page: HepingYimoPage, source_step_id: str) -> VisualFrame:
    lesson_step = next(
        item for item in page.lesson.steps if source_step_id in item.source_step_ids
    )
    visual_step = next(
        item for item in page.visual_ir.steps if item.lesson_step_id == lesson_step.id
    )
    assert len(visual_step.frames) == 1
    return visual_step.frames[0]


def _frame_for_unit(page: HepingYimoPage, unit_tail: str) -> VisualFrame:
    matches = [
        frame
        for step in page.visual_ir.steps
        for frame in step.frames
        if any(key.rsplit("/", 1)[-1] == unit_tail for key in frame.teaching_unit_keys)
    ]
    assert len(matches) == 1
    return matches[0]


def _refs(frame: VisualFrame) -> set[str]:
    return {ref for obj in frame.objects for ref in obj.geometry_refs}


def _known_geometry(geometry: Mapping[str, Any]) -> set[str]:
    return {
        *map(str, (geometry.get("fixedPoints") or {}).keys()),
        *map(str, (geometry.get("movingPoints") or {}).keys()),
        *(
            str(curve["id"])
            for curve in geometry.get("curves") or ()
            if isinstance(curve, dict) and curve.get("id")
        ),
    }


def _timeline_refs(value: Any, known: set[str]) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in {
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
            } and str(nested or "") in known:
                refs.add(str(nested))
            refs.update(_timeline_refs(nested, known))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            if str(nested) in known:
                refs.add(str(nested))
            refs.update(_timeline_refs(nested, known))
    return refs


def _text_values(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in {"caption", "label", "labelText", "text"} and isinstance(nested, str):
                result.append(nested)
            result.extend(_text_values(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            result.extend(_text_values(nested))
    return result


def _point_pair(
    geometry: Mapping[str, Any],
    point_id: str,
    environment: Mapping[str, sp.Expr],
) -> tuple[sp.Expr, sp.Expr]:
    raw = (geometry.get("fixedPoints") or {}).get(point_id)
    if raw is None:
        raw = (geometry.get("movingPoints") or {}).get(point_id)
    assert isinstance(raw, list) and len(raw) == 2
    substitutions = {sp.Symbol(name): value for name, value in environment.items()}
    return tuple(sp.simplify(sp.sympify(str(value)).subs(substitutions)) for value in raw)  # type: ignore[return-value]


def _distance(left: tuple[sp.Expr, sp.Expr], right: tuple[sp.Expr, sp.Expr]) -> sp.Expr:
    return sp.sqrt((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2)


@cache
def _solve_heping_snapshot() -> ExplanationSnapshot:
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture("tj-2026-heping-yimo-25")
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
