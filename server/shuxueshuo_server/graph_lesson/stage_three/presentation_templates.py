"""Declarative prose rendering and registered, pure mathematical preparation."""


import re
from copy import deepcopy
from string import Formatter

import sympy as sp

from .capabilities.ranges import reciprocal_coefficients
from .discriminant_display import constant_true_condition, displayed_delta_condition
from .math_values import (
    BOUND_EXPLANATION,
    BOUND_TEX,
    EXTREMUM_TEX,
    math_value,
    polynomial_extrema_attained,
)
from .presentation_intervals import (
    cases_view,
    classified_view,
    conditions_view,
    linear_view,
    merge_view,
)
from .variable_display import case_view as variable_case_view
from .variable_display import merge_view as variable_merge_view
from .variable_display import slope_view as variable_slope_view


def _lookup(values, path):
    result = values
    for part in path.split("."):
        result = result[part]
    return result


def _piecewise_range_parameter_view(values):
    from .piecewise_range_parameter_presentation import presentation
    return presentation(values)


def _piecewise_range_view(values):
    from .piecewise_range_presentation import presentation
    return presentation(values)


def _piecewise_inequality_view(values):
    from .piecewise_inequality_presentation import presentation
    return presentation(values)


def _piecewise_modeling_view(values):
    from .piecewise_modeling_presentation import presentation
    return presentation(values)


def _piecewise_equation_view(values):
    from .piecewise_equation_presentation import presentation
    return presentation(values)


def _extremum_view(values):
    from .extremum_presentation import presentation
    return presentation(values)


def _mono_inequality_view(values):
    from .monotonicity_inequality_presentation import presentation
    return presentation(values)


def _mono_parameter_view(values):
    from .monotonicity_parameter_presentation import presentation
    return presentation(values)


def _abstract_monotonicity_view(values):
    from .abstract_monotonicity_presentation import presentation
    return presentation(values)


def _parity_view(values):
    from .parity_presentation import presentation
    return presentation(values)


def _parity_parameter_view(values):
    from .parity_parameter_presentation import presentation
    return presentation(values)


def _parity_extension_view(values):
    from .parity_extension_presentation import presentation
    return presentation(values)


def _function_symmetry_view(values):
    from .symmetry_presentation import presentation
    return presentation(values)


def _monotonicity_view(values):
    from .monotonicity_presentation import presentation
    return presentation(values)


def _function_graph_view(values):
    if values['description']['source']['kind'] != 'select_function_graph':
        from .absolute_graph_presentation import presentation as absolute_presentation
        return absolute_presentation(values)
    from .graph_transform_presentation import presentation
    return presentation(values)


class _MathFormatter(Formatter):
    def get_field(self, field_name, args, kwargs):
        value = _lookup(kwargs, field_name)
        return (math_value(value)["latex"] if isinstance(value, sp.Basic) else value), field_name


_FORMATTER = _MathFormatter()


def _render(node, values):
    if isinstance(node, str):
        return _FORMATTER.vformat(node, (), values)
    if isinstance(node, list):
        return "".join(_render(item, values) for item in node)
    if "if" in node:
        return _render(node["then"] if _lookup(values, node["if"]) else node.get("else", ""), values)
    if "select" in node:
        key = str(_lookup(values, node["select"]))
        return _render(node["cases"].get(key, node.get("default", "")), values)
    return node.get("separator", "").join(
        _render(node["body"], {**values, node["as"]: item}) for item in _lookup(values, node["for"])
    )


def _variable_swap(values):
    original = math_value(values["before"][0])["latex"]
    collected = math_value(values["function"])["latex"]
    return {"swap_identity": f"{original}={collected}"}


def _variable_range(values):
    bounds = values["range"]
    return {"after": [*values["after"], *(item["value"] for item in bounds["candidates"])],
            "square": values["slope_certificate"].get("square"),
            "has_square": "square" in values["slope_certificate"],
            "multiple": len(bounds["candidates"]) > 1}


def _variable_conditions(values):
    return {"before": [*values["before"], *values["conditions"]],
            "after": [*values["normalized"], *values["solutions"], *values["after"]],
            "multiple": len(values["conditions"]) > 1}


def _numeric_range(values):
    return {"constant": values.get("kind") == "constant"}


def _interval_cases(values):
    return {"after": [*values["after"], *(case["condition"] for case in values["cases"])]}


def _classified_range(values):
    bounds = values["range"]
    key = bounds["bound"]
    return {"after": [*values["after"], bounds[key]], "bound_value": bounds[key],
            "bound_attained": bounds[key + "_attained"], "has_vertex": values["vertex"] is not None}


def _interval_merge(values):
    return {"before": [*values["before"], *(item for result in values["results"]
                                           for item in result["outputs"]["conditions"])],
            "after": [*values["solutions"], *values["after"]],
            "case_solutions": [{"condition": case["condition"], "solution": solution}
                               for case, solution in zip(values["cases"], values["solutions"], strict=True)]}


