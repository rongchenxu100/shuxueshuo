"""Private two-moving-point reduction for the atomic coupled kernel.

No ``SPEC`` is defined here; this implementation cannot be registered as a
Planner-facing Method without crossing the tested internal boundary.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..._common import *
from ..._common import _canonical_reference_name, _canonical_segment_name


class TwoMovingPointsPathReductionMethod:
    """把两个受约束动点的路径转成“已有固定点到动点”的单动点路径。

    这个 method 不绑定任何题目的具体点名。它只要求输入描述清楚：

    - 第一个动点在哪条边上；
    - 第二个动点在哪条边上；
    - 两个动点之间的线段关系；
    - 两条边的三个基准点坐标。

    method 会用一个统一参数表示两个动点，验证线段关系，并证明原路径中的两动点
    线段可以替换为“题面已有固定点-第二动点”线段。

    语义边界：

    - 它不创建辅助点，也不构造新轨迹；
    - 替换后的固定点必须来自题面已有点；
    - ``sqrt(2)*MN+AN`` 这类需要新辅助点或新射线的加权路径，应使用
      ``weighted_axis_path_triangle_transform``，不是本 method。
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

        first_moving_name = _canonical_reference_name(
            first_membership["point"]
        )
        second_moving_name = _canonical_reference_name(
            second_membership["point"]
        )
        first_segment = _canonical_segment_name(first_membership["segment"])
        second_segment = _canonical_segment_name(
            second_membership["segment"]
        )
        first_segment_names = list(first_segment)
        second_segment_names = list(second_segment)
        (left_scale, left_segment), (right_scale, right_segment) = (
            _binding_relation_terms(binding_relation, kernel)
        )
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
        replacement_geometry = _right_isosceles_replacement_geometry(
            kernel=kernel,
            first_segment_names=first_segment_names,
            second_segment_names=second_segment_names,
            fixed_name=fixed_name,
            joint_point=joint_point,
            second_fixed_name=second_fixed_name,
            first_moving_name=first_moving_name,
            second_moving_name=second_moving_name,
            first_segment_start=first_segment_start,
            second_segment_end=second_segment_end,
            first_moving_point=first_moving_point,
            second_moving_point=second_moving_point,
            left_scale=left_scale,
            right_scale=right_scale,
        )
        transformation = {
            "type": "existing_fixed_endpoint_replacement",
            "original_path": path_text,
            "transformed_path": transformed_path,
            "segment_equality": f"{replaced_segment}={replacement_segment}",
            "replaced_segment": replaced_segment,
            "replacement_segment": replacement_segment,
            "replacement_fixed_endpoint": fixed_name,
            "replacement_moving_point": second_moving_name,
            "moving_locus_segment_name": second_segment,
            "creates_auxiliary_point": False,
            "reason": str(binding_relation.get("description", "")),
            **_structured_transformation_metadata(
                original_path=original_path,
                first_membership=first_membership,
                second_membership=second_membership,
                binding_relation=binding_relation,
            ),
            **(
                {"replacement_geometry": replacement_geometry}
                if replacement_geometry is not None
                else {}
            ),
        }
        checks = [
            _check(
                "moving_points_binding_relation",
                sp.simplify(
                    left_scale**2 * left_distance_squared
                    - right_scale**2 * right_distance_squared
                )
                == 0,
                "两个动点的绑定线段关系成立",
            ),
            _check(
                "moving_segment_equal_fixed_segment",
                sp.simplify(
                    moving_distance_squared - replacement_distance_squared
                )
                == 0,
                f"{replaced_segment} 与 {replacement_segment} 等长",
            ),
        ]
        if replacement_geometry is not None:
            checks.extend(
                (
                    _check(
                        "right_isosceles_replacement_frame",
                        True,
                        "端点替换对应一个等腰直角三角形框架",
                    ),
                    _check(
                        "projection_rectangle_verified",
                        True,
                        "两个垂足构成矩形并给出对应边等长",
                    ),
                    _check(
                        "perpendicular_bisector_replacement_verified",
                        True,
                        f"垂直平分线证明 {replaced_segment}＝{replacement_segment}",
                    ),
                )
            )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "path_transformation": TypedValue(
                    "PathTransformation",
                    transformation,
                    source=self.method_id,
                )
            },
            checks=checks,
            trace_fragments=[
                _step(
                    self.method_id,
                    "把两动点路径转化为单动点路径",
                    f"将 {path_text} 转化为 {transformed_path}",
                    "利用两个动点的线段绑定关系，把原路径中的两动点线段替换成等长的题面已有固定点到动点线段。",
                    f"{binding_relation.get('description', '')}，可得 {replaced_segment}={replacement_segment}",
                    f"{path_text}={transformed_path}",
                )
            ],
        )


