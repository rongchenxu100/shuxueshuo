"""two_moving_points_path_reduction 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class TwoMovingPointsPathReductionMethod:
    """把两个受约束动点的路径转成单动点路径。

    这个 method 不绑定南开题的 E/G/D/M/N 点名。它只要求输入描述清楚：

    - 第一个动点在哪条边上；
    - 第二个动点在哪条边上；
    - 两个动点之间的线段关系；
    - 两条边的三个基准点坐标。

    method 会用一个统一参数表示两个动点，验证线段关系，并证明原路径中的两动点
    线段可以替换为“固定点-第二动点”线段。
    """

    method_id = "two_moving_points_path_reduction"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        original_path = inputs["original_path"]
        first_membership = inputs["first_moving_membership"]
        second_membership = inputs["second_moving_membership"]
        binding_relation = inputs["binding_relation"]
        first_segment_start: Point = inputs["first_segment_start"]
        joint_point: Point = inputs["joint_point"]
        second_segment_end: Point = inputs["second_segment_end"]
        path_text = str(original_path["path"])

        first_moving_name = str(first_membership["point"])
        second_moving_name = str(second_membership["point"])
        first_segment_names = [str(name) for name in first_membership["segment"]]
        second_segment_names = [str(name) for name in second_membership["segment"]]
        left_scale, left_segment = _parse_scaled_segment(str(binding_relation["left"]), kernel)
        right_scale, right_segment = _parse_scaled_segment(str(binding_relation["right"]), kernel)
        fixed_name = _other_segment_endpoint(left_segment, first_moving_name)
        second_fixed_name = _other_segment_endpoint(right_segment, second_moving_name)
        _validate_moving_point_memberships(
            first_segment_names,
            second_segment_names,
            fixed_name,
            second_fixed_name,
        )
        replaced_segment = f"{first_moving_name}{second_moving_name}"
        replacement_segment = f"{fixed_name}{second_moving_name}"
        transformed_path = _replace_segment_in_path(path_text, replaced_segment, replacement_segment)

        t = sp.Symbol("t", real=True)
        first_ratio = sp.simplify(
            (right_scale / left_scale)
            * kernel.distance(second_segment_end, joint_point)
            / kernel.distance(first_segment_start, joint_point)
        )
        first_moving_point = (
            sp.simplify(first_segment_start[0] + first_ratio * t * (joint_point[0] - first_segment_start[0])),
            sp.simplify(first_segment_start[1] + first_ratio * t * (joint_point[1] - first_segment_start[1])),
        )
        second_moving_point = (
            sp.simplify(second_segment_end[0] + t * (joint_point[0] - second_segment_end[0])),
            sp.simplify(second_segment_end[1] + t * (joint_point[1] - second_segment_end[1])),
        )
        left_distance_squared = kernel.distance_squared(first_segment_start, first_moving_point)
        right_distance_squared = kernel.distance_squared(second_segment_end, second_moving_point)
        moving_distance_squared = kernel.distance_squared(first_moving_point, second_moving_point)
        replacement_distance_squared = kernel.distance_squared(first_segment_start, second_moving_point)
        transformation = {
            "original_path": path_text,
            "transformed_path": transformed_path,
            "segment_equality": f"{replaced_segment}={replacement_segment}",
            "reason": str(binding_relation.get("description", "")),
        }
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "path_transformation": TypedValue(
                    "PathTransformation",
                    transformation,
                    source=self.method_id,
                )
            },
            checks=[
                _check(
                    "moving_points_binding_relation",
                    sp.simplify(
                        left_scale**2 * left_distance_squared
                        - right_scale**2 * right_distance_squared
                    ) == 0,
                    "两个动点的绑定线段关系成立",
                ),
                _check(
                    "moving_segment_equal_fixed_segment",
                    sp.simplify(moving_distance_squared - replacement_distance_squared) == 0,
                    f"{replaced_segment} 与 {replacement_segment} 等长",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "把两动点路径转化为单动点路径",
                    f"将 {path_text} 转化为 {transformed_path}",
                    "利用两个动点的线段绑定关系，把原路径中的两动点线段替换成等长的固定点到动点线段。",
                    f"{binding_relation.get('description', '')}，可得 {replaced_segment}={replacement_segment}",
                    f"{path_text}={transformed_path}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=TwoMovingPointsPathReductionMethod,
    title='两动点路径降维',
    solves=('reduce_two_moving_point_path',),
    inputs={
    "original_path": {
        "type": "Condition",
        "required": True,
        "description": "原路径条件，例如 {\"path\": \"EG+FG\"}。"
    },
    "first_moving_membership": {
        "type": "Condition",
        "required": True,
        "description": "第一个动点所在边，例如 E 在线段 DM 上。"
    },
    "second_moving_membership": {
        "type": "Condition",
        "required": True,
        "description": "第二个动点所在边，例如 G 在线段 MN 上。"
    },
    "binding_relation": {
        "type": "Condition",
        "required": True,
        "description": "两个动点的线段绑定关系，例如 DE=sqrt(2)*NG。"
    },
    "first_segment_start": {
        "type": "Point",
        "required": True,
        "description": "第一条动点边上绑定线段的固定端点，例如 D。"
    },
    "joint_point": {
        "type": "Point",
        "required": True,
        "description": "两条动点边的公共端点，例如 M。"
    },
    "second_segment_end": {
        "type": "Point",
        "required": True,
        "description": "第二条动点边上绑定线段的固定端点，例如 N。"
    }
},
    outputs={
    "path_transformation": "PathTransformation"
},
    preconditions=('两个动点分别位于两条有公共端点的线段上', 'binding_relation 将第一个动点到固定端点的距离与第二个动点到固定端点的距离绑定', 'original_path 包含需要替换的两动点线段'),
    postconditions=('原路径中的两动点线段被替换为固定点到第二动点的等长线段',),
    trace_template=(),
)
