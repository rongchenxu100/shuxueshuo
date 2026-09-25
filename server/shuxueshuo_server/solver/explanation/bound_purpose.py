"""Describe the effect of an already verified bound; never authorize a proof."""

from ..math_kernel.expression_parser import parse_math_expression
from ..math_kernel.expression_rewrite import _legacy_tree, tree_latex


def verified_bound_effect(source, result, symbols):
    before = parse_math_expression(source, symbols)
    after = parse_math_expression(result, symbols)
    input_symbols = sorted(str(s) for s in before.to_sympy(symbols).free_symbols)
    output_symbols = sorted(str(s) for s in after.to_sympy(symbols).free_symbols)
    removed = sorted(set(input_symbols) - set(output_symbols))
    introduced = set(output_symbols) - set(input_symbols)
    kind = "bound"
    if input_symbols and not introduced:
        if not output_symbols:
            kind = "constant_bound"
        elif removed:
            kind = "eliminate_variable"
    return {
        "kind": kind,
        "input_symbols": input_symbols,
        "output_symbols": output_symbols,
        "removed_symbols": removed,
        "before_latex": tree_latex(_legacy_tree(before.ast)),
        "after_latex": tree_latex(_legacy_tree(after.ast)),
    }


def purpose_cards(items):
    """Generic card data: purpose and tool are separate, not frontend dispatch."""
    cards = []
    for i, data in enumerate(items):
        effect = data.get("teaching_effect", {})
        if effect.get("kind") not in {"eliminate_variable", "constant_bound"}:
            return []
        eliminate = effect["kind"] == "eliminate_variable"
        cards.append(
            {
                "label": f"第{i + 1}步",
                "purpose": "消去 " + "、".join(effect["removed_symbols"])
                if eliminate
                else "求解",
                "tool": "基本不等式",
                "progressLabel": "变量数变化",
                "progress": str(len(effect["input_symbols"]))
                + " → "
                + (str(len(effect["output_symbols"])) if eliminate else "定值"),
                "before": r"\(" + effect["before_latex"] + r"\)",
                "after": r"\(" + effect["after_latex"] + r"\)",
                "reason": "配对项的乘积：\\("
                + r"\left("
                + data["term_latex"][0]
                + r"\right)\cdot\left("
                + data["term_latex"][1]
                + r"\right)="
                + data["paired_product_latex"]
                + r"\)",
                "detail": ("求界式只剩 " + "、".join(effect["output_symbols"]))
                if eliminate
                else "得到常数下界，随后检查取等",
            }
        )
    return cards


def relation_count_plan(items):
    """A teaching heuristic checked against this route, never a proof rule.

    Do not infer how many inequalities to execute from the subtraction. Only
    show it when the submitted route supplies that many distinct equalities.
    This does not assert independence, uniqueness, or exhaustiveness of roots.
    """
    import sympy as sp

    from ..math_kernel.expression_parser import parse_math_relation

    if not items or not all(d.get("teaching_effect") for d in items):
        return None
    variables = items[0]["teaching_effect"]["input_symbols"]
    existing = items[0].get("condition_equations_latex")
    if existing is None or len(set(existing)) != len(existing):
        return None
    # Existing conditions are kept as supplied; ambiguous counting is omitted.
    if any(d.get("condition_equations_latex") != existing for d in items):
        return None
    symbols = {name: sp.Symbol(name, real=True) for name in variables}
    keys = set()
    applications = items[-1].get("applications", [])
    for application in applications:
        parsed = parse_math_relation(application["equality"], symbols)
        left, right = parsed.ast.children
        lhs = parse_math_expression(parsed.source[slice(*left.span)], symbols).to_sympy(
            symbols
        )
        rhs = parse_math_expression(
            parsed.source[slice(*right.span)], symbols
        ).to_sympy(symbols)
        difference = sp.cancel(lhs - rhs)
        if not difference.free_symbols:
            return None
        numerator = sp.fraction(difference)[0]
        try:
            polynomial = sp.Poly(numerator, *symbols.values())
        except sp.PolynomialError:
            return None
        key = polynomial.monic().as_expr()
        keys.add(key)
    missing = len(variables) - len(existing)
    if missing <= 0 or missing != len(keys) or len(keys) != len(applications):
        return None
    return {
        "ariaLabel": "规划取等关系：变量数减去已有取等条件数",
        "variable": {
            "label": "变量数",
            "value": str(len(variables)),
            "detail": "、".join(variables),
        },
        "condition": {
            "label": "已有取等条件数",
            "value": str(len(existing)),
            "detail": "；".join(r"\(" + e + r"\)" for e in existing) or "无",
        },
        "result": {"label": "待补取等关系数", "value": str(missing)},
    }
