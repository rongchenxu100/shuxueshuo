"""Exact, side-effect-free search for the equal-length ray path Macro."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    PathMinimumWitness,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRuntimeSearchReport,
)

Point = tuple[sp.Expr, sp.Expr]


class EqualLengthRayPathSearchError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryability: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryability = retryability
        self.details = dict(details or {})


@dataclass(frozen=True)
class PathAttainmentCandidate:
    candidate_id: str
    strategy: str
    point: Point
    expression: sp.Expr
    feasible: bool
    checks: tuple[Mapping[str, Any], ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "strategy": self.strategy,
            "point": [_expression_text(item) for item in self.point],
            "expression": _expression_text(self.expression),
            "feasible": self.feasible,
            "checks": [_json_safe(item) for item in self.checks],
        }


@dataclass(frozen=True)
class SegmentPathMinimumSearchResult:
    winner: PathAttainmentCandidate
    candidates: tuple[PathAttainmentCandidate, ...]


def search_segment_path_minimum(
    *,
    fixed_point: Point,
    auxiliary_point: Point,
    segment_start: Point,
    segment_end: Point,
    assumptions: Sequence[sp.Basic] = (),
) -> SegmentPathMinimumSearchResult:
    """Minimize ``fixed-M + M-auxiliary`` for M on a closed segment."""

    fixed_point = _refine_point(fixed_point, assumptions)
    auxiliary_point = _refine_point(auxiliary_point, assumptions)
    segment_start = _refine_point(segment_start, assumptions)
    segment_end = _refine_point(segment_end, assumptions)
    candidates: list[PathAttainmentCandidate] = []
    direct = _intersection_candidate(
        strategy="direct_intersection",
        line_start=fixed_point,
        line_end=auxiliary_point,
        segment_start=segment_start,
        segment_end=segment_end,
        objective_points=(fixed_point, auxiliary_point),
        assumptions=assumptions,
    )
    if direct is not None:
        candidates.append(direct)

    reflected_fixed = _reflect_point_across_line(
        fixed_point,
        segment_start,
        segment_end,
    )
    reflection = _intersection_candidate(
        strategy="reflection_straightening",
        line_start=reflected_fixed,
        line_end=auxiliary_point,
        segment_start=segment_start,
        segment_end=segment_end,
        objective_points=(fixed_point, auxiliary_point),
        assumptions=assumptions,
    )
    if reflection is not None:
        candidates.append(reflection)

    for index, point in enumerate((segment_start, segment_end)):
        expression = sp.simplify(
            _distance(fixed_point, point) + _distance(point, auxiliary_point)
        )
        candidates.append(
            _candidate(
                strategy=f"segment_endpoint_{index}",
                point=point,
                expression=expression,
                feasible=True,
                checks=(
                    {
                        "check": "point_on_closed_segment",
                        "passed": True,
                        "parameter": str(index),
                    },
                ),
            )
        )

    feasible = tuple(item for item in candidates if item.feasible)
    if not feasible:
        raise EqualLengthRayPathSearchError(
            "functional.path_minimum_attainment_unproven",
            "no path-minimum candidate has a proved legal attainment point",
            retryability="planner_repairable",
        )
    direct_candidates = tuple(
        item for item in feasible if item.strategy == "direct_intersection"
    )
    if direct_candidates:
        winner = direct_candidates[0]
    else:
        winner = _unique_proved_minimum(feasible, assumptions=assumptions)
    return SegmentPathMinimumSearchResult(
        winner=winner,
        candidates=tuple(candidates),
    )


def build_equal_length_ray_path_witness(
    *,
    step_id: str,
    report: MacroRuntimeSearchReport,
    role_points: Mapping[str, Point],
    fact_payloads: Mapping[str, Mapping[str, Any]],
    entity_payloads: Mapping[str, Mapping[str, Any]],
    auxiliary_point: Point,
    runtime_minimum_expression: Any,
    provenance_signature: str,
    assumptions: Sequence[sp.Basic] = (),
) -> PathMinimumWitness:
    """Build the authenticated theorem and attainment witness for one winner."""

    roles = {item.role: item.chosen_ref for item in report.role_resolutions}
    required_roles = {"anchor", "reference_point", "ray_point", "fixed_point"}
    if set(roles) != required_roles or not required_roles <= set(role_points):
        raise EqualLengthRayPathSearchError(
            "planner.macro_contract_invalid",
            "equal-length path winner omitted a required public role",
            retryability="configuration",
            details={"roles": sorted(roles)},
        )
    segment_payload = fact_payloads["point_on_segment"]
    ray_payload = fact_payloads["point_on_ray"]
    equal_payload = fact_payloads["equal_length_condition"]
    target_payload = fact_payloads["path_minimum_target"]
    segment_entity = entity_payloads[str(segment_payload["segment"])]
    endpoints = tuple(str(item) for item in segment_entity.get("endpoints", ()))
    if len(endpoints) != 2:
        raise EqualLengthRayPathSearchError(
            "planner.macro_contract_invalid",
            "point-on-segment Fact does not identify one closed segment",
            retryability="configuration",
        )
    anchor = role_points["anchor"]
    reference = role_points["reference_point"]
    ray_point = role_points["ray_point"]
    fixed = role_points["fixed_point"]
    _verify_auxiliary_construction(
        anchor=anchor,
        reference=reference,
        ray_point=ray_point,
        auxiliary=auxiliary_point,
        assumptions=assumptions,
    )
    search = search_segment_path_minimum(
        fixed_point=fixed,
        auxiliary_point=auxiliary_point,
        segment_start=anchor,
        segment_end=reference,
        assumptions=assumptions,
    )
    runtime_expression = _refine_expression(
        runtime_minimum_expression,
        assumptions,
    )
    proved_expression = _refine_expression(
        search.winner.expression,
        assumptions,
    )
    if sp.simplify(runtime_expression - proved_expression) != 0:
        raise EqualLengthRayPathSearchError(
            "functional.method_result_inconsistent",
            "runtime minimum expression differs from the proved path winner",
            retryability="configuration",
            details={
                "runtime": _expression_text(runtime_expression),
                "proved": _expression_text(search.winner.expression),
            },
        )

    segment_moving = str(segment_payload.get("point", ""))
    ray_moving = str(ray_payload.get("point", ""))
    minimizing_segment_point = search.winner.point
    minimizing_ray_point = _corresponding_ray_point(
        anchor=anchor,
        ray_direction=ray_point,
        segment_point=minimizing_segment_point,
    )
    role_labels = {
        key: _object_label(value, entity_payloads)
        for key, value in roles.items()
    }
    segment_label = _object_label(segment_moving, entity_payloads)
    ray_moving_label = _object_label(ray_moving, entity_payloads)
    auxiliary_label = "G"
    original_objective = str(
        target_payload.get("path")
        or target_payload.get("expression")
        or target_payload.get("description")
        or "path minimum"
    )
    reduced_objective = (
        f"{role_labels['fixed_point']}{segment_label}+"
        f"{segment_label}{auxiliary_label}"
    )
    equivalence_proof = (
        (
            f"{_length_label(equal_payload.get('left'))}="
            f"{_length_label(equal_payload.get('right'))}"
        ),
        (
            f"{role_labels['anchor']}{role_labels['reference_point']}="
            f"{role_labels['anchor']}{auxiliary_label}"
        ),
        "the included angles are formed by the same segment and ray lines",
        (
            f"SAS proves the corresponding triangles congruent, so "
            f"{role_labels['reference_point']}{ray_moving_label}="
            f"{segment_label}{auxiliary_label}"
        ),
        f"therefore {original_objective}={reduced_objective}",
    )
    constructions = (
        {
            "kind": "equal_length_point_on_ray",
            "label": auxiliary_label,
            "anchor": role_labels["anchor"],
            "reference_point": role_labels["reference_point"],
            "ray_direction_point": role_labels["ray_point"],
            "coordinate": _point_payload(auxiliary_point),
        },
    )
    checks = tuple(
        {
            "candidate_id": item.candidate_id,
            "strategy": item.strategy,
            "feasible": item.feasible,
            "expression": _expression_text(item.expression),
            "checks": [_json_safe(check) for check in item.checks],
        }
        for item in search.candidates
    )
    return PathMinimumWitness(
        step_id=step_id,
        macro_id=report.macro_id,
        original_objective=original_objective,
        reduced_objective=reduced_objective,
        role_resolutions=report.role_resolutions,
        constructions=constructions,
        equivalence_proof=equivalence_proof,
        legal_domain=(
            f"{segment_label} lies on the closed segment through "
            f"{role_labels['anchor']} and {role_labels['reference_point']}",
            f"{ray_moving_label} lies on the positive ray from {role_labels['anchor']}",
        ),
        minimum_strategy=search.winner.strategy,
        minimum_expression=_expression_text(search.winner.expression),
        minimizing_points={
            segment_label: _point_payload(minimizing_segment_point),
            ray_moving_label: _point_payload(minimizing_ray_point),
        },
        attainment_checks=checks,
        macro_search_report=report,
        provenance_signature=provenance_signature,
    )


def build_equal_length_ray_execution_witness(
    *,
    compiled: Any,
    prepared: Any,
    report: MacroRuntimeSearchReport,
    method_results: Sequence[Any],
    handle_registry: Any,
) -> PathMinimumWitness:
    """Build execution evidence from the equal-length implementation contract.

    This adapter deliberately lives with the Macro implementation. Transaction
    execution only dispatches through the registry and has no geometry-specific
    role, Fact, or witness knowledge.
    """

    role_points: dict[str, Point] = {}
    for role in ("anchor", "reference_point", "ray_point", "fixed_point"):
        value = _prepared_runtime_arg_value(prepared, role)
        if value is None:
            raise EqualLengthRayPathSearchError(
                "planner.macro_contract_invalid",
                f"equal-length path role {role} has no exact runtime Point",
                retryability="configuration",
            )
        role_points[role] = _runtime_point(value)

    auxiliary_point: Point | None = None
    minimum_expression: Any | None = None
    for result in method_results:
        method_id = str(getattr(result, "method_id", ""))
        outputs = getattr(result, "outputs", {})
        if method_id == "equal_length_ray_point" and "point" in outputs:
            auxiliary_point = _runtime_point(outputs["point"])
        if method_id == "distance_between_points" and "distance" in outputs:
            minimum_expression = getattr(outputs["distance"], "value", None)
    if auxiliary_point is None or minimum_expression is None:
        raise EqualLengthRayPathSearchError(
            "planner.macro_contract_invalid",
            "equal-length path Macro omitted its internal winner outputs",
            retryability="configuration",
        )

    fact_payloads: dict[str, Mapping[str, Any]] = {}
    for arg_name in (
        "path_minimum_target",
        "equal_length_condition",
        "point_on_segment",
        "point_on_ray",
    ):
        values = prepared.reconciliation.resolved_args.get(arg_name, ())
        if len(values) != 1:
            raise EqualLengthRayPathSearchError(
                "planner.macro_contract_invalid",
                f"equal-length path Macro requires one {arg_name} Fact",
                retryability="configuration",
            )
        try:
            fact_payloads[arg_name] = handle_registry.fact_payloads[
                values[0].handle
            ]
        except KeyError as exc:
            raise EqualLengthRayPathSearchError(
                "planner.macro_contract_invalid",
                f"equal-length path Fact {arg_name} is absent from ProblemIR",
                retryability="configuration",
            ) from exc
    assumptions = _problem_symbol_assumptions(
        handle_registry,
        values=(
            *role_points.values(),
            auxiliary_point,
            minimum_expression,
        ),
    )
    provenance = compiled.problem_source_provenance
    provenance_signature = (
        provenance.semantic_signature()
        if provenance is not None
        else stable_hash(
            {
                "call_id": compiled.call_id,
                "search_signature": report.search_signature,
            }
        )
    )
    return build_equal_length_ray_path_witness(
        step_id=compiled.call_id,
        report=report,
        role_points=role_points,
        fact_payloads=fact_payloads,
        entity_payloads=handle_registry.entity_payloads,
        auxiliary_point=auxiliary_point,
        runtime_minimum_expression=minimum_expression,
        provenance_signature=provenance_signature,
        assumptions=assumptions,
    )


def _prepared_runtime_arg_value(prepared: Any, arg_name: str) -> Any | None:
    candidates = tuple(
        item.runtime_value
        for item in prepared.arg_bindings
        if item.logical_binding.key.arg_name == arg_name
        and item.runtime_value is not None
    )
    if len(candidates) == 1:
        return candidates[0]
    state_values = tuple(
        item.runtime_value
        for item in prepared.state_reads
        if item.arg_name == arg_name
    )
    return state_values[0] if len(state_values) == 1 else None


def _runtime_point(value: Any) -> Point:
    payload = getattr(value, "value", value)
    if not isinstance(payload, (tuple, list)) or len(payload) != 2:
        raise EqualLengthRayPathSearchError(
            "planner.macro_contract_invalid",
            "equal-length path role did not materialize as one Point",
            retryability="configuration",
        )
    return sp.sympify(payload[0]), sp.sympify(payload[1])


def _problem_symbol_assumptions(
    handle_registry: Any,
    *,
    values: Sequence[Any],
) -> tuple[sp.Basic, ...]:
    symbols = {
        symbol.name: symbol
        for value in values
        for symbol in _runtime_free_symbols_for_assumptions(value)
    }
    result: list[sp.Basic] = []
    for payload in handle_registry.fact_payloads.values():
        if payload.get("type") != "symbol_constraint":
            continue
        subject = payload.get("subject")
        if not isinstance(subject, str):
            continue
        symbol = symbols.get(subject.rsplit(":", 1)[-1])
        if symbol is None:
            continue
        operator = payload.get("operator")
        try:
            boundary = sp.sympify(payload.get("value"))
        except (TypeError, ValueError):
            continue
        if boundary != 0:
            continue
        if operator == ">":
            result.append(sp.Q.positive(symbol))
        elif operator == ">=":
            result.append(sp.Q.nonnegative(symbol))
        elif operator == "<":
            result.append(sp.Q.negative(symbol))
        elif operator == "<=":
            result.append(sp.Q.nonpositive(symbol))
    return tuple(result)


def _runtime_free_symbols_for_assumptions(value: Any) -> tuple[sp.Symbol, ...]:
    payload = getattr(value, "value", value)
    if isinstance(payload, sp.Basic):
        return tuple(payload.free_symbols)
    if isinstance(payload, Mapping):
        return tuple(
            dict.fromkeys(
                symbol
                for child in payload.values()
                for symbol in _runtime_free_symbols_for_assumptions(child)
            )
        )
    if isinstance(payload, (tuple, list)):
        return tuple(
            dict.fromkeys(
                symbol
                for child in payload
                for symbol in _runtime_free_symbols_for_assumptions(child)
            )
        )
    return ()


def _intersection_candidate(
    *,
    strategy: str,
    line_start: Point,
    line_end: Point,
    segment_start: Point,
    segment_end: Point,
    objective_points: tuple[Point, Point],
    assumptions: Sequence[sp.Basic],
) -> PathAttainmentCandidate | None:
    t, u = sp.symbols("_segment_t _line_u", real=True)
    segment = _affine(segment_start, segment_end, t)
    line = _affine(line_start, line_end, u)
    solutions = sp.solve(
        (sp.Eq(segment[0], line[0]), sp.Eq(segment[1], line[1])),
        (t, u),
        dict=True,
    )
    if len(solutions) != 1 or t not in solutions[0] or u not in solutions[0]:
        return None
    segment_parameter = sp.simplify(solutions[0][t])
    line_parameter = sp.simplify(solutions[0][u])
    point = tuple(sp.simplify(item.subs(t, segment_parameter)) for item in segment)
    segment_ok = _prove_unit_interval(segment_parameter, assumptions)
    line_ok = _prove_unit_interval(line_parameter, assumptions)
    expression = sp.simplify(
        _distance(line_start, line_end)
        if strategy in {"direct_intersection", "reflection_straightening"}
        else (
            _distance(objective_points[0], point)
            + _distance(point, objective_points[1])
        )
    )
    return _candidate(
        strategy=strategy,
        point=(point[0], point[1]),
        expression=expression,
        feasible=segment_ok and line_ok,
        checks=(
            {
                "check": "intersection_on_segment",
                "parameter": _expression_text(segment_parameter),
                "passed": segment_ok,
            },
            {
                "check": "straightened_line_attainment",
                "parameter": _expression_text(line_parameter),
                "passed": line_ok,
            },
        ),
    )


def _unique_proved_minimum(
    candidates: Sequence[PathAttainmentCandidate],
    *,
    assumptions: Sequence[sp.Basic],
) -> PathAttainmentCandidate:
    winners: list[PathAttainmentCandidate] = []
    for candidate in candidates:
        if all(
            _prove_nonnegative(
                other.expression - candidate.expression,
                assumptions,
            )
            for other in candidates
        ):
            winners.append(candidate)
    if not winners:
        raise EqualLengthRayPathSearchError(
            "functional.path_minimum_attainment_unproven",
            "parameter branches prevent a proved comparison of path candidates",
            retryability="planner_repairable",
            details={
                "candidates": [item.to_payload() for item in candidates],
            },
        )
    expressions = {
        sp.srepr(sp.simplify(item.expression)) for item in winners
    }
    if len(expressions) != 1:
        raise EqualLengthRayPathSearchError(
            "functional.macro_search_ambiguous",
            "multiple non-equivalent path minima remain valid",
            retryability="planner_repairable",
            details={"candidates": [item.to_payload() for item in winners]},
        )
    return min(winners, key=lambda item: item.candidate_id)


def _verify_auxiliary_construction(
    *,
    anchor: Point,
    reference: Point,
    ray_point: Point,
    auxiliary: Point,
    assumptions: Sequence[sp.Basic],
) -> None:
    direction = _subtract(ray_point, anchor)
    auxiliary_direction = _subtract(auxiliary, anchor)
    cross = sp.simplify(
        direction[0] * auxiliary_direction[1]
        - direction[1] * auxiliary_direction[0]
    )
    dot = sp.simplify(
        direction[0] * auxiliary_direction[0]
        + direction[1] * auxiliary_direction[1]
    )
    length_drift = sp.simplify(
        _distance_squared(anchor, auxiliary)
        - _distance_squared(anchor, reference)
    )
    if (
        cross != 0
        or length_drift != 0
        or not _prove_nonnegative(dot, assumptions)
    ):
        raise EqualLengthRayPathSearchError(
            "functional.method_check_failed",
            "auxiliary point failed ray direction or equal-length checks",
            retryability="planner_repairable",
            details={
                "cross": _expression_text(cross),
                "dot": _expression_text(dot),
                "length_drift": _expression_text(length_drift),
            },
        )


def _corresponding_ray_point(
    *,
    anchor: Point,
    ray_direction: Point,
    segment_point: Point,
) -> Point:
    direction = _subtract(ray_direction, anchor)
    direction_length = _distance(anchor, ray_direction)
    segment_length = _distance(anchor, segment_point)
    scale = sp.simplify(segment_length / direction_length)
    return (
        sp.simplify(anchor[0] + direction[0] * scale),
        sp.simplify(anchor[1] + direction[1] * scale),
    )


def _reflect_point_across_line(point: Point, start: Point, end: Point) -> Point:
    direction = _subtract(end, start)
    denominator = sp.simplify(direction[0] ** 2 + direction[1] ** 2)
    if denominator == 0:
        raise EqualLengthRayPathSearchError(
            "planner.macro_contract_invalid",
            "path segment endpoints are coincident",
            retryability="configuration",
        )
    offset = _subtract(point, start)
    scale = sp.simplify(
        (offset[0] * direction[0] + offset[1] * direction[1]) / denominator
    )
    projection = (
        sp.simplify(start[0] + scale * direction[0]),
        sp.simplify(start[1] + scale * direction[1]),
    )
    return (
        sp.simplify(2 * projection[0] - point[0]),
        sp.simplify(2 * projection[1] - point[1]),
    )


def _candidate(
    *,
    strategy: str,
    point: Point,
    expression: sp.Expr,
    feasible: bool,
    checks: tuple[Mapping[str, Any], ...],
) -> PathAttainmentCandidate:
    payload = {
        "strategy": strategy,
        "point": _point_payload(point),
        "expression": _expression_text(expression),
    }
    return PathAttainmentCandidate(
        candidate_id=stable_hash(payload),
        strategy=strategy,
        point=point,
        expression=expression,
        feasible=feasible,
        checks=checks,
    )


def _prove_unit_interval(
    value: sp.Expr,
    assumptions: Sequence[sp.Basic],
) -> bool:
    value = _refine_expression(value, assumptions)
    return _prove_nonnegative(value, assumptions) and _prove_nonnegative(
        1 - value,
        assumptions,
    )


def _prove_nonnegative(
    value: sp.Expr,
    assumptions: Sequence[sp.Basic] = (),
) -> bool:
    value = _refine_expression(value, assumptions)
    if value == 0:
        return True
    with sp.assuming(*assumptions):
        asked = sp.ask(sp.Q.nonnegative(value))
    if asked is not None:
        return bool(asked)
    numerator, denominator = sp.together(value).as_numer_denom()
    with sp.assuming(*assumptions):
        numerator_nonnegative = sp.ask(sp.Q.nonnegative(numerator))
        denominator_positive = sp.ask(sp.Q.positive(denominator))
    if numerator_nonnegative is True and denominator_positive is True:
        return True
    with sp.assuming(*assumptions):
        numerator_nonpositive = sp.ask(sp.Q.nonpositive(numerator))
        denominator_negative = sp.ask(sp.Q.negative(denominator))
    return numerator_nonpositive is True and denominator_negative is True


def _distance(left: Point, right: Point) -> sp.Expr:
    return sp.sqrt(_distance_squared(left, right))


def _distance_squared(left: Point, right: Point) -> sp.Expr:
    return sp.simplify((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2)


def _subtract(left: Point, right: Point) -> Point:
    return sp.simplify(left[0] - right[0]), sp.simplify(left[1] - right[1])


def _affine(start: Point, end: Point, parameter: sp.Expr) -> Point:
    return (
        sp.simplify(start[0] + parameter * (end[0] - start[0])),
        sp.simplify(start[1] + parameter * (end[1] - start[1])),
    )


def _as_expression(value: Any) -> sp.Expr:
    if isinstance(value, sp.Basic):
        return value
    return sp.sympify(value)


def _refine_expression(
    value: Any,
    assumptions: Sequence[sp.Basic],
) -> sp.Expr:
    expression = _as_expression(value)
    if assumptions:
        expression = sp.refine(expression, sp.And(*assumptions))
    return sp.simplify(expression)


def _refine_point(
    point: Point,
    assumptions: Sequence[sp.Basic],
) -> Point:
    return (
        _refine_expression(point[0], assumptions),
        _refine_expression(point[1], assumptions),
    )


def _expression_text(value: Any) -> str:
    return sp.sstr(sp.simplify(_as_expression(value)))


def _point_payload(point: Point) -> list[str]:
    return [_expression_text(point[0]), _expression_text(point[1])]


def _object_label(
    handle: str,
    entity_payloads: Mapping[str, Mapping[str, Any]],
) -> str:
    payload = entity_payloads.get(handle, {})
    name = payload.get("name")
    if isinstance(name, str) and name:
        return name
    return handle.rsplit(":", 1)[-1]


def _length_label(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "".join(str(item).rsplit(":", 1)[-1] for item in value)
    return "length"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, sp.Basic):
        return _expression_text(value)
    return value


__all__ = [
    "EqualLengthRayPathSearchError",
    "PathAttainmentCandidate",
    "SegmentPathMinimumSearchResult",
    "build_equal_length_ray_execution_witness",
    "build_equal_length_ray_path_witness",
    "search_segment_path_minimum",
]
