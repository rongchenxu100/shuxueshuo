"""Exact radical-product square/sign identities and hostile certificate tests."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import function_equality as equality
from tests.solver.test_graph_function_equality_math import descriptor


def checked(left, right, domain=None, relation="equal"):
    lhs, rhs = descriptor(left, domain=domain), descriptor(right, domain=domain, function_ref="option:A:g")
    result = equality.compare_pair(lhs, rhs)
    assert result["relation"] == relation, result
    assert equality.verify_pair(lhs, rhs, result)["status"] == "verified"
    return lhs, rhs, result


@pytest.mark.parametrize("left,right,domain", [
    ("sqrt(-2*x^3)", "-x*sqrt(-2*x)", None),
    ("sqrt(-2*x^3)", "sqrt(-2*x)*(-x)", None),
    ("sqrt(3*x^3)", "x*sqrt(3*x)", None),
    ("sqrt(3*x^3)", "sqrt(3*x)*x", None),
    ("sqrt(x-1)*sqrt(x+1)", "sqrt((x+1)*(x-1))", "[1,∞)"),
    ("sqrt(x+1)*sqrt(x-1)", "sqrt((x-1)*(x+1))", "[1,∞)"),
    ("sqrt(x^2+1)*sqrt(x^2+1)", "x^2+1", None),
    ("sqrt(x^2+1)^2", "x^2+1", None),
    ("sqrt(x^2-1)*sqrt(x^2-1)", "sqrt(x^2-1)^2", None),
    ("sqrt(x^6+1)", "sqrt(1+x^6)", None),
    ("abs(x^3)", "sqrt(x^6)", None),
    ("x*abs(x)", "-x^2", "(-∞,0]"),
    ("x*abs(x)", "x^2", "[0,∞)"),
    ("0*sqrt(x)", "0", "[0,∞)"),
    ("sqrt(0*x^2)*x", "0", None),
    ("sqrt(x)/sqrt(x)", "1", "(0,∞)"),
    ("(x-1)*sqrt(x)/((x-1)*sqrt(x))", "1", "(0,∞) setminus {1}"),
    ("sqrt(x)/(-sqrt(x))", "-1", "(0,∞)"),
    ("(x^2/x)*sqrt(x^2+1)", "x*sqrt(x^2+1)", "ℝ setminus {0}"),
    ("-sqrt(x)*sqrt(x)", "-x", "[0,∞)"),
    ("sqrt(2)*sqrt(8)", "4", None),
    ("-3*sqrt(2)*sqrt(8)", "-12", None),
    ("sqrt(x)", "1", "{1}"),
    ("sqrt(x^2+1)", "1", "{0}"),
    ("(x^2-2)*sqrt(x)", "-1", "{1}"),
    ("sqrt(x)+sqrt(x+1)", "1", "{0}"),
    ("sqrt(-(x^2-1)^2)", "0*sqrt(-(x^2-1)^2)", None),
])
def test_radical_products_positive_negative_zero_and_original_domains(left, right, domain):
    checked(left, right, domain)


@pytest.mark.parametrize("left,right,domain", [
    ("sqrt(-2*x^3)", "x*sqrt(-2*x)", None),
    ("sqrt(3*x^3)", "-x*sqrt(3*x)", None),
    ("sqrt(x^2+1)", "-sqrt(x^2+1)", None),
    ("sqrt(x^2+1)", "sqrt(x^2+2)", None),
    ("x*sqrt(x^2+1)", "-x*sqrt(x^2+1)", None),
    ("sqrt(x)", "x", "[0,∞)"),
    ("x^3*(x-1)*(x+1)", "0", None),
    ("sqrt(x)", "2", "{1}"),
])
def test_no_square_only_or_finite_sample_identity(left, right, domain):
    _, _, result = checked(left, right, domain, relation="different")
    assert result["reason"] == "outputs_differ"
    assert result["counterexample"]["left_value"] != result["counterexample"]["right_value"]


@pytest.mark.parametrize("mutation", ["square", "sign", "value", "missing_cell", "sample", "source", "rule"])
def test_radical_identity_certificate_mutations_fail_closed(mutation):
    lhs, rhs, result = checked("x*sqrt(x^2+1)", "sqrt(x^2+1)*x")
    bad = deepcopy(result)
    cell = bad["proof"]["cells"][0]
    if mutation == "square":
        cell["left_rule"]["square"] += 1
    elif mutation == "sign":
        cell["left_rule"]["sign"] *= -1
    elif mutation == "value":
        cell["left_polynomial"] = -cell["left_polynomial"]
    elif mutation == "missing_cell":
        bad["proof"]["cells"].pop(1)
    elif mutation == "sample":
        cell["sample"] = sp.S.One
    elif mutation == "source":
        bad["left"]["expression_ast"] = descriptor("sqrt(x^2+1)")["expression_ast"]
    else:
        cell["left_rule"] = {"rule": "bounded_rational_normal_form", "normal_form": sp.S.One}
    assert equality.verify_pair(lhs, rhs, bad)["status"] == "math_failed"


def test_verifier_rejects_a_producer_that_omits_internal_sign_changes(monkeypatch):
    lhs = descriptor("((x-1)*(x-3))*sqrt(x^2+1)")
    rhs = descriptor("sqrt(((x-1)*(x-3))^2*(x^2+1))")
    assert equality.compare_pair(lhs, rhs)["relation"] == "different"
    monkeypatch.setattr(equality, "_rational_cuts", lambda value: set())
    forged = equality.compare_pair(lhs, rhs)
    assert forged["relation"] == "equal", forged
    checked_result = equality.verify_pair(lhs, rhs, forged)
    assert checked_result["status"] == "math_failed"
    assert checked_result["diagnostics"][0]["code"] == "function_equality.sign_cell_not_invariant"


def test_radical_identity_verifier_does_not_call_producer(monkeypatch):
    lhs, rhs, result = checked("sqrt(-2*x^3)", "-x*sqrt(-2*x)")

    def forbidden(*args, **kwargs):
        raise AssertionError("independent verification cannot call producer")

    for name in ("_radical_monomial", "_monomial_square", "_generic_cell", "_rational_cuts", "_solve_domain"):
        monkeypatch.setattr(equality, name, forbidden)
    assert equality.verify_pair(lhs, rhs, result)["status"] == "verified"


def test_zero_power_and_rationalized_radical_keep_their_original_holes():
    _, _, result = checked("sqrt((x-1)^2)/sqrt((x-1)^2)", "(x-1)^0")
    assert result["left"]["domain"] == result["right"]["domain"] == sp.S.Reals - sp.FiniteSet(1)
    assert result["left"]["constraints"] and result["right"]["constraints"]


@pytest.mark.parametrize("left,right,flag", [
    ("sqrt(x^2+1)^2", "x^2+1", "from_square_root"),
    ("abs(x^3)^2", "x^6", "from_absolute"),
])
def test_rationalized_source_still_carries_its_mathematical_basis(left, right, flag):
    _, _, result = checked(left, right)
    assert all(row["left_rule"].get(flag) for row in result["proof"]["cells"]
               if isinstance(row["domain"], sp.Interval))


def test_coefficient_budget_applies_to_rational_intermediates_before_cancellation():
    factor = 2 ** 100
    lhs = descriptor(f"({factor}*{factor}*x)/({factor}*{factor})")
    result = equality.compare_pair(lhs, descriptor("x"))
    assert result["relation"] == "unresolved"
    assert "coefficient_limit" in result["reason"]
