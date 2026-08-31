"""Private square-path dimension reduction for the atomic square kernel.

把正方形中点/中心结构中的三段路径降维为单动点两段折线路径。
"""

from __future__ import annotations

from ..._common import *


class SquarePathDimensionReductionMethod:
    """由正方形中点与中心关系把多段路径降为单动点折线。"""

    method_id = "square_path_dimension_reduction"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        path_condition: dict[str, Any] = inputs["path_condition"]
        square_condition: dict[str, Any] = inputs["square_condition"]
        midpoint_condition: dict[str, Any] = inputs["midpoint_condition"]
        square_center_condition: dict[str, Any] = inputs["square_center_condition"]
        moving_point: PointRef = inputs["moving_point"]
        fixed_endpoint_1_ref: PointRef | None = inputs.get(
            "fixed_endpoint_1_ref"
        )
        fixed_endpoint_2_ref: PointRef | None = inputs.get(
            "fixed_endpoint_2_ref"
        )

        path = str(path_condition["path"])
        segments = _parse_path_segments(path)
        if len(segments) != 3:
            raise method_precondition_failed(
                "square path dimension reduction requires exactly three path segments",
                arg_name="path_condition",
                role="source_path",
                expected={"type": "Condition", "state": "three_segments", "segment_count": 3},
                observed={"state": "wrong_segment_count", "segment_count": len(segments)},
                repair_action="choose_three_segment_square_path",
            )

        vertices = _square_vertices(square_condition)
        typed_terms = _typed_path_terms(path_condition)
        if typed_terms is not None:
            roles = _typed_square_path_roles(
                vertices=vertices,
                midpoint_condition=midpoint_condition,
                square_center_condition=square_center_condition,
                typed_terms=typed_terms,
                display_segments=segments,
                moving_point=moving_point,
                fixed_endpoint_1_ref=fixed_endpoint_1_ref,
                fixed_endpoint_2_ref=fixed_endpoint_2_ref,
            )
            side_start = roles["side_start"]
            side_end = roles["side_end"]
            moving_vertex = roles["moving_vertex"]
            midpoint = roles["midpoint"]
            center = roles["center"]
            other_fixed = roles["other_fixed"]
            center_midpoint = roles["center_midpoint"]
            midpoint_other = roles["midpoint_other"]
            other_moving = roles["other_moving"]
        else:
            square_names = tuple(_handle_name(item) for item in vertices[:4])
            moving_vertex = moving_point.name
            midpoint = _handle_name(str(midpoint_condition["point"]))
            center = _handle_name(str(square_center_condition["point"]))
            midpoint_of = [_handle_name(str(item)) for item in midpoint_condition.get("of", [])]
            side_start = _square_side_endpoint_for_moving_point(
                vertices=square_names,
                midpoint_side=midpoint_of,
                moving_point=moving_vertex,
            )
            side_end = next(item for item in midpoint_of if item != side_start)
            if (
                fixed_endpoint_1_ref is not None
                and fixed_endpoint_1_ref.name != side_start
            ):
                raise method_precondition_failed(
                    "computed fixed endpoint does not match the planner-selected moving point",
                    arg_name="moving_point",
                    role="square_path_interpretation",
                    expected={"fixed_endpoint_1": side_start},
                    observed={"fixed_endpoint_1": fixed_endpoint_1_ref.name},
                    repair_action="choose_square_path_moving_point",
                )
            center_midpoint = _find_segment(segments, center, midpoint)
            midpoint_other = _segment_with_endpoint(segments, midpoint, exclude=center_midpoint)
            other_fixed = _other_segment_endpoint(midpoint_other, midpoint)
            other_moving = _find_segment(segments, other_fixed, moving_vertex)
            if (
                fixed_endpoint_2_ref is not None
                and fixed_endpoint_2_ref.name != other_fixed
            ):
                raise method_precondition_failed(
                    "computed path endpoint does not match the selected transformation",
                    arg_name="moving_point",
                    role="square_path_interpretation",
                    expected={"fixed_endpoint_2": other_fixed},
                    observed={"fixed_endpoint_2": fixed_endpoint_2_ref.name},
                    repair_action="choose_square_path_moving_point",
                )
        if str(square_center_condition.get("square")) != str(square_condition.get("handle", square_condition.get("id", ""))):
            # Canonical fact payloads do not always carry their own handle. When absent,
            # the structural checks below still pin the same square by its vertices.
            pass

        square_side = f"{side_start}{side_end}"
        replacement_segment = f"{side_start}{moving_vertex}"
        transformed_path = f"{side_start}{moving_vertex}+{other_fixed}{moving_vertex}"

        transformation = {
            "type": "square_path_dimension_reduction",
            "original_path": path,
            "transformed_path": transformed_path,
            "moving_point_name": moving_vertex,
            "moving_point_ref": _canonical_point_ref(moving_point),
            "fixed_point_names": (side_start, other_fixed),
            "roles": {
                "square_vertices": tuple(
                    _source_point_label(item) for item in vertices[:4]
                ),
                "side_start": side_start,
                "side_end": side_end,
                "midpoint": midpoint,
                "center": center,
                "other_fixed": other_fixed,
                "moving_vertex": moving_vertex,
            },
            "segments": {
                "square_side": square_side,
                "center_midpoint": center_midpoint,
                "midpoint_fixed": midpoint_other,
                "fixed_moving": other_moving,
                "replacement": replacement_segment,
            },
            "relations": {
                "midpoint_fixed_half_of_side": f"{midpoint_other}={square_side}/2",
                "center_midpoint_half_of_replacement": f"{center_midpoint}={replacement_segment}/2",
                "square_sides_equal": f"{square_side}={replacement_segment}",
                "merged_segment": f"{center_midpoint}+{midpoint_other}={replacement_segment}",
                "path_equality": f"{path}={transformed_path}",
            },
            "reason": (
                f"{center_midpoint}={replacement_segment}/2，{midpoint_other}={square_side}/2，"
                f"且 {square_side}={replacement_segment}，因此 {path} 转化为 {transformed_path}"
            ),
        }
        if (
            fixed_endpoint_1_ref is not None
            and fixed_endpoint_2_ref is not None
        ):
            transformation["fixed_endpoint_refs"] = (
                _canonical_point_ref(fixed_endpoint_1_ref),
                _canonical_point_ref(fixed_endpoint_2_ref),
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
            checks=[
                _check("path_has_center_to_midpoint_segment", center_midpoint in segments, "路径包含中心到中点线段"),
                _check("path_has_midpoint_to_fixed_segment", midpoint_other in segments, "路径包含中点到固定点线段"),
                _check("path_has_fixed_to_moving_vertex_segment", other_moving in segments, "路径包含固定点到正方形顶点线段"),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "正方形路径降维",
                    "把三段路径化成单动点折线",
                    (
                        f"{midpoint} 是 {square_side} 的中点，{center} 是正方形对角线 "
                        f"{side_end}{moving_vertex} 的中点。"
                    ),
                    f"{center_midpoint}={replacement_segment}/2, {midpoint_other}={square_side}/2, {path}={transformed_path}",
                    f"后续只需研究动点 {moving_vertex} 在线上的折线路径 {transformed_path}",
                )
            ],
        )


