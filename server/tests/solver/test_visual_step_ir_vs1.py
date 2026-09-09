from __future__ import annotations

import copy
import inspect
import json
from dataclasses import dataclass, replace
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
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingScope,
    TeachingSource,
)
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
from shuxueshuo_server.solver.visual.parameter_identity import (
    parameterized_point_contexts_by_step,
)
from shuxueshuo_server.solver.visual.role_binders import (
    VisualRoleBinderRegistry,
    VisualRoleBindings,
)
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


@pytest.fixture(scope="module")
def hexi_yimo_page() -> HepingYimoPage:
    snapshot = _solve_hexi_snapshot()
    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir, lesson=lesson)
    return HepingYimoPage(
        snapshot=snapshot,
        lesson=lesson,
        visual_ir=visual_ir,
        compiled=forward_compile(visual_ir),
    )


@pytest.fixture(scope="module")
def xiqing_yimo_page() -> HepingYimoPage:
    snapshot = _solve_xiqing_snapshot()
    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir, lesson=lesson)
    return HepingYimoPage(
        snapshot=snapshot,
        lesson=lesson,
        visual_ir=visual_ir,
        compiled=forward_compile(visual_ir),
    )


@pytest.fixture(scope="module")
def nankai_yimo_page() -> HepingYimoPage:
    snapshot = _solve_nankai_snapshot()
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
    assert "LineParabolaIntersectionMarker" in visual_builder._METHOD_VISUAL_TEMPLATE_RENDERERS
    assert "AtomicPathMinimumMarker" in visual_builder._RECIPE_VISUAL_TEMPLATE_RENDERERS
    assert "BrokenPathStraighteningMarker" not in visual_builder._RECIPE_VISUAL_TEMPLATE_RENDERERS
    for recipe_id in (
        "equal_length_ray_path_reduction",
        "quadratic_square_path_minimum",
        "coupled_segment_endpoint_replacement_path_minimum",
        "weighted_axis_path_minimum",
    ):
        assert recipes.specs[recipe_id].visual is not None


@pytest.mark.parametrize(
    ("constraint", "expected_domain", "expected_min", "expected_max"),
    (
        (
            {"operator": ">", "value": "0"},
            {"kind": "inequality", "expression": "u>0"},
            0.1,
            4.0,
        ),
        (
            {"operator": "<=", "value": "2"},
            {"kind": "inequality", "expression": "u<=2"},
            -4.0,
            2.0,
        ),
    ),
)
def test_weighted_axis_slider_window_respects_verified_dynamic_constraint(
    constraint,
    expected_domain,
    expected_min,
    expected_max,
) -> None:
    constrained = visual_parametric._constraint_domain_and_window(
        parameter_name="u",
        constraint=constraint,
        viewport_min=-4.0,
        viewport_max=4.0,
        step=0.1,
    )

    assert constrained is not None
    mathematical_domain, minimum, maximum, default = constrained
    assert mathematical_domain == expected_domain
    assert minimum == pytest.approx(expected_min)
    assert maximum == pytest.approx(expected_max)
    assert minimum <= default <= maximum


def test_weighted_axis_slider_rejects_unresolved_symbolic_constraint() -> None:
    assert (
        visual_parametric._constraint_domain_and_window(
            parameter_name="u",
            constraint={"operator": ">", "value": "b"},
            viewport_min=-4.0,
            viewport_max=4.0,
            step=0.1,
        )
        is None
    )


def test_visual_context_is_spec_driven_not_capability_switched() -> None:
    source = inspect.getsource(visual_builder._visual_context_for_step)

    for capability_id in (
        "quadratic_vertex_point",
        "square_adjacent_vertex_from_side",
        "evaluate_point_at_parameter",
    ):
        assert capability_id not in source


def test_parameterized_point_identity_is_inferred_from_public_result_types(
    heping_yimo_page: HepingYimoPage,
) -> None:
    producer = TeachingSource(
        source_step_id="produce_moving_point",
        capability_id="renamed_or_new_capability",
        inputs={},
        outputs={
            "parameter": {
                "runtime_type": "Symbol",
                "value": "u",
                "display": "u",
            },
            "point": {
                "runtime_type": "Point",
                "value": ["2*u+1", "u-3"],
                "display": "动点(u)",
            },
        },
    )
    consumer = TeachingSource(
        source_step_id="consume_moving_point",
        capability_id="consumer_capability",
        inputs={
            "point": (
                {
                    "ref": {
                        "kind": "step_result",
                        "step_id": "produce_moving_point",
                        "return": "point",
                    },
                    "runtime_type": "Point",
                    "value": ["2*u+1", "u-3"],
                    "display": "动点(u)",
                },
            )
        },
        outputs={},
    )
    snapshot = replace(
        heping_yimo_page.snapshot,
        root_scope=TeachingScope(
            scope_ref="ii",
            steps=(producer, consumer),
        ),
        evidence={},
        answers={},
    )

    assert parameterized_point_contexts_by_step(snapshot) == {
        "produce_moving_point": frozenset({("ii", "u")}),
        "consume_moving_point": frozenset({("ii", "u")}),
    }


