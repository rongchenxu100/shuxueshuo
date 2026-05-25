"""V1.5 无状态 method 的直接数学单测。

这些测试不使用 fixture，也不经过 RuntimeContext；目的是证明每个 method 只依赖
typed inputs 和 SympyKernel。
"""

import sympy as sp
import pytest

from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.methods import (
    BrokenPathStraighteningCandidatesMethod,
    DistanceBetweenPointsMethod,
    LineIntersectionPointMethod,
    MidpointPointMethod,
    ParameterFromMinimumValueMethod,
    ParameterFromSegmentLengthMethod,
    ParabolaAtParameterMethod,
    QuadraticAxisFromRelationMethod,
    QuadraticCoefficientsFromCurvePointsMethod,
    QuadraticFromKnownCoefficientsMethod,
    RightAngleEqualLengthCandidatesMethod,
    SelectPointByQuadrantConstraintMethod,
    SelectStraighteningCandidateMethod,
    SquareOppositePointMethod,
    TwoMovingPointsPathReductionMethod,
)
from shuxueshuo_server.solver.runtime.models import PointRef


def test_quadratic_axis_from_relation_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["a", "b"])
    a, b = symbols["a"], symbols["b"]

    result = QuadraticAxisFromRelationMethod().run(
        {
            "coefficient_relation": sp.Eq(2 * a + b, 0),
            "a": a,
            "b": b,
            "target": PointRef("D", "$problem.points.D"),
        },
        kernel,
    )

    assert result.outputs["axis_point"].value == (1, 0)
    assert all(check.ok for check in result.checks)


def test_quadratic_axis_from_relation_rejects_ac_relation() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["a", "b", "c"])
    a, b, c = symbols["a"], symbols["b"], symbols["c"]

    with pytest.raises(ValueError, match="involving both a and b"):
        QuadraticAxisFromRelationMethod().run(
            {
                "coefficient_relation": sp.Eq(a + c, 0),
                "a": a,
                "b": b,
                "target": PointRef("D", "$problem.points.D"),
            },
            kernel,
        )


def test_quadratic_axis_from_relation_rejects_undetermined_ratio() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["a", "b", "c"])
    a, b, c = symbols["a"], symbols["b"], symbols["c"]

    with pytest.raises(ValueError, match="determine b/a ratio"):
        QuadraticAxisFromRelationMethod().run(
            {
                "coefficient_relation": sp.Eq(a + b + c, 0),
                "a": a,
                "b": b,
                "target": PointRef("D", "$problem.points.D"),
            },
            kernel,
        )


def test_quadratic_from_known_coefficients_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = symbols["x"], symbols["a"], symbols["b"], symbols["c"]

    result = QuadraticFromKnownCoefficientsMethod().run(
        {
            "quadratic": a * x**2 + b * x + c,
            "coefficient_relation": sp.Eq(2 * a + b, 0),
            "known_coefficients": {a: 2, c: -5},
            "all_coefficients": [a, b, c],
        },
        kernel,
    )

    assert sp.simplify(result.outputs["parabola"].value - (2 * x**2 - 4 * x - 5)) == 0


def test_quadratic_from_known_coefficients_rejects_incomplete_solution() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = symbols["x"], symbols["a"], symbols["b"], symbols["c"]

    with pytest.raises(ValueError, match="不足以确定所有缺失系数"):
        QuadraticFromKnownCoefficientsMethod().run(
            {
                "quadratic": a * x**2 + b * x + c,
                "coefficient_relation": sp.Eq(2 * a + b, 0),
                "known_coefficients": {a: 2},
                "all_coefficients": [a, b, c],
            },
            kernel,
        )


def test_quadratic_from_known_coefficients_rejects_multiple_solutions() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = symbols["x"], symbols["a"], symbols["b"], symbols["c"]

    with pytest.raises(ValueError, match="不能唯一确定缺失系数"):
        QuadraticFromKnownCoefficientsMethod().run(
            {
                "quadratic": a * x**2 + b * x + c,
                "coefficient_relation": sp.Eq(b**2 - 4, 0),
                "known_coefficients": {a: 2, c: -5},
                "all_coefficients": [a, b, c],
            },
            kernel,
        )


