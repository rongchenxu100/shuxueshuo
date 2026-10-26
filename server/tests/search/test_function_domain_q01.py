"""The uploaded y=... question retains its original restrictions in reading."""

import pytest

from shuxueshuo_server.graph_lesson.stage_two.fragments import (
    _domain_formula_body_matches,
)
from shuxueshuo_server.search.lesson import present_lesson, run_stage_two
from tests.search.function_domain_recording import RECORDING, revalidate_recording


def test_real_q01_recording_binds_y_formula_and_power_knowledge(tmp_path):
    result = revalidate_recording(RECORDING.parent / "q01-recorded-20261026", problem_id="function-concepts-q01")
    candidate = result["candidate"]
    assert candidate["root"]["definitions"] == ["f(x)=(x+4)^0*(x^2-1)/(x-1)"]
    assert "y=" in candidate["original_text"]

    def forbidden():
        raise AssertionError("unique supported recognition must not call a model")

    stage_two = run_stage_two(tmp_path, result, provider=forbidden, unsupported_root=tmp_path / "unsupported")
    goal = present_lesson(stage_two, result["features"], candidate["original_text"],
                          "function-concepts-q01", candidate=candidate)["goals"][0]
    assert goal["primary"] == "type-function-domain"
    assert goal["walk"]["bundle"]["intro"][0]["interaction"]["type"] == "choice"
    assert not goal["d1"].get("diagnostics")
    (given,) = goal["d1"]["givens"]
    assert "integer-power#zero-exponent" in given["knowledge_refs"]
    assert "rational-expression#meaning" in given["knowledge_refs"]
    assert "y=" in given["quote"][0]["text"]
    assert "^0" in given["quote"][0]["text"] and "x-1" in given["quote"][0]["text"]


@pytest.mark.parametrize("display,expected,matches", [
    (r"(x+4)^0\frac{x^2-1}{x-1}", "(x+4)^0*(x^2-1)/(x-1)", True),
    (r"(t-3)^{0}\dfrac{t^2-4}{t-2}", "(t-3)^0*(t^2-4)/(t-2)", True),
    (r"(x+4)^ {0}\frac{x^2-1}{x-1}", "(x+4)^0*(x^2-1)/(x-1)", True),
    (r"(x+4)^0(x+1)", "(x+4)^0*(x^2-1)/(x-1)", False),
    (r"\frac{x^2-1}{x-1}", "(x+4)^0*(x^2-1)/(x-1)", False),
    (r"(x+4)^2\frac{x^2-1}{x-1}", "(x+4)^0*(x^2-1)/(x-1)", False),
    ("a/(b/c)", "a*c/b", False),
    (r"x^{1}2", "x^12", False),
    (r"\unknown{(x+4)^0}\frac{x^2-1}{x-1}", "(x+4)^0*(x^2-1)/(x-1)", False),
])
def test_display_product_grouping_preserves_powers_and_each_original_divisor(display, expected, matches):
    assert _domain_formula_body_matches(display, expected) is matches
