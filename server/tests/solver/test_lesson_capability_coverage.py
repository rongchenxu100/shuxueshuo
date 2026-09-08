from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
    llm_facing_annotated_plan_payload,
)
from shuxueshuo_server.solver.explanation.models import iter_teaching_sources
from shuxueshuo_server.solver.explanation.teaching_specs import TeachingSpecBinder
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.lesson_authoring_support import build_recorded_snapshot
from shuxueshuo_server.solver.lesson_capability_coverage import (
    build_lesson_capability_coverage,
    discover_public_lesson_capabilities,
)
from shuxueshuo_server.solver.lesson_capability_coverage_review import (
    RECORDED_CASE_IDS,
    build_capability_coverage_review,
    capability_coverage_fixture_payloads,
)
from shuxueshuo_server.solver.lesson_capability_synthetic import (
    build_synthetic_capability_scenarios,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.student_display import find_internal_math_tokens


FIXTURE_ROOT = (
    Path(__file__).resolve().parent
    / "fixtures/lesson_scope_authoring_vnext/public_capability_c0"
)


@pytest.fixture(scope="module")
def c0_inputs():
    root = _repo_root()
    with TemporaryDirectory(prefix="lesson-c0-test-") as temp_dir:
        snapshots = tuple(
            build_recorded_snapshot(
                problem_id,
                authority_dir=Path(temp_dir) / problem_id,
                f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
            )
            for problem_id in RECORDED_CASE_IDS
        )
    return snapshots, build_synthetic_capability_scenarios()


def _iter_annotated_sources(scope):
    yield from scope.steps
    for goal in scope.goals:
        yield from goal.steps
    for child in scope.children:
        yield from _iter_annotated_sources(child)


def test_public_set_is_derived_from_family_catalog() -> None:
    public = discover_public_lesson_capabilities()
    assert len(public) == 29
    assert sum(item.kind == "function" for item in public) == 23
    assert sum(item.kind == "macro" for item in public) == 6
    assert len({item.capability_id for item in public}) == 29
    assert all(item.families for item in public)


def test_recorded_and_typed_synthetic_execution_cover_all_public_capabilities(
    c0_inputs,
) -> None:
    snapshots, scenarios = c0_inputs
    report = build_lesson_capability_coverage(
        snapshots=snapshots,
        synthetic_scenarios={
            capability_id: scenario.coverage_payload()
            for capability_id, scenario in scenarios.items()
        },
    )
    assert report["summary"] == {
        "public_capability_count": 29,
        "public_function_count": 23,
        "public_macro_count": 6,
        "recorded_coverage_count": 26,
        "synthetic_coverage_count": 3,
        "complete_coverage_count": 29,
        "diagnostic_count": 0,
    }
    assert set(scenarios) == {
        "distance_between_points",
        "equal_length_ray_point",
        "line_intersection_point",
    }
    assert all(
        scenario.coverage_payload()["execution"] == "real_stateless_method"
        and scenario.coverage_payload()["checks_passed"]
        for scenario in scenarios.values()
    )


def test_each_public_function_and_macro_has_one_complete_disposition(
    c0_inputs,
) -> None:
    snapshots, scenarios = c0_inputs
    report = build_lesson_capability_coverage(
        snapshots=snapshots,
        synthetic_scenarios={
            key: value.coverage_payload() for key, value in scenarios.items()
        },
    )
    methods = MethodSpecRegistry.load_from_code()
    recipes = RecipeSpecRegistry.load_from_code()
    for capability_id, card in report["capabilities"].items():
        assert card["diagnostics"] == []
        if card["kind"] == "function":
            spec = methods.require(card["source_id"])
            assert (spec.teaching_unit is None) != (
                spec.generic_teaching_reason is None
            )
            assert (spec.visual is None) != (
                spec.no_new_visual_reason is None
            )
        else:
            spec = recipes.get(card["source_id"])
            assert spec is not None
            assert spec.teaching is not None
            assert spec.visual is not None
            unit_tails = {
                key.rsplit("/", 1)[-1]
                for key in card["teaching_units"]
            }
            assert unit_tails == set(spec.visual.teaching_substep_templates)


def test_all_public_functions_use_explicit_runtime_bound_teaching_units() -> None:
    """A public Function must not collapse its mathematics to a generic summary."""

    methods = MethodSpecRegistry.load_from_code()
    public_functions = (
        item for item in discover_public_lesson_capabilities() if item.kind == "function"
    )
    for capability in public_functions:
        spec = methods.require(capability.source_id)
        assert spec.teaching_unit is not None, capability.capability_id
        assert spec.generic_teaching_reason is None, capability.capability_id
        assert spec.teaching_unit.role_binder_id not in {
            "generic_source",
            "generic_trace",
        }, capability.capability_id


def test_heping_yimo_projects_the_three_reviewed_derivations_in_full(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    snapshot = next(
        item for item in snapshots if item.problem_id == "tj-2026-heping-yimo-25"
    )
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    binder = TeachingSpecBinder()

    parabola = json.dumps(
        binder.bind_source(sources["derive_parabola_i"], snapshot=snapshot)[
            0
        ].to_payload(),
        ensure_ascii=False,
    )
    assert "A(－1,0) 在 y＝ax²＋bx－3 上" in parabola
    assert "0＝a－b－3" in parabola
    assert "D(2,－3) 在 y＝ax²＋bx－3 上" in parabola
    assert "－3＝4a＋2b－3" in parabola
    assert "联立上述方程，得 a＝1，b＝－2" in parabola
    assert "题设给出当前二次函数的系数条件" not in parabola

    equal_angle = json.dumps(
        binder.bind_source(sources["derive_equal_angle_i"], snapshot=snapshot)[
            0
        ].to_payload(),
        ensure_ascii=False,
    )
    assert "C(0,－3)、O(0,0)、B(3,0)，且 OC⊥OB" in equal_angle
    assert "OC＝3，OB＝3" in equal_angle
    assert "Rt△COB 为等腰直角三角形" in equal_angle
    assert "∠CBO＝∠CBE＋∠OBE" in equal_angle
    assert "消去公共角 ∠CBE" in equal_angle

    axis_intercept = json.dumps(
        binder.bind_source(
            sources["derive_axis_intercept_F_i"],
            snapshot=snapshot,
        )[0].to_payload(),
        ensure_ascii=False,
    )
    assert "B、E、F 共线" in axis_intercept
    assert "Rt△BOF 与 Rt△AOC" in axis_intercept
    assert "tan∠OBF＝OF/OB" in axis_intercept
    assert "OF/OB＝AO/CO" in axis_intercept
    assert "OB＝3，AO＝1，CO＝3，所以 OF＝1" in axis_intercept
    assert "F 在 y 轴负半轴上" in axis_intercept


def test_other_computational_methods_do_not_delegate_missing_math_to_llm(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    snapshot = next(
        item for item in snapshots if item.problem_id == "tj-2026-heping-ermo-25"
    )
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    binder = TeachingSpecBinder()

    def material_text(step_id: str) -> str:
        return json.dumps(
            binder.bind_source(sources[step_id], snapshot=snapshot)[0].to_payload(),
            ensure_ascii=False,
        )

    parabola = material_text("derive_parabola_i")
    assert "代入 y＝－x²＋bx＋c" in parabola
    assert "得 y＝－x²－2x＋3" in parabola

    vertex = material_text("derive_vertex_P_i")
    assert "配方，得 y＝－(x＋1)²＋4" in vertex
    assert "顶点为 P(－1,4)" in vertex

    parameter = material_text("solve_parameter_c_ii")
    assert "c＝－7 或 c＝5" in parameter
    assert "根据 c＞1，保留 c＝5" in parameter

    evaluated_point = material_text("evaluate_minimum_point_G_ii")
    assert "x_G＝1/4－3c/4＝－7/2" in evaluated_point
    assert "y_G＝－c/2－1/2＝－3" in evaluated_point

    candidates = material_text("solve_axis_point_candidates_i")
    assert "E(－1,t) 与 G(t－3,－2) 都由同一参数 t 表示" in candidates
    assert "把参数值代回 E(－1,t)" in candidates


def test_coefficient_relations_explain_the_missing_coefficient_before_substitution(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    snapshot = next(
        item for item in snapshots if item.problem_id == "tj-2026-nankai-yimo-25"
    )
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "i_derive_parabola"
    )
    material = json.dumps(
        TeachingSpecBinder().bind_source(source, snapshot=snapshot)[0].to_payload(),
        ensure_ascii=False,
    )

    assert "将 a＝2 代入 2a＋b＝0，解得 b＝－4" in material
    assert "代入 y＝ax²＋bx＋c，得 y＝2x²－4x－5" in material


def test_nankai_selected_candidate_and_endpoint_replacement_use_geometry(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    snapshot = next(
        item for item in snapshots if item.problem_id == "tj-2026-nankai-yimo-25"
    )
    sources = {
        item.source_step_id: item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id in {"ii_construct_N", "ii_path_minimum"}
    }
    binder = TeachingSpecBinder()

    point_materials = [
        item.to_payload()
        for item in binder.bind_source(
            sources["ii_construct_N"],
            snapshot=snapshot,
        )
    ]
    assert len(point_materials) == 2
    candidate_text = json.dumps(point_materials[0], ensure_ascii=False)
    selected_text = json.dumps(point_materials[1], ensure_ascii=False)
    candidate_derive = "\n".join(
        "".join(item) for item in point_materials[0]["derive"]
    )
    selected_derive = "\n".join(
        "".join(item) for item in point_materials[1]["derive"]
    )
    for fragment in (
        "设两个候选点分别为N₁、N₂",
        "MU⊥x 轴于U，N₁V⊥x 轴于V，N₂W⊥x 轴于W",
        "U(m,0)，DU＝m－1，MU＝1",
        "∠MDN₁＝∠MDN₂＝90°，DM＝DN₁＝DN₂",
        "Rt△DUM≌Rt△N₁VD≌Rt△N₂WD",
        "DV＝DW＝MU＝1，N₁V＝N₂W＝DU＝m－1",
        "V(2,0)，W(0,0)，N₁(2,1－m)，N₂(0,m－1)",
    ):
        assert fragment in candidate_derive
    assert "候选 1" not in candidate_text
    assert "候选 2" not in candidate_text
    for fragment in (
        "根据题设条件确定唯一候选点",
        "N 在第四象限，且 m＞2",
        "N₁(2,1－m)满足上述条件",
        "N₂(0,m－1)不满足上述条件",
        "唯一符合题意的点为N(2,1－m)",
    ):
        assert fragment in selected_derive or fragment in selected_text
    assert "Rt△" not in selected_derive

    path_materials = [
        item.to_payload()
        for item in binder.bind_source(
            sources["ii_path_minimum"],
            snapshot=snapshot,
        )
    ]
    replacement_text = json.dumps(path_materials[0], ensure_ascii=False)
    for fragment in (
        "GH⊥DN于H，GK⊥DM于K",
        "△GNH是等腰直角三角形",
        "GH＝HN＝NG/√2",
        "四边形DKGH是矩形",
        "DE＝√2·NG＝2GH",
        "GK垂直平分DE",
        "△DGE是等腰三角形，EG＝DG",
        "EG＋FG＝DG＋FG",
    ):
        assert fragment in replacement_text

    replacement = next(
        calculation["facts"]
        for calculation in sources["ii_path_minimum"].calculations
        if calculation["kind"] == "existing_fixed_endpoint_replacement"
    )
    geometry = replacement["geometry_certificate"]
    assert geometry["kind"] == "right_isosceles_perpendicular_bisector"
    assert geometry["student_second_leg_projection"]["label"] == "H"
    assert geometry["student_first_leg_projection"]["label"] == "K"


def test_every_public_function_projects_its_key_student_computation(
    c0_inputs,
) -> None:
    """Cover the mathematical action that generic input/output text used to omit."""

    snapshots, scenarios = c0_inputs
    artifacts = build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=scenarios,
    )
    text_by_capability = {
        card["capability_id"]: json.dumps(
            [
                material
                for occurrence in card["occurrences"]
                for material in occurrence["bound_materials"]
            ],
            ensure_ascii=False,
        )
        for card in artifacts.review["cards"]
        if card["kind"] == "function"
    }
    required_fragments = {
        "angle_sum_equal_angle_candidates": ("等腰直角三角形", "消去公共角"),
        "axis_intercept_from_equal_acute_angles": ("tan∠", "共线"),
        "distance_between_points": ("两点距离公式", "AB＝5"),
        "equal_length_ray_point": ("参考线段", "截取"),
        "evaluate_expression_at_parameter": ("代入", "化简得"),
        "evaluate_point_at_parameter": ("代入：", "x_G＝", "y_G＝"),
        "line_intersection_point": ("其方程为", "联立", "解得 x＝"),
        "line_parabola_second_intersection_point": ("联立", "排除"),
        "midpoint_point": ("中点公式",),
        "parameter_from_expression_value": ("题设要求", "解方程，得", "保留"),
        "parameter_from_minimum_value": ("题设要求", "解方程，得", "保留"),
        "parameter_from_segment_length": (
            "长度条件",
            "距离公式建立方程",
            "解方程，得",
            "保留",
        ),
        "point_candidates_from_curve_point_condition": (
            "都由同一参数",
            "代入曲线点坐标",
            "把参数值代回",
        ),
        "point_on_parabola_at_x": ("代入横坐标",),
        "quadratic_axis_from_relation": ("x＝－b/(2a)", "代入得"),
        "quadratic_axis_parameterized_point": ("对称轴", "设"),
        "quadratic_from_constraints": ("代入", "联立上述方程"),
        "quadratic_vertex_point": ("配方", "顶点为"),
        "quadratic_x_axis_intercept_point": ("y＝0", "取"),
        "quadratic_y_axis_intercept_point": ("x＝0", "代入"),
        "right_angle_equal_length_candidates": (
            "顺、逆时针旋转 90°",
            "两个候选位置",
        ),
        "square_adjacent_vertex_from_side": ("正方形", "Rt△"),
        "translated_point": ("横、纵坐标分别相加",),
    }
    assert set(text_by_capability) == set(required_fragments)
    for capability_id, fragments in required_fragments.items():
        text = text_by_capability[capability_id]
        assert all(fragment in text for fragment in fragments), (
            capability_id,
            fragments,
            text,
        )

    vertex = next(
        card
        for card in artifacts.review["cards"]
        if card["capability_id"] == "quadratic_vertex_point"
    )
    vertex_materials = [
        json.dumps(occurrence["bound_materials"], ensure_ascii=False)
        for occurrence in vertex["occurrences"]
    ]
    assert all("顶点为 " in material for material in vertex_materials)
    assert all("vertex(" not in material for material in vertex_materials)


def test_hexi_yimo_projects_the_reviewed_geometry_and_parameter_flow(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    snapshot = next(
        item for item in snapshots if item.problem_id == "tj-2026-hexi-yimo-25"
    )
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    binder = TeachingSpecBinder()

    candidate_construction = json.dumps(
        binder.bind_source(
            sources["derive_right_angle_candidates_ii"],
            snapshot=snapshot,
        )[0].to_payload(),
        ensure_ascii=False,
    )
    assert "顺、逆时针旋转 90°" in candidate_construction
    assert "D 的两个候选位置" in candidate_construction
    assert "D₁(－b－3,－1)，D₂(b＋1,1)" in candidate_construction
    assert "D 候选 1" not in candidate_construction
    assert "D 候选 2" not in candidate_construction
    assert "DH⊥x 轴" not in candidate_construction
    assert "Rt△AOC≌Rt△DHA" not in candidate_construction

    curve_materials = binder.bind_source(
        sources["select_curve_candidate_ii"],
        snapshot=snapshot,
    )
    solve_b = json.dumps(curve_materials[0].to_payload(), ensure_ascii=False)
    for fragment in (
        "作\", \"DH⊥x 轴，垂足为 H",
        "C(0,－b－2)",
        "AO＝1，OC＝b＋2",
        "∠CAD＝90°，AC＝AD",
        "Rt△AOC≌Rt△DHA",
        "AH＝OC＝b＋2，DH＝AO＝1",
        "H(b＋1,0)，D(b＋1,1)",
    ):
        assert fragment in solve_b

    assert "D 在抛物线 y＝2x²－bx－b－2 上" in solve_b
    assert "将 D(b＋1,1) 代入，得 1＝b²＋2b" in solve_b
    assert "b²＋2b－1＝0" in solve_b
    assert "b＞0" in solve_b
    assert "b＝√2－1" in solve_b

    substitute = json.dumps(curve_materials[1].to_payload(), ensure_ascii=False)
    assert "b＝√2－1，D(b＋1,1)" in substitute
    assert "D(√2,1)" in substitute
    assert "Eq(" not in substitute

    weighted = binder.bind_source(
        sources["derive_weighted_minimum_iii"],
        snapshot=snapshot,
    )
    reduction = json.dumps(weighted[0].to_payload(), ensure_ascii=False)
    for fragment in (
        "等腰直角三角形 AQN",
        "AQ＝QN，∠AQN＝90°",
        "AN 是 Rt△AQN 的斜边",
        "AN＝√2·QN",
        "√2MN＋AN＝√2(MN＋QN)",
        "Q 在过 A 且经过 y 轴正半轴点 (0,1) 的 45° 固定射线 y＝x＋1 上运动",
    ):
        assert fragment in reduction

    minimum = json.dumps(weighted[1].to_payload(), ensure_ascii=False)
    for fragment in (
        "两点之间线段最短",
        "MN＋NQ≥MQ",
        "M、N、Q 三点共线时，折线最短",
        "MQ 的最小值是 M 到这条射线的垂线段",
        "MH⊥x 轴，垂足为 H",
        "△MHN 是等腰直角三角形",
        "M(b＋1/2,－(2b＋3)/4)",
        "MH＝HN＝(2b＋3)/4",
        "MN＝√2·(2b＋3)/4",
        "AN＝AH－HN＝(2b＋3)/4",
        "QN＝√2·(2b＋3)/8",
        "MN＋QN＝3√2(2b＋3)/8",
        "最小值＝√2·3√2(2b＋3)/8＝(6b＋9)/4",
        "N((2b－1)/4,0)",
        "0＜b≤1/2",
        "最小值在正半轴端点 O 取得",
        "MO＝√(20b²＋28b＋13)/4，AO＝1",
    ):
        assert fragment in minimum


def test_all_public_teaching_materials_hide_internal_math_syntax(c0_inputs) -> None:
    snapshots, scenarios = c0_inputs
    for snapshot in snapshots:
        plan = llm_facing_annotated_plan_payload(
            AnnotatedTeachingPlanProjector().project(snapshot).plan
        )
        assert find_internal_math_tokens(plan) == [], snapshot.problem_id
    artifacts = build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=scenarios,
    )
    leaks: list[tuple[str, str, list[str]]] = []
    for card in artifacts.review["cards"]:
        for occurrence in card["occurrences"]:
            hits = find_internal_math_tokens(occurrence["bound_materials"])
            if hits:
                leaks.append(
                    (
                        str(card["capability_id"]),
                        str(occurrence["source_step_id"]),
                        hits,
                    )
                )
    assert leaks == []


def test_deferred_point_identity_is_projected_once_as_a_student_label(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    snapshot = next(
        item for item in snapshots if item.problem_id == "tj-2026-heping-yimo-25"
    )
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    payload = projection.plan.to_payload()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "derive_axis_intercept_F_i_point" not in serialized
    assert '"left_angle": "OBF"' in serialized
    assert '"left_angle_points": ["O", "B", "F"]' in serialized

    steps = {
        source.step_id: source
        for source in _iter_annotated_sources(projection.plan.root_scope)
    }
    assert steps["derive_equal_angle_i"].outputs["angle_equality"]["display"] == (
        "∠OBF＝∠ACO"
    )
    assert steps["derive_axis_intercept_F_i"].inputs["angle_equality"][0][
        "display"
    ] == "∠OBF＝∠ACO"
    assert steps["derive_axis_intercept_F_i"].outputs["point"]["display"] == (
        "F(0,-1)"
    )


def test_new_public_macros_are_atomic_sources_with_two_bound_units(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    sources = {
        source.capability_id: (snapshot, source)
        for snapshot in snapshots
        for source in iter_teaching_sources(snapshot.root_scope)
        if source.capability_id in {
            "right_angle_equal_length_construct_and_select",
            "curve_candidate_parameter_solve",
        }
    }
    assert set(sources) == {
        "right_angle_equal_length_construct_and_select",
        "curve_candidate_parameter_solve",
    }
    binder = TeachingSpecBinder()
    for snapshot, source in sources.values():
        assert len(binder.bind_source(source, snapshot=snapshot)) == 2
        assert source.calculations
        assert source.outputs


def test_equal_length_ray_macro_teaches_construction_before_coordinate_work(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    snapshot = next(
        item for item in snapshots if item.problem_id == "tj-2026-heping-yimo-25"
    )
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.capability_id == "equal_length_ray_path_reduction"
    )
    materials = [
        item.to_payload()
        for item in TeachingSpecBinder().bind_source(source, snapshot=snapshot)
    ]
    assert len(materials) == 2

    reduction_text = json.dumps(materials[0], ensure_ascii=False)
    assert "在射线CD上构造G，使CG＝CB" in reduction_text
    assert "G(" not in reduction_text
    assert "∠BCN＝∠GCM" in reduction_text
    assert "△BCN≌△GCM（边角边），故BN＝MG" in reduction_text

    minimum_text = json.dumps(materials[1], ensure_ascii=False)
    assert "OM＋MG≥OG" in minimum_text
    assert "OG＝√[" in minimum_text
    assert "＝3√(2a²＋1)/|a|" in minimum_text


def test_all_public_teaching_materials_contain_no_english_prose(
    c0_inputs,
) -> None:
    """Machine contracts may use English keys; student prose may not."""

    snapshots, scenarios = c0_inputs
    artifacts = build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=scenarios,
    )
    forbidden_words = {
        "and",
        "are",
        "because",
        "candidate",
        "closed",
        "condition",
        "congruent",
        "corresponding",
        "curve",
        "domain",
        "eq",
        "equality",
        "expression",
        "false",
        "formed",
        "given",
        "included",
        "interior",
        "lies",
        "line",
        "lines",
        "minimum",
        "otherwise",
        "parameter",
        "piecewise",
        "point",
        "positive",
        "proves",
        "ray",
        "result",
        "same",
        "sas",
        "segment",
        "selected",
        "solve",
        "sqrt",
        "state",
        "the",
        "therefore",
        "throughout",
        "triangles",
        "true",
        "using",
        "valid",
        "value",
        "when",
        "where",
        "with",
    }
    leaks: list[tuple[str, str, str]] = []
    for card in artifacts.review["cards"]:
        for occurrence in card["occurrences"]:
            for material in occurrence["bound_materials"]:
                student_text = "\n".join(
                    (
                        str(material["title"]),
                        str(material["nav_title"]),
                        str(material["goal"]),
                        *(str(item[1]) for item in material["derive"]),
                        *(str(item) for item in material["box"]),
                    )
                )
                words = {
                    item.lower()
                    for item in re.findall(r"[A-Za-z]+", student_text)
                }
                found = sorted(words & forbidden_words)
                if found:
                    leaks.append(
                        (
                            str(card["capability_id"]),
                            str(occurrence["source_step_id"]),
                            ",".join(found),
                        )
                    )
    assert leaks == []


def test_weighted_path_auxiliary_point_has_one_computed_student_identity(
    c0_inputs,
) -> None:
    snapshots, _ = c0_inputs
    weighted = [
        (snapshot, source)
        for snapshot in snapshots
        for source in iter_teaching_sources(snapshot.root_scope)
        if source.capability_id == "weighted_axis_path_minimum"
    ]
    assert len(weighted) == 2
    binder = TeachingSpecBinder()
    for snapshot, source in weighted:
        evidence = snapshot.evidence_for_step(source.source_step_id)
        assert len(evidence) == 1
        construction = evidence[0]["constructions"][0]
        student_point = construction["student_auxiliary_point"]
        label = student_point["label"]
        geometry = construction["axis_projection_geometry"]
        assert geometry["kind"] == "axis_projection_geometric_minimum"
        projection = geometry["student_projection_point"]
        boundary = geometry["student_boundary_point"]
        used_labels = {
            str(item.get("name") or "")
            for item in snapshot.problem.get("entities", ())
            if isinstance(item, dict) and item.get("entity_type") == "point"
        }
        assert label not in used_labels
        assert projection["label"] not in used_labels | {label}
        assert boundary["label"] not in used_labels | {
            label,
            projection["label"],
        }
        public_text = json.dumps(
            {
                "evidence": evidence,
                "calculations": source.calculations,
                "materials": [
                    item.to_payload()
                    for item in binder.bind_source(source, snapshot=snapshot)
                ],
            },
            ensure_ascii=False,
        )
        assert "AauxiliaryM" not in public_text
        assert "auxiliaryM" not in public_text
        assert label in public_text
        roles = {
            str(item["role"]): str(item["chosen_ref"])
            for item in evidence[0]["role_resolutions"]
        }
        assert (
            f"{roles['curve_point']}{projection['label']}⊥x 轴"
            in public_text
        )
        assert "三角形" in public_text


def test_weighted_path_geometry_teaching_contains_no_case_literal() -> None:
    solver_root = Path(__file__).resolve().parents[2] / "shuxueshuo_server/solver"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            solver_root / "runtime/methods/weighted_axis_path_minimum.py",
            solver_root / "runtime/weighted_axis_path_evidence.py",
            solver_root / "explanation/evidence_projectors.py",
            solver_root / "explanation/teaching_specs.py",
        )
    )
    for forbidden in (
        "tj-2026",
        "hexi",
        "河西",
        "(0,1)",
        "b > 1/2",
        "2*b + 3",
    ):
        assert forbidden not in sources


def test_right_angle_and_coupled_geometry_contain_no_case_literal() -> None:
    solver_root = Path(__file__).resolve().parents[2] / "shuxueshuo_server/solver"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            solver_root / "runtime/right_angle_selection_geometry.py",
            solver_root
            / "runtime/methods/_internal/path/two_moving_points_path_reduction.py",
            solver_root / "runtime/coupled_segment_path_evidence.py",
            solver_root / "explanation/evidence_projectors.py",
            solver_root / "explanation/teaching_specs.py",
        )
    )
    for forbidden in (
        "tj-2026",
        "nankai",
        "南开",
        "Rt△DUM",
        "四边形DKGH",
        "DE＝√2·NG",
        "N(2,1",
    ):
        assert forbidden not in sources