def test_right_angle_equal_length_candidates_method() -> None:
    kernel = SympyKernel()

    result = RightAngleEqualLengthCandidatesMethod().run(
        {
            "anchor": (sp.Integer(1), sp.Integer(0)),
            "reference": (sp.Integer(3), sp.Integer(1)),
            "target": PointRef("N", "$question.ii.points.N"),
        },
        kernel,
    )

    assert result.outputs["candidates"].value == [(2, -2), (0, 2)]
    assert all(check.ok for check in result.checks)


def test_select_point_by_quadrant_constraint_uses_explicit_m_greater_than_2() -> None:
    kernel = SympyKernel()
    m = kernel.symbols(["m"])["m"]

    result = SelectPointByQuadrantConstraintMethod().run(
        {
            "candidates": [(sp.Integer(2), 1 - m), (sp.Integer(0), m - 1)],
            "target": PointRef("N", "$question.ii.points.N"),
            "quadrant": {"quadrant": "第四象限"},
            "parameter": m,
            "parameter_constraint": {"operator": ">", "value": sp.Integer(2)},
        },
        kernel,
    )

    assert result.outputs["selected_point"].value == (2, 1 - m)
    assert all(check.ok for check in result.checks)


def test_select_point_by_quadrant_constraint_rejects_ambiguous_candidates() -> None:
    kernel = SympyKernel()
    m = kernel.symbols(["m"])["m"]

    with pytest.raises(ValueError, match="exactly one"):
        SelectPointByQuadrantConstraintMethod().run(
            {
                "candidates": [(sp.Integer(2), 1 - m), (sp.Integer(3), -m)],
                "target": PointRef("N", "$question.ii.points.N"),
                "quadrant": {"quadrant": "第四象限"},
                "parameter": m,
                "parameter_constraint": {"operator": ">", "value": sp.Integer(2)},
            },
            kernel,
        )


def test_midpoint_point_method() -> None:
    kernel = SympyKernel()

    result = MidpointPointMethod().run(
        {
            "p1": (sp.Integer(0), sp.Integer(2)),
            "p2": (sp.Integer(4), sp.Integer(6)),
            "target": PointRef("F", "$question.ii.points.F"),
        },
        kernel,
    )

    assert result.outputs["midpoint"].value == (2, 4)


def test_quadratic_coefficients_from_curve_points_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c", "m"])
    x, a, b, c, m = (symbols[name] for name in ("x", "a", "b", "c", "m"))

    result = QuadraticCoefficientsFromCurvePointsMethod().run(
        {
            "quadratic": a * x**2 + b * x + c,
            "x": x,
            "p1": (m, 1),
            "p2": (2, 1 - m),
            "coefficient_relation": sp.Eq(2 * a + b, 0),
            "unknowns": [a, b, c],
        },
        kernel,
    )

    assert all(check.ok for check in result.checks)
    assert a in result.outputs["coefficients"].value


def test_parameter_from_segment_length_method() -> None:
    kernel = SympyKernel()
    m = kernel.symbols(["m"])["m"]

    result = ParameterFromSegmentLengthMethod().run(
        {
            "p1": (m, 1),
            "p2": (2, 1 - m),
            "parameter": m,
            "condition": {"value": "10"},
            "constraint": {"operator": ">", "value": sp.Integer(2)},
        },
        kernel,
    )

    assert result.outputs["parameter_value"].value == 3


def test_parabola_at_parameter_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "m"])
    x, m = symbols["x"], symbols["m"]

    result = ParabolaAtParameterMethod().run(
        {"parabola": m * x**2, "parameter": m, "parameter_value": sp.Integer(3)},
        kernel,
    )

    assert result.outputs["parabola"].value == 3 * x**2


def test_two_moving_points_path_reduction_method() -> None:
    kernel = SympyKernel()
    m = kernel.symbols(["m"])["m"]

    result = TwoMovingPointsPathReductionMethod().run(
        {
            "original_path": {"path": "EG+FG"},
            "first_moving_membership": {
                "point": "E",
                "segment": ["D", "M"],
            },
            "second_moving_membership": {
                "point": "G",
                "segment": ["M", "N"],
            },
            "binding_relation": {
                "left": "DE",
                "right": "sqrt(2)*NG",
                "description": "DE=√2·NG",
            },
            "first_segment_start": (sp.Integer(1), sp.Integer(0)),
            "joint_point": (m, sp.Integer(1)),
            "second_segment_end": (sp.Integer(2), 1 - m),
        },
        kernel,
    )

    transformation = result.outputs["path_transformation"].value
    assert transformation["original_path"] == "EG+FG"
    assert transformation["transformed_path"] == "DG+FG"
    assert transformation["segment_equality"] == "EG=DG"
    assert all(check.ok for check in result.checks)


