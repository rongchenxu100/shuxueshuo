"""Method explanation role binders."""

from __future__ import annotations

import re
from typing import Any, Protocol

import sympy as sp

from shuxueshuo_server.solver.contracts import MethodExplanationSpec
from shuxueshuo_server.solver.student_display import student_math_display as _student_expr

from ..models import ExplanationSnapshot, LessonCandidateGroup
from .common import (
    after_equals,
    handle_name,
    minimum_expression_from_conclusion,
    parameter_assignment,
    roles_from_trace,
)


class MethodRoleBinder(Protocol):
    """Bind method explanation roles from an invocation group and snapshot."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        ...


class GenericTraceMethodRoleBinder:
    """Fallback binder: expose trace fragments as simple roles."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        trace_roles = roles_from_trace(group)
        return {
            role: trace_roles.get(role, "")
            for role in explanation.role_schema
            if trace_roles.get(role, "")
        } or trace_roles


class RoleNameRegistryMethodRoleBinder:
    """Role-name based binder used by existing method explanation specs."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        trace_roles = roles_from_trace(group)
        roles: dict[str, Any] = {}
        for role in explanation.role_schema:
            binder = _METHOD_ROLE_BINDERS.get(role)
            value = trace_roles.get(role, "") if binder is None else binder(
                method_id,
                trace_roles,
                group,
                snapshot,
            )
            if value not in ("", None):
                roles[role] = value
        return roles or trace_roles


class DistanceBetweenPointsRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Named binder for distance_between_points; delegates to role-name binding."""


class LineParabolaSecondIntersectionRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind line expression and target point for a line-parabola intersection step."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        trace_roles = roles_from_trace(group)
        line_points = str(roles.get("line_points") or "两个已知点")
        parabola = _student_parabola_text(str(roles.get("parabola") or "抛物线"))
        known_point = str(roles.get("known_point") or "已知交点")
        target_point = _compact_point_text(str(roles.get("target_point") or trace_roles.get("conclusion", "")))
        if target_point:
            roles["target_point"] = target_point
        line_name = _line_name(known_point, target_point)
        line_expression = _line_expression_from_trace(trace_roles.get("calculation", ""), line_name)
        if line_expression:
            roles["line_expression"] = line_expression
        return roles


class QuadraticVertexPointRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind vertex-form parabola and vertex point."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        expression = _read_value_by_type(group.step, snapshot, "Parabola")
        vertex_form = _completed_square_expression(expression) if expression else ""
        if vertex_form:
            roles["parabola_vertex_form"] = f"y＝{vertex_form}"
        elif expression:
            roles["parabola_vertex_form"] = f"y＝{_quadratic_expression_display(expression)}"
        point = _point_conclusion_display(roles_from_trace(group).get("conclusion", ""))
        if point:
            roles["vertex_point"] = point
        return roles


class QuadraticXAxisInterceptPointRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind y=0 equation and the selected x-axis intercept."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        expression = _read_value_by_type(group.step, snapshot, "Parabola")
        if expression:
            roles["parabola"] = f"y＝{_quadratic_expression_display(expression)}"
            roles["intercept_equation"] = f"{_quadratic_expression_display(expression)}＝0"
        point = _point_conclusion_display(roles_from_trace(group).get("conclusion", ""))
        if point:
            roles["target_point"] = point
        return roles


class QuadraticAxisParameterizedPointRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind a point on the symmetry axis as a student-facing parameter point."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        point = _axis_parameterized_point_from_trace(roles_from_trace(group).get("conclusion", ""))
        if point:
            target, axis_x, display = point
            roles["target"] = target
            roles["axis_equation"] = f"x＝{axis_x}"
            roles["parameterized_point"] = display
        return roles


class QuadraticAxisXInterceptPointRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind the symmetry-axis x-intercept point."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        trace_roles = roles_from_trace(group)
        axis_x = _axis_x_from_calculation(trace_roles.get("calculation", ""))
        if axis_x:
            roles["axis_equation"] = f"x＝{axis_x}"
        point = _point_conclusion_display(trace_roles.get("conclusion", ""))
        if point:
            roles["axis_point"] = point
            label = _point_label_from_display(point)
            if label:
                roles["target_label"] = label
        if not roles.get("target_label"):
            target_label = _point_label_from_step_target(group.step)
            if target_label:
                roles["target_label"] = target_label
        return roles


class QuadraticFromConstraintsRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind student-facing coefficient substitution and vertex form."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        trace_roles = roles_from_trace(group)
        calculation = trace_roles.get("calculation", "")
        conclusion = trace_roles.get("conclusion", "")
        constraints = _coefficient_substitution_text(calculation)
        if constraints:
            roles["constraints"] = constraints
        expression = _parabola_expression_from_conclusion(conclusion)
        if expression:
            roles["result_parabola"] = _quadratic_expression_display(expression)
            roles["parabola_title_action"] = _quadratic_title_action(expression)
            completed = _completed_square_expression(expression)
            result = str(roles["result_parabola"])
            if completed and completed != result:
                roles["completed_square_suffix"] = f"＝{completed}"
            else:
                roles["completed_square_suffix"] = ""
        else:
            roles.setdefault("completed_square_suffix", "")
            roles.setdefault("parabola_title_action", "求")
        curve_point_derivation = _quadratic_curve_point_derivation(
            group=group,
            snapshot=snapshot,
            calculation=calculation,
            result_parabola=str(roles.get("result_parabola") or ""),
            completed_square_suffix=str(roles.get("completed_square_suffix") or ""),
        )
        if curve_point_derivation:
            roles["derive_items"] = curve_point_derivation
        return roles


class ParameterFromExpressionValueRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind an expression-value equation and the solved parameter."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        expression = _read_value_by_type(group.step, snapshot, "MinimumExpression")
        target_value = _condition_value_for_step(group.step, snapshot)
        parameter, parameter_value = parameter_assignment(
            roles_from_trace(group).get("conclusion", "")
            or roles_from_trace(group).get("calculation", "")
        )
        if expression:
            roles["expression"] = _student_expr(expression, fullwidth_operators=True)
        if target_value:
            roles["target_value"] = _student_expr(target_value, fullwidth_operators=True)
        if parameter:
            roles["parameter"] = parameter
        if parameter_value:
            roles["parameter_value"] = _student_expr(parameter_value, fullwidth_operators=True)
        return roles


class EvaluatePointAtParameterRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind a parameter substitution into a point coordinate."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        label = _produced_point_label(group.step) or _point_label_from_step_target(group.step)
        source_pair = _source_point_pair_for_label(label, group.step, snapshot) if label else None
        evaluated_pair = _runtime_point_for_step(group.step_id, snapshot)
        if label and source_pair is not None:
            roles["source_point"] = _student_point_display(label, source_pair)
        if label and evaluated_pair is not None:
            roles["evaluated_point"] = _student_point_display(label, evaluated_pair)
        parameter, parameter_value = parameter_assignment(
            roles_from_trace(group).get("calculation", "")
            or roles_from_trace(group).get("conclusion", "")
        )
        if parameter:
            roles["parameter"] = parameter
        if parameter_value:
            roles["parameter_value"] = _student_expr(parameter_value, fullwidth_operators=True)
        return roles


class SquareAdjacentVertexRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind a coordinate-difference proof for a square adjacent vertex."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        detail = _square_adjacent_detail(group, snapshot)
        roles.update({key: value for key, value in detail.items() if value not in ("", None)})
        trace_target = _point_conclusion_display(roles_from_trace(group).get("conclusion", ""))
        if trace_target and not roles.get("target_point"):
            roles["target_point"] = trace_target
        return roles


