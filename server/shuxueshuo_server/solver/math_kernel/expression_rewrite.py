"""Bounded rational rewrite verification with a separate ordered display tree.

No candidate text is evaluated as Python. Tree ids are local display ids, not
MathObject identities. All algebra uses the caller's existing Symbol objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sympy as sp
from sympy.core.relational import Relational

from .expression_parser import MathParseError, _parse, _sympy


class RewriteError(ValueError):
    def __init__(self, code: str, message: str, row: int | None = None):
        self.code, self.row = code, row
        self.message = message
        super().__init__(
            f"{code}"
            + (f" at steps[{row}]" if row is not None else "")
            + f": {message}"
        )


@dataclass
class ParsedExpression:
    source: str
    tree: dict[str, Any]
    value: sp.Expr
    denominators: tuple[sp.Expr, ...]


def _parser_error(exc: MathParseError) -> RewriteError:
    error = RewriteError(exc.code, exc.message, exc.step)
    error.source, error.span = exc.source, exc.span
    error.path, error.source_path = exc.path, exc.source_path
    return error


def _legacy_tree(node, path="n"):
    # Historical M01 trees omit parentheses nodes and use n.0/n.1 ids.
    result = {"id": path, "op": node.op}
    if node.text is not None:
        result["text"] = node.text
    if node.children:
        result["children"] = [
            _legacy_tree(child, f"{path}.{i}") for i, child in enumerate(node.children)
        ]
    return result


def _legacy_parsed(source, symbols, *, relation=False):
    parsed = _parse(source, symbols, relation=relation, legacy=True)
    # Keep M01's computational power guard as well as the syntax budgets. A
    # division such as 1/x lowers to Pow even without a written power operator.
    for node in parsed.ast.walk():
        if node.op == "pow":
            base = _sympy(node.children[0], symbols)
            if base.has(sp.Pow) or sp.count_ops(base) > 24:
                raise MathParseError(
                    "expression_too_large",
                    "首轮不接受嵌套幂或大型幂展开",
                    source=source,
                    span=node.span,
                    path=node.path,
                )
    return parsed


def _postorder(node):
    for child in node.children:
        yield from _postorder(child)
    yield node


def parse_expression(source: str, symbols: Mapping[str, sp.Symbol]) -> ParsedExpression:
    try:
        parsed = _legacy_parsed(source, symbols)
        obligations = {item.node_path: item for item in parsed.obligations}
        return ParsedExpression(
            source,
            _legacy_tree(parsed.ast),
            parsed.to_sympy(symbols),
            tuple(
                _sympy(obligations[node.path].expression, symbols)
                for node in _postorder(parsed.ast)
                if node.path in obligations
            ),
        )
    except MathParseError as exc:
        raise _parser_error(exc) from exc


def tree_latex(tree: dict) -> str:
    op = tree["op"]
    if op in ("symbol", "integer"):
        return sp.latex(sp.Symbol(tree["text"])) if op == "symbol" else tree["text"]
    children = tree["children"]
    a = tree_latex(children[0])
    if op in ("neg", "pos"):
        return ("-" if op == "neg" else "+") + "\\left(" + a + "\\right)"
    b = tree_latex(children[1])
    if op == "div":
        return "\\frac{" + a + "}{" + b + "}"
    if op == "pow":
        if children[0]["op"] in ("add", "sub", "mul", "neg"):
            a = "\\left(" + a + "\\right)"
        return "{" + a + "}^{" + b + "}"
    if op == "mul":
        if children[0]["op"] in ("add", "sub"):
            a = "\\left(" + a + "\\right)"
        if children[1]["op"] in ("add", "sub"):
            b = "\\left(" + b + "\\right)"
        return a + "\\cdot " + b
    if children[1]["op"] in ("add", "sub"):
        b = "\\left(" + b + "\\right)"
    return a + ("+" if op == "add" else "-") + b


def formula(parsed: ParsedExpression) -> dict:
    return {"latex": tree_latex(parsed.tree), "tree": parsed.tree}


def parse_relation(text: str, symbols: Mapping[str, sp.Symbol]) -> Relational:
    try:
        return _legacy_parsed(text, symbols, relation=True).to_sympy(symbols)
    except MathParseError as exc:
        raise _parser_error(exc) from exc


def relation_from_bound(value: Any, symbols: Mapping[str, sp.Symbol]) -> Relational:
    if isinstance(value, Relational):
        return value
    if isinstance(value, str):
        return parse_relation(value, symbols)
    if isinstance(value, dict):
        if "expression" in value:
            return parse_relation(str(value["expression"]), symbols)
        if "symbol" in value and "operator" in value and "value" in value:
            return parse_relation(
                f"{value['symbol']}{value['operator']}{value['value']}", symbols
            )
    raise RewriteError("unsupported_condition", "无法读取已绑定的数学条件")


def same_relation(x: Relational, y: Relational) -> bool:
    if type(x) is not type(y):
        return False
    if isinstance(x, (sp.Equality, sp.Unequality)):
        # Constant nonzero scaling preserves the relation, including reversed equality.
        dx, dy = sp.cancel(x.lhs - x.rhs), sp.cancel(y.lhs - y.rhs)
        if dx == 0 or dy == 0:
            return dx == dy
        ratio = sp.cancel(dx / dy)
        return not ratio.free_symbols and ratio.is_zero is False
    return sp.cancel(x.lhs - y.lhs) == 0 and sp.cancel(x.rhs - y.rhs) == 0


def _domain_nonzero(expr: sp.Expr, conditions: list[Relational]) -> bool:
    if expr.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
        return False
    if expr.is_zero is False:
        return True
    predicates = []
    for c in conditions:
        delta = c.lhs - c.rhs
        if isinstance(c, sp.StrictGreaterThan):
            predicates.append(sp.Q.positive(delta))
        elif isinstance(c, sp.StrictLessThan):
            predicates.append(sp.Q.negative(delta))
        elif isinstance(c, sp.Unequality):
            predicates.append(sp.Q.nonzero(delta))
    assumptions = sp.And(*predicates)
    if sp.ask(sp.Q.nonzero(expr), assumptions) is True:
        return True
    if expr.is_Mul:
        return all(_domain_nonzero(x, conditions) for x in expr.args)
    if expr.is_Pow and expr.exp.is_Integer:
        return _domain_nonzero(expr.base, conditions)
    return False


def verify_equivalence(
    before: sp.Expr, after: sp.Expr, using: list[Relational]
) -> bool:
    difference = sp.cancel(before - after)
    if difference == 0:
        return True
    equations = [sp.cancel(c.lhs - c.rhs) for c in using if isinstance(c, sp.Equality)]
    if not equations:
        return False
    symbols = sorted(
        difference.free_symbols | set().union(*(e.free_symbols for e in equations)),
        key=str,
    )
    if not symbols:
        return False
    # Polynomial ideal membership is a sufficient certificate, never numerical probing.
    numerator = sp.fraction(difference)[0]
    polynomials = [sp.fraction(e)[0] for e in equations]
    try:
        if len(symbols) > 4 or len(polynomials) > 4:
            raise RewriteError("proof_limit", "超出首轮有理式证明规模")
        for p in [numerator, *polynomials]:
            poly = sp.Poly(p, *symbols)
            if poly.total_degree() > 12 or len(poly.terms()) > 128:
                raise RewriteError("proof_limit", "超出首轮多项式证明规模")
        basis = sp.groebner(polynomials, *symbols)
        if list(basis) == [1]:
            raise RewriteError("inconsistent_conditions", "绑定条件相互矛盾")
        return basis.reduce(numerator)[1] == 0
    except (sp.PolynomialError, sp.polys.polyerrors.CoercionFailed):
        return False


def _terms(tree: dict) -> list[dict]:
    return (
        _terms(tree["children"][0]) + _terms(tree["children"][1])
        if tree["op"] == "add"
        else [tree]
    )


def _signature(tree: dict):
    return (
        tree["op"],
        tree.get("text"),
        tuple(_signature(x) for x in tree.get("children", [])),
    )


def _value(tree: dict, symbols: Mapping[str, sp.Symbol]) -> sp.Expr:
    op = tree["op"]
    if op == "symbol":
        return symbols[tree["text"]]
    if op == "integer":
        return sp.Integer(tree["text"])
    args = [_value(x, symbols) for x in tree["children"]]
    if op == "neg":
        return -args[0]
    if op == "pos":
        return args[0]
    x, y = args
    return {
        "add": lambda: x + y,
        "sub": lambda: x - y,
        "mul": lambda: x * y,
        "div": lambda: x / y,
        "pow": lambda: x**y,
    }[op]()


def _sum_formula(terms: list[dict]) -> dict:
    return {
        "latex": "+".join(tree_latex(t) for t in terms),
        "nodeIds": [t["id"] for t in terms],
    }


def classify(
    before: ParsedExpression,
    after: ParsedExpression,
    using: list[int],
    conditions: list[Relational],
    symbols: Mapping[str, sp.Symbol],
) -> dict:
    old, new = _terms(before.tree), _terms(after.tree)
    unchanged = []
    for t in list(old):
        found = next((s for s in new if _signature(s) == _signature(t)), None)
        if found is not None:
            unchanged.append(
                {
                    "latex": tree_latex(t),
                    "beforeNodeId": t["id"],
                    "afterNodeId": found["id"],
                }
            )
            old.remove(t)
            new.remove(found)
    result = {
        "operation": "equivalent_rewrite",
        "before": formula(before),
        "after": formula(after),
        "localBefore": _sum_formula(old),
        "localAfter": _sum_formula(new),
        "unchanged": unchanged,
        "highlights": [],
        "conditionCardIds": [f"c{i}" for i in using],
    }
    if len(old) >= 2 and len(new) == 1 and all(t["op"] == "div" for t in old + new):
        den = _value(new[0]["children"][1], symbols)
        ds = [_value(t["children"][1], symbols) for t in old]
        multipliers = [sp.cancel(den / d) for d in ds]
        if (
            all(m.is_polynomial(*symbols.values()) for m in multipliers)
            and sp.cancel(
                sum(_value(t, symbols) for t in old) - _value(new[0], symbols)
            )
            == 0
        ):
            result["operation"] = "combine_fractions"
            result["evidence"] = {
                "kind": "structural_common_denominator",
                "mergedFractionCount": len(old),
                "commonDenominator": sp.latex(den),
                "multipliers": [sp.latex(m) for m in multipliers],
                "localEquivalenceVerified": True,
                "wholeEquivalenceVerified": True,
            }
            result["highlights"] = [
                {
                    "role": f"denominator_{i}",
                    "side": "before",
                    "nodeId": t["children"][1]["id"],
                    "latex": tree_latex(t["children"][1]),
                }
                for i, t in enumerate(old)
            ]
            for i, c in enumerate(conditions):
                if (
                    isinstance(c, sp.Equality)
                    and c.lhs.free_symbols
                    and not c.rhs.free_symbols
                ):
                    ratio = sp.cancel(den / c.lhs)
                    if not ratio.free_symbols and ratio.is_zero is False:
                        result["revealedConditionIds"] = result.get(
                            "revealedConditionIds", []
                        ) + [f"c{i}"]
                        result["highlights"].append(
                            {
                                "role": "condition_block",
                                "side": "after",
                                "nodeId": new[0]["children"][1]["id"],
                                "latex": sp.latex(c.lhs),
                                "factor": str(c.lhs),
                            }
                        )
    elif using:
        eqs = [conditions[i] for i in using]
        substituted = before.value
        for c in eqs:
            if isinstance(c, sp.Equality):
                substituted = substituted.subs(c.lhs, c.rhs)
        if (
            sp.cancel(substituted - after.value) == 0
            and sp.cancel(substituted - before.value) != 0
        ):
            result["operation"] = "substitute_condition"
            result["evidence"] = {
                "kind": "bound_equality_substitution",
                "wholeEquivalenceVerified": True,
            }
            result["replacements"] = [
                {
                    "conditionCardId": f"c{i}",
                    "block": {"latex": sp.latex(conditions[i].lhs)},
                    "value": {"latex": sp.latex(conditions[i].rhs)},
                }
                for i in using
                if isinstance(conditions[i], sp.Equality)
            ]
    if result["operation"] == "equivalent_rewrite":
        result["classificationGap"] = (
            "已验证等价，但没有唯一匹配的专门变形结构；使用普通等式链。"
        )
    return result


def verify_chain(
    expression: sp.Expr,
    raw_conditions: list[Any],
    steps: list[dict],
    symbols: Mapping[str, sp.Symbol],
) -> dict:
    conditions = [relation_from_bound(c, symbols) for c in raw_conditions]
    if len(conditions) > 16:
        raise RewriteError("proof_limit", "本轮最多绑定 16 个条件")
    for node in sp.preorder_traversal(expression):
        if (
            node.is_Pow
            and node.exp.is_negative
            and not _domain_nonzero(node.base, conditions)
        ):
            raise RewriteError("domain_unverified", "尚不能验证绑定输入的分母非零")
    parsed = []
    transitions = []
    for i, row in enumerate(steps):
        try:
            current = parse_expression(row["math"], symbols)
            if current.value.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
                raise RewriteError("undefined_expression", "表达式无定义")
            for den in current.denominators:
                if not _domain_nonzero(den, conditions):
                    raise RewriteError(
                        "domain_unverified", f"尚不能验证分母 {den} 非零"
                    )
            selected = []
            for text in row.get("using", []):
                relation = parse_relation(text, symbols)
                if not isinstance(relation, sp.Equality):
                    raise RewriteError(
                        "unsupported_using_condition",
                        "using 首轮只支持等式；定义域条件由代码检查",
                    )
                matches = [
                    j for j, c in enumerate(conditions) if same_relation(relation, c)
                ]
                if len(matches) != 1:
                    raise RewriteError(
                        "condition_unbound", "using 必须唯一匹配已绑定条件"
                    )
                selected.append(matches[0])
            if i == 0:
                if selected or sp.cancel(current.value - expression) != 0:
                    raise RewriteError(
                        "input_mismatch", "链首必须对应输入表达式，且不能使用新条件"
                    )
            else:
                if not verify_equivalence(
                    parsed[-1].value, current.value, [conditions[j] for j in selected]
                ):
                    raise RewriteError("equivalence_unverified", "前后式等价验证未通过")
                transition = classify(
                    parsed[-1], current, selected, conditions, symbols
                )
                transition["id"] = f"t{i - 1}"
                transitions.append(transition)
            parsed.append(current)
        except RewriteError as exc:
            error = RewriteError(exc.code, exc.message, i)
            for field in ("source", "span", "path", "source_path"):
                if hasattr(exc, field):
                    setattr(error, field, getattr(exc, field))
            raise error from exc
    reveal = False
    for i, t in enumerate(transitions):
        actual = set().union(
            *(
                set(s["conditionCardIds"])
                for s in transitions[i + 1 :]
                if s["operation"] == "substitute_condition"
            )
        )
        used = actual.intersection(t.get("revealedConditionIds", []))
        if used:
            reveal = True
            t["effect"] = "reveal_condition"
            t["conditionCardIds"] = sorted(used)
    return {
        "value": parsed[-1].value,
        "source": formula(parsed[0]),
        "result": formula(parsed[-1]),
        "transitions": transitions,
        "conditionCards": [
            {"id": f"c{i}", "latex": sp.latex(c), "boundIndex": i}
            for i, c in enumerate(conditions)
        ],
        "teachingEffect": "combine_fractions_revealing_condition"
        if reveal
        else "equivalent_rewrite",
    }
