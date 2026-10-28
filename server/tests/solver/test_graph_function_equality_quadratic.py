"""Q19 expansion: exact sign families, original holes and independent proofs.

These are declared development regressions, not the separately frozen holdout.
"""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import function_equality as equality
from tests.solver.test_graph_function_equality_math import descriptor


def checked_pair(left, right, *, domain=None, expected="equal"):
    lhs = descriptor(left, domain=domain)
    rhs = descriptor(right, domain=domain, function_ref="option:A:g")
    result = equality.compare_pair(lhs, rhs)
    assert result["relation"] == expected, result
    assert equality.verify_pair(lhs, rhs, result)["status"] == "verified"
    return lhs, rhs, result


@pytest.mark.parametrize("candidate,expected", [
    ("x^2+abs(x^2+1)", "equal"),
    ("sqrt((2*x^2+1)^2)", "equal"),
    ("abs(2*x^2+1)", "equal"),
    ("((2*x^2+1)*(x+1))/(x+1)", "different"),
])
def test_q19_four_candidates_against_one_baseline(candidate, expected):
    _, _, result = checked_pair("2*x^2+1", candidate, expected=expected)
    if expected == "different":
        assert result["reason"] == "domains_differ"
        assert result["counterexample"]["point"] == -1
        assert result["right"]["natural_domain"] == sp.S.Reals - sp.FiniteSet(-1)
        assert any(row["kind"] == "denominator_nonzero" for row in result["right"]["constraints"])


SIGN_POLYNOMIALS = [
    "x^2+1", "-x^2-1",               # no real roots, either opening
    "(x-2)^2", "-(x-2)^2",           # a repeated root, either opening
    "x^2-1", "1-x^2",               # two rational roots and three sign cells
    "(3/2)*x^2-(3/4)*x-3/4",          # nonintegral coefficients and roots
    "0*x^2+2*x-3", "0*x^2-2*x+3",    # degree degenerates to either linear sign
    "0*x^2+0*x+3", "0*x^2+0*x-3",    # positive and negative constants
    "0*x^2+0*x", "x^2-x*x",          # literal and algebraic zero polynomials
]


@pytest.mark.parametrize("polynomial", SIGN_POLYNOMIALS)
def test_all_quadratic_sign_families_match_square_root_and_absolute(polynomial):
    lhs, _, result = checked_pair(f"sqrt(({polynomial})^2)", f"abs({polynomial})")
    assert result["left"]["domain"] == result["right"]["domain"] == sp.S.Reals
    # Each side and each bound name is independent of representative Q19 data.
    renamed = descriptor(f"abs({polynomial.replace('x', 't')})", variable="t")
    reverse = equality.compare_pair(renamed, lhs)
    assert reverse["relation"] == "equal"
    assert equality.verify_pair(renamed, lhs, reverse)["status"] == "verified"


@pytest.mark.parametrize("polynomial", SIGN_POLYNOMIALS)
def test_polynomial_offset_and_commuted_sum_keep_all_sign_cells(polynomial):
    checked_pair(f"x^2-2*x+3+abs({polynomial})", f"abs(-({polynomial}))+(x^2-2*x+3)")


@pytest.mark.parametrize("left,right,domain,expected", [
    ("abs(x^2-1)", "x^2-1", None, "different"),
    ("sqrt((x^2-1)^2)", "x^2-1", None, "different"),
    ("abs(x^2-1)", "x^2-1", "[1,∞)", "equal"),
    ("abs(x^2-1)", "1-x^2", "[-1,1]", "equal"),
    ("abs(x^2-1)", "x^2-1", "[-1,1]", "different"),
    ("x^2+abs(x^2-1)", "1", "[-1,1]", "equal"),
    ("x^2+abs(x^2-1)", "2*x^2-1", "(-∞,-1]", "equal"),
    ("abs(-(x-2)^2)", "(x-2)^2", None, "equal"),
    ("abs(0*x^2+0*x)", "0", None, "equal"),
    ("abs(x^2-1)", "0", "{1}", "equal"),
    ("abs(x^2-1)", "0", "{0}", "different"),
])
def test_domain_relative_signs_endpoints_and_exact_negative_witnesses(left, right, domain, expected):
    _, _, result = checked_pair(left, right, domain=domain, expected=expected)
    if expected == "different":
        assert result["reason"] == "outputs_differ"
        assert isinstance(result["counterexample"]["point"], sp.Rational)
        assert result["counterexample"]["left_value"] != result["counterexample"]["right_value"]


