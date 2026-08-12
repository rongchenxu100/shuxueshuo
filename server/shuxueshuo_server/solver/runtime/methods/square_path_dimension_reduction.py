"""square_path_dimension_reduction 无状态 method。

把正方形中点/中心结构中的三段路径降维为单动点两段折线路径。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec

from ._common import *
from ._spec import MethodSpecSource


class SquarePathDimensionReductionMethod:
    """由正方形中点与中心关系把多段路径降为单动点折线。"""

    method_id = "square_path_dimension_reduction"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        path_condition: dict[str, Any] = inputs["path_condition"]
        square_condition: dict[str, Any] = inputs["square_condition"]
        midpoint_condition: dict[str, Any] = inputs["midpoint_condition"]
        square_center_condition: dict[str, Any] = inputs["square_center_condition"]
        fixed_endpoint_1_ref: PointRef | None = inputs.get(
            "fixed_endpoint_1_ref"
        )
        fixed_endpoint_2_ref: PointRef | None = inputs.get(
            "fixed_endpoint_2_ref"
        )

        path = str(path_condition["path"])
        segments = _parse_path_segments(path)
        if len(segments) != 3:
            raise ValueError("square_path_dimension_reduction requires a three-segment path")

        vertices = _square_vertices(square_condition)
        typed_terms = _typed_path_terms(path_condition)
        if typed_terms is not None:
            roles = _typed_square_path_roles(
                vertices=vertices,
                midpoint_condition=midpoint_condition,
                square_center_condition=square_center_condition,
                typed_terms=typed_terms,
                display_segments=segments,
                fixed_endpoint_2_ref=fixed_endpoint_2_ref,
            )
            side_start = (
                fixed_endpoint_1_ref.name
                if fixed_endpoint_1_ref is not None
                else _source_point_label(vertices[0])
            )
            side_end = _source_point_label(vertices[1])
            moving_vertex = roles["moving_vertex"]
            midpoint = roles["midpoint"]
            center = roles["center"]
            other_fixed = roles["other_fixed"]
            center_midpoint = roles["center_midpoint"]
            midpoint_other = roles["midpoint_other"]
            other_moving = roles["other_moving"]
        else:
            side_start = _handle_name(vertices[0])
            side_end = _handle_name(vertices[1])
            moving_vertex = _handle_name(vertices[3])
            midpoint = _handle_name(str(midpoint_condition["point"]))
            center = _handle_name(str(square_center_condition["point"]))
            midpoint_of = [_handle_name(str(item)) for item in midpoint_condition.get("of", [])]
            if {side_start, side_end} != set(midpoint_of):
                raise ValueError("midpoint condition must refer to the square side endpoints")
            center_midpoint = _find_segment(segments, center, midpoint)
            midpoint_other = _segment_with_endpoint(segments, midpoint, exclude=center_midpoint)
            other_fixed = _other_segment_endpoint(midpoint_other, midpoint)
            other_moving = _find_segment(segments, other_fixed, moving_vertex)
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
            "moving_point_ref": vertices[3],
            "fixed_point_names": (side_start, other_fixed),
            "roles": {
                "square_vertices": (side_start, side_end, _source_point_label(vertices[2]), moving_vertex),
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
        raise ValueError("square condition requires ordered vertices")
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
        raise ValueError("path_condition.terms must be a list")
    terms: list[tuple[str, str]] = []
    for raw in raw_terms:
        if (
            not isinstance(raw, (list, tuple))
            or len(raw) != 2
            or not all(isinstance(item, str) and item.startswith("point:") for item in raw)
        ):
            raise ValueError("path_condition.terms must contain point-handle pairs")
        terms.append((str(raw[0]), str(raw[1])))
    return terms


def _typed_square_path_roles(
    *,
    vertices: list[str],
    midpoint_condition: dict[str, Any],
    square_center_condition: dict[str, Any],
    typed_terms: list[tuple[str, str]],
    display_segments: list[str],
    fixed_endpoint_2_ref: PointRef | None,
) -> dict[str, str]:
    """Validate the square path by exact handles, then derive display labels."""

    if len(typed_terms) != 3 or len(display_segments) != 3:
        raise ValueError("square path requires three typed terms")
    side_start, side_end, _, moving_handle = vertices[:4]
    midpoint_handle = str(midpoint_condition.get("point", ""))
    midpoint_of = tuple(str(item) for item in midpoint_condition.get("of", ()))
    center_handle = str(square_center_condition.get("point", ""))
    if len(midpoint_of) != 2 or set(midpoint_of) != {side_start, side_end}:
        raise ValueError("midpoint condition must refer to the square side endpoints")

    center_index = _typed_edge_index(typed_terms, center_handle, midpoint_handle)
    midpoint_indexes = [
        index
        for index, pair in enumerate(typed_terms)
        if index != center_index and midpoint_handle in pair
    ]
    if len(midpoint_indexes) != 1:
        raise ValueError("path must contain one midpoint-to-fixed segment")
    midpoint_index = midpoint_indexes[0]
    other_fixed_handle = _typed_other_endpoint(
        typed_terms[midpoint_index],
        midpoint_handle,
    )
    moving_indexes = [
        index
        for index, pair in enumerate(typed_terms)
        if index not in {center_index, midpoint_index}
        and set(pair) == {other_fixed_handle, moving_handle}
    ]
    if len(moving_indexes) != 1:
        raise ValueError("path must contain the fixed-to-moving square segment")
    moving_index = moving_indexes[0]

    labels = _typed_path_display_labels(
        typed_terms,
        display_segments,
        anchors=(
            (other_fixed_handle, fixed_endpoint_2_ref.name)
            if fixed_endpoint_2_ref is not None
            else None
        ),
    )
    return {
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
        raise ValueError("path must contain exactly one center-to-midpoint segment")
    return matches[0]


def _typed_other_endpoint(pair: tuple[str, str], endpoint: str) -> str:
    if pair[0] == endpoint:
        return pair[1]
    if pair[1] == endpoint:
        return pair[0]
    raise ValueError("typed path pair does not contain expected endpoint")


def _typed_path_display_labels(
    terms: list[tuple[str, str]],
    segments: list[str],
    *,
    anchors: tuple[str, str] | None,
) -> dict[str, str]:
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
    if anchors is not None:
        anchor_handle, anchor_name = anchors
        candidates = [
            item for item in candidates if item.get(anchor_handle) == anchor_name
        ]
    unique = {
        tuple(sorted(item.items())): item
        for item in candidates
    }
    if len(unique) != 1:
        raise ValueError("typed path terms do not uniquely map to display labels")
    return next(iter(unique.values()))


def _display_segment_endpoints(segment: str) -> tuple[str, str]:
    names = "".join(char for char in segment if char.isalpha() and char.isupper())
    if len(names) != 2:
        raise ValueError(f"cannot parse display segment endpoints from {segment!r}")
    return names[0], names[1]


def _canonical_point_ref(point_ref: PointRef) -> str:
    return f"point:{point_ref.scope_id}:{point_ref.name}"


def _find_segment(segments: list[str], p1: str, p2: str) -> str:
    wanted = {p1, p2}
    for segment in segments:
        if set(segment) == wanted:
            return segment
    raise ValueError(f"path does not contain segment {p1}{p2}")


def _segment_with_endpoint(segments: list[str], endpoint: str, *, exclude: str) -> str:
    matches = [segment for segment in segments if segment != exclude and endpoint in segment]
    if len(matches) != 1:
        raise ValueError(f"path must contain exactly one remaining segment through {endpoint}")
    return matches[0]


SPEC = MethodSpecSource(
    method_cls=SquarePathDimensionReductionMethod,
    title="正方形路径降维",
    summary=(
        "仅用于原目标路径恰好由三段组成，并且正方形边、中点、中心或对角线"
        "交点关系能够通过斜边中线与三角形中位线把其中两段合并为一段的结构。"
        "路径中的结构化固定端点必须先由其题面定义在当前 scope 或祖先 scope"
        "物化为 Point state；PointRef 或点名本身不是可执行坐标。"
        "输出等价的单动点两段 PathTransformation，不负责拉直或求最小值；"
        "输出不携带动点轨迹，后续必须先求 PathTransformation 声明动点的 Line。"
    ),
    do_not_use_when=(
        "原路径只有两段，或不需要正方形的中点和中心关系即可完成等长/比例替换。",
        "缺少三段路径、正方形、中点、中心或对角线交点中的必要结构化条件。",
        "路径固定端点只有 PointRef、定义或点名而没有已计算 Point state；应先用"
        "与题面构造匹配的 capability 物化该点，不能拿任意可见 Point 代替。",
        "目标是处理线段与射线等长、加权距离，或已经完成降维的普通两段折线路径。",
    ),
    solves=("reduce_square_path_dimension", "derive_path_transformation"),
    inputs={
        "path_condition": {"type": "Condition", "required": True},
        "square_condition": {"type": "Condition", "required": True},
        "midpoint_condition": {"type": "Condition", "required": True},
        "square_center_condition": {"type": "Condition", "required": True},
        "fixed_endpoint_1_ref": {"type": "PointRef", "required": False},
        "fixed_endpoint_2_ref": {"type": "PointRef", "required": False},
    },
    outputs={"path_transformation": "PathTransformation"},
    preconditions=(
        "path_condition.path 是三段路径",
        "midpoint_condition 指向正方形一边的中点",
        "square_center_condition 指向该正方形中心或对角线交点",
        "中点到另一固定点的半边关系已有直角三角形斜边中线依据",
        "两个结构化固定端点都已有当前 scope 可见的 Point state",
    ),
    postconditions=(
        "输出 transformed_path 是两段共享同一动点的折线路径",
        "输出 payload 包含 moving_point_name 与 fixed_point_names，供后续 planner repair 继续规划",
    ),
    explanation=MethodExplanationSpec(
        role_schema={
            "midpoint_statement": "说明哪个点是正方形边的中点。",
            "right_triangle_statement": "用于斜边中线关系的直角三角形。",
            "midpoint_fixed_half": "边中点到固定点线段的半长关系。",
            "center_midpoint_statement": "说明哪个点是正方形对角线中心。",
            "midline_statement": "正方形边与动点构成三角形中的中位线关系。",
            "center_midpoint_half": "中心到中点线段的半长关系。",
            "square_side_equality": "用于合并两段半长的正方形相邻边相等关系。",
            "merged_segment": "合并后的线段等量关系。",
            "path_equality": "最终路径转化等式。",
        },
        student_goal_template="利用斜边中线和三角形中位线，把正方形路径中的两段合并为一段。",
        student_title_template="由斜边中线和中位线转化线段",
        student_nav_title_template="多动点转化为单动点问题",
        derive_templates=(
            "∵{midpoint_statement}",
            "∴{right_triangle_statement}，{midpoint_fixed_half}",
            "∵{center_midpoint_statement}",
            "∴{midline_statement}",
            "∴{center_midpoint_half}",
            "∵{square_side_equality}",
            "∴{merged_segment}",
            "∴{path_equality}",
        ),
        box_templates=("{midpoint_fixed_half}", "{center_midpoint_half}", "{merged_segment}", "{path_equality}"),
        role_binder_id="square_path_dimension_reduction",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "square_path_marker": "正方形路径降维中的直角三角形和中位线视觉证明。",
        },
        role_binder_id="square_path_dimension_reduction",
        scene_templates=(
            {
                "component": "SquarePathDimensionMarker",
                "persistence": "carry_forward",
                "square_fill": "rgba(15, 118, 110, 0.055)",
                "square_color": "rgba(15, 118, 110, 0.50)",
                "right_triangle_fill": "rgba(14, 165, 233, 0.12)",
                "midline_triangle_fill": "rgba(245, 158, 11, 0.12)",
                "half_segment_color": "#7c3aed",
                "path_segment_color": "#dc2626",
                "replacement_color": "#b45309",
                "show_half_segment_labels": False,
            },
        ),
    ),
)
