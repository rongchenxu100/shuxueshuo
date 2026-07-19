"""linked_broken_path_geometric_minimum 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import ScalarResultFormSpec

from ._common import *
from ._spec import MethodSpecSource


class LinkedBrokenPathGeometricMinimumMethod:
    """用“将军饮马”的折线最短思想处理带联动辅助点的路径最值。

    南开题里的 ``broken_path_straightening_candidates`` 是标准反射型将军饮马；
    河西题第（Ⅲ）问不是简单反射，而是先构造 Q，使 ``AN`` 变成同倍率下的
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
        parameter_constraint = inputs["parameter_constraint"]
        dynamic_constraint = inputs["dynamic_constraint"]

        if sp.simplify(fixed_point[1]) != 0 or sp.simplify(moving_point[1]) != 0:
            raise ValueError("linked_broken_path_geometric_minimum requires fixed/moving points on x-axis")
        if sp.simplify(moving_point[0] - dynamic_parameter) != 0:
            raise ValueError("moving point x-coordinate must be the dynamic parameter")

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

        target_value = kernel.expr(condition["value"], {parameter.name: parameter})
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
    Strategy Planner 看到的是更可复用的细粒度能力，而不是河西题专属大 recipe。
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
        parameter_constraint = inputs["parameter_constraint"]
        _dynamic_constraint = inputs["dynamic_constraint"]

        if sp.simplify(fixed_point[1]) != 0 or sp.simplify(moving_point[1]) != 0:
            raise ValueError("linked_broken_path_minimum_expression requires fixed/moving points on x-axis")
        if sp.simplify(moving_point[0] - dynamic_parameter) != 0:
            raise ValueError("moving point x-coordinate must be the dynamic parameter")

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
    scale = sp.simplify(transformation.get("scale", sp.sqrt(2)))
    geometry = str(transformation.get("geometry", "45_45_90"))
    if sp.simplify(scale - sp.sqrt(2)) == 0 and geometry == "45_45_90":
        return scale
    if sp.simplify(scale - 2) == 0 and geometry == "30_60_90":
        return scale
    raise ValueError("linked broken path minimum supports only sqrt(2)/45° or 2/30° weighted transforms")


def _same_point(p1: Point, p2: Point) -> bool:
    """判断两个点坐标是否等价。"""
    return sp.simplify(p1[0] - p2[0]) == 0 and sp.simplify(p1[1] - p2[1]) == 0


def _locus_direction(locus: dict[str, Any]) -> tuple[sp.Expr, sp.Expr]:
    """读取辅助点运动射线方向。"""
    direction = locus.get("direction")
    if not isinstance(direction, tuple) or len(direction) != 2:
        raise ValueError("auxiliary_locus.direction must be a 2D vector")
    return (sp.sympify(direction[0]), sp.sympify(direction[1]))


def _locus_start(locus: dict[str, Any]) -> Point:
    """读取辅助点运动射线起点。"""
    start = locus.get("start_point")
    if not isinstance(start, tuple) or len(start) != 2:
        raise ValueError("auxiliary_locus.start_point must be a point")
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
        raise ValueError("auxiliary_locus.direction cannot be zero")
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
    对河西题这类一次表达式，结合 ``b>0`` 可以把 Abs 化掉，得到学生解法里的
    线性最小值表达式。
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
        raise ValueError(f"linked broken path dynamic parameter cannot be uniquely determined: {candidates}")
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
        raise ValueError(f"geometric minimum parameter value cannot be uniquely determined: {candidates}")
    return valid[0]


def _constraint_satisfied(value: sp.Expr, constraint: dict[str, sp.Expr | str]) -> bool:
    """判断数值是否满足首版支持的 ``>`` 约束。"""
    lower = _constraint_lower_bound(constraint)
    if lower is None:
        return True
    return bool(sp.simplify(value - lower) > 0)


def _constraint_lower_bound(constraint: dict[str, sp.Expr | str]) -> sp.Expr | None:
    """读取首版支持的严格下界约束。"""
    if str(constraint.get("operator", "")) != ">":
        return None
    return sp.sympify(constraint["value"])


