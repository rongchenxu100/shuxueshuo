"""Student-facing math display helpers.

These helpers turn runtime/SymPy-ish values into compact text suitable for
LessonIR boxes, explanation drafts, and visual labels. They do not parse or
invent math facts.
"""

from __future__ import annotations

import re
from typing import Any

import sympy as sp


def student_math_display(
    value: Any,
    *,
    fullwidth_operators: bool = False,
    simplify_sympy: bool = True,
) -> str:
    """Render a math value in compact student-facing notation."""

    if simplify_sympy and isinstance(value, sp.Basic):
        text = sp.sstr(sp.simplify(value))
    else:
        text = str(value)
    text = text.strip().replace(" ", "")
    text = re.sub(r"Abs\(([^()]+)\)", r"|\1|", text)
    text = text.replace("**3", "³").replace("**2", "²")
    text = text.replace("sqrt", "√")
    text = text.replace("*", "")
    if fullwidth_operators:
        text = text.replace("+", "＋").replace("-", "－")
    return text