def test_parameter_value_output_inherits_unique_input_parameter_identity() -> None:
    source = TeachingSource(
        source_step_id="solve_parameter",
        capability_id="parameter_from_expression_value",
        inputs={
            "parameter": (
                {
                    "runtime_type": "ParameterValue",
                    "value": "b",
                    "display": "b",
                },
            )
        },
        outputs={
            "parameter_value": {
                "runtime_type": "ParameterValue",
                "value": "2",
                "display": "2",
            }
        },
    )

    assert visual_builder.verified_parameter_values_from_source(source) == {"b": "2"}


def test_dynamic_point_choice_uses_typed_provenance_not_internal_id_text() -> None:
    geometry = {
        "fixedPoints": {},
        "movingPoints": {
            "looks_like_axis_locus": ["u", "0"],
            "semantic_result": ["u", "0"],
        },
        "pointMeta": {
            "looks_like_axis_locus": {
                "label": "动点",
                "scopeId": "ii",
                "scopeRoot": "ii",
                "visualOnly": True,
            },
            "semantic_result": {
                "label": "动点",
                "scopeId": "ii",
                "scopeRoot": "ii",
                "definition": "parameterized_point",
                "semanticRoles": ["path_attainment_point"],
                "sourceStepIds": ["produce_moving_point"],
            },
        },
        "curves": [],
    }
    binder = VisualRoleBinderRegistry.default(geometry, {"entities": [], "facts": []})

    assert (
        binder._dynamic_point_ref_for_label("动点", "ii", "y=0")
        == "semantic_result"
    )


def test_square_context_resolves_non_latin_point_by_exact_source_ref(
    heping_yimo_page: HepingYimoPage,
) -> None:
    problem = copy.deepcopy(heping_yimo_page.snapshot.problem)
    problem["entities"].append(
        {
            "entity_type": "point",
            "handle": "point:problem:交点甲",
            "name": "交点甲",
            "scope_id": "problem",
        }
    )
    snapshot = replace(heping_yimo_page.snapshot, problem=problem)
    source = TeachingSource(
        source_step_id="use_named_point",
        capability_id="synthetic",
        inputs={
            "target": (
                {
                    "ref": {"kind": "source", "ref": "point:problem:交点甲"},
                    "runtime_type": "Point",
                    "value": ["1", "2"],
                    "display": "交点甲(1,2)",
                },
            )
        },
        outputs={},
    )

    assert visual_builder._problem_point_handles_for_input(
        source,
        "target",
        sources={},
        snapshot=snapshot,
        scope_id="i",
    ) == {"point:problem:交点甲"}


def test_goal_answer_output_identity_uses_problem_target_handle(
    heping_yimo_page: HepingYimoPage,
) -> None:
    source = next(
        item
        for item in visual_builder.iter_teaching_sources(
            heping_yimo_page.snapshot.root_scope
        )
        if item.source_step_id == "derive_curve_intersection_E_i"
    )

    assert visual_role_binders._public_point_semantic_ref(
        heping_yimo_page.snapshot,
        source,
        "point",
    ) == "point:i_2:E"


def test_line_parabola_renderer_uses_bound_roles_not_fixed_point_names() -> None:
    template = {
        "persistence": "carry_forward",
        "line_color": "#123456",
        "target_color": "#654321",
    }
    bindings = VisualRoleBindings(
        line_parabola_intersections=(
            {
                "source_step_id": "intersection_step",
                "line_p1": "geometry_alpha",
                "line_p1_label": "交点甲",
                "line_p2": "geometry_beta",
                "line_p2_label": "交点乙",
                "known_point": "geometry_alpha",
                "known_label": "交点甲",
                "target_point": "geometry_gamma",
                "target_label": "交点丙",
                "target_display": "交点丙(3,4)",
            },
        )
    )

    items = visual_builder._line_parabola_intersection_marker_items(
        template,
        bindings,
    )

    assert any(
        item.get("component") == "ColoredLine"
        and item.get("from") == "geometry_alpha"
        and item.get("to") == "geometry_gamma"
        for item in items
    )
    assert any(
        item.get("component") == "CoordinateLabel"
        and item.get("at") == "geometry_gamma"
        and item.get("text") == "交点丙(3,4)"
        for item in items
    )
    renderer_source = inspect.getsource(
        visual_builder._line_parabola_intersection_marker_items
    )
    assert all(token not in renderer_source for token in ('"B"', '"E"', '"F"'))


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