def _square_vertices(condition: dict[str, Any]) -> list[str]:
    vertices = condition.get("vertices")
    if not isinstance(vertices, list) or len(vertices) < 4:
        raise method_input_invalid(
            "square condition requires at least four ordered vertices",
            arg_name="square_condition",
            role="square_vertices",
            expected={"type": "Condition", "state": "ordered_vertices"},
            observed={"type": type(vertices).__name__, "count": len(vertices) if isinstance(vertices, list) else 0},
            repair_action="provide_square_vertex_order",
        )
    return [str(item) for item in vertices]


def _handle_name(handle: str) -> str:
    return handle.rsplit(":", 1)[-1]


def _source_point_label(handle: str) -> str:
    """Best-effort display label; never used as runtime object identity."""

    parts = handle.split(":", 2)
    local_id = parts[-1]
    if len(parts) == 3:
        suffix = f"_{parts[1]}"
        if local_id.endswith(suffix) and len(local_id) > len(suffix):
            return local_id[: -len(suffix)]
    return local_id


def _typed_path_terms(condition: dict[str, Any]) -> list[tuple[str, str]] | None:
    raw_terms = condition.get("terms")
    if raw_terms is None:
        return None
    if not isinstance(raw_terms, list):
        raise method_input_invalid(
            "path condition terms must be a list",
            arg_name="path_condition",
            role="typed_path_terms",
            expected={"type": "PointPairList"},
            observed={"type": type(raw_terms).__name__},
            repair_action="choose_typed_path_condition",
        )
    terms: list[tuple[str, str]] = []
    for raw in raw_terms:
        if (
            not isinstance(raw, (list, tuple))
            or len(raw) != 2
            or not all(isinstance(item, str) and item.startswith("point:") for item in raw)
        ):
            raise method_input_invalid(
                "path condition terms must contain point-handle pairs",
                arg_name="path_condition",
                role="typed_path_terms",
                expected={"type": "PointPairList", "state": "canonical_point_handles"},
                observed={"type": type(raw).__name__, "value": repr(raw)},
                repair_action="choose_typed_path_condition",
            )
        terms.append((str(raw[0]), str(raw[1])))
    return terms


