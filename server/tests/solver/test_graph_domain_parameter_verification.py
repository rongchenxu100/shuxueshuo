"""Complete original-source proofs for M6, independent of its method output."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import capabilities, driver
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_domain import (
    _radicand_always_nonnegative,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    endpoint_check,
    verify,
)
from tests.solver.test_graph_domain_parameter import TARGET, candidate, execute


@pytest.mark.parametrize(
    "formula,expected",
    [
        ("sqrt(k*x^2+2*x+1)", sp.Interval(1, sp.oo)),
        ("sqrt(k*x^2+4*x+1)", sp.Interval(4, sp.oo)),
        ("sqrt(x^2+k)", sp.Interval(0, sp.oo)),
        ("sqrt(k*x^2+k*x)", sp.FiniteSet(0)),
        ("sqrt(k*x^2-1)", sp.S.EmptySet),
        ("sqrt(k*x^2+1)", sp.Interval(0, sp.oo)),
        ("sqrt(k*x^2+(k-1)*x)", sp.FiniteSet(1)),
        ("sqrt(x^2+k*x+2)", sp.Interval(-2 * sp.sqrt(2), 2 * sp.sqrt(2))),
        ("sqrt((k-1)*x^2+2*x+k)", sp.Interval((1 + sp.sqrt(5)) / 2, sp.oo)),
        ("sqrt(-x^2+k)", sp.S.EmptySet),
        ("sqrt(k*x^2)", sp.Interval(0, sp.oo)),
        ("sqrt((k-1)*x^2+2*(k-1)*x+k-1)", sp.Interval(1, sp.oo)),
    ],
)
def test_complete_parameter_proof_and_real_method_agree(formula, expected):
    value = candidate(formula)
    context, state = execute(value)
    assert state["status"] == "method_complete", state.get("diagnostics")
    assert driver.export_values(state)["feasible_set"] == expected
    result = verify(value, TARGET, context, expected)
    assert result["status"] == "verified", result
    proof = result["proof"]
    assert proof["invariance"]["proved"]
    assert proof["reconstructed_set"] == math_value(expected)
    assert proof["expression_ast"] == context["domain_goal"]["expression_ast"]
    assert {row["kind"] for row in proof["critical_polynomials"]} == {
        "coefficient_A", "coefficient_B", "coefficient_C", "discriminant",
    }
    assert all(row["source_ref"] == "/root/definitions/0" and row["ast_path"] == [2]
               for row in proof["critical_polynomials"])
    assert len(proof["cells"]) == 2 * len(proof["critical_points"]) + 1
    assert endpoint_check(value, TARGET, expected)["status"] == "passed"


@pytest.mark.parametrize(
    "wrong",
    [
        sp.Interval(1, 2),
        sp.Interval(2, 3),
        sp.Interval.open(1, sp.oo),
        sp.S.Reals,
        sp.S.EmptySet,
        sp.FiniteSet(1),
        sp.Union(sp.Interval(1, 2), sp.Interval(3, sp.oo)),
        sp.Union(sp.FiniteSet(-2), sp.Interval(1, sp.oo)),
        sp.Interval(sp.sqrt(2), sp.oo),
    ],
)
def test_wrong_sets_are_rejected_on_the_complete_source_partition(wrong):
    value = candidate()
    context = build_context(value, TARGET)
    right = verify(value, TARGET, context, sp.Interval(1, sp.oo))
    result = verify(value, TARGET, context, wrong)
    assert result["status"] == "math_failed", result
    assert result["counterexample"]["original_holds"] != result["counterexample"]["candidate_includes"]
    # The proof partition must come from the original predicate, never the answer.
    for key in ("critical_polynomials", "critical_points", "cells", "reconstructed_set"):
        assert result["proof"][key] == right["proof"][key]


def test_verifier_accepts_equivalent_union_and_algebraic_root_spellings():
    value = candidate()
    union = sp.Union(sp.Interval(1, 2), sp.Interval(2, sp.oo), evaluate=False)
    assert verify(value, TARGET, build_context(value, TARGET), union)["status"] == "verified"

    k = sp.Symbol("k")
    root_interval = sp.Interval(sp.CRootOf(k**2 - 8, 0), sp.CRootOf(k**2 - 8, 1))
    value = candidate("sqrt(x^2+k*x+2)")
    result = verify(value, TARGET, build_context(value, TARGET), root_interval)
    assert result["status"] == "verified", result
    assert endpoint_check(value, TARGET, root_interval)["status"] == "passed"


@pytest.mark.parametrize("field", ["domain_goal", "entries", "goal_ast", "missing_context"])
def test_source_context_mismatch_is_a_failed_proof(field):
    value = candidate()
    context = build_context(value, TARGET)
    if field == "domain_goal":
        context[field]["expression_ast"] = ["number", "1"]
    elif field == "entries":
        context[field][0]["ast"][2] = ["number", "1"]
    elif field == "goal_ast":
        context[field]["domain"] = ["interval", True, True, ["number", "0"], ["number", "1"]]
    else:
        context = {}
    result = verify(value, TARGET, context, sp.Interval(1, sp.oo))
    assert result["status"] == "math_failed", result
    assert result["diagnostics"][0]["code"] == "constraint_context_mismatch"


def test_verification_uses_no_execution_capability_or_inequality_solver(monkeypatch):
    value = candidate("sqrt(x^2+k*x+2)")
    context = build_context(value, TARGET)
    frozen = deepcopy((value, context))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the independent proof must not call the solver")

    monkeypatch.setattr(capabilities, "execute", forbidden)
    monkeypatch.setattr(sp, "solve_univariate_inequality", forbidden)
    result = verify(value, TARGET, context, sp.Interval(-2 * sp.sqrt(2), 2 * sp.sqrt(2)))
    assert result["status"] == "verified", result
    assert (value, context) == frozen


def test_positive_discriminant_is_a_proved_failure_not_a_gap():
    x = sp.Symbol("x", real=True)
    assert _radicand_always_nonnegative(3*x**2 + 4*x + 1, x) is False
    assert _radicand_always_nonnegative(x**2 - 1, x) is False


def test_parameter_endpoints_keep_excluded_and_degenerate_truth_values():
    value = candidate()
    result = endpoint_check(value, TARGET, sp.Interval(1, sp.oo))
    points = {row["point"]["expression"]: row for row in result["points"]}
    assert points["0"]["included"] is False and points["0"]["holds"] is False
    assert points["0"]["passed"] is True
    assert points["0"]["evidence"]["certificate"]["degree"] == 1
    assert points["1"]["included"] is True and points["1"]["holds"] is True
    assert points["1"]["evidence"]["certificate"]["discriminant_sign"] == 0
    wrong = endpoint_check(value, TARGET, sp.Interval(0, sp.oo))
    assert wrong["status"] == "failed"
    assert any(row["included"] and not row["holds"] and not row["passed"] for row in wrong["points"])

    constant = endpoint_check(candidate("sqrt(k*x^2+1)"), TARGET, sp.Interval(0, sp.oo))
    zero = next(row for row in constant["points"] if row["point"]["expression"] == "0")
    assert zero["included"] and zero["holds"] and zero["passed"]
    assert zero["evidence"]["certificate"]["degree"] == 0
    assert zero["evidence"]["certificate"]["coefficient_signs"] == {"A": 0, "B": 0, "C": 1}
