"""Internal kernel for coupled-segment endpoint-replacement path minima.

INTERNAL COMPOSITION BOUNDARY: PathTransformation, straightening candidates,
synthetic reflection points and witness details stay private to this Method.
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, PointRef

from ._common import *
from ._common import is_definitely_nonnegative
from ._spec import MethodSpecSource, declare_input_views
from .broken_path_straightening_candidates import (
    BrokenPathStraighteningCandidatesMethod,
)
from .distance_between_points import DistanceBetweenPointsMethod
from .line_locus_minimum_point import LineLocusMinimumPointMethod
from .select_straightening_candidate import SelectStraighteningCandidateMethod
from .two_moving_points_path_reduction import TwoMovingPointsPathReductionMethod


class CoupledSegmentPathMinimumMethod:
    """Reduce a coupled path, straighten it and recover its attainment point."""

    method_id = "coupled_segment_endpoint_replacement_path_minimum_kernel"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        path_condition = inputs["path_condition"]
        first_membership = inputs["first_membership"]
        second_membership = inputs["second_membership"]
        binding_relation = inputs["segment_binding_relation"]
        first_segment_start: Point = inputs["first_segment_start"]
        joint_point: Point = inputs["joint_point"]
        second_segment_end: Point = inputs["second_segment_end"]
        transformed_fixed_endpoint: Point = inputs["transformed_fixed_endpoint"]
        moving_point_ref: PointRef = inputs["moving_point"]

        results: list[StatelessMethodResult] = []
        reduction = TwoMovingPointsPathReductionMethod().run(
            {
                "original_path": path_condition,
                "first_moving_membership": first_membership,
                "second_moving_membership": second_membership,
                "binding_relation": binding_relation,
                "first_segment_start": first_segment_start,
                "joint_point": joint_point,
                "second_segment_end": second_segment_end,
            },
            kernel,
        )
        results.append(reduction)
        transformation = reduction.outputs["path_transformation"].value

        direction = (
            sp.simplify(second_segment_end[0] - joint_point[0]),
            sp.simplify(second_segment_end[1] - joint_point[1]),
        )
        if direction == (0, 0):
            raise method_precondition_failed(
                "the selected moving-point segment has zero direction",
                arg_name="second_segment_end",
                role="moving_locus_endpoint",
                repair_action="select_connected_coupled_path_facts",
            )
        moving_locus = {
            "kind": "line",
            "point_name": moving_point_ref.name,
            "start_point": joint_point,
            "direction": direction,
            "equation": f"line({moving_point_ref.name})",
        }

        straightening = BrokenPathStraighteningCandidatesMethod().run(
            {
                "path_transformation": transformation,
                "moving_locus": moving_locus,
                "fixed_point_1": first_segment_start,
                "fixed_point_2": transformed_fixed_endpoint,
            },
            kernel,
        )
        results.append(straightening)
        auxiliary_ref = PointRef(
            name="auxiliary",
            path=f"{moving_point_ref.path}#coupled-segment-reflection",
            definition={"definition": "straightening_auxiliary_point"},
            scope_id=moving_point_ref.scope_id,
        )
        selected_result = SelectStraighteningCandidateMethod().run(
            {
                "candidates": straightening.outputs["candidates"].value,
                "target": auxiliary_ref,
            },
            kernel,
        )
        results.append(selected_result)
        minimum_point_1 = selected_result.outputs["minimum_point_1"].value
        minimum_point_2 = selected_result.outputs["minimum_point_2"].value

        distance = DistanceBetweenPointsMethod().run(
            {"p1": minimum_point_1, "p2": minimum_point_2},
            kernel,
        )
        results.append(distance)
        minimum_expression = distance.outputs["distance"].value

        attainment = LineLocusMinimumPointMethod().run(
            {
                "moving_locus": moving_locus,
                "minimum_point_1": minimum_point_1,
                "minimum_point_2": minimum_point_2,
                "target": moving_point_ref,
            },
            kernel,
        )
        results.append(attainment)
        attainment_point = attainment.outputs["point"].value
        segment_parameter = _verified_segment_parameter(
            attainment_point,
            start=joint_point,
            end=second_segment_end,
        )

        selected = selected_result.outputs["selected_candidate"].value
        evidence = {
            "original_objective": str(transformation["original_path"]),
            "reduced_objective": str(transformation["transformed_path"]),
            "equivalence_proof": (str(transformation["segment_equality"]),),
            "moving_locus": str(moving_locus["equation"]),
            "minimum_strategy": str(selected.get("strategy", "reflection")),
            "minimum_expression": kernel.sstr(minimum_expression),
            "attainment_point": tuple(kernel.sstr(item) for item in attainment_point),
            "attainment_segment_parameter": kernel.sstr(segment_parameter),
            "reflected_point": tuple(
                kernel.sstr(item) for item in selected["reflected_point"]
            ),
            "reflect_source": str(selected["reflect_source"]),
            "reflected_point_name": str(selected["reflected_point_name"]),
            "moving_point": str(selected["moving_point"]),
            "other_fixed_point": str(selected["other_fixed_point"]),
            "transformed_path": str(selected["transformed_path"]),
            "straightened_path": str(selected["straightened_path"]),
            "segment_equality": str(transformation["segment_equality"]),
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
                fragment for result in results for fragment in result.trace_fragments
            ],
        )


def _verified_segment_parameter(
    point: Point,
    *,
    start: Point,
    end: Point,
) -> sp.Expr:
    direction = tuple(sp.simplify(b - a) for a, b in zip(start, end))
    nonzero = next((index for index, value in enumerate(direction) if value != 0), None)
    if nonzero is None:
        raise method_precondition_failed(
            "the reduced moving segment is degenerate",
            role="moving_locus",
            repair_action="select_connected_coupled_path_facts",
        )
    parameter = sp.simplify(
        (point[nonzero] - start[nonzero]) / direction[nonzero]
    )
    on_supporting_line = all(
        sp.simplify(start[index] + parameter * direction[index] - point[index]) == 0
        for index in range(len(direction))
    )
    inside_segment = (
        is_definitely_nonnegative(parameter)
        and is_definitely_nonnegative(1 - parameter)
    )
    if not on_supporting_line or not inside_segment:
        raise method_precondition_failed(
            "the straightened equality point is not provably on the source moving segment",
            role="attainment_point",
            expected_state="point_on_moving_segment",
            observed_state=f"segment_parameter={parameter}",
            repair_action="choose_applicable_capability",
        )
    return parameter


SPEC = MethodSpecSource(
    method_cls=CoupledSegmentPathMinimumMethod,
    title="耦合线段端点替换路径最值内核",
    summary=(
        "Given a two-moving-point path and one segment binding relation, "
        "prove an existing-endpoint replacement, straighten the resulting "
        "single-moving-point path, and return its minimum and attainment point."
    ),
    solves=("derive_coupled_segment_path_minimum",),
    inputs={
        "path_condition": {"type": "Condition", "required": True},
        "first_membership": {"type": "Condition", "required": True},
        "second_membership": {"type": "Condition", "required": True},
        "segment_binding_relation": {"type": "Condition", "required": True},
        "first_segment_start": {"type": "Point", "required": True},
        "joint_point": {"type": "Point", "required": True},
        "second_segment_end": {"type": "Point", "required": True},
        "transformed_fixed_endpoint": {"type": "Point", "required": True},
        "moving_point": {"type": "PointRef", "required": True},
    },
    input_views=declare_input_views(
        immutable_value=(
            "path_condition",
            "first_membership",
            "second_membership",
            "segment_binding_relation",
        ),
        latest_state=(
            "first_segment_start",
            "joint_point",
            "second_segment_end",
            "transformed_fixed_endpoint",
        ),
        identity=("moving_point",),
    ),
    outputs={
        "minimum_expression": "MinimumExpression",
        "attainment_point": "Point",
        "evidence": "PathWitness",
    },
    internal_outputs=("evidence",),
    preconditions=(
        "the selected path and relation determine one connected two-moving-point graph",
        "the coupling proves an existing fixed-endpoint replacement",
        "the reduced moving point has one non-degenerate line locus",
    ),
    postconditions=(
        "minimum_expression equals the source path minimum",
        "attainment_point is the original reduced moving point at equality",
    ),
    explanation=MethodExplanationSpec(
        role_schema={
            "original_path": "题设两动点路径。",
            "reduced_path": "等长替换后的单动点折线路径。",
            "minimum_expression": "拉直后得到的最小值表达式。",
            "attainment_point": "路径取得最小值时的原题动点。",
        },
        student_goal_template="利用耦合线段关系降维并求路径最小值。",
        student_title_template="端点替换后的路径最值",
        derive_templates=(
            "把 {original_path} 等价化为 {reduced_path}。",
            "拉直单动点路径得到 {minimum_expression}。",
            "确定最短状态下的 {attainment_point}。",
        ),
        box_templates=("{minimum_expression}", "{attainment_point}"),
        role_binder_id="coupled_segment_path_minimum",
    ),
)


__all__ = ["CoupledSegmentPathMinimumMethod", "SPEC"]
