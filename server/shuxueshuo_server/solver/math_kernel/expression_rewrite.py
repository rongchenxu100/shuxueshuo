"""Bounded rational rewrite verification with a separate ordered display tree.

No candidate text is evaluated as Python. Tree ids are local display ids, not
MathObject identities. All algebra uses the caller's existing Symbol objects.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import sympy as sp
from sympy.core.relational import Relational


class RewriteError(ValueError):
    def __init__(self, code: str, message: str, row: int | None = None):
        self.code, self.row = code, row
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


def parse_expression(source: str, symbols: Mapping[str, sp.Symbol]) -> ParsedExpression:
    if not isinstance(source, str) or not source.strip() or len(source) > 1024:
        raise RewriteError("invalid_expression", "表达式应为 1–1024 个字符")
    try:
        root = ast.parse(source.strip().replace("^", "**"), mode="eval").body
    except (SyntaxError, RecursionError) as exc:
        raise RewriteError("invalid_syntax", "只接受显式乘号的数学表达式") from exc
    if sum(1 for _ in ast.walk(root)) > 256:
        raise RewriteError("expression_too_large", "表达式结构过大")

    def expansion_budget(node):
        if isinstance(node, ast.UnaryOp):
            return expansion_budget(node.operand)
        if not isinstance(node, ast.BinOp):
            return 1
        left, right = expansion_budget(node.left), expansion_budget(node.right)
        if isinstance(node.op, ast.Pow):
            exponent = (
                node.right.operand
                if isinstance(node.right, ast.UnaryOp)
                else node.right
            )
            if (
                not isinstance(exponent, ast.Constant)
                or type(exponent.value) is not int
                or abs(exponent.value) > 12
            ):
                raise RewriteError(
                    "unsupported_power", "指数应为绝对值不超过 12 的整数字面量"
                )
            if any(isinstance(n, ast.Pow) for n in ast.walk(node.left)):
                raise RewriteError("expression_too_large", "首轮不接受嵌套幂")
            size = left ** abs(exponent.value)
        elif isinstance(node.op, (ast.Add, ast.Sub)):
            size = left + right
        else:
            size = left * right
        if size > 128:
            raise RewriteError("proof_limit", "潜在展开规模超过首轮限制")
        return size

    expansion_budget(root)
    denominators: list[sp.Expr] = []

    def visit(node: ast.AST, path: str = "n", depth: int = 0):
        if depth > 32:
            raise RewriteError("expression_too_deep", "括号层数过多")
        if isinstance(node, ast.Name):
            if node.id not in symbols:
                raise RewriteError("unknown_symbol", f"未知变量 {node.id}")
            return {"id": path, "op": "symbol", "text": node.id}, symbols[node.id]
        if (
            isinstance(node, ast.Constant)
            and type(node.value) is int
            and abs(node.value) <= 10**9
        ):
            return {"id": path, "op": "integer", "text": str(node.value)}, sp.Integer(
                node.value
            )
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            child, value = visit(node.operand, path + ".0", depth + 1)
            op = "neg" if isinstance(node.op, ast.USub) else "pos"
            return {
                "id": path,
                "op": op,
                "children": [child],
            }, -value if op == "neg" else value
        if not isinstance(node, ast.BinOp) or not isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
        ):
            raise RewriteError(
                "unsupported_syntax", "仅支持整数、变量、加减乘除、整数幂和括号"
            )
        left, x = visit(node.left, path + ".0", depth + 1)
        right, y = visit(node.right, path + ".1", depth + 1)
        op = {
            ast.Add: "add",
            ast.Sub: "sub",
            ast.Mult: "mul",
            ast.Div: "div",
            ast.Pow: "pow",
        }[type(node.op)]
        if op == "pow" and (not y.is_Integer or abs(y) > 12):
            raise RewriteError(
                "unsupported_power", "首轮只支持绝对值不超过 12 的整数幂"
            )
        if op == "pow" and (sp.count_ops(x) > 24 or x.has(sp.Pow)):
            raise RewriteError("expression_too_large", "首轮不接受嵌套幂或大型幂展开")
        if op == "div":
            denominators.append(y)
        if op == "pow" and y < 0:
            denominators.append(x)
        value = {
            "add": lambda: x + y,
            "sub": lambda: x - y,
            "mul": lambda: x * y,
            "div": lambda: x / y,
            "pow": lambda: x**y,
        }[op]()
        return {"id": path, "op": op, "children": [left, right]}, value

    tree, value = visit(root)
    return ParsedExpression(source, tree, value, tuple(denominators))


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
    import re

    parts = re.split(r"(>=|<=|!=|=|>|<)", text)
    if len(parts) != 3:
        raise RewriteError("invalid_condition", "条件必须是单个等式或大小关系")
    x, y = (
        parse_expression(parts[0], symbols).value,
        parse_expression(parts[2], symbols).value,
    )
    return {"=": sp.Eq, "!=": sp.Ne, ">": sp.Gt, "<": sp.Lt, ">=": sp.Ge, "<=": sp.Le}[
        parts[1]
    ](x, y, evaluate=False)


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
            exc.row = i
            raise RewriteError(exc.code, str(exc), i) from exc
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