def _variable_case_merge(values):
    """The linear case summary only needs the case conditions and solved sets."""
    return {"before": [*values["before"], *values["solutions"]],
            "case_solutions": [{"condition": case["condition"], "solution": solution}
                               for case, solution in zip(values["cases"], values["solutions"], strict=True)]}


def _degree_case_merge(values):
    """Present the case solutions already checked by merge_cases, without solving again."""
    rows = [{"condition": record["condition"], "solution": record["outputs"]["solution"]}
            for record in values["case_results"]]
    total = math_value(values["after"][-1])["latex"]
    union = r" \cup ".join(math_value(row["solution"])["latex"] for row in rows)
    return {"merge_rows": rows, "merge_equation": f"{union} = {total}",
            "merge_total": rf"{math_value(values['parameter'])['latex']} \in {total}"}


def _endpoint_bounds(values):
    return {"after": [*values["after"], *(item["value"] for item in values["range"]["candidates"])]}


def _interval_conditions(values):
    return {"before": [*values["before"], *values["conditions"]],
            "after": [*values["solutions"], *values["after"]], "multiple": len(values["conditions"]) > 1}


def _normalize_view(values):
    chain = []
    for expression in [*values["before"], *values["after"]]:
        if not chain or expression != chain[-1]:
            chain.append(expression)
    return {"normalization_chain": r" \Longleftrightarrow ".join(math_value(item)["latex"] for item in chain),
            "normalization_relations": [{"relation": item, "position": "after" if index == len(chain)-1 else
                                         "before" if index == 0 else "intermediate"}
                                        for index, item in enumerate(chain)]}


def _discriminant_view(values, opening=None):
    """Describe the normalized polynomial without switching to the sign residual.

    Internally, a <= relation uses rhs-lhs to share the >= sign theorem.  The
    student continues with lhs-rhs and the relation already published in the
    normalization card; only the coefficient condition is mirrored here.
    """
    opening = values["opening"] if opening is None else opening
    relation = values["relation"]
    positive = relation.rel_op in (">", ">=")
    residual_coefficient = opening.lhs - opening.rhs
    coefficient = residual_coefficient if positive else -residual_coefficient
    existential = values["quantifier"] == "∃"
    delta_upward = positive != existential
    view = {
        "display_expression": relation.lhs - relation.rhs,
        "display_coefficient": coefficient,
        "display_opening": (sp.Gt if positive else sp.Lt)(coefficient, 0, evaluate=False),
        "comparison_positive": positive,
        "fixed_positive": residual_coefficient.is_positive is True,
        "fixed_negative": residual_coefficient.is_negative is True,
        "actual_opening": ("向上" if coefficient.is_positive is True else
                           "向下" if coefficient.is_negative is True else ""),
        "automatic_opening": "向上" if positive else "向下",
        "delta_opening": "向上" if delta_upward else "向下",
        "delta_vertex": "最低点" if delta_upward else "最高点",
        "target_side": "上方" if positive else "下方",
        "target_sign_text": {">": "严格大于零", ">=": "大于或等于零",
                             "<": "严格小于零", "<=": "小于或等于零"}[relation.rel_op],
    }
    mode = ("automatic" if existential else "delta") if view["fixed_positive"] else (
        ("delta" if existential else "impossible") if view["fixed_negative"] else "parameter")
    position = ("高于" if positive else "低于") if relation.rel_op in (">", "<") else (
        "不低于" if positive else "不高于")
    summaries = {
        "delta": f"图像开口{view['actual_opening']}，{view['delta_vertex']}须{position}横轴。",
        "automatic": f"图像开口{view['actual_opening']}，一定有部分图像位于横轴{view['target_side']}，因此有实数解。",
        "impossible": f"图像开口{view['actual_opening']}，不可能在全体实数上满足这个不等式。",
        "parameter": (f"开口{view['automatic_opening']}时自动有解；开口{view['delta_opening']}时，"
                      f"{view['delta_vertex']}须{position}横轴。" if existential else
                      f"需要图像开口{view['delta_opening']}，且{view['delta_vertex']}{position}横轴。"),
    }
    return {**view, "opening_mode": mode, "opening_summary": summaries[mode], "vertex_position": position,
            "opening_determined": view["fixed_positive"] or view["fixed_negative"]}


def _opening(values):
    opening = values.get("opening", values["after"][0])
    view = _discriminant_view(values, opening)
    operator = {">": ">", ">=": r"\geq", "<": "<", "<=": r"\leq"}[values["relation"].rel_op]
    extremum = "最小值" if view["delta_opening"] == "向上" else "最大值"
    vertex = rf"\text{{{extremum}}}{operator}0"
    mode = view["opening_mode"]
    if mode == "automatic":
        lines = [rf"\text{{开口{view['actual_opening']}}}", r"\text{必有实数解}"]
    elif mode == "impossible":
        lines = [rf"\text{{开口{view['actual_opening']}}}", r"\text{无法恒成立}"]
    elif mode == "parameter" and values["quantifier"] == "∃":
        lines = [rf"\text{{开口{view['automatic_opening']}：有解}}",
                 rf"\text{{开口{view['delta_opening']}：}}" + vertex]
    else:
        lines = [rf"\text{{开口{view['delta_opening']}}}", vertex]
    conclusion = r"\begin{gathered}" + r"\\".join(lines) + r"\end{gathered}"
    return {**view, "opening": opening, "after": [values["relation"]], "opening_conclusion": conclusion}


