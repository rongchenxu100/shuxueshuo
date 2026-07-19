"""V1.5 MethodSpec 加载测试。

这些测试确保 method 代码里的 SPEC 能被加载成强类型 MethodSpec，并且生成的 JSON
资产没有和代码事实源漂移。
"""

import json
from pathlib import Path
import re

import pytest

from shuxueshuo_server.solver.runtime.method_specs import (
    MethodSpecRegistry,
    parse_method_spec,
)
from shuxueshuo_server.solver.runtime.methods import method_spec_payloads
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry


PLACEHOLDER_RE = re.compile(r"{([A-Za-z_][A-Za-z0-9_]*)}")
ENGLISH_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def test_loads_right_angle_candidate_and_selector_specs() -> None:
    registry = MethodSpecRegistry.load_from_code()
    candidate_spec = registry.require("right_angle_equal_length_candidates")
    selector_spec = registry.require("select_point_by_quadrant_constraint")

    assert candidate_spec.method_id == "right_angle_equal_length_candidates"
    assert "参数" in candidate_spec.summary
    assert candidate_spec.inputs["anchor"].type == "Point"
    assert candidate_spec.outputs["candidates"] == "PointList"
    assert selector_spec.inputs["parameter_constraint"].type == "Constraint"
    assert selector_spec.outputs["selected_point"] == "Point"


def test_loads_broken_path_straightening_specs() -> None:
    registry = MethodSpecRegistry.load_from_code()
    candidate_spec = registry.require("broken_path_straightening_candidates")
    selector_spec = registry.require("select_straightening_candidate")

    assert candidate_spec.inputs["path_transformation"].type == "PathTransformation"
    assert candidate_spec.outputs["candidates"] == "StraighteningCandidateList"
    assert selector_spec.inputs["candidates"].type == "StraighteningCandidateList"
    assert selector_spec.outputs["auxiliary_point"] == "Point"


def test_loads_quadratic_from_constraints_spec() -> None:
    """统一二次函数约束 method 应暴露足够的可选约束输入槽位。"""
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("quadratic_from_constraints")

    assert "最简" in spec.summary
    assert "使用原则" in spec.summary
    assert spec.inputs["quadratic"].type == "Expression"
    assert spec.inputs["x"].type == "Symbol"
    assert spec.inputs["all_coefficients"].type == "SymbolList"
    assert spec.inputs["known_coefficients"].required is False
    assert spec.inputs["coefficient_relation"].type == "Equation"
    assert spec.inputs["curve_point"].type == "Point"
    assert spec.inputs["curve_points"].type == "PointList"
    assert spec.inputs["free_parameter"].type == "Symbol"
    assert spec.inputs["free_parameters"].type == "SymbolList"
    assert spec.outputs["coefficients"] == "Coefficients"
    assert spec.outputs["parabola"] == "Parabola"
    assert any("重复求解" in item for item in spec.do_not_use_when)


def test_method_spec_usage_guidance_round_trips_and_validates() -> None:
    payload = next(
        item
        for item in method_spec_payloads()
        if item["method_id"] == "evaluate_point_at_parameter"
    )

    spec = parse_method_spec(payload)

    assert spec.do_not_use_when == tuple(payload["do_not_use_when"])
    duplicated = dict(payload)
    duplicated["do_not_use_when"] = ["avoid this", "avoid this"]
    assert parse_method_spec(duplicated).do_not_use_when == ("avoid this",)
    malformed = dict(payload)
    malformed["do_not_use_when"] = [""]
    with pytest.raises(
        ValueError,
        match="do_not_use_when items must be non-empty",
    ):
        parse_method_spec(malformed)


def test_loads_quadratic_candidate_filter_spec() -> None:
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("filter_point_candidates_by_quadratic_curve")

    assert spec.inputs["candidates"].type == "PointList"
    assert spec.inputs["parabola"].type == "Parabola"
    assert spec.inputs["parameter_constraint"].type == "Constraint"
    assert spec.outputs["filtered_candidates"] == "PointList"
    assert spec.outputs["rejected_candidates"] == "PointList"
    assert spec.outputs["selected_candidate"] == "Point"


def test_loads_square_axis_candidate_atomic_specs() -> None:
    registry = MethodSpecRegistry.load_from_code()
    axis_point = registry.require("quadratic_axis_parameterized_point")
    square_vertex = registry.require("square_adjacent_vertex_from_side")
    curve_condition = registry.require("point_candidates_from_curve_point_condition")
    point_at_parameter = registry.require("evaluate_point_at_parameter")
    minimum_point = registry.require("line_locus_minimum_point")

    assert axis_point.inputs["parabola"].type == "Parabola"
    assert axis_point.outputs["point"] == "Point"
    assert square_vertex.inputs["square_condition"].type == "Condition"
    assert square_vertex.inputs["target"].type == "PointRef|Point"
    assert square_vertex.inputs["side_start_ref"].type == "PointRef|Point"
    assert square_vertex.inputs["side_end_ref"].type == "PointRef|Point"
    assert square_vertex.outputs["point"] == "Point"
    assert curve_condition.inputs["target_point"].type == "Point"
    assert curve_condition.inputs["curve_point"].type == "Point"
    assert curve_condition.outputs["candidates"] == "PointList"
    assert point_at_parameter.inputs["point"].type == "Point"
    assert point_at_parameter.outputs["evaluated_point"] == "Point"
    assert minimum_point.inputs["moving_locus"].type == "Line"
    assert minimum_point.inputs["target"].type == "PointRef|Point"
    assert minimum_point.outputs["point"] == "Point"


