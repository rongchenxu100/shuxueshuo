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
        moving_membership = inputs.get("moving_point_membership")
        moving_locus = inputs.get("moving_locus")
        fixed_point_1: Point = inputs["fixed_point_1"]
        fixed_point_2: Point = inputs["fixed_point_2"]
        line_point_1, line_point_2, moving_line_name, expected_moving = _line_from_inputs(
            moving_membership=moving_membership,
            moving_locus=moving_locus,
            inputs=inputs,
        )
        transformed_path = str(transformation["transformed_path"])
        segments = _parse_path_segments(transformed_path)
        if len(segments) != 2:
            raise ValueError("broken_path_straightening_candidates requires a two-segment broken path")
        moving_point_name = _common_endpoint(segments[0], segments[1])
        if expected_moving is not None and moving_point_name != expected_moving:
            raise ValueError(
                f"path moving point {moving_point_name!r} does not match membership {expected_moving!r}"
            )
        fixed_name_1 = _other_segment_endpoint(segments[0], moving_point_name)
        fixed_name_2 = _other_segment_endpoint(segments[1], moving_point_name)
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
    summary='输入: 折线路径两端点、运动线段和辅助点定义；输出: 可用于将军饮马/折线拉直的候选方案。',
    solves=('derive_broken_path_straightening_candidates',),
    inputs={
    "path_transformation": {
        "type": "PathTransformation",
        "required": True,
        "description": "上一步得到的路径转化，例如 EG+FG=DG+FG。"
    },
    "moving_point_membership": {
        "type": "Condition",
        "required": False,
        "description": "动点所在直线/线段，例如 G 在线段 MN 上。"
    },
    "moving_locus": {
        "type": "Line",
        "required": False,
        "description": "动点轨迹直线；若提供该输入，则不需要 moving_point_membership 和 line_point_1/line_point_2。"
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
        "required": False,
        "description": "动点所在直线上的第一个点。"
    },
    "line_point_2": {
        "type": "Point",
        "required": False,
        "description": "动点所在直线上的第二个点。"
    }
},
    outputs={
    "candidates": "StraighteningCandidateList"
},
    preconditions=('path_transformation.transformed_path 是由两条线段组成的单动点折线', '提供 moving_locus，或同时提供 moving_point_membership、line_point_1 和 line_point_2', '动点轨迹直线与 transformed_path 的公共动点一致'),
    postconditions=('每个候选都包含一个反射点和对应的最短线段',),
    trace_template=(),
)


def _line_from_inputs(
    *,
    moving_membership: dict[str, Any] | None,
    moving_locus: dict[str, Any] | None,
    inputs: dict[str, Any],
) -> tuple[Point, Point, str, str | None]:
    """从 membership 或直接 Line 输入读取动点所在直线。"""
    if moving_locus is not None:
        start = _line_point(moving_locus, "start_point")
        direction = _line_point(moving_locus, "direction")
        line_point_2 = (
            sp.simplify(start[0] + direction[0]),
            sp.simplify(start[1] + direction[1]),
        )
        point_name = str(moving_locus["point_name"]) if "point_name" in moving_locus else ""
        expected = None if point_name in {"", "moving_point", "point", "P"} else point_name
        return (
            start,
            line_point_2,
            str(moving_locus.get("equation") or moving_locus.get("point_name") or "moving_locus"),
            expected,
        )
    if moving_membership is None:
        raise ValueError("broken_path_straightening_candidates requires moving_locus or moving_point_membership")
    if "line_point_1" not in inputs or "line_point_2" not in inputs:
        raise ValueError("moving_point_membership mode requires line_point_1 and line_point_2")
    return (
        inputs["line_point_1"],
        inputs["line_point_2"],
        "".join(str(name) for name in moving_membership["segment"]),
        str(moving_membership["point"]),
    )


def _line_point(line: dict[str, Any], key: str) -> Point:
    raw = line.get(key)
    if isinstance(raw, list) and len(raw) == 2:
        raw = tuple(raw)
    if not isinstance(raw, tuple) or len(raw) != 2:
        raise ValueError(f"moving_locus requires 2D {key}")
    return (sp.simplify(raw[0]), sp.simplify(raw[1]))