def _discriminant_condition_view(values):
    view = _discriminant_view(values)
    condition = displayed_delta_condition(values["delta"], values["relation"], values["x"],
                                          values["quantifier"], values["after"][-1])
    coefficients = sp.Poly(view["display_expression"], values["x"])
    a, b, c = (math_value(coefficients.nth(degree))["latex"] for degree in (2, 1, 0))
    delta = math_value(values["delta"])["latex"]
    strict = values["relation"].rel_op in (">", "<")
    universal = values["quantifier"] == "∀"
    condition_words = ("严格小于零" if strict else "小于或等于零") if universal else (
        "严格大于零" if strict else "大于或等于零")
    condition_operator = ("<" if strict else r"\leq") if universal else (">" if strict else r"\geq")
    inactive = view["opening_mode"] in ("automatic", "impossible")
    conclusion = (r"\text{无需限制判别式}" if view["opening_mode"] == "automatic" else
                  r"\text{此情况不满足原题条件}" if inactive else math_value(condition)["latex"])
    return {**view, "delta_formula": rf"\Delta=\left({b}\right)^2-4\cdot\left({a}\right)\cdot\left({c}\right)={delta}",
            "delta_condition_words": condition_words, "delta_conclusion": conclusion,
            "delta_requirements": [] if inactive else [rf"\Delta {condition_operator} 0"],
            "before": [] if inactive else values["before"],
            "after": [values["relation"]] if inactive else [condition]}


def _opening_branch_solution(values):
    branch, parameter = values["branch"], math_value(values["parameter"])["latex"]
    condition = math_value(branch["condition"])["latex"]
    domain = math_value(branch["domain"])["latex"]
    answer = math_value(branch["solution"])["latex"]
    fixed_opening = constant_true_condition(branch["condition"])
    before = [] if fixed_opening else [branch["condition"]]
    if branch["automatic"]:
        equation = (rf"{parameter}\in {answer}" if fixed_opening else
                    rf"{condition}\ \Longleftrightarrow\ {parameter}\in {answer}")
    else:
        before.append(branch["delta_condition"])
        delta = math_value(branch["delta_condition"])["latex"]
        delta_set = math_value(branch["delta_solution"])["latex"]
        grouped_delta = rf"\left({delta_set}\right)" if isinstance(branch["delta_solution"], sp.Union) else delta_set
        grouped_domain = rf"\left({domain}\right)" if isinstance(branch["domain"], sp.Union) else domain
        if fixed_opening and branch["domain"] == sp.S.Reals:
            equation = rf"{delta}\ \Longleftrightarrow\ {parameter}\in {answer}"
        else:
            equation = (r"\begin{aligned}" + rf"{delta}&\ \Longleftrightarrow\ {parameter}\in {delta_set}"
                        + r"\\" + rf"{parameter}&\in {grouped_domain}\cap {grouped_delta}={answer}" + r"\end{aligned}")
    return {"before": before, "branch_equation": equation, "branch_answer": answer}


def _opening_branch_merge(values):
    branches = values["branches"]
    total = math_value(values["after"][-1])["latex"]
    pieces = [math_value(branch["solution"])["latex"] for branch in branches]
    return {"opening_union": r" \cup ".join(pieces) + "=" + total,
            "opening_total": total}


def _degree_cases(values):
    """Display the certified partition; presentation does not solve it again."""
    zero_cases = [case["condition"] for case in values["cases"] if case["kind"] == "degenerate"]
    zero_condition = sp.Or(*zero_cases)
    # The solver's residual mirrors <= relations; students keep lhs-rhs.
    coefficient = values["coefficient"] if values["relation"].rel_op in (">", ">=") else -values["coefficient"]
    zero_relation = sp.Eq(coefficient, 0, evaluate=False)
    zero_chain = [zero_relation] if zero_relation == zero_condition else [zero_relation, zero_condition]
    return {"degree_coefficient": coefficient, "degree_zero_condition": zero_condition,
            "degree_other_condition": sp.Ne(coefficient, 0, evaluate=False),
            "degree_zero_chain": r" \Longleftrightarrow ".join(math_value(item)["latex"] for item in zero_chain)}


def _degenerate_case(values):
    return {"is_constant": values["linear_coefficient"].is_zero is True,
            "case_condition": sp.Eq(values["parameter"], values["value"], evaluate=False),
            "substituted_relation": values["after"][0]}


def _solution_view(values):
    symbols = set().union(*(item.free_symbols for item in values["before"] if isinstance(item, sp.Basic)))
    return {"solution_set": values["after"][-1], "solution_symbol": symbols.pop() if len(symbols) == 1 else None}


