"""Shared SymPy parsing helpers for visual generation."""

from __future__ import annotations

from typing import Any
import re

import sympy as sp


AXIS_PARAMETER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+")
SYMPY_LOCALS = {"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs}


def sympify_visual_expr(
    value: Any,
    *,
    axis_parameter_alias: str | None = None,
) -> sp.Expr | None:
    """Parse a student/runtime visual expression with consistent normalization."""
    try:
        return sp.simplify(
            sp.sympify(
                visual_expr_text(value, axis_parameter_alias=axis_parameter_alias),
                locals=SYMPY_LOCALS,
            )
        )
    except Exception:
        return None


def sympy_pair(
    value: Any,
    *,
    axis_parameter_alias: str | None = None,
) -> tuple[sp.Expr, sp.Expr] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    x = sympify_visual_expr(value[0], axis_parameter_alias=axis_parameter_alias)
    y = sympify_visual_expr(value[1], axis_parameter_alias=axis_parameter_alias)
    if x is None or y is None:
        return None
    return x, y


def visual_expr_text(value: Any, *, axis_parameter_alias: str | None = None) -> str:
    text = str(value).replace("^", "**")
    text = re.sub(r"\babs\s*\(", "Abs(", text)
    text = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\*\1\b", r"\1**2", text)
    if axis_parameter_alias is not None:
        text = AXIS_PARAMETER_PATTERN.sub(axis_parameter_alias, text)
    return text
