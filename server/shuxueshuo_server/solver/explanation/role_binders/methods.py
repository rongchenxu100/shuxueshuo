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


def method_role_binders() -> dict[str, MethodRoleBinder]:
    role_name = RoleNameRegistryMethodRoleBinder()
    return {
        "generic_trace": GenericTraceMethodRoleBinder(),
        "role_name_registry": role_name,
        "distance_between_points": DistanceBetweenPointsRoleBinder(),
        "line_parabola_second_intersection_point": LineParabolaSecondIntersectionRoleBinder(),
    }


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