def _separation_naming(values):
    return {"named": bool(values["function_name"]) and values["function"].has(values["x"]),
            "operator_tex": {"<=": r"\leq", "<": "<", ">=": r"\geq", ">": ">"}[values["operator"]],
            "divisor_negative": bool(values.get("divisor", sp.S.One).is_negative)}


_OPERATOR_TEX = {"<=": r"\leq", "<": "<", ">=": r"\geq", ">": ">"}
_MIRROR = {"<=": ">=", "<": ">", ">=": "<=", ">": "<"}
_WEAK = {"<": "<=", ">": ">=", "<=": "<=", ">=": ">="}


def _policy_view(values):
    """The quantified relation and the bound comparison it reduces to, as the policy states them.

    Without an attainment proof, a universal strict relation reads as the weak
    bound comparison with an equality caveat. Proven extrema keep strictness.
    A function the method named earlier is referred to by that name.
    """
    policy, function, expression, x = values["policy"], values["function"], values["parameter_expression"], values["x"]
    operator, universal = policy["operator"], policy["quantifier"] == "∀"
    numeric = not expression.free_symbols
    attained = polynomial_extrema_attained(function, x, values["domain"])
    shown = _WEAK[operator] if universal and not attained else operator
    x_tex = math_value(x)["latex"]
    named = bool(values["function_name"]) and function.has(x)
    body = f"{values['function_name']}({x_tex})" if named else math_value(function)["latex"]
    bound_body = rf"\left({body}\right)" if not function.is_Atom and not named else body
    target = math_value(expression)["latex"]

    def compare(left, op):
        return (f"{left} {_OPERATOR_TEX[_MIRROR[op]]} {target}" if numeric
                else f"{target} {_OPERATOR_TEX[op]} {left}")
    extreme = rf"{bound_body}_{{{(EXTREMUM_TEX if attained else BOUND_TEX)[policy['bound']]}}}"
    definition = f"{body}={math_value(function)['latex']}" if named and values["define_name"] else ""
    return {"policy_relation": compare(body, operator), "policy_definition": definition,
            "policy_condition": compare(extreme, shown), "policy_condition_short": compare(extreme, shown),
            "policy_universal": universal, "policy_low": policy["bound"] == "inf", "policy_strict": policy["strict"],
            "policy_attained": attained, "bound_explanation": "" if attained else BOUND_EXPLANATION}


def _hook_view(values):
    """The hook ``ax+b/x+c`` as a derivation: AM-GM at the turn, the two monotone pieces, the domain's side.

    The turn and the endpoint values come from the capability; this only splits
    the half axis at the turn and writes the equivalent formulas.
    """
    function, x, domain, turn = values["function"], values["x"], values["domain"], values["turn"]
    a, c, b = reciprocal_coefficients(function, x)
    point, minimum = turn["point"], turn["minimum"]
    positive = point.is_positive is True
    half = sp.Interval.open(0, sp.oo) if positive else sp.Interval.open(-sp.oo, 0)
    left = sp.Interval.Lopen(half.start, point) if positive else sp.Interval(half.start, point, True, False)
    right = sp.Interval.Ropen(point, half.end) if positive else sp.Interval(point, half.end, False, True)
    side = ("left" if (domain.sup - point).is_nonpositive
            else "right" if (domain.inf - point).is_nonnegative else "both")
    label = (f"{values['function_name']}({math_value(x)['latex']})" if values["function_name"]
             else math_value(function)["latex"])
    peak_label = label if values["function_name"] else rf"\left({label}\right)"

    def tex(value):
        return {sp.oo: r"+\infty", -sp.oo: r"-\infty"}.get(value, math_value(value)["latex"])

    def call(at):
        if values["function_name"]:
            return rf"{values['function_name']}\left({tex(at)}\right)"
        return rf"\left.{label}\right|_{{{math_value(x)['latex']}={tex(at)}}}"

    # Both terms are positive on the half axis after multiplying by ``sign``, so
    # h = sign·(p + q) + c and AM-GM bounds p + q by 2·sqrt(p·q) with p = q at the turn.
    sign = 1 if (a * point).is_positive else -1
    p, q = sign * a * x, sign * b / x
    shift = "" if c == 0 else ("+" if c.is_positive else "") + math_value(c)["latex"]
    grouped = math_value(p + q)["latex"]
    product = r"\cdot ".join(rf"\left({math_value(t)['latex']}\right)" if t.could_extract_minus_sign()
                             else math_value(t)["latex"] for t in (p, q))
    bound = rf"2\sqrt{{{product}}}"
    amgm = (rf"{label}={grouped}{shift} \geq {bound}{shift}" if sign > 0
            else rf"{label}=-\left({grouped}\right){shift} \leq -{bound}{shift}")
    amgm += f"={tex(turn['value'])}"
    x_tex = math_value(x)["latex"]
    ends = []
    for row in values["endpoints"]:
        at, value = row["point"], row["value"]
        if row["attained"]:
            ends.append({"attained": True, "equation": f"{call(at)}={tex(value)}"})
            continue
        side_mark = "" if at in (sp.oo, -sp.oo) else ("^{+}" if at == domain.inf else "^{-}")
        ends.append({"attained": False, "approach": rf"{x_tex}\to {tex(at)}{side_mark}",
                     "limit": rf"{label}\to {tex(value)}"})
    return {"hook_label": label, "hook_left": left, "hook_right": right, "hook_minimum": minimum,
            "hook_turn": rf"\left({math_value(point)['latex']},\,{math_value(turn['value'])['latex']}\right)",
            "hook_side": side, "hook_relation": f"{x_tex}>0" if positive else f"{x_tex}<0",
            "hook_positive": [math_value(t)["latex"] for t in (p, q) if t != x], "hook_amgm": amgm,
            "hook_equal": math_value(sp.Eq(p, q, evaluate=False))["latex"],
            "hook_peak": f"{peak_label}_{{{EXTREMUM_TEX['inf' if minimum else 'sup']}}}={call(point)}={tex(turn['value'])}",
            "hook_ends": ends}


