"""V1.5 无状态 method 的直接数学单测。

这些测试不使用 fixture，也不经过 RuntimeContext；目的是证明每个 method 只依赖
typed inputs 和 SympyKernel。
"""

import sympy as sp
import pytest

from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.methods import (
    AngleSumEqualAngleCandidatesMethod,
    AxisInterceptFromEqualAcuteAnglesMethod,
    BrokenPathStraighteningCandidatesMethod,
    CoefficientAtParameterMethod,
    DistanceBetweenPointsMethod,
    EqualLengthRayPointMethod,
    EvaluateExpressionAtParameterMethod,
    EvaluatePointAtParameterMethod,
    FilterPointCandidatesByQuadraticCurveMethod,
    LineLocusMinimumPointMethod,
    LineParabolaSecondIntersectionPointMethod,
    LineIntersectionPointMethod,
    LinkedBrokenPathGeometricMinimumMethod,
    LinkedBrokenPathMinimumExpressionMethod,
    MidpointPointMethod,
    ParameterFromExpressionValueMethod,
    ParameterFromMinimumValueMethod,
    ParameterFromSegmentLengthMethod,
    ParameterFromCurvePointOnQuadraticMethod,
    ParabolaAtParameterMethod,
    PointOnParabolaAtXMethod,
    PointCandidatesFromCurvePointConditionMethod,
    ParameterizedPointLocusLineMethod,
    QuadraticAxisFromRelationMethod,
    QuadraticAxisParameterizedPointMethod,
    QuadraticFromConstraintsMethod,
    QuadraticXAxisInterceptPointMethod,
    QuadraticVertexPointMethod,
    QuadraticYAxisInterceptPointMethod,
    RightAngleEqualLengthCandidatesMethod,
    SelectCurvePointCandidateAndSolveCoefficientsMethod,
    SelectPointByQuadrantConstraintMethod,
    SelectStraighteningCandidateMethod,
    SquareAdjacentVertexFromSideMethod,
    SquareOppositePointMethod,
    SquarePathDimensionReductionMethod,
    TwoMovingPointsPathReductionMethod,
    TranslatedPointMethod,
    WeightedAxisPathTriangleTransformMethod,
)
from shuxueshuo_server.solver.runtime.models import PointRef
from shuxueshuo_server.solver.runtime.symbolic_target_closure import (
    solve_target_symbol_closure,
)
from shuxueshuo_server.solver.runtime.methods.quadratic_from_constraints import (
    analyze_quadratic_constraints,
)


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


def test_target_symbol_closure_solves_joint_system_before_classifying() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "y"])
    x, y = symbols["x"], symbols["y"]

    result = solve_target_symbol_closure(
        [sp.Eq(x + y, 3), sp.Eq(x - y, 1)],
        target=x,
        kernel=kernel,
    )

    assert result.status == "unique"
    assert result.target_value == 2
    assert result.substitution == {x: 2, y: 1}


def test_target_symbol_closure_accepts_unique_target_across_auxiliary_branches() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "y"])
    x, y = symbols["x"], symbols["y"]

    result = solve_target_symbol_closure(
        [sp.Eq(x, 2), sp.Eq(y**2, 1)],
        target=x,
        kernel=kernel,
    )

    assert result.status == "unique"
    assert result.target_value == 2
    assert result.substitution == {x: 2}


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


def test_quadratic_from_constraints_with_known_coefficients_and_relation() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = symbols["x"], symbols["a"], symbols["b"], symbols["c"]

    result = QuadraticFromConstraintsMethod().run(
        {
            "quadratic": a * x**2 + b * x + c,
            "x": x,
            "coefficient_relation": sp.Eq(2 * a + b, 0),
            "known_coefficients": {a: 2, c: -5},
            "all_coefficients": [a, b, c],
        },
        kernel,
    )

    assert sp.simplify(result.outputs["parabola"].value - (2 * x**2 - 4 * x - 5)) == 0


def test_quadratic_from_constraints_ignores_tautological_curve_point() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b", "c"])
    x, b, c = symbols["x"], symbols["b"], symbols["c"]

    result = QuadraticFromConstraintsMethod().run(
        {
            "quadratic": -x**2 + b * x + c,
            "x": x,
            "all_coefficients": [b],
            "p1": (0, c),
            "p2": (-c, 0),
        },
        kernel,
    )

    expected = -x**2 + (1 - c) * x + c
    assert sp.simplify(result.outputs["parabola"].value - expected) == 0
    assert all(check.ok for check in result.checks)


def test_quadratic_axis_parameterized_point_method() -> None:
    kernel = SympyKernel()
    x = kernel.symbols(["x"])["x"]

    result = QuadraticAxisParameterizedPointMethod().run(
        {
            "parabola": -x**2 - 2 * x + 3,
            "x": x,
            "target": PointRef("E", "$subquestion.i_2.points.E"),
        },
        kernel,
    )

    point = result.outputs["point"].value
    assert point[0] == -1
    assert point[1].name == "_axis_param_E"
    assert result.outputs["parameter"].type == "Symbol"
    assert result.outputs["parameter"].value is point[1]
    assert all(check.ok for check in result.checks)


def test_square_adjacent_vertex_from_side_method_uses_square_orientation() -> None:
    kernel = SympyKernel()
    t = sp.Symbol("_axis_param_E", real=True)

    result = SquareAdjacentVertexFromSideMethod().run(
        {
            "side_start": (sp.Integer(-3), sp.Integer(0)),
            "side_end": (sp.Integer(-1), t),
            "square_condition": {
                "type": "square",
                "vertices": [
                    "point:problem:A",
                    "point:i_2:E",
                    "point:i_2:K",
                    "point:i_2:G",
                ],
                "orientation": "below_x_axis",
            },
            "target": PointRef("G", "$subquestion.i_2.points.G"),
        },
        kernel,
    )

    assert result.outputs["point"].value == (t - 3, -2)
    assert all(check.ok for check in result.checks)


