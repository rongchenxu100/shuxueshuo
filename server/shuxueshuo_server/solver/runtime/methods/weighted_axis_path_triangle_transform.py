"""weighted_axis_path_triangle_transform 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.weighted_triangle_geometry import (
    WeightedTriangleGeometryUnsupportedError,
    weighted_triangle_geometry_for_weight,
    weighted_triangle_geometry_payloads,
)

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


class WeightedAxisPathTriangleTransformMethod:
    """用直角三角形把加权 x 轴动点路径转化为普通折线路径。

    method 支持两类中考常见权重：

    - ``sqrt(2)``：等腰直角三角形，``AN = sqrt(2)*QN``；
    - ``2``：30°/60° 直角三角形，``AN = 2*QN``。

    对一般权重 ``w>1``，辅助点坐标公式可以统一写成固定端点到动点偏移的
    ``(w^2-1)/w^2`` 与 ``sqrt(w^2-1)/w^2`` 分解。但后续折线路径最值还依赖
    辅助点运动方向和三角形几何解释，所以本 method 不把任意 ``w>1`` 自动视为
    已支持能力；只有在共享 geometry profile registry 中登记并补过验算的权重
    才会开放。当前只登记 ``sqrt(2)`` 与 ``2``。
    """

    method_id = "weighted_axis_path_triangle_transform"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        condition = inputs["condition"]
        fixed_point: Point = inputs["fixed_point"]
        moving_point: Point = inputs["moving_point"]
        dynamic_parameter = inputs["dynamic_parameter"]
        auxiliary_point_ref: PointRef = inputs["auxiliary_point_ref"]
        moving_point_ref: PointRef | None = inputs.get("moving_point_ref")
        linked_fixed_endpoint_ref: PointRef | None = inputs.get(
            "linked_fixed_endpoint_ref"
        )

        if sp.simplify(fixed_point[1]) != 0 or sp.simplify(moving_point[1]) != 0:
            raise method_precondition_failed(
                "weighted-axis transformation requires both points on the x-axis",
                role="axis_points",
                expected={"y_coordinates": [0, 0]},
                observed={"y_coordinates": [fixed_point[1], moving_point[1]]},
            )
        if sp.simplify(moving_point[0] - dynamic_parameter) != 0:
            raise method_precondition_failed(
                "moving point x-coordinate must equal the dynamic parameter",
                arg_name="moving_point",
                role="moving_point",
                expected={"x": dynamic_parameter},
                observed={"x": moving_point[0]},
            )

        path_info = _parse_weighted_axis_path(str(condition["path"]), kernel)
        weight = path_info["weight"]
        try:
            geometry = weighted_triangle_geometry_for_weight(weight)
        except WeightedTriangleGeometryUnsupportedError as exc:
            raise method_precondition_failed(
                "weighted path uses an unsupported triangle geometry weight",
                arg_name="condition",
                role="path_weight",
                expected={"supported_weights": list(exc.supported)},
                observed={"weight": str(exc.weight)},
                repair_action="choose_supported_weighted_path_capability",
            ) from exc

        fixed_name = str(path_info["fixed_name"])
        moving_name = str(path_info["moving_name"])
        curve_name = str(path_info["curve_name"])
        auxiliary_name = auxiliary_point_ref.name
        auxiliary_segment = f"{auxiliary_name}{moving_name}"
        inner_path = f"{path_info['weighted_segment']}+{auxiliary_segment}"
        transformed_path = f"{kernel.sstr(weight)}*({inner_path})"

        # 以 fixed(ax,0)、moving(n,0) 为一条斜边关系构造直角三角形。
        # 设 L=n-ax，要求 fixed-moving = weight * auxiliary-moving。
        # 辅助点坐标统一为：
        #   x = ax + L * (w^2 - 1) / w^2
        #   y =      L * sqrt(w^2 - 1) / w^2
        # 坐标公式对已登记的 weight 复用；direction 不从公式自动推导，而是
        # 来自共享 geometry profile，避免未验算 geometry 进入
        # 后续 linked broken path method。
        ax = fixed_point[0]
        n = dynamic_parameter
        offset = sp.simplify(n - ax)
        weight_sq = sp.simplify(weight**2)
        leg_factor = sp.simplify((weight_sq - 1) / weight_sq)
        height_factor = sp.simplify(sp.sqrt(weight_sq - 1) / weight_sq)
        auxiliary_point = (
            sp.simplify(ax + offset * leg_factor),
            sp.simplify(offset * height_factor),
        )
        qn_squared = kernel.distance_squared(auxiliary_point, moving_point)
        an_squared = kernel.distance_squared(fixed_point, moving_point)
        right_angle_dot = dot_from_origin(auxiliary_point, fixed_point, moving_point)
        direction = geometry.direction_value
        locus_cross = sp.simplify(
            (auxiliary_point[0] - ax) * direction[1]
            - auxiliary_point[1] * direction[0]
        )
        auxiliary_locus = {
            "kind": "ray",
            "point_name": auxiliary_name,
            "start_name": fixed_name,
            "start_point": fixed_point,
            "direction": direction,
            "equation": _locus_equation_text(ax, direction, kernel),
            "reason": (
                f"{auxiliary_name} 随 {moving_name} 在由 {fixed_name} 引出的"
                f" {geometry.angle_label} 射线上运动。"
            ),
        }
        transformation = {
            "type": "weighted_axis_triangle_transform",
            "original_path": str(condition["path"]),
            "weight": weight,
            "geometry_profile_id": geometry.profile_id,
            "construction": geometry.construction,
            "fixed_point_name": fixed_name,
            "moving_point_name": moving_name,
            "curve_point_name": curve_name,
            "auxiliary_point_name": auxiliary_name,
            "auxiliary_point_ref": _canonical_point_ref(auxiliary_point_ref),
            "transformed_path": transformed_path,
            "inner_path": inner_path,
            "scale": weight,
            "geometry": geometry.geometry,
            "reason": (
                f"构造{geometry.title} {fixed_name}{auxiliary_name}{moving_name}，"
                f"使 {fixed_name}{moving_name}={kernel.sstr(weight)}*{auxiliary_segment}。"
            ),
        }
        if moving_point_ref is not None:
            transformation["moving_point_ref"] = _canonical_point_ref(
                moving_point_ref
            )
        if linked_fixed_endpoint_ref is not None:
            transformation["linked_fixed_endpoint_ref"] = _canonical_point_ref(
                linked_fixed_endpoint_ref
            )

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
                    "triangle_leg_ratio",
                    sp.simplify(an_squared - weight**2 * qn_squared) == 0,
                    f"{fixed_name}{moving_name}={kernel.sstr(weight)}*{auxiliary_segment}",
                ),
                _check(
                    "weighted_segment_replaced",
                    sp.simplify(an_squared - weight**2 * qn_squared) == 0,
                    f"{fixed_name}{moving_name} 可以替换为 {kernel.sstr(weight)}*{auxiliary_segment}",
                ),
                _check(
                    "auxiliary_point_on_fixed_ray",
                    locus_cross == 0,
                    f"{auxiliary_name} 在由 {fixed_name} 引出的 {geometry.angle_label} 射线上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "构造辅助三角形转化加权路径",
                    f"将 {condition['path']} 转化为 {transformed_path}",
                    (
                        f"构造{geometry.title} {fixed_name}{auxiliary_name}{moving_name}，"
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
        raise method_input_invalid(
            "weighted-axis path must contain two terms",
            arg_name="condition",
            role="weighted_path",
            expected={"term_count": 2},
            observed={"term_count": len(terms), "path": path},
        )
    weight, weighted_segment = _parse_scaled_segment(terms[0], kernel)
    axis_weight, axis_segment = _parse_scaled_segment(terms[1], kernel)
    if sp.simplify(axis_weight - 1) != 0:
        raise method_precondition_failed(
            "the axis segment of the weighted path must be unweighted",
            arg_name="condition",
            role="axis_segment",
            expected={"weight": 1},
            observed={"weight": axis_weight, "segment": axis_segment},
        )
    moving_name = _common_endpoint(weighted_segment, axis_segment)
    return {
        "weight": weight,
        "weighted_segment": weighted_segment,
        "axis_segment": axis_segment,
        "moving_name": moving_name,
        "fixed_name": _other_segment_endpoint(axis_segment, moving_name),
        "curve_name": _other_segment_endpoint(weighted_segment, moving_name),
    }


def _canonical_point_ref(point_ref: PointRef) -> str:
    return f"point:{point_ref.scope_id}:{point_ref.name}"


def _locus_equation_text(
    fixed_x: sp.Expr,
    direction: tuple[sp.Expr, sp.Expr],
    kernel: SympyKernel,
) -> str:
    """生成辅助点轨迹直线的可读方程。"""
    dx, dy = direction
    return f"{kernel.sstr(dy)}*(x-({kernel.sstr(fixed_x)}))-{kernel.sstr(dx)}*y=0"


SPEC = MethodSpecSource(
    method_cls=WeightedAxisPathTriangleTransformMethod,
    title="加权路径的直角三角形转化",
    summary=(
        "距离和中有一项带大于 1 的权重，且目标恰为“一个加权线段 + 一个普通线段”、"
        "两项共享同一个 x 轴动点时，"
        "用已登记的直角三角形构造把加权项改写为普通距离。公开输入中的 "
        "minimum_value 必须引用 type=minimum_value 的题面已知最小值 fact，"
        "不能引用 path_minimum_target；该 fact 在这里只负责提供原路径，不表示"
        "本能力会求最小值。本能力只"
        "输出辅助点、等价的 PathTransformation 和辅助点轨迹，后续 linked-path "
        "最值能力再消费这些状态求最小值表达式。当前只支持权重 sqrt(2) 和 2。"
    ),
    do_not_use_when=(
        "原距离和没有权重，或只是普通两段等长/比例替换、正方形三段路径、线段与射线等长结构。",
        "动点不在声明的坐标轴上，或路径权重不是当前支持的 sqrt(2) 或 2。",
        "目标是直接得到最小值表达式、最小值或参数值；该能力只产生辅助对象、轨迹和等价路径变换。",
        "只有 path_minimum_target 而没有携带同一路径的 minimum_value fact。",
    ),
    solves=("transform_weighted_axis_path_by_triangle",),
    inputs={
        "condition": {
            "type": "Condition",
            "required": True,
            "description": (
                "type=minimum_value 的题面已知最小值条件，其中必须携带加权"
                "路径；path_minimum_target 不是该输入。"
            ),
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
        "moving_point_ref": {
            "type": "PointRef",
            "required": False,
            "description": "compiler 注入的动点对象身份。",
        },
        "linked_fixed_endpoint_ref": {
            "type": "PointRef",
            "required": False,
            "description": "compiler 注入的联动折线路径固定端点身份。",
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
    input_views=declare_input_views(
        identity=(
            "moving_point_ref",
            "linked_fixed_endpoint_ref",
            "dynamic_parameter",
            "auxiliary_point_ref",
        ),
        latest_state=("fixed_point", "moving_point"),
        immutable_value=("condition",),
    ),
    outputs={
        "auxiliary_point": "Point",
        "path_transformation": "PathTransformation",
        "auxiliary_locus": "Line",
    },
    preconditions=(
        "fixed_point 与 moving_point 在 x 轴上",
        "加权路径的权重必须在 method 的辅助三角形几何白名单中，当前为 sqrt(2) 或 2",
        "新增权重时必须同时登记 geometry/direction 并补充 transform 与 linked minimum 验算",
    ),
    postconditions=("输出 planner 指定的辅助点、路径转化说明与辅助点运动射线",),
    geometry_profiles=weighted_triangle_geometry_payloads(),
)
