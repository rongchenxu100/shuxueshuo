"""Private broken-path straightening candidates for atomic path kernels.

No ``SPEC`` is defined here; this implementation cannot be registered as a
Planner-facing Method without crossing the tested internal boundary.
"""

from __future__ import annotations

from ..._common import *
from ..._common import _canonical_reference_name, _canonical_segment_name


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
            raise method_precondition_failed(
                "straightening requires a two-segment broken path",
                arg_name="path_transformation",
                role="transformed_path",
                expected={"segment_count": 2},
                observed={"segment_count": len(segments), "path": transformed_path},
            )
        moving_point_name = _common_endpoint(segments[0], segments[1])
        if expected_moving is not None and moving_point_name != expected_moving:
            raise method_result_inconsistent(
                "path moving point conflicts with its membership condition",
                role="moving_point",
                internal_ref=expected_moving,
                expected={"point": expected_moving},
                observed={"point": moving_point_name},
                retryability="planner_repairable",
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
        for candidate in candidates:
            _attach_structured_candidate_roles(candidate, transformation)
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
        raise method_input_missing(
            "straightening requires a moving locus or membership condition",
            arg_name="moving_locus",
            role="moving_locus",
            expected={"one_of": ["moving_locus", "moving_point_membership"]},
        )
    if "line_point_1" not in inputs or "line_point_2" not in inputs:
        missing = [
            key
            for key in ("line_point_1", "line_point_2")
            if key not in inputs
        ]
        raise method_input_missing(
            "membership mode requires two materialized points on the moving line",
            arg_name=missing[0],
            role="moving_locus_endpoint",
            expected={"required_args": ["line_point_1", "line_point_2"]},
            observed={"missing_args": missing},
            repair_action="provide_visible_point_producer",
        )
    return (
        inputs["line_point_1"],
        inputs["line_point_2"],
        _canonical_segment_name(moving_membership["segment"]),
        _canonical_reference_name(moving_membership["point"]),
    )


def _line_point(line: dict[str, Any], key: str) -> Point:
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


def _attach_structured_candidate_roles(
    candidate: dict[str, Any],
    transformation: dict[str, Any],
) -> None:
    """Carry canonical path roles into the selected-candidate state."""

    fixed_refs = transformation.get("fixed_endpoint_refs")
    moving_ref = transformation.get("moving_point_ref")
    locus_refs = transformation.get("moving_locus_endpoint_refs")
    if not (
        isinstance(fixed_refs, list)
        and len(fixed_refs) == 2
        and all(_canonical_point_ref(item) for item in fixed_refs)
        and _canonical_point_ref(moving_ref)
        and isinstance(locus_refs, list)
        and len(locus_refs) == 2
        and all(_canonical_point_ref(item) for item in locus_refs)
    ):
        return
    fixed_by_name = {
        str(item).rsplit(":", 1)[-1]: str(item)
        for item in fixed_refs
    }
    source_ref = fixed_by_name.get(str(candidate.get("reflect_source", "")))
    other_ref = fixed_by_name.get(str(candidate.get("other_fixed_point", "")))
    if source_ref is None or other_ref is None:
        return
    candidate.update(
        {
            "reflect_source_ref": source_ref,
            "other_fixed_point_ref": other_ref,
            "moving_point_ref": moving_ref,
            "moving_locus_condition_ref": transformation.get(
                "moving_locus_condition_ref"
            ),
            "moving_locus_segment_ref": transformation.get(
                "moving_locus_segment_ref"
            ),
            "moving_locus_endpoint_refs": list(locus_refs),
            "source_path_transformation_refs": list(
                transformation.get("source_condition_refs", ())
            ),
        }
    )


def _canonical_point_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("point:")


__all__ = ["BrokenPathStraighteningCandidatesMethod"]
