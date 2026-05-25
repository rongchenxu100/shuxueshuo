"""broken_path_straightening_candidates 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class BrokenPathStraighteningCandidatesMethod:
    """为单动点折线路径生成“将军饮马”拉直候选。

    这个 method 接收上一步已经得到的单动点路径，例如 ``DG+FG``，以及动点所在
    直线 ``MN``。它不会预设应该反射 D 还是反射 F，而是分别把两个固定端点关于
    动点所在直线作对称，得到两种候选：

    - 反射第一个固定端点：``DG+FG -> D'G+FG``，最短候选为 ``D'F``；
    - 反射第二个固定端点：``DG+FG -> DG+F'G``，最短候选为 ``DF'``。

    后续选择哪个候选，由 ``select_straightening_candidate`` 根据可计算性策略决定。
    """

    method_id = "broken_path_straightening_candidates"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        transformation = inputs["path_transformation"]
        moving_membership = inputs["moving_point_membership"]
        fixed_point_1: Point = inputs["fixed_point_1"]
        fixed_point_2: Point = inputs["fixed_point_2"]
        line_point_1: Point = inputs["line_point_1"]
        line_point_2: Point = inputs["line_point_2"]
        transformed_path = str(transformation["transformed_path"])
        segments = _parse_path_segments(transformed_path)
        if len(segments) != 2:
            raise ValueError("broken_path_straightening_candidates requires a two-segment broken path")
        moving_point_name = _common_endpoint(segments[0], segments[1])
        expected_moving = str(moving_membership["point"])
        if moving_point_name != expected_moving:
            raise ValueError(
                f"path moving point {moving_point_name!r} does not match membership {expected_moving!r}"
            )
        fixed_name_1 = _other_segment_endpoint(segments[0], moving_point_name)
        fixed_name_2 = _other_segment_endpoint(segments[1], moving_point_name)
        moving_line_name = "".join(str(name) for name in moving_membership["segment"])
        candidates = [
            _straightening_candidate(
                kernel=kernel,
                transformed_path=transformed_path,
                moving_point_name=moving_point_name,
                moving_line_name=moving_line_name,
                source_name=fixed_name_1,
                source_point=fixed_point_1,
                other_name=fixed_name_2,
                other_point=fixed_point_2,
                line_point_1=line_point_1,
                line_point_2=line_point_2,
            ),
            _straightening_candidate(
                kernel=kernel,
                transformed_path=transformed_path,
                moving_point_name=moving_point_name,
                moving_line_name=moving_line_name,
                source_name=fixed_name_2,
                source_point=fixed_point_2,
                other_name=fixed_name_1,
                other_point=fixed_point_1,
                line_point_1=line_point_1,
                line_point_2=line_point_2,
            ),
        ]
        checks: list[CheckResult] = []
        for candidate in candidates:
            moving_point = _generic_point_on_line(line_point_1, line_point_2)
            source_point = candidate["source_point"]
            reflected_point = candidate["reflected_point"]
            checks.append(
                _check(
                    f"{candidate['id']}_reflection_preserves_distance",
                    sp.simplify(
                        kernel.distance_squared(source_point, moving_point)
                        - kernel.distance_squared(reflected_point, moving_point)
                    ) == 0,
                    f"{candidate['reflected_point_name']} 关于 {moving_line_name} 对称后保持到动点的距离",
                )
            )
        calculation = "；".join(
            (
                f"反射 {candidate['reflect_source']} 得 {candidate['reflected_point_name']}"
                f"({_fmt_point(candidate['reflected_point'], kernel)})，候选最短线段"
                f" {candidate['minimum_segment']}"
            )
            for candidate in candidates
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "candidates": TypedValue(
                    "StraighteningCandidateList",
                    candidates,
                    source=self.method_id,
                )
            },
            checks=checks,
            trace_fragments=[
                _step(
                    self.method_id,
                    "列出折线拉直候选",
                    f"为 {transformed_path} 生成可选的将军饮马转化",
                    "动点在同一直线上时，可以把折线一端关于动点所在直线作对称，把折线最短问题转成两定点距离问题。",
                    calculation,
                    f"得到 {len(candidates)} 个拉直候选",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=BrokenPathStraighteningCandidatesMethod,
    title='折线拉直候选生成',
    solves=('derive_broken_path_straightening_candidates',),
    inputs={
    "path_transformation": {
        "type": "PathTransformation",
        "required": True,
        "description": "上一步得到的路径转化，例如 EG+FG=DG+FG。"
    },
    "moving_point_membership": {
        "type": "Condition",
        "required": True,
        "description": "动点所在直线/线段，例如 G 在线段 MN 上。"
    },
    "fixed_point_1": {
        "type": "Point",
        "required": True,
        "description": "折线路径的第一个固定端点。"
    },
    "fixed_point_2": {
        "type": "Point",
        "required": True,
        "description": "折线路径的第二个固定端点。"
    },
    "line_point_1": {
        "type": "Point",
        "required": True,
        "description": "动点所在直线上的第一个点。"
    },
    "line_point_2": {
        "type": "Point",
        "required": True,
        "description": "动点所在直线上的第二个点。"
    }
},
    outputs={
    "candidates": "StraighteningCandidateList"
},
    preconditions=('path_transformation.transformed_path 是由两条线段组成的单动点折线', 'moving_point_membership.point 是两条线段的公共端点', 'line_point_1 与 line_point_2 确定动点所在直线'),
    postconditions=('每个候选都包含一个反射点和对应的最短线段',),
    trace_template=(),
)
