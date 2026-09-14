"""Private weighted-path triangle transform for the atomic weighted kernel.

No ``SPEC`` is defined here; this implementation cannot be registered as a
Planner-facing Method without crossing the tested internal boundary.
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.weighted_triangle_geometry import (
    WeightedTriangleGeometryDomainError,
    weighted_triangle_geometry_for_weight,
)

from ..._common import *


class WeightedAxisPathTriangleTransformMethod:
    """用直角三角形把加权 x 轴动点路径转化为普通折线路径。

    对任意常数权重 ``w>1``，辅助点坐标统一由固定端点到动点偏移的
    ``(w²-1)/w²`` 与 ``sqrt(w²-1)/w²`` 分解得到。runtime 只验证直角、
    边长倍率和射线方向；等腰直角或 30°/60° 等学生叙事由教学层选择。
    """

    method_id = "weighted_axis_path_triangle_transform"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        condition = inputs["condition"]
        fixed_point: Point = inputs["fixed_point"]
        moving_point: Point = inputs["moving_point"]
        dynamic_parameter = inputs["dynamic_parameter"]
        auxiliary_point_ref: PointRef = inputs["auxiliary_point_ref"]
        orientation_sign = int(inputs.get("_orientation_sign", 1))
        if orientation_sign not in {-1, 1}:
            raise StatelessMethodError(
                "planner.method_contract_invalid",
                "weighted triangle orientation must be +1 or -1",
                category="configuration",
                retryability="configuration",
                arg_name="_orientation_sign",
                role="internal_geometry_orientation",
                expected={"values": [-1, 1]},
                observed={"value": orientation_sign},
                repair_action="fix_runtime_contract",
            )
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

        path_info = _parse_weighted_axis_path_condition(condition, kernel)
        weight = path_info["weight"]
        try:
            geometry = weighted_triangle_geometry_for_weight(weight)
        except WeightedTriangleGeometryDomainError as exc:
            raise method_precondition_failed(
                "weighted path requires a constant real weight greater than one",
                arg_name="condition",
                role="path_weight",
                expected={"domain": "constant real weight > 1"},
                observed={"weight": str(exc.weight)},
                repair_action="choose_valid_weighted_path_capability",
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
        # 坐标与射线方向都由同一组通用结构系数导出；materialized
        # transformation 会在下游再次逐字段校验，避免漂移的 geometry 进入
        # linked broken path method。
        ax = fixed_point[0]
        n = dynamic_parameter
        offset = sp.simplify(n - ax)
        leg_factor = geometry.leg_factor
        height_factor = geometry.height_factor
        auxiliary_point = (
            sp.simplify(ax + offset * leg_factor),
            sp.simplify(orientation_sign * offset * height_factor),
        )
        qn_squared = kernel.distance_squared(auxiliary_point, moving_point)
        an_squared = kernel.distance_squared(fixed_point, moving_point)
        right_angle_dot = dot_from_origin(auxiliary_point, fixed_point, moving_point)
        direction = (
            geometry.direction_value[0],
            sp.simplify(
                orientation_sign * geometry.direction_value[1]
            ),
        )
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
                "固定射线上运动。"
            ),
        }
        transformation = {
            "type": "weighted_axis_triangle_transform",
            "original_path": str(condition["path"]),
            "weight": weight,
            "construction": "weighted_right_triangle",
            "fixed_point_name": fixed_name,
            "moving_point_name": moving_name,
            "curve_point_name": curve_name,
            "auxiliary_point_name": auxiliary_name,
            "auxiliary_point_ref": _canonical_point_ref(auxiliary_point_ref),
            "transformed_path": transformed_path,
            "inner_path": inner_path,
            "scale": weight,
            "geometry": geometry.to_payload(),
            "path_equivalence": {
                "weighted_segment": ["curve_point", "moving_point"],
                "unit_segment": ["fixed_point", "moving_point"],
                "auxiliary_segment": ["auxiliary_point", "moving_point"],
                "scale": kernel.sstr(weight),
            },
            "orientation_sign": orientation_sign,
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
                    f"{auxiliary_name} 在由 {fixed_name} 引出的固定射线上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "构造辅助三角形转化加权路径",
                    f"将 {condition['path']} 转化为 {transformed_path}",
                    (
                        f"构造直角三角形 {fixed_name}{auxiliary_name}{moving_name}，"
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


def _parse_weighted_axis_path_condition(
    condition: dict[str, Any],
    kernel: SympyKernel,
) -> dict[str, Any]:
    """Prefer canonical typed terms; keep path text for legacy callers only."""

    terms = condition.get("terms")
    if isinstance(terms, list):
        parsed: list[tuple[sp.Expr, tuple[str, str]]] = []
        for item in terms:
            if isinstance(item, dict):
                segment = item.get("segment")
                scale = item.get("scale", "1")
            else:
                segment = item
                scale = "1"
            if (
                not isinstance(segment, list)
                or len(segment) != 2
                or not all(isinstance(value, str) for value in segment)
            ):
                raise method_input_invalid(
                    "weighted-axis typed path term is invalid",
                    arg_name="condition",
                    role="weighted_path",
                )
            parsed.append(
                (
                    sp.simplify(
                        _require_canonical_runtime_expression(
                            scale,
                            kernel,
                            arg_name="condition",
                            role="path_scale",
                        )
                    ),
                    (str(segment[0]), str(segment[1])),
                )
            )
        weighted = tuple(item for item in parsed if sp.simplify(item[0] - 1) != 0)
        unit = tuple(item for item in parsed if sp.simplify(item[0] - 1) == 0)
        if len(weighted) != 1 or len(unit) != 1:
            raise method_precondition_failed(
                "weighted-axis typed path requires one weighted and one unit term",
                arg_name="condition",
                role="weighted_path",
            )
        weight, weighted_pair = weighted[0]
        _, unit_pair = unit[0]
        shared = tuple(item for item in weighted_pair if item in unit_pair)
        if len(shared) != 1:
            raise method_precondition_failed(
                "weighted-axis typed path terms must share one endpoint",
                arg_name="condition",
                role="weighted_path",
            )
        moving = shared[0]
        curve = next(item for item in weighted_pair if item != moving)
        fixed = next(item for item in unit_pair if item != moving)
        return {
            "weight": weight,
            "weighted_segment": f"{_point_label(curve)}{_point_label(moving)}",
            "axis_segment": f"{_point_label(fixed)}{_point_label(moving)}",
            "moving_name": _point_label(moving),
            "fixed_name": _point_label(fixed),
            "curve_name": _point_label(curve),
        }
    return _parse_weighted_axis_path(str(condition["path"]), kernel)


def _point_label(handle: str) -> str:
    return handle.rsplit(":", 1)[-1]


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


__all__ = ["WeightedAxisPathTriangleTransformMethod"]