class PointCandidatesFromCurveConditionRoleBinder(RoleNameRegistryMethodRoleBinder):
    """Bind the algebra that turns a curve-point condition into point candidates."""

    def bind(
        self,
        *,
        method_id: str,
        explanation: MethodExplanationSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        roles = super().bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        detail = _curve_point_candidate_detail(group, snapshot)
        roles.update({key: value for key, value in detail.items() if value not in ("", None)})
        return roles


def method_role_binders() -> dict[str, MethodRoleBinder]:
    role_name = RoleNameRegistryMethodRoleBinder()
    return {
        "generic_trace": GenericTraceMethodRoleBinder(),
        "role_name_registry": role_name,
        "quadratic_vertex_point": QuadraticVertexPointRoleBinder(),
        "quadratic_x_axis_intercept_point": QuadraticXAxisInterceptPointRoleBinder(),
        "quadratic_axis_parameterized_point": QuadraticAxisParameterizedPointRoleBinder(),
        "quadratic_axis_x_intercept_point": QuadraticAxisXInterceptPointRoleBinder(),
        "quadratic_from_constraints": QuadraticFromConstraintsRoleBinder(),
        "parameter_from_expression_value": ParameterFromExpressionValueRoleBinder(),
        "evaluate_point_at_parameter": EvaluatePointAtParameterRoleBinder(),
        "distance_between_points": DistanceBetweenPointsRoleBinder(),
        "line_parabola_second_intersection_point": LineParabolaSecondIntersectionRoleBinder(),
        "square_adjacent_vertex_from_side": SquareAdjacentVertexRoleBinder(),
        "point_candidates_from_curve_point_condition": PointCandidatesFromCurveConditionRoleBinder(),
    }


def _student_named_label(label: str) -> str:
    return str(label).replace("_prime", "′")


def _student_segment_name(raw: str) -> str:
    return re.sub(r"([A-Z])_prime", r"\1′", str(raw or ""))


def _student_join_point_labels(labels: tuple[str, ...]) -> str:
    return "、".join(_student_named_label(label) for label in labels if label)


def _bind_distance_p1(
    method_id: str,
    trace_roles: dict[str, str],
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    p1, _ = _distance_points_from_group(group, snapshot)
    return p1


def _bind_distance_p2(
    method_id: str,
    trace_roles: dict[str, str],
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    _, p2 = _distance_points_from_group(group, snapshot)
    return p2


def _bind_distance_value(
    method_id: str,
    trace_roles: dict[str, str],
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    calculation = trace_roles.get("calculation", "")
    conclusion = trace_roles.get("conclusion", "")
    return after_equals(calculation) or minimum_expression_from_conclusion(conclusion) or conclusion or calculation


def _bind_known_conditions(
    method_id: str,
    trace_roles: dict[str, str],
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    return trace_roles.get("reason", "") or "题设条件"


def _bind_result_parabola(
    method_id: str,
    trace_roles: dict[str, str],
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    return trace_roles.get("conclusion", "") or trace_roles.get("calculation", "")


def _coefficient_substitution_text(calculation: str) -> str:
    parts = []
    for chunk in str(calculation).split(","):
        if "=" not in chunk:
            continue
        left, right = chunk.split("=", 1)
        left = left.strip()
        right = right.strip()
        if not left or not right:
            continue
        parts.append(f"{left}＝{_student_expr(right, fullwidth_operators=True)}")
    return "，".join(parts)


def _quadratic_curve_point_derivation(
    *,
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
    calculation: str,
    result_parabola: str,
    completed_square_suffix: str,
) -> list[str]:
    step = group.step
    curve_point = _curve_point_constraint_read(step, snapshot)
    if curve_point is None:
        return []
    label, point_pair, parabola = curve_point
    x_value, y_value = point_pair
    substituted = _quadratic_substitution_simplified_terms_display(parabola, x_value)
    try:
        rhs_value = sp.simplify(parabola.subs(sp.Symbol("x"), x_value))
        residual = sp.simplify(rhs_value - y_value)
        factored = sp.factor(residual)
    except Exception:
        return []
    relation = _coefficient_substitution_text(calculation)
    if not relation:
        return []
    items = [
        f"∵{_student_point_display(label, point_pair)} 在 y＝{_quadratic_expression_display(str(parabola))} 上",
    ]
    equation = f"{_student_square_expr(y_value)}＝{substituted}"
    factored_text = _factored_residual_display(factored, calculation)
    if factored_text and factored_text != _student_square_expr(residual):
        equation = f"{equation}＝{factored_text}"
    items.append(f"∴{equation}")
    nonzero_condition = _nonzero_condition_for_factor(factored, snapshot)
    if nonzero_condition:
        items.append(f"∵{nonzero_condition}")
    items.append(f"∴{relation}")
    if result_parabola:
        items.append(f"∴y＝{result_parabola}{completed_square_suffix}")
    return items


def _factored_residual_display(factored: sp.Expr, calculation: str) -> str:
    relation = _first_relation_from_calculation(calculation)
    if relation is not None:
        lhs_raw, rhs_raw, lhs, rhs = relation
        relation_zero = sp.simplify(rhs - lhs)
        if relation_zero != 0:
            try:
                quotient = sp.simplify(factored / relation_zero)
            except Exception:
                quotient = None
            if quotient is not None and quotient.is_Symbol:
                return f"{_student_square_expr(quotient)}({_relation_zero_display(lhs_raw, rhs_raw)})"
    return _student_square_expr(factored)


def _first_relation_from_calculation(calculation: str) -> tuple[str, str, sp.Expr, sp.Expr] | None:
    for chunk in str(calculation).split(","):
        if "=" not in chunk:
            continue
        left, right = (part.strip() for part in chunk.split("=", 1))
        if not left or not right:
            continue
        try:
            return left, right, sp.sympify(left), sp.sympify(right)
        except Exception:
            return None
    return None


def _relation_zero_display(lhs_raw: str, rhs_raw: str) -> str:
    rhs_text = _student_expr(rhs_raw, fullwidth_operators=True)
    lhs_text = _student_expr(lhs_raw, fullwidth_operators=True)
    if lhs_text.startswith("－"):
        return f"{rhs_text}＋{lhs_text.removeprefix('－')}"
    return f"{rhs_text}－{lhs_text}"


def _curve_point_constraint_read(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> tuple[str, tuple[sp.Expr, sp.Expr], sp.Expr] | None:
    parabola = _function_expression_for_step(step, snapshot)
    if parabola is None:
        return None
    coordinate_reads: list[tuple[str, tuple[sp.Expr, sp.Expr]]] = []
    curve_labels: set[str] = set()
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        fact = _fact_for_handle(handle, snapshot)
        if not isinstance(fact, dict):
            continue
        if fact.get("type") == "point_coordinate":
            label = _point_label_from_subject_or_fact(fact, snapshot)
            pair = _sympy_point_pair(fact.get("value"))
            if label and pair is not None:
                coordinate_reads.append((label, pair))
        elif fact.get("type") == "point_on_curve":
            label = _point_label_from_entity_handle_or_name(str(fact.get("point") or ""), snapshot)
            if label:
                curve_labels.add(label)
    matches = [(label, pair) for label, pair in coordinate_reads if label in curve_labels]
    if len(matches) != 1:
        return None
    label, pair = matches[0]
    return label, pair, parabola


def _fact_for_handle(handle: str, snapshot: ExplanationSnapshot) -> dict[str, Any] | None:
    fact = snapshot.fact_index.get(handle)
    if isinstance(fact, dict):
        return fact
    for item in (snapshot.problem or {}).get("facts") or ():
        if isinstance(item, dict) and str(item.get("handle") or "") == handle:
            return item
    return None


def _function_expression_for_step(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> sp.Expr | None:
    entity_by_handle = {
        str(entity.get("handle") or ""): entity
        for entity in (snapshot.problem or {}).get("entities") or ()
        if isinstance(entity, dict)
    }
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        entity = entity_by_handle.get(handle)
        if not isinstance(entity, dict):
            continue
        expression = entity.get("expression")
        if expression in (None, ""):
            continue
        try:
            return sp.sympify(str(expression), locals={"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs})
        except Exception:
            continue
    return None


def _point_label_from_subject_or_fact(
    fact: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> str:
    subject = str(fact.get("subject") or fact.get("point") or "")
    label = _point_label_from_entity_handle_or_name(subject, snapshot)
    if label:
        return label
    return _semantic_point_label(str(fact.get("name") or handle_name(str(fact.get("handle") or ""))))


def _point_label_from_entity_handle_or_name(handle: str, snapshot: ExplanationSnapshot) -> str:
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict):
            continue
        if str(entity.get("handle") or "") == handle:
            return str(entity.get("name") or "")
    return _semantic_point_label(handle_name(handle))


def _quadratic_substitution_simplified_terms_display(parabola: sp.Expr, x_arg: sp.Expr) -> str:
    x = sp.Symbol("x")
    try:
        poly = sp.Poly(parabola, x)
    except Exception:
        return _student_square_expr(parabola.subs(x, x_arg))
    if poly.degree() != 2:
        return _student_square_expr(parabola.subs(x, x_arg))
    terms = [
        sp.simplify(poly.coeff_monomial(x**2) * x_arg**2),
        sp.simplify(poly.coeff_monomial(x) * x_arg),
        sp.simplify(poly.coeff_monomial(1)),
    ]
    return _join_terms(_constant_term_display(term) for term in terms if sp.simplify(term) != 0)


def _nonzero_condition_for_factor(factored: sp.Expr, snapshot: ExplanationSnapshot) -> str:
    factors = [factor for factor, _ in sp.factor_list(factored)[1]]
    constrained_symbols = {
        str((str(fact.get("subject") or "").rsplit(":", 1)[-1] or "")).strip(): fact
        for fact in (snapshot.problem or {}).get("facts") or ()
        if isinstance(fact, dict) and fact.get("type") == "symbol_constraint"
    }
    for factor in factors:
        simplified = sp.simplify(factor)
        if not isinstance(simplified, sp.Symbol):
            continue
        fact = constrained_symbols.get(simplified.name)
        if not fact:
            continue
        operator = str(fact.get("operator") or "")
        value = str(fact.get("value") or "")
        if operator in {">", ">="} and value:
            op = "＞" if operator == ">" else "≥"
            return f"{simplified.name}{op}{_student_expr(value, fullwidth_operators=True)}"
        if operator in {"<", "<="} and value:
            op = "＜" if operator == "<" else "≤"
            return f"{simplified.name}{op}{_student_expr(value, fullwidth_operators=True)}"
    return ""


def _parabola_expression_from_conclusion(conclusion: str) -> str:
    text = str(conclusion).strip()
    if text.startswith("y="):
        return text.split("=", 1)[1].strip()
    return text


def _quadratic_expression_display(expression: str) -> str:
    try:
        x = sp.Symbol("x")
        expr = sp.sympify(str(expression))
        poly = sp.Poly(expr, x)
        if poly.degree() != 2:
            return _student_expr(expression, fullwidth_operators=True)
        a = sp.simplify(poly.coeff_monomial(x**2))
        b = sp.simplify(poly.coeff_monomial(x))
        c = sp.simplify(poly.coeff_monomial(1))
        parts = [_power_term_display(a, "x²"), _linear_term_display(b), _constant_term_display(c)]
        return _join_terms(part for part in parts if part)
    except Exception:
        return _student_expr(expression, fullwidth_operators=True)


def _quadratic_title_action(expression: str) -> str:
    try:
        x = sp.Symbol("x")
        expr = sp.sympify(str(expression))
        free_parameters = {str(symbol) for symbol in expr.free_symbols if symbol != x}
        return "化简" if free_parameters else "求"
    except Exception:
        return "求"


def _power_term_display(coefficient: sp.Expr, variable: str) -> str:
    coefficient = sp.simplify(coefficient)
    if coefficient == 0:
        return ""
    if sp.simplify(coefficient - 1) == 0:
        return variable
    if sp.simplify(coefficient + 1) == 0:
        return f"－{variable}"
    if coefficient.is_number and bool(coefficient < 0):
        return f"－{_student_expr(-coefficient, fullwidth_operators=True)}{variable}"
    return f"{_student_expr(coefficient, fullwidth_operators=True)}{variable}"


def _linear_term_display(coefficient: sp.Expr) -> str:
    coefficient = sp.simplify(coefficient)
    if coefficient == 0:
        return ""
    if sp.simplify(coefficient - 1) == 0:
        return "x"
    if sp.simplify(coefficient + 1) == 0:
        return "－x"
    if coefficient.is_number and bool(coefficient < 0):
        return f"－{_student_expr(-coefficient, fullwidth_operators=True)}x"
    text = _student_expr(coefficient, fullwidth_operators=True)
    if "＋" in text or "－" in text:
        text = f"({text})"
    return f"{text}x"


def _constant_term_display(value: sp.Expr) -> str:
    value = sp.simplify(value)
    if value == 0:
        return ""
    return _student_expr(value, fullwidth_operators=True)


def _join_terms(terms: Any) -> str:
    out = ""
    for raw in terms:
        term = str(raw)
        if not term:
            continue
        if not out:
            out = term
        elif term.startswith("－"):
            out += term
        else:
            out += f"＋{term}"
    return out


def _completed_square_expression(expression: str) -> str:
    try:
        x = sp.Symbol("x")
        expr = sp.sympify(str(expression))
        poly = sp.Poly(expr, x)
        if poly.degree() != 2:
            return ""
        a = poly.coeff_monomial(x**2)
        b = poly.coeff_monomial(x)
        h = sp.simplify(-b / (2 * a))
        k = sp.simplify(expr.subs(x, h))
        if a.free_symbols or h.free_symbols or k.free_symbols:
            return ""
        completed = sp.simplify(a * (x - h) ** 2 + k)
        if sp.expand(completed - expr) != 0:
            return ""
        return _completed_square_display(a, h, k)
    except Exception:
        return ""


def _completed_square_display(a: sp.Expr, h: sp.Expr, k: sp.Expr) -> str:
    square = _square_factor_display(a, h)
    tail = _signed_display(k)
    return f"{square}{tail}"


def _square_factor_display(a: sp.Expr, h: sp.Expr) -> str:
    inner = _shifted_x_display(h)
    if sp.simplify(a - 1) == 0:
        return f"({inner})²"
    if sp.simplify(a + 1) == 0:
        return f"－({inner})²"
    if a.is_number and bool(a < 0):
        coefficient = _student_expr(-a, fullwidth_operators=True)
        return f"－{coefficient}({inner})²"
    coefficient = _student_expr(a, fullwidth_operators=True)
    return f"{coefficient}({inner})²"


def _shifted_x_display(h: sp.Expr) -> str:
    h = sp.simplify(h)
    if sp.simplify(h) == 0:
        return "x"
    if h.is_number and bool(h > 0):
        return f"x－{_student_expr(h, fullwidth_operators=True)}"
    if h.is_number and bool(h < 0):
        return f"x＋{_student_expr(-h, fullwidth_operators=True)}"
    return f"x－({_student_expr(h, fullwidth_operators=True)})"


def _signed_display(value: sp.Expr) -> str:
    value = sp.simplify(value)
    if value == 0:
        return ""
    if value.is_number and bool(value < 0):
        return f"－{_student_expr(-value, fullwidth_operators=True)}"
    return f"＋{_student_expr(value, fullwidth_operators=True)}"


def _read_value_by_type(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
    value_type: str,
) -> str:
    direct = _read_direct_value_by_type(step, snapshot, value_type)
    if direct:
        return direct
    for handle in step.get("reads", []):
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        if not fact or fact.get("type") != value_type:
            continue
        scope_id = str(fact.get("scope_id") or "")
        source_step_id = str(fact.get("source_step_id") or "")
        value = _runtime_value_for_fact(
            snapshot,
            value_type=value_type,
            scope_id=scope_id,
            source_step_id=source_step_id,
        )
        if value:
            return value
        text = _value_from_fact_description(fact)
        if text:
            return text
    return ""


def _read_direct_value_by_type(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
    value_type: str,
) -> str:
    for handle in step.get("reads", []):
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        if fact and fact.get("type") == value_type and fact.get("value") not in (None, ""):
            return str(fact["value"])
    return ""


def _runtime_value_for_fact(
    snapshot: ExplanationSnapshot,
    *,
    value_type: str,
    scope_id: str,
    source_step_id: str,
) -> str:
    fallback = ""
    for handle, fact in snapshot.fact_index.items():
        if not str(handle).startswith("runtime:"):
            continue
        if fact.get("type") != value_type or fact.get("value") in (None, ""):
            continue
        if source_step_id and _fact_belongs_to_step(fact, source_step_id):
            return str(fact["value"])
        if scope_id and str(fact.get("scope_id") or "") == scope_id:
            fallback = str(fact["value"])
    return fallback


def _value_from_fact_description(fact: dict[str, Any]) -> str:
    description = str(fact.get("description") or "")
    if "y=" in description:
        return description.split("y=", 1)[1].strip()
    if "y =" in description:
        return description.split("y =", 1)[1].strip()
    return ""


def _condition_value_for_step(step: dict[str, Any], snapshot: ExplanationSnapshot) -> str:
    scope_id = str(step.get("scope_id") or "")
    for handle in step.get("reads", []):
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        value = _condition_value(fact)
        if value:
            return value
    for fact in snapshot.fact_index.values():
        if fact.get("type") != "Condition":
            continue
        if scope_id and str(fact.get("scope_id") or "") not in {scope_id, "problem"}:
            continue
        value = _condition_value(fact)
        if value:
            return value
    return ""


def _condition_value(fact: dict[str, Any] | None) -> str:
    if not fact:
        return ""
    value = fact.get("value")
    if isinstance(value, dict) and value.get("value") not in (None, ""):
        return str(value["value"])
    return ""


def _point_conclusion_display(text: str) -> str:
    raw = str(text).strip()
    match = re.match(r"([A-Z][A-Za-z0-9_]*)\s*=?\s*\((.*)\)$", raw)
    if not match:
        return raw
    name, body = match.groups()
    parts = [part.strip() for part in body.split(",")]
    if len(parts) != 2:
        return raw
    return f"{name}({_student_expr(parts[0], fullwidth_operators=True)},{_student_expr(parts[1], fullwidth_operators=True)})"


def _point_label_from_display(text: str) -> str:
    match = re.match(r"\s*([A-Z][A-Za-z0-9_′']*)\s*\(", str(text))
    return match.group(1) if match else ""


def _curve_point_candidate_detail(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> dict[str, str]:
    step = group.step
    target_label = _target_candidate_label(step)
    target_pair = _point_pair_for_label(target_label, step, snapshot) if target_label else None
    curve_label, curve_pair = _curve_point_read_for_candidate_step(
        step,
        snapshot,
        target_label=target_label,
    )
    parabola = _parabola_expr_for_step(step, snapshot)
    if not target_label or target_pair is None or not curve_label or curve_pair is None or parabola is None:
        return {}
    parameter = _shared_point_parameter(target_pair, curve_pair, parabola)
    if parameter is None:
        return {}
    candidates = _point_list_output_for_step(step, snapshot)
    if not candidates:
        return {}
    candidates = _sort_candidates_by_parameter(candidates, target_pair, parameter)
    parameter_values = [
        value
        for candidate in candidates
        if (value := _parameter_value_from_candidate(target_pair, candidate, parameter)) is not None
    ]
    curve_x, curve_y = curve_pair
    x_arg = sp.simplify(curve_x)
    coeffs = _condition_coefficients_for_curve_point(parabola, curve_y)
    if coeffs is None:
        return {}
    auxiliary_name = sp.Symbol("u")
    return {
        "target_label": target_label,
        "curve_kind": _curve_kind_display(parabola),
        "curve_point": _student_point_display(curve_label, curve_pair),
        "curve_equation": f"y＝{_quadratic_expression_display(str(parabola))}",
        "substitution_equation": (
            f"{_student_square_expr(curve_y)}＝{_quadratic_substitution_display(parabola, x_arg)}"
        ),
        "parameter_equation": f"{_quadratic_in_variable_display(coeffs, _student_square_expr(x_arg))}＝0",
        "auxiliary_parameter": f"u＝{_student_square_expr(x_arg)}",
        "auxiliary_equation": f"{_quadratic_in_variable_display(coeffs, 'u')}＝0",
        "auxiliary_solutions": _solutions_display("u", _solve_quadratic_coeffs(coeffs)),
        "parameter_solutions": _solutions_display(_student_square_expr(parameter), parameter_values),
        "target_candidates": " 或 ".join(_student_point_display(target_label, point) for point in candidates),
    }


def _curve_kind_display(parabola: sp.Expr | None) -> str:
    return "抛物线" if parabola is not None else "曲线"


def _target_candidate_label(step: dict[str, Any]) -> str:
    for raw in (
        str(step.get("target") or ""),
        *(str(item.get("handle") or "") for item in step.get("produces") or () if isinstance(item, dict)),
    ):
        label = _semantic_point_label(_answer_tail_name(raw))
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*", label):
            return label
    return ""


def _answer_tail_name(handle: str) -> str:
    tail = handle_name(handle)
    if "." in tail:
        tail = tail.rsplit(".", 1)[-1]
    return tail


def _curve_point_read_for_candidate_step(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
    *,
    target_label: str,
) -> tuple[str, tuple[sp.Expr, sp.Expr] | None]:
    scored: list[tuple[int, str, tuple[sp.Expr, sp.Expr]]] = []
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        if not isinstance(fact, dict) or fact.get("type") != "Point":
            continue
        label = _semantic_point_label(str(fact.get("name") or handle_name(handle)))
        if not label or label == target_label:
            continue
        pair = _point_pair_for_handle(handle, snapshot)
        if pair is None:
            continue
        score = 1
        if any(symbol.name.startswith("_axis_param_") or symbol.name == "t" for coord in pair for symbol in coord.free_symbols):
            score += 3
        if "curve" in handle or "parabola" in handle:
            score += 2
        scored.append((score, label, pair))
    if not scored:
        return "", None
    scored.sort(key=lambda item: item[0], reverse=True)
    _, label, pair = scored[0]
    return label, pair


def _parabola_expr_for_step(step: dict[str, Any], snapshot: ExplanationSnapshot) -> sp.Expr | None:
    raw = _read_value_by_type(step, snapshot, "Parabola")
    if not raw:
        return None
    try:
        return sp.sympify(str(raw), locals={"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs})
    except Exception:
        return None


def _shared_point_parameter(
    target_pair: tuple[sp.Expr, sp.Expr],
    curve_pair: tuple[sp.Expr, sp.Expr],
    parabola: sp.Expr,
) -> sp.Symbol | None:
    point_symbols = set().union(*(coord.free_symbols for coord in (*target_pair, *curve_pair)))
    curve_symbols = set(parabola.free_symbols) | {sp.Symbol("x")}
    candidates = sorted(point_symbols - curve_symbols, key=lambda symbol: symbol.name)
    if len(candidates) != 1:
        return None
    return candidates[0]


def _point_list_output_for_step(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> list[tuple[sp.Expr, sp.Expr]]:
    step_id = str(step.get("step_id") or "")
    scope_id = str(step.get("scope_id") or "")
    target_tail = handle_name(str(step.get("target") or ""))
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "PointList":
            continue
        if _fact_belongs_to_step(item, step_id) and item.get("value") not in (None, ""):
            points = _sympy_point_list(item.get("value"))
            if points:
                return points
    scored: list[tuple[int, list[tuple[sp.Expr, sp.Expr]]]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "PointList":
            continue
        points = _sympy_point_list(item.get("value"))
        if not points:
            continue
        item_handle = str(item.get("handle") or "")
        item_scope = str(item.get("scope_id") or "")
        score = 0
        if str(item.get("source_step_id") or "") == step_id:
            score += 5
        if scope_id and item_scope == scope_id:
            score += 3
        if target_tail and item_handle.endswith(f":outputs:{target_tail}"):
            score += 2
        if score > 0:
            scored.append((score, points))
    if not scored:
        return []
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _sympy_point_list(value: Any) -> list[tuple[sp.Expr, sp.Expr]]:
    if not isinstance(value, (list, tuple)):
        return []
    points: list[tuple[sp.Expr, sp.Expr]] = []
    for item in value:
        pair = _sympy_point_pair(item)
        if pair is not None:
            points.append(pair)
    return points


def _sort_candidates_by_parameter(
    candidates: list[tuple[sp.Expr, sp.Expr]],
    target_pair: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol,
) -> list[tuple[sp.Expr, sp.Expr]]:
    def sort_key(point: tuple[sp.Expr, sp.Expr]) -> tuple[float, str]:
        value = _parameter_value_from_candidate(target_pair, point, parameter)
        try:
            numeric = float(sp.N(value)) if value is not None else float("-inf")
        except Exception:
            numeric = float("-inf")
        return (-numeric, _student_point_display("", point))

    return sorted(candidates, key=sort_key)


def _parameter_value_from_candidate(
    target_pair: tuple[sp.Expr, sp.Expr],
    candidate: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol,
) -> sp.Expr | None:
    for expr, value in zip(target_pair, candidate, strict=True):
        if parameter not in expr.free_symbols:
            continue
        try:
            solutions = sp.solve(sp.Eq(expr, value), parameter)
        except Exception:
            solutions = []
        if solutions:
            return sp.simplify(solutions[0])
    return None


def _condition_coefficients_for_curve_point(
    parabola: sp.Expr,
    curve_y: sp.Expr,
) -> tuple[sp.Expr, sp.Expr, sp.Expr] | None:
    x = sp.Symbol("x")
    try:
        poly = sp.Poly(parabola, x)
    except Exception:
        return None
    if poly.degree() != 2:
        return None
    coeffs = (
        sp.simplify(poly.coeff_monomial(x**2)),
        sp.simplify(poly.coeff_monomial(x)),
        sp.simplify(poly.coeff_monomial(1) - curve_y),
    )
    if coeffs[0].could_extract_minus_sign():
        coeffs = tuple(sp.simplify(-item) for item in coeffs)  # type: ignore[assignment]
    return coeffs


def _quadratic_substitution_display(parabola: sp.Expr, x_arg: sp.Expr) -> str:
    x = sp.Symbol("x")
    try:
        poly = sp.Poly(parabola, x)
    except Exception:
        return _student_square_expr(parabola.subs(x, x_arg))
    if poly.degree() != 2:
        return _student_square_expr(parabola.subs(x, x_arg))
    terms = (
        _coefficient_body_term_display(poly.coeff_monomial(x**2), f"{_parenthesized_display(x_arg)}²"),
        _coefficient_body_term_display(poly.coeff_monomial(x), _parenthesized_display(x_arg)),
        _constant_term_display(poly.coeff_monomial(1)),
    )
    return _join_terms(term for term in terms if term)


def _quadratic_in_variable_display(
    coeffs: tuple[sp.Expr, sp.Expr, sp.Expr],
    variable_display: str,
) -> str:
    variable = str(variable_display)
    base = variable if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", variable) else f"({variable})"
    terms = (
        _coefficient_body_term_display(coeffs[0], f"{base}²"),
        _coefficient_body_term_display(coeffs[1], base),
        _constant_term_display(coeffs[2]),
    )
    return _join_terms(term for term in terms if term)


def _coefficient_body_term_display(coefficient: sp.Expr, body: str) -> str:
    coefficient = sp.simplify(coefficient)
    if coefficient == 0:
        return ""
    if sp.simplify(coefficient - 1) == 0:
        return body
    if sp.simplify(coefficient + 1) == 0:
        return f"－{body}"
    if coefficient.is_number and bool(coefficient < 0):
        return f"－{_student_expr(-coefficient, fullwidth_operators=True)}{body}"
    return f"{_student_expr(coefficient, fullwidth_operators=True)}{body}"


def _parenthesized_display(value: sp.Expr) -> str:
    text = _student_square_expr(value)
    return text if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", text) else f"({text})"


def _solve_quadratic_coeffs(coeffs: tuple[sp.Expr, sp.Expr, sp.Expr]) -> list[sp.Expr]:
    u = sp.Symbol("u")
    equation = coeffs[0] * u**2 + coeffs[1] * u + coeffs[2]
    try:
        return [sp.simplify(root) for root in sp.solve(sp.Eq(equation, 0), u)]
    except Exception:
        return []


def _solutions_display(symbol: str, values: list[sp.Expr]) -> str:
    if len(values) == 2:
        first, second = values[0], values[1]
        center = sp.simplify((first + second) / 2)
        delta = sp.simplify(abs(first - second) / 2)
        if delta != 0:
            return f"{symbol}＝{_center_plus_minus_display(center, delta)}"
    return f"{symbol}＝" + " 或 ".join(_student_square_expr(value) for value in values)


def _center_plus_minus_display(center: sp.Expr, delta: sp.Expr) -> str:
    delta_text = _student_square_expr(delta)
    if sp.simplify(center) == 0:
        return f"±{delta_text}"
    center_text = _student_square_expr(center)
    return f"{center_text}±{delta_text}"


def _square_adjacent_detail(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> dict[str, str]:
    step = group.step
    square = _square_fact_for_method_step(step, snapshot)
    vertices = [
        str(item)
        for item in (square or {}).get("vertices") or ()
        if isinstance(item, str) and item
    ]
    if len(vertices) < 4:
        return {}
    labels = [_point_label_from_handle_or_problem(handle, snapshot) for handle in vertices[:4]]
    if any(not label for label in labels):
        return {}
    target_label = _square_target_label(step, labels)
    if not target_label:
        return {}
    side = _square_known_side_for_target(labels, target_label)
    if side is None:
        return {}
    base_label, side_end_label, adjacent_label = side
    base = _point_pair_for_label(base_label, step, snapshot)
    side_end = _point_pair_for_label(side_end_label, step, snapshot)
    adjacent = _point_pair_for_label(adjacent_label, step, snapshot)
    if adjacent is None:
        adjacent = _point_pair_from_trace(roles_from_trace(group).get("conclusion", ""), adjacent_label)
    roles: dict[str, str] = {
        "target_label": adjacent_label,
        "known_side": f"{base_label}{side_end_label}",
        "target_side": f"{base_label}{adjacent_label}",
        "square_name": "".join(labels[:4]),
        "side_equal_statement": f"{base_label}{side_end_label}＝{base_label}{adjacent_label}",
        "square_right_angle_statement": f"∠{side_end_label}{base_label}{adjacent_label}＝90°",
    }
    if base is not None and side_end is not None:
        side_vector = (
            sp.simplify(side_end[0] - base[0]),
            sp.simplify(side_end[1] - base[1]),
        )
        roles["known_side_vector"] = _student_vector_display(side_vector)
    if base is not None and adjacent is not None:
        adjacent_vector = (
            sp.simplify(adjacent[0] - base[0]),
            sp.simplify(adjacent[1] - base[1]),
        )
        roles["target_side_vector"] = _student_vector_display(adjacent_vector)
        roles["target_point"] = _student_point_display(adjacent_label, adjacent)
    if base is not None and side_end is not None and adjacent is not None:
        side_projection = (sp.simplify(side_end[0]), sp.simplify(base[1]))
        target_projection = (sp.simplify(adjacent[0]), sp.simplify(base[1]))
        used_labels = set(labels)
        side_projection_label = _projection_label_for_pair(
            side_projection,
            step,
            snapshot,
            used_labels,
            preferred=("Q", "R", "S"),
        )
        used_labels.add(side_projection_label)
        target_projection_label = _projection_label_for_pair(
            target_projection,
            step,
            snapshot,
            used_labels,
            preferred=("Q", "R", "S"),
        )
        reference_line = _square_projection_reference_line(base, side_projection, target_projection)
        roles.update(
            {
                "projection_construction": _square_projection_construction_text(
                    side_end_label=side_end_label,
                    side_projection_label=side_projection_label,
                    target_label=adjacent_label,
                    target_projection_label=target_projection_label,
                    reference_line=reference_line,
                    side_projection_known=_projection_label_is_existing_problem_point(
                        side_projection_label,
                        snapshot,
                    ),
                ),
                "projection_right_angles": (
                    f"∠{side_end_label}{side_projection_label}{base_label}"
                    f"＝∠{adjacent_label}{target_projection_label}{base_label}＝90°"
                ),
                "matching_angle_statement": (
                    f"∠{side_end_label}{base_label}{side_projection_label}"
                    f"＝∠{base_label}{adjacent_label}{target_projection_label}"
                ),
                "triangle_congruence": (
                    f"Rt△{base_label}{side_end_label}{side_projection_label}"
                    f"≌Rt△{adjacent_label}{base_label}{target_projection_label}"
                ),
                "length_correspondence": _square_length_correspondence_text(
                    base_label=base_label,
                    side_end_label=side_end_label,
                    side_projection_label=side_projection_label,
                    target_label=adjacent_label,
                    target_projection_label=target_projection_label,
                    base=base,
                    side_end=side_end,
                    adjacent=adjacent,
                    target_projection=target_projection,
                    square=square or {},
                ),
                "target_position_condition": _square_target_position_condition(
                    adjacent_label,
                    square or {},
                    labels,
                ),
            }
        )
    return roles


def _projection_label_for_pair(
    pair: tuple[sp.Expr, sp.Expr],
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
    used_labels: set[str],
    *,
    preferred: tuple[str, ...],
) -> str:
    existing = _existing_projection_point_label(pair, step, snapshot, used_labels)
    if existing:
        return existing
    for label in (*preferred, "Q", "R", "S", "T", "U", "V", "W"):
        if label not in used_labels:
            return label
    return "Q"


def _existing_projection_point_label(
    pair: tuple[sp.Expr, sp.Expr],
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
    used_labels: set[str],
) -> str:
    scope_id = str(step.get("scope_id") or "")
    candidates: list[tuple[int, str]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        label = _semantic_point_label(str(item.get("name") or handle_name(str(item.get("handle") or ""))))
        if not label or label in used_labels:
            continue
        value = _sympy_point_pair(item.get("value"))
        if value is None or not _same_point(value, pair):
            continue
        score = _point_scope_score(str(item.get("scope_id") or ""), scope_id)
        if score > 0:
            candidates.append((score, label))
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or entity.get("entity_type") != "point":
            continue
        label = str(entity.get("name") or "")
        if not label or label in used_labels:
            continue
        value = _sympy_point_pair(entity.get("coordinate"))
        if value is not None and _same_point(value, pair):
            candidates.append((4, label))
            continue
        definition = str(entity.get("definition") or "")
        if (
            definition == "axis_x_intercept"
            and _is_zero_expr(pair[1])
            and _projection_x_matches_axis_parameter(pair[0], step, snapshot)
        ):
            candidates.append((3, label))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _projection_label_is_existing_problem_point(
    label: str,
    snapshot: ExplanationSnapshot,
) -> bool:
    for entity in (snapshot.problem or {}).get("entities") or ():
        if (
            isinstance(entity, dict)
            and entity.get("entity_type") == "point"
            and str(entity.get("name") or "") == label
        ):
            return True
    return False


def _same_point(left: tuple[sp.Expr, sp.Expr], right: tuple[sp.Expr, sp.Expr]) -> bool:
    return _is_zero_expr(left[0] - right[0]) and _is_zero_expr(left[1] - right[1])


def _is_zero_expr(value: sp.Expr) -> bool:
    return sp.simplify(value) == 0


def _projection_x_matches_axis_parameter(
    x_value: sp.Expr,
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> bool:
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        if not _handle_is_axis_point(handle, snapshot):
            continue
        pair = _point_pair_for_handle(handle, snapshot)
        if pair is None:
            pair = _point_pair_for_label(_semantic_point_label(handle_name(handle)), step, snapshot)
        if pair is not None and _is_zero_expr(pair[0] - x_value):
            return True
    for item in step.get("produces") or ():
        if not isinstance(item, dict):
            continue
        handle = item.get("handle")
        if not isinstance(handle, str):
            continue
        if not _handle_is_axis_point(handle, snapshot):
            continue
        pair = _point_pair_for_handle(handle, snapshot)
        if pair is None:
            pair = _point_pair_for_label(_semantic_point_label(handle_name(handle)), step, snapshot)
        if pair is not None and _is_zero_expr(pair[0] - x_value):
            return True
    return False


def _handle_is_axis_point(handle: str, snapshot: ExplanationSnapshot) -> bool:
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or str(entity.get("handle") or "") != handle:
            continue
        return str(entity.get("definition") or "") in {"point_on_axis", "axis_x_intercept"}
    fact = snapshot.fact_index.get(handle)
    if isinstance(fact, dict) and fact.get("type") == "Point":
        source_step_id = str(fact.get("source_step_id") or "")
        for step in snapshot.effective_steps:
            if (
                isinstance(step, dict)
                and str(step.get("step_id") or "") == source_step_id
                and str(step.get("recipe_hint") or "") == "quadratic_axis_parameterized_point"
            ):
                return True
        description = str(fact.get("description") or "")
        if "对称轴" in description or "symmetry axis" in description.lower():
            return True
    return False


def _square_projection_reference_line(
    base: tuple[sp.Expr, sp.Expr],
    side_projection: tuple[sp.Expr, sp.Expr],
    target_projection: tuple[sp.Expr, sp.Expr],
) -> str:
    if _is_zero_expr(base[1]) and _is_zero_expr(side_projection[1]) and _is_zero_expr(target_projection[1]):
        return "x轴"
    return "过已知顶点的水平线"


def _square_projection_construction_text(
    *,
    side_end_label: str,
    side_projection_label: str,
    target_label: str,
    target_projection_label: str,
    reference_line: str,
    side_projection_known: bool,
) -> str:
    target_text = f"{target_label}{target_projection_label}⊥{reference_line}于 {target_projection_label}"
    if side_projection_known:
        return target_text
    return (
        f"{side_end_label}{side_projection_label}⊥{reference_line}于 {side_projection_label}，"
        f"{target_text}"
    )


def _square_length_correspondence_text(
    *,
    base_label: str,
    side_end_label: str,
    side_projection_label: str,
    target_label: str,
    target_projection_label: str,
    base: tuple[sp.Expr, sp.Expr],
    side_end: tuple[sp.Expr, sp.Expr],
    adjacent: tuple[sp.Expr, sp.Expr],
    target_projection: tuple[sp.Expr, sp.Expr],
    square: dict[str, Any],
) -> str:
    target_horizontal = _square_length_expr(target_projection[0] - base[0])
    side_vertical = _square_length_expr(side_end[1] - base[1])
    orientation = str(square.get("orientation") or "")
    if orientation == "below_x_axis":
        target_vertical = _square_length_expr(base[1] - adjacent[1])
    else:
        target_vertical = _square_length_expr(adjacent[1] - base[1])
    side_horizontal = _square_length_expr(side_end[0] - base[0])
    return (
        f"{base_label}{target_projection_label}＝{side_projection_label}{side_end_label}"
        f"＝{target_horizontal}，"
        f"{target_label}{target_projection_label}＝{base_label}{side_projection_label}"
        f"＝{target_vertical if target_vertical else side_horizontal}"
    )


def _square_length_expr(value: sp.Expr) -> str:
    simplified = sp.simplify(value)
    if simplified.is_number and simplified.could_extract_minus_sign():
        simplified = sp.simplify(-simplified)
    return _student_square_expr(simplified)


def _square_target_position_condition(
    target_label: str,
    square: dict[str, Any],
    labels: list[str],
) -> str:
    orientation = str(square.get("orientation") or "")
    orientation_target = _square_orientation_target_label(square, labels)
    if orientation == "below_x_axis" and target_label == orientation_target:
        return f"{target_label} 在 x 轴下方"
    if orientation == "above_x_axis" and target_label == orientation_target:
        return f"{target_label} 在 x 轴上方"
    return f"按正方形顶点顺序选取 {target_label}"


def _square_orientation_target_label(square: dict[str, Any], labels: list[str]) -> str:
    description = str(square.get("description") or "")
    for label in labels:
        if f"{label} 在 x 轴下方" in description or f"{label}在 x 轴下方" in description:
            return label
        if f"{label} 在 x 轴上方" in description or f"{label}在 x 轴上方" in description:
            return label
    return labels[3] if len(labels) >= 4 else ""


def _square_fact_for_method_step(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any] | None:
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        if isinstance(fact, dict) and fact.get("type") == "square":
            return fact
        for problem_fact in (snapshot.problem or {}).get("facts") or ():
            if (
                isinstance(problem_fact, dict)
                and str(problem_fact.get("handle") or "") == handle
                and problem_fact.get("type") == "square"
            ):
                return problem_fact
    return None


def _point_label_from_handle_or_problem(handle: str, snapshot: ExplanationSnapshot) -> str:
    for entity in (snapshot.problem or {}).get("entities") or ():
        if isinstance(entity, dict) and str(entity.get("handle") or "") == handle:
            return str(entity.get("name") or handle_name(handle))
    return _semantic_point_label(handle_name(handle))


def _square_target_label(step: dict[str, Any], labels: list[str]) -> str:
    for raw in (
        str(step.get("target") or ""),
        *(str(item.get("handle") or "") for item in step.get("produces") or () if isinstance(item, dict)),
    ):
        label = _semantic_point_label(handle_name(raw))
        if label in labels:
            return label
    for handle in step.get("reads") or ():
        if not isinstance(handle, str) or not handle.startswith("point:"):
            continue
        label = _semantic_point_label(handle_name(handle))
        if label in labels and label != labels[0]:
            return label
    return ""


def _semantic_point_label(text: str) -> str:
    match = re.match(r"([A-Z][A-Za-z0-9]*)(?:_|$)", str(text))
    return match.group(1) if match else str(text)


def _produced_point_label(step: dict[str, Any]) -> str:
    for produced in step.get("produces") or ():
        if not isinstance(produced, dict):
            continue
        if str(produced.get("output_type") or "") != "Point":
            continue
        for raw in (
            str(produced.get("handle") or ""),
            str(produced.get("description") or ""),
        ):
            label = _semantic_point_label(handle_name(raw))
            if re.match(r"^[A-Z][A-Za-z0-9]*$", label):
                return label
            match = re.search(r"([A-Z][A-Za-z0-9]*)\s*点坐标", raw)
            if match:
                return match.group(1)
    return ""


def _point_label_from_step_target(step: dict[str, Any]) -> str:
    target = str(step.get("target") or "")
    if not target:
        return ""
    label = _semantic_point_label(handle_name(target))
    return label if re.match(r"^[A-Z][A-Za-z0-9]*$", label) else ""


def _source_point_pair_for_label(
    label: str,
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> tuple[sp.Expr, sp.Expr] | None:
    scope_id = str(step.get("scope_id") or "")
    candidates = (
        f"runtime:{scope_id}:points:{label}",
        f"runtime:problem:points:{label}",
    )
    for handle in candidates:
        fact = snapshot.fact_index.get(handle)
        if isinstance(fact, dict) and fact.get("type") == "Point":
            pair = _sympy_point_pair(fact.get("value"))
            if pair is not None:
                return pair
    for fact in snapshot.fact_index.values():
        if not isinstance(fact, dict) or fact.get("type") != "Point":
            continue
        if str(fact.get("name") or "") != label:
            continue
        if scope_id and str(fact.get("scope_id") or "") not in {scope_id, "problem"}:
            continue
        pair = _sympy_point_pair(fact.get("value"))
        if pair is not None:
            return pair
    return None


def _runtime_point_for_step(
    step_id: str,
    snapshot: ExplanationSnapshot,
) -> tuple[sp.Expr, sp.Expr] | None:
    for fact in snapshot.fact_index.values():
        if not isinstance(fact, dict) or fact.get("type") != "Point":
            continue
        if not _fact_belongs_to_step(fact, step_id):
            continue
        pair = _sympy_point_pair(fact.get("value"))
        if pair is not None:
            return pair
    return None


def _square_known_side_for_target(
    labels: list[str],
    target_label: str,
) -> tuple[str, str, str] | None:
    if len(labels) < 4:
        return None
    if target_label == labels[3]:
        return labels[0], labels[1], labels[3]
    if target_label == labels[1]:
        return labels[0], labels[3], labels[1]
    if target_label == labels[2]:
        return labels[1], labels[0], labels[2]
    return None


def _point_pair_for_label(
    label: str,
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> tuple[sp.Expr, sp.Expr] | None:
    scope_id = str(step.get("scope_id") or "")
    handles: list[str] = []
    for handle in step.get("reads") or ():
        if isinstance(handle, str):
            handles.append(handle)
    target = step.get("target")
    if isinstance(target, str):
        handles.append(target)
    for item in step.get("produces") or ():
        if isinstance(item, dict) and isinstance(item.get("handle"), str):
            handles.append(str(item["handle"]))
    for handle in handles:
        handle_label = _semantic_point_label(handle_name(handle))
        if handle_label != label:
            continue
        pair = _point_pair_for_handle(handle, snapshot)
        if pair is not None:
            return pair
    candidates: list[tuple[int, tuple[sp.Expr, sp.Expr]]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        if _semantic_point_label(str(item.get("name") or handle_name(str(item.get("handle") or "")))) != label:
            continue
        pair = _sympy_point_pair(item.get("value"))
        if pair is not None:
            score = _point_scope_score(str(item.get("scope_id") or ""), scope_id)
            if score > 0:
                candidates.append((score, pair))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or entity.get("entity_type") != "point":
            continue
        if str(entity.get("name") or "") != label:
            continue
        pair = _sympy_point_pair(entity.get("coordinate"))
        if pair is not None:
            return pair
    return None


def _point_scope_score(item_scope: str, step_scope: str) -> int:
    if item_scope == step_scope and step_scope:
        return 5
    if item_scope == "problem":
        return 4
    if step_scope and _scope_root_for_explanation(item_scope) == _scope_root_for_explanation(step_scope):
        return 3
    if not step_scope:
        return 1
    return 0


def _scope_root_for_explanation(scope_id: str) -> str:
    if not scope_id:
        return "problem"
    return str(scope_id).split("_", 1)[0] or "problem"


def _fact_belongs_to_step(fact: dict[str, Any], step_id: str) -> bool:
    if not step_id:
        return False
    source_step_id = str(fact.get("source_step_id") or "")
    if source_step_id:
        return source_step_id == step_id
    return str(fact.get("scope_id") or "") == step_id


def _point_pair_for_handle(
    handle: str,
    snapshot: ExplanationSnapshot,
) -> tuple[sp.Expr, sp.Expr] | None:
    fact = snapshot.fact_index.get(handle)
    if isinstance(fact, dict):
        pair = _sympy_point_pair(fact.get("value"))
        if pair is not None:
            return pair
    source_step_id = str(fact.get("source_step_id") or "") if isinstance(fact, dict) else ""
    handle_tail = handle_name(handle)
    handle_scope = _canonical_scope_from_handle(handle)
    aliases = _point_runtime_name_aliases(handle_tail)
    uses_runtime_alias = aliases != {handle_tail}
    runtime_candidates: list[tuple[int, tuple[sp.Expr, sp.Expr]]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        item_handle = str(item.get("handle") or "")
        item_scope = str(item.get("scope_id") or "")
        item_name = str(item.get("name") or handle_name(item_handle))
        score = 0
        if item_handle == handle:
            score = 20
        elif uses_runtime_alias and item_name in aliases and source_step_id and item_scope == source_step_id:
            score = 18
        elif uses_runtime_alias and item_name in aliases and (not handle_scope or item_scope == handle_scope):
            score = 16
        elif uses_runtime_alias and any(item_handle.endswith(f":outputs:{alias}") for alias in aliases) and (
            not handle_scope or item_scope == handle_scope
        ):
            score = 14
        elif source_step_id and item_scope == source_step_id:
            score = 9
        if score <= 0:
            continue
        pair = _sympy_point_pair(item.get("value"))
        if pair is not None:
            runtime_candidates.append((score, pair))
    if runtime_candidates:
        runtime_candidates.sort(key=lambda item: item[0], reverse=True)
        return runtime_candidates[0][1]
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or str(entity.get("handle") or "") != handle:
            continue
        pair = _sympy_point_pair(entity.get("coordinate"))
        if pair is not None:
            return pair
    return None


def _point_runtime_name_aliases(name: str) -> set[str]:
    aliases = {str(name or "")}
    match = re.fullmatch(r"path_minimum_point_(\d+)", str(name or ""))
    if match:
        aliases.add(f"minimum_point_{match.group(1)}")
    return {alias for alias in aliases if alias}


def _canonical_scope_from_handle(handle: str) -> str:
    parts = str(handle).split(":")
    return parts[1] if len(parts) > 2 else ""


def _point_pair_from_trace(text: str, label: str) -> tuple[sp.Expr, sp.Expr] | None:
    raw = str(text).strip()
    match = re.match(rf"{re.escape(label)}\s*=?\s*\((.*)\)$", raw)
    if not match:
        return None
    parts = [part.strip() for part in match.group(1).split(",")]
    return _sympy_point_pair(parts)


def _sympy_point_pair(value: Any) -> tuple[sp.Expr, sp.Expr] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return (
            _sympy_axis_expr(value[0]),
            _sympy_axis_expr(value[1]),
        )
    except Exception:
        return None


def _sympy_axis_expr(value: Any) -> sp.Expr:
    text = re.sub(r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+", "t", str(value))
    return sp.simplify(sp.sympify(text, locals={"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs}))


def _student_vector_display(pair: tuple[sp.Expr, sp.Expr]) -> str:
    return f"({_student_square_expr(pair[0])},{_student_square_expr(pair[1])})"


def _student_point_display(label: str, pair: tuple[sp.Expr, sp.Expr]) -> str:
    return f"{label}({_student_square_expr(pair[0])},{_student_square_expr(pair[1])})"


def _student_square_expr(value: Any) -> str:
    text = re.sub(r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+", "t", str(value))
    return _student_expr(text, fullwidth_operators=True)


def _axis_parameterized_point_from_trace(text: str) -> tuple[str, str, str] | None:
    raw = str(text).strip()
    match = re.match(r"([A-Z][A-Za-z0-9_]*)\s*=?\s*\((.*)\)$", raw)
    if not match:
        return None
    name, body = match.groups()
    parts = [part.strip() for part in body.split(",")]
    if len(parts) != 2:
        return None
    axis_x = _student_expr(parts[0], fullwidth_operators=True)
    parameter = _student_axis_parameter(parts[1])
    return name, axis_x, f"{name}({axis_x},{parameter})"


def _student_axis_parameter(value: str) -> str:
    if re.search(r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+", str(value)):
        return "t"
    return _student_expr(value, fullwidth_operators=True)


def _axis_x_from_calculation(text: str) -> str:
    raw = str(text)
    if "=" not in raw:
        return ""
    _, right = raw.split("=", 1)
    return _student_expr(right.strip(), fullwidth_operators=True)


def _bind_parameter(
    method_id: str,
    trace_roles: dict[str, str],
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    parameter, _ = parameter_assignment(trace_roles.get("conclusion", "") or trace_roles.get("calculation", ""))
    return parameter


def _bind_parameter_value(
    method_id: str,
    trace_roles: dict[str, str],
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    _, value = parameter_assignment(trace_roles.get("conclusion", "") or trace_roles.get("calculation", ""))
    return value


_METHOD_ROLE_BINDERS = {
    "p1": _bind_distance_p1,
    "p2": _bind_distance_p2,
    "distance": _bind_distance_value,
    "known_conditions": _bind_known_conditions,
    "result_parabola": _bind_result_parabola,
    "expression": lambda method_id, trace_roles, group, snapshot: _expression_from_previous(group, snapshot),
    "target_value": lambda method_id, trace_roles, group, snapshot: _target_value_from_step(group.step),
    "parameter": _bind_parameter,
    "parameter_value": _bind_parameter_value,
    "angle_sum_condition": lambda method_id, trace_roles, group, snapshot: _condition_description(group.step, snapshot),
    "reference_angle": lambda method_id, trace_roles, group, snapshot: _reference_angle_from_trace(trace_roles.get("calculation", "")),
    "angle_equality": lambda method_id, trace_roles, group, snapshot: trace_roles.get("conclusion", "") or trace_roles.get("goal", ""),
    "input_angle_equality": lambda method_id, trace_roles, group, snapshot: trace_roles.get("reason", ""),
    "ratio_equation": lambda method_id, trace_roles, group, snapshot: _ratio_equation_from_trace(trace_roles.get("calculation", "")) or trace_roles.get("calculation", ""),
    "target_point": lambda method_id, trace_roles, group, snapshot: trace_roles.get("conclusion", "") or trace_roles.get("goal", ""),
    "line_points": lambda method_id, trace_roles, group, snapshot: _line_points_from_step(group.step),
    "parabola": lambda method_id, trace_roles, group, snapshot: _parabola_description(group.step, snapshot),
    "known_point": lambda method_id, trace_roles, group, snapshot: _known_point_from_step(group.step),
    "calculation": lambda method_id, trace_roles, group, snapshot: trace_roles.get("calculation", ""),
    "conclusion": lambda method_id, trace_roles, group, snapshot: trace_roles.get("conclusion", ""),
    "goal": lambda method_id, trace_roles, group, snapshot: trace_roles.get("goal", ""),
    "reason": lambda method_id, trace_roles, group, snapshot: trace_roles.get("reason", ""),
}


def _distance_points_from_group(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> tuple[str, str]:
    draft = group.step.get("target") or ""
    if group.capability_id == "equal_length_ray_path_reduction":
        for insight in snapshot.planner_insights:
            facts = insight.get("facts") if isinstance(insight, dict) else None
            if not isinstance(facts, dict):
                continue
            transformed_path = str(facts.get("transformed_path") or "")
            match = re.search(r"([A-Z][A-Z])$", transformed_path)
            if match:
                return match.group(1)[0], match.group(1)[1]
    for produced in group.step.get("produces", []):
        description = str(produced.get("description", ""))
        match = re.search(r"([A-Z][A-Z])", description)
        if match:
            return match.group(1)[0], match.group(1)[1]
    match = re.search(r"([A-Z][A-Z])", str(draft))
    if match:
        return match.group(1)[0], match.group(1)[1]
    return "两点", ""


def _expression_from_previous(group: LessonCandidateGroup, snapshot: ExplanationSnapshot) -> str:
    for handle in group.step.get("reads", []):
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        if fact and fact.get("type") == "MinimumExpression":
            value = fact.get("value")
            return str(value or fact.get("description") or handle)
    for handle in group.step.get("reads", []):
        if isinstance(handle, str) and "expression" in handle:
            return handle
    return "前面得到的表达式"


def _target_value_from_step(step: dict[str, Any]) -> str:
    for handle in step.get("reads", []):
        if isinstance(handle, str) and ("value_given" in handle or "minimum_value" in handle):
            return handle
    return "题设给定值"


def _condition_description(step: dict[str, Any], snapshot: ExplanationSnapshot) -> str:
    facts = _facts_by_handle(snapshot)
    for handle in step.get("reads", []):
        if not isinstance(handle, str):
            continue
        fact = facts.get(handle)
        if fact and fact.get("type") == "angle_sum_condition":
            return str(fact.get("description") or handle)
    for handle in step.get("reads", []):
        if isinstance(handle, str) and "angle" in handle:
            return handle
    return "角和条件"


def _reference_angle_from_trace(text: str) -> str:
    match = re.search(r"∠([^=]+)=45", text)
    return f"∠{match.group(1)}" if match else "参考 45° 角"


def _ratio_equation_from_trace(text: str) -> str:
    match = re.search(r"([^，,]+=[^，,]+)", text)
    return match.group(1).strip() if match else ""


def _line_points_from_step(step: dict[str, Any]) -> str:
    labels = []
    for handle in step.get("reads", []):
        if isinstance(handle, str) and handle.startswith("point:"):
            labels.append(handle_name(handle))
    if len(labels) >= 2:
        return "、".join(labels[:2])
    return "两个已知点"


def _known_point_from_step(step: dict[str, Any]) -> str:
    for handle in step.get("reads", []):
        if isinstance(handle, str) and handle.startswith("point:"):
            return handle_name(handle)
    return "已知交点"


def _parabola_description(step: dict[str, Any], snapshot: ExplanationSnapshot) -> str:
    for handle in step.get("reads", []):
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        if fact and fact.get("type") == "Parabola":
            return str(fact.get("value") or fact.get("description") or "抛物线")
    return "抛物线"


def _line_expression_from_trace(text: str, line_name: str) -> str:
    match = re.search(r"line:\s*y\s*=\s*(.+)$", text.strip())
    if not match:
        return text.strip()
    rhs = match.group(1).strip()
    display = _linear_expr_display(rhs)
    prefix = f"{line_name}: " if line_name else ""
    return f"{prefix}{display}" if display else f"{prefix}y={rhs}"


def _line_name(known_point: str, target_point: str) -> str:
    known = re.match(r"([A-Z])$", known_point.strip())
    target = re.match(r"([A-Z])(?:\(|$)", target_point.strip())
    if known and target:
        return f"{known.group(1)}{target.group(1)}"
    return "目标直线"


def _linear_expr_display(rhs: str) -> str:
    try:
        x = sp.Symbol("x")
        expr = sp.sympify(rhs, locals={"x": x})
        slope = sp.simplify(expr.coeff(x))
        intercept = sp.simplify(expr.subs(x, 0))
    except Exception:
        return f"y={rhs.replace('*', '')}"
    slope_text = _slope_text(slope)
    intercept_text = _signed_term(intercept)
    return f"y={slope_text}x{intercept_text}"


def _slope_text(value: sp.Expr) -> str:
    if sp.simplify(value - 1) == 0:
        return ""
    if sp.simplify(value + 1) == 0:
        return "-"
    return f"({_student_expr(value)})"


def _signed_term(value: sp.Expr) -> str:
    value = sp.simplify(value)
    if value == 0:
        return ""
    if value.is_negative:
        return f"-{_student_expr(-value)}"
    return f"+{_student_expr(value)}"


def _student_parabola_text(value: str) -> str:
    text = _student_expr(value)
    if text == "抛物线" or text.startswith("y="):
        return text
    return f"y={text}"


def _compact_point_text(value: str) -> str:
    return re.sub(r",\s+", ",", value.strip())


def _facts_by_handle(snapshot: ExplanationSnapshot) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("handle")): item
        for item in snapshot.problem.get("facts", [])
        if isinstance(item, dict) and item.get("handle")
    }
