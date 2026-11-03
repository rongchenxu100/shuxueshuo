"""Reuse the quantified-quadratic selection plane when a host method borrows."""

import sympy as sp

from ..stage_one.features import extract_features
from ..stage_two.recognition import load_nodes
from . import capabilities, judgments
from .math_values import latex
from .premises import math_text
from .selection import evaluate_goal

PRIMARY = "type-quantified-quadratic"
TARGET = "/root/goals/0"
REL_OPS = {">=": ">=", ">": ">", "<=": "<=", "<": "<", "==": "=", "!=": "≠"}


def _quantified_fact(values):
    relation = values["universal_statement"]
    op = REL_OPS.get(relation.rel_op)
    if op is None:
        raise ValueError("domain.parameter_borrow_relation_unsupported")
    variable, parameter = values["x"], values["parameter"]
    body = f"{math_text(relation.lhs)}{op}{math_text(relation.rhs)}"
    domain = values["domain"]
    if domain == sp.S.Reals:
        domain_text = "ℝ"
    elif isinstance(domain, sp.Interval):
        def endpoint(value):
            return "-∞" if value is -sp.oo else "+∞" if value is sp.oo else math_text(value)
        domain_text = ("(" if domain.left_open else "[") + endpoint(domain.start) + "," + endpoint(domain.end) + (")" if domain.right_open else "]")
    else:
        raise ValueError("domain.parameter_borrow_domain_unsupported")
    return f"∀{variable}∈{domain_text}:{body}", str(parameter)


def select_borrowed_method(values):
    """Run the graph selection rule on the reduced universal subproblem."""
    borrowed = values.get("borrowed_method")
    host_route = values.get("host_route")
    if not isinstance(borrowed, str) or not borrowed.startswith("method-"):
        raise ValueError("domain.parameter_borrow_method_required")
    if not isinstance(host_route, str) or not host_route:
        raise ValueError("domain.parameter_borrow_host_route_required")
    fact, symbol = _quantified_fact(values)
    candidate = {
        "original_text": fact,
        "root": {"facts": [fact], "goals": [{"kind": "find_range", "symbol": symbol}]},
    }
    features = extract_features(candidate)
    if not features.get("ok"):
        raise ValueError("domain.parameter_borrow_features_failed")
    result = evaluate_goal(candidate, TARGET, features["features"], PRIMARY)
    if result.get("d3") is None or result.get("d4") is None:
        raise ValueError("domain.parameter_borrow_selection_unavailable")
    branch = next(
        (row for row in result["selection"]["branches"] if row["target"] == borrowed),
        None,
    )
    if branch is None or branch.get("recommendation") not in ("preferred", "optional"):
        raise ValueError("domain.parameter_borrow_method_not_fit")
    return result, branch, host_route


def _degenerate_separation(values, interaction_id):
    """A checked direct reuse where the quadratic selection rule does not apply."""
    relation, variable, parameter = values["universal_statement"], values["x"], values["parameter"]
    if values.get("borrowed_method") != "method-separation":
        return None
    polynomial = sp.Poly(relation.lhs - relation.rhs, variable)
    if polynomial.degree() > 1:
        return None
    separated = capabilities.inspect_separation(relation, parameter, variable, values["domain"])
    if not separated["checks"] or not all(row.get("passed") is True for row in separated["checks"]):
        raise ValueError("domain.parameter_borrow_separation_unchecked")
    outputs = separated["outputs"]
    judgments.range_skill(outputs["function"], variable, values["domain"], reserved_symbols=(parameter,))
    method_label = load_nodes()["method-separation"]["label"]
    question = (
        rf"当前子问题为 $\forall {latex(variable)}\in {latex(values['domain'])},\ {latex(relation)}$。"
        f"关于自变量的式子已退化为一次或常数，参数可分离。借用{method_label}，先分离参数，再在题给范围求值域。"
    )
    return {
        "parts": [{"id": interaction_id + "#1", "title": "借用已学方法", "question": question,
                   "submit_label": "继续", "interaction": {"type": "read"}, "expected_answer": {},
                   "feedback": {"answer": "确认参数可分离后，继续在题给范围内求值域。"}, "effects": {"log": f"借用已学方法：{method_label}。",
                                                "nodes": ["method-separation"]}}],
        "diagnostics": [{"kind": "checked_degenerate_domain_parameter_borrow", "method": "method-separation",
                         "degree": int(polynomial.degree()), "passed": True}],
    }


def compile_borrow_plane(values, interaction_id):
    """Project rule-quadratic-method D3 as the mid-route borrow card."""
    direct = _degenerate_separation(values, interaction_id)
    if direct is not None:
        return direct
    result, branch, host_route = select_borrowed_method(values)
    d3, d4 = result["d3"], result["d4"]
    nodes = load_nodes()
    coverage = d3["interaction"]["coverage"]
    options_by_branch = {row["branch"]: row for row in d4["options"]}
    method_label = nodes[branch["target"]]["label"]
    methods, alternatives = [], {}
    for key, cells in coverage.items():
        option = options_by_branch.get(key)
        target = option["method"] if option else next(
            row["target"] for row in result["selection"]["branches"] if row["branch"] == key
        )
        label = nodes[target]["label"]
        entry = {"value": key, "label": label, "target": target, "cells": [list(cell) for cell in cells]}
        if key == branch["branch"]:
            entry.update(route=host_route, route_plan="planned")
        elif option:
            entry["route_plan"] = option["route_plan"]
            alternatives[key] = {
                "message": f"{label}适用于当前子问题，但本次尚未展开这条子方法路线。可以选择{method_label}继续。",
                "href": f"/knowledge/{target}/",
            }
        methods.append(entry)
    variable, relation = latex(values["x"]), latex(values["universal_statement"])
    feedback = {
        "x": d3["feedback"]["x"],
        "y": d3["feedback"]["y"],
        "method": d3["feedback"]["method"],
        "method_choice": f"当前恒成立子问题使用{method_label}；其它适用方法不在本路线展开。",
    }
    part = {
        "id": interaction_id + "#1",
        "title": "选择已学方法",
        "question": (
            rf"当前子问题是：对所有 ${variable}\in {latex(values['domain'])}$，都有 ${relation}$。"
            "本题落在选法坐标的哪一格？应借用哪一种已学方法？"
        ),
        "submit_label": d3["submit_label"],
        "interaction": {
            "type": "plane",
            "title": d3["interaction"]["title"],
            "x": d3["interaction"]["x"],
            "y": d3["interaction"]["y"],
            "methods": methods,
        },
        "expected_answer": {"cell": list(d3["expected_answer"]["cell"]), "method": branch["branch"]},
        # The expected method identifies the expanded/replay route. Applicable
        # unexpanded methods remain valid choices, without completing this step.
        "alternatives": alternatives,
        "feedback": feedback,
        "effects": {
            "log": f"借用已学方法：{method_label}。",
            "nodes": ["rule-quadratic-method", branch["target"]],
        },
    }
    diagnostics = [{
        "kind": "checked_domain_parameter_borrow",
        "method": branch["target"],
        "rule": result["selection"]["rule"],
        "branch": branch["branch"],
        "cell": list(d3["expected_answer"]["cell"]),
    }]
    return {"parts": [part], "diagnostics": diagnostics}