@pytest.mark.parametrize("expression,polynomial,hole", [
    ("((x^2+1)*(x-1))/(x-1)", "x^2+1", 1),
    ("((x-1)*(x^2+1))/(x-1)", "x^2+1", 1),
    ("((x^2+1)*(1-x))/(-x+1)", "x^2+1", 1),
    ("((x+1)*(2*x-1))/(2*x-1)", "x+1", sp.Rational(1, 2)),
    ("(0*(x+1))/(x+1)", "0", -1),
    ("((x-x)*(x+1))/(x+1)", "0", -1),
])
def test_cancellation_keeps_original_nonzero_factor_and_accepts_common_punctured_domain(expression, polynomial, hole):
    _, _, result = checked_pair(expression, polynomial, expected="different")
    assert result["reason"] == "domains_differ"
    assert result["counterexample"]["point"] == hole
    assert result["left"]["constraints"][0]["kind"] == "denominator_nonzero"
    assert result["left"]["constraints"][0]["ast_path"] == [2]
    domain = f"ℝ setminus {{{hole}}}"
    _, _, result = checked_pair(expression, polynomial, domain=domain)
    assert result["left"]["domain"] == result["right"]["domain"] == sp.S.Reals - sp.FiniteSet(hole)
    assert all(row["left_rule"]["rule"] == "cancel_common_nonzero_factor" for row in result["proof"]["cells"])
    # Source guards remain even though the explicit domain already removes the hole.
    assert any(row["kind"] == "denominator_nonzero" for row in result["left"]["constraints"])


@pytest.mark.parametrize("factor", ["2", "-3", "0*x+4"])
def test_nonzero_constant_cancellation_degenerate_branch(factor):
    checked_pair(f"((x^2+1)*({factor}))/({factor})", "x^2+1")


def test_declared_domain_cannot_restore_a_cancelled_hole():
    left = descriptor("((x^2+1)*(x-1))/(x-1)", domain="ℝ")
    result = equality.compare_pair(left, descriptor("x^2+1"))
    assert result["relation"] == "unresolved"
    assert result["reason"] == "function_equality.declared_domain_conflict"


@pytest.mark.parametrize("left,right,domain", [
    ("abs(x^2-1)", "1-x^2", "[-1,1] setminus {-1,0,1}"),
    ("sqrt((x^2-1)^2)", "abs(x^2-1)", "ℝ setminus {-2,0,2}"),
    ("(0*(x+1))/(x+1)", "0", "[-2,2] setminus {-1,0,1}"),
])
def test_sign_partition_and_original_holes_on_disconnected_explicit_domains(left, right, domain):
    _, _, result = checked_pair(left, right, domain=domain)
    assert sp.Union(*(row["domain"] for row in result["proof"]["cells"])) == result["left"]["domain"]


def test_equality_honors_the_shared_removed_points_and_coefficient_budget():
    value = descriptor("abs(x^2+1)", domain="ℝ setminus {" + ",".join(map(str, range(17))) + "}")
    assert equality.structural_inspect(value)["structure_supported"] is False
    assert equality.compare_pair(value, descriptor("x^2+1"))["relation"] == "unresolved"
    value = descriptor(f"abs({2**129}*x^2+1)")
    assert equality.structural_inspect(value)["structure_supported"] is False


@pytest.mark.parametrize("expression", [
    "abs(x^2-2)", "sqrt((x^2-2)^2)", "x+abs(x^2-2)",  # irrational sign cuts
    "sqrt(x^4+1)", "sqrt(x^4+2*x^2+1)",               # no original square structure
    "abs(x^3)", "sqrt((x^3)^2)", "x^3+abs(x)",
    "abs(abs(x))", "sqrt((abs(x))^2)", "abs(sqrt(x))",
    "abs(x)+abs(x-1)", "x*abs(x)",
    "(x^2-1)/(x-1)", "((x^2+1)*(x+1))/(x-1)",
    "((x^3+1)*(x-1))/(x-1)", "((x^2+1)*(x^2-1))/(x^2-1)",
    "((x^2+1)*0)/0", "((x^2+1)*(x-x))/(x-x)",
    "a*x+abs(x)", "abs(a*x^2+1)",
])
def test_outside_declared_families_is_unresolved_never_unequal(expression):
    value = descriptor(expression)
    assert equality.structural_inspect(value)["structure_supported"] is False
    assert equality.compare_pair(value, descriptor("x"))["relation"] == "unresolved"


