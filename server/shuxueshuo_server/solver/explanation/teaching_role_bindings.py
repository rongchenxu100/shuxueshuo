"""Typed TeachingUnit role binding from verified Snapshot v3 values only.

This module intentionally has no dependency on the retired explanation draft,
candidate-group, replay-trace, ``effective_steps`` or ``fact_index`` APIs.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.contracts import TeachingUnitSpec
from shuxueshuo_server.solver.student_display import student_math_display

from .models import (
    ExplanationSnapshot,
    TeachingSource,
    iter_teaching_sources,
    teaching_source_owners,
)


class TeachingRoleBindingError(ValueError):
    """Verified source values cannot satisfy a TeachingUnit role contract."""


RoleBinder = Callable[
    [TeachingSource, ExplanationSnapshot],
    Mapping[str, Any],
]


def bind_teaching_roles(
    source: TeachingSource,
    unit: TeachingUnitSpec,
    *,
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    binder = _ROLE_BINDERS.get(unit.role_binder_id)
    if binder is None:
        if not unit.role_schema:
            return {}
        roles = _generic_roles(source)
    else:
        roles = dict(binder(source, snapshot))
    missing = sorted(
        role
        for role in unit.role_schema
        if role not in roles
        and _template_uses_role(unit, role)
    )
    if missing:
        raise TeachingRoleBindingError(
            "teaching_role_binding_missing: "
            f"step={source.source_step_id}, binder={unit.role_binder_id}, "
            f"roles={missing}"
        )
    return roles


def format_teaching_template(template: str, roles: Mapping[str, Any]) -> str:
    class _Safe(dict[str, str]):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    values = _Safe(
        {
            key: (
                str(value.get("label") or value.get("handle") or "")
                if isinstance(value, Mapping)
                else str(value)
            )
            for key, value in roles.items()
        }
    )
    return template.format_map(values)


def _template_uses_role(unit: TeachingUnitSpec, role: str) -> bool:
    needle = "{" + role + "}"
    return any(
        needle in value
        for value in (
            unit.title_template,
            unit.nav_title_template,
            unit.goal_template,
            *(text for _, text in unit.derive_templates),
            *unit.box_templates,
        )
    )


def _generic_roles(source: TeachingSource) -> dict[str, Any]:
    roles: dict[str, Any] = {}
    for name, items in source.inputs.items():
        if len(items) == 1:
            roles[name] = _item_display(items[0])
        elif items:
            roles[name] = "，".join(_item_display(item) for item in items)
    for name, item in source.outputs.items():
        roles[name] = _item_display(item)
    # A material role named after a public return must describe the verified
    # value, not its binding handle.  Output targets are only a fallback for
    # templates that explicitly ask for a target identity and have no value
    # role with the same name.
    for name, target in source.output_targets.items():
        roles.setdefault(name, target.rsplit(":", 1)[-1])
    return roles


def _quadratic_from_constraints(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    parabola = _output_expr(source, "parabola")
    result = _quadratic_expression_display(parabola)
    completed = _completed_square_expression(parabola)
    roles: dict[str, Any] = {
        "result_parabola": result,
        "parabola_title_action": _quadratic_title_action(parabola),
        "completed_square_suffix": (
            f"＝{completed}" if completed and completed != result else ""
        ),
    }
    coefficients = _output_value(source, "coefficients")
    relation = _coefficient_mapping_display(coefficients)
    point_items = _input_items(
        source,
        "curve_point",
        "curve_points",
        "p1",
        "p2",
    )
    constraint_displays = _quadratic_constraint_displays(
        source,
        coefficients=coefficients,
    )
    known_substitutions = _quadratic_known_substitutions(
        source,
        coefficients=coefficients,
    )
    if not relation:
        relation = "，".join(constraint_displays)
    if not relation:
        raise TeachingRoleBindingError(
            f"teaching_quadratic_constraint_result_missing: {source.source_step_id}"
        )

    dynamic: list[str] = []
    point_equations: list[str] = []
    x = sp.Symbol("x")
    for point_item in point_items:
        base = _curve_expression_for_point(point_item, snapshot)
        pair = _point_pair(point_item.get("value"))
        label = _point_label(point_item)
        if base is None or pair is None or not label:
            raise TeachingRoleBindingError(
                "teaching_quadratic_curve_constraint_invalid: "
                f"{source.source_step_id}"
            )
        x_value, y_value = pair
        working_base = sp.simplify(base.subs(known_substitutions))
        substituted = _quadratic_substitution_simplified_display(
            working_base,
            x_value,
        )
        residual = sp.simplify(working_base.subs(x, x_value) - y_value)
        factored = sp.factor(residual)
        equation = f"{_math(y_value)}＝{substituted}"
        factored_display = _math(factored)
        if len(point_items) == 1 and factored_display != substituted:
            equation += f"＝{factored_display}"
        dynamic.extend(
            (
                f"∵{_point_display(label, pair)} 在 "
                f"y＝{_quadratic_expression_display(base)} 上",
                f"∴代入 {label} 点坐标，得 {equation}",
            )
        )
        point_equations.append(equation)
        if len(point_items) == 1:
            condition = _nonzero_factor_condition(factored, snapshot)
            if condition:
                dynamic.append(f"∵{condition}")

    if point_items and constraint_displays:
        dynamic.insert(0, f"∵题设还给出 {'，'.join(constraint_displays)}")
    if point_items:
        solve_action = "联立上述方程" if len(point_equations) > 1 else "化简上述方程"
        dynamic.append(f"计算{solve_action}，得 {relation}")
    else:
        origin = "，".join(constraint_displays) or relation
        relation_derivations = _quadratic_relation_derivation_displays(
            source,
            coefficients=coefficients,
            known_substitutions=known_substitutions,
        )
        source_expression = _matching_quadratic_source_expression(
            snapshot,
            coefficients=coefficients,
            result=parabola,
        )
        dynamic.append(f"∵已知系数条件为 {origin}")
        dynamic.extend(relation_derivations)
        if source_expression is not None:
            dynamic.append(
                f"计算代入 y＝"
                f"{_quadratic_expression_display(source_expression)}，"
                f"得 y＝{result}"
            )
        elif not relation_derivations:
            dynamic.append(f"计算由系数条件得 {relation}")
    dynamic.append(f"∴y＝{result}{roles['completed_square_suffix']}")
    roles.update(
        {
            "constraints": relation,
            "constraint_origin": dynamic[0].removeprefix("∵"),
            "constraint_derivation": "；".join(
                value.removeprefix("∵").removeprefix("∴").removeprefix("计算")
                for value in dynamic[1:-1]
            ),
            "derive_items": dynamic,
        }
    )
    return roles


def _quadratic_x_axis_intercept(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    parabola = _input_expr(source, "parabola")
    x = sp.Symbol("x")
    roots = sorted(
        (sp.simplify(value) for value in sp.solve(sp.Eq(parabola, 0), x)),
        key=sp.default_sort_key,
    )
    point = _output_point(source, "point")
    target = _output_label(source, "point")
    selected_x = point[0]
    side = _problem_point_attribute(snapshot, target, "side")
    if side in {"left", "right"}:
        direction = "左侧" if side == "left" else "右侧"
        ordering = "较小根" if side == "left" else "较大根"
        selection = f"{target} 定义为{direction}交点，取{ordering} x＝{_math(selected_x)}"
    elif len(roots) == 1:
        selection = "方程只有一个交点横坐标"
    else:
        selection = f"结合{target or '目标点'}的定义，取 x＝{_math(selected_x)}"
    return {
        "parabola": f"y＝{_quadratic_expression_display(parabola)}",
        "intercept_equation": f"{_quadratic_expression_display(parabola)}＝0",
        "root_candidates": " 或 ".join(f"x＝{_math(root)}" for root in roots),
        "selection_reason": selection,
        "target_point": _point_display(target, point),
        "known_point": "",
    }


def _quadratic_y_axis_intercept(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    quadratic = _input_expr(source, "quadratic")
    point = _output_point(source, "point")
    label = _output_label(source, "point")
    parabola = _quadratic_expression_display(quadratic)
    value = sp.simplify(quadratic.subs(sp.Symbol("x"), 0))
    return {
        "quadratic": f"y＝{parabola}",
        "point": _point_display(label, point),
        "derive_items": (
            "∵y 轴上的点满足 x＝0",
            f"计算代入 x＝0，得 y＝"
            f"{_quadratic_substitution_display(quadratic, sp.Integer(0))}＝{_math(value)}",
            f"∴{_point_display(label, point)}",
        ),
    }


def _right_angle_equal_length_candidates(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    relation = _one_input(source, "right_angle_equal_length")
    target_item = _one_input(source, "target")
    assert relation is not None and target_item is not None
    value = relation.get("value")
    if not isinstance(value, Mapping):
        raise TeachingRoleBindingError(
            "teaching_right_angle_equal_length_relation_invalid"
        )
    angle = tuple(str(item) for item in value.get("angle") or ())
    target = _point_label(target_item)
    if len(angle) != 3 or not target or target not in {angle[0], angle[2]}:
        raise TeachingRoleBindingError(
            "teaching_right_angle_equal_length_roles_invalid"
        )
    anchor = angle[1]
    reference = angle[2] if target == angle[0] else angle[0]
    anchor_item = _find_point_input_by_label(source, anchor)
    reference_item = _find_point_input_by_label(source, reference)
    anchor_pair = (
        _point_pair(anchor_item.get("value"))
        if anchor_item
        else _snapshot_point_pair(anchor, snapshot, source=source)
    )
    reference_pair = (
        _point_pair(reference_item.get("value"))
        if reference_item
        else _snapshot_point_pair(reference, snapshot, source=source)
    )
    dynamic: list[str] = [
        f"∵以 {anchor} 为直角顶点，且 {anchor}{target}＝{anchor}{reference}、"
        f"∠{target}{anchor}{reference}＝90°",
    ]
    dx = sp.simplify(reference_pair[0] - anchor_pair[0])
    dy = sp.simplify(reference_pair[1] - anchor_pair[1])
    candidates = _point_list(source.outputs["candidates"].get("value"))
    if len(candidates) != 2:
        raise TeachingRoleBindingError(
            "teaching_right_angle_equal_length_candidates_invalid"
        )
    candidate_labels = tuple(
        _indexed_point_label(target, index) for index in range(1, 3)
    )
    candidate_displays = tuple(
        _point_display(label, point)
        for label, point in zip(candidate_labels, candidates, strict=True)
    )
    dynamic.append(
        f"∵{_point_display(anchor, anchor_pair)}，"
        f"{_point_display(reference, reference_pair)}，"
        f"从 {anchor} 到 {reference} 横向变化 {_math(dx)}、"
        f"纵向变化 {_math(dy)}"
    )
    dynamic.append(
        f"设将 {anchor}{reference} 绕 {anchor} 顺、逆时针旋转 90°，"
        f"所得端点分别为 {candidate_labels[0]}、{candidate_labels[1]}"
    )
    dynamic.append(
        "∴旋转后横、纵坐标差互换，并改变其中一个方向，"
        f"所以 {target} 的两个候选位置为 "
        + "，".join(candidate_displays)
    )
    construction_result = "，".join(candidate_displays)
    return {
        "anchor": anchor,
        "reference": reference,
        "target": target,
        "candidates": construction_result,
        "construction_title": "由直角等腰关系构造候选点",
        "construction_nav_title": "构造候选点",
        "construction_goal": "把已知直角边顺、逆时针旋转 90°，列出所有等长候选点。",
        "construction_result": construction_result,
        "derive_items": tuple(dynamic),
    }


def _midpoint_from_definition(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    definition = _one_input(source, "midpoint_definition")
    assert definition is not None
    value = definition.get("value")
    endpoints = (
        tuple(str(item) for item in value.get("of") or ())
        if isinstance(value, Mapping)
        else ()
    )
    if len(endpoints) != 2:
        raise TeachingRoleBindingError(
            "teaching_midpoint_definition_endpoints_invalid"
        )
    p1_pair = _snapshot_point_pair(endpoints[0], snapshot, source=source)
    p2_pair = _snapshot_point_pair(endpoints[1], snapshot, source=source)
    midpoint = _output_point(source, "midpoint")
    midpoint_label = _output_label(source, "midpoint")
    p1 = _point_display(endpoints[0], p1_pair)
    p2 = _point_display(endpoints[1], p2_pair)
    midpoint_display = _point_display(midpoint_label, midpoint)
    calculation = (
        f"x_{midpoint_label}＝({_coordinate_operand(p1_pair[0])}＋"
        f"{_coordinate_operand(p2_pair[0])})/2＝{_math(midpoint[0])}，"
        f"y_{midpoint_label}＝({_coordinate_operand(p1_pair[1])}＋"
        f"{_coordinate_operand(p2_pair[1])})/2＝{_math(midpoint[1])}"
    )
    return {
        "p1": p1,
        "p2": p2,
        "midpoint": midpoint_display,
        "derive_items": (
            f"∵线段两端点为 {p1}、{p2}",
            f"计算由中点公式，{calculation}",
            f"∴中点为 {midpoint_display}",
        ),
    }


def _parameter_from_segment_length(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    parameter = _parameter_output_target(source)
    parameter_value = _item_display(source.outputs["parameter_value"])
    condition = _segment_condition_display(source)
    equations = _calculation_equation_displays(source)
    if not equations:
        raise TeachingRoleBindingError(
            f"teaching_segment_parameter_equation_missing: {source.source_step_id}"
        )
    p1 = _input_point_display(source, "p1", snapshot)
    p2 = _input_point_display(source, "p2", snapshot)
    dynamic = [
        f"∵目标线段端点为 {p1}、{p2}",
        f"∵题设长度条件为 {condition}",
    ]
    for equation in equations:
        dynamic.append(f"计算由距离公式建立方程 {equation}")
    candidates = _real_calculation_solutions(source, parameter)
    if candidates:
        dynamic.append(
            f"计算解方程，得 "
            f"{_solution_candidates_display(parameter, candidates)}"
        )
    if len(candidates) > 1:
        filter_context = _parameter_filter_context(source, snapshot, parameter)
        dynamic.append(
            f"∵根据 {filter_context}，保留 "
            f"{parameter}＝{parameter_value}"
        )
    dynamic.append(f"∴{parameter}＝{parameter_value}")
    return {
        "p1": p1,
        "p2": p2,
        "condition": condition,
        "parameter": parameter,
        "parameter_value": parameter_value,
        "derive_items": tuple(dynamic),
    }


def _parameter_from_minimum_value(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    minimum_expression = _first_input_display(source, "minimum_expression")
    condition = _first_input_display(source, "condition", "minimum_value")
    parameter = _parameter_output_target(source)
    parameter_value = _item_display(source.outputs["parameter_value"])
    equations = _calculation_equation_displays(source)
    equation = equations[0] if equations else f"{minimum_expression}＝{condition}"
    candidates = _real_calculation_solutions(source, parameter)
    dynamic = [
        f"∵题设要求 {equation}",
        (
            f"计算解方程，得 "
            f"{_solution_candidates_display(parameter, candidates)}"
            if candidates
            else f"计算解关于 {parameter} 的方程"
        ),
    ]
    if len(candidates) > 1:
        filter_context = _parameter_filter_context(source, snapshot, parameter)
        dynamic.append(
            f"∵根据 {filter_context}，保留 "
            f"{parameter}＝{parameter_value}"
        )
    dynamic.append(f"∴{parameter}＝{parameter_value}")
    return {
        "minimum_expression": minimum_expression,
        "condition": condition,
        "parameter": parameter,
        "parameter_value": parameter_value,
        "derive_items": tuple(dynamic),
    }


def _angle_sum_equal_angle(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    condition_item = _one_input(source, "condition")
    assert condition_item is not None
    condition_value = condition_item.get("value")
    equality_value = _output_value(source, "angle_equality")
    if not isinstance(condition_value, Mapping) or not isinstance(
        equality_value,
        Mapping,
    ):
        raise TeachingRoleBindingError("teaching_angle_equality_invalid")
    terms = tuple(str(value) for value in condition_value.get("angle_terms") or ())
    if len(terms) != 2:
        raise TeachingRoleBindingError("teaching_angle_sum_terms_invalid")
    value = _math(condition_value.get("value") or "")
    left = _difference_angle(
        terms[0],
        str(equality_value.get("reference_angle") or ""),
    )
    right = terms[1]
    if not left or not _valid_angle_name(right):
        raise TeachingRoleBindingError("teaching_equal_angle_roles_invalid")
    condition = f"∠{terms[0]}＋∠{terms[1]}＝{value}°"
    equality = f"∠{left}＝∠{right}"
    reference = str(equality_value.get("reference_angle") or "")
    reference_value = _math(
        equality_value.get("reference_angle_value") or condition_value.get("value")
    )
    reference_proof = _reference_angle_proof(
        reference,
        reference_value=reference_value,
        snapshot=snapshot,
        source=source,
    )
    dynamic = [
        *reference_proof,
        f"∵∠{reference}＝∠{terms[0]}＋∠{left}，且 {condition}",
        f"∴两式消去公共角 ∠{terms[0]}，得 {equality}",
    ]
    return {
        "condition": condition,
        "angle_equality": equality,
        "derive_items": tuple(dynamic),
    }


def _axis_intercept_from_equal_angle(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    equality_item = _one_input(source, "angle_equality")
    assert equality_item is not None
    equality = _referenced_angle_equality(equality_item, snapshot)
    point = _output_point(source, "point")
    label = _anonymous_point_output_label(source, snapshot)
    match = re.fullmatch(r"∠([^＝]+)＝∠(.+)", equality)
    if match is None:
        raise TeachingRoleBindingError("teaching_angle_equality_display_invalid")
    left, right = match.groups()
    if len(left) != 3 or len(right) != 3:
        raise TeachingRoleBindingError("teaching_angle_equality_points_invalid")

    target_angle = f"{left[:2]}{label}"
    origin_label = left[0]
    x_axis_label = left[1]
    reference_x_label = right[0]
    y_axis_label = right[1]
    right_origin_label = right[2]
    if right_origin_label != origin_label:
        raise TeachingRoleBindingError("teaching_equal_angle_origin_mismatch")

    origin = _snapshot_point_pair(origin_label, snapshot, source=source)
    x_axis_point = _snapshot_point_pair(x_axis_label, snapshot, source=source)
    reference_x_point = _snapshot_point_pair(
        reference_x_label,
        snapshot,
        source=source,
    )
    y_axis_point = _snapshot_point_pair(y_axis_label, snapshot, source=source)
    ob = _point_distance(origin, x_axis_point)
    of = _point_distance(origin, point)
    ao = _point_distance(origin, reference_x_point)
    co = _point_distance(origin, y_axis_point)
    ray_point = left[2]
    position = _axis_position_statement(label, point, origin=origin)
    dynamic = (
        f"∵{x_axis_label}、{ray_point}、{label} 共线，所以 "
        f"∠{target_angle}＝∠{left}＝∠{right}",
        f"∵Rt△{x_axis_label}{origin_label}{label} 与 "
        f"Rt△{reference_x_label}{origin_label}{y_axis_label} 均为直角三角形",
        f"∴tan∠{target_angle}＝{origin_label}{label}/{origin_label}{x_axis_label}，"
        f"tan∠{right}＝{reference_x_label}{origin_label}/{y_axis_label}{origin_label}",
        f"∴{origin_label}{label}/{origin_label}{x_axis_label}＝"
        f"{reference_x_label}{origin_label}/{y_axis_label}{origin_label}",
        f"计算{origin_label}{x_axis_label}＝{_math(ob)}，"
        f"{reference_x_label}{origin_label}＝{_math(ao)}，"
        f"{y_axis_label}{origin_label}＝{_math(co)}，所以 "
        f"{origin_label}{label}＝{_math(of)}",
        f"∵{position}",
        f"∴{_point_display(label, point)}",
    )
    return {
        "angle_equality": equality,
        "point": _point_display(label, point),
        "derive_items": dynamic,
    }


def _line_parabola_intersection(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    line_p1_item = _one_input(source, "line_p1")
    line_p2_item = _one_input(source, "line_p2")
    assert line_p1_item is not None and line_p2_item is not None
    line_p1_pair = _point_pair(line_p1_item.get("value"))
    line_p2_pair = _point_pair(line_p2_item.get("value"))
    if line_p1_pair is None or line_p2_pair is None:
        raise TeachingRoleBindingError("teaching_line_points_invalid")
    line_p1 = _input_point_display(source, "line_p1", snapshot)
    line_p2 = _input_point_display(source, "line_p2", snapshot)
    known_point = _input_point_display(source, "known_point", snapshot)
    parabola_expr = _input_expr(source, "parabola")
    parabola = f"y＝{_quadratic_expression_display(parabola_expr)}"
    line_equation, line_expr = _line_equation(line_p1_pair, line_p2_pair)
    target_pair = _output_point(source, "point")
    target = _point_display(_output_label(source, "point"), target_pair)
    known_pair = _point_pair(_one_input(source, "known_point").get("value"))
    if line_expr is None or known_pair is None:
        raise TeachingRoleBindingError("teaching_line_parabola_equation_invalid")
    x = sp.Symbol("x")
    intersection_equation = sp.Eq(line_expr, parabola_expr)
    roots = tuple(
        sorted(
            (sp.simplify(item) for item in sp.solve(intersection_equation, x)),
            key=sp.default_sort_key,
        )
    )
    return {
        "line_p1": line_p1,
        "line_p2": line_p2,
        "parabola": parabola,
        "known_point": known_point,
        "point": target,
        "derive_items": (
            f"作连接 {line_p1}、{line_p2}，得直线 {line_equation}",
            f"计算联立 {line_equation} 与 {parabola}，得 "
            + " 或 ".join(f"x＝{_math(root)}" for root in roots),
            f"∵{known_point} 是已知交点，排除 x＝{_math(known_pair[0])}",
            f"∴另一交点为 {target}",
        ),
    }


def _quadratic_vertex(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    parabola = _input_expr(source, "parabola")
    point = _output_point(source, "point")
    output_label = _output_label(source, "point")
    semantic_label = _semantic_problem_point_label(
        source,
        snapshot,
        definition="vertex",
    )
    label = (
        semantic_label
        if semantic_label and output_label not in _problem_point_labels(snapshot)
        else output_label or semantic_label
    )
    vertex_form = _completed_square_expression(parabola)
    parabola_display = _quadratic_expression_display(parabola)
    point_display = _point_display(label, point)
    if vertex_form:
        calculation = f"配方，得 y＝{vertex_form}"
    else:
        x = sp.Symbol("x")
        poly = sp.Poly(parabola, x)
        a = sp.simplify(poly.coeff_monomial(x**2))
        b = sp.simplify(poly.coeff_monomial(x))
        calculation = (
            f"由 x_顶＝－({_math(b)})/[2×({_math(a)})]"
            f"＝{_math(point[0])}，"
            f"代入得 y_顶＝{_math(point[1])}"
        )
        if a == 0:
            raise TeachingRoleBindingError("teaching_quadratic_vertex_not_quadratic")
    return {
        "parabola_vertex_form": f"y＝{vertex_form or parabola_display}",
        "vertex_point": point_display,
        "derive_items": (
            f"∵抛物线为 y＝{parabola_display}",
            f"计算{calculation}",
            f"∴顶点为 {point_display}",
        ),
    }


def _quadratic_axis_point(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    point = _output_point(source, "point")
    target = _output_label(source, "point")
    return {
        "target": target,
        "axis_equation": f"x＝{_math(point[0])}",
        "parameterized_point": _point_display(target, point),
    }


def _square_adjacent_vertex(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    square_item = _one_input(source, "square")
    square = square_item.get("value")
    if not isinstance(square, Mapping):
        raise TeachingRoleBindingError("teaching_square_value_invalid")
    vertices = tuple(str(value) for value in square.get("vertices") or ())
    if len(vertices) != 4:
        raise TeachingRoleBindingError("teaching_square_vertices_invalid")
    base_item = _one_input(source, "side_start")
    side_item = _one_input(source, "side_end")
    base = _point_pair(base_item.get("value"))
    side_end = _point_pair(side_item.get("value"))
    adjacent = _output_point(source, "adjacent_vertex")
    base_label = _point_label(base_item)
    side_label = _point_label(side_item)
    target_label = _output_label(source, "adjacent_vertex")
    if base is None or side_end is None or not all((base_label, side_label, target_label)):
        raise TeachingRoleBindingError("teaching_square_points_invalid")

    reference_line = "x轴" if sp.simplify(base[1]) == 0 else "过已知顶点的水平线"
    side_projection = (sp.simplify(side_end[0]), sp.simplify(base[1]))
    target_projection = (sp.simplify(adjacent[0]), sp.simplify(base[1]))
    used = set(vertices) | _problem_point_labels(snapshot)
    side_projection_label = _existing_projection_label(
        source,
        point_label=side_label,
        pair=side_projection,
        snapshot=snapshot,
    )
    side_projection_is_existing = bool(side_projection_label)
    if not side_projection_label:
        side_projection_label = _next_point_label(used)
    used.add(side_projection_label)
    target_projection_label = _existing_projection_label(
        source,
        point_label=target_label,
        pair=target_projection,
        snapshot=snapshot,
    )
    target_projection_is_existing = bool(target_projection_label)
    if not target_projection_label:
        target_projection_label = _next_point_label(used)

    if side_projection_is_existing:
        construction = (
            f"{target_label}{target_projection_label}⊥{reference_line}于 {target_projection_label}"
        )
    elif target_projection_is_existing:
        construction = (
            f"{side_label}{side_projection_label}⊥{reference_line}于 {side_projection_label}"
        )
    else:
        construction = (
            f"{side_label}{side_projection_label}⊥{reference_line}于 {side_projection_label}，"
            f"{target_label}{target_projection_label}⊥{reference_line}于 {target_projection_label}"
        )
    target_horizontal = _positive_math(target_projection[0] - base[0])
    side_vertical = _positive_math(side_end[1] - base[1])
    target_vertical = _positive_math(adjacent[1] - base[1])
    side_horizontal = _positive_math(side_end[0] - base[0])
    return {
        "target_label": target_label,
        "projection_construction": construction,
        "square_name": "".join(vertices),
        "side_equal_statement": f"{base_label}{side_label}＝{base_label}{target_label}",
        "square_right_angle_statement": f"∠{side_label}{base_label}{target_label}＝90°",
        "projection_right_angles": (
            f"∠{side_label}{side_projection_label}{base_label}"
            f"＝∠{target_label}{target_projection_label}{base_label}＝90°"
        ),
        "matching_angle_statement": (
            f"∠{side_label}{base_label}{side_projection_label}"
            f"＝∠{base_label}{target_label}{target_projection_label}"
        ),
        "triangle_congruence": (
            f"Rt△{base_label}{side_label}{side_projection_label}"
            f"≌Rt△{target_label}{base_label}{target_projection_label}"
        ),
        "length_correspondence": (
            f"{base_label}{target_projection_label}＝{side_projection_label}{side_label}"
            f"＝{target_horizontal or side_vertical}，"
            f"{target_label}{target_projection_label}＝{base_label}{side_projection_label}"
            f"＝{target_vertical or side_horizontal}"
        ),
        "target_position_condition": _square_position_condition(
            target_label,
            square,
            vertices,
        ),
        "target_point": _point_display(target_label, adjacent),
    }


def _curve_point_candidates(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    target_item = _one_input(source, "target_point")
    curve_item = _one_input(source, "curve_point")
    parabola = _input_expr(source, "parabola")
    target_pair = _point_pair(target_item.get("value"))
    curve_pair = _point_pair(curve_item.get("value"))
    candidates = _point_list(_output_value(source, "candidates"))
    target_label = _point_label(target_item)
    curve_label = _point_label(curve_item)
    if target_pair is None or curve_pair is None or not candidates:
        raise TeachingRoleBindingError("teaching_curve_candidates_invalid")
    parameter = _shared_parameter(target_pair, curve_pair, parabola)
    x_arg, curve_y = curve_pair
    x = sp.Symbol("x")
    poly = sp.Poly(parabola - curve_y, x)
    coefficients = tuple(
        sp.simplify(poly.coeff_monomial(power))
        for power in (x**2, x, 1)
    )
    if coefficients[0].could_extract_minus_sign():
        coefficients = tuple(sp.simplify(-value) for value in coefficients)
    parameter_values = [
        value
        for candidate in candidates
        if (value := _parameter_value(target_pair, candidate, parameter)) is not None
    ]
    candidates = _sort_candidates(candidates, target_pair, parameter)
    parameter_values = [
        value
        for candidate in candidates
        if (value := _parameter_value(target_pair, candidate, parameter)) is not None
    ]
    target_display = _point_display(target_label, target_pair)
    curve_display = _point_display(curve_label, curve_pair)
    curve_equation = f"y＝{_quadratic_expression_display(parabola)}"
    substitution_equation = (
        f"{_math(curve_y)}＝{_quadratic_substitution_display(parabola, x_arg)}"
    )
    parameter_equation = (
        f"{_quadratic_in_variable_display(coefficients, _math(x_arg))}＝0"
    )
    parameter_solutions = _solutions_display(str(parameter), parameter_values)
    target_candidates = " 或 ".join(
        _point_display(target_label, point) for point in candidates
    )
    return {
        "target_label": target_label,
        "curve_kind": "抛物线",
        "curve_point": curve_display,
        "curve_equation": curve_equation,
        "substitution_equation": substitution_equation,
        "parameter_equation": parameter_equation,
        "parameter_solutions": parameter_solutions,
        "target_candidates": target_candidates,
        "derive_items": (
            f"∵{target_display} 与 {curve_display} 都由同一参数 "
            f"{_math(parameter)} 表示",
            f"∵{curve_display} 在 {curve_equation} 上",
            f"∴代入曲线点坐标，得 {substitution_equation}",
            f"计算整理为 {parameter_equation}",
            f"计算解得 {parameter_solutions}",
            f"∴把参数值代回 {target_display}，得 {target_candidates}",
        ),
    }


def _parameter_from_expression(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    expression = _one_input(source, "expression")
    condition = _one_input(source, "minimum_value", required=False)
    if condition is None:
        condition = _one_input(source, "condition")
    target = condition.get("value")
    if isinstance(target, Mapping):
        target = target.get("value")
    parameter_item = _one_input(source, "parameter")
    parameter = _item_display(parameter_item)
    output = _output_value(source, "parameter_value")
    equation_displays = _calculation_equation_displays(source)
    equation = (
        equation_displays[0]
        if equation_displays
        else f"{_math(expression.get('value'))}＝{_math(target)}"
    )
    expression_value = _expr(expression.get("value"))
    target_value = _expr(target)
    candidates = _real_calculation_solutions(source, parameter)
    branch_derivation = _piecewise_parameter_derivation(
        expression_value,
        target=target_value,
        parameter=parameter,
    )
    if branch_derivation:
        dynamic = list(branch_derivation)
    else:
        dynamic = [
            f"∵题设要求 {equation}",
            (
                f"计算解方程，得 "
                f"{_solution_candidates_display(parameter, candidates)}"
                if candidates
                else f"计算解关于 {parameter} 的方程"
            ),
        ]
    if len(candidates) > 1:
        filter_context = _parameter_filter_context(source, snapshot, parameter)
        dynamic.append(
            f"∵根据 {filter_context}，保留 "
            f"{parameter}＝{_math(output)}"
        )
    dynamic.append(f"∴{parameter}＝{_math(output)}")
    return {
        "expression": _math(expression.get("value")),
        "target_value": _math(target),
        "parameter": parameter,
        "parameter_value": _math(output),
        "derive_items": tuple(dynamic),
    }


def _evaluate_point(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    point_item = _one_input(source, "point")
    value_item = _one_input(source, "parameter_value")
    output = _output_point(source, "evaluated_point")
    label = _output_label(source, "evaluated_point") or _point_label(point_item)
    source_pair = _point_pair(point_item.get("value"))
    if source_pair is None:
        raise TeachingRoleBindingError("teaching_evaluate_point_input_invalid")
    symbols = sorted(
        set().union(*(value.free_symbols for value in source_pair)),
        key=lambda value: value.name,
    )
    parameter = symbols[0].name if len(symbols) == 1 else ""
    if not parameter:
        ref = value_item.get("ref")
        if isinstance(ref, Mapping) and ref.get("kind") == "source":
            parameter = str(ref.get("ref") or "")
    source_display = str(point_item.get("display") or "").strip()
    if source_display.startswith("("):
        source_display = label + source_display
    output_item = source.outputs.get("evaluated_point") or {}
    output_display = str(output_item.get("display") or "").strip()
    if output_display.startswith("("):
        output_display = label + output_display
    source_point_display = source_display or _raw_point_display(label, source_pair)
    evaluated_point_display = output_display or _raw_point_display(label, output)
    coordinate_calculation = (
        f"x_{label}＝{_math(source_pair[0])}＝{_math(output[0])}，"
        f"y_{label}＝{_math(source_pair[1])}＝{_math(output[1])}"
    )
    return {
        "source_point": source_point_display,
        "parameter": parameter,
        "parameter_value": _math(value_item.get("value")),
        "evaluated_point": evaluated_point_display,
        "derive_items": (
            f"∵{source_point_display}，{parameter}＝{_math(value_item.get('value'))}",
            f"计算将 {parameter}＝{_math(value_item.get('value'))} 代入："
            f"{coordinate_calculation}",
            f"∴{evaluated_point_display}",
        ),
    }


def _quadratic_axis_x_intercept(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    point = _output_point(source, "axis_point")
    label = _output_label(source, "axis_point")
    return {
        "axis_equation": f"x＝{_math(point[0])}",
        "axis_point": _point_display(label, point),
        "target_label": label,
    }


def _translated_point(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    source_item = _one_input(source, "source")
    source_pair = _point_pair(source_item.get("value"))
    target_pair = _output_point(source, "point")
    if source_pair is None:
        raise TeachingRoleBindingError("teaching_translation_source_invalid")
    source_label = _point_label(source_item)
    target_label = _output_label(source, "point")
    vector = (
        sp.simplify(target_pair[0] - source_pair[0]),
        sp.simplify(target_pair[1] - source_pair[1]),
    )
    return {
        "source_point": _point_display(source_label, source_pair),
        "target_point": _point_display(target_label, target_pair),
        "vector": f"({_math(vector[0])},{_math(vector[1])})",
        "derive_items": (
            f"∵{_point_display(source_label, source_pair)} 按向量 "
            f"({_math(vector[0])},{_math(vector[1])}) 平移",
            f"计算横、纵坐标分别相加："
            f"({_math(source_pair[0])}＋({_math(vector[0])})，"
            f"{_math(source_pair[1])}＋({_math(vector[1])}))",
            f"∴{_point_display(target_label, target_pair)}",
        ),
    }


def _distance_between_points(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    p1_item = _one_input(source, "p1")
    p2_item = _one_input(source, "p2")
    assert p1_item is not None and p2_item is not None
    p1 = _point_pair(p1_item.get("value"))
    p2 = _point_pair(p2_item.get("value"))
    if p1 is None or p2 is None:
        raise TeachingRoleBindingError("teaching_distance_points_invalid")
    p1_display = _item_display(p1_item)
    p2_display = _item_display(p2_item)
    p1_label = _point_label(p1_item)
    p2_label = _point_label(p2_item)
    segment = f"{p1_label}{p2_label}" if p1_label and p2_label else "两点距离"
    distance = _expr(_output_value(source, "distance"))
    distance_display = _item_display(
        source.outputs.get("evaluated_distance")
        or source.outputs.get("distance")
        or {}
    )
    formula = (
        f"{segment}＝√[({_math(p2[0])}－({_math(p1[0])}))²＋"
        f"({_math(p2[1])}－({_math(p1[1])}))²]"
    )
    dynamic = [
        f"∵两端点为 {p1_display} 与 {p2_display}",
        f"计算由两点距离公式，{formula}＝{_math(distance)}",
    ]
    parameter_identity_item = _one_input(source, "parameter", required=False)
    parameter_value_item = _one_input(
        source,
        "parameter_value",
        required=False,
    )
    if (
        parameter_value_item is not None
        and "evaluated_distance" in source.outputs
    ):
        parameter = _parameter_name_from_bound_inputs(
            parameter_item=parameter_identity_item,
            value_item=parameter_value_item,
        )
        dynamic.append(
            f"计算代入 {parameter}＝{_math(parameter_value_item.get('value'))}，"
            f"得 {distance_display}"
        )
    dynamic.append(f"∴{segment}＝{distance_display}")
    return {
        "p1": p1_display,
        "p2": p2_display,
        "distance": distance_display,
        "derive_items": tuple(dynamic),
    }


def _equal_length_ray_point(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    anchor_item = _one_input(source, "anchor")
    reference_item = _one_input(source, "reference_point")
    ray_item = _one_input(source, "ray_point")
    assert (
        anchor_item is not None
        and reference_item is not None
        and ray_item is not None
    )
    anchor = _point_pair(anchor_item.get("value"))
    reference = _point_pair(reference_item.get("value"))
    ray_point = _point_pair(ray_item.get("value"))
    target = _output_point(source, "point")
    if anchor is None or reference is None or ray_point is None:
        raise TeachingRoleBindingError("teaching_equal_length_ray_points_invalid")
    anchor_label = _point_label(anchor_item)
    reference_label = _point_label(reference_item)
    ray_label = _point_label(ray_item)
    target_label = _output_label(source, "point")
    reference_length = _point_distance(anchor, reference)
    target_display = _point_display(target_label, target)
    return {
        "anchor": _point_display(anchor_label, anchor),
        "reference_point": _point_display(reference_label, reference),
        "ray_point": _point_display(ray_label, ray_point),
        "point": target_display,
        "derive_items": (
            f"∵射线 {anchor_label}{ray_label} 由 "
            f"{_point_display(anchor_label, anchor)}、"
            f"{_point_display(ray_label, ray_point)} 确定",
            f"计算参考线段 {anchor_label}{reference_label}＝{_math(reference_length)}",
            f"作在射线 {anchor_label}{ray_label} 上截取 "
            f"{anchor_label}{target_label}＝{anchor_label}{reference_label}",
            f"∴{target_display}",
        ),
    }


def _line_intersection(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    items = {
        name: _one_input(source, name)
        for name in ("line1_p1", "line1_p2", "line2_p1", "line2_p2")
    }
    pairs = {
        name: _point_pair(item.get("value")) if item is not None else None
        for name, item in items.items()
    }
    if any(pair is None for pair in pairs.values()):
        raise TeachingRoleBindingError("teaching_line_intersection_points_invalid")
    line1, _ = _line_equation(
        _require_point_pair(pairs["line1_p1"]),
        _require_point_pair(pairs["line1_p2"]),
    )
    line2, _ = _line_equation(
        _require_point_pair(pairs["line2_p1"]),
        _require_point_pair(pairs["line2_p2"]),
    )
    intersection_pair = _output_point(source, "intersection")
    intersection = _point_display(
        _output_label(source, "intersection"),
        intersection_pair,
    )
    displays = {
        name: _item_display(item)
        for name, item in items.items()
        if item is not None
    }
    return {
        **displays,
        "intersection": intersection,
        "derive_items": (
            f"∵第一条直线经过 {displays['line1_p1']}、{displays['line1_p2']}，"
            f"其方程为 {line1}",
            f"∵第二条直线经过 {displays['line2_p1']}、{displays['line2_p2']}，"
            f"其方程为 {line2}",
            f"计算联立 {line1} 与 {line2}，解得 "
            f"x＝{_math(intersection_pair[0])}，y＝{_math(intersection_pair[1])}",
            f"∴交点为 {intersection}",
        ),
    }


def _point_on_parabola_at_x(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    parabola = _input_expr(source, "parabola")
    point = _output_point(source, "point")
    label = _output_label(source, "point")
    curve_display = _quadratic_expression_display(parabola)
    substitution = _quadratic_substitution_display(parabola, point[0])
    point_display = _point_display(label, point)
    return {
        "parabola": f"y＝{curve_display}",
        "point": point_display,
        "derive_items": (
            f"∵{label or '目标点'} 在 y＝{curve_display} 上，且 x＝{_math(point[0])}",
            f"计算代入横坐标，y＝{substitution}＝{_math(point[1])}",
            f"∴{point_display}",
        ),
    }


def _quadratic_axis_from_relation(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    relation_item = _one_input(source, "coefficient_relation")
    assert relation_item is not None
    relation = _item_display(relation_item)
    raw = relation_item.get("value")
    equation_text = raw.get("equation") if isinstance(raw, Mapping) else raw
    equation = _parse_equation(equation_text)
    axis_point = _output_point(source, "axis_point")
    axis_display = _point_display(_output_label(source, "axis_point"), axis_point)
    substitution = ""
    if equation is not None:
        b = sp.Symbol("b")
        solutions = sp.solve(equation, b)
        if len(solutions) == 1:
            substitution = f"由 {relation} 得 b＝{_math(solutions[0])}，"
    return {
        "coefficient_relation": relation,
        "axis_point": axis_display,
        "derive_items": (
            "∵二次函数的对称轴为 x＝－b/(2a)",
            f"计算{substitution}代入得 x＝{_math(axis_point[0])}",
            f"∴对称轴与 x 轴交于 {axis_display}",
        ),
    }


def _evaluate_expression_at_parameter(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    expression_item = _one_input(source, "expression")
    parameter_item = _one_input(source, "parameter", required=False)
    value_item = _one_input(source, "parameter_value")
    assert expression_item is not None and value_item is not None
    output_name, output_item = next(iter(source.outputs.items()))
    parameter = _parameter_name_from_bound_inputs(
        parameter_item=parameter_item,
        value_item=value_item,
    )
    expression_display = _item_display(expression_item)
    evaluated_display = _item_display(output_item)
    return {
        "expression": expression_display,
        "parameter": parameter,
        "parameter_value": _math(value_item.get("value")),
        "evaluated_result": evaluated_display,
        "derive_items": (
            f"∵{parameter}＝{_math(value_item.get('value'))}",
            f"计算把 {parameter}＝{_math(value_item.get('value'))} 代入 "
            f"{expression_display}，化简得 {evaluated_display}",
            f"∴{evaluated_display}",
        ),
        output_name: evaluated_display,
    }


def _one_input(
    source: TeachingSource,
    name: str,
    *,
    required: bool = True,
) -> Mapping[str, Any] | None:
    values = source.inputs.get(name, ())
    if len(values) == 1:
        return values[0]
    if not values and not required:
        return None
    raise TeachingRoleBindingError(
        f"teaching_input_cardinality_invalid: {source.source_step_id}.{name}"
    )


def _input_items(
    source: TeachingSource,
    *names: str,
) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for name in names:
        for item in source.inputs.get(name, ()):
            key = (
                str(item.get("ref") or ""),
                repr(item.get("value")),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return tuple(result)


def _quadratic_constraint_displays(
    source: TeachingSource,
    *,
    coefficients: Any,
) -> tuple[str, ...]:
    """Render the actual coefficient facts without leaking input ref spelling."""

    result: list[str] = []
    coefficient_values = (
        {
            str(name): _expr(value)
            for name, value in coefficients.items()
        }
        if isinstance(coefficients, Mapping)
        else {}
    )
    for item in source.inputs.get("known_coefficients", ()):
        value = _expr(item.get("value"))
        name = _coefficient_name_for_input(item, coefficient_values)
        if name:
            result.append(f"{name}＝{_math(value)}")
        else:
            result.append(f"已知系数取值为 {_math(value)}")
    for item in _input_items(
        source,
        "coefficient_relation",
        "extra_equation",
        "parameter_value",
    ):
        result.append(_item_display(item))
    return tuple(dict.fromkeys(result))


def _quadratic_known_substitutions(
    source: TeachingSource,
    *,
    coefficients: Any,
) -> dict[sp.Symbol, sp.Expr]:
    if not isinstance(coefficients, Mapping):
        return {}
    coefficient_values = {
        str(name): _expr(value)
        for name, value in coefficients.items()
    }
    substitutions: dict[sp.Symbol, sp.Expr] = {}
    for item in source.inputs.get("known_coefficients", ()):
        value = _expr(item.get("value"))
        name = _coefficient_name_for_input(item, coefficient_values)
        if name:
            substitutions[sp.Symbol(name)] = value
    return substitutions


def _quadratic_relation_derivation_displays(
    source: TeachingSource,
    *,
    coefficients: Any,
    known_substitutions: Mapping[sp.Symbol, sp.Expr],
) -> tuple[str, ...]:
    """Explain coefficients derived from typed relations, not only final substitution.

    Runtime has already verified the returned coefficient mapping.  This projector
    identifies which coefficients were supplied directly and which were obtained
    from a public coefficient equation, then exposes that missing algebraic link to
    the student.  It never infers a coefficient name from display text.
    """

    if not isinstance(coefficients, Mapping):
        return ()
    relation_items = _input_items(
        source,
        "coefficient_relation",
        "extra_equation",
    )
    equations = tuple(
        equation
        for item in relation_items
        if (
            equation := _parse_equation(
                item.get("value", {}).get("equation")
                if isinstance(item.get("value"), Mapping)
                else item.get("value")
            )
        )
        is not None
    )
    if not equations:
        return ()

    relation_symbols = set().union(*(equation.free_symbols for equation in equations))
    output_values = {
        sp.Symbol(str(name)): _expr(value)
        for name, value in coefficients.items()
    }
    derived = {
        symbol: value
        for symbol, value in output_values.items()
        if symbol in relation_symbols
        and symbol not in known_substitutions
        and sp.simplify(value - symbol) != 0
    }
    if not derived:
        return ()

    # Fail loudly if a future runtime returns a mapping that does not actually
    # satisfy the public equations this teaching line cites.
    for equation in equations:
        residual = sp.simplify(
            (equation.lhs - equation.rhs).subs(output_values, simultaneous=True)
        )
        if residual != 0:
            raise TeachingRoleBindingError(
                "teaching_quadratic_relation_output_mismatch: "
                f"{source.source_step_id}"
            )

    known_used = {
        symbol: value
        for symbol, value in known_substitutions.items()
        if symbol in relation_symbols
    }
    relation_text = "，".join(_equation_display(equation) for equation in equations)
    known_text = "，".join(
        f"{symbol.name}＝{_math(value)}"
        for symbol, value in sorted(known_used.items(), key=lambda item: item[0].name)
    )
    derived_text = "，".join(
        f"{symbol.name}＝{_math(value)}"
        for symbol, value in sorted(derived.items(), key=lambda item: item[0].name)
    )
    action = (
        f"将 {known_text} 代入 {relation_text}"
        if known_text
        else f"由 {relation_text}"
    )
    return (f"计算{action}，解得 {derived_text}",)


def _matching_quadratic_source_expression(
    snapshot: ExplanationSnapshot,
    *,
    coefficients: Any,
    result: sp.Expr,
) -> sp.Expr | None:
    """Find the public quadratic template whose verified coefficients yield result."""

    if not isinstance(coefficients, Mapping):
        return None
    substitutions = {
        sp.Symbol(str(name)): _expr(value) for name, value in coefficients.items()
    }
    x = sp.Symbol("x")
    matches: list[sp.Expr] = []
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, Mapping) or entity.get("entity_type") != "function":
            continue
        raw_expression = entity.get("expression")
        if raw_expression in (None, ""):
            continue
        expression = _expr(raw_expression)
        try:
            if sp.Poly(expression, x).degree() != 2:
                continue
        except sp.PolynomialError:
            continue
        if sp.simplify(expression.subs(substitutions) - result) != 0:
            continue
        if not any(sp.simplify(expression - existing) == 0 for existing in matches):
            matches.append(expression)
    return matches[0] if len(matches) == 1 else None


def _coefficient_name_for_input(
    item: Mapping[str, Any],
    coefficient_values: Mapping[str, sp.Expr],
) -> str:
    """Resolve a known coefficient by public SourceRef identity, then value."""

    value = _expr(item.get("value"))
    ref = item.get("ref")
    if isinstance(ref, Mapping) and ref.get("kind") == "source":
        tokens = tuple(
            token
            for token in re.split(r"[^A-Za-z0-9]+|_", str(ref.get("ref") or ""))
            if token
        )
        identity_matches = [
            name
            for name, candidate in coefficient_values.items()
            if name in tokens and sp.simplify(candidate - value) == 0
        ]
        if len(identity_matches) == 1:
            return identity_matches[0]
    value_matches = [
        name
        for name, candidate in coefficient_values.items()
        if sp.simplify(candidate - value) == 0
    ]
    return value_matches[0] if len(value_matches) == 1 else ""


def _first_input_display(source: TeachingSource, *names: str) -> str:
    matches = [
        _item_display(item)
        for name in names
        for item in source.inputs.get(name, ())
    ]
    if len(matches) != 1:
        raise TeachingRoleBindingError(
            "teaching_input_alias_cardinality_invalid: "
            f"{source.source_step_id}:{names}"
        )
    return matches[0]


def _parameter_output_target(source: TeachingSource) -> str:
    target = str(source.output_targets.get("parameter_value") or "")
    if target:
        return target.rsplit(":", 1)[-1]
    for calculation in source.calculations:
        if str(calculation.get("kind") or "") != "solution":
            continue
        target = str(calculation.get("target") or "")
        if target:
            return target
    raise TeachingRoleBindingError(
        f"teaching_parameter_identity_missing: {source.source_step_id}"
    )


def _snapshot_point_pair(
    label: str,
    snapshot: ExplanationSnapshot,
    *,
    source: TeachingSource | None = None,
) -> tuple[sp.Expr, sp.Expr]:
    pairs: list[tuple[sp.Expr, sp.Expr]] = []
    owners = teaching_source_owners(snapshot.root_scope)
    current_owner = (
        owners.get(source.source_step_id, ("", None))
        if source
        else ("", None)
    )
    current_scope = current_owner[0]
    dependency_steps = _explicit_dependency_step_ids(source) if source else set()
    parent_by_scope = _scope_parent_map(snapshot)

    def add(pair: tuple[sp.Expr, sp.Expr]) -> None:
        if not any(_same_point(pair, existing) for existing in pairs):
            pairs.append(pair)

    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, Mapping) or str(entity.get("name") or "") != label:
            continue
        entity_scope = str(entity.get("scope_id") or "problem")
        if current_scope and not _scope_is_visible(
            entity_scope,
            from_scope=current_scope,
            parent_by_scope=parent_by_scope,
        ):
            continue
        pair = _point_pair(entity.get("coordinate"))
        if pair is None and entity.get("definition") == "coordinate_origin":
            pair = (sp.Integer(0), sp.Integer(0))
        if pair is not None:
            add(pair)
    for candidate in iter_teaching_sources(snapshot.root_scope):
        candidate_owner = owners.get(candidate.source_step_id, ("", None))
        if (
            current_scope
            and candidate.source_step_id not in dependency_steps
            and not _teaching_owner_is_visible(
                candidate_owner,
                from_owner=current_owner,
                parent_by_scope=parent_by_scope,
            )
        ):
            continue
        for name, result in candidate.outputs.items():
            target = str(candidate.output_targets.get(name) or "").rsplit(":", 1)[-1]
            if target != label and _point_label(result) != label:
                continue
            pair = _point_pair(result.get("value"))
            if pair is not None:
                add(pair)
        for items in candidate.inputs.values():
            for item in items:
                if _point_label(item) != label:
                    continue
                pair = _point_pair(item.get("value"))
                if pair is not None:
                    add(pair)
    if len(pairs) != 1:
        raise TeachingRoleBindingError(
            "teaching_point_identity_value_ambiguous: "
            f"label={label}, count={len(pairs)}"
        )
    return pairs[0]


def _semantic_problem_point_label(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
    *,
    definition: str,
) -> str:
    """Resolve a public point role from ProblemIR semantics, never from ID text."""

    owners = teaching_source_owners(snapshot.root_scope)
    current_scope, _ = owners.get(source.source_step_id, ("", None))
    parent_by_scope = _scope_parent_map(snapshot)
    scope_rank: dict[str, int] = {}
    cursor: str | None = current_scope
    distance = 0
    while cursor is not None:
        scope_rank[cursor] = distance
        cursor = parent_by_scope.get(cursor)
        distance += 1
    scope_rank.setdefault("problem", distance)

    candidates: list[tuple[int, str]] = []
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, Mapping):
            continue
        if (
            entity.get("entity_type") != "point"
            or entity.get("definition") != definition
        ):
            continue
        scope_ref = str(entity.get("scope_id") or "problem")
        label = str(entity.get("name") or "")
        if (
            not re.fullmatch(r"[A-Z](?:[0-9]+|[′']+)?", label)
            or scope_ref not in scope_rank
        ):
            continue
        candidates.append((scope_rank[scope_ref], label))
    if not candidates:
        return ""
    nearest = min(rank for rank, _ in candidates)
    labels = sorted({label for rank, label in candidates if rank == nearest})
    return labels[0] if len(labels) == 1 else ""


def _parameter_filter_context(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
    parameter: str,
) -> str:
    owners = teaching_source_owners(snapshot.root_scope)
    current_scope, _ = owners.get(source.source_step_id, ("", None))
    parent_by_scope = _scope_parent_map(snapshot)
    operator_display = {
        ">": "＞",
        ">=": "≥",
        "<": "＜",
        "<=": "≤",
        "=": "＝",
        "==": "＝",
        "!=": "≠",
    }
    constraints: list[str] = []
    for fact in (snapshot.problem or {}).get("facts") or ():
        if not isinstance(fact, Mapping) or fact.get("type") != "symbol_constraint":
            continue
        subject = str(fact.get("subject") or "").rsplit(":", 1)[-1]
        fact_scope = str(fact.get("scope_id") or "problem")
        if subject != parameter or not _scope_is_visible(
            fact_scope,
            from_scope=current_scope,
            parent_by_scope=parent_by_scope,
        ):
            continue
        operator = operator_display.get(str(fact.get("operator") or ""))
        if operator and fact.get("value") not in (None, ""):
            constraints.append(f"{parameter}{operator}{_math(fact['value'])}")
    return "、".join(dict.fromkeys(constraints)) or "题设中的参数范围"


def _scope_parent_map(snapshot: ExplanationSnapshot) -> dict[str, str | None]:
    result: dict[str, str | None] = {"problem": None}

    def visit(scope: Any, parent: str | None) -> None:
        result[scope.scope_ref] = parent
        for child in scope.children:
            visit(child, scope.scope_ref)

    root_parent = None if snapshot.root_scope.scope_ref == "problem" else "problem"
    visit(snapshot.root_scope, root_parent)
    return result


def _scope_is_visible(
    candidate_scope: str,
    *,
    from_scope: str,
    parent_by_scope: Mapping[str, str | None],
) -> bool:
    cursor: str | None = from_scope
    while cursor is not None:
        if cursor == candidate_scope:
            return True
        cursor = parent_by_scope.get(cursor)
    return candidate_scope == "problem"


def _teaching_owner_is_visible(
    candidate_owner: tuple[str, str | None],
    *,
    from_owner: tuple[str, str | None],
    parent_by_scope: Mapping[str, str | None],
) -> bool:
    candidate_scope, candidate_goal = candidate_owner
    from_scope, from_goal = from_owner
    if not _scope_is_visible(
        candidate_scope,
        from_scope=from_scope,
        parent_by_scope=parent_by_scope,
    ):
        return False
    if candidate_scope == from_scope:
        return candidate_goal is None or candidate_goal == from_goal
    return candidate_goal is None


def _explicit_dependency_step_ids(source: TeachingSource) -> set[str]:
    result: set[str] = set()
    for items in source.inputs.values():
        for item in items:
            for key in ("ref", "resolved_from"):
                ref = item.get(key)
                if isinstance(ref, Mapping) and ref.get("kind") == "step_result":
                    step_id = str(ref.get("step_id") or "")
                    if step_id:
                        result.add(step_id)
    return result


def _output_value(source: TeachingSource, name: str) -> Any:
    item = source.outputs.get(name)
    if not isinstance(item, Mapping):
        raise TeachingRoleBindingError(
            f"teaching_output_missing: {source.source_step_id}.{name}"
        )
    return item.get("value")


def _output_expr(source: TeachingSource, name: str) -> sp.Expr:
    return _expr(_output_value(source, name))


def _input_expr(source: TeachingSource, name: str) -> sp.Expr:
    item = _one_input(source, name)
    assert item is not None
    return _expr(item.get("value"))


def _output_point(source: TeachingSource, name: str) -> tuple[sp.Expr, sp.Expr]:
    pair = _point_pair(_output_value(source, name))
    if pair is None:
        raise TeachingRoleBindingError(
            f"teaching_point_output_invalid: {source.source_step_id}.{name}"
        )
    return pair


def _output_label(source: TeachingSource, name: str) -> str:
    target = str(source.output_targets.get(name) or "")
    if target:
        return target.rsplit(":", 1)[-1]
    item = source.outputs.get(name)
    return _point_label(item or {})


def _input_point_display(
    source: TeachingSource,
    name: str,
    snapshot: ExplanationSnapshot,
) -> str:
    item = _one_input(source, name)
    assert item is not None
    pair = _point_pair(item.get("value"))
    if pair is None:
        raise TeachingRoleBindingError(
            f"teaching_point_input_invalid: {source.source_step_id}.{name}"
        )
    label = _point_label(item)
    ref = item.get("ref")
    if not label and isinstance(ref, Mapping) and ref.get("kind") == "step_result":
        producer_id = str(ref.get("step_id") or "")
        producer = next(
            (
                candidate
                for candidate in iter_teaching_sources(snapshot.root_scope)
                if candidate.source_step_id == producer_id
            ),
            None,
        )
        if producer is not None:
            label = _anonymous_point_output_label(producer, snapshot)
    return _point_display(label, pair) if label else f"({_math(pair[0])},{_math(pair[1])})"


def _find_point_input_by_label(
    source: TeachingSource,
    label: str,
) -> Mapping[str, Any] | None:
    matches = [
        item
        for items in source.inputs.values()
        for item in items
        if _point_label(item) == label and _point_pair(item.get("value")) is not None
    ]
    if len(matches) > 1:
        unique = {repr(item.get("value")) for item in matches}
        if len(unique) != 1:
            raise TeachingRoleBindingError(
                f"teaching_point_input_ambiguous: {source.source_step_id}.{label}"
            )
    return matches[0] if matches else None


def _anonymous_point_output_label(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> str:
    for output_name in source.outputs:
        label = _output_label(source, output_name)
        if label:
            return label
    if source.capability_id == "axis_intercept_from_equal_acute_angles":
        return _first_unused_point_label(_problem_point_labels(snapshot))
    return ""


def _referenced_angle_equality(
    item: Mapping[str, Any],
    snapshot: ExplanationSnapshot,
) -> str:
    ref = item.get("ref")
    if isinstance(ref, Mapping) and ref.get("kind") == "step_result":
        producer_id = str(ref.get("step_id") or "")
        producer = next(
            (
                candidate
                for candidate in iter_teaching_sources(snapshot.root_scope)
                if candidate.source_step_id == producer_id
            ),
            None,
        )
        if producer is not None and producer.capability_id == "angle_sum_equal_angle_candidates":
            return str(_angle_sum_equal_angle(producer, snapshot)["angle_equality"])
    value = item.get("value")
    if isinstance(value, Mapping):
        left = str(value.get("left_angle") or "")
        right = str(value.get("right_angle") or "")
        if _valid_angle_name(left) and _valid_angle_name(right):
            return f"∠{left}＝∠{right}"
    raise TeachingRoleBindingError("teaching_angle_equality_reference_invalid")


def _valid_angle_name(value: str) -> bool:
    angle_pattern = (
        r"[A-Z][A-Za-z0-9_′']*"
        r"[A-Z][A-Za-z0-9_′']*"
        r"[A-Z][A-Za-z0-9_′']*"
    )
    return bool(re.fullmatch(angle_pattern, value))


def _difference_angle(angle: str, reference: str) -> str:
    if not (_valid_angle_name(angle) and _valid_angle_name(reference)):
        return ""
    if len(angle) != 3 or len(reference) != 3 or angle[1] != reference[1]:
        return ""
    angle_rays = {angle[0], angle[2]}
    reference_rays = {reference[0], reference[2]}
    shared = angle_rays & reference_rays
    if len(shared) != 1:
        return ""
    left = next(iter(reference_rays - shared))
    right = next(iter(angle_rays - shared))
    return f"{left}{angle[1]}{right}"


def _reference_angle_proof(
    reference: str,
    *,
    reference_value: str,
    snapshot: ExplanationSnapshot,
    source: TeachingSource,
) -> tuple[str, ...]:
    """Reconstruct the coordinate proof for a verified reference angle."""

    if len(reference) != 3 or not _valid_angle_name(reference):
        raise TeachingRoleBindingError("teaching_reference_angle_points_invalid")
    labels = tuple(reference)
    points = {
        label: _snapshot_point_pair(label, snapshot, source=source)
        for label in labels
    }
    right_vertex = ""
    other_vertices: tuple[str, str] | None = None
    for candidate in labels:
        others = tuple(label for label in labels if label != candidate)
        if len(others) != 2:
            continue
        origin = points[candidate]
        vector1 = (
            sp.simplify(points[others[0]][0] - origin[0]),
            sp.simplify(points[others[0]][1] - origin[1]),
        )
        vector2 = (
            sp.simplify(points[others[1]][0] - origin[0]),
            sp.simplify(points[others[1]][1] - origin[1]),
        )
        dot = sp.simplify(vector1[0] * vector2[0] + vector1[1] * vector2[1])
        if dot == 0:
            right_vertex = candidate
            other_vertices = (others[0], others[1])
            break
    if not right_vertex or other_vertices is None:
        raise TeachingRoleBindingError("teaching_reference_right_angle_missing")
    first, second = other_vertices
    first_length = _point_distance(points[right_vertex], points[first])
    second_length = _point_distance(points[right_vertex], points[second])
    if sp.simplify(first_length - second_length) != 0:
        raise TeachingRoleBindingError("teaching_reference_equal_legs_missing")
    triangle = f"{first}{right_vertex}{second}"
    return (
        f"∵{_point_display(first, points[first])}、"
        f"{_point_display(right_vertex, points[right_vertex])}、"
        f"{_point_display(second, points[second])}，且 "
        f"{right_vertex}{first}⊥{right_vertex}{second}",
        f"计算{right_vertex}{first}＝{_math(first_length)}，"
        f"{right_vertex}{second}＝{_math(second_length)}",
        f"∴Rt△{triangle} 为等腰直角三角形，所以 "
        f"∠{reference}＝{reference_value}°",
    )


def _axis_position_statement(
    label: str,
    point: tuple[sp.Expr, sp.Expr],
    *,
    origin: tuple[sp.Expr, sp.Expr],
) -> str:
    if sp.simplify(point[0] - origin[0]) == 0:
        delta = sp.simplify(point[1] - origin[1])
        if delta.is_negative:
            return f"{label} 在 y 轴负半轴上"
        if delta.is_positive:
            return f"{label} 在 y 轴正半轴上"
        return f"{label} 与原点重合"
    if sp.simplify(point[1] - origin[1]) == 0:
        delta = sp.simplify(point[0] - origin[0])
        if delta.is_negative:
            return f"{label} 在 x 轴负半轴上"
        if delta.is_positive:
            return f"{label} 在 x 轴正半轴上"
        return f"{label} 与原点重合"
    raise TeachingRoleBindingError("teaching_axis_intercept_not_on_axis")


def _first_unused_point_label(used: set[str]) -> str:
    for codepoint in range(ord("A"), ord("Z") + 1):
        label = chr(codepoint)
        if label not in used:
            return label
    return _next_point_label(used)


def _item_display(item: Mapping[str, Any]) -> str:
    display = str(item.get("display") or "").strip()
    if display:
        return _student_text(display)
    return _math(item.get("value"))


def _point_label(item: Mapping[str, Any]) -> str:
    display = str(item.get("display") or "")
    match = re.match(r"\s*([A-Z][A-Za-z0-9_′']*)\s*\(", display)
    if match:
        return match.group(1).replace("_prime", "′")
    ref = item.get("ref")
    if isinstance(ref, Mapping) and ref.get("kind") == "source":
        value = str(ref.get("ref") or "")
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", value):
            return value
    return ""


def _point_pair(value: Any) -> tuple[sp.Expr, sp.Expr] | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes) or len(value) != 2:
        return None
    try:
        return _expr(value[0]), _expr(value[1])
    except Exception:
        return None


def _require_point_pair(
    value: tuple[sp.Expr, sp.Expr] | None,
) -> tuple[sp.Expr, sp.Expr]:
    if value is None:
        raise TeachingRoleBindingError("teaching_point_value_missing")
    return value


def _point_distance(
    left: tuple[sp.Expr, sp.Expr],
    right: tuple[sp.Expr, sp.Expr],
) -> sp.Expr:
    return sp.simplify(
        sp.sqrt((right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2)
    )


def _line_equation(
    p1: tuple[sp.Expr, sp.Expr],
    p2: tuple[sp.Expr, sp.Expr],
) -> tuple[str, sp.Expr | None]:
    if _same_point(p1, p2):
        raise TeachingRoleBindingError("teaching_line_points_coincident")
    x = sp.Symbol("x")
    if sp.simplify(p2[0] - p1[0]) == 0:
        return f"x＝{_math(p1[0])}", None
    slope = sp.simplify((p2[1] - p1[1]) / (p2[0] - p1[0]))
    intercept = sp.simplify(p1[1] - slope * p1[0])
    expression = sp.expand(slope * x + intercept)
    return f"y＝{_linear_expression_display(expression)}", expression


def _linear_expression_display(expression: sp.Expr) -> str:
    x = sp.Symbol("x")
    poly = sp.Poly(sp.expand(expression), x)
    if poly.degree() > 1:
        return _math(expression)
    return _join_terms(
        (
            _coefficient_term(poly.coeff_monomial(x), "x"),
            _constant_term(poly.coeff_monomial(1)),
        )
    ) or "0"


def _parse_equation(value: Any) -> sp.Equality | None:
    if isinstance(value, sp.Equality):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = sp.sympify(text, locals={"Eq": sp.Eq, "sqrt": sp.sqrt})
    except (sp.SympifyError, TypeError, ValueError):
        if "=" not in text or text.count("=") != 1:
            return None
        left, right = text.split("=", 1)
        try:
            parsed = sp.Eq(sp.sympify(left), sp.sympify(right))
        except (sp.SympifyError, TypeError, ValueError):
            return None
    return parsed if isinstance(parsed, sp.Equality) else None


def _equation_display(value: Any) -> str:
    equation = _parse_equation(value)
    if equation is not None:
        return f"{_math(equation.lhs)}＝{_math(equation.rhs)}"
    return _student_text(str(value))


def _calculation_equation_displays(source: TeachingSource) -> tuple[str, ...]:
    equations: list[str] = []
    for calculation in source.calculations:
        if str(calculation.get("kind") or "") != "equation_system":
            continue
        raw_equations = calculation.get("equations") or ()
        if isinstance(raw_equations, str):
            raw_equations = (raw_equations,)
        if not isinstance(raw_equations, Sequence):
            continue
        equations.extend(_equation_display(value) for value in raw_equations)
    return tuple(dict.fromkeys(equations))


def _real_calculation_solutions(
    source: TeachingSource,
    parameter: str,
) -> tuple[sp.Expr, ...]:
    """Recover all real equation candidates before runtime constraint filtering."""

    raw_equations: list[Any] = []
    for calculation in source.calculations:
        if str(calculation.get("kind") or "") != "equation_system":
            continue
        values = calculation.get("equations") or ()
        if isinstance(values, str):
            values = (values,)
        if isinstance(values, Sequence):
            raw_equations.extend(values)
    if not raw_equations or not parameter:
        return ()

    result: list[sp.Expr] = []
    for raw in raw_equations:
        equation = _parse_equation(raw)
        if equation is None:
            continue
        for candidate in _solve_real_equation(equation, parameter):
            if not any(sp.simplify(candidate - existing) == 0 for existing in result):
                result.append(candidate)
    return tuple(sorted(result, key=sp.default_sort_key))


def _solve_real_equation(
    equation: sp.Equality,
    parameter: str,
) -> tuple[sp.Expr, ...]:
    matching_symbols = [
        symbol for symbol in equation.free_symbols if symbol.name == parameter
    ]
    if len(matching_symbols) != 1:
        return ()
    real_parameter = sp.Symbol(parameter, real=True)
    real_equation = equation.xreplace({matching_symbols[0]: real_parameter})
    try:
        solutions = sp.solve(real_equation, real_parameter)
    except (NotImplementedError, TypeError, ValueError):
        return ()
    result: list[sp.Expr] = []
    for solution in solutions:
        candidate = sp.simplify(solution)
        if candidate.is_real is False:
            continue
        if not any(sp.simplify(candidate - existing) == 0 for existing in result):
            result.append(candidate)
    return tuple(sorted(result, key=sp.default_sort_key))


def _piecewise_parameter_derivation(
    expression: sp.Expr,
    *,
    target: sp.Expr,
    parameter: str,
) -> tuple[str, ...]:
    if not isinstance(expression, sp.Piecewise):
        return ()
    parameter_symbols = [
        symbol for symbol in expression.free_symbols if symbol.name == parameter
    ]
    if len(parameter_symbols) != 1:
        return ()
    source_parameter = parameter_symbols[0]
    previous_conditions: list[sp.Expr] = []
    lines = ["∵当前表达式需按参数范围分段讨论"]
    for branch_expression, condition in expression.args:
        if condition is sp.true:
            effective_condition = sp.simplify_logic(
                sp.And(*(sp.Not(item) for item in previous_conditions))
            )
        else:
            effective_condition = condition
            previous_conditions.append(condition)
        equation = sp.Eq(branch_expression, target)
        candidates = _solve_real_equation(equation, parameter)
        valid_candidates = tuple(
            candidate
            for candidate in candidates
            if _condition_accepts_candidate(
                effective_condition,
                source_parameter=source_parameter,
                candidate=candidate,
            )
        )
        result = (
            _solution_candidates_display(parameter, valid_candidates)
            if valid_candidates
            else "无符合该分支范围的解"
        )
        lines.append(
            f"计算当 {_condition_display(effective_condition)} 时，令 "
            f"{_math(branch_expression)}＝{_math(target)}，解得 {result}"
        )
    return tuple(lines)


def _condition_accepts_candidate(
    condition: sp.Expr,
    *,
    source_parameter: sp.Symbol,
    candidate: sp.Expr,
) -> bool:
    result = sp.simplify(condition.subs(source_parameter, candidate))
    return result is sp.true


def _condition_display(condition: sp.Expr) -> str:
    text = sp.sstr(condition)
    return (
        text.replace(">=", "≥")
        .replace("<=", "≤")
        .replace(">", "＞")
        .replace("<", "＜")
        .replace(" & ", " 且 ")
        .replace(" | ", " 或 ")
    )


def _solution_candidates_display(
    parameter: str,
    values: Sequence[sp.Expr],
) -> str:
    return " 或 ".join(f"{parameter}＝{_math(value)}" for value in values)


def _segment_condition_display(source: TeachingSource) -> str:
    items = _input_items(
        source,
        "condition",
        "length_squared",
        "segment_length_relation",
    )
    if len(items) != 1:
        raise TeachingRoleBindingError(
            f"teaching_segment_condition_cardinality_invalid: {source.source_step_id}"
        )
    item = items[0]
    value = item.get("value")
    if not isinstance(value, Mapping):
        return _item_display(item)
    condition_type = str(value.get("type") or item.get("runtime_type") or "")
    if condition_type == "length_squared":
        segment = str(value.get("segment") or "").strip()
        squared_value = value.get("value")
        if segment and squared_value not in (None, ""):
            return f"{segment}²＝{_math(squared_value)}"
    if condition_type == "segment_length_relation":
        left = str(value.get("left_segment") or "").strip()
        right = str(value.get("right_segment") or "").strip()
        scale = _expr(value.get("scale") or 1)
        if left and right:
            right_term = right if scale == 1 else f"{_math(scale)}{right}"
            return f"{left}＝{right_term}"
    equation = value.get("equation")
    if equation:
        return _equation_display(equation)
    return _item_display(item)


def _parameter_name_from_bound_inputs(
    *,
    parameter_item: Mapping[str, Any] | None,
    value_item: Mapping[str, Any],
) -> str:
    """Read parameter identity from binding authority, never expression deltas.

    New snapshots expose the compiler-bound ``parameter`` input directly.
    Older recorded snapshots predate that projection and retain the same
    identity on ``parameter_value.ref``; that is a binding-origin fallback,
    not an inference from before/after expressions.  Consequently a verified
    idempotent substitution remains teachable when its value is unchanged.
    """

    if parameter_item is not None:
        raw_value = parameter_item.get("value")
        if isinstance(raw_value, str) and re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*",
            raw_value,
        ):
            return raw_value
        display = str(parameter_item.get("display") or "")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", display):
            return display
        ref = parameter_item.get("ref")
        if isinstance(ref, Mapping) and ref.get("kind") == "source":
            source_ref = str(ref.get("ref") or "")
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", source_ref):
                return source_ref

    value_ref = value_item.get("ref")
    if isinstance(value_ref, Mapping) and value_ref.get("kind") == "source":
        source_ref = str(value_ref.get("ref") or "")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", source_ref):
            return source_ref
    raise TeachingRoleBindingError("teaching_parameter_identity_missing")


def _point_list(value: Any) -> list[tuple[sp.Expr, sp.Expr]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [pair for item in value if (pair := _point_pair(item)) is not None]


def _point_display(label: str, pair: tuple[sp.Expr, sp.Expr]) -> str:
    return f"{label}({_math(pair[0])},{_math(pair[1])})"


def _indexed_point_label(label: str, index: int) -> str:
    subscript_digits = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
    return f"{label}{str(index).translate(subscript_digits)}"


def _coordinate_operand(value: sp.Expr) -> str:
    simplified = sp.simplify(value)
    display = _math(simplified)
    return display if simplified.is_Atom or simplified.is_nonnegative else f"({display})"


def _raw_point_display(label: str, pair: tuple[sp.Expr, sp.Expr]) -> str:
    return f"{label}({sp.sstr(pair[0]).replace(' ', '')},{sp.sstr(pair[1]).replace(' ', '')})"


def _expr(value: Any) -> sp.Expr:
    text = re.sub(
        r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+",
        "t",
        str(value),
    )
    return sp.sympify(text, locals={"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs})


def _math(value: Any) -> str:
    if isinstance(value, sp.Basic):
        raw = sp.sstr(value)
    else:
        raw = str(value)
    raw = re.sub(
        r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+",
        "t",
        raw,
    )
    return student_math_display(
        raw,
        fullwidth_operators=True,
        simplify_sympy=False,
    )


def _student_text(value: str) -> str:
    return (
        value.replace("_prime", "′")
        .replace("A_prime", "A′")
        .replace("-", "－")
        .replace("+", "＋")
        .replace("=", "＝")
    )


def _quadratic_expression_display(expression: Any) -> str:
    expr = _expr(expression)
    x = sp.Symbol("x")
    poly = sp.Poly(expr, x)
    if poly.degree() != 2:
        return _math(expr)
    return _join_terms(
        (
            _coefficient_term(poly.coeff_monomial(x**2), "x²"),
            _coefficient_term(poly.coeff_monomial(x), "x"),
            _constant_term(poly.coeff_monomial(1)),
        )
    )


def student_quadratic_expression_display(expression: Any) -> str:
    """Public student-order wrapper shared by Function and Macro binders."""

    return _quadratic_expression_display(expression)


def _quadratic_title_action(expression: sp.Expr) -> str:
    x = sp.Symbol("x")
    return "化简" if expression.free_symbols - {x} else "求"


def _completed_square_expression(expression: Any) -> str:
    expr = _expr(expression)
    x = sp.Symbol("x")
    poly = sp.Poly(expr, x)
    if poly.degree() != 2:
        return ""
    a = sp.simplify(poly.coeff_monomial(x**2))
    b = sp.simplify(poly.coeff_monomial(x))
    h = sp.simplify(-b / (2 * a))
    k = sp.simplify(expr.subs(x, h))
    if a.free_symbols or h.free_symbols or k.free_symbols:
        return ""
    inner = "x" if h == 0 else f"x{'－' if h > 0 else '＋'}{_math(abs(h))}"
    if a == 1:
        square = f"({inner})²"
    elif a == -1:
        square = f"－({inner})²"
    else:
        square = f"{_math(a)}({inner})²"
    if k == 0:
        return square
    return f"{square}{'－' if k < 0 else '＋'}{_math(abs(k))}"


def _coefficient_term(coefficient: sp.Expr, body: str) -> str:
    coefficient = sp.simplify(coefficient)
    if coefficient == 0:
        return ""
    if coefficient == 1:
        return body
    if coefficient == -1:
        return f"－{body}"
    text = _math(abs(coefficient) if coefficient.is_number else coefficient)
    if "＋" in text or ("－" in text and not text.startswith("－")):
        text = f"({text})"
    return ("－" if coefficient.is_number and coefficient < 0 else "") + text + body


def _constant_term(value: sp.Expr) -> str:
    return "" if sp.simplify(value) == 0 else _math(value)


def _join_terms(terms: Sequence[str]) -> str:
    result = ""
    for term in terms:
        if not term:
            continue
        if not result or term.startswith("－"):
            result += term
        else:
            result += "＋" + term
    return result


def _coefficient_mapping_display(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return "，".join(f"{name}＝{_math(raw)}" for name, raw in value.items())


def _curve_expression_for_point(
    item: Mapping[str, Any],
    snapshot: ExplanationSnapshot,
) -> sp.Expr | None:
    ref = item.get("ref")
    if not isinstance(ref, Mapping) or ref.get("kind") != "source":
        return None
    label = str(ref.get("ref") or "")
    entities = tuple(
        entity
        for entity in (snapshot.problem or {}).get("entities") or ()
        if isinstance(entity, Mapping)
    )
    point = next(
        (entity for entity in entities if str(entity.get("name") or "") == label),
        None,
    )
    curve_handle = str(point.get("of") or "") if point else ""
    direct_curve = next(
        (
            entity
            for entity in entities
            if str(entity.get("handle") or "") == curve_handle
            and entity.get("entity_type") == "function"
            and entity.get("expression") not in (None, "")
        ),
        None,
    )
    if point is not None and direct_curve is None:
        point_handle = str(point.get("handle") or "")
        matching_curves = {
            str(fact.get("curve") or "")
            for fact in (snapshot.problem or {}).get("facts") or ()
            if isinstance(fact, Mapping)
            and str(fact.get("type") or "").startswith("point_on_curve")
            and str(fact.get("point") or "") == point_handle
            and fact.get("curve")
        }
        if len(matching_curves) == 1:
            curve_handle = next(iter(matching_curves))
    curve = next(
        (
            entity
            for entity in entities
            if str(entity.get("handle") or "") == curve_handle
            and entity.get("expression") not in (None, "")
        ),
        None,
    )
    return _expr(curve["expression"]) if curve else None


def _quadratic_substitution_display(parabola: sp.Expr, x_arg: sp.Expr) -> str:
    x = sp.Symbol("x")
    poly = sp.Poly(parabola, x)
    body = _math(x_arg) if x_arg.is_Symbol else f"({_math(x_arg)})"
    return _join_terms(
        (
            _coefficient_term(poly.coeff_monomial(x**2), f"{body}²"),
            _coefficient_term(poly.coeff_monomial(x), body),
            _constant_term(poly.coeff_monomial(1)),
        )
    )


def _quadratic_substitution_simplified_display(
    parabola: sp.Expr,
    x_arg: sp.Expr,
) -> str:
    x = sp.Symbol("x")
    poly = sp.Poly(parabola, x)
    return _join_terms(
        (
            _math(sp.simplify(poly.coeff_monomial(x**2) * x_arg**2)),
            _math(sp.simplify(poly.coeff_monomial(x) * x_arg)),
            _constant_term(poly.coeff_monomial(1)),
        )
    )


def _quadratic_in_variable_display(
    coefficients: Sequence[sp.Expr],
    variable: str,
) -> str:
    body = variable if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", variable) else f"({variable})"
    return _join_terms(
        (
            _coefficient_term(coefficients[0], f"{body}²"),
            _coefficient_term(coefficients[1], body),
            _constant_term(coefficients[2]),
        )
    )


def _nonzero_factor_condition(
    factored: sp.Expr,
    snapshot: ExplanationSnapshot,
) -> str:
    symbols = {symbol.name for symbol in factored.free_symbols}
    text = " ".join(
        str(value)
        for value in (snapshot.problem or {}).get("original_text") or ()
    )
    for symbol in sorted(symbols):
        match = re.search(rf"\b{re.escape(symbol)}\s*(>=|>|<=|<)\s*([^，,）)\s]+)", text)
        if match:
            operator = {">": "＞", ">=": "≥", "<": "＜", "<=": "≤"}[match.group(1)]
            return f"{symbol}{operator}{_math(match.group(2))}"
    return ""


def _problem_point_attribute(
    snapshot: ExplanationSnapshot,
    label: str,
    name: str,
) -> str:
    for entity in (snapshot.problem or {}).get("entities") or ():
        if isinstance(entity, Mapping) and str(entity.get("name") or "") == label:
            return str(entity.get(name) or "")
    return ""


def _problem_point_labels(snapshot: ExplanationSnapshot) -> set[str]:
    return {
        str(entity.get("name") or "")
        for entity in (snapshot.problem or {}).get("entities") or ()
        if isinstance(entity, Mapping) and entity.get("entity_type") == "point"
    }


def _existing_projection_label(
    source: TeachingSource,
    *,
    point_label: str,
    pair: tuple[sp.Expr, sp.Expr],
    snapshot: ExplanationSnapshot,
) -> str:
    semantic_matches = _semantic_projection_labels(
        point_label=point_label,
        pair=pair,
        snapshot=snapshot,
    )
    if len(semantic_matches) > 1:
        raise TeachingRoleBindingError(
            "teaching_projection_existing_object_ambiguous: "
            f"step={source.source_step_id}, point={point_label}, "
            f"candidates={sorted(semantic_matches)}"
        )
    if semantic_matches:
        return next(iter(semantic_matches))

    value_matches: set[str] = set()
    for candidate in iter_teaching_sources(snapshot.root_scope):
        for name, result in candidate.outputs.items():
            value = _point_pair(result.get("value"))
            label = str(candidate.output_targets.get(name) or _point_label(result))
            if label and value is not None and _same_point(value, pair):
                value_matches.add(label)
    if len(value_matches) > 1:
        raise TeachingRoleBindingError(
            "teaching_projection_existing_object_ambiguous: "
            f"step={source.source_step_id}, point={point_label}, "
            f"candidates={sorted(value_matches)}"
        )
    if value_matches:
        return next(iter(value_matches))
    return ""


def _semantic_projection_labels(
    *,
    point_label: str,
    pair: tuple[sp.Expr, sp.Expr],
    snapshot: ExplanationSnapshot,
) -> set[str]:
    """Resolve a projection foot by typed problem relations, never by its letter.

    A point declared on a curve axis and that curve's axis/x-axis intercept are
    the same mathematical object after vertical projection onto the x-axis.
    The labels (for example E/M) are data; the relation and shared curve owner
    establish identity.
    """

    if sp.simplify(pair[1]) != 0:
        return set()
    entities = tuple(
        entity
        for entity in (snapshot.problem or {}).get("entities") or ()
        if isinstance(entity, Mapping) and entity.get("entity_type") == "point"
    )
    sources = tuple(
        entity
        for entity in entities
        if str(entity.get("name") or "") == point_label
        and entity.get("definition") == "point_on_axis"
    )
    matches: set[str] = set()
    for source_entity in sources:
        curve_ref = source_entity.get("of")
        if not curve_ref:
            continue
        for candidate in entities:
            if candidate.get("definition") != "axis_x_intercept":
                continue
            if candidate.get("of") != curve_ref:
                continue
            label = str(candidate.get("name") or "")
            if label:
                matches.add(label)
    return matches

def _next_point_label(used: set[str]) -> str:
    alphabet = tuple(chr(value) for value in range(ord("A"), ord("Z") + 1))
    occupied = [alphabet.index(value) for value in used if value in alphabet]
    start = max(occupied, default=-1) + 1
    for label in (*alphabet[start:], *alphabet[:start]):
        if label not in used:
            return label
    suffix = 1
    while True:
        for label in alphabet:
            candidate = f"{label}{suffix}"
            if candidate not in used:
                return candidate
        suffix += 1


def _positive_math(value: sp.Expr) -> str:
    simplified = sp.simplify(value)
    if simplified.is_number and simplified < 0:
        simplified = -simplified
    return _math(simplified)


def _same_point(
    left: tuple[sp.Expr, sp.Expr],
    right: tuple[sp.Expr, sp.Expr],
) -> bool:
    return sp.simplify(left[0] - right[0]) == 0 and sp.simplify(left[1] - right[1]) == 0


def _square_position_condition(
    target: str,
    square: Mapping[str, Any],
    vertices: Sequence[str],
) -> str:
    orientation = str(square.get("orientation") or "")
    orientation_target = vertices[3]
    if orientation == "below_x_axis" and target == orientation_target:
        return f"{target} 在 x 轴下方"
    if orientation == "above_x_axis" and target == orientation_target:
        return f"{target} 在 x 轴上方"
    return f"按正方形顶点顺序选取 {target}"


def _shared_parameter(
    target: tuple[sp.Expr, sp.Expr],
    curve: tuple[sp.Expr, sp.Expr],
    parabola: sp.Expr,
) -> sp.Symbol:
    point_symbols = set().union(*(value.free_symbols for value in (*target, *curve)))
    candidates = sorted(
        point_symbols - parabola.free_symbols - {sp.Symbol("x")},
        key=lambda value: value.name,
    )
    if len(candidates) != 1:
        raise TeachingRoleBindingError("teaching_curve_parameter_ambiguous")
    return candidates[0]


def _parameter_value(
    pattern: tuple[sp.Expr, sp.Expr],
    point: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol,
) -> sp.Expr | None:
    for expression, value in zip(pattern, point, strict=True):
        if parameter in expression.free_symbols:
            solutions = sp.solve(sp.Eq(expression, value), parameter)
            if solutions:
                return sp.simplify(solutions[0])
    return None


def _sort_candidates(
    candidates: Sequence[tuple[sp.Expr, sp.Expr]],
    pattern: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol,
) -> list[tuple[sp.Expr, sp.Expr]]:
    def key(point: tuple[sp.Expr, sp.Expr]) -> tuple[float, str]:
        value = _parameter_value(pattern, point, parameter)
        try:
            numeric = float(sp.N(value)) if value is not None else float("-inf")
        except Exception:
            numeric = float("-inf")
        return -numeric, _point_display("", point)

    return sorted(candidates, key=key)


def _solutions_display(symbol: str, values: Sequence[sp.Expr]) -> str:
    if len(values) == 2:
        center = sp.simplify((values[0] + values[1]) / 2)
        delta = sp.simplify(abs(values[0] - values[1]) / 2)
        if delta != 0:
            center_text = "" if center == 0 else _math(center)
            return f"{symbol}＝{center_text}±{_math(delta)}"
    return f"{symbol}＝" + " 或 ".join(_math(value) for value in values)


_ROLE_BINDERS: dict[str, RoleBinder] = {
    "quadratic_from_constraints": _quadratic_from_constraints,
    "quadratic_x_axis_intercept_point": _quadratic_x_axis_intercept,
    "quadratic_y_axis_intercept_point": _quadratic_y_axis_intercept,
    "right_angle_equal_length_candidates": (
        _right_angle_equal_length_candidates
    ),
    "midpoint_point": _midpoint_from_definition,
    "parameter_from_segment_length": _parameter_from_segment_length,
    "parameter_from_minimum_value": _parameter_from_minimum_value,
    "quadratic_vertex_point": _quadratic_vertex,
    "quadratic_axis_parameterized_point": _quadratic_axis_point,
    "square_adjacent_vertex_from_side": _square_adjacent_vertex,
    "point_candidates_from_curve_point_condition": _curve_point_candidates,
    "parameter_from_expression_value": _parameter_from_expression,
    "evaluate_point_at_parameter": _evaluate_point,
    "quadratic_axis_x_intercept_point": _quadratic_axis_x_intercept,
    "translated_point": _translated_point,
    "angle_sum_equal_angle_candidates": _angle_sum_equal_angle,
    "axis_intercept_from_equal_acute_angles": _axis_intercept_from_equal_angle,
    "line_parabola_second_intersection_point": _line_parabola_intersection,
    "distance_between_points": _distance_between_points,
    "equal_length_ray_point": _equal_length_ray_point,
    "line_intersection_point": _line_intersection,
    "point_on_parabola_at_x": _point_on_parabola_at_x,
    "quadratic_axis_from_relation": _quadratic_axis_from_relation,
    "evaluate_expression_at_parameter": _evaluate_expression_at_parameter,
    "generic_source": lambda source, snapshot: _generic_roles(source),
    "generic_trace": lambda source, snapshot: _generic_roles(source),
}


__all__ = [
    "TeachingRoleBindingError",
    "bind_teaching_roles",
    "format_teaching_template",
]
