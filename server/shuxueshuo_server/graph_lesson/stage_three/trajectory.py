"""Exact, non-evaluating checkpoint codec and serializable trace values."""

import sympy as sp

from .math_values import math_value

_CONSTRUCTORS = {
    name: getattr(sp, name)
    for name in (
        "Add",
        "Mul",
        "Pow",
        "Abs",
        "Interval",
        "Union",
        "Intersection",
        "FiniteSet",
        "Equality",
        "Unequality",
        "GreaterThan",
        "LessThan",
        "StrictGreaterThan",
        "StrictLessThan",
        "And",
        "Or",
        "Complement",
    )
}
_CONSTANTS = {
    "Reals": sp.S.Reals,
    "EmptySet": sp.S.EmptySet,
    "Infinity": sp.oo,
    "NegativeInfinity": -sp.oo,
    "BooleanTrue": sp.true,
    "BooleanFalse": sp.false,
}


def encode_value(value):
    if isinstance(value, sp.CRootOf):
        # A rational polynomial and a root index are inert data. Never persist
        # RootOf's printed expression for later sympify/eval reconstruction.
        return {"$math": "CRootOf", "coefficients": [encode_value(c) for c in value.poly.all_coeffs()],
                "index": int(value.index)}
    if isinstance(value, sp.Symbol):
        return {"$math": "Symbol", "name": value.name}
    if isinstance(value, sp.Integer):
        return {"$math": "Integer", "value": str(value)}
    if isinstance(value, sp.Rational):
        return {"$math": "Rational", "p": str(value.p), "q": str(value.q)}
    if isinstance(value, sp.Basic):
        name = type(value).__name__
        if name in _CONSTANTS:
            return {"$math": name}
        if name not in _CONSTRUCTORS:
            raise ValueError(f"checkpoint.unsupported_math:{name}")
        return {"$math": name, "args": [encode_value(v) for v in value.args]}
    if isinstance(value, dict):
        return {key: encode_value(v) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_value(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(type(value).__name__)


def decode_value(value):
    if isinstance(value, list):
        return [decode_value(v) for v in value]
    if not isinstance(value, dict):
        return value
    if "$math" not in value:
        return {key: decode_value(v) for key, v in value.items()}
    name = value["$math"]
    if name in _CONSTANTS:
        return _CONSTANTS[name]
    if name == "Symbol":
        return sp.Symbol(value["name"], real=True)
    if name == "Integer":
        return sp.Integer(value["value"])
    if name == "Rational":
        return sp.Rational(int(value["p"]), int(value["q"]))
    if name == "CRootOf":
        coefficients = value.get("coefficients")
        index = value.get("index")
        if (not isinstance(coefficients, list) or not 2 <= len(coefficients) <= 49
                or type(index) is not int or not 0 <= index < len(coefficients) - 1):
            raise ValueError("checkpoint.invalid_algebraic_root")
        coefficients = [decode_value(c) for c in coefficients]
        if (any(not isinstance(c, sp.Rational) for c in coefficients) or coefficients[0] == 0):
            raise ValueError("checkpoint.invalid_algebraic_polynomial")
        polynomial = sp.Poly.from_list(coefficients, sp.Symbol("_root"), domain=sp.QQ)
        return sp.CRootOf(polynomial, index, radicals=False)
    if name not in _CONSTRUCTORS:
        raise ValueError("checkpoint.unknown_math_type")
    arguments = [decode_value(v) for v in value["args"]]
    if name in {
        # Preserve an original radical even when its constant radicand is
        # negative. Its real definedness is checked before arithmetic.
        "Pow",
        "Equality",
        "Unequality",
        "GreaterThan",
        "LessThan",
        "StrictGreaterThan",
        "StrictLessThan",
    }:
        return _CONSTRUCTORS[name](*arguments, evaluate=False)
    return _CONSTRUCTORS[name](*arguments)


def trace_value(value):
    if isinstance(value, sp.Basic):
        return {**math_value(value), "exact": encode_value(value)}
    if isinstance(value, dict):
        return {k: trace_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [trace_value(v) for v in value]
    return value
