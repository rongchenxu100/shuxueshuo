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


def test_loads_weighted_geometric_path_specs() -> None:
    """加权路径的几何转化与折线最短应作为独立 method 暴露给 planner。"""
    registry = MethodSpecRegistry.load_from_code()
    transform = registry.require("weighted_axis_path_triangle_transform")
    minimum = registry.require("linked_broken_path_geometric_minimum")

    assert transform.inputs["condition"].type == "Condition"
    assert transform.inputs["auxiliary_point_ref"].type == "PointRef"
    assert transform.outputs["auxiliary_point"] == "Point"
    assert transform.outputs["path_transformation"] == "PathTransformation"
    assert transform.outputs["auxiliary_locus"] == "Line"
    assert minimum.inputs["path_transformation"].type == "PathTransformation"
    assert minimum.inputs["auxiliary_locus"].type == "Line"
    assert minimum.inputs["auxiliary_point"].type == "Point"
    assert minimum.outputs["parameter_value"] == "ParameterValue"


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