def _affine_substitution_view(values):
    """Keep the original function's argument while displaying its substituted expression."""
    original = math_value(values["original_expression"])["latex"]
    variable = math_value(values["original_variable"])["latex"]
    label = f"{values['function_name']}({variable})" if values["function_name"] else original
    return {"affine_original": f"{label}={original}" if values["function_name"] else original,
            "affine_identity": f"{label}={math_value(values['expression'])['latex']}"}


def _affine_restore_view(values):
    """Select certified points and attainment; never infer an extremum from the turn alone."""
    points, turn = values["points"], values["turn"]
    rows = [*points, *(row for row in values["endpoints"]
                       if not any(row["point"] == point["point"] for point in points))]
    turn_attained = turn is not None and turn.get(
        "attained", any(row["point"] == turn["point"] and row["attained"] for row in points))
    bounds = values["range"]
    label = (f"{values['function_name']}({math_value(values['original_variable'])['latex']})"
             if values.get("function_name") else
             math_value(values["original_expression"])["latex"] if "original_expression" in values else "")
    return {"affine_restored_rows": rows, "affine_turn_outside": turn is not None and not turn_attained,
            "affine_restored_label": label,
            "affine_bounds": [{"low": key == "inf", "value": bounds[key],
                               "finite": bounds[key] not in (-sp.oo, sp.oo),
                               "attained": bounds[key + "_attained"]} for key in ("inf", "sup")]}


# Preparation functions only select supplied evidence or construct equivalent
# mathematical objects. They contain no prose and never perform solving.
from .abstract_domain_presentation import presentation as abstract_domain_presentation
from .abstract_parameter_presentation import (
    presentation as abstract_parameter_presentation,
)
from .domain_presentation import parameter_view as domain_parameter_view
from .domain_presentation import presentation as domain_presentation
from .equality_presentation import view as equality_view
from .evaluation_presentation import presentation as evaluation_presentation
from .formula_presentation import presentation as formula_presentation
from .quantified_subproblem import presentation as quantified_subproblem_view
from .range_presentation import presentation as range_presentation
from .substitution_interaction import range_presentation as substituted_range_view

PREPARERS = {
    'substituted_range_view': substituted_range_view,
    'quantified_subproblem_view': quantified_subproblem_view,
    'piecewise_range_view': _piecewise_range_view,
    'piecewise_range_parameter_view': _piecewise_range_parameter_view,
    'piecewise_inequality_view': _piecewise_inequality_view,
    'piecewise_modeling_view': _piecewise_modeling_view,
    'piecewise_equation_view': _piecewise_equation_view,
    'extremum_view': _extremum_view,
    'mono_inequality_view': _mono_inequality_view,
    'mono_parameter_view': _mono_parameter_view,
    'parity_parameter_view': _parity_parameter_view,
    'parity_extension_view': _parity_extension_view,
    'function_symmetry_view': _function_symmetry_view,
    'monotonicity_view': _monotonicity_view,
    'abstract_monotonicity_view': _abstract_monotonicity_view,
    'parity_view': _parity_view,
    'function_graph_view': _function_graph_view,
    'function_formula_view': formula_presentation,
    'function_range_view': range_presentation,
    'function_evaluation_view': evaluation_presentation,
    'equality_view': equality_view,
    'abstract_domain_view': abstract_domain_presentation,
    'abstract_domain_parameter_view': abstract_parameter_presentation,
    "domain_view": domain_presentation,
    "domain_parameter_view": domain_parameter_view,
    "normalize_view": _normalize_view,
    "variable_swap": _variable_swap,
    "variable_range": _variable_range, "variable_conditions": _variable_conditions,
    "variable_cases": _interval_cases, "variable_case_merge": variable_merge_view,
    "variable_slope": variable_slope_view, "variable_sign_case": variable_case_view,
    "degree_case_merge": _degree_case_merge,
    "numeric_range": _numeric_range, "interval_cases": lambda v: {**_interval_cases(v), **cases_view(v)},
    "classified_range": lambda v: {**_classified_range(v), **classified_view(v)},
    "interval_merge": lambda v: {**_interval_merge(v), **merge_view(v)},
    "endpoint_bounds": _endpoint_bounds, "linear_case": lambda v: {**_numeric_range(v), **linear_view(v)},
    "interval_conditions": lambda v: {**_interval_conditions(v), **conditions_view(v)},
    "opening": _opening, "degree_cases": _degree_cases,
    "degenerate_case": _degenerate_case, "separation_naming": _separation_naming,
    "policy_view": _policy_view, "hook_view": _hook_view, "solution_view": _solution_view,
    "discriminant_view": _discriminant_condition_view,
    "opening_branch_solution": _opening_branch_solution, "opening_branch_merge": _opening_branch_merge,
    "affine_substitution_view": _affine_substitution_view, "affine_restore_view": _affine_restore_view,
}
_DISCRIMINANT_FIELDS = {"display_expression", "display_coefficient", "display_opening", "comparison_positive",
                        "fixed_positive", "fixed_negative", "actual_opening", "automatic_opening",
                        "delta_opening", "delta_vertex", "target_side", "target_sign_text",
                        "opening_mode", "opening_summary", "vertex_position", "opening_determined"}