def test_review_has_one_card_per_public_capability(c0_inputs) -> None:
    snapshots, scenarios = c0_inputs
    artifacts = build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=scenarios,
    )
    assert len(artifacts.review["cards"]) == 29
    assert artifacts.review["human_review_approved"] is False
    assert artifacts.review["status"] == "awaiting_human_review"
    assert all(not card["diagnostics"] for card in artifacts.review["cards"])

    weighted = next(
        card
        for card in artifacts.review["cards"]
        if card["capability_id"] == "weighted_axis_path_minimum"
    )
    assert len(weighted["occurrences"]) == 2
    for occurrence in weighted["occurrences"]:
        construction = next(
            calculation["facts"]
            for calculation in occurrence["teaching_source"]["calculations"]
            if calculation["kind"] == "weighted_right_triangle"
        )
        auxiliary = construction["student_auxiliary_point"]
        visual_payload = json.dumps(
            occurrence["visual_steps"],
            ensure_ascii=False,
        )
        assert f'"labelText": "{auxiliary["label"]}"' in visual_payload
        assert '"role": "student_auxiliary_point"' in visual_payload
        assert "auxiliaryM" not in visual_payload
        axis_geometry = construction["axis_projection_geometry"]
        dynamic_parameter = axis_geometry["dynamic_parameter"]
        dynamic_constraint = axis_geometry["dynamic_constraint"]
        local_parameters = [
            parameter
            for visual_step in occurrence["visual_steps"]
            for frame in visual_step["frames"]
            for parameter in frame["local_parameters"]
            if parameter["name"] == dynamic_parameter
        ]
        assert local_parameters
        expected_domain = {
            "kind": "inequality",
            "expression": (
                f"{dynamic_parameter}{dynamic_constraint['operator']}"
                f"{dynamic_constraint['value']}"
            ),
        }
        for parameter in local_parameters:
            assert parameter["mathematical_domain"] == expected_domain
            assert parameter["display_window"]["min"] > 0
            assert all(control["min"] > 0 for control in parameter["controls"])


