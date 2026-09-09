"""Internal kernel for the atomic weighted-axis path minimum Macro.

INTERNAL COMPOSITION BOUNDARY: the auxiliary triangle, synthetic point,
PathTransformation, locus and equality-state expressions never cross the
Planner-facing capability boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from shuxueshuo_server.solver.contracts import (
    PointRef,
    ScalarResultFormSpec,
)

from ._internal.path.linked_broken_path_geometric_minimum import (
    LinkedBrokenPathMinimumExpressionMethod,
)
from ._internal.path.weighted_axis_path_triangle_transform import (
    WeightedAxisPathTriangleTransformMethod,
)
from ._common import *
from ._common import (
    is_definitely_nonnegative,
    is_definitely_positive_under_lower_bound,
)
from ._spec import MethodSpecSource, declare_input_views


@dataclass(frozen=True)
class _WeightedOrientationCandidate:
    orientation_sign: int
    transform: StatelessMethodResult
    minimum: StatelessMethodResult
    minimum_expression: sp.Expr
    interior_minimum_expression: sp.Expr
    attainment_condition: sp.Expr
    boundary_minimum_expression: sp.Expr | None
    dynamic_parameter_expression: sp.Expr
    dynamic_point_expression: Point
    auxiliary_attainment_point: Point
    ray_parameter: sp.Expr
    path_segment_parameter: sp.Expr


class _ProofVerdict(str, Enum):
    PROVED_TRUE = "proved_true"
    PROVED_FALSE = "proved_false"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class _ProofResult:
    verdict: _ProofVerdict
    reduced: sp.Expr | None = None
    error: str | None = None


class WeightedAxisPathMinimumMethod:
    """Transform one weighted two-term axis path and prove its minimum."""

    method_id = "weighted_axis_path_minimum_kernel"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        path_condition = inputs["path_condition"]
        fixed_point: Point = inputs["fixed_point"]
        curve_point: Point = inputs["curve_point"]
        moving_point: Point = inputs["moving_point"]
        moving_point_ref: PointRef = inputs["moving_point_ref"]
        parameter: sp.Symbol = inputs["parameter"]
        dynamic_parameter: sp.Symbol = inputs["dynamic_parameter"]
        parameter_constraint = _canonicalize_runtime_constraint(
            inputs["parameter_constraint"],
            kernel,
            arg_name="parameter_constraint",
        )
        dynamic_constraint = _canonicalize_runtime_constraint(
            inputs["dynamic_constraint"],
            kernel,
            arg_name="dynamic_constraint",
        )
        assert parameter_constraint is not None
        assert dynamic_constraint is not None

        auxiliary_ref = PointRef(
            name="auxiliary",
            path=f"{moving_point_ref.path}#weighted-axis-triangle",
            definition={"definition": "weighted_axis_internal_auxiliary"},
            scope_id=moving_point_ref.scope_id,
        )
        valid: list[_WeightedOrientationCandidate] = []
        rejected: list[dict[str, Any]] = []
        for orientation_sign in (1, -1):
            try:
                candidate = _evaluate_orientation(
                    orientation_sign=orientation_sign,
                    path_condition=path_condition,
                    fixed_point=fixed_point,
                    curve_point=curve_point,
                    moving_point=moving_point,
                    moving_point_ref=moving_point_ref,
                    auxiliary_ref=auxiliary_ref,
                    parameter=parameter,
                    dynamic_parameter=dynamic_parameter,
                    parameter_constraint=parameter_constraint,
                    dynamic_constraint=dynamic_constraint,
                    kernel=kernel,
                )
            except StatelessMethodError as exc:
                authority = exc.authority
                if authority.retryability == "configuration":
                    raise
                rejected.append(
                    {
                        "orientation_sign": orientation_sign,
                        "code": authority.code,
                        "message": str(exc),
                    }
                )
                continue
            valid.append(candidate)

        if not valid:
            raise method_precondition_failed(
                "no weighted triangle orientation has a reachable equality state",
                role="weighted_path_orientation",
                expected={"valid_candidate_count": 1},
                observed={
                    "valid_candidate_count": 0,
                    "candidate_diagnostics": rejected,
                },
                repair_action="choose_applicable_weighted_path_capability",
            )
        reference = valid[0].minimum_expression
        inequivalent = tuple(
            item
            for item in valid[1:]
            if sp.simplify(item.minimum_expression - reference) != 0
        )
        if inequivalent:
            raise method_result_ambiguous(
                "multiple weighted triangle orientations produce non-equivalent minima",
                role="weighted_path_orientation",
                expected={"equivalent_public_output_count": 1},
                observed={
                    "candidates": [
                        {
                            "orientation_sign": item.orientation_sign,
                            "minimum_expression": kernel.sstr(
                                item.minimum_expression
                            ),
                        }
                        for item in valid
                    ]
                },
                repair_action="supply_disambiguating_geometric_constraint",
            )
        winner = valid[0]
        transformation = winner.transform.outputs[
            "path_transformation"
        ].value
        locus = winner.transform.outputs["auxiliary_locus"].value
        axis_projection_geometry = _axis_projection_geometry_witness(
            weight=sp.sympify(transformation["scale"]),
            fixed_point=fixed_point,
            curve_point=curve_point,
            moving_point=moving_point,
            interior_moving_point=winner.dynamic_point_expression,
            dynamic_parameter=dynamic_parameter,
            dynamic_constraint=dynamic_constraint,
            parameter=parameter,
            parameter_constraint=parameter_constraint,
            attainment_condition=winner.attainment_condition,
            interior_minimum=winner.interior_minimum_expression,
            boundary_minimum=winner.boundary_minimum_expression,
            locus_start=tuple(sp.sympify(item) for item in locus["start_point"]),
            locus_direction=tuple(
                sp.sympify(item) for item in locus["direction"]
            ),
            kernel=kernel,
        )
        evidence = {
            "original_objective": str(path_condition.get("path", "weighted path")),
            "weight": kernel.sstr(sp.sympify(transformation["scale"])),
            "orientation_sign": winner.orientation_sign,
            "triangle_geometry": dict(transformation["geometry"]),
            "path_equivalence": dict(transformation["path_equivalence"]),
            "auxiliary_point_formula": tuple(
                kernel.sstr(item)
                for item in winner.transform.outputs["auxiliary_point"].value
            ),
            "auxiliary_locus": str(locus["equation"]),
            "auxiliary_locus_kind": str(locus["kind"]),
            "minimum_strategy": "weighted_triangle_then_reachable_straightening",
            "minimum_expression": kernel.sstr(winner.minimum_expression),
            "interior_minimum_expression": kernel.sstr(
                winner.interior_minimum_expression
            ),
            "attainment_condition": kernel.sstr(winner.attainment_condition),
            "boundary_minimum_expression": (
                kernel.sstr(winner.boundary_minimum_expression)
                if winner.boundary_minimum_expression is not None
                else None
            ),
            "dynamic_parameter_expression": kernel.sstr(
                winner.dynamic_parameter_expression
            ),
            "dynamic_point_expression": tuple(
                kernel.sstr(item) for item in winner.dynamic_point_expression
            ),
            "auxiliary_attainment_point": tuple(
                kernel.sstr(item) for item in winner.auxiliary_attainment_point
            ),
            "ray_parameter": kernel.sstr(winner.ray_parameter),
            "path_segment_parameter": kernel.sstr(
                winner.path_segment_parameter
            ),
            "axis_projection_geometry": axis_projection_geometry,
            "orientation_candidates": tuple(
                {
                    "orientation_sign": item.orientation_sign,
                    "minimum_expression": kernel.sstr(item.minimum_expression),
                    "equivalent_to_winner": (
                        sp.simplify(
                            item.minimum_expression
                            - winner.minimum_expression
                        )
                        == 0
                    ),
                }
                for item in valid
            ),
            "rejected_orientations": tuple(rejected),
        }
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "minimum_expression": TypedValue(
                    "MinimumExpression",
                    winner.minimum_expression,
                    source=self.method_id,
                ),
                "evidence": TypedValue(
                    "PathWitness",
                    evidence,
                    source=self.method_id,
                ),
            },
            checks=[
                *winner.transform.checks,
                *winner.minimum.checks,
                _check(
                    "auxiliary_attainment_on_declared_ray",
                    _prove_nonnegative_on_parameter_domain(
                        winner.ray_parameter,
                        parameter=parameter,
                        constraint=parameter_constraint,
                    ),
                    "取等辅助点位于声明射线，而不只是所在直线",
                ),
                _check(
                    "moving_parameter_in_declared_domain",
                    _constraint_branch_is_represented(
                        winner,
                        target_constraint=dynamic_constraint,
                        parameter=parameter,
                        parameter_constraint=parameter_constraint,
                    ),
                    "只在取等点属于动点定义域时发布最小值",
                ),
                _check(
                    "straightening_equality_is_reachable",
                    _prove_unit_interval_on_parameter_domain(
                        winner.path_segment_parameter,
                        parameter=parameter,
                        constraint=parameter_constraint,
                    ),
                    "原动点位于曲线端点与辅助点之间，折线等号可达到",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "加权轴上路径最值",
                    "求可取得的最小值表达式",
                    "在内部构造与权重匹配的辅助三角形，拉直路径并验证取等点属于动点定义域。",
                    (
                        f"权重={evidence['weight']}，构造关系已验证"
                    ),
                    f"最小值表达式为 {kernel.sstr(winner.minimum_expression)}",
                )
            ],
        )


def _evaluate_orientation(
    *,
    orientation_sign: int,
    path_condition: dict[str, Any],
    fixed_point: Point,
    curve_point: Point,
    moving_point: Point,
    moving_point_ref: PointRef,
    auxiliary_ref: PointRef,
    parameter: sp.Symbol,
    dynamic_parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
    dynamic_constraint: dict[str, sp.Expr | str],
    kernel: SympyKernel,
) -> _WeightedOrientationCandidate:
    transform = WeightedAxisPathTriangleTransformMethod().run(
        {
            "condition": path_condition,
            "fixed_point": fixed_point,
            "moving_point": moving_point,
            "moving_point_ref": moving_point_ref,
            "dynamic_parameter": dynamic_parameter,
            "auxiliary_point_ref": auxiliary_ref,
            "_orientation_sign": orientation_sign,
        },
        kernel,
    )
    minimum = LinkedBrokenPathMinimumExpressionMethod().run(
        {
            "path_transformation": transform.outputs[
                "path_transformation"
            ].value,
            "auxiliary_locus": transform.outputs["auxiliary_locus"].value,
            "fixed_point": fixed_point,
            "curve_point": curve_point,
            "moving_point": moving_point,
            "auxiliary_point": transform.outputs["auxiliary_point"].value,
            "parameter": parameter,
            "dynamic_parameter": dynamic_parameter,
            "parameter_constraint": parameter_constraint,
            "dynamic_constraint": dynamic_constraint,
        },
        kernel,
    )
    if not all(check.ok for check in (*transform.checks, *minimum.checks)):
        raise method_precondition_failed(
            "weighted orientation failed an internal mathematical check",
            role="weighted_path_orientation",
            observed={"orientation_sign": orientation_sign},
            repair_action="choose_applicable_weighted_path_capability",
        )
    dynamic_expression = minimum.outputs[
        "dynamic_parameter_expression"
    ].value
    dynamic_point = minimum.outputs["dynamic_point_expression"].value
    auxiliary_point = tuple(
        sp.simplify(item.subs(dynamic_parameter, dynamic_expression))
        for item in transform.outputs["auxiliary_point"].value
    )
    locus = transform.outputs["auxiliary_locus"].value
    direction = tuple(sp.sympify(item) for item in locus["direction"])
    start = tuple(sp.sympify(item) for item in locus["start_point"])
    ray_parameter = _affine_parameter(
        auxiliary_point,
        start=start,
        direction=direction,
        role="auxiliary_ray",
    )
    segment_direction = tuple(
        sp.simplify(auxiliary_point[index] - curve_point[index])
        for index in range(2)
    )
    path_segment_parameter = _affine_parameter(
        dynamic_point,
        start=curve_point,
        direction=segment_direction,
        role="straightening_segment",
    )
    if not _prove_nonnegative_on_parameter_domain(
        ray_parameter,
        parameter=parameter,
        constraint=parameter_constraint,
    ):
        raise method_precondition_failed(
            "the straightening foot lies outside the declared auxiliary ray",
            role="auxiliary_ray",
            observed={
                "orientation_sign": orientation_sign,
                "ray_parameter": str(ray_parameter),
            },
            repair_action="choose_applicable_weighted_path_capability",
        )
    if not _prove_unit_interval_on_parameter_domain(
        path_segment_parameter,
        parameter=parameter,
        constraint=parameter_constraint,
    ):
        raise method_precondition_failed(
            "the shared moving point cannot attain equality on the straightened segment",
            role="attainment",
            observed={
                "orientation_sign": orientation_sign,
                "segment_parameter": str(path_segment_parameter),
            },
            repair_action="choose_applicable_weighted_path_capability",
        )
    interior_minimum = minimum.outputs["minimum_expression"].value
    (
        minimum_expression,
        attainment_condition,
        boundary_minimum,
    ) = _minimum_with_dynamic_domain(
        interior_minimum=interior_minimum,
        dynamic_expression=dynamic_expression,
        target_constraint=dynamic_constraint,
        parameter=parameter,
        parameter_constraint=parameter_constraint,
    )
    return _WeightedOrientationCandidate(
        orientation_sign=orientation_sign,
        transform=transform,
        minimum=minimum,
        minimum_expression=minimum_expression,
        interior_minimum_expression=interior_minimum,
        attainment_condition=attainment_condition,
        boundary_minimum_expression=boundary_minimum,
        dynamic_parameter_expression=dynamic_expression,
        dynamic_point_expression=dynamic_point,
        auxiliary_attainment_point=auxiliary_point,
        ray_parameter=ray_parameter,
        path_segment_parameter=path_segment_parameter,
        )


def _axis_projection_geometry_witness(
    *,
    weight: sp.Expr,
    fixed_point: Point,
    curve_point: Point,
    moving_point: Point,
    interior_moving_point: Point,
    dynamic_parameter: sp.Symbol,
    dynamic_constraint: dict[str, sp.Expr | str],
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
    attainment_condition: sp.Expr,
    interior_minimum: sp.Expr,
    boundary_minimum: sp.Expr | None,
    locus_start: Point,
    locus_direction: Point,
    kernel: SympyKernel,
) -> dict[str, Any]:
    """Publish a reusable axis-projection proof, not problem-specific prose.

    Every successful ``weighted_axis_path_minimum`` invocation already proves
    that the moving point lies on the x-axis and that the straightened path is
    attainable.  This certificate exposes the corresponding right-triangle
    lengths so the teaching layer can explain the minimum geometrically for
    every legal constant weight, with or without a familiar teaching profile.
    """

    zero = sp.Integer(0)
    if (
        sp.simplify(fixed_point[1]) != zero
        or sp.simplify(moving_point[1]) != zero
        or sp.simplify(interior_moving_point[1]) != zero
    ):
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            "weighted-axis geometry witness requires x-axis endpoints",
            category="configuration",
            retryability="configuration",
            role="axis_projection_geometry",
            repair_action="fix_runtime_contract",
        )

    projection_point = (sp.simplify(curve_point[0]), zero)
    vertical_length = _oriented_length_on_parameter_domain(
        sp.simplify(curve_point[1]),
        parameter=parameter,
        constraint=parameter_constraint,
    )
    horizontal_length = _oriented_length_on_parameter_domain(
        sp.simplify(curve_point[0] - interior_moving_point[0]),
        parameter=parameter,
        constraint=parameter_constraint,
    )
    fixed_to_moving = _oriented_length_on_parameter_domain(
        sp.simplify(interior_moving_point[0] - fixed_point[0]),
        parameter=parameter,
        constraint=parameter_constraint,
    )
    fixed_to_projection = _oriented_length_on_parameter_domain(
        sp.simplify(projection_point[0] - fixed_point[0]),
        parameter=parameter,
        constraint=parameter_constraint,
    )
    auxiliary_to_moving = sp.simplify(fixed_to_moving / weight)

    curve_to_moving_squared = sp.factor(
        vertical_length**2 + horizontal_length**2
    )
    if sp.simplify(vertical_length - horizontal_length) == 0:
        curve_to_moving = sp.simplify(sp.sqrt(2) * vertical_length)
        projection_triangle_relation: dict[str, Any] = {
            "kind": "equal_legs",
        }
    elif sp.simplify(vertical_length**2 - 3 * horizontal_length**2) == 0:
        curve_to_moving = sp.simplify(2 * horizontal_length)
        projection_triangle_relation = {
            "kind": "vertical_squared_multiple_of_horizontal",
            "multiplier": "3",
        }
    elif sp.simplify(horizontal_length**2 - 3 * vertical_length**2) == 0:
        curve_to_moving = sp.simplify(2 * vertical_length)
        projection_triangle_relation = {
            "kind": "horizontal_squared_multiple_of_vertical",
            "multiplier": "3",
        }
    else:
        implied_length = sp.simplify(
            interior_minimum / weight - auxiliary_to_moving
        )
        if (
            sp.simplify(implied_length**2 - curve_to_moving_squared) == 0
            and _prove_nonnegative_on_parameter_domain(
                implied_length,
                parameter=parameter,
                constraint=parameter_constraint,
            )
        ):
            curve_to_moving = implied_length
        else:
            curve_to_moving = sp.sqrt(curve_to_moving_squared)
        projection_triangle_relation = {"kind": "pythagorean"}

    straightened_length = sp.simplify(curve_to_moving + auxiliary_to_moving)

    lower = dynamic_constraint.get("value")
    if not isinstance(lower, sp.Basic):
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            "weighted-axis geometry witness requires a canonical domain endpoint",
            category="configuration",
            retryability="configuration",
            role="axis_projection_geometry",
            repair_action="fix_runtime_contract",
        )
    boundary_point = tuple(
        sp.simplify(sp.sympify(item).subs(dynamic_parameter, lower))
        for item in moving_point
    )
    boundary_curve_distance_squared = sp.factor(
        kernel.distance_squared(curve_point, boundary_point)
    )
    boundary_fixed_length = _oriented_length_on_parameter_domain(
        sp.simplify(boundary_point[0] - fixed_point[0]),
        parameter=parameter,
        constraint=parameter_constraint,
    )
    direction_coordinate = next(
        (
            index
            for index, value in enumerate(locus_direction)
            if sp.simplify(value) != 0
        ),
        None,
    )
    if direction_coordinate is None:
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            "weighted-axis teaching locus has no direction",
            category="configuration",
            retryability="configuration",
            role="axis_projection_geometry",
            repair_action="fix_runtime_contract",
        )
    direction_scale = sp.simplify(
        1 / locus_direction[direction_coordinate]
    )
    locus_reference_point = tuple(
        sp.simplify(
            locus_start[index]
            + direction_scale * locus_direction[index]
        )
        for index in range(2)
    )
    if sp.simplify(
        fixed_to_projection - horizontal_length - fixed_to_moving
    ) == 0:
        fixed_moving_decomposition = "projection_minus_horizontal"
    elif sp.simplify(
        fixed_to_projection + horizontal_length - fixed_to_moving
    ) == 0:
        fixed_moving_decomposition = "projection_plus_horizontal"
    elif sp.simplify(
        horizontal_length - fixed_to_projection - fixed_to_moving
    ) == 0:
        fixed_moving_decomposition = "horizontal_minus_projection"
    else:
        fixed_moving_decomposition = "coordinate_distance"

    def point_payload(point: Point) -> list[str]:
        return [kernel.sstr(sp.factor(item)) for item in point]

    return {
        "kind": "axis_projection_geometric_minimum",
        "projection_triangle_relation": projection_triangle_relation,
        "fixed_point": point_payload(fixed_point),
        "curve_point": point_payload(curve_point),
        "moving_point_formula": point_payload(moving_point),
        "interior_moving_point": point_payload(interior_moving_point),
        "projection_point": point_payload(projection_point),
        "boundary_point": point_payload(boundary_point),
        "locus_start_point": point_payload(locus_start),
        "locus_direction": point_payload(locus_direction),
        "locus_reference_point": point_payload(locus_reference_point),
        "parameter": str(parameter),
        "parameter_constraint": {
            "operator": str(parameter_constraint.get("operator") or ""),
            "value": kernel.sstr(sp.sympify(parameter_constraint["value"])),
        },
        "dynamic_parameter": str(dynamic_parameter),
        "dynamic_constraint": {
            "operator": str(dynamic_constraint.get("operator") or ""),
            "value": kernel.sstr(lower),
        },
        "vertical_leg_length": kernel.sstr(sp.factor(vertical_length)),
        "horizontal_leg_length": kernel.sstr(sp.factor(horizontal_length)),
        "curve_to_moving_length_squared": kernel.sstr(
            curve_to_moving_squared
        ),
        "curve_to_moving_length": kernel.sstr(sp.factor(curve_to_moving)),
        "fixed_to_projection_length": kernel.sstr(
            sp.factor(fixed_to_projection)
        ),
        "fixed_moving_decomposition": fixed_moving_decomposition,
        "fixed_to_moving_length": kernel.sstr(sp.factor(fixed_to_moving)),
        "auxiliary_to_moving_length": kernel.sstr(
            sp.factor(auxiliary_to_moving)
        ),
        "straightened_length": kernel.sstr(sp.factor(straightened_length)),
        "scaled_interior_minimum": kernel.sstr(
            sp.together(sp.expand(interior_minimum))
        ),
        "attainment_condition": kernel.sstr(attainment_condition),
        "boundary_curve_distance_squared": kernel.sstr(
            boundary_curve_distance_squared
        ),
        "boundary_fixed_length": kernel.sstr(
            sp.factor(boundary_fixed_length)
        ),
        "boundary_minimum_expression": (
            kernel.sstr(boundary_minimum)
            if boundary_minimum is not None
            else None
        ),
    }


def _oriented_length_on_parameter_domain(
    expression: sp.Expr,
    *,
    parameter: sp.Symbol,
    constraint: dict[str, sp.Expr | str],
) -> sp.Expr:
    """Choose the nonnegative orientation of one collinear segment length."""

    simplified = sp.simplify(expression)
    for candidate in (simplified, sp.simplify(-simplified)):
        if _prove_nonnegative_on_parameter_domain(
            candidate,
            parameter=parameter,
            constraint=constraint,
        ):
            return candidate
    # The squared form remains a correct student-visible length even when the
    # symbolic sign prover cannot orient a future parameterization.
    return sp.sqrt(sp.factor(simplified**2))


def _affine_parameter(
    point: Point,
    *,
    start: Point,
    direction: Point,
    role: str,
) -> sp.Expr:
    nonzero = next(
        (
            index
            for index, value in enumerate(direction)
            if sp.simplify(value) != 0
        ),
        None,
    )
    if nonzero is None:
        raise method_precondition_failed(
            "weighted path candidate has a degenerate affine direction",
            role=role,
            repair_action="choose_applicable_weighted_path_capability",
        )
    parameter = sp.simplify(
        (point[nonzero] - start[nonzero]) / direction[nonzero]
    )
    if any(
        sp.simplify(
            start[index] + parameter * direction[index] - point[index]
        )
        != 0
        for index in range(2)
    ):
        raise method_precondition_failed(
            "weighted path candidate is not on its declared affine locus",
            role=role,
            repair_action="choose_applicable_weighted_path_capability",
        )
    return parameter


def _constraint_lower_bound(
    constraint: dict[str, sp.Expr | str],
) -> sp.Expr | None:
    if str(constraint.get("operator", "")) != ">":
        return None
    value = constraint.get("value")
    return value if isinstance(value, sp.Basic) else None


def _prove_nonnegative_on_parameter_domain(
    expression: sp.Expr,
    *,
    parameter: sp.Symbol,
    constraint: dict[str, sp.Expr | str],
) -> bool:
    expression = sp.simplify(expression)
    if is_definitely_nonnegative(expression):
        return True
    lower = _constraint_lower_bound(constraint)
    return lower is not None and is_definitely_positive_under_lower_bound(
        expression,
        parameter,
        lower,
    )


def _prove_unit_interval_on_parameter_domain(
    expression: sp.Expr,
    *,
    parameter: sp.Symbol,
    constraint: dict[str, sp.Expr | str],
) -> bool:
    return _prove_nonnegative_on_parameter_domain(
        expression,
        parameter=parameter,
        constraint=constraint,
    ) and _prove_nonnegative_on_parameter_domain(
        sp.simplify(1 - expression),
        parameter=parameter,
        constraint=constraint,
    )


def _prove_constraint_on_parameter_domain(
    expression: sp.Expr,
    *,
    target_constraint: dict[str, sp.Expr | str],
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
) -> _ProofResult:
    if str(target_constraint.get("operator", "")) != ">":
        return _ProofResult(
            _ProofVerdict.UNKNOWN,
            error="unsupported target constraint operator",
        )
    lower = target_constraint.get("value")
    if not isinstance(lower, sp.Basic):
        return _ProofResult(
            _ProofVerdict.UNKNOWN,
            error="target constraint has no canonical symbolic bound",
        )
    positive = sp.simplify(expression - lower)
    if is_definitely_positive(positive):
        return _ProofResult(_ProofVerdict.PROVED_TRUE, sp.S.true)
    parameter_lower = _constraint_lower_bound(parameter_constraint)
    if parameter_lower is not None and is_definitely_positive_under_lower_bound(
            positive,
            parameter,
            parameter_lower,
        ):
        return _ProofResult(_ProofVerdict.PROVED_TRUE, sp.S.true)
    if parameter_lower is None:
        return _ProofResult(
            _ProofVerdict.UNKNOWN,
            error="unsupported parameter-domain constraint",
        )
    counterexample = (
        sp.StrictGreaterThan(parameter, parameter_lower),
        sp.LessThan(expression, lower),
    )
    try:
        reduced = sp.reduce_inequalities(counterexample, parameter)
    except (NotImplementedError, TypeError, ValueError) as exc:
        return _ProofResult(
            _ProofVerdict.UNKNOWN,
            error=f"{type(exc).__name__}: {exc}",
        )
    return _ProofResult(
        (
            _ProofVerdict.PROVED_TRUE
            if reduced is sp.S.false
            else _ProofVerdict.PROVED_FALSE
        ),
        reduced,
    )


def _minimum_with_dynamic_domain(
    *,
    interior_minimum: sp.Expr,
    dynamic_expression: sp.Expr,
    target_constraint: dict[str, sp.Expr | str],
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
) -> tuple[sp.Expr, sp.Expr, sp.Expr | None]:
    """Represent only minimum values that are attained in the moving domain.

    A line-distance calculation is valid only while its perpendicular foot
    belongs to the declared moving-point ray.  For a strict lower-bound domain,
    the excluded endpoint may determine an infimum but can never determine a
    minimum.  Keep the interior branch guarded by its attainment condition and
    do not publish the endpoint value as a minimum branch.
    """

    if str(target_constraint.get("operator", "")) != ">":
        raise method_precondition_failed(
            "conditional weighted-path attainment requires a lower-bound moving domain",
            role="dynamic_parameter",
            observed={"operator": target_constraint.get("operator")},
            repair_action="choose_applicable_weighted_path_capability",
        )
    lower = target_constraint.get("value")
    if not isinstance(lower, sp.Basic):
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            "dynamic constraint reached weighted kernel without a canonical bound",
            category="configuration",
            retryability="configuration",
            arg_name="dynamic_constraint",
            role="dynamic_parameter_domain",
            repair_action="fix_runtime_contract",
        )
    domain_proof = _prove_constraint_on_parameter_domain(
        dynamic_expression,
        target_constraint=target_constraint,
        parameter=parameter,
        parameter_constraint=parameter_constraint,
    )
    if domain_proof.verdict == _ProofVerdict.UNKNOWN:
        _raise_symbolic_proof_inconclusive(
            operation="domain_implication",
            expressions=(sp.StrictGreaterThan(dynamic_expression, lower),),
            parameter=parameter,
            parameter_constraint=parameter_constraint,
            proof=domain_proof,
        )
    if domain_proof.verdict == _ProofVerdict.PROVED_TRUE:
        return sp.simplify(interior_minimum), sp.S.true, None
    attainment_condition = sp.StrictGreaterThan(
        sp.simplify(dynamic_expression),
        lower,
    )
    solution_proof = _conditions_have_solution(
        (attainment_condition,),
        parameter=parameter,
        parameter_constraint=parameter_constraint,
    )
    if solution_proof.verdict == _ProofVerdict.UNKNOWN:
        _raise_symbolic_proof_inconclusive(
            operation="satisfiability",
            expressions=(attainment_condition,),
            parameter=parameter,
            parameter_constraint=parameter_constraint,
            proof=solution_proof,
        )
    if solution_proof.verdict == _ProofVerdict.PROVED_FALSE:
        raise method_precondition_failed(
            "the weighted-path interior equality state is unreachable in the parameter domain",
            role="dynamic_parameter",
            observed={
                "dynamic_parameter_expression": str(dynamic_expression),
                "attainment_condition": str(attainment_condition),
            },
            repair_action="choose_applicable_weighted_path_capability",
        )
    return (
        sp.Piecewise(
            (sp.simplify(interior_minimum), attainment_condition),
        ),
        attainment_condition,
        None,
    )


def _conditions_have_solution(
    conditions: tuple[sp.Expr, ...],
    *,
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
) -> _ProofResult:
    domain: list[sp.Expr] = list(conditions)
    lower = _constraint_lower_bound(parameter_constraint)
    if lower is not None:
        domain.append(sp.StrictGreaterThan(parameter, lower))
    try:
        reduced = sp.reduce_inequalities(domain, parameter)
    except (NotImplementedError, TypeError, ValueError) as exc:
        return _ProofResult(
            _ProofVerdict.UNKNOWN,
            error=f"{type(exc).__name__}: {exc}",
        )
    return _ProofResult(
        (
            _ProofVerdict.PROVED_FALSE
            if reduced is sp.S.false
            else _ProofVerdict.PROVED_TRUE
        ),
        reduced,
    )


def _raise_symbolic_proof_inconclusive(
    *,
    operation: str,
    expressions: tuple[sp.Expr, ...],
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
    proof: _ProofResult,
) -> None:
    raise StatelessMethodError(
        "functional.weighted_path_symbolic_proof_inconclusive",
        "the weighted-path kernel could not prove a required domain statement",
        category="configuration",
        retryability="configuration",
        role="weighted_path_domain_proof",
        observed={
            "operation": operation,
            "expressions": [str(item) for item in expressions],
            "parameter": str(parameter),
            "parameter_constraint": {
                key: str(value) for key, value in parameter_constraint.items()
            },
            "proof_error": proof.error,
        },
        repair_action="extend_weighted_path_symbolic_prover",
    )


def _constraint_branch_is_represented(
    candidate: _WeightedOrientationCandidate,
    *,
    target_constraint: dict[str, sp.Expr | str],
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
) -> bool:
    del parameter, parameter_constraint
    if candidate.attainment_condition is sp.S.true:
        return (
            candidate.boundary_minimum_expression is None
            and not isinstance(candidate.minimum_expression, sp.Piecewise)
        )
    if str(target_constraint.get("operator", "")) == ">":
        return (
            candidate.boundary_minimum_expression is None
            and candidate.attainment_condition is not sp.S.false
            and isinstance(candidate.minimum_expression, sp.Piecewise)
            and len(candidate.minimum_expression.args) == 1
        )
    return (
        candidate.boundary_minimum_expression is not None
        and candidate.attainment_condition is not sp.S.false
        and isinstance(candidate.minimum_expression, sp.Piecewise)
    )


SPEC = MethodSpecSource(
    method_cls=WeightedAxisPathMinimumMethod,
    title="加权轴上路径最值内核",
    summary=(
        "Given a two-term weighted path with one shared axis moving point, "
        "resolve the registered auxiliary-triangle geometry internally, prove "
        "where the straightening equality state is reachable in the declared "
        "moving domain, and return the minimum expression only on those "
        "attained parameter branches."
    ),
    solves=("derive_weighted_axis_path_minimum",),
    inputs={
        "path_condition": {"type": "Condition", "required": True},
        "fixed_point": {"type": "Point", "required": True},
        "curve_point": {"type": "Point", "required": True},
        "moving_point": {"type": "Point", "required": True},
        "moving_point_ref": {"type": "PointRef", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "dynamic_parameter": {"type": "Symbol", "required": True},
        "parameter_constraint": {"type": "Constraint", "required": True},
        "dynamic_constraint": {"type": "Constraint", "required": True},
    },
    input_views=declare_input_views(
        immutable_value=(
            "path_condition",
            "parameter_constraint",
            "dynamic_constraint",
        ),
        latest_state=("fixed_point", "curve_point", "moving_point"),
        identity=("moving_point_ref", "parameter", "dynamic_parameter"),
    ),
    outputs={
        "minimum_expression": "MinimumExpression",
        "evidence": "PathWitness",
    },
    internal_outputs=("evidence",),
    scalar_result_forms={
        "minimum_expression": ScalarResultFormSpec(
            possible_forms=("open_expression", "closed_value"),
            description=(
                "仍依赖主参数时为 open_expression；参数已确定且结果无自由符号时"
                "为 closed_value。"
            ),
        )
    },
    distinct_arg_groups=(("parameter", "dynamic_parameter"),),
    preconditions=(
        "path_condition contains exactly one registered non-unit weighted term and one unit term",
        "the two terms share one materialized axis moving point",
        "the curve endpoint is materialized with one primary parameter",
        "the primary and dynamic parameter domains are explicit",
    ),
    postconditions=(
        "minimum_expression contains only parameter branches where the source weighted path minimum is attained",
        "every published branch has a selected auxiliary-ray foot and original moving point that make equality reachable",
    ),
)


__all__ = ["SPEC", "WeightedAxisPathMinimumMethod"]
