"""V1.5 MethodSpec 加载测试。

这些测试确保 method 代码里的 SPEC 能被加载成强类型 MethodSpec，并且生成的 JSON
资产没有和代码事实源漂移。
"""

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.runtime.method_specs import (
    MethodSpecRegistry,
    parse_method_spec,
)
from shuxueshuo_server.solver.runtime.methods import method_spec_payloads


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
    assert square_vertex.outputs["point"] == "Point"
    assert curve_condition.inputs["target_point"].type == "Point"
    assert curve_condition.inputs["curve_point"].type == "Point"
    assert curve_condition.outputs["candidates"] == "PointList"
    assert point_at_parameter.inputs["point"].type == "Point"
    assert point_at_parameter.outputs["evaluated_point"] == "Point"
    assert minimum_point.inputs["moving_locus"].type == "Line"
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