def test_human_approved_c0_fixtures_match_current_public_registry(c0_inputs) -> None:
    snapshots, scenarios = c0_inputs
    artifacts = build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=scenarios,
    )
    expected = capability_coverage_fixture_payloads(artifacts)

    for filename, payload in expected.items():
        assert json.loads(
            (FIXTURE_ROOT / filename).read_text(encoding="utf-8")
        ) == payload

    review = json.loads(
        (FIXTURE_ROOT / "human-review-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert review["review_status"] == "approved"
    assert review["source_batch"] == "f5-f5c0-public-capability-review"
    assert review["checks"]["all_29_capability_cards_reviewed"] is True
    assert review["checks"]["no_problem_specific_visual_patch"] is True


def test_generic_visual_builder_contains_no_public_capability_dispatch() -> None:
    builder_path = (
        Path(__file__).resolve().parents[2]
        / "shuxueshuo_server/solver/visual/builder.py"
    )
    source = builder_path.read_text(encoding="utf-8")
    public_ids = {
        item.capability_id for item in discover_public_lesson_capabilities()
    }
    assert sorted(capability_id for capability_id in public_ids if capability_id in source) == []


def test_conditional_visual_is_declared_by_output_presence() -> None:
    spec = MethodSpecRegistry.load_from_code().require(
        "evaluate_expression_at_parameter"
    )
    assert spec.visual is not None
    assert [
        template.get("when") for template in spec.visual.scene_templates
    ] == [{"output_present": "evaluated_parabola"}]
