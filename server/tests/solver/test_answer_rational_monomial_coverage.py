import pytest

from shuxueshuo_server.solver.explanation.scope_lesson import answer_display_is_covered


@pytest.mark.parametrize("expected,box", [
    ("x²/6-x/3-7", "y＝1/6x²－1/3x－7"),
    ("x²/6-x/3-7", "y＝(1/6)x²－(1/3)x－7"),
    ("2x²/5+3x/7-1", "y＝2/5x²＋3/7x－1"),
    ("1/6x²-1/3x-7", "y＝x²/6－x/3－7"),
])
def test_same_rational_monomial_is_not_rejected(expected, box):
    assert answer_display_is_covered(expected, box)


@pytest.mark.parametrize("box", ["y＝2/6x²－1/3x－7", "y＝1/6x²＋1/3x－7",
    "y＝1/7x²－1/3x－7", "y＝1/6x²－1/3x－8", "y＝1/(6x²)－1/(3x)－7"])
def test_wrong_coefficient_sign_constant_or_reciprocal_still_rejected(box):
    assert not answer_display_is_covered("x²/6-x/3-7", box)