def _right_isosceles_replacement_geometry(
    *,
    kernel: SympyKernel,
    first_segment_names: list[str],
    second_segment_names: list[str],
    fixed_name: str,
    joint_point: Point,
    second_fixed_name: str,
    first_moving_name: str,
    second_moving_name: str,
    first_segment_start: Point,
    second_segment_end: Point,
    first_moving_point: Point,
    second_moving_point: Point,
    left_scale: sp.Expr,
    right_scale: sp.Expr,
) -> dict[str, Any] | None:
    """Recognize and certify the reusable perpendicular-bisector proof.

    The calculation path does not depend on this profile.  If a valid
    endpoint replacement has another geometry, the Method still returns its
    algebraically verified result and teaching can use the shorter equality.
    """

    shared = set(first_segment_names) & set(second_segment_names)
    if len(shared) != 1:
        return None
    joint_name = next(iter(shared))
    if fixed_name == joint_name or second_fixed_name == joint_name:
        return None
    first_leg = tuple(
        sp.simplify(b - a)
        for a, b in zip(first_segment_start, joint_point, strict=True)
    )
    second_leg = tuple(
        sp.simplify(b - a)
        for a, b in zip(first_segment_start, second_segment_end, strict=True)
    )
    first_norm = sp.simplify(sum(item**2 for item in first_leg))
    second_norm = sp.simplify(sum(item**2 for item in second_leg))
    if (
        sp.simplify(sum(a * b for a, b in zip(first_leg, second_leg, strict=True)))
        != 0
        or sp.simplify(first_norm - second_norm) != 0
        or not is_definitely_positive(first_norm)
    ):
        return None
    scale = sp.simplify(right_scale / left_scale)
    if sp.simplify(scale - sp.sqrt(2)) != 0:
        return None

    first_foot = _orthogonal_projection(
        second_moving_point,
        start=first_segment_start,
        direction=first_leg,
    )
    second_foot = _orthogonal_projection(
        second_moving_point,
        start=first_segment_start,
        direction=second_leg,
    )
    vector_equalities = (
        _same_vector(
            first_segment_start,
            first_foot,
            second_foot,
            second_moving_point,
        ),
        _same_vector(
            first_segment_start,
            second_foot,
            first_foot,
            second_moving_point,
        ),
        _same_vector(
            first_segment_start,
            first_foot,
            first_foot,
            first_moving_point,
        ),
    )
    right_subtriangle = (
        sp.simplify(
            kernel.distance_squared(second_moving_point, second_foot)
            - kernel.distance_squared(second_segment_end, second_foot)
        )
        == 0
    )
    first_projection_right = sp.simplify(
        sum(
            (a - b) * direction
            for a, b, direction in zip(
                second_moving_point,
                first_foot,
                first_leg,
                strict=True,
            )
        )
    ) == 0
    second_projection_right = sp.simplify(
        sum(
            (a - b) * direction
            for a, b, direction in zip(
                second_moving_point,
                second_foot,
                second_leg,
                strict=True,
            )
        )
    ) == 0
    replacement_equal = sp.simplify(
        kernel.distance_squared(first_moving_point, second_moving_point)
        - kernel.distance_squared(first_segment_start, second_moving_point)
    ) == 0
    if not all(
        (
            *vector_equalities,
            right_subtriangle,
            first_projection_right,
            second_projection_right,
            replacement_equal,
        )
    ):
        return None
    return {
        "kind": "right_isosceles_perpendicular_bisector",
        "roles": {
            "right_vertex": fixed_name,
            "first_leg_vertex": joint_name,
            "second_leg_vertex": second_fixed_name,
            "first_leg_moving_point": first_moving_name,
            "hypotenuse_moving_point": second_moving_name,
        },
        "first_leg": (fixed_name, joint_name),
        "second_leg": (fixed_name, second_fixed_name),
        "hypotenuse": (joint_name, second_fixed_name),
        "binding": {
            "left_segment": (fixed_name, first_moving_name),
            "right_segment": (second_fixed_name, second_moving_name),
            "scale": kernel.sstr(scale),
        },
        "replacement": {
            "left_segment": (first_moving_name, second_moving_name),
            "right_segment": (fixed_name, second_moving_name),
        },
        "verified_relations": (
            "right_isosceles_frame",
            "hypotenuse_projection_isosceles",
            "projection_rectangle",
            "first_projection_is_binding_midpoint",
            "perpendicular_bisector",
            "endpoint_distances_equal",
        ),
    }


def _orthogonal_projection(
    point: Point,
    *,
    start: Point,
    direction: tuple[sp.Expr, sp.Expr],
) -> Point:
    denominator = sp.simplify(sum(item**2 for item in direction))
    factor = sp.simplify(
        sum(
            (coordinate - origin) * component
            for coordinate, origin, component in zip(
                point,
                start,
                direction,
                strict=True,
            )
        )
        / denominator
    )
    return tuple(
        sp.simplify(origin + factor * component)
        for origin, component in zip(start, direction, strict=True)
    )  # type: ignore[return-value]


