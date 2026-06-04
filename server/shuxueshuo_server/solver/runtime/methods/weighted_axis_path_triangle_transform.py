"""weighted_axis_path_triangle_transform 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class WeightedAxisPathTriangleTransformMethod:
    """用直角三角形把加权 x 轴动点路径转化为普通折线路径。

    当前实现覆盖河西 25 的 ``sqrt(2)*MN + AN``：在 x 轴上以 A、N 为端点构造
    等腰直角三角形 AQN，使 ``AN = sqrt(2)*QN``，于是原路径可转为
    ``sqrt(2)*(MN + QN)``。后续遇到 30°/60° 直角三角形时，可以在这个 method
    内按权重扩展辅助点构造，而不是让 planner 直接写死辅助点坐标。
    """

    method_id = "weighted_axis_path_triangle_transform"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        condition = inputs["condition"]
        fixed_point: Point = inputs["fixed_point"]
        moving_point: Point = inputs["moving_point"]
        dynamic_parameter = inputs["dynamic_parameter"]
        auxiliary_point_ref: PointRef = inputs["auxiliary_point_ref"]

        if sp.simplify(fixed_point[1]) != 0 or sp.simplify(moving_point[1]) != 0:
            raise ValueError("weighted_axis_path_triangle_transform requires points on x-axis")
        if sp.simplify(moving_point[0] - dynamic_parameter) != 0:
            raise ValueError("moving point x-coordinate must be the dynamic parameter")

        path_info = _parse_weighted_axis_path(str(condition["path"]), kernel)
        weight = path_info["weight"]
        if sp.simplify(weight - sp.sqrt(2)) != 0:
            raise ValueError("current triangle transform only supports sqrt(2) weight")

        fixed_name = str(path_info["fixed_name"])
        moving_name = str(path_info["moving_name"])
        curve_name = str(path_info["curve_name"])
        auxiliary_name = auxiliary_point_ref.name
        auxiliary_segment = f"{auxiliary_name}{moving_name}"
        inner_path = f"{path_info['weighted_segment']}+{auxiliary_segment}"
        transformed_path = f"{kernel.sstr(weight)}*({inner_path})"

        # 以 fixed(ax,0)、moving(n,0) 为斜边端点，在 x 轴上方构造等腰直角三角形。
        # 辅助点名称由 planner 传入的 PointRef 决定；method 只负责坐标构造和验算。
        # 坐标公式为 ((ax+n)/2, (n-ax)/2)，保证两条直角边垂直且等长。
        ax = fixed_point[0]
        n = dynamic_parameter
        auxiliary_point = (
            sp.simplify((ax + n) / 2),
            sp.simplify((n - ax) / 2),
        )
        aq_squared = kernel.distance_squared(fixed_point, auxiliary_point)
        qn_squared = kernel.distance_squared(auxiliary_point, moving_point)
        an_squared = kernel.distance_squared(fixed_point, moving_point)
        right_angle_dot = dot_from_origin(auxiliary_point, fixed_point, moving_point)
        locus_equation = sp.simplify(auxiliary_point[1] - (auxiliary_point[0] - ax))
        auxiliary_locus = {
            "kind": "ray",
            "point_name": auxiliary_name,
            "start_name": fixed_name,
            "start_point": fixed_point,
            "direction": (sp.Integer(1), sp.Integer(1)),
            "equation": f"y=x-({kernel.sstr(ax)})",
            "reason": f"{auxiliary_name} 随 {moving_name} 在由 {fixed_name} 引出的 45 度射线上运动。",
        }
        transformation = {
            "type": "weighted_axis_triangle_transform",
            "original_path": str(condition["path"]),
            "weight": weight,
            "construction": "right_isosceles_triangle",
            "fixed_point_name": fixed_name,
            "moving_point_name": moving_name,
            "curve_point_name": curve_name,
            "auxiliary_point_name": auxiliary_name,
            "transformed_path": transformed_path,
            "inner_path": inner_path,
            "scale": weight,
            "reason": (
                f"构造等腰直角三角形 {fixed_name}{auxiliary_name}{moving_name}，"
                f"使 {fixed_name}{moving_name}={kernel.sstr(weight)}*{auxiliary_segment}。"
            ),
        }

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "auxiliary_point": TypedValue(
                    "Point",
                    auxiliary_point,
                    source=self.method_id,
                ),
                "path_transformation": TypedValue(
                    "PathTransformation",
                    transformation,
                    source=self.method_id,
                ),
                "auxiliary_locus": TypedValue(
                    "Line",
                    auxiliary_locus,
                    source=self.method_id,
                ),
            },
            checks=[
                _check(
                    "triangle_is_right_angle",
                    sp.simplify(right_angle_dot) == 0,
                    f"{fixed_name}{auxiliary_name} 与 {auxiliary_name}{moving_name} 垂直",
                ),
                _check(
                    "triangle_equal_legs",
                    sp.simplify(aq_squared - qn_squared) == 0,
                    f"{fixed_name}{auxiliary_name} 与 {auxiliary_name}{moving_name} 等长",
                ),
                _check(
                    "weighted_segment_replaced",
                    sp.simplify(an_squared - weight**2 * qn_squared) == 0,
                    f"{fixed_name}{moving_name} 可以替换为 {kernel.sstr(weight)}*{auxiliary_segment}",
                ),
                _check(
                    "auxiliary_point_on_fixed_ray",
                    locus_equation == 0,
                    f"{auxiliary_name} 在由 {fixed_name} 引出的 45 度射线上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "构造辅助三角形转化加权路径",
                    f"将 {condition['path']} 转化为 {transformed_path}",
                    (
                        f"构造等腰直角三角形 {fixed_name}{auxiliary_name}{moving_name}，"
                        f"把加权项 {fixed_name}{moving_name} 改写成同倍率下的"
                        f" {auxiliary_segment}，从而把加权路径转成普通折线路径。"
                    ),
                    (
                        f"{auxiliary_name}=({_fmt_point(auxiliary_point, kernel)})，"
                        f"{fixed_name}{moving_name}={kernel.sstr(weight)}*{auxiliary_segment}"
                    ),
                    f"{condition['path']}={transformed_path}",
                )
            ],
        )


def _parse_weighted_axis_path(path: str, kernel: SympyKernel) -> dict[str, Any]:
    """解析 ``sqrt(2)*MN+AN`` 这类“加权线段 + 轴上线段”路径。

    返回的点名只来自题面路径文本；辅助点名不在这里生成，而由 planner 通过
    ``auxiliary_point_ref`` 显式传入。
    """
    terms = _parse_path_segments(path)
    if len(terms) != 2:
        raise ValueError(f"weighted axis path must have two segments: {path}")
    weight, weighted_segment = _parse_scaled_segment(terms[0], kernel)
    axis_weight, axis_segment = _parse_scaled_segment(terms[1], kernel)
    if sp.simplify(axis_weight - 1) != 0:
        raise ValueError(f"axis segment must not be weighted: {path}")
    moving_name = _common_endpoint(weighted_segment, axis_segment)
    return {
        "weight": weight,
        "weighted_segment": weighted_segment,
        "axis_segment": axis_segment,
        "moving_name": moving_name,
        "fixed_name": _other_segment_endpoint(axis_segment, moving_name),
        "curve_name": _other_segment_endpoint(weighted_segment, moving_name),
    }


SPEC = MethodSpecSource(
    method_cls=WeightedAxisPathTriangleTransformMethod,
    title="加权路径的直角三角形转化",
    summary=(
        "输入: sqrt(2) 加权路径、轴上动点和辅助点定义；输出: 几何转化后的等价路径与辅助点轨迹。"
        "使用边界: 当前实现只支持 sqrt(2) 权重，对应等腰直角三角形转化；30°/60° 等其他权重需新增扩展后再使用。"
    ),
    solves=("transform_weighted_axis_path_by_triangle",),
    inputs={
        "condition": {
            "type": "Condition",
            "required": True,
            "description": "加权路径条件，例如 {\"path\": \"sqrt(2)*MN+AN\"}。",
        },
        "fixed_point": {
            "type": "Point",
            "required": True,
            "description": "x 轴上的固定端点，例如 A。",
        },
        "moving_point": {
            "type": "Point",
            "required": True,
            "description": "x 轴上的动点，例如 N(n,0)。",
        },
        "dynamic_parameter": {
            "type": "Symbol",
            "required": True,
            "description": "动点横坐标参数，例如 n。",
        },
        "auxiliary_point_ref": {
            "type": "PointRef",
            "required": True,
            "description": "planner 声明的辅助点引用；method 使用它的点名生成路径转化。",
        },
    },
    outputs={
        "auxiliary_point": "Point",
        "path_transformation": "PathTransformation",
        "auxiliary_locus": "Line",
    },
    preconditions=(
        "fixed_point 与 moving_point 在 x 轴上",
        "加权路径的权重必须为 sqrt(2)，当前切片只支持等腰直角三角形转化",
    ),
    postconditions=("输出 planner 指定的辅助点、路径转化说明与辅助点运动射线",),
)