PREPARED_FIELDS = {
    'substituted_range_view': {'range_label', 'range_identity', 'range_title', 'range_result', 'range_explanation'},
    'quantified_subproblem_view': {'subproblem_statement', 'subproblem_title', 'subproblem_explanation', 'subproblem_caption'},
    'piecewise_range_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'piecewise_range_parameter_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'piecewise_inequality_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'piecewise_modeling_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'piecewise_equation_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'monotonicity_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'extremum_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'mono_inequality_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'mono_parameter_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'parity_parameter_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'parity_extension_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'function_symmetry_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'abstract_monotonicity_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'parity_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'function_graph_view': {'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label', 'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math'},
    'function_formula_view': {
        'formula_title', 'formula_explanation', 'derivation_caption', 'derivation_left_label',
        'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math',
    },
    'function_range_view': {
        'range_title', 'range_explanation', 'derivation_caption', 'derivation_left_label',
        'derivation_left_math', 'derivation_left_note', 'derivation_right_label', 'derivation_right_math',
    },
    'function_evaluation_view': {
        'evaluation_title', 'evaluation_explanation', 'derivation_caption',
        'derivation_left_label', 'derivation_left_math', 'derivation_left_note',
        'derivation_right_label', 'derivation_right_math', 'condition_groups', 'pairing_diagram',
    },
    'abstract_domain_parameter_view': {
        'domain_explanation', 'derivation_caption', 'derivation_left_label',
        'derivation_left_math', 'derivation_left_note', 'derivation_right_label',
        'derivation_right_math', 'interval_explorer',
    },
    'equality_view': {
        'equality_explanation', 'option_label', 'left_name', 'right_name',
        'left_math', 'right_math', 'left_domain', 'right_domain',
        'domain_connector', 'correspondence_connector', 'relation_connector',
        'left_value_math', 'right_value_math', 'correspondence_caption',
        'verdict_result', 'domain_relation_result',
    },
    'abstract_domain_view': {
        'domain_explanation', 'derivation_caption', 'derivation_left_label',
        'derivation_left_math', 'derivation_left_note', 'derivation_right_label',
        'derivation_right_math',
    },
    "domain_view": {"domain_lines", "domain_explanation"},
    "domain_parameter_view": {"domain_lines", "domain_explanation"},
    "normalize_view": {"normalization_chain", "normalization_relations"},
    "variable_swap": {"swap_identity"},
    "variable_range": {"after", "square", "has_square", "multiple"},
    "variable_conditions": {"before", "after", "multiple"},
    "variable_cases": {"after"},
    "variable_slope": {"slope_rows", "single_sign", "slope_chain"},
    "variable_sign_case": {"bound_identity", "bound_attained", "bound_name", "case_constant",
                           "case_conditions", "case_answer", "case_chain"},
    "variable_case_merge": {"before", "case_solutions", "merge_equation", "merge_answer"},
    "degree_case_merge": {"merge_rows", "merge_equation", "merge_total"},
    "numeric_range": {"constant"},
    "interval_cases": {"after", "case_rows", "opening", "axis", "function_label", "bound_name"},
    "classified_range": {"after", "bound_value", "bound_attained", "has_vertex", "case_condition", "axis_relation",
                         "leading_relation", "monotone", "function_label", "extreme", "approach", "axis_fixed",
                         "place", "opening"},
    "linear_case": {"constant", "case_condition", "function_label", "trend", "range_set", "case_function"},
    "interval_merge": {"before", "after", "case_solutions", "merge_rows", "merge_total"},
    "endpoint_bounds": {"after"},
    "interval_conditions": {"before", "after", "multiple", "case_condition", "condition_list", "condition_system",
                            "any_condition", "case_answer"},
    "opening": _DISCRIMINANT_FIELDS | {"opening", "after", "opening_conclusion"},
    "degree_cases": {"degree_coefficient", "degree_zero_condition", "degree_other_condition", "degree_zero_chain"},
    "degenerate_case": {"is_constant", "case_condition", "substituted_relation"},
    "separation_naming": {"named", "operator_tex", "divisor_negative"},
    "policy_view": {"policy_relation", "policy_definition", "policy_condition", "policy_condition_short", "policy_universal",
                    "policy_low", "policy_strict", "policy_attained", "bound_explanation"},
    "solution_view": {"solution_set", "solution_symbol"},
    "discriminant_view": _DISCRIMINANT_FIELDS | {"delta_formula", "delta_condition_words", "delta_conclusion", "delta_requirements",
                                               "before", "after"},
    "opening_branch_solution": {"before", "branch_equation", "branch_answer"},
    "opening_branch_merge": {"opening_union", "opening_total"},
    "hook_view": {"hook_label", "hook_left", "hook_right", "hook_minimum", "hook_turn", "hook_side",
                  "hook_relation", "hook_positive", "hook_amgm", "hook_equal", "hook_peak", "hook_ends"},
    "affine_substitution_view": {"affine_original", "affine_identity"},
    "affine_restore_view": {"affine_restored_rows", "affine_turn_outside", "affine_bounds", "affine_restored_label"},
}