def test_square_adjacent_vertex_from_side_method_accepts_known_ag_side() -> None:
    kernel = SympyKernel()

    result = SquareAdjacentVertexFromSideMethod().run(
        {
            "side_start": (sp.Integer(-5), sp.Integer(0)),
            "side_end": (sp.Rational(-7, 2), sp.Integer(-3)),
            "square_condition": {
                "type": "square",
                "vertices": [
                    "point:ii:A",
                    "point:ii:E",
                    "point:ii:K",
                    "point:ii:G",
                ],
                "orientation": "below_x_axis",
            },
            "target": PointRef("E", "$question.ii.points.E"),
        },
        kernel,
    )

    assert result.outputs["point"].value == (sp.Integer(-2), sp.Rational(3, 2))
    assert all(check.ok for check in result.checks)


def test_point_candidates_from_curve_point_condition_method() -> None:
    kernel = SympyKernel()
    x = kernel.symbols(["x"])["x"]
    t = sp.Symbol("_axis_param_E", real=True)

    result = PointCandidatesFromCurvePointConditionMethod().run(
        {
            "target_point": (sp.Integer(-1), t),
            "curve_point": (t - 3, sp.Integer(-2)),
            "parabola": -x**2 - 2 * x + 3,
            "x": x,
        },
        kernel,
    )

    candidates = result.outputs["candidates"].value
    assert set(candidates) == {
        (sp.Integer(-1), 2 - sp.sqrt(6)),
        (sp.Integer(-1), 2 + sp.sqrt(6)),
    }
    assert all(check.ok for check in result.checks)


def test_angle_sum_equal_angle_candidates_method_heping_geometry() -> None:
    kernel = SympyKernel()

    result = AngleSumEqualAngleCandidatesMethod().run(
        {
            "condition": {
                "type": "angle_sum",
                "description": "∠CBE+∠ACO=45°",
                "angle_terms": ["CBE", "ACO"],
                "value": "45",
            },
            "x_axis_point": (sp.Integer(3), sp.Integer(0)),
            "y_axis_point": (sp.Integer(0), sp.Integer(-3)),
            "reference_x_axis_point": (sp.Integer(-1), sp.Integer(0)),
            "origin": (sp.Integer(0), sp.Integer(0)),
            "target": PointRef("F", "$subquestion.i_2.points.F"),
        },
        kernel,
    )

    assert result.outputs["angle_equality"].type == "AngleEquality"
    assert result.outputs["angle_equality"].value["left_angle"] == "OBF"
    assert result.outputs["angle_equality"].value["right_angle"] == "ACO"
    assert all(check.ok for check in result.checks)


def test_axis_intercept_from_equal_acute_angles_method_heping_geometry() -> None:
    kernel = SympyKernel()

    result = AxisInterceptFromEqualAcuteAnglesMethod().run(
        {
            "angle_equality": {"left_angle": "OBF", "right_angle": "ACO"},
            "x_axis_point": (sp.Integer(3), sp.Integer(0)),
            "y_axis_point": (sp.Integer(0), sp.Integer(-3)),
            "reference_x_axis_point": (sp.Integer(-1), sp.Integer(0)),
            "origin": (sp.Integer(0), sp.Integer(0)),
            "target": PointRef("F", "$subquestion.i_2.points.F"),
        },
        kernel,
    )

    assert result.outputs["point"].value == (0, -1)
    assert all(check.ok for check in result.checks)


def test_translated_point_method_uses_target_definition_vector() -> None:
    kernel = SympyKernel()

    result = TranslatedPointMethod().run(
        {
            "source": (sp.Integer(0), sp.Integer(-3)),
            "target": PointRef(
                "D",
                "$problem.points.D",
                definition={"definition": "translated_point", "of": "C", "vector": ["2", "0"]},
            ),
        },
        kernel,
    )

    assert result.outputs["point"].value == (2, -3)
    assert all(check.ok for check in result.checks)


def test_line_parabola_second_intersection_point_method_heping_geometry() -> None:
    kernel = SympyKernel()
    x = kernel.symbols(["x"])["x"]

    result = LineParabolaSecondIntersectionPointMethod().run(
        {
            "parabola": x**2 - 2 * x - 3,
            "x": x,
            "line_p1": (sp.Integer(3), sp.Integer(0)),
            "line_p2": (sp.Integer(0), sp.Integer(-1)),
            "known_point": (sp.Integer(3), sp.Integer(0)),
            "target": PointRef(
                "E",
                "$subquestion.i_2.points.E",
                definition={"x_range": ["-1", "0"]},
            ),
        },
        kernel,
    )

    assert result.outputs["point"].value == (sp.Rational(-2, 3), sp.Rational(-11, 9))
    assert all(check.ok for check in result.checks)


def test_equal_length_ray_point_method_heping_geometry() -> None:
    kernel = SympyKernel()
    a = kernel.symbols(["a"])["a"]

    result = EqualLengthRayPointMethod().run(
        {
            "anchor": (sp.Integer(0), sp.Integer(-3)),
            "reference_point": (sp.Integer(3) / a, sp.Integer(0)),
            "ray_point": (sp.Integer(2), sp.Integer(-3)),
            "target": PointRef("G", "$question.ii.points.G"),
        },
        kernel,
    )

    point = result.outputs["point"].value
    assert sp.simplify(point[1] + 3) == 0
    assert sp.simplify(kernel.distance_squared((0, -3), point) - (9 / a**2 + 9)) == 0
    assert all(check.ok for check in result.checks)


def test_quadratic_from_constraints_rejects_incomplete_solution() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = symbols["x"], symbols["a"], symbols["b"], symbols["c"]

    with pytest.raises(ValueError, match="约束不足以确定系数"):
        QuadraticFromConstraintsMethod().run(
            {
                "quadratic": a * x**2 + b * x + c,
                "x": x,
                "coefficient_relation": sp.Eq(2 * a + b, 0),
                "known_coefficients": {a: 2},
                "all_coefficients": [a, b, c],
            },
            kernel,
        )