def test_sign_partition_is_complete_and_uses_every_quadratic_root():
    _, _, result = checked_pair("sqrt((x^2-1)^2)", "abs(x^2-1)")
    cells = result["proof"]["cells"]
    assert [row["domain"] for row in cells] == [
        sp.Interval.open(-sp.oo, -1), sp.FiniteSet(-1), sp.Interval.open(-1, 1),
        sp.FiniteSet(1), sp.Interval.open(1, sp.oo)]
    assert [row["left_rule"].get("sign") for row in cells] == [1, None, -1, None, 1]
    for row in (cells[0], cells[2], cells[4]):
        assert row["left_rule"]["sign_evidence"]["real_zeros"] == [-1, 1]


@pytest.mark.parametrize("mutation", ["missing_cell", "wrong_sign", "missing_root", "wrong_sample_value", "wrong_offset"])
def test_quadratic_certificate_mutations_are_rejected(mutation):
    left, right, result = checked_pair("x^2+abs(x^2-1)", "abs(1-x^2)+x^2")
    bad = deepcopy(result)
    rule = bad["proof"]["cells"][0]["left_rule"]
    if mutation == "missing_cell":
        bad["proof"]["cells"].pop(2)
    elif mutation == "wrong_sign":
        rule["sign"] = -1
    elif mutation == "missing_root":
        rule["sign_evidence"]["real_zeros"].pop()
    elif mutation == "wrong_sample_value":
        rule["sign_evidence"]["sample_value"] = -1
    else:
        rule["polynomial_offset"] += 1
    assert equality.verify_pair(left, right, bad)["status"] == "math_failed"


@pytest.mark.parametrize("mutation", ["restore_hole", "drop_guard", "wrong_factor", "wrong_factor_path"])
def test_cancellation_certificate_mutations_are_rejected(mutation):
    left, right, result = checked_pair("((x^2+1)*(x-1))/(x-1)", "x^2+1", domain="ℝ setminus {1}")
    bad = deepcopy(result)
    if mutation == "restore_hole":
        bad["left"]["domain"] = sp.S.Reals
    elif mutation == "drop_guard":
        bad["left"]["constraints"] = []
    elif mutation == "wrong_factor":
        bad["proof"]["cells"][0]["left_rule"]["common_factor"] += 1
    else:
        bad["proof"]["cells"][0]["left_rule"]["factor_ast_path"] = [1, 1]
    assert equality.verify_pair(left, right, bad)["status"] == "math_failed"


def test_identity_verification_does_not_call_the_producer_or_condition_solver(monkeypatch):
    left, right, result = checked_pair("x^2+abs(x^2+1)", "2*x^2+1")

    def forbidden(*args, **kwargs):
        raise AssertionError("producer must not be used for independent identity verification")

    monkeypatch.setattr(equality, "_normal_form", forbidden)
    monkeypatch.setattr(equality, "_solve_domain", forbidden)
    assert equality.verify_pair(left, right, result)["status"] == "verified"


def test_independent_root_count_rejects_a_producer_that_misses_sign_changes(monkeypatch):
    left, right = descriptor("abs(x^2-1)"), descriptor("1-x^2")
    # Simulate the producer accidentally omitting both roots. A sample at zero
    # would now claim equality on all reals; root-count validation must fail.
    monkeypatch.setattr(equality, "_breakpoints", lambda value: [])
    bad = equality.compare_pair(left, right)
    assert bad["relation"] == "equal", bad
    checked = equality.verify_pair(left, right, bad)
    assert checked["status"] == "math_failed"
    assert checked["diagnostics"][0]["code"] == "function_equality.sign_cell_not_invariant"
