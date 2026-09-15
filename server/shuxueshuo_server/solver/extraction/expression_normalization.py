"""Conservative expression spelling normalization, never algebraic simplification.

Only arithmetic syntax is normalized: whitespace, redundant grouping and the
legacy mathematical caret spelling of powers. Operand order and the operator
tree are retained, including denominators and square roots. No expression is
evaluated. Unsupported syntax is returned unchanged (apart from whitespace),
so normalization cannot make invalid input pass the domain validator.
"""
from __future__ import annotations

import ast
import re

EXPRESSION_NORMALIZATION_VERSION = "expression-spelling/v1"


def normalize_expression_spelling(value: str) -> str:
    original = str(value).strip()
    fallback = re.sub(r"\s+", "", original)
    if len(original) > 2048:
        return fallback
    # Domain equations also use a single '=' rather than Python comparisons.
    parts = re.split(r"(?<![<>=!])=(?!=)", original)
    if len(parts) == 2:
        return "=".join(normalize_expression_spelling(part) for part in parts)
    if len(parts) != 1:
        return fallback
    try:
        tree = ast.parse(original.replace("^", "**"), mode="eval")
        nodes = list(ast.walk(tree))
        if len(nodes) > 256:
            return fallback
        allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load,
                   ast.Constant, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div,
                   ast.Pow, ast.UAdd, ast.USub)
        for node in nodes:
            if not isinstance(node, allowed):
                return fallback
            # Never round a decimal through Python float parsing.
            if isinstance(node, ast.Constant) and type(node.value) is not int:
                return fallback
            if isinstance(node, ast.Call) and (
                not isinstance(node.func, ast.Name) or node.keywords
            ):
                return fallback
        return re.sub(r"\s+", "", ast.unparse(tree))
    except (SyntaxError, ValueError, RecursionError):
        return fallback
