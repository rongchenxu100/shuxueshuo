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

from .models import ExplanationSnapshot, TeachingSource, iter_teaching_sources


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
    roles.update(source.output_targets)
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
    curve_point = _one_input(source, "curve_point", required=False)
    if curve_point is None:
        relation = relation or _known_coefficient_inputs(source)
        roles.update(
            {
                "constraints": relation,
                "constraint_origin": "题设给出当前二次函数的系数条件",
                "constraint_derivation": relation,
            }
        )
        return roles

    base = _curve_expression_for_point(curve_point, snapshot)
    pair = _point_pair(curve_point.get("value"))
    label = _point_label(curve_point)
    if base is None or pair is None or not label or not relation:
        raise TeachingRoleBindingError(
            f"teaching_quadratic_curve_constraint_invalid: {source.source_step_id}"
        )
    x = sp.Symbol("x")
    x_value, y_value = pair
    substituted = _quadratic_substitution_simplified_display(base, x_value)
    residual = sp.simplify(base.subs(x, x_value) - y_value)
    factored = sp.factor(residual)
    factored_display = _math(factored)
    equation = f"{_math(y_value)}＝{substituted}"
    if factored_display != substituted:
        equation += f"＝{factored_display}"
    dynamic = [
        f"∵{_point_display(label, pair)} 在 y＝{_quadratic_expression_display(base)} 上",
        f"∴{equation}",
    ]
    condition = _nonzero_factor_condition(factored, snapshot)
    if condition:
        dynamic.append(f"∵{condition}")
    dynamic.extend(
        (
            f"∴{relation}",
            f"∴y＝{result}{roles['completed_square_suffix']}",
        )
    )
    roles.update(
        {
            "constraints": relation,
            "constraint_origin": dynamic[0].removeprefix("∵"),
            "constraint_derivation": "；".join(
                value.removeprefix("∵").removeprefix("∴")
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
    return {
        "quadratic": f"y＝{_quadratic_expression_display(quadratic)}",
        "point": _point_display(label, point),
    }


def _angle_sum_equal_angle(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
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
    return {
        "condition": f"∠{terms[0]}＋∠{terms[1]}＝{value}°",
        "angle_equality": f"∠{left}＝∠{right}",
    }


def _axis_intercept_from_equal_angle(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    equality_item = _one_input(source, "angle_equality")
    assert equality_item is not None
    equality = _referenced_angle_equality(equality_item, snapshot)
    point = _output_point(source, "point")
    label = _first_unused_point_label(_problem_point_labels(snapshot))
    return {
        "angle_equality": equality,
        "point": _point_display(label, point),
    }


def _line_parabola_intersection(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    return {
        "line_p1": _input_point_display(source, "line_p1", snapshot),
        "line_p2": _input_point_display(source, "line_p2", snapshot),
        "parabola": f"y＝{_quadratic_expression_display(_input_expr(source, 'parabola'))}",
        "known_point": _input_point_display(source, "known_point", snapshot),
        "point": _point_display(
            _output_label(source, "point"),
            _output_point(source, "point"),
        ),
    }


def _quadratic_vertex(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
    parabola = _input_expr(source, "parabola")
    point = _output_point(source, "point")
    label = _output_label(source, "point")
    vertex_form = _completed_square_expression(parabola)
    return {
        "parabola_vertex_form": f"y＝{vertex_form or _quadratic_expression_display(parabola)}",
        "vertex_point": _point_display(label, point),
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
    return {
        "target_label": target_label,
        "curve_kind": "抛物线",
        "curve_point": _point_display(curve_label, curve_pair),
        "curve_equation": f"y＝{_quadratic_expression_display(parabola)}",
        "substitution_equation": (
            f"{_math(curve_y)}＝{_quadratic_substitution_display(parabola, x_arg)}"
        ),
        "parameter_equation": (
            f"{_quadratic_in_variable_display(coefficients, _math(x_arg))}＝0"
        ),
        "parameter_solutions": _solutions_display(str(parameter), parameter_values),
        "target_candidates": " 或 ".join(
            _point_display(target_label, point) for point in candidates
        ),
    }


def _parameter_from_expression(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    del snapshot
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
    return {
        "expression": _math(expression.get("value")),
        "target_value": _math(target),
        "parameter": parameter,
        "parameter_value": _math(output),
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
    return {
        "source_point": source_display or _raw_point_display(label, source_pair),
        "parameter": parameter,
        "parameter_value": _math(value_item.get("value")),
        "evaluated_point": output_display or _raw_point_display(label, output),
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
        return target
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
    return bool(re.fullmatch(r"[A-Z][A-Za-z0-9_′']*[A-Z][A-Za-z0-9_′']*[A-Z][A-Za-z0-9_′']*", value))


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


def _point_list(value: Any) -> list[tuple[sp.Expr, sp.Expr]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [pair for item in value if (pair := _point_pair(item)) is not None]


def _point_display(label: str, pair: tuple[sp.Expr, sp.Expr]) -> str:
    return f"{label}({_math(pair[0])},{_math(pair[1])})"


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


def _known_coefficient_inputs(source: TeachingSource) -> str:
    values = source.inputs.get("known_coefficients", ())
    return "，".join(_item_display(item) for item in values)


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
    if point is not None and not curve_handle:
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
    "generic_source": lambda source, snapshot: _generic_roles(source),
    "generic_trace": lambda source, snapshot: _generic_roles(source),
}


__all__ = [
    "TeachingRoleBindingError",
    "bind_teaching_roles",
    "format_teaching_template",
]
