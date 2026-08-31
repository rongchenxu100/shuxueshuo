"""square_adjacent_vertex_from_side 无状态 method。

由正方形一条边的两个端点，构造相邻顶点的参数化坐标。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


class SquareAdjacentVertexFromSideMethod:
    """由正方形边端点和方向条件求指定相邻顶点。"""

    method_id = "square_adjacent_vertex_from_side"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        side_start: Point = inputs["side_start"]
        side_end: Point = inputs["side_end"]
        square_condition: dict[str, Any] = inputs["square_condition"]
        target: PointRef = inputs["target"]
        side_start_ref: PointRef | None = inputs.get("side_start_ref")
        side_end_ref: PointRef | None = inputs.get("side_end_ref")
        parameter = inputs.get("parameter")
        parameter_constraint = _canonicalize_runtime_constraint(
            inputs.get("parameter_constraint"),
            kernel,
            arg_name="parameter_constraint",
        )
        substitutions = _optional_parameter_substitution(
            inputs,
            side_start,
            side_end,
            allow_parameter_without_value=True,
            allow_closed_noop=True,
        )
        if substitutions:
            side_start = _subs_point(side_start, substitutions)
            side_end = _subs_point(side_end, substitutions)

        vertices = _square_vertices(square_condition)
        vector = (
            sp.simplify(side_end[0] - side_start[0]),
            sp.simplify(side_end[1] - side_start[1]),
        )
        target_role = _target_vertex_role(
            vertices,
            target.name,
            side_start_ref=side_start_ref,
            side_end_ref=side_end_ref,
        )
        if target_role in {"from_start_clockwise", "from_start_counterclockwise"}:
            point = _adjacent_vertex_from_role(side_start, vector, target_role)
        elif target_role in {"from_end_clockwise", "from_end_counterclockwise"}:
            point = _adjacent_vertex_from_role(side_end, vector, target_role)
        else:
            candidates = _adjacent_vertex_candidates(side_start, side_end, vector, target_role)
            point = _select_by_orientation(
                candidates,
                square_condition,
                parameter=parameter,
                parameter_constraint=parameter_constraint,
            )

        base = side_start if target_role == "from_start" else side_end
        if target_role.startswith("from_start_"):
            base = side_start
        if target_role.startswith("from_end_"):
            base = side_end
        base_to_target = (
            sp.simplify(point[0] - base[0]),
            sp.simplify(point[1] - base[1]),
        )
        side_vector = vector if target_role.startswith("from_start") else (
            sp.simplify(side_start[0] - side_end[0]),
            sp.simplify(side_start[1] - side_end[1]),
        )

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "square_adjacent_side_perpendicular",
                    sp.simplify(side_vector[0] * base_to_target[0] + side_vector[1] * base_to_target[1]) == 0,
                    "正方形相邻边互相垂直",
                ),
                _check(
                    "square_adjacent_side_equal_length",
                    sp.simplify(
                        side_vector[0] ** 2
                        + side_vector[1] ** 2
                        - base_to_target[0] ** 2
                        - base_to_target[1] ** 2
                    ) == 0,
                    "正方形相邻边长度相等",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由正方形边求相邻顶点",
                    f"表示 {target.name} 的坐标",
                    "正方形相邻边由已知边向量旋转 90° 得到，再按题设方向选择对应顶点。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


def _square_vertices(condition: dict[str, Any]) -> list[str]:
    """读取 square condition 中的顶点顺序。"""
    vertices = condition.get("vertices")
    if not isinstance(vertices, list) or len(vertices) < 4:
        raise method_input_invalid(
            "square condition requires at least four ordered vertices",
            arg_name="square_condition",
            role="square_vertices",
            expected={"type": "Condition", "state": "ordered_vertices"},
            observed={"type": type(vertices).__name__, "count": len(vertices) if isinstance(vertices, list) else 0},
            repair_action="provide_square_vertex_order",
        )
    return [str(item) for item in vertices]


def _target_vertex_role(
    vertices: list[str],
    target_name: str,
    *,
    side_start_ref: PointRef | None,
    side_end_ref: PointRef | None,
) -> str:
    """判断目标顶点是从边起点还是终点旋转得到。"""
    names = [_handle_name(handle) for handle in vertices]
    if side_start_ref is not None and side_end_ref is not None:
        return _target_vertex_role_from_known_side(
            names,
            side_start_ref.name,
            side_end_ref.name,
            target_name,
        )
    if target_name == names[3]:
        return "from_start"
    if target_name == names[1]:
        return "from_start_counterclockwise"
    if target_name == names[2]:
        return "from_end"
    raise method_precondition_failed(
        f"square target {target_name!r} is not adjacent to the declared side",
        arg_name="target",
        role="adjacent_vertex",
        internal_ref=target_name,
        expected={"type": "Point", "state": "adjacent_to_known_side"},
        observed={"state": "not_adjacent", "ordered_vertices": names},
        repair_action="choose_adjacent_square_vertex",
    )


def _target_vertex_role_from_known_side(
    names: list[str],
    side_start_name: str,
    side_end_name: str,
    target_name: str,
) -> str:
    """按 ordered vertices 和已知边方向确定旋转方向。"""
    try:
        start_index = names.index(side_start_name)
        end_index = names.index(side_end_name)
        target_index = names.index(target_name)
    except ValueError as exc:
        raise method_input_invalid(
            "known square side and target must all occur in ordered vertices",
            arg_name="square_condition",
            role="square_vertices",
            internal_ref=target_name,
            expected={"type": "Condition", "state": "contains_known_side_and_target"},
            observed={
                "ordered_vertices": names,
                "side_start": side_start_name,
                "side_end": side_end_name,
                "target": target_name,
            },
            repair_action="provide_square_vertex_order",
        ) from exc
    size = len(names)
    next_start = (start_index + 1) % size
    prev_start = (start_index - 1) % size
    next_end = (end_index + 1) % size
    prev_end = (end_index - 1) % size
    if end_index == next_start:
        if target_index == prev_start:
            return "from_start_clockwise"
        if target_index == next_end:
            return "from_end_clockwise"
    if end_index == prev_start:
        if target_index == next_start:
            return "from_start_counterclockwise"
        if target_index == prev_end:
            return "from_end_counterclockwise"
    raise method_precondition_failed(
        "square target is not adjacent to the known side",
        arg_name="target",
        role="adjacent_vertex",
        internal_ref=target_name,
        expected={"type": "Point", "state": "adjacent_to_known_side"},
        observed={"state": "not_adjacent", "ordered_vertices": names},
        repair_action="choose_adjacent_square_vertex",
    )


def _handle_name(handle: str) -> str:
    """读取 canonical handle 的 name 段。"""
    return handle.rsplit(":", 1)[-1]


def _adjacent_vertex_candidates(
    side_start: Point,
    side_end: Point,
    vector: Point,
    target_role: str,
) -> list[Point]:
    """返回两个 90° 旋转候选。"""
    rotations = (
        (vector[1], -vector[0]),
        (-vector[1], vector[0]),
    )
    base = side_start if target_role == "from_start" else side_end
    return [
        (sp.simplify(base[0] + rotation[0]), sp.simplify(base[1] + rotation[1]))
        for rotation in rotations
    ]


def _adjacent_vertex_from_role(base: Point, vector: Point, role: str) -> Point:
    """按 ordered vertices 推出的旋转方向求目标顶点。"""
    if role.endswith("_clockwise"):
        rotation = (vector[1], -vector[0])
    elif role.endswith("_counterclockwise"):
        rotation = (-vector[1], vector[0])
    else:
        raise method_input_invalid(
            f"unsupported square adjacent role: {role}",
            arg_name="target",
            role="adjacent_vertex",
            expected={"state": "clockwise_or_counterclockwise"},
            observed={"state": role},
            repair_action="choose_adjacent_square_vertex",
        )
    return (
        sp.simplify(base[0] + rotation[0]),
        sp.simplify(base[1] + rotation[1]),
    )


def _select_by_orientation(
    candidates: list[Point],
    condition: dict[str, Any],
    *,
    parameter: sp.Symbol | None = None,
    parameter_constraint: dict[str, Any] | None = None,
) -> Point:
    """按 square condition 中的 orientation 选择唯一候选。"""
    orientation = str(condition.get("orientation", "")).strip()
    if orientation in {"clockwise", "right"}:
        return candidates[0]
    if orientation in {"counterclockwise", "left"}:
        return candidates[1]
    if orientation == "below_x_axis":
        selected = [
            point for point in candidates
            if _definitely_negative(
                point[1],
                parameter=parameter,
                parameter_constraint=parameter_constraint,
            )
        ]
        if len(selected) == 1:
            return selected[0]
    if orientation == "above_x_axis":
        selected = [
            point for point in candidates
            if _definitely_positive(
                point[1],
                parameter=parameter,
                parameter_constraint=parameter_constraint,
            )
        ]
        if len(selected) == 1:
            return selected[0]
    raise method_result_ambiguous(
        "square adjacent vertex orientation does not select exactly one candidate",
        arg_name="square_condition",
        role="orientation_constraint",
        expected={"state": "unique_orientation"},
        observed={
            "orientation": orientation or "unspecified",
            "candidate_count": len(candidates),
        },
        repair_action="supply_disambiguating_constraint",
    )


def _definitely_negative(
    value: sp.Expr,
    *,
    parameter: sp.Symbol | None = None,
    parameter_constraint: dict[str, Any] | None = None,
) -> bool:
    if is_definitely_negative(value):
        return True
    return _definitely_signed_under_constraint(
        value,
        parameter=parameter,
        parameter_constraint=parameter_constraint,
        want_positive=False,
    )


def _definitely_positive(
    value: sp.Expr,
    *,
    parameter: sp.Symbol | None = None,
    parameter_constraint: dict[str, Any] | None = None,
) -> bool:
    if is_definitely_positive(value):
        return True
    return _definitely_signed_under_constraint(
        value,
        parameter=parameter,
        parameter_constraint=parameter_constraint,
        want_positive=True,
    )


def _definitely_signed_under_constraint(
    value: sp.Expr,
    *,
    parameter: sp.Symbol | None,
    parameter_constraint: dict[str, Any] | None,
    want_positive: bool,
) -> bool:
    """在简单 ``parameter > lower`` 约束下判断一次表达式符号。"""
    if parameter is None or parameter_constraint is None:
        return False
    if str(parameter_constraint.get("operator", "")) != ">":
        return False
    lower_bound = parameter_constraint.get("value")
    if not isinstance(lower_bound, sp.Basic):
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            "square parameter constraint is not a canonical runtime expression",
            category="configuration",
            retryability="configuration",
            arg_name="parameter_constraint",
            role="parameter_lower_bound",
            expected={"state": "canonical_sympy_expression"},
            observed={"type": type(lower_bound).__name__},
            repair_action="fix_runtime_contract",
        )
    try:
        poly = sp.Poly(value, parameter)
    except sp.PolynomialError:
        return False
    if poly.degree() > 1:
        return False
    slope = sp.simplify(poly.coeff_monomial(parameter))
    at_bound = sp.simplify(value.subs(parameter, lower_bound))
    if want_positive:
        return (
            is_definitely_positive(slope)
            and is_definitely_nonnegative(at_bound)
        ) or (
            is_definitely_zero(slope)
            and is_definitely_positive(at_bound)
        )
    return (
        is_definitely_negative(slope)
        and is_definitely_nonpositive(at_bound)
    ) or (
        is_definitely_zero(slope)
        and is_definitely_negative(at_bound)
    )


SPEC = MethodSpecSource(
    method_cls=SquareAdjacentVertexFromSideMethod,
    title="由正方形边求相邻顶点",
    summary=(
        "由正方形一条已知边的两个已计算端点、顶点顺序和方向条件，求指定相邻"
        "顶点的坐标表达式。必须通过公开返回角色 adjacent_vertex 明确绑定本次"
        "要计算的正方形顶点；代码用该对象在 ordered vertices 中的角色确定旋转方向，"
        "不会在多个剩余顶点之间猜测。该能力只做 90° 旋转构造，不负责把顶点"
        "代入曲线求参数。"
    ),
    do_not_use_when=(
        "已知边任一端点只有对象引用而没有坐标状态。",
        "目标是求当前边端点本身，而不是由这条边旋转得到的相邻顶点。",
        "正方形关系中仍有多个合法候选顶点，但没有通过公开返回角色 adjacent_vertex 明确绑定本次要计算的对象。",
        (
            "side_start 或 side_end 来自前序 call，但该返回没有绑定到正方形中"
            "对应的已有顶点对象；call-local Point 不能代替 ordered vertices "
            "中的对象身份。"
        ),
    ),
    solves=("derive_square_adjacent_vertex_from_side",),
    inputs={
        "side_start": {"type": "Point", "required": True},
        "side_end": {"type": "Point", "required": True},
        "square_condition": {"type": "Condition", "required": True},
        "target": {"type": "PointRef|Point", "required": True},
        "side_start_ref": {"type": "PointRef|Point", "required": False},
        "side_end_ref": {"type": "PointRef|Point", "required": False},
        "parameter": {"type": "Symbol", "required": False},
        "parameter_value": {"type": "ParameterValue", "required": False},
        "parameter_constraint": {"type": "Constraint", "required": False},
    },
    input_views=declare_input_views(
        identity=("target", "side_start_ref", "side_end_ref", "parameter"),
        latest_state=("side_start", "side_end", "parameter_value"),
        immutable_value=("square_condition", "parameter_constraint"),
    ),
    outputs={"point": "Point"},
    preconditions=(
        "square_condition 包含 ordered vertices；side_start、side_end 和绑定的目标点都必须对应其中的明确顶点角色",
        "若方向不能由 ordered vertices 唯一确定，则需要可判定的 orientation 或参数范围约束",
    ),
    postconditions=(
        "输出对象就是公开返回角色 adjacent_vertex 绑定的正方形顶点",
        "输出顶点与给定边构成垂直等长的正方形相邻边",
    ),
    explanation=MethodExplanationSpec(
        role_schema={
            "target_label": "学生可见的目标顶点点名。",
            "projection_construction": "为目标顶点作坐标辅助线的构造说明。",
            "square_name": "学生可见的正方形名称。",
            "side_equal_statement": "正方形相邻边相等的结论。",
            "square_right_angle_statement": "正方形公共顶点处的直角结论。",
            "projection_right_angles": "坐标辅助线形成的直角关系。",
            "matching_angle_statement": "对应的非直角锐角关系。",
            "triangle_congruence": "学生可见的全等直角三角形。",
            "length_correspondence": "全等后对应的坐标长度关系。",
            "target_position_condition": "用于选择目标点的方位条件。",
            "target_point": "学生可见的目标顶点坐标。",
        },
        student_goal_template="利用正方形相邻边垂直且等长，求相邻顶点坐标。",
        student_title_template="由正方形求相邻顶点{target_label}",
        student_nav_title_template="正方形求顶点{target_label}",
        derive_templates=(
            "作{projection_construction}",
            "∵四边形 {square_name} 是正方形",
            "∴{side_equal_statement}，{square_right_angle_statement}",
            "∵{projection_right_angles}",
            "∴{matching_angle_statement}",
            "∴{triangle_congruence}",
            "∴{length_correspondence}",
            "∵{target_position_condition}",
            "∴{target_point}",
        ),
        box_templates=("{target_point}",),
        role_binder_id="square_adjacent_vertex_from_side",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "square_vertices": "正方形条件给出的有序顶点。",
            "known_side": "该方法使用的已知边。",
            "target_vertex": "该方法求出的相邻正方形顶点。",
            "coordinate_triangles": "展示旋转后坐标差关系的直角三角形辅助图形。",
        },
        role_binder_id="square_adjacent_vertex_from_side",
        scene_templates=(
            {
                "component": "SquareAdjacentVertexMarker",
                "persistence": "carry_forward",
                "fill": "rgba(14, 165, 233, 0.12)",
                "color": "#0284c7",
                "edge_color": "#0f766e",
                "target_color": "#b45309",
            },
        ),
    ),
    repair_hints=(
        {
            "code": "square_side_end_not_found",
            "applies_to": (
                "method:square_adjacent_vertex_from_side",
                "binding_selector:square:side_end",
            ),
            "message": "正方形边端点绑定失败；通常不需要新增 segment，系统可从已求点坐标 fact/answer 绑定正方形边端点。",
            "next_actions": (
                "保持 `square_adjacent_vertex_from_side`；让它读取正方形条件、目标点实体和已有点坐标 fact/answer，不要新增 `segment:*` 或只为端点绑定服务的 utility step。",
            ),
            "do_not": (
                "不要新增 `segment:*` 只为让正方形边端点绑定通过。",
                "不要新增只计算端点坐标的临时 utility step。",
            ),
        },
    ),
)