def test_broken_path_straightening_candidates_method() -> None:
    kernel = SympyKernel()
    m = kernel.symbols(["m"])["m"]

    result = BrokenPathStraighteningCandidatesMethod().run(
        {
            "path_transformation": {
                "original_path": "EG+FG",
                "transformed_path": "DG+FG",
                "segment_equality": "EG=DG",
            },
            "moving_point_membership": {
                "point": "G",
                "segment": ["M", "N"],
            },
            "fixed_point_1": (sp.Integer(1), sp.Integer(0)),
            "fixed_point_2": (sp.Rational(3, 2), sp.Rational(1, 2) - m / 2),
            "line_point_1": (m, sp.Integer(1)),
            "line_point_2": (sp.Integer(2), 1 - m),
        },
        kernel,
    )

    candidates = result.outputs["candidates"].value
    by_name = {candidate["reflected_point_name"]: candidate for candidate in candidates}
    assert by_name["D_prime"]["reflected_point"] == (m + 1, 2 - m)
    assert by_name["D_prime"]["minimum_segment"] == "D_primeF"
    assert by_name["F_prime"]["reflected_point"] == (m / 2 + sp.Rational(3, 2), sp.Rational(3, 2) - m)
    assert all(check.ok for check in result.checks)


def test_select_straightening_candidate_prefers_simpler_reflection() -> None:
    kernel = SympyKernel()
    m = kernel.symbols(["m"])["m"]
    candidates = BrokenPathStraighteningCandidatesMethod().run(
        {
            "path_transformation": {
                "original_path": "EG+FG",
                "transformed_path": "DG+FG",
                "segment_equality": "EG=DG",
            },
            "moving_point_membership": {
                "point": "G",
                "segment": ["M", "N"],
            },
            "fixed_point_1": (sp.Integer(1), sp.Integer(0)),
            "fixed_point_2": (sp.Rational(3, 2), sp.Rational(1, 2) - m / 2),
            "line_point_1": (m, sp.Integer(1)),
            "line_point_2": (sp.Integer(2), 1 - m),
        },
        kernel,
    ).outputs["candidates"].value

    result = SelectStraighteningCandidateMethod().run(
        {
            "candidates": candidates,
            "target": PointRef("D_prime", "$question.ii.points.D_prime"),
        },
        kernel,
    )

    selected = result.outputs["selected_candidate"].value
    assert selected["reflected_point_name"] == "D_prime"
    assert result.outputs["auxiliary_point"].value == (m + 1, 2 - m)
    assert all(check.ok for check in result.checks)


def test_square_opposite_point_method() -> None:
    kernel = SympyKernel()

    result = SquareOppositePointMethod().run(
        {
            "vertex": (1, 0),
            "adjacent1": (3, 1),
            "adjacent2": (2, -2),
            "target": PointRef("D_prime", "$question.ii.points.D_prime"),
        },
        kernel,
    )

    assert result.outputs["point"].value == (4, -1)


def test_distance_between_points_method() -> None:
    kernel = SympyKernel()

    result = DistanceBetweenPointsMethod().run(
        {"p1": (0, 0), "p2": (3, 4)},
        kernel,
    )

    assert result.outputs["distance"].value == 5


def test_parameter_from_minimum_value_method() -> None:
    kernel = SympyKernel()
    m = kernel.symbols(["m"])["m"]

    result = ParameterFromMinimumValueMethod().run(
        {
            "minimum_expression": m + 1,
            "condition": {"value": "5"},
            "parameter": m,
            "constraint": {"operator": ">", "value": sp.Integer(2)},
        },
        kernel,
    )

    assert result.outputs["parameter_value"].value == 4


def test_line_intersection_point_method() -> None:
    kernel = SympyKernel()

    result = LineIntersectionPointMethod().run(
        {
            "line1_p1": (0, 0),
            "line1_p2": (2, 0),
            "line2_p1": (1, -1),
            "line2_p2": (1, 1),
            "target": PointRef("G", "$question.ii.points.G"),
        },
        kernel,
    )

    assert result.outputs["intersection"].value == (1, 0)
