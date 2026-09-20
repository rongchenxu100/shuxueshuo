"""Bounded scalar AST. Never evaluates model strings or calls sympify on them."""

import ast
import re

import sympy as sp


def scalar_expression(text, names=(), obligations=None):
    obligations = obligations if obligations is not None else []
    if len(text) > 1024:
        raise ValueError("algebra.length_limit")
    text = text.replace("−", "-").replace("×", "*").replace("÷", "/").replace("^", "**")
    try:
        root = ast.parse(text.strip(), mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("algebra.syntax") from exc
    if sum(1 for _ in ast.walk(root)) > 256:
        raise ValueError("algebra.node_limit")
    used = set()

    def visit(node, depth=0):
        if depth > 32:
            raise ValueError("algebra.depth_limit")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            token = ast.get_source_segment(text.strip(), node)
            if not re.fullmatch(r"\d+(\.\d+)?", token or "") or len(token) > 64:
                raise ValueError("algebra.number")
            return sp.Rational(token)
        if isinstance(node, ast.Name) and node.id in names:
            used.add(node.id)
            return sp.Symbol(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = visit(node.operand, depth + 1)
            return -value if isinstance(node.op, ast.USub) else value
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sqrt"
            and len(node.args) == 1
            and not node.keywords
        ):
            value = visit(node.args[0], depth + 1)
            if value.is_negative is True:
                raise ValueError("algebra.nonreal")
            if value.is_nonnegative is not True:
                obligations.append(
                    {"code": "nonnegative_radicand", "expression": str(value)}
                )
            return sp.sqrt(value)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("algebra.zero_denominator")
                if right.is_zero is not False:
                    obligations.append(
                        {
                            "code": "nonzero_algebra_denominator",
                            "expression": str(right),
                        }
                    )
                return left / right
            if isinstance(node.op, ast.Pow) and right.is_Integer and abs(right) <= 12:
                if left == 0 and right < 0:
                    raise ValueError("algebra.zero_denominator")
                if right < 0 and left.is_zero is not False:
                    obligations.append(
                        {"code": "nonzero_algebra_denominator", "expression": str(left)}
                    )
                if (
                    left.is_Rational
                    and max(int(left.p).bit_length(), int(left.q).bit_length())
                    * max(1, abs(int(right)))
                    > 4096
                ):
                    raise ValueError("algebra.numeric_limit")
                return left**right
        raise ValueError("algebra.forbidden_node_or_symbol")

    result = visit(root.body)
    if used != set(names):
        raise ValueError("algebra.refs_mismatch")
    return result