def test_quadratic_constraint_analysis_classifies_solution_shape() -> None:
    x, alpha, beta, gamma = sp.symbols("x alpha beta gamma")
    quadratic = alpha * x**2 + beta * x + gamma
    base = {
        "quadratic": quadratic,
        "x": x,
        "all_coefficients": [alpha, beta, gamma],
    }

    single_free = analyze_quadratic_constraints(
        {
            **base,
            "known_coefficients": {alpha: 1},
            "curve_point": sp.Point(0, 2),
        }
    )
    underdetermined = analyze_quadratic_constraints(base)
    ambiguous = analyze_quadratic_constraints(
        {
            **base,
            "known_coefficients": {alpha: 1, gamma: 0},
            "extra_equation": sp.Eq(beta**2, 1),
        }
    )

    assert single_free.status == "single_free"
    assert single_free.free_parameters == (beta,)
    assert underdetermined.status == "underdetermined"
    assert underdetermined.free_parameters == (alpha, beta, gamma)
    assert ambiguous.status == "ambiguous"
    assert ambiguous.branch_count == 2


def test_quadratic_from_constraints_rejects_multiple_solutions() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = symbols["x"], symbols["a"], symbols["b"], symbols["c"]

    with pytest.raises(ValueError, match="不能唯一确定缺失系数"):
        QuadraticFromConstraintsMethod().run(
            {
                "quadratic": a * x**2 + b * x + c,
                "x": x,
                "coefficient_relation": sp.Eq(b**2 - 4, 0),
                "known_coefficients": {a: 2, c: -5},
                "all_coefficients": [a, b, c],
            },
            kernel,
        )


def test_quadratic_from_constraints_with_all_known_coefficients() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (symbols[name] for name in ("x", "a", "b", "c"))

    result = QuadraticFromConstraintsMethod().run(
        {
            "quadratic": a * x**2 - b * x + c,
            "x": x,
            "known_coefficients": {a: 1, b: 2, c: 3},
            "all_coefficients": [a, b, c],
        },
        kernel,
    )

    assert sp.simplify(result.outputs["parabola"].value - (x**2 - 2 * x + 3)) == 0


def test_quadratic_from_constraints_keeps_free_parameter() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (symbols[name] for name in ("x", "a", "b", "c"))

    result = QuadraticFromConstraintsMethod().run(
        {
            "quadratic": a * x**2 - b * x + c,
            "x": x,
            "known_coefficients": {a: 1},
            "all_coefficients": [a, b, c],
            "curve_point": (-1, 0),
            "free_parameter": b,
        },
        kernel,
    )

    assert sp.simplify(result.outputs["coefficients"].value[c] - (-b - 1)) == 0
    assert sp.simplify(result.outputs["parabola"].value - (x**2 - b * x - b - 1)) == 0


def test_quadratic_from_constraints_substitutes_a_and_curve_point() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (symbols[name] for name in ("x", "a", "b", "c"))

    result = QuadraticFromConstraintsMethod().run(
        {
            "quadratic": a * x**2 - b * x + c,
            "x": x,
            "known_coefficients": {a: 2},
            "all_coefficients": [a, b, c],
            "curve_point": (-1, 0),
            "free_parameter": b,
        },
        kernel,
    )

    assert sp.simplify(result.outputs["coefficients"].value[c] - (-b - 2)) == 0
    assert sp.simplify(result.outputs["parabola"].value - (2 * x**2 - b * x - b - 2)) == 0


def test_quadratic_from_constraints_allows_multiple_free_coefficients() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (symbols[name] for name in ("x", "a", "b", "c"))

    result = QuadraticFromConstraintsMethod().run(
        {
            "quadratic": a * x**2 - b * x + c,
            "x": x,
            "known_coefficients": {a: 2},
            "all_coefficients": [a, b, c],
            "free_parameters": [b, c],
        },
        kernel,
    )

    assert result.outputs["coefficients"].value == {a: 2}
    assert sp.simplify(result.outputs["parabola"].value - (2 * x**2 - b * x + c)) == 0


def test_quadratic_vertex_point_method() -> None:
    kernel = SympyKernel()
    x = kernel.symbols(["x"])["x"]

    result = QuadraticVertexPointMethod().run(
        {
            "parabola": x**2 - 2 * x + 3,
            "x": x,
            "target": PointRef("P", "$question.i.points.P"),
        },
        kernel,
    )

    assert result.outputs["point"].value == (1, 2)


def test_quadratic_y_axis_intercept_point_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (symbols[name] for name in ("x", "a", "b", "c"))

    result = QuadraticYAxisInterceptPointMethod().run(
        {
            "quadratic": a * x**2 - b * x + c,
            "x": x,
            "target": PointRef("C", "$question.ii.points.C"),
        },
        kernel,
    )

    assert result.outputs["point"].value == (0, c)


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


def test_right_angle_equal_length_candidates_keep_symbolic_endpoint() -> None:
    """已知直角边端点含参数时，旋转候选应保留符号表达式。"""
    kernel = SympyKernel()
    b = kernel.symbols(["b"])["b"]

    result = RightAngleEqualLengthCandidatesMethod().run(
        {
            "anchor": (sp.Integer(-1), sp.Integer(0)),
            "reference": (sp.Integer(0), -b - 2),
            "target": PointRef("D", "$question.ii.points.D"),
        },
        kernel,
    )

    assert result.outputs["candidates"].value == [(-b - 3, -1), (b + 1, 1)]
    assert all(check.ok for check in result.checks)


