from __future__ import annotations

import sympy as sp

from shuxueshuo_server.solver.student_display import (
    find_internal_math_tokens,
    student_math_display,
)


def test_student_math_display_compacts_polynomial_text() -> None:
    assert student_math_display("x**2 - 2*x - 3") == "x²-2x-3"


def test_student_math_display_formats_sympy_abs_and_sqrt() -> None:
    a = sp.Symbol("a", positive=True)
    x = sp.Symbol("x")

    assert student_math_display(sp.Abs(x)) == "|x|"
    assert student_math_display(sp.sqrt(2 * a**2 + 1) / a) == "√(2a²+1)/a"


def test_student_math_display_can_use_fullwidth_operators() -> None:
    assert student_math_display("x**2 - 2*x + 3", fullwidth_operators=True) == "x²－2x＋3"
    assert student_math_display("b>1/2", fullwidth_operators=True) == "b＞1/2"
    assert student_math_display("x>=0", fullwidth_operators=True) == "x≥0"


def test_student_math_display_localizes_min_max_calls() -> None:
    value = student_math_display("min(2*DM+AM)", fullwidth_operators=True)
    assert value == "最小值(2DM＋AM)"
    assert find_internal_math_tokens(value) == []


def test_student_math_display_renders_structured_sympy_as_student_math() -> None:
    assert student_math_display("Eq(x**2, 4)") == "x²＝4"
    assert student_math_display("True") == "恒成立"
    assert student_math_display("False") == "不成立"


def test_student_math_display_renders_piecewise_without_internal_tokens() -> None:
    assert student_math_display("Piecewise((x, x >= 0), (-x, True))") == (
        "当 x≥0 时为 x；其余情况为 -x"
    )
    nested = student_math_display(
        "Eq(Piecewise((x, x >= 0), (-x, True)), 4)"
    )
    assert nested == "当 x≥0 时为 x；其余情况为 -x＝4"
    assert find_internal_math_tokens(nested) == []


def test_student_math_display_hides_undefined_piecewise_default() -> None:
    assert student_math_display(
        "Piecewise((3*b/2 + 9/4, b > 1/2), (nan, True))"
    ) == "当 b＞1/2 时为 3b/2+9/4"


def test_internal_math_token_scan_checks_student_values_not_contract_keys() -> None:
    assert find_internal_math_tokens(
        {"minimum_expression": "当 b＞1/2 时为 √2；其余情况为 1"}
    ) == []
    assert find_internal_math_tokens(
        {
            "derive": [
                "计算 Eq(b**2 + 2*b, 1)",
                "∴ Piecewise((sqrt(2), b > 0), (1, True))",
            ]
        }
    ) == ["*", "**", "Eq", "Piecewise", "True", "sqrt"]
