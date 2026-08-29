"""Deterministic kernel for a quadratic-function square path minimum.

INTERNAL COMPOSITION BOUNDARY: this Method is private to the atomic Macro.
It deliberately keeps using the verified PathTransformation composition
Methods even if their public planner-facing capabilities are later retired.
Only the minimum expression and the original moving point at equality cross
this boundary.
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, PointRef

from ._common import *
from ._internal.path.broken_path_straightening_candidates import (
    BrokenPathStraighteningCandidatesMethod,
)
from ._internal.path.line_locus_minimum_point import LineLocusMinimumPointMethod
from ._internal.path.parameterized_point_locus_line import (
    ParameterizedPointLocusLineMethod,
)
from ._internal.path.select_straightening_candidate import (
    SelectStraighteningCandidateMethod,
)
from ._internal.path.square_path_dimension_reduction import (
    SquarePathDimensionReductionMethod,
)
from ._spec import MethodSpecSource, declare_input_views
from .distance_between_points import DistanceBetweenPointsMethod
from .quadratic_axis_parameterized_point import (
    QuadraticAxisParameterizedPointMethod,
)
from .quadratic_axis_x_intercept_point import QuadraticAxisXInterceptPointMethod
from .square_adjacent_vertex_from_side import SquareAdjacentVertexFromSideMethod


class QuadraticSquarePathMinimumMethod:
    """Internal-only composition of reduction, locus and straightening."""

    method_id = "quadratic_square_path_minimum_kernel"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parabola = inputs["parabola"]
        path_condition = inputs["path_condition"]
        square_condition = inputs["square_condition"]
        midpoint_condition = inputs["midpoint_definition"]
        center_condition = inputs["square_center"]
        axis_membership = inputs["axis_membership"]
        side_start: Point = inputs["side_start"]
        side_start_ref: PointRef = inputs["side_start_ref"]
        axis_point_ref: PointRef = inputs["axis_point"]
        moving_point_ref: PointRef = inputs["moving_point"]
        fixed_endpoint_ref: PointRef = inputs["fixed_endpoint"]

        if str(axis_membership.get("point", "")) not in {
            axis_point_ref.path,
            axis_point_ref.definition.get("handle"),
        } and _ref_name(str(axis_membership.get("point", ""))) != axis_point_ref.name:
            raise method_input_invalid(
                "axis membership does not describe the selected square side point",
                arg_name="axis_membership",
                role="axis_point",
                expected={"point": axis_point_ref.name},
                observed={"point": axis_membership.get("point")},
                repair_action="select_connected_square_axis_facts",
            )

        x = next(
            (symbol for symbol in parabola.free_symbols if symbol.name == "x"),
            None,
        )
        if x is None:
            raise method_input_invalid(
                "quadratic square path kernel requires the canonical x symbol",
                arg_name="parabola",
                role="function_variable",
                expected={"symbol": "x"},
                observed={"free_symbols": sorted(s.name for s in parabola.free_symbols)},
                repair_action="provide_current_quadratic_state",
            )

        results: list[StatelessMethodResult] = []
        axis_point_result = QuadraticAxisParameterizedPointMethod().run(
            {"parabola": parabola, "x": x, "target": axis_point_ref},
            kernel,
        )
        results.append(axis_point_result)
        axis_point = axis_point_result.outputs["point"].value
        axis_parameter = axis_point_result.outputs["parameter"].value

        moving_point_result = SquareAdjacentVertexFromSideMethod().run(
            {
                "side_start": side_start,
                "side_end": axis_point,
                "square_condition": square_condition,
                "target": moving_point_ref,
                "side_start_ref": side_start_ref,
                "side_end_ref": axis_point_ref,
            },
            kernel,
        )
        results.append(moving_point_result)
        moving_point = moving_point_result.outputs["point"].value

        fixed_result = QuadraticAxisXInterceptPointMethod().run(
            {"parabola": parabola, "x": x, "target": fixed_endpoint_ref},
            kernel,
        )
        results.append(fixed_result)
        fixed_endpoint = fixed_result.outputs["axis_point"].value

        reduction_result = SquarePathDimensionReductionMethod().run(
            {
                "path_condition": path_condition,
                "square_condition": square_condition,
                "midpoint_condition": midpoint_condition,
                "square_center_condition": center_condition,
                "moving_point": moving_point_ref,
                "fixed_endpoint_1_ref": side_start_ref,
                "fixed_endpoint_2_ref": fixed_endpoint_ref,
            },
            kernel,
        )
        results.append(reduction_result)
        transformation = reduction_result.outputs["path_transformation"].value

        locus_result = ParameterizedPointLocusLineMethod().run(
            {
                "point": moving_point,
                "target": moving_point_ref,
                "parameter": axis_parameter,
            },
            kernel,
        )
        results.append(locus_result)
        moving_locus = locus_result.outputs["line"].value

        straightening_result = BrokenPathStraighteningCandidatesMethod().run(
            {
                "path_transformation": transformation,
                "moving_locus": moving_locus,
                "fixed_point_1": side_start,
                "fixed_point_2": fixed_endpoint,
            },
            kernel,
        )
        results.append(straightening_result)
        auxiliary_ref = PointRef(
            name="auxiliary",
            path=f"{moving_point_ref.path}#quadratic-square-reflection",
            definition={"definition": "straightening_auxiliary_point"},
            scope_id=moving_point_ref.scope_id,
        )
        selected_result = SelectStraighteningCandidateMethod().run(
            {
                "candidates": straightening_result.outputs["candidates"].value,
                "target": auxiliary_ref,
            },
            kernel,
        )
        results.append(selected_result)
        minimum_point_1 = selected_result.outputs["minimum_point_1"].value
        minimum_point_2 = selected_result.outputs["minimum_point_2"].value

        distance_result = DistanceBetweenPointsMethod().run(
            {"p1": minimum_point_1, "p2": minimum_point_2},
            kernel,
        )
        results.append(distance_result)
        minimum_expression = distance_result.outputs["distance"].value

        attainment_result = LineLocusMinimumPointMethod().run(
            {
                "moving_locus": moving_locus,
                "minimum_point_1": minimum_point_1,
                "minimum_point_2": minimum_point_2,
                "target": moving_point_ref,
            },
            kernel,
        )
        results.append(attainment_result)
        attainment_point = attainment_result.outputs["point"].value

        selected = selected_result.outputs["selected_candidate"].value
        evidence = {
            "original_objective": str(transformation["original_path"]),
            "reduced_objective": str(transformation["transformed_path"]),
            "equivalence_proof": tuple(
                str(value) for value in transformation["relations"].values()
            ),
            "moving_locus": str(moving_locus.get("equation", "line")),
            "minimum_strategy": str(selected.get("strategy", "reflection")),
            "minimum_expression": kernel.sstr(minimum_expression),
            "attainment_point": tuple(kernel.sstr(item) for item in attainment_point),
            "reflected_point": tuple(
                kernel.sstr(item) for item in selected["reflected_point"]
            ),
            "reflect_source": str(selected["reflect_source"]),
            "reflected_point_name": str(selected["reflected_point_name"]),
            "moving_point": str(selected["moving_point"]),
            "other_fixed_point": str(selected["other_fixed_point"]),
            "transformed_path": str(selected["transformed_path"]),
            "straightened_path": str(selected["straightened_path"]),
            "segment_equality": str(selected["segment_equality"]),
            "minimum_segment": str(selected["minimum_segment"]),
        }
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "minimum_expression": TypedValue(
                    "MinimumExpression",
                    minimum_expression,
                    source=self.method_id,
                ),
                "attainment_point": TypedValue(
                    "Point",
                    attainment_point,
                    source=self.method_id,
                ),
                "evidence": TypedValue(
                    "PathWitness",
                    evidence,
                    source=self.method_id,
                ),
            },
            checks=[check for result in results for check in result.checks],
            trace_fragments=[
                _step(
                    self.method_id,
                    "正方形约束下的路径最值",
                    "求路径最小值和取等点",
                    "由当前抛物线与正方形关系确定动点状态，在内部完成等价降维、反射与取等验证。",
                    (
                        f"{evidence['original_objective']}="
                        f"{evidence['reduced_objective']}"
                    ),
                    (
                        f"最小值为 {kernel.sstr(minimum_expression)}，"
                        f"在 {moving_point_ref.name}"
                        f"{_fmt_point(attainment_point, kernel)} 处取得"
                    ),
                )
            ],
        )


def _ref_name(value: str) -> str:
    return value.rsplit(":", 1)[-1]


SPEC = MethodSpecSource(
    method_cls=QuadraticSquarePathMinimumMethod,
    title="二次函数正方形路径最值内核",
    summary=(
        "Given a current quadratic state, one square-governed path objective, "
        "and code-resolved structural roles, derive the exact minimum expression "
        "and the original moving point at equality."
    ),
    solves=("derive_quadratic_square_path_minimum",),
    inputs={
        "parabola": {"type": "Parabola", "required": True},
        "path_condition": {"type": "Condition", "required": True},
        "square_condition": {"type": "Condition", "required": True},
        "midpoint_definition": {
            "type": "Condition",
            "required": True,
        },
        "square_center": {
            "type": "Condition",
            "required": True,
        },
        "axis_membership": {
            "type": "Condition",
            "required": True,
        },
        "side_start": {
            "type": "Point",
            "required": True,
        },
        "side_start_ref": {
            "type": "PointRef",
            "required": True,
        },
        "axis_point": {
            "type": "PointRef",
            "required": True,
        },
        "moving_point": {
            "type": "PointRef",
            "required": True,
        },
        "fixed_endpoint": {
            "type": "PointRef",
            "required": True,
        },
    },
    input_views=declare_input_views(
        latest_state=("parabola", "side_start"),
        immutable_value=(
            "path_condition",
            "square_condition",
            "midpoint_definition",
            "square_center",
            "axis_membership",
        ),
        identity=(
            "side_start_ref",
            "axis_point",
            "moving_point",
            "fixed_endpoint",
        ),
    ),
    outputs={
        "minimum_expression": "MinimumExpression",
        "attainment_point": "Point",
        "evidence": "PathWitness",
    },
    internal_outputs=("evidence",),
    preconditions=(
        "the selected square, midpoint, center and axis facts form one connected proof closure",
        "the three-segment source path admits one square reduction to a line-locus moving point",
    ),
    postconditions=(
        "minimum_expression equals the original path minimum",
        "attainment_point lies on the moving locus and the straightened minimum segment",
    ),
    explanation=MethodExplanationSpec(
        role_schema={
            "original_path": "题设三段路径。",
            "reduced_path": "由正方形关系得到的单动点折线路径。",
            "moving_locus": "正方形动点的轨迹直线。",
            "minimum_expression": "拉直后得到的最小值表达式。",
            "attainment_point": "路径取最小值时的原题动点。",
        },
        student_goal_template="利用二次函数与正方形关系求路径最小值。",
        student_title_template="正方形关系下的路径最值",
        derive_templates=(
            "把 {original_path} 化为 {reduced_path}。",
            "求出动点轨迹 {moving_locus}。",
            "拉直路径得到 {minimum_expression}，并确定 {attainment_point}。",
        ),
        box_templates=("{minimum_expression}", "{attainment_point}"),
        role_binder_id="quadratic_square_path_minimum",
    ),
)


__all__ = ["QuadraticSquarePathMinimumMethod", "SPEC"]