def _same_vector(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> bool:
    return all(
        sp.simplify(
            (first_end[index] - first_start[index])
            - (second_end[index] - second_start[index])
        )
        == 0
        for index in range(2)
    )


def _binding_relation_terms(
    relation: Mapping[str, Any],
    kernel: SympyKernel,
) -> tuple[tuple[sp.Expr, str], tuple[sp.Expr, str]]:
    """Read both canonical structured and legacy text relation payloads."""

    left_segment = relation.get("left_segment")
    right_segment = relation.get("right_segment")
    if left_segment is not None and right_segment is not None:
        return (
            (sp.Integer(1), _canonical_segment_name(left_segment)),
            (
                sp.simplify(
                    _require_canonical_runtime_expression(
                        relation.get("scale", "1"),
                        kernel,
                        arg_name="binding_relation",
                        role="segment_scale",
                    )
                ),
                _canonical_segment_name(right_segment),
            ),
        )
    structured = tuple(
        _structured_relation_term(relation.get(key), kernel)
        for key in ("left_term", "right_term")
    )
    left_segment, right_segment = structured
    if left_segment is not None and right_segment is not None:
        return left_segment, right_segment
    return (
        _parse_scaled_segment(str(relation["left"]), kernel),
        _parse_scaled_segment(str(relation["right"]), kernel),
    )


def _structured_relation_term(
    value: Any,
    kernel: SympyKernel,
) -> tuple[sp.Expr, str] | None:
    if not isinstance(value, Mapping) or value.get("segment") is None:
        return None
    return (
        sp.simplify(
            _require_canonical_runtime_expression(
                value.get("scale", "1"),
                kernel,
                arg_name="binding_relation",
                role="segment_scale",
            )
        ),
        _canonical_segment_name(value["segment"]),
    )


def _structured_transformation_metadata(
    *,
    original_path: Mapping[str, Any],
    first_membership: Mapping[str, Any],
    second_membership: Mapping[str, Any],
    binding_relation: Mapping[str, Any],
) -> dict[str, Any]:
    original_terms = _canonical_path_terms(original_path.get("terms"))
    first_moving = _canonical_point_ref(first_membership.get("point_ref"))
    second_moving = _canonical_point_ref(second_membership.get("point_ref"))
    relation_terms = tuple(
        item
        for item in (
            _canonical_scaled_term(binding_relation.get("left_term")),
            _canonical_scaled_term(binding_relation.get("right_term")),
        )
        if item is not None
    )
    if (
        len(original_terms) != 2
        or first_moving is None
        or second_moving is None
        or len(relation_terms) != 2
    ):
        return {}
    first_relation = next(
        (
            item
            for item in relation_terms
            if first_moving in item["segment"]
        ),
        None,
    )
    if first_relation is None:
        return {}
    first_fixed = next(
        endpoint
        for endpoint in first_relation["segment"]
        if endpoint != first_moving
    )
    replaced_index = next(
        (
            index
            for index, segment in enumerate(original_terms)
            if set(segment) == {first_moving, second_moving}
        ),
        None,
    )
    if replaced_index is None:
        return {}
    transformed_terms = list(original_terms)
    transformed_terms[replaced_index] = (first_fixed, second_moving)
    fixed_endpoints = tuple(
        segment[0] if segment[1] == second_moving else segment[1]
        for segment in transformed_terms
        if second_moving in segment
    )
    if len(fixed_endpoints) != 2:
        return {}
    source_conditions = tuple(
        item
        for item in (
            original_path.get("condition_ref"),
            first_membership.get("condition_ref"),
            second_membership.get("condition_ref"),
            binding_relation.get("condition_ref"),
        )
        if isinstance(item, str) and item.startswith("fact:")
    )
    moving_locus_endpoints = _canonical_path_terms(
        [second_membership.get("segment_endpoint_refs")]
    )
    return {
        "original_terms": [list(item) for item in original_terms],
        "transformed_terms": [list(item) for item in transformed_terms],
        "moving_point_ref": second_moving,
        "fixed_endpoint_refs": list(fixed_endpoints),
        "moving_locus_condition_ref": second_membership.get("condition_ref"),
        "moving_locus_segment_ref": second_membership.get("segment_ref"),
        "moving_locus_endpoint_refs": (
            list(moving_locus_endpoints[0])
            if moving_locus_endpoints
            else []
        ),
        "equality_witnesses": [
            {
                "left_segment": [first_moving, second_moving],
                "right_segment": [first_fixed, second_moving],
                "source_condition_refs": list(source_conditions),
            }
        ],
        "source_condition_refs": list(source_conditions),
    }


def _canonical_scaled_term(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    segment = _canonical_path_terms([value.get("segment")])
    if not segment:
        return None
    return {
        "scale": str(value.get("scale", "1")),
        "segment": segment[0],
    }


def _canonical_path_terms(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        return ()
    result: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 2
            or not all(_canonical_point_ref(child) for child in item)
        ):
            return ()
        result.append((str(item[0]), str(item[1])))
    return tuple(result)


def _canonical_point_ref(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("point:") else None


__all__ = ["TwoMovingPointsPathReductionMethod"]