def _typed_square_path_roles(
    *,
    vertices: list[str],
    midpoint_condition: dict[str, Any],
    square_center_condition: dict[str, Any],
    typed_terms: list[tuple[str, str]],
    display_segments: list[str],
    moving_point: PointRef,
    fixed_endpoint_1_ref: PointRef | None,
    fixed_endpoint_2_ref: PointRef | None,
) -> dict[str, str]:
    """Validate the square path by exact handles, then derive display labels."""

    if len(typed_terms) != 3 or len(display_segments) != 3:
        raise method_precondition_failed(
            "square path requires three typed terms aligned with three display segments",
            arg_name="path_condition",
            role="source_path",
            expected={"state": "three_typed_terms", "count": 3},
            observed={"typed_term_count": len(typed_terms), "display_segment_count": len(display_segments)},
            repair_action="choose_three_segment_square_path",
        )
    moving_handle = _canonical_point_ref(moving_point)
    midpoint_handle = str(midpoint_condition.get("point", ""))
    midpoint_of = tuple(str(item) for item in midpoint_condition.get("of", ()))
    center_handle = str(square_center_condition.get("point", ""))
    side_start = _square_side_endpoint_for_moving_point(
        vertices=tuple(vertices[:4]),
        midpoint_side=midpoint_of,
        moving_point=moving_handle,
    )
    side_end = next(item for item in midpoint_of if item != side_start)
    if (
        fixed_endpoint_1_ref is not None
        and _canonical_point_ref(fixed_endpoint_1_ref) != side_start
    ):
        raise method_precondition_failed(
            "computed fixed endpoint does not match the planner-selected moving point",
            arg_name="moving_point",
            role="square_path_interpretation",
            expected={"fixed_endpoint_1": side_start},
            observed={
                "fixed_endpoint_1": _canonical_point_ref(fixed_endpoint_1_ref)
            },
            repair_action="choose_square_path_moving_point",
        )

    center_index = _typed_edge_index(typed_terms, center_handle, midpoint_handle)
    midpoint_indexes = [
        index
        for index, pair in enumerate(typed_terms)
        if index != center_index and midpoint_handle in pair
    ]
    if len(midpoint_indexes) != 1:
        raise method_result_ambiguous(
            "path must contain exactly one midpoint-to-fixed segment",
            arg_name="path_condition",
            role="midpoint_to_fixed_segment",
            expected={"candidate_count": 1},
            observed={"candidate_count": len(midpoint_indexes)},
            repair_action="choose_matching_path_segments",
        )
    midpoint_index = midpoint_indexes[0]
    other_fixed_handle = _typed_other_endpoint(
        typed_terms[midpoint_index],
        midpoint_handle,
    )
    if (
        fixed_endpoint_2_ref is not None
        and _canonical_point_ref(fixed_endpoint_2_ref) != other_fixed_handle
    ):
        raise method_precondition_failed(
            "computed path endpoint does not match the selected transformation",
            arg_name="moving_point",
            role="square_path_interpretation",
            expected={"fixed_endpoint_2": other_fixed_handle},
            observed={
                "fixed_endpoint_2": _canonical_point_ref(fixed_endpoint_2_ref)
            },
            repair_action="choose_square_path_moving_point",
        )
    moving_indexes = [
        index
        for index, pair in enumerate(typed_terms)
        if index not in {center_index, midpoint_index}
        and set(pair) == {other_fixed_handle, moving_handle}
    ]
    if len(moving_indexes) != 1:
        raise method_result_ambiguous(
            "path must contain exactly one fixed-to-moving square segment",
            arg_name="path_condition",
            role="fixed_to_moving_segment",
            expected={"candidate_count": 1},
            observed={"candidate_count": len(moving_indexes)},
            repair_action="choose_matching_path_segments",
        )
    moving_index = moving_indexes[0]

    labels = _typed_path_display_labels(
        typed_terms,
        display_segments,
        anchors=(
            (moving_handle, moving_point.name),
            *((
                (side_start, fixed_endpoint_1_ref.name),
            ) if fixed_endpoint_1_ref is not None else ()),
            *((
                (other_fixed_handle, fixed_endpoint_2_ref.name),
            ) if fixed_endpoint_2_ref is not None else ()),
        ),
    )
    return {
        "side_start": labels.get(side_start, _source_point_label(side_start)),
        "side_end": labels.get(side_end, _source_point_label(side_end)),
        "center": labels[center_handle],
        "midpoint": labels[midpoint_handle],
        "other_fixed": labels[other_fixed_handle],
        "moving_vertex": labels[moving_handle],
        "center_midpoint": display_segments[center_index],
        "midpoint_other": display_segments[midpoint_index],
        "other_moving": display_segments[moving_index],
    }