def test_loads_parameter_from_curve_point_on_quadratic_spec() -> None:
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("parameter_from_curve_point_on_quadratic")

    assert spec.inputs["quadratic"].type == "Parabola"
    assert spec.inputs["point"].type == "Point"
    assert spec.inputs["parameter"].type == "Symbol"
    assert spec.inputs["parameter_constraint"].type == "Constraint"
    assert spec.outputs["parameter_value"] == "ParameterValue"
    assert spec.outputs["point"] == "Point"
    assert spec.outputs["parabola"] == "Parabola"


def test_loads_weighted_geometric_path_specs() -> None:
    """加权路径的几何转化与折线最短应作为独立 method 暴露给 planner。"""
    registry = MethodSpecRegistry.load_from_code()
    transform = registry.require("weighted_axis_path_triangle_transform")
    minimum = registry.require("linked_broken_path_minimum_expression")
    parameter = registry.require("parameter_from_expression_value")

    assert transform.inputs["condition"].type == "Condition"
    assert transform.inputs["auxiliary_point_ref"].type == "PointRef"
    assert transform.outputs["auxiliary_point"] == "Point"
    assert transform.outputs["path_transformation"] == "PathTransformation"
    assert transform.outputs["auxiliary_locus"] == "Line"
    assert minimum.inputs["path_transformation"].type == "PathTransformation"
    assert minimum.inputs["auxiliary_locus"].type == "Line"
    assert minimum.inputs["auxiliary_point"].type == "Point"
    assert minimum.outputs["minimum_expression"] == "MinimumExpression"
    assert "parameter_value" not in minimum.outputs
    assert parameter.inputs["expression"].type == "MinimumExpression"
    assert parameter.outputs["parameter_value"] == "ParameterValue"
    assert parameter.explanation is not None
    assert parameter.explanation.student_title_template == "由表达式取值反求参数"


def test_y_axis_intercept_summary_allows_symbolic_coefficients() -> None:
    """y 轴交点 method 的能力摘要应说明可保留未定系数。"""
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("quadratic_y_axis_intercept_point")

    assert spec.inputs["quadratic"].type == "Expression"
    assert "未定系数" in spec.summary


def test_searches_spec_by_goal_type() -> None:
    registry = MethodSpecRegistry.load_from_code()

    matches = registry.for_goal("derive_right_angle_equal_length_candidates")

    assert [spec.method_id for spec in matches] == ["right_angle_equal_length_candidates"]


def test_scalar_result_form_specs_round_trip_from_code() -> None:
    registry = MethodSpecRegistry.load_from_code()

    distance = registry.require("distance_between_points")
    assert set(distance.scalar_result_forms) == {
        "distance",
        "evaluated_distance",
    }
    assert distance.scalar_result_forms["distance"].possible_forms == (
        "open_expression",
        "closed_value",
    )
    assert distance.scalar_result_forms["distance"].closure_policy == (
        "no_free_symbols"
    )

    evaluate = registry.require("evaluate_expression_at_parameter")
    assert set(evaluate.scalar_result_forms) == {
        "evaluated_expression",
        "evaluated_minimum_expression",
    }
    assert "evaluated_parabola" not in evaluate.scalar_result_forms


def test_generated_json_specs_match_code_source() -> None:
    spec_dir = Path("../internal/method-specs")
    expected = {
        payload["method_id"]: payload
        for payload in method_spec_payloads()
    }
    actual = {
        raw["method_id"]: raw
        for raw in (
            json.loads(path.read_text(encoding="utf-8"))
            for path in spec_dir.glob("*.json")
        )
    }

    assert actual == expected


def test_method_explanation_placeholders_are_declared_roles() -> None:
    registry = MethodSpecRegistry.load_from_code()

    for spec in registry.specs.values():
        explanation = spec.explanation
        if explanation is None:
            continue
        templates = (
            explanation.student_goal_template,
            explanation.student_title_template,
            explanation.student_nav_title_template,
            *explanation.derive_templates,
            *explanation.box_templates,
        )
        placeholders = {
            match
            for template in templates
            for match in PLACEHOLDER_RE.findall(template)
        }

        assert placeholders <= set(explanation.role_schema), spec.method_id