def _validate_path(path, names):
    if (not isinstance(path, str) or not re.fullmatch(r"[A-Za-z][A-Za-z_0-9]*(?:\.[A-Za-z][A-Za-z_0-9]*)*", path)
            or path.split(".")[0] not in names):
        raise ValueError("presentation.unknown_template_binding:" + str(path))


def _validate_node(node, names):
    if isinstance(node, str):
        for _, name, spec, conversion in _FORMATTER.parse(node):
            if name is not None:
                _validate_path(name, names)
                if spec or conversion:
                    raise ValueError("presentation.unsupported_template_format")
        return
    if isinstance(node, list):
        for item in node:
            _validate_node(item, names)
        return
    if not isinstance(node, dict):
        raise TypeError("presentation.invalid_template_node")
    if "if" in node and set(node) <= {"if", "then", "else"} and "then" in node:
        _validate_path(node["if"], names)
        _validate_node(node["then"], names)
        _validate_node(node.get("else", ""), names)
    elif "select" in node and set(node) <= {"select", "cases", "default"} and isinstance(node.get("cases"), dict):
        _validate_path(node["select"], names)
        for value in [*node["cases"].values(), node.get("default", "")]:
            _validate_node(value, names)
    elif "for" in node and set(node) <= {"for", "as", "body", "separator"} and "body" in node:
        _validate_path(node["for"], names)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", node.get("as", "")) or not isinstance(node.get("separator", ""), str):
            raise ValueError("presentation.invalid_template_loop")
        _validate_node(node["body"], names | {node["as"]})
    else:
        raise ValueError("presentation.unknown_template_node")


def validate_registry(registry):
    for specification in registry["templates"].values():
        if type(specification.get("omit_if_unchanged", False)) is not bool:
            raise ValueError("presentation.invalid_unchanged_policy")
        preparation = specification.get("prepare")
        if preparation is not None and preparation not in PREPARERS:
            raise ValueError("presentation.unknown_preparer:" + str(preparation))
        names = set(specification["required_bindings"]) | PREPARED_FIELDS.get(preparation, set()) | {"has_case"}
        for name, node in specification.get("variables", {}).items():
            _validate_node(node, names)
            names.add(name)
        _validate_node(specification["title"], names)
        _validate_node(specification.get("render", specification["explanation"]), names)
        if "highlight" in specification:
            _validate_highlight(specification["highlight"], names)
    _validate_node(registry["case_prefix"], {"condition"})
    return registry


