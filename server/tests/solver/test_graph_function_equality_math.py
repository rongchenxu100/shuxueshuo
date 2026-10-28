"""Q20 family: domain-first comparison, full certificates and hostile mutations."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_equality import (
    compare_pair,
    domain_context,
    structural_inspect,
    verify_pair,
)
from shuxueshuo_server.graph_lesson.stage_one.function_domain import (
    ARGUMENT,
    expression_latex,
)
from shuxueshuo_server.graph_lesson.stage_three.function_domain import admitted
from shuxueshuo_server.problem_understanding.notation_parser import parse


def descriptor(text, variable="x", domain=None, function_ref="option:A:f"):
    def bind(ast):
        if ast == ["name", variable]:
            return deepcopy(ARGUMENT)
        if ast[0] == "name":
            return ["ref", "free:" + ast[1]]
        return [bind(child) if isinstance(child, list) else child for child in ast]

    def normalize_domain(ast):
        if ast[0] == "tuple":
            return ["interval", False, False, *ast[1:]]
        if ast[0] == "set_difference":
            return ["set_difference", normalize_domain(ast[1]), ast[2]]
        return ast

    domain_ast = normalize_domain(parse(domain)) if domain else ["real"]
    return {"function_ref": function_ref, "function_name": "f", "variable": variable,
            "source_ref": "/root/goals/0/comparison/options/A/functions/f/definition",
            "expression_ast": bind(parse(text)), "input_domain_ast": domain_ast,
            "input_domain_source_ref": "/root/goals/0/options/A/domain" if domain else "",
            "explicit_domain": domain is not None}


@pytest.mark.parametrize("lhs,rhs,relation,reason", [
    ("x", "sqrt(x)^2", "different", "domains_differ"),
    ("x^2", "(x+1)^2", "different", "outputs_differ"),
    ("sqrt(x^2)", "abs(x)", "equal", "same_domain_and_correspondence"),
    ("3*x^2-2*x+3", "3*x^2-2*x+3", "equal", "same_domain_and_correspondence"),
    ("sqrt(x^2)", "x", "different", "outputs_differ"),
    ("sqrt((-2*x+4)^2)", "abs(4-2*x)", "equal", "same_domain_and_correspondence"),
    ("sqrt((-3)^2)", "3", "equal", "same_domain_and_correspondence"),
    ("sqrt(0^2)", "abs(0)", "equal", "same_domain_and_correspondence"),
    ("sqrt(0*x+4)^2", "4", "equal", "same_domain_and_correspondence"),
    ("abs(0*x-2)", "2", "equal", "same_domain_and_correspondence"),
    ("0^2", "0", "equal", "same_domain_and_correspondence"),
    ("(-3)^2", "9", "equal", "same_domain_and_correspondence"),
    ("(x-1)*(x+1)", "x^2-1", "equal", "same_domain_and_correspondence"),
    ("x*(x-1)", "0", "different", "outputs_differ"),
])
def test_complete_first_batch_family(lhs, rhs, relation, reason):
    left, right = descriptor(lhs), descriptor(rhs, function_ref="option:A:g")
    result = compare_pair(left, right)
    assert (result["relation"], result["reason"]) == (relation, reason), result
    assert verify_pair(left, right, result)["status"] == "verified"


def test_q20_domain_first_and_exact_counterexample():
    result = compare_pair(descriptor("x"), descriptor("sqrt(x)^2"))
    assert result["left"]["domain"] == sp.S.Reals
    assert result["right"]["domain"] == sp.Interval(0, sp.oo)
    assert result["counterexample"]["point"] < 0
    assert result["right"]["constraints"][0]["ast_path"] == [1, 2]
    result = compare_pair(descriptor("x^2"), descriptor("(x+1)^2"))
    assert result["counterexample"] == {"point": sp.S.Zero, "left_value": sp.S.Zero, "right_value": sp.S.One}


def test_bound_argument_renaming_and_abs_source_display():
    left, right = descriptor("3*x^2-2*x+3"), descriptor("3*t^2-2*t+3", variable="t")
    assert compare_pair(left, right)["relation"] == "equal"
    assert expression_latex(descriptor("abs(x)")["expression_ast"], "x") == r"\left|x\right|"
    assert admitted(domain_context(descriptor("abs(x)")))


@pytest.mark.parametrize("slope", [-3, 0, 2])
@pytest.mark.parametrize("intercept", [-2, 0, 5])
def test_affine_absolute_family_covers_every_coefficient_sign(slope, intercept):
    affine = f"({slope}*x+({intercept}))"
    left, right = descriptor(f"sqrt({affine}^2)"), descriptor(f"abs({affine})")
    result = compare_pair(left, right)
    assert result["relation"] == "equal", result
    assert verify_pair(left, right, result)["status"] == "verified"


@pytest.mark.parametrize("lhs,rhs,domain,expected", [
    ("sqrt(x^2)", "x", "[0,∞)", "equal"),
    ("sqrt(x)^2", "x", "[0,∞)", "equal"),
    ("sqrt((1-2*x)^2)", "1-2*x", "(-∞,0.5]", "equal"),
    ("sqrt((1-2*x)^2)", "1-2*x", "(0.5,∞)", "different"),
    ("x^2", "x", "[0,0]", "equal"),
    ("x^2", "x", "{1}", "equal"),
    ("x^2", "x", "{2}", "different"),
    ("x^2", "x", "(0,1)", "different"),
])
def test_explicit_intervals_singletons_and_boundary_truth(lhs, rhs, domain, expected):
    left, right = descriptor(lhs, domain=domain), descriptor(rhs, domain=domain)
    result = compare_pair(left, right)
    assert result["relation"] == expected, result
    assert verify_pair(left, right, result)["status"] == "verified"


def test_singleton_notation_equivalent_but_source_preserved():
    left, right = descriptor("x^2", domain="[0,0]"), descriptor("x", domain="{0}")
    result = compare_pair(left, right)
    assert result["relation"] == "equal"
    assert result["left"]["domain"] == result["right"]["domain"] == sp.FiniteSet(0)
    assert result["left"]["input_domain_ast"] != result["right"]["input_domain_ast"]
    assert verify_pair(left, right, result)["status"] == "verified"


def test_natural_domain_does_not_become_declared_because_source_exists():
    left = descriptor("sqrt(x)^2")
    assert left["source_ref"] and not left["input_domain_source_ref"]
    result = compare_pair(left, descriptor("x", domain="[0,∞)"))
    assert result["relation"] == "equal"


@pytest.mark.parametrize("text,domain,reason", [
    ("sqrt(x)^2", "ℝ", "function_equality.declared_domain_conflict"),
    ("sqrt(x)^2", "[-1,1]", "function_equality.declared_domain_conflict"),
    ("sqrt(-1)^2", None, "function_equality.empty_function_domain"),
    ("x", "[0,0)", "function_equality.empty_function_domain"),
    ("x", "(0,0]", "function_equality.empty_function_domain"),
    ("x", "[2,1]", "function_equality.empty_function_domain"),
])
def test_invalid_function_does_not_become_false_or_vacuously_equal(text, domain, reason):
    left = descriptor(text, domain=domain)
    result = compare_pair(left, descriptor("x"))
    assert result["relation"] == "unresolved"
    assert result["reason"] == reason, result


@pytest.mark.parametrize("text", [
    "sqrt((2*x^3+1)^2)", "a*x+1", "sqrt(sqrt(x))", "abs(abs(x))",
])
def test_unsupported_structures_remain_unresolved(text):
    value = descriptor(text)
    assert structural_inspect(value)["structure_supported"] is False
    assert compare_pair(value, descriptor("x"))["relation"] == "unresolved"


@pytest.mark.parametrize("text,reason", [
    ("abs(x^3+1)", "outputs_differ"), ("x^3", "outputs_differ"),
    ("sqrt(x)", "domains_differ"), ("(x^2-1)/(x-1)", "domains_differ"),
    ("(x-1)^0", "domains_differ"), ("x^12", "outputs_differ"),
])
def test_previously_family_blocked_structures_use_domain_first_proofs(text, reason):
    value, other = descriptor(text), descriptor("x")
    assert structural_inspect(value)["structure_supported"] is True
    result = compare_pair(value, other)
    assert (result["relation"], result["reason"]) == ("different", reason)
    assert verify_pair(value, other, result)["status"] == "verified"


def test_affirmative_certificate_covers_negative_zero_and_positive_cells():
    left, right = descriptor("sqrt(x^2)"), descriptor("abs(x)")
    result = compare_pair(left, right)
    cells = result["proof"]["cells"]
    assert [row["domain"] for row in cells] == [sp.Interval.open(-sp.oo, 0), sp.FiniteSet(0), sp.Interval.open(0, sp.oo)]
    assert [row["left_rule"].get("sign") for row in cells] == [-1, None, 1]
    for mutation in ("remove_cell", "wrong_sign", "wrong_domain", "wrong_poly", "wrong_source", "wrong_guard"):
        bad = deepcopy(result)
        if mutation == "remove_cell":
            bad["proof"]["cells"].pop(0)
        elif mutation == "wrong_sign":
            bad["proof"]["cells"][0]["left_rule"]["sign"] = 1
        elif mutation == "wrong_domain":
            bad["left"]["domain"] = sp.Interval(0, sp.oo)
        elif mutation == "wrong_poly":
            bad["proof"]["cells"][0]["left_polynomial"] = sp.Symbol("u", real=True)
        elif mutation == "wrong_source":
            bad["left"]["source_ref"] = "/other/option"
        else:
            bad["left"]["constraints"][0]["condition"] = sp.true
        assert verify_pair(left, right, bad)["status"] == "math_failed", mutation


@pytest.mark.parametrize("left,right,new_point", [
    ("x", "sqrt(x)^2", sp.S.One),
    ("x^2", "(x+1)^2", sp.Rational(-1, 2)),
    ("x^2", "(x+1)^2", sp.oo),
    ("x^2", "(x+1)^2", sp.Float(0)),
])
def test_verifier_rejects_invalid_counterexamples(left, right, new_point):
    left, right = descriptor(left), descriptor(right)
    result = compare_pair(left, right)
    result["counterexample"]["point"] = new_point
    assert verify_pair(left, right, result)["status"] == "math_failed"