def test_method_role_schema_descriptions_are_student_facing_chinese() -> None:
    for payload in method_spec_payloads():
        for section in ("explanation", "visual"):
            role_schema = (payload.get(section) or {}).get("role_schema") or {}
            for role_id, description in role_schema.items():
                assert ENGLISH_WORD_RE.search(str(description)) is None, (
                    payload["method_id"],
                    section,
                    role_id,
                    description,
                )


def test_curve_point_candidate_visual_spec_is_not_square_bound() -> None:
    spec = MethodSpecRegistry.load_from_code().require("point_candidates_from_curve_point_condition")

    assert spec.visual is not None
    assert spec.visual.role_schema == {
        "target_candidates": "由曲线条件得到的目标点候选。",
        "candidate_context_regions": "可选的候选几何上下文区域，例如候选正方形。",
    }
    assert [template["component"] for template in spec.visual.scene_templates] == [
        "CurvePointCandidateMarker",
    ]


def test_empty_student_nav_title_template_is_omitted_from_generated_json() -> None:
    generated = {
        payload["method_id"]: payload
        for payload in method_spec_payloads()
    }
    raw_specs = {
        raw["method_id"]: raw
        for raw in (
            json.loads(path.read_text(encoding="utf-8"))
            for path in Path("../internal/method-specs").glob("*.json")
        )
    }

    for method_id, payload in generated.items():
        explanation = payload.get("explanation")
        if not isinstance(explanation, dict):
            continue
        assert explanation.get("student_nav_title_template") != "", method_id
        assert raw_specs[method_id].get("explanation", {}).get("student_nav_title_template") != "", method_id


def test_recipe_proof_outline_placeholders_are_declared_roles() -> None:
    registry = RecipeSpecRegistry.load_from_code()

    for spec in registry.specs.values():
        explanation = spec.explanation
        if explanation is None:
            continue
        placeholders = {
            match
            for template in explanation.proof_outline_templates
            for match in PLACEHOLDER_RE.findall(template)
        }
        assert placeholders <= set(explanation.role_schema), spec.recipe_id


def test_rejects_missing_required_field() -> None:
    with pytest.raises(ValueError, match="missing required"):
        parse_method_spec({"method_id": "broken"})


def test_rejects_unknown_input_type() -> None:
    with pytest.raises(ValueError, match="unknown input type"):
        parse_method_spec(
            {
                "method_id": "broken",
                "title": "Broken",
                "solves": ["derive_point_coordinate"],
                "inputs": {"x": {"type": "Unknown"}},
                "outputs": {"derived_point": "Point"},
            }
        )


def test_accepts_known_output_union_type() -> None:
    spec = parse_method_spec(
        {
            "method_id": "union_output",
            "title": "Union Output",
            "solves": ["derive_expression"],
            "inputs": {"x": {"type": "Expression|MinimumExpression"}},
            "outputs": {"value": "Expression|MinimumExpression"},
        }
    )

    assert spec.outputs["value"] == "Expression|MinimumExpression"


def test_method_purity_is_explicit_and_legacy_specs_are_conservative() -> None:
    raw = {
        "method_id": "synthetic_method",
        "title": "Synthetic",
        "solves": ["derive_expression"],
        "inputs": {"x": {"type": "Expression"}},
        "outputs": {"value": "Expression"},
    }

    assert parse_method_spec(raw).is_pure is False
    assert parse_method_spec({**raw, "is_pure": True}).is_pure is True
    with pytest.raises(ValueError, match="is_pure must be a boolean"):
        parse_method_spec({**raw, "is_pure": "yes"})

    assert all(
        spec.is_pure
        for spec in MethodSpecRegistry.load_from_code().specs.values()
    )


def test_point_parameter_substitution_is_declared_by_method_spec() -> None:
    spec = MethodSpecRegistry.load_from_code().require(
        "evaluate_point_at_parameter"
    )

    assert spec.plan_transformer == "substitute_all_point_parameters"
    assert spec.reconciliation_validators == ("companion_symbol_coverage",)


def test_reconciliation_validator_declarations_are_normalized() -> None:
    raw = {
        "method_id": "synthetic_method",
        "title": "Synthetic",
        "solves": ["derive_expression"],
        "inputs": {"x": {"type": "Expression"}},
        "outputs": {"value": "Expression"},
        "reconciliation_validators": ["identity_check", "identity_check"],
    }

    assert parse_method_spec(raw).reconciliation_validators == (
        "identity_check",
    )
    with pytest.raises(
        ValueError,
        match="reconciliation_validators must be a list",
    ):
        parse_method_spec({**raw, "reconciliation_validators": "identity_check"})


def test_rejects_unknown_output_union_member() -> None:
    with pytest.raises(ValueError, match="unknown output type"):
        parse_method_spec(
            {
                "method_id": "broken_output",
                "title": "Broken Output",
                "solves": ["derive_expression"],
                "inputs": {"x": {"type": "Expression"}},
                "outputs": {"value": "Expression|Unknown"},
            }
        )
