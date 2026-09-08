"""Student-facing math display helpers.

These helpers turn runtime/SymPy-ish values into compact text suitable for
LessonIR boxes, explanation drafts, and visual labels. They do not parse or
invent math facts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import sympy as sp
from sympy.core.relational import Relational


_INTERNAL_MATH_CALL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(Eq|Ne|Lt|Le|Gt|Ge|sqrt|Abs|Piecewise|Rational|Integer|Float|"
    r"FiniteSet|Interval|Union|ImageSet|Lambda|Min|Max|Add|Mul|Pow|"
    r"Symbol|Tuple|And|Or|Not|Contains|ConditionSet)\s*\(",
    re.IGNORECASE,
)
_INTERNAL_BOOLEAN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(True|False|nan|zoo|oo)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_INTERNAL_OPERATOR_PATTERNS = (
    ("**", re.compile(r"\*\*")),
    ("*", re.compile(r"(?<!\*)\*(?!\*)")),
    ("==", re.compile(r"==")),
    (">=", re.compile(r">=")),
    ("<=", re.compile(r"<=")),
    ("!=", re.compile(r"!=")),
)


def student_math_display(
    value: Any,
    *,
    fullwidth_operators: bool = False,
    simplify_sympy: bool = True,
) -> str:
    """Render a math value in compact student-facing notation."""

    structured = _structured_sympy_value(value)
    if structured is not None:
        return _structured_math_display(
            structured,
            fullwidth_operators=fullwidth_operators,
        )
    if simplify_sympy and isinstance(value, sp.Basic):
        text = sp.sstr(sp.simplify(value))
    else:
        text = str(value)
    return _compact_math_text(text, fullwidth_operators=fullwidth_operators)


def find_internal_math_tokens(value: Any) -> list[str]:
    """Find computer-algebra spellings that must never reach student prose.

    Only string values are inspected. Mapping keys are deliberately ignored so
    machine contracts can retain names such as ``minimum_expression`` while
    every title, proof line, and conclusion remains student-facing.
    """

    hits: set[str] = set()
    for text in _iter_string_values(value):
        hits.update(
            _canonical_internal_math_token(item)
            for item in _INTERNAL_MATH_CALL_PATTERN.findall(text)
        )
        hits.update(
            _canonical_internal_math_token(item)
            for item in _INTERNAL_BOOLEAN_PATTERN.findall(text)
        )
        for token, pattern in _INTERNAL_OPERATOR_PATTERNS:
            if pattern.search(text):
                hits.add(token)
    return sorted(hits)


def _canonical_internal_math_token(value: str) -> str:
    canonical = {
        "eq": "Eq",
        "piecewise": "Piecewise",
        "sqrt": "sqrt",
        "true": "True",
        "false": "False",
    }
    return canonical.get(value.lower(), value)


def _iter_string_values(value: Any):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_string_values(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for item in value:
            yield from _iter_string_values(item)


def _structured_sympy_value(value: Any) -> sp.Basic | None:
    if isinstance(value, (sp.Equality, sp.Piecewise, Relational)) or value in (
        True,
        False,
        sp.true,
        sp.false,
    ):
        return sp.sympify(value)
    text = str(value).strip()
    if text == "True":
        return sp.true
    if text == "False":
        return sp.false
    if not (
        text.startswith("Eq(")
        or text.startswith("Piecewise(")
    ):
        return None
    try:
        parsed = sp.sympify(
            text,
            locals={
                "Abs": sp.Abs,
                "Eq": sp.Eq,
                "Piecewise": sp.Piecewise,
                "sqrt": sp.sqrt,
            },
        )
    except (TypeError, ValueError, SyntaxError, sp.SympifyError):
        return None
    return parsed if isinstance(parsed, sp.Basic) else None


def _structured_math_display(
    value: sp.Basic,
    *,
    fullwidth_operators: bool,
) -> str:
    if value == sp.true:
        return "恒成立"
    if value == sp.false:
        return "不成立"
    if isinstance(value, sp.Equality):
        return (
            _nested_sympy_display(
                value.lhs,
                fullwidth_operators=fullwidth_operators,
            )
            + "＝"
            + _nested_sympy_display(
                value.rhs,
                fullwidth_operators=fullwidth_operators,
            )
        )
    if isinstance(value, sp.Piecewise):
        branches: list[str] = []
        for expression, condition in value.args:
            expression_text = _plain_sympy_display(
                expression,
                fullwidth_operators=fullwidth_operators,
            )
            if condition == sp.true:
                branches.append(f"其余情况为 {expression_text}")
            else:
                condition_text = _structured_math_display(
                    condition,
                    fullwidth_operators=True,
                )
                branches.append(f"当 {condition_text} 时为 {expression_text}")
        return "；".join(branches)
    if isinstance(value, Relational):
        operator = {
            "<": "＜",
            "<=": "≤",
            ">": "＞",
            ">=": "≥",
            "!=": "≠",
        }.get(value.rel_op, value.rel_op)
        return (
            _plain_sympy_display(
                value.lhs,
                fullwidth_operators=fullwidth_operators,
            )
            + operator
            + _plain_sympy_display(
                value.rhs,
                fullwidth_operators=fullwidth_operators,
            )
        )
    return _plain_sympy_display(
        value,
        fullwidth_operators=fullwidth_operators,
    )


def _nested_sympy_display(
    value: sp.Basic,
    *,
    fullwidth_operators: bool,
) -> str:
    if isinstance(value, (sp.Equality, sp.Piecewise, Relational)) or value in (
        sp.true,
        sp.false,
    ):
        return _structured_math_display(
            value,
            fullwidth_operators=fullwidth_operators,
        )
    return _plain_sympy_display(
        value,
        fullwidth_operators=fullwidth_operators,
    )


def _plain_sympy_display(
    value: Any,
    *,
    fullwidth_operators: bool,
) -> str:
    return _compact_math_text(
        sp.sstr(sp.simplify(value)),
        fullwidth_operators=fullwidth_operators,
    )


def _compact_math_text(text: str, *, fullwidth_operators: bool) -> str:
    text = text.strip().replace(" ", "")
    text = re.sub(r"Abs\(([^()]+)\)", r"|\1|", text)
    text = text.replace("**3", "³").replace("**2", "²")
    text = text.replace("sqrt", "√")
    text = re.sub(r"√\(([A-Za-z0-9]+)\)", r"√\1", text)
    text = text.replace("*", "")
    if fullwidth_operators:
        text = (
            text.replace(">=", "≥")
            .replace("<=", "≤")
            .replace("!=", "≠")
            .replace("==", "＝")
            .replace("=", "＝")
            .replace(">", "＞")
            .replace("<", "＜")
            .replace("+", "＋")
            .replace("-", "－")
        )
    return text


__all__ = ["find_internal_math_tokens", "student_math_display"]
