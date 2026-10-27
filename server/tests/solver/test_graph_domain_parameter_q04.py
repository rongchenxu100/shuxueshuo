"""Q4 reuses M6, including the successful constant degeneration at m = 0."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import capabilities, driver, selection
from shuxueshuo_server.graph_lesson.stage_three.domain_borrow import (
    select_borrowed_method,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    endpoint_check,
    verify,
)
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.learning.graph_walk import grade
from tests.solver.test_graph_domain_parameter_interactions import (
    TARGET,
    candidate,
    execute,
)

ANSWER = sp.Interval(0, sp.Rational(3, 4))


@pytest.fixture(scope="module")
def q04():
    value = candidate("sqrt(m*x^2+4*m*x+3)", parameter="m")
    context, state, chunks = execute(value)
    return value, context, state, chunks


def test_q04_selects_existing_domain_parameter_and_discriminant_methods(q04):
    value, _, state, chunks = q04
    features = extract_features(value)["features"]
    assert [row["type_id"] for row in evaluate_types(features)
            if row["status"] == "supported"] == ["type-function-domain"]
    selected = selection.evaluate_goal(value, TARGET, features, "type-function-domain")
    assert selected["selection"]["branches"][0]["target"] == "method-domain-parameter"
    borrowed, branch, route = select_borrowed_method(decode_value(state["interaction_seeds"][2]["values"]))
    assert borrowed["selection"]["rule"] == "rule-quadratic-method"
    assert branch["target"] == "method-discriminant"
    assert route == "domain-parameter"
    assert chunks[2][0]["parts"][0]["interaction"]["type"] == "plane"
    assert driver.export_values(state)["feasible_set"] == ANSWER
    methods = {row["method"] for row in state["trajectory"]["steps"]}
    assert methods == {"method-domain-parameter", "method-discriminant", "quadratic-inequality-solve"}


def test_q04_keeps_constant_zero_case_and_intersects_nondegenerate_range(q04):
    _, _, state, chunks = q04
    values = [decode_value(seed["values"]) for seed in state["interaction_seeds"]]
    constant = next(row for row in values if row.get("is_constant") is True)
    assert constant["value"] == 0 and constant["constant"] == 3
    assert constant["linear_coefficient"] == 0 and constant["holds"] is True
    assert constant["after"][-1] == sp.FiniteSet(0)
    branch = next(row["branch"] for row in values if "opening_certificate" in row)
    assert branch["delta_solution"] == ANSWER
    assert branch["solution"] == sp.Interval.Lopen(0, sp.Rational(3, 4))
    merge = next(row for row in values if "merge_rows" in row)
    assert [row["solution"] for row in merge["merge_rows"]] == [sp.FiniteSet(0), branch["solution"]]
    assert merge["after"] == [ANSWER]

    parts = [part for chunk, _ in chunks for part in chunk["parts"]]
    degenerate = next(part for part in parts if part["interaction"]["type"] == "checklist")
    assert "$3 \\geq 0$" in degenerate["question"]
    assert grade(degenerate, {"value": ["s1o1"]}, "domain-parameter") == "passed"
    assert grade(degenerate, {"value": ["s1o2"]}, "domain-parameter") == "wrong"
    assert len(parts) == 11
    for part in parts:
        expected = part["expected_answer"]
        answer = ([*expected["cell"], expected["method"]] if "cell" in expected
                  else expected["required"] if "required" in expected
                  else expected["terms"] if "terms" in expected else expected["one_of"][0])
        assert grade(part, {"value": answer}, "domain-parameter") == "passed"


def test_q04_source_verification_does_not_depend_on_execution_or_inequality_solver(q04, monkeypatch):
    value, context, _, _ = q04

    def forbidden(*_args, **_kwargs):
        raise AssertionError("independent verification must use the original predicate")

    monkeypatch.setattr(capabilities, "execute", forbidden)
    monkeypatch.setattr(sp, "solve_univariate_inequality", forbidden)
    proof = verify(value, TARGET, context, ANSWER)
    assert proof["status"] == "verified", proof
    assert proof["proof"]["invariance"]["proved"] is True
    assert proof["proof"]["reconstructed_set"] == math_value(ANSWER)
    assert proof["proof"]["expression_ast"] == context["domain_goal"]["expression_ast"]


@pytest.mark.parametrize("wrong", [
    sp.Interval.Lopen(0, sp.Rational(3, 4)),  # dropping the successful constant case
    sp.Interval.Ropen(0, sp.Rational(3, 4)),  # dropping the repeated-root endpoint
    sp.Interval(0, 1),  # accepting a parameter with negative radicand values
])
def test_q04_independent_proof_and_endpoint_check_reject_wrong_boundaries(q04, wrong):
    value, context, _, _ = q04
    result = verify(value, TARGET, context, wrong)
    assert result["status"] == "math_failed"
    assert result["counterexample"]["original_holds"] != result["counterexample"]["candidate_includes"]
    assert endpoint_check(value, TARGET, wrong)["status"] == "failed"


def test_q04_included_endpoints_have_constant_and_repeated_root_certificates(q04):
    value, _, _, _ = q04
    checked = endpoint_check(value, TARGET, ANSWER)
    assert checked["status"] == "passed"
    points = {row["point"]["expression"]: row for row in checked["points"]}
    assert set(points) == {"0", "3/4"}
    assert all(row["included"] and row["holds"] and row["passed"] for row in points.values())
    assert points["0"]["evidence"]["certificate"]["degree"] == 0
    assert points["0"]["evidence"]["polynomial"]["expression"] == "3"
    assert points["3/4"]["evidence"]["certificate"]["degree"] == 2
    assert points["3/4"]["evidence"]["certificate"]["discriminant_sign"] == 0


def test_q04_family_uses_current_symbols_and_coefficients():
    value = candidate("sqrt(a*t^2-6*a*t+2)", variable="t", parameter="a", function="g")
    context, state, chunks = execute(value)
    expected = sp.Interval(0, sp.Rational(2, 9))
    assert driver.export_values(state)["feasible_set"] == expected
    assert verify(value, TARGET, context, expected)["status"] == "verified"
    assert endpoint_check(value, TARGET, expected)["status"] == "passed"
    parts = [part for chunk, _ in chunks for part in chunk["parts"]]
    constant = next(part for part in parts if part["interaction"]["type"] == "checklist")
    assert "$a=0$" in constant["question"] and "$2 \\geq 0$" in constant["question"]
    assert "D_{g}" in next(option["label"] for option in parts[-1]["interaction"]["options"]
                           if option["value"] in parts[-1]["expected_answer"]["one_of"])