def _linear_positive_under_lower_bound(
    expression: sp.Expr,
    parameter: sp.Symbol,
    lower_bound: sp.Expr | None,
) -> bool:
    """证明一次表达式在参数下界右侧恒正。"""
    expression = sp.simplify(expression)
    if not expression.has(parameter):
        return bool(expression > 0)
    if lower_bound is None:
        return False
    poly = sp.Poly(expression, parameter)
    if poly.degree() > 1:
        return False
    slope = sp.simplify(poly.coeff_monomial(parameter))
    at_bound = sp.simplify(expression.subs(parameter, lower_bound))
    return bool(slope >= 0 and at_bound > 0)


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


SPEC = MethodSpecSource(
    method_cls=LinkedBrokenPathGeometricMinimumMethod,
    title="联动点折线拉直最值",
    summary=(
        "输入: 已完成的加权辅助三角形转化与辅助点轨迹；输出: 几何最小值与极值点。"
        "使用边界: 支持 sqrt(2)/45° 与 2/30° 两类 weighted transform。"
    ),
    solves=("derive_linked_broken_path_geometric_minimum",),
    inputs={
        "condition": {"type": "Condition", "required": True},
        "path_transformation": {"type": "PathTransformation", "required": True},
        "auxiliary_locus": {"type": "Line", "required": True},
        "fixed_point": {"type": "Point", "required": True},
        "curve_point": {"type": "Point", "required": True},
        "moving_point": {"type": "Point", "required": True},
        "auxiliary_point": {"type": "Point", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "dynamic_parameter": {"type": "Symbol", "required": True},
        "parameter_constraint": {"type": "Constraint", "required": True},
        "dynamic_constraint": {"type": "Constraint", "required": True},
    },
    outputs={
        "parameter_value": "ParameterValue",
        "dynamic_parameter_value": "ParameterValue",
        "minimum_value": "MinimumExpression",
        "dynamic_point": "Point",
    },
    preconditions=(
        "已经完成加权路径到普通折线的辅助点转化",
        "path_transformation.scale/geometry 必须来自受支持的 weighted_axis_path_triangle_transform",
        "Q 随 N 在固定射线上运动",
    ),
    postconditions=("输出参数值满足题设最小值和动点范围",),
)


MINIMUM_EXPRESSION_SPEC = MethodSpecSource(
    method_cls=LinkedBrokenPathMinimumExpressionMethod,
    title="联动点折线最短表达式",
    summary=(
        "输入: 已完成的加权辅助三角形转化、曲线点和动点表达式；输出: 关于参数的几何最小值表达式。"
        "使用边界: 支持 sqrt(2)/45° 与 2/30° 两类 weighted transform。"
        "使用原则: 本 method 只求表达式，不反求参数；若输入已经不含自由参数，结果会自然闭合为具体值。"
    ),
    solves=("derive_linked_broken_path_minimum_expression",),
    inputs={
        "path_transformation": {"type": "PathTransformation", "required": True},
        "auxiliary_locus": {"type": "Line", "required": True},
        "fixed_point": {"type": "Point", "required": True},
        "curve_point": {"type": "Point", "required": True},
        "moving_point": {"type": "Point", "required": True},
        "auxiliary_point": {"type": "Point", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "dynamic_parameter": {"type": "Symbol", "required": True},
        "parameter_constraint": {"type": "Constraint", "required": True},
        "dynamic_constraint": {"type": "Constraint", "required": True},
    },
    outputs={
        "minimum_expression": "MinimumExpression",
        "dynamic_parameter_expression": "Expression",
        "dynamic_point_expression": "Point",
    },
    scalar_result_forms={
        "minimum_expression": ScalarResultFormSpec(
            possible_forms=("open_expression", "closed_value"),
            description=(
                "路径状态仍含未确定参数时为 open_expression；全部输入已确定时为 "
                "closed_value。"
            ),
        ),
        "dynamic_parameter_expression": ScalarResultFormSpec(
            possible_forms=("open_expression", "closed_value"),
            description=(
                "联动参数仍依赖未确定参数时为 open_expression；不存在自由参数时为 "
                "closed_value。"
            ),
        ),
    },
    preconditions=(
        "已经完成加权路径到普通折线的辅助点转化",
        "path_transformation.scale/geometry 必须来自受支持的 weighted_axis_path_triangle_transform",
        "辅助点沿固定射线运动",
    ),
    postconditions=("输出最小值表达式供后续反求参数",),
)
