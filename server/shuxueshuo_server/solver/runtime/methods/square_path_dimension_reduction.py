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

        path = str(path_condition["path"])
        segments = _parse_path_segments(path)
        if len(segments) != 3:
            raise ValueError("square_path_dimension_reduction requires a three-segment path")

        vertices = _square_vertices(square_condition)
        side_start = _handle_name(vertices[0])
        side_end = _handle_name(vertices[1])
        moving_vertex = _handle_name(vertices[3])
        midpoint = _handle_name(str(midpoint_condition["point"]))
        center = _handle_name(str(square_center_condition["point"]))
        midpoint_of = [_handle_name(str(item)) for item in midpoint_condition.get("of", [])]
        if {side_start, side_end} != set(midpoint_of):
            raise ValueError("midpoint condition must refer to the square side endpoints")
        if str(square_center_condition.get("square")) != str(square_condition.get("handle", square_condition.get("id", ""))):
            # Canonical fact payloads do not always carry their own handle. When absent,
            # the structural checks below still pin the same square by its vertices.
            pass

        center_midpoint = _find_segment(segments, center, midpoint)
        midpoint_other = _segment_with_endpoint(segments, midpoint, exclude=center_midpoint)
        other_fixed = _other_segment_endpoint(midpoint_other, midpoint)
        other_moving = _find_segment(segments, other_fixed, moving_vertex)
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
                "square_vertices": (side_start, side_end, _handle_name(vertices[2]), moving_vertex),
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
        "Given 正方形边、中点、中心和三段路径条件, derive 等价的单动点两段折线路径。"
        "该 method 只做正方形结构下的路径降维，不负责拉直求最值；输出的 "
        "PathTransformation 会揭示后续真实 moving_point 与 fixed_points，"
        "planner 不应在执行前猜测降维后的动点。当前实现仅适用于三段路径中"
        "前两段可由正方形中心、中点和斜边中线关系合并为一条正方形边的结构；"
        "其它正方形路径转换应使用独立能力或扩展后的声明式变换规则。"
    ),
    solves=("reduce_square_path_dimension", "derive_path_transformation"),
    inputs={
        "path_condition": {"type": "Condition", "required": True},
        "square_condition": {"type": "Condition", "required": True},
        "midpoint_condition": {"type": "Condition", "required": True},
        "square_center_condition": {"type": "Condition", "required": True},
    },
    outputs={"path_transformation": "PathTransformation"},
    preconditions=(
        "path_condition.path 是三段路径",
        "midpoint_condition 指向正方形一边的中点",
        "square_center_condition 指向该正方形中心或对角线交点",
        "中点到另一固定点的半边关系已有直角三角形斜边中线依据",
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
