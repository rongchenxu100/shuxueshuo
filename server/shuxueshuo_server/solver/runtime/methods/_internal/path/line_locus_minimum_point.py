"""Private line-locus attainment solver for atomic path kernels.

由最短线段和动点轨迹直线求最短状态下的动点坐标。
"""

from __future__ import annotations

from ..._common import *


class LineLocusMinimumPointMethod:
    """求最短线段与动点轨迹直线的交点。"""

    method_id = "line_locus_minimum_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        moving_locus = inputs["moving_locus"]
        minimum_point_1: Point = inputs["minimum_point_1"]
        minimum_point_2: Point = inputs["minimum_point_2"]
        target = inputs["target"]
        target_name = _target_point_name(target)

        line_p1, line_p2 = _line_points(moving_locus)
        substitutions = _optional_parameter_substitution(
            inputs,
            line_p1,
            line_p2,
            minimum_point_1,
            minimum_point_2,
            allow_closed_noop=True,
        )
        if substitutions:
            line_p1, line_p2, minimum_point_1, minimum_point_2 = (
                _subs_point(point, substitutions)
                for point in (line_p1, line_p2, minimum_point_1, minimum_point_2)
            )
        point = kernel.line_intersection(
            (minimum_point_1, minimum_point_2),
            (line_p1, line_p2),
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "minimum_point_on_minimum_segment",
                    point_collinear(point, minimum_point_1, minimum_point_2),
                    f"{target_name} 在最短线段上",
                ),
                _check(
                    "minimum_point_on_locus",
                    point_collinear(point, line_p1, line_p2),
                    f"{target_name} 在动点轨迹直线上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "求最短状态动点",
                    f"确定 {target_name} 的坐标",
                    "最短状态下，动点是拉直后的最短线段与原动点轨迹直线的交点。",
                    f"{target_name}=({_fmt_point(point, kernel)})",
                    f"{target_name}({_fmt_point(point, kernel)})",
                )
            ],
        )


def _line_points(line: dict[str, Any]) -> tuple[Point, Point]:
    """从 Line payload 读取一条直线上的两个点。"""
    start = _line_point(line, "start_point")
    direction = _line_point(line, "direction")
    end = (
        sp.simplify(start[0] + direction[0]),
        sp.simplify(start[1] + direction[1]),
    )
    return start, end


def _line_point(line: dict[str, Any], key: str) -> Point:
    """读取 Line payload 中的二维点或方向。"""
    raw = line.get(key)
    if isinstance(raw, list) and len(raw) == 2:
        raw = tuple(raw)
    if not isinstance(raw, tuple) or len(raw) != 2:
        raise method_input_invalid(
            "moving locus requires a two-dimensional point or direction",
            arg_name="moving_locus",
            role=key,
            expected={"dimension": 2},
            observed={"value": raw},
        )
    return (sp.simplify(raw[0]), sp.simplify(raw[1]))


def _target_point_name(target: PointRef | Point) -> str:
    """读取最短状态动点的显示名。

    ``line_locus_minimum_point`` 的 target 只用于 trace/check 文案。若 target
    实体已经被前序步骤求成 Point，executor 会先从 runtime path 恢复 PointRef。
    """
    if isinstance(target, PointRef):
        return target.name
    raise StatelessMethodError(
        "planner.method_contract_invalid",
        "target must be a PointRef; target identity was not restored before "
        "Method execution",
        category="configuration",
        retryability="configuration",
        arg_name="target",
        role="minimum_point_target",
        expected={"type": "PointRef"},
        observed={"type": type(target).__name__},
        repair_action="fix_runtime_contract",
    )


__all__ = ["LineLocusMinimumPointMethod"]