def test_select_curve_point_candidate_and_solve_coefficients_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (symbols[name] for name in ("x", "a", "b", "c"))
    candidates = RightAngleEqualLengthCandidatesMethod().run(
        {
            "anchor": (-1, 0),
            "reference": (0, c),
            "target": PointRef("D", "$question.ii.points.D"),
        },
        kernel,
    ).outputs["candidates"].value

    result = SelectCurvePointCandidateAndSolveCoefficientsMethod().run(
        {
            "candidates": candidates,
            "target": PointRef("D", "$question.ii.points.D"),
            "quadratic": a * x**2 - b * x + c,
            "x": x,
            "curve_point": (-1, 0),
            "known_coefficients": {a: 2},
            "unknowns": [a, b, c],
            "primary_symbol": b,
            "secondary_symbol": c,
            "primary_constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    assert sp.simplify(result.outputs["primary_value"].value - (-1 + sp.sqrt(2))) == 0
    assert sp.simplify(result.outputs["secondary_value"].value - (-1 - sp.sqrt(2))) == 0
    assert result.outputs["point"].value == (sp.sqrt(2), 1)


def test_select_curve_point_candidate_uses_pre_substituted_parabola() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (symbols[name] for name in ("x", "a", "b", "c"))
    parametric_parabola = 2 * x**2 - b * x - b - 2
    candidates = RightAngleEqualLengthCandidatesMethod().run(
        {
            "anchor": (-1, 0),
            "reference": (0, -b - 2),
            "target": PointRef("D", "$question.ii.points.D"),
        },
        kernel,
    ).outputs["candidates"].value

    result = SelectCurvePointCandidateAndSolveCoefficientsMethod().run(
        {
            "candidates": candidates,
            "target": PointRef("D", "$question.ii.points.D"),
            "quadratic": parametric_parabola,
            "x": x,
            "coefficient_dependencies": {a: 2, c: -b - 2},
            "primary_symbol": b,
            "secondary_symbol": c,
            "primary_constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    assert sp.simplify(result.outputs["primary_value"].value - (-1 + sp.sqrt(2))) == 0
    assert sp.simplify(result.outputs["secondary_value"].value - (-1 - sp.sqrt(2))) == 0
    assert result.outputs["point"].value == (sp.sqrt(2), 1)


def test_filter_point_candidates_by_quadratic_curve_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b"])
    x, b = symbols["x"], symbols["b"]

    result = FilterPointCandidatesByQuadraticCurveMethod().run(
        {
            "candidates": [(-b - 3, -1), (b + 1, 1)],
            "target": PointRef("D", "$question.ii.points.D"),
            "parabola": 2 * x**2 - b * x - b - 2,
            "x": x,
            "parameter": b,
            "parameter_constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    assert result.outputs["filtered_candidates"].value == [(b + 1, 1)]
    assert result.outputs["rejected_candidates"].value == [(-b - 3, -1)]
    assert result.outputs["selected_candidate"].value == (b + 1, 1)
    assert all(check.ok for check in result.checks)


def test_filter_point_candidates_by_quadratic_curve_keeps_all_valid_candidates() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b"])
    x, b = symbols["x"], symbols["b"]

    result = FilterPointCandidatesByQuadraticCurveMethod().run(
        {
            "candidates": [(sp.Integer(0), sp.Integer(1)), (sp.Integer(1), sp.Integer(2))],
            "target": PointRef("T", "$question.ii.points.T"),
            "parabola": x**2 + b,
            "x": x,
            "parameter": b,
            "parameter_constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    assert result.outputs["filtered_candidates"].value == [(sp.Integer(0), sp.Integer(1)), (sp.Integer(1), sp.Integer(2))]
    assert result.outputs["rejected_candidates"].value == []


def test_parameter_from_curve_point_on_quadratic_method() -> None:
    """含参点代入含参抛物线后，应反求参数并代回点和抛物线。"""
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b"])
    x, b = symbols["x"], symbols["b"]

    result = ParameterFromCurvePointOnQuadraticMethod().run(
        {
            "quadratic": 2 * x**2 - b * x - b - 2,
            "x": x,
            "point": (b + 1, sp.Integer(1)),
            "parameter": b,
            "parameter_constraint": {"operator": ">", "value": 0},
        },
        kernel,
    )

    parameter_value = -1 + sp.sqrt(2)
    assert sp.simplify(result.outputs["parameter_value"].value - parameter_value) == 0
    assert result.outputs["point"].value == (sp.sqrt(2), sp.Integer(1))
    assert sp.simplify(
        result.outputs["parabola"].value
        - (2 * x**2 + (1 - sp.sqrt(2)) * x - 1 - sp.sqrt(2))
    ) == 0
    assert all(check.ok for check in result.checks)
    assert all(check.ok for check in result.checks)


def test_parameter_from_curve_point_specializes_known_symbol_before_solving() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "u", "v"])
    x, u, v = symbols["x"], symbols["u"], symbols["v"]

    result = ParameterFromCurvePointOnQuadraticMethod().run(
        {
            "quadratic": u * x**2 - 2 * u * x + 1 - u * v**2 + 2 * u * v,
            "x": x,
            "point": (sp.Integer(2), sp.Integer(-2)),
            "parameter": u,
            "parameter_constraint": {"operator": ">", "value": 0},
            "known_parameter": v,
            "known_parameter_value": sp.Integer(3),
        },
        kernel,
    )

    assert result.outputs["parameter_value"].value == 1
    assert result.outputs["point"].value == (sp.Integer(2), sp.Integer(-2))
    assert sp.expand(result.outputs["parabola"].value) == x**2 - 2 * x - 2


def test_parameter_from_curve_point_closes_residual_coefficient_to_target() -> None:
    """A uniquely solved residual coefficient may map back to the bound target."""
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (symbols[name] for name in ("x", "a", "b", "c"))
    parabola_in_c = (1 - c) * x**2 / 3 - 2 * (1 - c) * x / 3 + c

    result = ParameterFromCurvePointOnQuadraticMethod().run(
        {
            "quadratic": parabola_in_c,
            "x": x,
            "point": (sp.Integer(2), sp.Integer(-2)),
            "parameter": a,
            "quadratic_template": a * x**2 + b * x + c,
        },
        kernel,
    )

    assert result.outputs["parameter_value"].value == 1
    assert result.outputs["point"].value == (sp.Integer(2), sp.Integer(-2))
    assert sp.expand(result.outputs["parabola"].value) == x**2 - 2 * x - 2


def test_parameter_closure_uses_quadratic_template_coefficient_sign() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c", "q"])
    x, a, b, c, q = (symbols[name] for name in ("x", "a", "b", "c", "q"))

    result = ParameterFromCurvePointOnQuadraticMethod().run(
        {
            "quadratic": x**2 - q * x,
            "quadratic_template": a * x**2 - b * x + c,
            "x": x,
            "point": (sp.Integer(1), sp.Integer(0)),
            "parameter": b,
        },
        kernel,
    )

    assert result.outputs["parameter_value"].value == 1
    assert sp.expand(result.outputs["parabola"].value) == x**2 - x


def test_parameter_from_curve_point_rejects_multiple_unresolved_symbols() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "u", "v"])
    x, u, v = symbols["x"], symbols["u"], symbols["v"]

    with pytest.raises(ValueError, match="function.constraints_underdetermined"):
        ParameterFromCurvePointOnQuadraticMethod().run(
            {
                "quadratic": u * x**2 - 2 * u * x + 1 - u * v**2 + 2 * u * v,
                "x": x,
                "point": (sp.Integer(2), sp.Integer(-2)),
                "parameter": u,
                "parameter_constraint": {"operator": ">", "value": 0},
            },
            kernel,
        )


def test_parameter_from_curve_point_reports_actual_residual_symbol() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "u", "v", "w"])
    x, u, v, w = (
        symbols["x"],
        symbols["u"],
        symbols["v"],
        symbols["w"],
    )

    with pytest.raises(
        ValueError,
        match=r"function.parameter_identity_mismatch: target=w, residual_symbols=u",
    ):
        ParameterFromCurvePointOnQuadraticMethod().run(
            {
                "quadratic": u * x**2 - 2 * u * x + 1 - u * v**2 + 2 * u * v,
                "x": x,
                "point": (sp.Integer(2), sp.Integer(-2)),
                "parameter": w,
                "known_parameter": v,
                "known_parameter_value": sp.Integer(3),
            },
            kernel,
        )


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


def test_quadratic_from_constraints_with_curve_points_and_relation() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c", "m"])
    x, a, b, c, m = (symbols[name] for name in ("x", "a", "b", "c", "m"))

    result = QuadraticFromConstraintsMethod().run(
        {
            "quadratic": a * x**2 + b * x + c,
            "x": x,
            "p1": (m, 1),
            "p2": (2, 1 - m),
            "coefficient_relation": sp.Eq(2 * a + b, 0),
            "all_coefficients": [a, b, c],
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


def test_parameter_from_segment_length_method_supports_segment_relation() -> None:
    kernel = SympyKernel()
    b = kernel.symbols(["b"])["b"]

    result = ParameterFromSegmentLengthMethod().run(
        {
            "p1": (-1, 0),
            "p2": (b + 2, -2 * b - 2),
            "reference_p1": (b + 1, 0),
            "reference_p2": (0, b + 1),
            "parameter": b,
            "condition": {
                "type": "segment_length_relation",
                "left_segment": "AD",
                "right_segment": "BC",
                "scale": "2",
            },
            "constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    assert result.outputs["parameter_value"].value == 1
    assert all(check.ok for check in result.checks)


def test_parabola_at_parameter_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "m"])
    x, m = symbols["x"], symbols["m"]

    result = ParabolaAtParameterMethod().run(
        {"parabola": m * x**2, "parameter": m, "parameter_value": sp.Integer(3)},
        kernel,
    )

    assert result.outputs["parabola"].value == 3 * x**2


def test_point_on_parabola_at_x_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b"])
    x, b = symbols["x"], symbols["b"]

    result = PointOnParabolaAtXMethod().run(
        {
            "parabola": x**2 - b * x - b - 1,
            "x": x,
            "target": PointRef(
                "M",
                "$question.iii.points.M",
                definition={"definition": "point_on_parabola_at_x", "x": "b + 1/2"},
            ),
        },
        kernel,
    )

    assert result.outputs["point"].value == (b + sp.Rational(1, 2), -b / 2 - sp.Rational(3, 4))


def test_quadratic_x_axis_intercept_point_method_returns_other_root() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b"])
    x, b = symbols["x"], symbols["b"]

    result = QuadraticXAxisInterceptPointMethod().run(
        {
            "quadratic": -x**2 + b * x + b + 1,
            "x": x,
            "target": PointRef(
                "B",
                "$question.ii.points.B",
                definition={"definition": "x_axis_intercept", "exclude_point": "A"},
            ),
            "known_point": (-1, 0),
        },
        kernel,
    )

    assert result.outputs["point"].value == (b + 1, 0)
    assert all(check.ok for check in result.checks)


def test_quadratic_x_axis_intercept_point_method_uses_left_target_side() -> None:
    kernel = SympyKernel()
    x = kernel.symbols(["x"])["x"]

    result = QuadraticXAxisInterceptPointMethod().run(
        {
            "quadratic": -x**2 - 2 * x + 3,
            "x": x,
            "target": PointRef(
                "A",
                "$problem.points.A",
                definition={"definition": "x_axis_intercept", "side": "left"},
            ),
        },
        kernel,
    )

    assert result.outputs["point"].value == (-3, 0)
    assert all(check.ok for check in result.checks)


def test_quadratic_x_axis_intercept_point_method_uses_right_target_side() -> None:
    kernel = SympyKernel()
    x = kernel.symbols(["x"])["x"]

    result = QuadraticXAxisInterceptPointMethod().run(
        {
            "quadratic": -x**2 - 2 * x + 3,
            "x": x,
            "target": PointRef(
                "B",
                "$problem.points.B",
                definition={"definition": "x_axis_intercept", "side": "right"},
            ),
        },
        kernel,
    )

    assert result.outputs["point"].value == (1, 0)
    assert all(check.ok for check in result.checks)


def test_two_moving_points_path_reduction_method() -> None:
    kernel = SympyKernel()
    m = kernel.symbols(["m"])["m"]

    result = TwoMovingPointsPathReductionMethod().run(
        {
            "original_path": {
                "path": "EG+FG",
                "condition_ref": "fact:ii:path_minimum_target",
                "terms": [
                    ["point:ii:E", "point:ii:G"],
                    ["point:ii:F", "point:ii:G"],
                ],
            },
            "first_moving_membership": {
                "point": "E",
                "segment": ["D", "M"],
                "condition_ref": "fact:ii:segment_E_on_DM",
                "point_ref": "point:ii:E",
                "segment_ref": "segment:ii:DM",
                "segment_endpoint_refs": [
                    "point:problem:D",
                    "point:ii:M",
                ],
            },
            "second_moving_membership": {
                "point": "G",
                "segment": ["M", "N"],
                "condition_ref": "fact:ii:segment_G_on_MN",
                "point_ref": "point:ii:G",
                "segment_ref": "segment:ii:MN",
                "segment_endpoint_refs": [
                    "point:ii:M",
                    "point:ii:N",
                ],
            },
            "binding_relation": {
                "left": "DE",
                "right": "sqrt(2)*NG",
                "description": "DE=√2·NG",
                "condition_ref": "fact:ii:segment_DE_eq_sqrt2_NG",
                "left_term": {
                    "scale": "1",
                    "segment": ["point:problem:D", "point:ii:E"],
                },
                "right_term": {
                    "scale": "sqrt(2)",
                    "segment": ["point:ii:N", "point:ii:G"],
                },
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
    assert transformation["type"] == "existing_fixed_endpoint_replacement"
    assert transformation["replacement_fixed_endpoint"] == "D"
    assert transformation["replacement_moving_point"] == "G"
    assert transformation["creates_auxiliary_point"] is False
    assert transformation["transformed_terms"] == [
        ["point:problem:D", "point:ii:G"],
        ["point:ii:F", "point:ii:G"],
    ]
    assert transformation["moving_point_ref"] == "point:ii:G"
    assert transformation["fixed_endpoint_refs"] == [
        "point:problem:D",
        "point:ii:F",
    ]
    assert transformation["moving_locus_condition_ref"] == (
        "fact:ii:segment_G_on_MN"
    )
    assert transformation["moving_locus_endpoint_refs"] == [
        "point:ii:M",
        "point:ii:N",
    ]
    assert transformation["source_condition_refs"] == [
        "fact:ii:path_minimum_target",
        "fact:ii:segment_E_on_DM",
        "fact:ii:segment_G_on_MN",
        "fact:ii:segment_DE_eq_sqrt2_NG",
    ]
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


def test_parameter_from_expression_value_method() -> None:
    """通用表达式取值反求参数不关心表达式来源是否叫“最小值”。"""
    kernel = SympyKernel()
    b = kernel.symbols(["b"])["b"]

    result = ParameterFromExpressionValueMethod().run(
        {
            "expression": sp.Rational(21, 8) * b,
            "condition": {"value": "21/4"},
            "parameter": b,
            "constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    assert result.outputs["parameter_value"].value == 2
    assert all(check.ok for check in result.checks)


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


def test_weighted_axis_path_triangle_transform_method() -> None:
    """加权路径先由辅助等腰直角三角形转成普通折线路径。"""
    kernel = SympyKernel()
    symbols = kernel.symbols(["n"])
    n = symbols["n"]

    result = WeightedAxisPathTriangleTransformMethod().run(
        {
            "condition": {"path": "sqrt(2)*MN+AN", "value": "21/4"},
            "fixed_point": (-1, 0),
            "moving_point": (n, 0),
            "dynamic_parameter": n,
            "auxiliary_point_ref": PointRef("R", "$question.iii.points.R"),
        },
        kernel,
    )

    assert result.outputs["auxiliary_point"].value == (
        (n - 1) / 2,
        (n + 1) / 2,
    )
    assert result.outputs["path_transformation"].value["inner_path"] == "MN+RN"
    assert result.outputs["path_transformation"].value["auxiliary_point_name"] == "R"
    assert result.outputs["auxiliary_locus"].type == "Line"
    assert result.outputs["auxiliary_locus"].value["kind"] == "ray"
    assert result.outputs["auxiliary_locus"].value["direction"] == (1, 1)
    assert all(check.ok for check in result.checks)


def test_weighted_axis_path_triangle_transform_method_supports_weight_2() -> None:
    """weight=2 时应使用 30°/60° 直角三角形转化。"""
    kernel = SympyKernel()
    symbols = kernel.symbols(["m"])
    m = symbols["m"]

    result = WeightedAxisPathTriangleTransformMethod().run(
        {
            "condition": {"path": "2DM+AM", "value": "5+5*sqrt(3)"},
            "fixed_point": (-1, 0),
            "moving_point": (m, 0),
            "dynamic_parameter": m,
            "auxiliary_point_ref": PointRef("Q", "$question.ii_2.points.Q"),
        },
        kernel,
    )

    assert result.outputs["auxiliary_point"].value == (
        sp.Rational(3, 4) * m - sp.Rational(1, 4),
        sp.sqrt(3) * (m + 1) / 4,
    )
    assert result.outputs["path_transformation"].value["inner_path"] == "DM+QM"
    assert result.outputs["path_transformation"].value["scale"] == 2
    assert result.outputs["path_transformation"].value["geometry"] == "30_60_90"
    assert result.outputs["auxiliary_locus"].value["direction"] == (3, sp.sqrt(3))
    assert all(check.ok for check in result.checks)


def test_linked_broken_path_geometric_minimum_method() -> None:
    """河西加权路径应走几何折线拉直，而不是依赖求导。"""
    kernel = SympyKernel()
    symbols = kernel.symbols(["b", "n"])
    b, n = symbols["b"], symbols["n"]
    transform = WeightedAxisPathTriangleTransformMethod().run(
        {
            "condition": {"path": "sqrt(2)*MN+AN", "value": "21/4"},
            "fixed_point": (-1, 0),
            "moving_point": (n, 0),
            "dynamic_parameter": n,
            "auxiliary_point_ref": PointRef("Q", "$question.iii.points.Q"),
        },
        kernel,
    )

    result = LinkedBrokenPathGeometricMinimumMethod().run(
        {
            "condition": {"path": "sqrt(2)*MN+AN", "value": "21/4"},
            "path_transformation": transform.outputs["path_transformation"].value,
            "auxiliary_locus": transform.outputs["auxiliary_locus"].value,
            "fixed_point": (-1, 0),
            "curve_point": (b + sp.Rational(1, 2), -b / 2 - sp.Rational(3, 4)),
            "moving_point": (n, 0),
            "auxiliary_point": transform.outputs["auxiliary_point"].value,
            "parameter": b,
            "dynamic_parameter": n,
            "parameter_constraint": {"operator": ">", "value": sp.Integer(0)},
            "dynamic_constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    assert result.outputs["parameter_value"].value == 2
    assert result.outputs["dynamic_parameter_value"].value == sp.Rational(3, 4)
    assert result.outputs["minimum_value"].value == sp.Rational(21, 4)
    assert result.outputs["dynamic_point"].value == (sp.Rational(3, 4), 0)
    assert all(check.ok for check in result.checks)


def test_linked_broken_path_minimum_expression_method() -> None:
    """薄 method 只求加权路径最小值表达式，不直接反求 b。"""
    kernel = SympyKernel()
    symbols = kernel.symbols(["b", "n"])
    b, n = symbols["b"], symbols["n"]
    transform = WeightedAxisPathTriangleTransformMethod().run(
        {
            "condition": {"path": "sqrt(2)*MN+AN", "value": "21/4"},
            "fixed_point": (-1, 0),
            "moving_point": (n, 0),
            "dynamic_parameter": n,
            "auxiliary_point_ref": PointRef("Q", "$question.iii.points.Q"),
        },
        kernel,
    )

    result = LinkedBrokenPathMinimumExpressionMethod().run(
        {
            "path_transformation": transform.outputs["path_transformation"].value,
            "auxiliary_locus": transform.outputs["auxiliary_locus"].value,
            "fixed_point": (-1, 0),
            "curve_point": (b + sp.Rational(1, 2), -b / 2 - sp.Rational(3, 4)),
            "moving_point": (n, 0),
            "auxiliary_point": transform.outputs["auxiliary_point"].value,
            "parameter": b,
            "dynamic_parameter": n,
            "parameter_constraint": {"operator": ">", "value": sp.Integer(0)},
            "dynamic_constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    assert sp.simplify(result.outputs["minimum_expression"].value - (sp.Rational(3, 2) * b + sp.Rational(9, 4))) == 0
    assert "parameter_value" not in result.outputs
    assert all(check.ok for check in result.checks)


def test_linked_broken_path_minimum_expression_method_supports_weight_2() -> None:
    """西青 2DM+AM 的 30°/60° 转化应得到关于 b 的最小值表达式。"""
    kernel = SympyKernel()
    symbols = kernel.symbols(["b", "m"])
    b, m = symbols["b"], symbols["m"]
    transform = WeightedAxisPathTriangleTransformMethod().run(
        {
            "condition": {"path": "2DM+AM", "value": "5+5*sqrt(3)"},
            "fixed_point": (-1, 0),
            "moving_point": (m, 0),
            "dynamic_parameter": m,
            "auxiliary_point_ref": PointRef("Q", "$question.ii_2.points.Q"),
        },
        kernel,
    )

    result = LinkedBrokenPathMinimumExpressionMethod().run(
        {
            "path_transformation": transform.outputs["path_transformation"].value,
            "auxiliary_locus": transform.outputs["auxiliary_locus"].value,
            "fixed_point": (-1, 0),
            "curve_point": (b + 2, -b - 3),
            "moving_point": (m, 0),
            "auxiliary_point": transform.outputs["auxiliary_point"].value,
            "parameter": b,
            "dynamic_parameter": m,
            "parameter_constraint": {"operator": ">", "value": sp.Integer(0)},
            "dynamic_constraint": {"operator": ">", "value": sp.Integer(0)},
        },
        kernel,
    )

    expected = sp.simplify((b + 3) * (1 + sp.sqrt(3)))
    assert sp.simplify(result.outputs["minimum_expression"].value - expected) == 0
    assert all(check.ok for check in result.checks)


def test_square_path_dimension_reduction_method() -> None:
    """正方形中心/中点结构把 HF+FM+MG 降维为 AG+MG。"""
    kernel = SympyKernel()

    result = SquarePathDimensionReductionMethod().run(
        {
            "path_condition": {"path": "HF+FM+MG"},
            "square_condition": {
                "vertices": ["point:ii:A", "point:ii:E", "point:ii:K", "point:ii:G"],
            },
            "midpoint_condition": {
                "point": "point:ii:F",
                "of": ["point:ii:A", "point:ii:E"],
            },
            "square_center_condition": {
                "point": "point:ii:H",
                "square": "fact:ii:square_AEKG",
            },
        },
        kernel,
    )

    transform = result.outputs["path_transformation"].value
    assert transform["transformed_path"] == "AG+MG"
    assert transform["fixed_point_names"] == ("A", "M")
    assert transform["moving_point_name"] == "G"
    assert all(check.ok for check in result.checks)


def test_parameterized_point_locus_line_method_allows_problem_parameter() -> None:
    """轨迹参数可与题目参数共存，优先选择内部运动参数。"""
    kernel = SympyKernel()
    c, t = sp.symbols("c _axis_param_E")

    result = ParameterizedPointLocusLineMethod().run(
        {
            "point": (t - c, -(c + 1) / 2),
            "target": PointRef("G", "$question.ii.points.G"),
        },
        kernel,
    )

    line = result.outputs["line"].value
    assert line["point_name"] == "G"
    assert line["direction"] == (1, 0)
    assert sp.simplify(line["start_point"][1] + (c + 1) / 2) == 0
    assert all(check.ok for check in result.checks)


def test_broken_path_straightening_candidates_accepts_locus_line() -> None:
    """将军饮马候选生成可直接读取动点轨迹 Line。"""
    kernel = SympyKernel()
    candidates = BrokenPathStraighteningCandidatesMethod().run(
        {
            "path_transformation": {"transformed_path": "AG+MG"},
            "moving_locus": {
                "kind": "line",
                "point_name": "G",
                "start_point": (0, -2),
                "direction": (1, 0),
            },
            "fixed_point_1": (0, 0),
            "fixed_point_2": (2, 0),
        },
        kernel,
    ).outputs["candidates"].value
    candidates = [dict(candidate) for candidate in candidates]
    candidates[1]["complexity_score"] += 1

    selected = SelectStraighteningCandidateMethod().run(
        {
            "candidates": candidates,
            "target": PointRef("Aux", "$question.ii.points.Aux", {"definition": "straightening_auxiliary_point"}),
        },
        kernel,
    )

    assert len(candidates) == 2
    assert selected.outputs["minimum_point_1"].type == "Point"
    assert selected.outputs["minimum_point_2"].type == "Point"


def test_coefficient_at_parameter_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["b", "c"])
    b, c = symbols["b"], symbols["c"]

    result = CoefficientAtParameterMethod().run(
        {
            "coefficients": {c: -b - 1},
            "coefficient": c,
            "parameter": b,
            "parameter_value": sp.Integer(2),
        },
        kernel,
    )

    assert result.outputs["coefficient_value"].value == -3


def test_evaluate_expression_at_parameter_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["b", "x"])
    b, x = symbols["b"], symbols["x"]

    result = EvaluateExpressionAtParameterMethod().run(
        {
            "expression": b * x + b**2,
            "parameter": b,
            "parameter_value": sp.Integer(2),
        },
        kernel,
    )

    assert result.outputs["evaluated_expression"].type == "Expression"
    assert result.outputs["evaluated_expression"].value == 2 * x + 4
    assert "evaluated_minimum_expression" not in result.outputs
    assert all(check.ok for check in result.checks)


def test_evaluate_expression_at_parameter_preserves_minimum_expression_type() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["b", "x"])
    b, x = symbols["b"], symbols["x"]

    result = EvaluateExpressionAtParameterMethod().run(
        {
            "expression": b * x + b**2,
            "parameter": b,
            "parameter_value": sp.Integer(2),
            "__input_types__": {"expression": "MinimumExpression"},
        },
        kernel,
    )

    assert "evaluated_expression" not in result.outputs
    assert result.outputs["evaluated_minimum_expression"].type == "MinimumExpression"
    assert result.outputs["evaluated_minimum_expression"].value == 2 * x + 4
    assert all(check.ok for check in result.checks)


def test_evaluate_expression_at_parameter_preserves_parabola_type() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["m", "x"])
    m, x = symbols["m"], symbols["x"]

    result = EvaluateExpressionAtParameterMethod().run(
        {
            "expression": m * x**2 + x,
            "parameter": m,
            "parameter_value": sp.Integer(2),
            "__input_types__": {"expression": "Parabola"},
        },
        kernel,
    )

    assert tuple(result.outputs) == ("evaluated_parabola",)
    assert result.outputs["evaluated_parabola"].type == "Parabola"
    assert sp.expand(result.outputs["evaluated_parabola"].value) == 2 * x**2 + x
    assert all(check.ok for check in result.checks)


def test_evaluate_point_at_parameter_method() -> None:
    kernel = SympyKernel()
    c = kernel.symbols(["c"])["c"]

    result = EvaluatePointAtParameterMethod().run(
        {
            "point": (-c, sp.Integer(0)),
            "parameter": c,
            "parameter_value": sp.Integer(5),
        },
        kernel,
    )

    assert result.outputs["evaluated_point"].type == "Point"
    assert result.outputs["evaluated_point"].value == (sp.Integer(-5), sp.Integer(0))
    assert all(check.ok for check in result.checks)


def test_line_locus_minimum_point_method() -> None:
    kernel = SympyKernel()

    result = LineLocusMinimumPointMethod().run(
        {
            "moving_locus": {
                "kind": "line",
                "point_name": "G",
                "start_point": (sp.Integer(0), sp.Integer(-3)),
                "direction": (sp.Integer(1), sp.Integer(0)),
            },
            "minimum_point_1": (sp.Integer(-5), sp.Integer(0)),
            "minimum_point_2": (sp.Rational(-7, 2), sp.Integer(-3)),
            "target": PointRef("G", "$question.ii.points.G"),
        },
        kernel,
    )

    assert result.outputs["point"].type == "Point"
    assert result.outputs["point"].value == (sp.Rational(-7, 2), sp.Integer(-3))
    assert all(check.ok for check in result.checks)


def test_line_locus_minimum_point_requires_named_target_ref() -> None:
    """method 层不应从 locus payload 兜底点名；PointRef 恢复由 executor 负责。"""
    kernel = SympyKernel()

    with pytest.raises(ValueError, match="target must be a PointRef"):
        LineLocusMinimumPointMethod().run(
            {
                "moving_locus": {
                    "kind": "line",
                    "point_name": "G",
                    "start_point": (sp.Integer(0), sp.Integer(-3)),
                    "direction": (sp.Integer(1), sp.Integer(0)),
                },
                "minimum_point_1": (sp.Integer(-5), sp.Integer(0)),
                "minimum_point_2": (sp.Rational(-7, 2), sp.Integer(-3)),
                "target": (sp.Integer(0), sp.Integer(-3)),
            },
            kernel,
        )