def _validate_highlight(highlight, names):
    if (not isinstance(highlight, dict)
            or not {"caption", "items"} <= set(highlight)
            <= {"caption", "items", "connector", "result", "conclusion_only", "layout", "replace_with_graph", "show_result", "interval_explorer", "condition_groups", "pairing_diagram"}
            or not isinstance(highlight.get("connector", ""), str)
            or highlight.get("layout", "merge") not in ("merge", "derivation")
            or (highlight.get("layout") == "merge" and "result" not in highlight)
            or not isinstance(highlight.get("conclusion_only", False), bool)
            or not isinstance(highlight.get("show_result", False), bool)
            or (highlight.get("show_result") and "result" not in highlight)
            or not isinstance(highlight.get("replace_with_graph", False), (bool, str))):
        raise ValueError("presentation.invalid_highlight")
    if "interval_explorer" in highlight:
        if highlight.get("layout") != "derivation":
            raise ValueError("presentation.invalid_interval_explorer_layout")
        _validate_path(highlight["interval_explorer"], names)
    if "condition_groups" in highlight:
        if highlight.get("layout") != "derivation":
            raise ValueError("presentation.invalid_condition_groups_layout")
        _validate_path(highlight["condition_groups"], names)
    if "pairing_diagram" in highlight:
        if highlight.get("layout") != "derivation":
            raise ValueError("presentation.invalid_pairing_diagram_layout")
        _validate_path(highlight["pairing_diagram"], names)
    if isinstance(highlight.get("replace_with_graph"), str):
        _validate_path(highlight["replace_with_graph"], names)
    _validate_node(highlight["caption"], names)
    _validate_node(highlight.get("result", ""), names)
    items = highlight["items"]
    if not isinstance(items, list) or not items:
        raise ValueError("presentation.invalid_highlight")
    if highlight.get("layout") == "derivation" and (
            len(items) != 2 or highlight.get("connector") != "⇒"
            or any("for" in item for item in items)):
        raise ValueError("presentation.invalid_derivation_highlight")
    for item in items:
        if not isinstance(item, dict) or not {"label", "math"} <= set(item) <= {"label", "math", "note", "for", "as"}:
            raise ValueError("presentation.invalid_highlight")
        scope = names
        if "for" in item:
            _validate_path(item["for"], names)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", item.get("as", "")):
                raise ValueError("presentation.invalid_highlight")
            scope = names | {item["as"]}
        for key, node in item.items():
            if key not in ("for", "as"):
                _validate_node(node, scope)


def prepare_values(specification, bindings, *, has_case=False):
    values = {**bindings, "has_case": has_case}
    for key in ("before", "after"):
        values[key] = list(values.get(key, []))
    if specification.get("prepare"):
        values.update(PREPARERS[specification["prepare"]](values))
    return values


def render_template(specification, bindings, *, has_case=False):
    values = prepare_values(specification, bindings, has_case=has_case)
    for name, node in specification.get("variables", {}).items():
        values[name] = _render(node, values)
    return values["before"], values["after"], _render(specification.get("render", specification["explanation"]), values)


def render_title(specification, bindings, *, has_case=False):
    return _render(specification["title"], prepare_values(specification, bindings, has_case=has_case))


def render_highlight(specification, bindings, *, has_case=False):
    """The card's emphasised conclusion: a caption over labelled formulas, read left to right.

    ``result`` is the one line the next step starts from.
    """
    if "highlight" not in specification:
        return None
    values = prepare_values(specification, bindings, has_case=has_case)
    for name, node in specification.get("variables", {}).items():
        values[name] = _render(node, values)
    highlight = specification["highlight"]
    items = []
    for item in highlight["items"]:
        fields = {key: node for key, node in item.items() if key not in ("for", "as")}
        scopes = ([{**values, item["as"]: entry} for entry in _lookup(values, item["for"])] if "for" in item
                  else [values])
        items.extend({key: text for key, text in ((key, _render(node, scope)) for key, node in fields.items()) if text}
                     for scope in scopes)
    rendered = {"caption": _render(highlight["caption"], values), "items": items}
    if "connector" in highlight:
        rendered["connector"] = _render(highlight["connector"], values)
    if "layout" in highlight:
        rendered["layout"] = highlight["layout"]
    if "interval_explorer" in highlight:
        explorer = _lookup(values, highlight["interval_explorer"])
        if explorer is not None:
            if not isinstance(explorer, dict):
                raise ValueError("presentation.invalid_interval_explorer")
            rendered["interval_explorer"] = deepcopy(explorer)
    if "condition_groups" in highlight:
        groups = _lookup(values, highlight["condition_groups"])
        if groups is not None:
            if (not isinstance(groups, list) or len(groups) != 2 or any(
                    not isinstance(group, dict) or set(group) != {'label', 'math'}
                    or not all(isinstance(value, str) and value for value in group.values())
                    for group in groups)):
                raise ValueError("presentation.invalid_condition_groups")
            rendered["condition_groups"] = deepcopy(groups)
    if "pairing_diagram" in highlight:
        diagram = _lookup(values, highlight["pairing_diagram"])
        if diagram is not None:
            if not isinstance(diagram, dict):
                raise ValueError("presentation.invalid_pairing_diagram")
            rendered["pairing_diagram"] = deepcopy(diagram)
    if result := _render(highlight.get("result", ""), values):
        rendered["result"] = result
        if highlight.get("show_result"):
            rendered["show_result"] = True
    if highlight.get("conclusion_only"):
        rendered["conclusion_only"] = True
    graph_alternative = highlight.get("replace_with_graph", False)
    if isinstance(graph_alternative, str):
        graph_alternative = _lookup(values, graph_alternative)
        if type(graph_alternative) is not bool:
            raise ValueError("presentation.invalid_graph_alternative")
    if graph_alternative:
        rendered["replace_with_graph"] = True
    return rendered


def render_case_prefix(registry, condition):
    return _render(registry["case_prefix"], {"condition": condition})