def test_moving_points_keep_their_constraint_carriers_visible(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(heping_yimo_page, "minimum_by_segment")
    carrier_by_role = {
        obj.role: set(obj.geometry_refs)
        for obj in frame.objects
        if obj.role.startswith("motion_carrier:")
    }

    assert carrier_by_role["motion_carrier:segment:point_M_ii"] == {
        "point_C_problem",
        "point_B_ii",
    }
    assert carrier_by_role["motion_carrier:ray:point_N_ii"] == {
        "point_C_problem",
        "point_G_ii",
    }


def test_equal_length_construction_viewport_uses_slider_bounds_not_render_window(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(heping_yimo_page, "path_reduction")

    assert frame.viewport["maxX"] - frame.viewport["minX"] < 10
    assert frame.viewport["maxY"] - frame.viewport["minY"] < 10


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


def test_minimum_frame_defaults_to_attainment_and_calculation_step_keeps_it(
    heping_yimo_page: HepingYimoPage,
) -> None:
    minimum = _frame_for_unit(heping_yimo_page, "minimum_by_segment")
    calculation = _frame_for_source(
        heping_yimo_page,
        "solve_parameter_from_minimum_ii",
    )
    minimum_parameters = {item["name"]: item for item in minimum.local_parameters}
    calculation_parameters = {
        item["name"]: item for item in calculation.local_parameters
    }

    assert minimum_parameters["u"]["mathematical_domain"] == {
        "kind": "closed_interval",
        "min": 0,
        "max": 1,
    }
    assert 0 < minimum_parameters["u"]["default_value"] < 1
    assert (
        calculation_parameters["u"]["default_value"]
        == minimum_parameters["u"]["default_value"]
    )
    assert calculation_parameters["u"]["controls"] == []

    environment = {
        str(item["name"]): sp.sympify(str(item["default_value"]))
        for item in minimum.local_parameters
    }
    origin = _point_pair(
        heping_yimo_page.visual_ir.geometry_registry,
        "O",
        environment,
    )
    moving = _point_pair(
        heping_yimo_page.visual_ir.geometry_registry,
        "point_M_ii",
        environment,
    )
    auxiliary = _point_pair(
        heping_yimo_page.visual_ir.geometry_registry,
        "point_G_ii",
        environment,
    )
    collinearity_error = sp.N(
        (moving[0] - origin[0]) * (auxiliary[1] - origin[1])
        - (moving[1] - origin[1]) * (auxiliary[0] - origin[0])
    )
    assert abs(float(collinearity_error)) < 1e-5


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


def test_angle_step_closes_reference_triangle_without_revealing_future_coordinate(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(heping_yimo_page, "derive_equal_angle_i")
    reference_triangle = next(
        obj
        for obj in frame.objects
        if obj.component == "OutlineRegion"
        and set(obj.component_payload.get("vertices") or ())
        == {"point_C_problem", "point_B_i_2", "O"}
    )

    assert reference_triangle.state == "context"
    assert any(
        obj.component == "Point" and obj.geometry_refs == ("point_E_i_2",)
        for obj in frame.objects
    )
    assert not any(
        obj.component == "CoordinateLabel"
        and obj.geometry_refs == ("point_E_i_2",)
        for obj in frame.objects
    )


def test_chained_angle_equality_exposes_transitive_triangle_pair() -> None:
    assert visual_role_binders._angle_equalities_from_texts(
        ["∠OBF＝∠OBE＝∠ACO"]
    ) == [
        ("OBF", "OBE"),
        ("OBE", "ACO"),
        ("OBF", "ACO"),
    ]
    assert visual_role_binders._select_axis_intercept_equality(
        [("OBF", "OBE"), ("OBE", "ACO"), ("OBF", "ACO")],
        result_label="F",
    ) == ("OBF", "ACO")


def test_axis_intercept_step_focuses_new_point_and_keeps_future_coordinate_hidden(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(heping_yimo_page, "derive_axis_intercept_F_i")

    assert any(
        obj.component == "EqualAcuteAngleInterceptMarker"
        for obj in frame.objects
    )
    assert any(
        obj.component == "Point"
        and obj.geometry_refs == ("point_F_i_2",)
        and obj.state == "focus"
        for obj in frame.objects
    )
    assert any(
        obj.component == "CoordinateLabel"
        and obj.geometry_refs == ("point_F_i_2",)
        and str(obj.display_label).replace(" ", "") == "F(0,－1)"
        for obj in frame.objects
    )
    assert not any(
        obj.component == "CoordinateLabel"
        and obj.geometry_refs == ("point_E_i_2",)
        for obj in frame.objects
    )


def test_carried_angle_never_outlives_its_supporting_sides(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(heping_yimo_page, "derive_axis_intercept_F_i")
    angle = next(obj for obj in frame.objects if obj.component == "AngleArc")
    vertex = str(angle.component_payload["vertex"])
    rays = {
        str(angle.component_payload["rayA"]),
        str(angle.component_payload["rayB"]),
    }
    rendered_edges = {
        frozenset(obj.geometry_refs)
        for obj in frame.objects
        if obj.component in {"ColoredLine", "DashedLine", "DistanceMarker"}
        and len(obj.geometry_refs) == 2
    }

    assert {frozenset((vertex, ray)) for ray in rays} <= rendered_edges


def test_line_parabola_intersection_focuses_target_not_construction_point(
    heping_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(heping_yimo_page, "derive_curve_intersection_E_i")
    point_states = {
        ref: obj.state
        for obj in frame.objects
        if obj.component == "Point"
        for ref in obj.geometry_refs
        if ref in {"point_E_i_2", "point_F_i_2"}
    }

    assert point_states == {
        "point_E_i_2": "focus",
        "point_F_i_2": "context",
    }


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


def test_curve_visibility_does_not_leak_a_later_solved_state(
    hexi_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(hexi_yimo_page, "derive_parametric_parabola_ii")
    curve_refs = {
        ref
        for item in frame.objects
        if item.component == "Parabola"
        for ref in item.geometry_refs
    }
    assert curve_refs == {"curve_ii_parabola"}


def test_nankai_quadratic_context_and_vertices_are_visible(
    nankai_yimo_page: HepingYimoPage,
) -> None:
    axis_frame = _frame_for_source(nankai_yimo_page, "i_derive_D")
    axis = next(
        item for item in axis_frame.objects if item.component == "AxisOfSymmetry"
    )
    assert axis.geometry_refs == ()
    assert axis.component_payload["xExpr"] == "1"

    part_i_curve = _frame_for_source(nankai_yimo_page, "i_derive_parabola")
    assert part_i_curve.viewport["minY"] <= -7 <= part_i_curve.viewport["maxY"]

    candidate_frame = _frame_for_unit(
        nankai_yimo_page,
        "construct_candidates",
    )
    assert any(
        item.component == "Parabola"
        and item.geometry_refs == ("curve_ii_parabola",)
        for item in candidate_frame.objects
    )

    part_ii_curve = _frame_for_source(nankai_yimo_page, "ii_derive_parabola")
    environment = {
        str(item["name"]): sp.sympify(str(item["default_value"]))
        for item in part_ii_curve.local_parameters
    }
    expression = _curve_expression(
        nankai_yimo_page.visual_ir.geometry_registry,
        "curve_ii_parabola",
        environment,
    )
    x = sp.Symbol("x")
    coefficient = sp.expand(expression).coeff(x, 2)
    vertex_x = sp.simplify(-sp.expand(expression).coeff(x, 1) / (2 * coefficient))
    vertex_y = sp.simplify(expression.subs(x, vertex_x))
    viewport = part_ii_curve.viewport
    assert viewport["minX"] < float(vertex_x) - 1
    assert viewport["maxX"] > float(vertex_x) + 1
    assert viewport["minY"] <= float(vertex_y) <= viewport["maxY"]


def test_nankai_candidate_construction_visualizes_the_complete_proof(
    nankai_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(nankai_yimo_page, "construct_candidates")
    geometry = nankai_yimo_page.visual_ir.geometry_registry
    labels_by_ref = {
        str(point_id): str(meta.get("label") or "")
        for point_id, meta in geometry["pointMeta"].items()
        if isinstance(meta, dict)
    }
    visible_point_labels = {
        item.display_label
        for item in frame.objects
        if item.component == "Point"
    }
    assert {"D", "M", "U", "V", "W", "N₁", "N₂"} <= visible_point_labels

    right_angles = {
        tuple(labels_by_ref.get(ref, "") for ref in item.geometry_refs)
        for item in frame.objects
        if item.component == "RightAngle"
    }
    assert ("D", "M", "N₁") in right_angles
    assert ("D", "M", "N₂") in right_angles

    dashed_segments = {
        frozenset(labels_by_ref.get(ref, "") for ref in item.geometry_refs)
        for item in frame.objects
        if item.component == "DashedLine"
    }
    assert {
        frozenset(("M", "U")),
        frozenset(("N₁", "V")),
        frozenset(("N₂", "W")),
    } <= dashed_segments

    d_points = [
        item
        for item in frame.objects
        if item.component == "Point" and item.display_label == "D"
    ]
    assert len(d_points) == 1
    assert d_points[0].geometry_refs == ("point_D_problem",)
    assert d_points[0].component_payload.get("showLabel") is False
    assert sum(
        item.component == "CoordinateLabel"
        and item.geometry_refs == ("point_D_problem",)
        for item in frame.objects
    ) == 1


def test_nankai_selected_candidate_replaces_the_candidate_construction(
    nankai_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(nankai_yimo_page, "select_candidate")
    point_labels = [
        item.display_label
        for item in frame.objects
        if item.component == "Point"
    ]

    assert point_labels.count("N") == 1
    assert not {"N₁", "N₂", "U", "V", "W"}.intersection(point_labels)
    assert not any(
        item.role.startswith("candidate_construction:")
        for item in frame.objects
    )
    assert not any(
        item.component in {"RightAngle", "DistanceMarker", "DashedLine"}
        for item in frame.objects
    )
    assert any(
        item.component == "CoordinateLabel"
        and item.geometry_refs == ("point_N_ii",)
        and str(item.display_label).replace(" ", "") == "N(2,1－m)"
        for item in frame.objects
    )


def test_nankai_endpoint_replacement_shows_g_and_its_rectangle_certificate(
    nankai_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(nankai_yimo_page, "endpoint_replacement")
    geometry = nankai_yimo_page.visual_ir.geometry_registry
    labels_by_ref = {
        str(point_id): str(meta.get("label") or "")
        for point_id, meta in geometry["pointMeta"].items()
        if isinstance(meta, dict)
    }
    point_labels = {
        item.display_label
        for item in frame.objects
        if item.component == "Point"
    }

    assert {"D", "M", "N", "E", "G", "K", "H"} <= point_labels
    rectangle = next(
        item for item in frame.objects if item.component == "OutlineRegion"
    )
    assert [labels_by_ref[ref] for ref in rectangle.geometry_refs] == [
        "D",
        "K",
        "G",
        "H",
    ]
    equality = next(
        item
        for item in frame.objects
        if item.component == "EquivalentSegmentMarker"
    )
    assert equality.display_label == "EG=DG"
    assert {
        frozenset((labels_by_ref[segment["from"]], labels_by_ref[segment["to"]]))
        for segment in equality.component_payload["segments"]
    } == {frozenset(("E", "G")), frozenset(("D", "G"))}
    assert {
        labels_by_ref[item.component_payload["vertex"]]
        for item in frame.objects
        if item.component == "RightAngle"
    } == {"K", "H"}

    point_ref_by_label = {
        item.display_label: item.geometry_refs[0]
        for item in frame.objects
        if item.component == "Point" and len(item.geometry_refs) == 1
    }
    assert any(
        item.component == "ColoredLine"
        and set(item.geometry_refs)
        == {point_ref_by_label["F"], point_ref_by_label["G"]}
        for item in frame.objects
    )
    parameters = {
        str(item["name"]): item for item in frame.local_parameters
    }
    motion = parameters["u"]
    assert motion["mathematical_domain"] == {
        "kind": "closed_interval",
        "min": 0.5,
        "max": 1.0,
    }
    assert motion["controls"][0]["label"] == "动点 G（E 联动）"
    assert {
        point_ref_by_label["E"],
        point_ref_by_label["G"],
        point_ref_by_label["K"],
        point_ref_by_label["H"],
    } <= set(motion["parameterized_points"])


def test_nankai_reflection_minimum_shows_the_complete_moving_path(
    nankai_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(nankai_yimo_page, "reflection_minimum")
    geometry = nankai_yimo_page.visual_ir.geometry_registry
    point_ref_by_label = {
        item.display_label: item.geometry_refs[0]
        for item in frame.objects
        if item.component == "Point" and len(item.geometry_refs) == 1
    }

    assert {"D", "D′", "F", "G", "M", "N"} <= set(point_ref_by_label)
    assert sum(
        item.component == "Point" and item.display_label == "D"
        for item in frame.objects
    ) == 1
    expected_segments = {
        frozenset((point_ref_by_label["D"], point_ref_by_label["G"])),
        frozenset((point_ref_by_label["D′"], point_ref_by_label["G"])),
        frozenset((point_ref_by_label["F"], point_ref_by_label["G"])),
        frozenset((point_ref_by_label["D′"], point_ref_by_label["F"])),
    }
    rendered_segments = {
        frozenset(item.geometry_refs)
        for item in frame.objects
        if item.component in {"ColoredLine", "DashedLine"}
        and len(item.geometry_refs) == 2
    }
    assert expected_segments <= rendered_segments
    assert sum(
        item.component in {"ColoredLine", "DashedLine"}
        and frozenset(item.geometry_refs)
        == frozenset((point_ref_by_label["F"], point_ref_by_label["G"]))
        for item in frame.objects
    ) == 1
    stale_construction_g_refs = {
        str(point_id)
        for point_id, meta in geometry["pointMeta"].items()
        if isinstance(meta, dict)
        and meta.get("definition") == "endpoint_replacement_construction"
        and meta.get("constructionRole") == "hypotenuse_moving_point"
    }
    assert not any(
        stale_construction_g_refs.intersection(item.geometry_refs)
        for item in frame.objects
    )
    assert any(
        item.component == "LocusLine"
        and set(item.geometry_refs)
        == {point_ref_by_label["M"], point_ref_by_label["N"]}
        for item in frame.objects
    )
    motion = next(
        item for item in frame.local_parameters if item["name"] == "u"
    )
    assert point_ref_by_label["G"] == "point_G_ii"
    assert motion["controls"][0]["label"] == "动点 G"
    assert motion["default_value"] == pytest.approx(2 / 3, abs=1e-6)
    assert set(motion["parameterized_points"]) == {point_ref_by_label["G"]}

    environment = {"m": sp.Integer(4), "u": sp.Rational(2, 3)}
    moving_expression = motion["parameterized_points"][
        point_ref_by_label["G"]
    ]["expression"]
    point_g = tuple(
        sp.sympify(value).subs(environment) for value in moving_expression
    )
    point_d_prime = _point_pair(geometry, point_ref_by_label["D′"], environment)
    point_f = _point_pair(geometry, point_ref_by_label["F"], environment)
    determinant = sp.simplify(
        (point_g[0] - point_d_prime[0]) * (point_f[1] - point_d_prime[1])
        - (point_g[1] - point_d_prime[1]) * (point_f[0] - point_d_prime[0])
    )
    assert determinant == 0


@pytest.mark.parametrize(
    ("source_step_id", "parameter_value"),
    (
        ("ii_1_solve_m", 3),
        ("ii_1_evaluate_minimum", 3),
        ("ii_1_specialize_parabola", 3),
        ("ii_2_solve_m", 8),
        ("ii_2_evaluate_G", 8),
        ("ii_2_specialize_parabola", 8),
    ),
)
def test_nankai_calculation_steps_freeze_the_path_scene_at_attainment(
    nankai_yimo_page: HepingYimoPage,
    source_step_id: str,
    parameter_value: int,
) -> None:
    frame = _frame_for_source(nankai_yimo_page, source_step_id)
    point_ref_by_label = {
        item.display_label: item.geometry_refs[0]
        for item in frame.objects
        if item.component == "Point" and len(item.geometry_refs) == 1
    }

    assert {"D", "D′", "F", "G", "M", "N"} <= set(point_ref_by_label)
    expected_segments = {
        frozenset((point_ref_by_label["D′"], point_ref_by_label["G"])),
        frozenset((point_ref_by_label["G"], point_ref_by_label["F"])),
        frozenset((point_ref_by_label["D′"], point_ref_by_label["F"])),
    }
    rendered_segments = {
        frozenset(item.geometry_refs)
        for item in frame.objects
        if item.component in {"ColoredLine", "DashedLine"}
        and len(item.geometry_refs) == 2
    }
    assert expected_segments <= rendered_segments
    assert any(
        item.component == "LocusLine"
        and set(item.geometry_refs)
        == {point_ref_by_label["M"], point_ref_by_label["N"]}
        for item in frame.objects
    )
    assert not any(
        item.role == "parameter_length:target" for item in frame.objects
    )
    assert sum(
        item.component == "Point" and item.display_label == "G"
        for item in frame.objects
    ) == 1

    geometry = nankai_yimo_page.visual_ir.geometry_registry
    environment = {"m": sp.Integer(parameter_value)}
    point_d_prime = _point_pair(
        geometry,
        point_ref_by_label["D′"],
        environment,
    )
    point_f = _point_pair(geometry, point_ref_by_label["F"], environment)
    point_g = _point_pair(geometry, point_ref_by_label["G"], environment)
    determinant = sp.simplify(
        (point_g[0] - point_d_prime[0]) * (point_f[1] - point_d_prime[1])
        - (point_g[1] - point_d_prime[1]) * (point_f[0] - point_d_prime[0])
    )
    assert determinant == 0


def test_anonymous_quadratic_vertex_is_visible_and_framed(
    xiqing_yimo_page: HepingYimoPage,
) -> None:
    derive_frame = _frame_for_source(xiqing_yimo_page, "derive_parabola_i")
    vertex_frame = _frame_for_source(xiqing_yimo_page, "derive_vertex_i")

    for frame in (derive_frame, vertex_frame):
        viewport = frame.viewport
        assert viewport["minX"] <= 2 <= viewport["maxX"]
        assert viewport["minY"] <= 9 <= viewport["maxY"]

    assert any(
        item.component == "Point"
        and item.geometry_refs == ("curve_i_parabola_vertex",)
        for item in vertex_frame.objects
    )

    intercept_frame = _frame_for_source(
        xiqing_yimo_page,
        "derive_x_intercept_B_ii",
    )
    assert intercept_frame.viewport["minX"] <= -1
    assert intercept_frame.viewport["maxY"] >= 4.2
    assert intercept_frame.viewport["minY"] > -5.1

    final_frame = _frame_for_source(
        xiqing_yimo_page,
        "solve_parameter_from_minimum_ii",
    )
    parameters = {
        str(item["name"]): item
        for item in final_frame.local_parameters
    }
    assert parameters["b"]["mathematical_domain"] == {
        "kind": "exact",
        "value": "2",
    }
    assert parameters["b"]["default_value"] == pytest.approx(2)
    assert parameters["m"]["default_value"] == pytest.approx(
        float(4 - 5 * sp.sqrt(3) / 3)
    )

    environment = {
        name: sp.sympify(str(item["default_value"]))
        for name, item in parameters.items()
    }
    geometry = xiqing_yimo_page.visual_ir.geometry_registry
    point_d = _point_pair(geometry, "point_D_ii", environment)
    point_m = _point_pair(geometry, "point_M_ii_2", environment)
    point_q = _point_pair(geometry, "point_Q_ii_2", environment)
    determinant = sp.simplify(
        (point_m[0] - point_d[0]) * (point_q[1] - point_d[1])
        - (point_m[1] - point_d[1]) * (point_q[0] - point_d[0])
    )
    assert abs(float(sp.N(determinant))) < 1e-9


def test_weighted_path_minimum_frame_shows_broken_and_shortest_paths(
    hexi_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(hexi_yimo_page, "domain_minimum")
    segments = {
        (item.component, item.geometry_refs)
        for item in frame.objects
        if item.component in {"ColoredLine", "DashedLine"}
    }

    assert ("ColoredLine", ("point_M_iii", "point_N_iii")) in segments
    assert ("ColoredLine", ("point_Q_iii", "point_N_iii")) in segments
    assert ("ColoredLine", ("point_A_iii", "point_Q_iii")) in segments
    assert ("DashedLine", ("point_M_iii", "point_Q_iii")) in segments


def test_parameter_calculation_keeps_shortest_path_and_auxiliary_ray(
    hexi_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(hexi_yimo_page, "solve_parameter_iii")
    segments = {
        (item.component, item.geometry_refs)
        for item in frame.objects
        if item.component in {"ColoredLine", "DashedLine"}
    }

    assert ("ColoredLine", ("point_A_iii", "point_Q_iii")) in segments
    assert ("DashedLine", ("point_M_iii", "point_Q_iii")) in segments


def test_right_angle_candidates_use_indexed_target_labels(
    hexi_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_source(hexi_yimo_page, "derive_right_angle_candidates_ii")
    labels = {
        item.display_label
        for item in frame.objects
        if item.component == "Point"
    }
    assert {"D₁", "D₂"} <= labels
    assert "候选1" not in labels
    assert "候选2" not in labels


def test_curve_candidate_filter_compares_both_indexed_points_at_solved_parameter(
    hexi_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(hexi_yimo_page, "filter_candidates")
    geometry = hexi_yimo_page.visual_ir.geometry_registry
    candidates = {
        item.display_label: item
        for item in frame.objects
        if item.role in {"candidate:selected", "candidate:rejected"}
    }
    assert set(candidates) == {"D₁", "D₂"}
    assert candidates["D₁"].role == "candidate:rejected"
    assert candidates["D₂"].role == "candidate:selected"
    assert not any(
        item.role.startswith("axis_projection:")
        for item in frame.objects
    )

    parameters = {item["name"]: item for item in frame.local_parameters}
    assert parameters["b"]["mathematical_domain"] == {
        "kind": "exact",
        "value": "-1 + sqrt(2)",
    }
    environment = {"b": sp.sqrt(2) - 1}
    curve = _curve_expression(geometry, "curve_ii_parabola", environment)
    selected_point = _point_pair(
        geometry,
        candidates["D₂"].geometry_refs[0],
        environment,
    )
    rejected_point = _point_pair(
        geometry,
        candidates["D₁"].geometry_refs[0],
        environment,
    )
    x = sp.Symbol("x")
    assert sp.simplify(curve.subs(x, selected_point[0]) - selected_point[1]) == 0
    assert sp.simplify(curve.subs(x, rejected_point[0]) - rejected_point[1]) != 0


def test_curve_candidate_filter_teaches_selection_without_rederiving_coordinates(
    hexi_yimo_page: HepingYimoPage,
) -> None:
    step = next(
        item
        for item in hexi_yimo_page.lesson.steps
        if item.teaching_unit_keys
        == ("curve_candidate_parameter_solve/filter_candidates",)
    )
    text = "\n".join([step.title, step.goal, *(line for _, line in step.derive)])

    assert "筛选D" in step.title
    assert "D₁" in text and "D₂" in text
    assert "代入" in text
    assert "全等三角形" not in text
    assert "DH⊥" not in text


def test_solved_curve_replaces_parameterized_curve_in_same_branch(
    hexi_yimo_page: HepingYimoPage,
) -> None:
    frame = _frame_for_unit(hexi_yimo_page, "solve_parameter_and_curve")
    geometry = hexi_yimo_page.visual_ir.geometry_registry
    curve_refs = {
        ref
        for item in frame.objects
        if item.component == "Parabola"
        for ref in item.geometry_refs
    }
    assert curve_refs == {"curve_ii_solved_parabola"}
    parameters = {item["name"]: item for item in frame.local_parameters}
    assert parameters["b"]["mathematical_domain"]["kind"] == "exact"

    environment = {"b": sp.sqrt(2) - 1}
    curve = _curve_expression(
        geometry,
        "curve_ii_solved_parabola",
        environment,
    )
    x = sp.Symbol("x")
    point_refs = {
        str(meta.get("label") or ""): ref
        for ref, meta in geometry["pointMeta"].items()
        if isinstance(meta, dict)
        and str(meta.get("scopeRoot") or "") == "ii"
        and str(meta.get("label") or "") in {"C", "D"}
        and meta.get("definition") != "public_candidate"
    }
    assert set(point_refs) == {"C", "D"}
    for label in ("C", "D"):
        point = _point_pair(geometry, point_refs[label], environment)
        assert sp.simplify(curve.subs(x, point[0]) - point[1]) == 0

    coordinate_labels = {
        item.display_label
        for item in frame.objects
        if item.component == "CoordinateLabel"
    }
    compact_labels = {text.replace(" ", "") for text in coordinate_labels}
    assert "D(√2,1)" in compact_labels
    assert "C(0,－√2－1)" in compact_labels
    assert not any("sqrt" in text for text in coordinate_labels)


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


def _curve_expression(
    geometry: Mapping[str, Any],
    curve_id: str,
    environment: Mapping[str, sp.Expr],
) -> sp.Expr:
    raw = next(
        curve
        for curve in geometry.get("curves") or ()
        if isinstance(curve, dict) and str(curve.get("id") or "") == curve_id
    )
    x = sp.Symbol("x")
    substitutions = {sp.Symbol(name): value for name, value in environment.items()}
    expression = sum(
        sp.sympify(str(raw[key])) * x**power
        for key, power in (("a", 2), ("b", 1), ("c", 0))
    )
    return sp.simplify(expression.subs(substitutions))


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


@cache
def _solve_hexi_snapshot() -> ExplanationSnapshot:
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture("tj-2026-hexi-yimo-25")
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


@cache
def _solve_xiqing_snapshot() -> ExplanationSnapshot:
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture("tj-2026-xiqing-yimo-25")
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


@cache
def _solve_nankai_snapshot() -> ExplanationSnapshot:
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture("tj-2026-nankai-yimo-25")
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
