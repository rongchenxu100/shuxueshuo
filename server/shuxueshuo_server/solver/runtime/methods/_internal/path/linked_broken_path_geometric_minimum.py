"""Private linked-path minimum implementation for atomic path kernels.

No ``SPEC`` is defined here; this implementation cannot be registered as a
Planner-facing Method without crossing the tested internal boundary.
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.weighted_triangle_geometry import (
    WeightedTriangleGeometryContractError,
    WeightedTriangleGeometryUnsupportedError,
    weighted_triangle_geometry_for_transformation,
)

from ..._common import *


class LinkedBrokenPathGeometricMinimumMethod:
    """用“将军饮马”的折线最短思想处理带联动辅助点的路径最值。

    标准 ``broken_path_straightening_candidates`` 处理反射型将军饮马；本
    method 处理另一类联动辅助点：先构造 Q，把一个加权线段转成同倍率的
    ``QN``，再研究 ``MN+QN``。这里封装的是这个“联动点 Q”版本：

    - Q 随 N 在一条固定 45° 射线上运动；
    - ``MN+QN`` 的最短状态由折线拉直给出，即 M、N、Q 共线；
    - 最短线段还需垂直于 Q 的运动射线。

    method 只使用上一步的路径转化、点坐标和题设最小值条件，不读取 fixture。
    """

    method_id = "linked_broken_path_geometric_minimum"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        condition = inputs["condition"]
        transformation = inputs["path_transformation"]
        auxiliary_locus = inputs["auxiliary_locus"]
        fixed_point: Point = inputs["fixed_point"]
        curve_point: Point = inputs["curve_point"]
        moving_point: Point = inputs["moving_point"]
        auxiliary_point: Point = inputs["auxiliary_point"]
        parameter = inputs["parameter"]
        dynamic_parameter = inputs["dynamic_parameter"]
        parameter_constraint = _canonicalize_runtime_constraint(
            inputs["parameter_constraint"],
            kernel,
            arg_name="parameter_constraint",
        )
        dynamic_constraint = _canonicalize_runtime_constraint(
            inputs["dynamic_constraint"],
            kernel,
            arg_name="dynamic_constraint",
        )
        assert parameter_constraint is not None
        assert dynamic_constraint is not None

        if sp.simplify(fixed_point[1]) != 0 or sp.simplify(moving_point[1]) != 0:
            raise method_precondition_failed(
                "linked broken path minimum requires both fixed and moving points on the x-axis",
                subjects=(
                    FunctionalDiagnosticSubject(
                        arg_name="fixed_point",
                        role="fixed_endpoint",
                        expected_type="Point",
                        expected_state="on_x_axis",
                        observed_state="on_x_axis" if sp.simplify(fixed_point[1]) == 0 else "off_x_axis",
                    ),
                    FunctionalDiagnosticSubject(
                        arg_name="moving_point",
                        role="moving_endpoint",
                        expected_type="Point",
                        expected_state="on_x_axis",
                        observed_state="on_x_axis" if sp.simplify(moving_point[1]) == 0 else "off_x_axis",
                    ),
                ),
                expected={"state": "both_on_x_axis"},
                observed={"fixed_y": str(fixed_point[1]), "moving_y": str(moving_point[1])},
                repair_action="choose_axis_path_points",
            )
        if sp.simplify(moving_point[0] - dynamic_parameter) != 0:
            raise method_input_invalid(
                "moving point x-coordinate must equal the declared dynamic parameter",
                arg_name="moving_point",
                role="moving_endpoint",
                expected={"type": "Point", "state": "x_coordinate_is_dynamic_parameter"},
                observed={"x_coordinate": str(moving_point[0]), "dynamic_parameter": str(dynamic_parameter)},
                repair_action="choose_matching_dynamic_point",
            )

        scale = _supported_transformation_scale(transformation)

        # 辅助点的运动射线是上一步显式输出的几何约束。折线拉直后，
        # MN+QN 的最小值就是曲线点 M 到这条射线所在直线的垂线段长度。
        # 先求垂足 Q*，再由辅助点公式 Q(n)=Q* 反推出动点参数 n。
        direction = _locus_direction(auxiliary_locus)
        locus_start = _locus_start(auxiliary_locus)
        foot_point = _projection_point(curve_point, locus_start, direction)
        dynamic_expression = _solve_dynamic_parameter_from_auxiliary_foot(
            kernel,
            auxiliary_point,
            foot_point,
            dynamic_parameter,
            fixed_point[0],
            parameter,
            parameter_constraint,
        )
        dynamic_point_expr = (
            sp.simplify(sp.sympify(moving_point[0]).subs(dynamic_parameter, dynamic_expression)),
            sp.simplify(sp.sympify(moving_point[1]).subs(dynamic_parameter, dynamic_expression)),
        )
        auxiliary_point_expr = _subs_point(
            auxiliary_point,
            {dynamic_parameter: dynamic_expression},
        )

        perpendicular_dot = _dot_with_direction(curve_point, auxiliary_point_expr, direction)
        point_on_locus = _point_on_locus(auxiliary_point_expr, locus_start, direction)

        # 原目标已转为 scale*(MN+QN)。当 Q 取垂足 Q* 时，MN+QN 被拉直为 MQ*，
        # 所以最小值表达式是 scale * distance(M, locus)。
        inner_minimum_expression = _point_to_locus_distance(
            curve_point,
            locus_start,
            direction,
            parameter,
            parameter_constraint,
        )
        minimum_expression = sp.simplify(scale * inner_minimum_expression)

        target_value = _require_canonical_runtime_expression(
            condition["value"],
            kernel,
            arg_name="condition",
            role="minimum_target_value",
        )
        parameter_value = _select_parameter_value(
            kernel.solve_values(sp.Eq(minimum_expression, target_value), parameter),
            parameter,
            parameter_constraint,
            dynamic_expression,
            dynamic_constraint,
        )
        dynamic_value = sp.simplify(dynamic_expression.subs(parameter, parameter_value))
        minimum_value = sp.simplify(minimum_expression.subs(parameter, parameter_value))
        dynamic_point = (dynamic_value, sp.Integer(0))

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "parameter_value": TypedValue("ParameterValue", parameter_value, source=self.method_id),
                "dynamic_parameter_value": TypedValue("ParameterValue", dynamic_value, source=self.method_id),
                "minimum_value": TypedValue("MinimumExpression", minimum_value, source=self.method_id),
                "dynamic_point": TypedValue("Point", dynamic_point, source=self.method_id),
            },
            checks=[
                _check(
                    "straightened_points_collinear",
                    point_collinear(curve_point, dynamic_point_expr, auxiliary_point_expr),
                    "最短状态下 M、N、Q 共线",
                ),
                _check(
                    "auxiliary_point_on_locus",
                    point_on_locus,
                    "最短状态下辅助点仍在声明的运动射线上",
                ),
                _check(
                    "auxiliary_point_is_locus_foot",
                    _same_point(auxiliary_point_expr, foot_point),
                    "最短状态下辅助点是曲线点到运动射线的垂足",
                ),
                _check(
                    "straightened_line_perpendicular_to_locus",
                    sp.simplify(perpendicular_dot) == 0,
                    "拉直后的 MQ 垂直于 Q 的运动射线",
                ),
                _check(
                    "parameter_constraint_satisfied",
                    _constraint_satisfied(parameter_value, parameter_constraint),
                    f"{parameter.name} 满足题设约束",
                ),
                _check(
                    "dynamic_constraint_satisfied",
                    _constraint_satisfied(dynamic_value, dynamic_constraint),
                    f"{dynamic_parameter.name} 满足动点范围",
                ),
                _check(
                    "minimum_value_matches",
                    sp.simplify(minimum_value - target_value) == 0,
                    "几何最小值等于题设给定值",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "用折线拉直求加权路径最值",
                    f"由 {transformation['transformed_path']} 的最短状态反求 {parameter.name}",
                    "构造 Q 后，原目标等价于同倍率下的 MN+QN；折线拉直后，最短值就是 M 到 Q 运动射线的垂线段长度。",
                    (
                        f"垂足=({_fmt_point(foot_point, kernel)})，"
                        f"{dynamic_parameter.name}={kernel.sstr(dynamic_expression)}，"
                        f"最小值={kernel.sstr(minimum_expression)}"
                    ),
                    (
                        f"{parameter.name}={kernel.sstr(parameter_value)}，"
                        f"{dynamic_parameter.name}={kernel.sstr(dynamic_value)}"
                    ),
                )
            ],
        )


class LinkedBrokenPathMinimumExpressionMethod:
    """只求联动折线最短的表达式，不在本 method 内反求参数。

    该 method 是 ``linked_broken_path_geometric_minimum`` 的薄版本：它完成学生
    解法中的“点到辅助点轨迹的垂线距离”这一步，输出关于主参数的最小值表达式。
    题设给定最小值后，再交给 ``parameter_from_expression_value`` 解参数。这样
    Strategy Planner 看到的是可复用的细粒度能力，而不是某道题专属的大 recipe。
    """

    method_id = "linked_broken_path_minimum_expression"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        transformation = inputs["path_transformation"]
        auxiliary_locus = inputs["auxiliary_locus"]
        fixed_point: Point = inputs["fixed_point"]
        curve_point: Point = inputs["curve_point"]
        moving_point: Point = inputs["moving_point"]
        auxiliary_point: Point = inputs["auxiliary_point"]
        parameter = inputs["parameter"]
        dynamic_parameter = inputs["dynamic_parameter"]
        parameter_constraint = _canonicalize_runtime_constraint(
            inputs["parameter_constraint"],
            kernel,
            arg_name="parameter_constraint",
        )
        assert parameter_constraint is not None
        _dynamic_constraint = inputs["dynamic_constraint"]

        if sp.simplify(fixed_point[1]) != 0 or sp.simplify(moving_point[1]) != 0:
            raise method_precondition_failed(
                "linked broken path expression requires both fixed and moving points on the x-axis",
                subjects=(
                    FunctionalDiagnosticSubject(
                        arg_name="fixed_point",
                        role="fixed_endpoint",
                        expected_type="Point",
                        expected_state="on_x_axis",
                        observed_state="on_x_axis" if sp.simplify(fixed_point[1]) == 0 else "off_x_axis",
                    ),
                    FunctionalDiagnosticSubject(
                        arg_name="moving_point",
                        role="moving_endpoint",
                        expected_type="Point",
                        expected_state="on_x_axis",
                        observed_state="on_x_axis" if sp.simplify(moving_point[1]) == 0 else "off_x_axis",
                    ),
                ),
                expected={"state": "both_on_x_axis"},
                observed={"fixed_y": str(fixed_point[1]), "moving_y": str(moving_point[1])},
                repair_action="choose_axis_path_points",
            )
        if sp.simplify(moving_point[0] - dynamic_parameter) != 0:
            raise method_input_invalid(
                "moving point x-coordinate must equal the declared dynamic parameter",
                arg_name="moving_point",
                role="moving_endpoint",
                expected={"type": "Point", "state": "x_coordinate_is_dynamic_parameter"},
                observed={"x_coordinate": str(moving_point[0]), "dynamic_parameter": str(dynamic_parameter)},
                repair_action="choose_matching_dynamic_point",
            )

        scale = _supported_transformation_scale(transformation)

        direction = _locus_direction(auxiliary_locus)
        locus_start = _locus_start(auxiliary_locus)
        foot_point = _projection_point(curve_point, locus_start, direction)
        dynamic_expression = _solve_dynamic_parameter_from_auxiliary_foot(
            kernel,
            auxiliary_point,
            foot_point,
            dynamic_parameter,
            fixed_point[0],
            parameter,
            parameter_constraint,
        )
        dynamic_point_expr = (
            sp.simplify(sp.sympify(moving_point[0]).subs(dynamic_parameter, dynamic_expression)),
            sp.simplify(sp.sympify(moving_point[1]).subs(dynamic_parameter, dynamic_expression)),
        )
        auxiliary_point_expr = _subs_point(auxiliary_point, {dynamic_parameter: dynamic_expression})
        perpendicular_dot = _dot_with_direction(curve_point, auxiliary_point_expr, direction)
        point_on_locus = _point_on_locus(auxiliary_point_expr, locus_start, direction)

        inner_minimum_expression = _point_to_locus_distance(
            curve_point,
            locus_start,
            direction,
            parameter,
            parameter_constraint,
        )
        minimum_expression = sp.simplify(scale * inner_minimum_expression)

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "minimum_expression": TypedValue(
                    "MinimumExpression",
                    minimum_expression,
                    source=self.method_id,
                ),
                "dynamic_parameter_expression": TypedValue(
                    "Expression",
                    dynamic_expression,
                    source=self.method_id,
                ),
                "dynamic_point_expression": TypedValue(
                    "Point",
                    dynamic_point_expr,
                    source=self.method_id,
                ),
            },
            checks=[
                _check(
                    "straightened_points_collinear",
                    point_collinear(curve_point, dynamic_point_expr, auxiliary_point_expr),
                    "最短状态下曲线点、动点、辅助点共线",
                ),
                _check(
                    "auxiliary_point_on_locus",
                    point_on_locus,
                    "最短状态下辅助点仍在声明的运动射线上",
                ),
                _check(
                    "auxiliary_point_is_locus_foot",
                    _same_point(auxiliary_point_expr, foot_point),
                    "最短状态下辅助点是曲线点到运动射线的垂足",
                ),
                _check(
                    "straightened_line_perpendicular_to_locus",
                    sp.simplify(perpendicular_dot) == 0,
                    "拉直后的连线垂直于辅助点运动射线",
                ),
                _check(
                    "dynamic_constraint_declared",
                    _dynamic_constraint is not None,
                    "动点约束已传入 method",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "求联动折线最小值表达式",
                    f"得到关于 {parameter.name} 的最小值表达式",
                    "辅助点沿固定射线运动，折线拉直后最短距离等于曲线点到该射线所在直线的垂线段长度。",
                    (
                        f"垂足=({_fmt_point(foot_point, kernel)})，"
                        f"{dynamic_parameter.name}={kernel.sstr(dynamic_expression)}"
                    ),
                    f"最小值表达式={kernel.sstr(minimum_expression)}",
                )
            ],
        )


def _dot_with_direction(point: Point, origin: Point, direction: tuple[sp.Expr, sp.Expr]) -> sp.Expr:
    """计算向量 origin->point 与给定方向向量的点积。"""
    return sp.simplify((point[0] - origin[0]) * direction[0] + (point[1] - origin[1]) * direction[1])


def _supported_transformation_scale(transformation: dict[str, Any]) -> sp.Expr:
    """读取并校验 weighted triangle transform 的倍率。

    ``weighted_axis_path_triangle_transform`` 负责判断具体权重是否可构造；本 method
    只接受已经带有受支持 geometry 标记的转化结果，再按通用点到直线距离公式求
    最短表达式。
    """
    try:
        return weighted_triangle_geometry_for_transformation(transformation).weight
    except WeightedTriangleGeometryUnsupportedError as exc:
        raise method_precondition_failed(
            "path transformation uses an unsupported triangle geometry weight",
            arg_name="path_transformation",
            role="geometry_profile",
            expected={"supported_weights": list(exc.supported)},
            observed={"weight": str(exc.weight)},
            repair_action="choose_supported_path_transformation",
        ) from exc
    except WeightedTriangleGeometryContractError as exc:
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            "materialized path transformation drifts from its geometry profile",
            category="configuration",
            retryability="configuration",
            arg_name="path_transformation",
            role="geometry_profile",
            expected={"field": exc.field, "value": str(exc.expected)},
            observed={"field": exc.field, "value": str(exc.observed)},
            repair_action="fix_runtime_contract",
        ) from exc


def _same_point(p1: Point, p2: Point) -> bool:
    """判断两个点坐标是否等价。"""
    return sp.simplify(p1[0] - p2[0]) == 0 and sp.simplify(p1[1] - p2[1]) == 0


def _locus_direction(locus: dict[str, Any]) -> tuple[sp.Expr, sp.Expr]:
    """读取辅助点运动射线方向。"""
    direction = locus.get("direction")
    if not isinstance(direction, tuple) or len(direction) != 2:
        raise method_input_invalid(
            "auxiliary locus direction must be a two-dimensional vector",
            arg_name="auxiliary_locus",
            role="locus_direction",
            expected={"type": "Vector2"},
            observed={"type": type(direction).__name__, "value": repr(direction)},
            repair_action="provide_valid_auxiliary_locus",
        )
    return (sp.sympify(direction[0]), sp.sympify(direction[1]))


def _locus_start(locus: dict[str, Any]) -> Point:
    """读取辅助点运动射线起点。"""
    start = locus.get("start_point")
    if not isinstance(start, tuple) or len(start) != 2:
        raise method_input_invalid(
            "auxiliary locus start must be a materialized point",
            arg_name="auxiliary_locus",
            role="locus_origin",
            expected={"type": "Point", "state": "materialized"},
            observed={"type": type(start).__name__, "value": repr(start)},
            repair_action="provide_valid_auxiliary_locus",
        )
    return (sp.sympify(start[0]), sp.sympify(start[1]))


def _point_on_locus(point: Point, start: Point, direction: tuple[sp.Expr, sp.Expr]) -> bool:
    """判断点是否在声明的直线/射线所在直线上。"""
    cross = (point[0] - start[0]) * direction[1] - (point[1] - start[1]) * direction[0]
    return sp.simplify(cross) == 0


def _projection_point(point: Point, start: Point, direction: tuple[sp.Expr, sp.Expr]) -> Point:
    """求点到直线 start + t*direction 的垂足。"""
    dx, dy = direction
    denominator = sp.simplify(dx**2 + dy**2)
    if denominator == 0:
        raise method_precondition_failed(
            "auxiliary locus direction cannot be the zero vector",
            arg_name="auxiliary_locus",
            role="locus_direction",
            expected={"type": "Vector2", "state": "nonzero"},
            observed={"state": "zero_vector"},
            repair_action="provide_valid_auxiliary_locus",
        )
    t = sp.simplify(((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator)
    return (
        sp.simplify(start[0] + t * dx),
        sp.simplify(start[1] + t * dy),
    )


def _point_to_locus_distance(
    point: Point,
    start: Point,
    direction: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
) -> sp.Expr:
    """计算点到辅助点运动轨迹所在直线的距离。

    用点到直线距离公式 ``|cross(point-start, direction)| / |direction|``。
    对一次表达式，结合参数正负约束可以把 Abs 化掉，得到学生解法里的线性
    最小值表达式。
    """
    dx, dy = direction
    cross = sp.simplify((point[0] - start[0]) * dy - (point[1] - start[1]) * dx)
    norm = sp.sqrt(sp.simplify(dx**2 + dy**2))
    return _simplify_abs_by_lower_bound(sp.Abs(cross) / norm, parameter, parameter_constraint)


def _solve_dynamic_parameter_from_auxiliary_foot(
    kernel: SympyKernel,
    auxiliary_point: Point,
    foot_point: Point,
    dynamic_parameter: sp.Symbol,
    fixed_x: sp.Expr,
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
) -> sp.Expr:
    """由 Q(n)=垂足 Q* 反推出动点参数。"""
    solutions = kernel.solve_equations(
        [
            sp.Eq(auxiliary_point[0], foot_point[0]),
            sp.Eq(auxiliary_point[1], foot_point[1]),
        ],
        [dynamic_parameter],
    )
    candidates = [
        sp.simplify(solution[dynamic_parameter])
        for solution in solutions
        if dynamic_parameter in solution
    ]
    return _select_dynamic_solution(candidates, fixed_x, parameter, parameter_constraint)


def _select_dynamic_solution(
    candidates: list[sp.Expr],
    fixed_x: sp.Expr,
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
) -> sp.Expr:
    """从共线方程的候选中排除退化解。

    共线方程会给出 ``N=A`` 这种退化候选；它让 Q 也退化到 A，不能表示题目里的
    x 轴正半轴动点。这里用 ``AN`` 在参数定义域内为正来选择真正的几何状态。
    """
    lower = _constraint_lower_bound(parameter_constraint)
    valid = [
        sp.simplify(candidate)
        for candidate in candidates
        if _linear_positive_under_lower_bound(
            sp.simplify(candidate - fixed_x),
            parameter,
            lower,
        )
    ]
    unique = []
    for candidate in valid:
        if candidate not in unique:
            unique.append(candidate)
    if len(unique) != 1:
        raise method_result_ambiguous(
            "linked broken path dynamic parameter is not uniquely determined",
            arg_name="dynamic_parameter",
            role="moving_point_parameter",
            internal_ref=parameter,
            expected={"type": "ParameterValue", "candidate_count": 1},
            observed={"candidate_count": len(unique), "candidates": [str(item) for item in candidates]},
            repair_action="supply_disambiguating_constraint",
        )
    return unique[0]


def _select_parameter_value(
    candidates: list[sp.Expr],
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
    dynamic_expression: sp.Expr,
    dynamic_constraint: dict[str, sp.Expr | str],
) -> sp.Expr:
    """同时满足参数约束和动点范围的参数值。"""
    valid = []
    for candidate in candidates:
        value = sp.simplify(candidate)
        dynamic_value = sp.simplify(dynamic_expression.subs(parameter, value))
        if _constraint_satisfied(value, parameter_constraint) and _constraint_satisfied(
            dynamic_value,
            dynamic_constraint,
        ):
            valid.append(value)
    if len(valid) != 1:
        raise method_result_ambiguous(
            "geometric minimum parameter value is not uniquely determined",
            arg_name="parameter",
            role="minimum_parameter",
            internal_ref=parameter,
            expected={"type": "ParameterValue", "candidate_count": 1},
            observed={"candidate_count": len(valid), "candidates": [str(item) for item in candidates]},
            repair_action="supply_disambiguating_constraint",
        )
    return valid[0]


def _constraint_satisfied(value: sp.Expr, constraint: dict[str, sp.Expr | str]) -> bool:
    """判断数值是否满足首版支持的 ``>`` 约束。"""
    lower = _constraint_lower_bound(constraint)
    if lower is None:
        return True
    return is_definitely_positive(sp.simplify(value - lower))


def _constraint_lower_bound(constraint: dict[str, sp.Expr | str]) -> sp.Expr | None:
    """读取首版支持的严格下界约束。"""
    if str(constraint.get("operator", "")) != ">":
        return None
    value = constraint["value"]
    if not isinstance(value, sp.Basic):
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            "parameter constraint reached Method without canonical expression binding",
            category="configuration",
            retryability="configuration",
            arg_name="parameter_constraint",
            role="parameter_lower_bound",
            expected={"state": "canonical_sympy_expression"},
            observed={"type": type(value).__name__},
            repair_action="fix_runtime_contract",
        )
    return value


def _linear_positive_under_lower_bound(
    expression: sp.Expr,
    parameter: sp.Symbol,
    lower_bound: sp.Expr | None,
) -> bool:
    """证明一次表达式在参数下界右侧恒正。"""
    expression = sp.simplify(expression)
    if not expression.has(parameter):
        return is_definitely_positive(expression)
    if lower_bound is None:
        return False
    return is_definitely_positive_under_lower_bound(
        expression,
        parameter,
        lower_bound,
    )


def _simplify_abs_by_lower_bound(
    expression: sp.Expr,
    parameter: sp.Symbol,
    constraint: dict[str, sp.Expr | str],
) -> sp.Expr:
    """用参数下界化简可判定为正的一次 Abs。"""
    lower = _constraint_lower_bound(constraint)
    if lower is None:
        return sp.simplify(expression)
    replacements = {}
    for atom in expression.atoms(sp.Abs):
        inner = sp.simplify(atom.args[0])
        if _linear_positive_under_lower_bound(inner, parameter, lower):
            replacements[atom] = inner
        elif _linear_positive_under_lower_bound(-inner, parameter, lower):
            replacements[atom] = -inner
    return sp.simplify(expression.xreplace(replacements))


__all__ = [
    "LinkedBrokenPathGeometricMinimumMethod",
    "LinkedBrokenPathMinimumExpressionMethod",
]
