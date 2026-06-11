"""parameterized_point_locus_line 无状态 method。

由单参数仿射点坐标推出动点轨迹直线。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class ParameterizedPointLocusLineMethod:
    """由参数化点坐标求运动轨迹直线。"""

    method_id = "parameterized_point_locus_line"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        point: Point = inputs["point"]
        target: PointRef | None = inputs.get("target")
        parameter = inputs.get("parameter") or _unique_parameter(point)

        start_point: Point = (
            sp.simplify(point[0].subs(parameter, 0)),
            sp.simplify(point[1].subs(parameter, 0)),
        )
        direction: Point = (
            sp.simplify(sp.diff(point[0], parameter)),
            sp.simplify(sp.diff(point[1], parameter)),
        )
        if direction == (0, 0):
            raise ValueError("parameterized point locus has zero direction")
        if not _is_affine(point, parameter):
            raise ValueError("parameterized point locus requires affine coordinates")
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


def _unique_parameter(point: Point) -> sp.Symbol:
    symbols = sorted(set(point[0].free_symbols) | set(point[1].free_symbols), key=lambda item: item.name)
    generated_motion = [symbol for symbol in symbols if symbol.name.startswith("_axis_param_")]
    if len(generated_motion) == 1:
        return generated_motion[0]
    if len(symbols) != 1:
        raise ValueError("parameterized point locus requires exactly one free parameter")
    return symbols[0]


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
        "适用于几何构造得到点坐标后，再把折线路径最值转化到动点所在直线的场景。"
    ),
    solves=("derive_parameterized_point_locus_line",),
    inputs={
        "point": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": False},
        "parameter": {"type": "Symbol", "required": False},
    },
    outputs={"line": "Line"},
    preconditions=("point 的两个坐标最多含一个公共参数，且关于该参数为一次式",),
    postconditions=("输出 Line 包含 start_point、direction 和 point_name",),
)
