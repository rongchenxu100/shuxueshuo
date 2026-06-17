from __future__ import annotations

import sympy as sp

from shuxueshuo_server.solver.student_display import student_math_display


def test_student_math_display_compacts_polynomial_text() -> None:
    assert student_math_display("x**2 - 2*x - 3") == "x²-2x-3"


def test_student_math_display_formats_sympy_abs_and_sqrt() -> None:
    a = sp.Symbol("a", positive=True)
    x = sp.Symbol("x")

    assert student_math_display(sp.Abs(x)) == "|x|"
    assert student_math_display(sp.sqrt(2 * a**2 + 1) / a) == "√(2a²+1)/a"


def test_student_math_display_can_use_fullwidth_operators() -> None:
    assert student_math_display("x**2 - 2*x + 3", fullwidth_operators=True) == "x²－2x＋3"