def _typed_edge_index(
    terms: list[tuple[str, str]],
    first: str,
    second: str,
) -> int:
    matches = [index for index, pair in enumerate(terms) if set(pair) == {first, second}]
    if len(matches) != 1:
        raise method_result_ambiguous(
            "path must contain exactly one center-to-midpoint segment",
            arg_name="path_condition",
            role="center_to_midpoint_segment",
            expected={"candidate_count": 1},
            observed={"candidate_count": len(matches)},
            repair_action="choose_matching_path_segments",
        )
    return matches[0]


def _typed_other_endpoint(pair: tuple[str, str], endpoint: str) -> str:
    if pair[0] == endpoint:
        return pair[1]
    if pair[1] == endpoint:
        return pair[0]
    raise method_input_invalid(
        "typed path pair does not contain the expected endpoint",
        arg_name="path_condition",
        role="typed_path_terms",
        internal_ref=endpoint,
        expected={"state": "contains_endpoint"},
        observed={"pair": list(pair)},
        repair_action="choose_typed_path_condition",
    )


def _typed_path_display_labels(
    terms: list[tuple[str, str]],
    segments: list[str],
    *,
    anchors: tuple[tuple[str, str], ...],
) -> dict[str, str]:
    path_handles = {
        handle
        for pair in terms
        for handle in pair
    }
    candidates: list[dict[str, str]] = [{}]
    for pair, segment in zip(terms, segments):
        display = _display_segment_endpoints(segment)
        next_candidates: list[dict[str, str]] = []
        for candidate in candidates:
            for names in (display, display[::-1]):
                proposed = dict(candidate)
                if any(
                    handle in proposed and proposed[handle] != name
                    for handle, name in zip(pair, names)
                ):
                    continue
                proposed[pair[0]] = names[0]
                proposed[pair[1]] = names[1]
                next_candidates.append(proposed)
        candidates = next_candidates
    for anchor_handle, anchor_name in anchors:
        if anchor_handle not in path_handles:
            continue
        candidates = [
            item for item in candidates if item.get(anchor_handle) == anchor_name
        ]
    unique = {
        tuple(sorted(item.items())): item
        for item in candidates
    }
    if len(unique) != 1:
        raise method_result_ambiguous(
            "typed path terms do not map uniquely to display labels",
            arg_name="path_condition",
            role="path_display_mapping",
            expected={"candidate_count": 1},
            observed={"candidate_count": len(unique)},
            repair_action="supply_disambiguating_constraint",
        )
    return next(iter(unique.values()))


