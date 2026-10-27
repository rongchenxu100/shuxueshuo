"""M6 branch completeness follows its admitted contract, independent of题号."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check
from shuxueshuo_server.learning.graph_walk import grade
from tests.solver.test_graph_domain_parameter import candidate, execute


@pytest.mark.parametrize("expression,expected", [
    ("x^2+k", sp.Interval(0, sp.oo)),
    ("-x^2+k", sp.S.EmptySet),
    ("k*x^2+2*x+1", sp.Interval(1, sp.oo)),
    ("k*x^2-2*x+1", sp.Interval(1, sp.oo)),
    ("k*x^2+1", sp.Interval(0, sp.oo)),
    ("k*x^2", sp.Interval(0, sp.oo)),
    ("k*x^2-1", sp.S.EmptySet),
    ("k*x^2+k*x", sp.FiniteSet(0)),
    ("k*x^2+x", sp.S.EmptySet),
    ("(k-1)*x^2+2*(k-1)*x+k-1", sp.Interval(1, sp.oo)),
    ("x^2+k*x+2", sp.Interval(-2 * sp.sqrt(2), 2 * sp.sqrt(2))),
    ("x^2+k*x-2", sp.S.EmptySet),
    ("k*x^2+(k-1)*x", sp.FiniteSet(1)),
], ids=[
    "fixed-positive-leading", "fixed-negative-leading",
    "degenerates-positive-linear", "degenerates-negative-linear",
    "degenerates-positive-constant", "degenerates-zero-constant", "degenerates-negative-constant",
    "only-degenerate-parameter", "constant-positive-discriminant", "shifted-zero-discriminant",
    "two-algebraic-endpoints", "always-positive-discriminant", "repeated-root-parameter",
])
def test_m6_mathematical_branches_have_verified_results_and_complete_judgments(expression, expected):
    value = candidate(f"sqrt({expression})")
    _, state = execute(value)
    assert state["status"] == "method_complete", state.get("diagnostics")
    assert driver.export_values(state)["feasible_set"] == expected
    assert state["verification"]["status"] == "verified"
    assert endpoint_check(value, "/root/goals/0", expected)["status"] == "passed"
    chunks, pending = interaction.compile_route(state["interaction_seeds"], interaction.load_registry())
    assert not pending
    units = {seed["step_id"]: seed["display_unit"] for seed in state["interaction_seeds"]}
    opening_seen = False
    for chunk, diagnostics in chunks:
        unit = units[chunk["steps"][0]["step_id"]]
        interaction.validate_chunk(chunk)
        if unit == "opening_excluded":
            # Opening-position judgments already establish impossibility.
            # The empty-set summary is deliberately read, not a missing rule.
            assert opening_seen
            assert chunk["status"] == "readonly" and chunk["reason"] == "repeat"
            continue
        assert chunk["status"] == "interactive", (unit, diagnostics)
        opening_seen |= unit == "opening"
        for part in chunk["parts"]:
            expected_answer = part["expected_answer"]
            answer = ([*expected_answer["cell"], expected_answer["method"]] if "cell" in expected_answer
                      else expected_answer["required"] if "required" in expected_answer
                      else expected_answer["terms"] if "terms" in expected_answer else expected_answer["one_of"][0])
            assert grade(part, {"value": answer}, "domain-parameter") == "passed"
            if part["interaction"]["type"] == "choice":
                wrong = [option["value"] for option in part["interaction"]["options"]
                         if option["value"] not in expected_answer["one_of"]]
                assert wrong, (unit, part)
                assert all(grade(part, {"value": option}, "domain-parameter") == "wrong" for option in wrong)
