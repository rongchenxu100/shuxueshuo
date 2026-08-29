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
    MethodExplanationSpec,
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
        evidence = {
            "original_objective": str(path_condition.get("path", "weighted path")),
            "reduced_objective": str(transformation["transformed_path"]),
            "weight": kernel.sstr(sp.sympify(transformation["scale"])),
            "geometry_profile_id": str(transformation["geometry_profile_id"]),
            "orientation_sign": winner.orientation_sign,
            "equivalence_proof": (
                str(transformation["reason"]),
                (
                    f"{transformation['original_path']}="
                    f"{transformation['transformed_path']}"
                ),
            ),
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
                    "取等域已由完整表达式或分段边界显式表示",
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
                    "求完整最小值表达式",
                    "在内部构造与权重匹配的辅助三角形，拉直路径并验证取等状态覆盖声明定义域。",
                    (
                        f"权重={evidence['weight']}，"
                        f"构造={evidence['geometry_profile_id']}"
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
        curve_point=curve_point,
        fixed_point=fixed_point,
        moving_point=moving_point,
        dynamic_parameter=dynamic_parameter,
        target_constraint=dynamic_constraint,
        parameter=parameter,
        parameter_constraint=parameter_constraint,
        weight=sp.sympify(
            transform.outputs["path_transformation"].value["weight"]
        ),
        kernel=kernel,
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
    curve_point: Point,
    fixed_point: Point,
    moving_point: Point,
    dynamic_parameter: sp.Symbol,
    target_constraint: dict[str, sp.Expr | str],
    parameter: sp.Symbol,
    parameter_constraint: dict[str, sp.Expr | str],
    weight: sp.Expr,
    kernel: SympyKernel,
) -> tuple[sp.Expr, sp.Expr, sp.Expr | None]:
    """Represent an interior foot and a possible axis-boundary branch.

    The old public two-step chain always returned the distance to the auxiliary
    *line*.  For the Hexi profile that foot corresponds to ``n=b/2-1/4`` and
    is on the positive-axis ray only when ``b>1/2``.  The atomic Macro must not
    publish that conditional expression as a global minimum, so it closes the
    one-dimensional convex objective with the declared lower endpoint.
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
    boundary_point = tuple(
        sp.simplify(sp.sympify(item).subs(dynamic_parameter, lower))
        for item in moving_point
    )
    boundary_minimum = sp.simplify(
        weight * kernel.distance(curve_point, boundary_point)
        + kernel.distance(fixed_point, boundary_point)
    )
    return (
        sp.Piecewise(
            (sp.simplify(interior_minimum), attainment_condition),
            (boundary_minimum, True),
        ),
        attainment_condition,
        boundary_minimum,
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
    del target_constraint, parameter, parameter_constraint
    if candidate.attainment_condition is sp.S.true:
        return (
            candidate.boundary_minimum_expression is None
            and not isinstance(candidate.minimum_expression, sp.Piecewise)
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
        "that the straightening equality state is reachable in the declared "
        "domains, and return only the minimum expression."
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
        "minimum_expression equals the source weighted path minimum",
        "the selected auxiliary-ray foot and original moving point make equality reachable",
    ),
    explanation=MethodExplanationSpec(
        role_schema={
            "original_path": "题设加权路径。",
            "weighted_triangle": "把普通轴上线段换成同倍率辅助线段的直角三角形。",
            "auxiliary_locus": "辅助点的合法射线轨迹。",
            "minimum_expression": "在合法取等状态下得到的路径最小值表达式。",
        },
        student_goal_template="用辅助三角形把加权路径化为可拉直折线并求最小值。",
        student_title_template="辅助三角形转化加权路径",
        derive_templates=(
            "构造 {weighted_triangle}，把 {original_path} 化为同倍率普通折线。",
            "沿 {auxiliary_locus} 拉直折线并验证取等状态合法。",
            "得到最小值表达式 {minimum_expression}。",
        ),
        box_templates=("{minimum_expression}",),
        role_binder_id="weighted_axis_path_minimum",
    ),
)


__all__ = ["SPEC", "WeightedAxisPathMinimumMethod"]
