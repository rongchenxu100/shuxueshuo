"""Shared original-syntax scalar conversion for domain admission and execution."""

import sympy as sp

from .stage_one.function_domain import ARGUMENT


def expression(ast, variable, symbols=None):
    """Retain powers so admission sees the same expansion cost as execution."""
    symbols = symbols or {}
    if ast == ARGUMENT:
        return variable
    kind = ast[0]
    if kind == "number":
        return sp.Rational(ast[1])
    if kind == "infinity":
        return sp.oo * ast[1] if len(ast) > 1 else sp.oo
    if kind == "ref":
        if ast[1] in symbols:
            return symbols[ast[1]]
        return sp.Symbol(ast[1].rsplit(":", 1)[-1], real=True)
    if kind == "neg":
        return -expression(ast[1], variable, symbols)
    if kind == "call" and ast[1] == "sqrt":
        return sp.Pow(expression(ast[2], variable, symbols), sp.Rational(1, 2), evaluate=False)
    left, right = (expression(a, variable, symbols) for a in ast[1:])
    return {
        "+": lambda: left + right,
        "-": lambda: left - right,
        "*": lambda: left * right,
        "/": lambda: left / right,
        "^": lambda: sp.Pow(left, right, evaluate=False),
    }[kind]()