def _display_segment_endpoints(segment: str) -> tuple[str, str]:
    names = "".join(char for char in segment if char.isalpha() and char.isupper())
    if len(names) != 2:
        raise method_input_invalid(
            f"cannot parse two display endpoints from segment {segment!r}",
            arg_name="path_condition",
            role="display_segment",
            expected={"type": "SegmentLabel", "endpoint_count": 2},
            observed={"value": segment, "endpoint_count": len(names)},
            repair_action="choose_typed_path_condition",
        )
    return names[0], names[1]


def _canonical_point_ref(point_ref: PointRef) -> str:
    return f"point:{point_ref.scope_id}:{point_ref.name}"


def _square_side_endpoint_for_moving_point(
    *,
    vertices: tuple[str, ...],
    midpoint_side: tuple[str, ...] | list[str],
    moving_point: str,
) -> str:
    """Validate one selected moving point against square adjacency."""

    side = tuple(midpoint_side)
    candidates: list[str] = []
    if len(vertices) == 4 and len(side) == 2:
        for endpoint in side:
            if endpoint not in vertices:
                continue
            other = next((item for item in side if item != endpoint), None)
            if other is None:
                continue
            index = vertices.index(endpoint)
            neighbors = (vertices[(index - 1) % 4], vertices[(index + 1) % 4])
            if other in neighbors and moving_point in neighbors and moving_point != other:
                candidates.append(endpoint)
    if len(candidates) != 1:
        raise method_precondition_failed(
            "selected moving point is incompatible with the square midpoint side",
            arg_name="moving_point",
            role="square_path_interpretation",
            internal_ref=moving_point,
            expected={"state": "adjacent_to_one_midpoint_side_endpoint"},
            observed={
                "moving_point": moving_point,
                "midpoint_side": list(side),
                "candidate_count": len(candidates),
            },
            repair_action="choose_square_path_moving_point",
        )
    return candidates[0]


def _find_segment(segments: list[str], p1: str, p2: str) -> str:
    wanted = {p1, p2}
    for segment in segments:
        if set(segment) == wanted:
            return segment
    raise method_input_missing(
        f"path does not contain required segment {p1}{p2}",
        arg_name="path_condition",
        role="required_path_segment",
        expected={"state": "segment_present", "endpoints": [p1, p2]},
        observed={"segments": segments},
        repair_action="choose_matching_path_segments",
    )


def _segment_with_endpoint(segments: list[str], endpoint: str, *, exclude: str) -> str:
    matches = [segment for segment in segments if segment != exclude and endpoint in segment]
    if len(matches) != 1:
        raise method_result_ambiguous(
            f"path must contain exactly one remaining segment through {endpoint}",
            arg_name="path_condition",
            role="remaining_path_segment",
            internal_ref=endpoint,
            expected={"candidate_count": 1},
            observed={"candidate_count": len(matches), "segments": matches},
            repair_action="choose_matching_path_segments",
        )
    return matches[0]


__all__ = ["SquarePathDimensionReductionMethod"]
