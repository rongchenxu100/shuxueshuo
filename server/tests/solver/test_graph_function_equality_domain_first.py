"""Domain admission is independent of correspondence normalization."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import function_equality as equality
from tests.solver.test_graph_function_equality_math import descriptor


@pytest.mark.parametrize("left,right,point", [
    ("x", "x^2/x", 0),
    ("sqrt(x-1)*sqrt(x+1)", "sqrt((x+1)*(x-1))", -2),
    ("sqrt(x)+sqrt(x-1)", "x", 0),
    ("(x^4-1)/(x^2-1)", "x^2+1", -1),
    ("0/(x-2)", "0", 2),
])
def test_domain_difference_never_calls_correspondence_producer(monkeypatch, left, right, point):
    def forbidden(*args, **kwargs):
        raise AssertionError("different domains must not need an M8 normal form")

    monkeypatch.setattr(equality, "_radical_monomial", forbidden)
    monkeypatch.setattr(equality, "_normal_form", forbidden)
    lhs, rhs = descriptor(left), descriptor(right)
    assert equality.structural_inspect(lhs)["structure_supported"] is True
    assert equality.structural_inspect(rhs)["structure_supported"] is True
    result = equality.compare_pair(lhs, rhs)
    assert (result["relation"], result["reason"]) == ("different", "domains_differ")
    assert result["counterexample"]["point"] == point
    assert equality.verify_pair(lhs, rhs, result)["status"] == "verified"


@pytest.mark.parametrize("expression", ["sqrt(x)+sqrt(x+1)", "sqrt(x)-sqrt(x+1)", "x^3+abs(x)"])
def test_same_domain_without_a_full_correspondence_proof_stays_unresolved(expression):
    lhs, rhs = descriptor(expression), descriptor(expression, function_ref="option:A:g")
    assert equality.structural_inspect(lhs)["structure_supported"] is True
    result = equality.compare_pair(lhs, rhs)
    assert result["relation"] == "unresolved"
    assert result["reason"] == "function_equality.radical_sum_unsupported"


@pytest.mark.parametrize("expression", ["sqrt(x^7)", "sqrt(x^3-2)", "abs(x^2-2)", "a*x", "sqrt(sqrt(x))"])
def test_domain_first_does_not_bypass_the_m1_scope_boundary(expression):
    lhs = descriptor(expression)
    assert equality.structural_inspect(lhs)["structure_supported"] is False
    assert equality.compare_pair(lhs, descriptor("x"))["relation"] == "unresolved"


@pytest.mark.parametrize("left,right,domain", [
    ("x^2/x", "x", "ℝ setminus {0}"),
    ("(x^2-1)/(x-1)", "x+1", "ℝ setminus {1}"),
    ("(x^4-1)/(x^2-1)", "x^2+1", "[-2,2] setminus {-1,1}"),
    ("(x^4+1)/(x^2+1)", "x^2+1-2*x^2/(x^2+1)", None),
    ("x^0", "1", "ℝ setminus {0}"),
    ("(x-1)/(x-1)", "(2*x-2)/(2*x-2)", None),
    ("1/(x^2-1)", "1/((x-1)*(x+1))", None),
    ("x^12", "x^6*x^6", None),
])
def test_bounded_rational_identities_keep_all_original_restrictions(left, right, domain):
    lhs, rhs = descriptor(left, domain=domain), descriptor(right, domain=domain)
    result = equality.compare_pair(lhs, rhs)
    assert result["relation"] == "equal", result
    assert equality.verify_pair(lhs, rhs, result)["status"] == "verified"
    if "/" in left:
        assert any(row["kind"] == "denominator_nonzero" for row in result["left"]["constraints"])


def test_explicit_domain_cannot_legitimize_original_denominator_zero():
    lhs = descriptor("x^2/x", domain="[-1,1]")
    result = equality.compare_pair(lhs, descriptor("x", domain="[-1,1]"))
    assert result["relation"] == "unresolved"
    assert result["reason"] == "function_equality.declared_domain_conflict"


@pytest.mark.parametrize("mutation", ["restore_hole", "erase_guard", "replace_expression", "wrong_membership"])
def test_domain_only_certificates_reject_mutations(mutation):
    lhs, rhs = descriptor("x"), descriptor("x^2/x")
    result = equality.compare_pair(lhs, rhs)
    bad = deepcopy(result)
    if mutation == "restore_hole":
        bad["right"]["domain"] = sp.S.Reals
    elif mutation == "erase_guard":
        bad["right"]["constraints"] = []
    elif mutation == "replace_expression":
        bad["right"]["expression_ast"] = lhs["expression_ast"]
    else:
        bad["counterexample"]["right_in_domain"] = True
    assert equality.verify_pair(lhs, rhs, bad)["status"] == "math_failed"


def test_correspondence_degree_budget_cannot_block_a_domain_counterexample():
    large = "((x+1)^12)^3"
    lhs = descriptor(large)
    assert equality.structural_inspect(lhs)["structure_supported"] is True
    result = equality.compare_pair(lhs, descriptor("x"))
    assert (result["relation"], result["reason"]) == (
        "unresolved", "function_equality.correspondence_degree_limit")
    rhs = descriptor("sqrt(x)")
    result = equality.compare_pair(lhs, rhs)
    assert (result["relation"], result["reason"]) == ("different", "domains_differ")
    assert equality.verify_pair(lhs, rhs, result)["status"] == "verified"


def test_rational_identity_verifier_does_not_call_producer(monkeypatch):
    lhs, rhs = descriptor("(x^4+1)/(x^2+1)"), descriptor("x^2+1-2*x^2/(x^2+1)")
    result = equality.compare_pair(lhs, rhs)
    assert result["relation"] == "equal"

    def forbidden(*args, **kwargs):
        raise AssertionError("independent verification cannot call producer")

    for name in ("_radical_monomial", "_generic_cell", "_solve_domain", "_partition_at"):
        monkeypatch.setattr(equality, name, forbidden)
    assert equality.verify_pair(lhs, rhs, result)["status"] == "verified"
