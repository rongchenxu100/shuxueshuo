"""parameterized_point_locus_line 无状态 method。

由单参数仿射点坐标推出动点轨迹直线。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


class ParameterizedPointLocusLineMethod:
    """由参数化点坐标求运动轨迹直线。"""

    method_id = "parameterized_point_locus_line"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        point: Point = inputs["point"]
        target: PointRef | None = inputs.get("target")
        parameter = inputs["parameter"]
        _require_substitution_symbol(point, parameter)

        start_point: Point = (
            sp.simplify(point[0].subs(parameter, 0)),
            sp.simplify(point[1].subs(parameter, 0)),
        )
        direction: Point = (
            sp.simplify(sp.diff(point[0], parameter)),
            sp.simplify(sp.diff(point[1], parameter)),
        )
        if direction == (0, 0):
            raise method_precondition_failed(
                "parameterized point locus has zero direction",
                arg_name="point",
                role="parameterized_point",
                expected={"state": "nonconstant_in_parameter"},
                observed={
                    "state": "zero_direction",
                    "parameter": parameter.name,
                    "coordinates": [kernel.sstr(item) for item in point],
                },
                repair_action="provide_nonconstant_parameterized_point",
            )
        if not _is_affine(point, parameter):
            raise method_precondition_failed(
                "parameterized point locus requires affine coordinates",
                arg_name="point",
                role="parameterized_point",
                expected={"maximum_parameter_degree": 1},
                observed={
                    "parameter": parameter.name,
                    "coordinates": [kernel.sstr(item) for item in point],
                },
                repair_action="choose_applicable_locus_capability",
            )
        line = {
            "kind": "line",
            "point_name": target.name if target is not None else "moving_point",
            "start_point": start_point,
            "direction": direction,
            "parameter": parameter.name,
            "equation": _line_equation_text(start_point, direction, kernel),
        }
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"line": TypedValue("Line", line, source=self.method_id)},
            checks=[
                _check("locus_direction_nonzero", direction != (0, 0), "轨迹方向向量非零"),
                _check("point_on_locus_line", True, "参数化点始终在该直线上"),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "求参数化点轨迹",
                    "得到动点所在直线",
                    "点坐标关于同一参数一次变化时，消去参数得到一条直线轨迹。",
                    f"起点({_fmt_point(start_point, kernel)})，方向({_fmt_point(direction, kernel)})",
                    line["equation"],
                )
            ],
        )


def _is_affine(point: Point, parameter: sp.Symbol) -> bool:
    for coord in point:
        try:
            poly = sp.Poly(coord, parameter)
        except sp.PolynomialError:
            return False
        if poly.degree() > 1:
            return False
    return True


def _line_equation_text(start_point: Point, direction: Point, kernel: SympyKernel) -> str:
    if sp.simplify(direction[1]) == 0:
        return f"y={kernel.sstr(start_point[1])}"
    if sp.simplify(direction[0]) == 0:
        return f"x={kernel.sstr(start_point[0])}"
    return (
        f"(x,y)=({kernel.sstr(start_point[0])},{kernel.sstr(start_point[1])})"
        f"+t({kernel.sstr(direction[0])},{kernel.sstr(direction[1])})"
    )


SPEC = MethodSpecSource(
    method_cls=ParameterizedPointLocusLineMethod,
    title="由参数化点求轨迹直线",
    summary=(
        "Given 单参数仿射点坐标 P(t), derive 该动点的直线轨迹。"
        "Line 可作为 call-local 中间结果直接被后续调用引用；只有题面确实"
        "声明了同一条 Line 对象时才绑定已有对象，不要为展示名称虚构 Line ref。"
        "适用于几何构造得到点坐标后，再把折线路径最值转化到动点所在直线的场景。"
    ),
    solves=("derive_parameterized_point_locus_line",),
    inputs={
        "point": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": False},
        "parameter": {
            "type": "Symbol",
            "required": True,
            "description": (
                "驱动该Point运动的确切Symbol身份；通常直接引用产生参数化点的"
                "前序call之parameter返回值，不能由自由符号名称猜测"
            ),
        },
    },
    input_views=declare_input_views(
        identity=("target", "parameter"),
        latest_state=("point",),
    ),
    outputs={"line": "Line"},
    preconditions=(
        "parameter必须是point坐标中实际出现的同一Symbol身份",
        "point坐标关于parameter为一次式；其他题目参数可以作为轨迹族常量保留",
    ),
    postconditions=("输出 Line 包含 start_point、direction 和 point_name",),
    explanation=MethodExplanationSpec(
        role_schema={
            "parameterized_point": "含一个参数的动点坐标。",
            "point_label": "动点的学生可见名称。",
            "locus_line": "消去参数后的轨迹直线。",
        },
        student_goal_template="由参数化坐标看出动点所在的轨迹直线。",
        student_title_template="由参数化点确定轨迹直线",
        derive_templates=(
            "∵{parameterized_point}",
            "∴{point_label} 始终在直线 {locus_line} 上",
        ),
        box_templates=("{locus_line}",),
        role_binder_id="parameterized_point_locus_line",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "moving_point": "产生轨迹的参数化动点。",
            "locus_line": "该动点所在的轨迹直线。",
        },
        role_binder_id="parameterized_point_locus_line",
        scene_templates=(
            {
                "component": "LocusLineMarker",
                "persistence": "carry_forward",
                "color": "#0f766e",
                "dash": "7 5",
                "width": 2.0,
                "label_anchor": "end",
                "label_dx": -170,
                "label_dy": -14,
            },
        ),
    ),
)
