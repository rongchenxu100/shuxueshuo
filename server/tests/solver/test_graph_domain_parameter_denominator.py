"""The root-denominator M6 contract, checked by structure rather than question id."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.function_domain_parameter import (
    inspect_match_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_three import capabilities, driver, selection
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_domain import (
    admitted_parameter,
    extract_domain_parameter_conditions,
    reduce_domain_equality_to_universal,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    endpoint_check,
    verify,
)
from tests.solver.test_graph_domain_parameter import (
    TARGET,
    candidate,
    execute,
    recognized,
    rows,
)


@pytest.mark.parametrize("numerator", [
    "1", "0", "-1", "k", "x", "k*x+x^2", "(x+k)^2", "(x+1)/2",
    "2^0", "k*x^2-6*k*x+k+8",
])
def test_polynomial_numerators_preserve_both_original_restrictions(numerator):
    value = candidate(f"({numerator})/sqrt(k*x^2-6*k*x+k+8)")
    frozen = deepcopy(value)
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is True, description
    assert description["has_division"] is True
    assert recognized(value) == ["type-function-domain"]
    selected = selection.evaluate_goal(value, TARGET, rows(value), "type-function-domain")
    assert selected["selection"]["branches"][0]["target"] == "method-domain-parameter"
    context = build_context(value, TARGET)
    assert admitted_parameter(context)
    extracted = extract_domain_parameter_conditions(context)["outputs"]
    constraints = extracted["constraints"]
    assert [(row["kind"], row["ast_path"], row["basis_refs"]) for row in constraints] == [
        ("radicand_nonnegative", [2, 2], ["square-root-expression#meaning"]),
        ("denominator_nonzero", [2], ["rational-expression#meaning"]),
    ]
    assert extracted["conditions"] == [row["condition"] for row in constraints]
    assert constraints[0]["condition"].rel_op == ">="
    assert constraints[1]["condition"].rel_op == "!="
    assert constraints[1]["expression_ast"] == description["expression_ast"][2]
    assert constraints[0]["expression_ast"] == description["expression_ast"][2][2]
    assert {row["source_ref"] for row in constraints} == {"/root/definitions/0"}
    reduced = reduce_domain_equality_to_universal(**{
        key: extracted[key] for key in ("constraints", "description", "variable", "parameter", "goal", "context")
    })["outputs"]
    assert reduced["strict"] is True
    assert reduced["relation"].rel_op == ">"
    assert reduced["universal_statement"] == reduced["relation"]
    assert reduced["relation"].lhs == constraints[0]["condition"].lhs
    assert value == frozen


@pytest.mark.parametrize("numerator", [
    "1/x", "0/x", "0*(1/x)", "1/k", "sqrt(x^2)", "x^0", "0^0", "x^(-1)",
    "x^(1/2)", "x^13", "(x^12)^12", "(1^12)^12", str(2**129),
    f"{2**127}+{2**127}", f"{2**64}*{2**64}",
])
def test_hidden_numerator_restrictions_and_over_budget_polynomials_are_rejected(numerator):
    value = candidate(f"({numerator})/sqrt(k*x^2+1)")
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is False, description
    assert "type-function-domain" not in recognized(value)


@pytest.mark.parametrize("expression", [
    "1/(sqrt(k*x^2+1)+1)", "1/sqrt(k*x^3+1)", "1/sqrt(k^2*x^2+1)",
    "1/sqrt(k*x+1)", "1/sqrt(x^2+1)", "1/(x*sqrt(k*x^2+1))",
])
def test_denominator_extension_does_not_expand_the_radicand_contract(expression):
    description = inspect_match_domain_target(candidate(expression), TARGET)
    assert description["structure_supported"] is False


@pytest.mark.parametrize("tamper", ["omit_denominator", "weaken_denominator", "move_source", "change_flag"])
def test_reduction_rejects_missing_or_forged_source_constraints(tamper):
    context = build_context(candidate("1/sqrt(k*x^2+1)"), TARGET)
    extracted = extract_domain_parameter_conditions(context)["outputs"]
    values = {key: deepcopy(extracted[key]) for key in (
        "constraints", "description", "variable", "parameter", "goal", "context"
    )}
    if tamper == "omit_denominator":
        values["constraints"].pop()
    elif tamper == "weaken_denominator":
        values["constraints"][1]["condition"] = sp.Ge(values["constraints"][1]["condition"].lhs, 0)
    elif tamper == "move_source":
        values["constraints"][1]["ast_path"] = [1]
    else:
        values["description"]["has_division"] = False
    with pytest.raises(capabilities.LocalCheckFailed, match="domain.parameter_source_mismatch"):
        reduce_domain_equality_to_universal(**values)
    altered_context = deepcopy(context)
    altered_context["domain_goal"]["has_division"] = False
    assert admitted_parameter(altered_context) is False


# Together with the non-strict matrix this covers positive/negative/fixed leading
# coefficients, linear and all constant degenerations, and all discriminant signs.
@pytest.mark.parametrize("radicand,expected", [
    ("x^2+k", sp.Interval.open(0, sp.oo)),
    ("-x^2+k", sp.S.EmptySet),
    ("k*x^2+2*x+1", sp.Interval.open(1, sp.oo)),
    ("k*x^2-2*x+1", sp.Interval.open(1, sp.oo)),
    ("k*x^2+1", sp.Interval(0, sp.oo)),
    ("k*x^2", sp.S.EmptySet),
    ("k*x^2-1", sp.S.EmptySet),
    ("k*x^2+k*x", sp.S.EmptySet),
    ("k*x^2+x", sp.S.EmptySet),
    ("(k-1)*x^2+2*(k-1)*x+k-1", sp.S.EmptySet),
    ("x^2+k*x+2", sp.Interval.open(-2 * sp.sqrt(2), 2 * sp.sqrt(2))),
    ("x^2+k*x-2", sp.S.EmptySet),
    ("k*x^2+(k-1)*x", sp.S.EmptySet),
    ("-k*x^2+k*x+1", sp.Interval.Lopen(-4, 0)),
    ("k*x^2-6*k*x+k+8", sp.Interval.Ropen(0, 1)),
], ids=[
    "fixed-positive-leading", "fixed-negative-leading", "positive-linear", "negative-linear",
    "positive-constant", "zero-constant", "negative-constant", "zero-constant-only",
    "positive-constant-discriminant", "identically-zero-discriminant", "algebraic-endpoints",
    "always-positive-discriminant", "repeated-discriminant-root", "reversed-leading-sign", "shifted-radicand",
])
def test_strict_structural_matrix_executes_and_independently_verifies(radicand, expected):
    value = candidate(f"1/sqrt({radicand})")
    _, state = execute(value)
    assert state["status"] == "method_complete", state.get("diagnostics") or state["trajectory"]
    assert driver.export_values(state)["feasible_set"] == expected
    assert state["verification"]["status"] == "verified", state["verification"]
    assert state["verification"]["proof"]["strict"] is True
    assert endpoint_check(value, TARGET, expected)["status"] == "passed"
    assert {step["method"] for step in state["trajectory"]["steps"]} <= {
        "method-domain-parameter", "method-discriminant", "quadratic-inequality-solve",
    }


@pytest.mark.parametrize("numerator", ["1", "0", "m", "m*x^2-6*m*x+m+8"])
def test_original_denominator_proof_is_independent_of_solver_and_cancellation(numerator, monkeypatch):
    value = candidate(f"({numerator})/sqrt(m*x^2-6*m*x+m+8)", parameter="m")
    context = build_context(value, TARGET)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("independent proof must read the original expression")

    monkeypatch.setattr(capabilities, "execute", forbidden)
    monkeypatch.setattr(sp, "solve_univariate_inequality", forbidden)
    answer = sp.Interval.Ropen(0, 1)
    proof = verify(value, TARGET, context, answer)
    assert proof["status"] == "verified", proof
    assert proof["proof"]["invariance"]["proved"] is True
    assert proof["proof"]["reconstructed_set"] == math_value(answer)
    assert proof["proof"]["expression_ast"] == context["domain_goal"]["expression_ast"]
    checked = endpoint_check(value, TARGET, answer)
    points = {row["point"]["expression"]: row for row in checked["points"]}
    assert checked["status"] == "passed"
    assert points["0"]["included"] is True and points["0"]["holds"] is True
    assert points["0"]["evidence"]["certificate"]["degree"] == 0
    assert points["0"]["evidence"]["certificate"]["coefficient_signs"]["C"] == 1
    assert points["1"]["included"] is False and points["1"]["holds"] is False
    assert points["1"]["evidence"]["certificate"]["discriminant_sign"] == 0
    assert all(row["evidence"]["certificate"]["strict"] for row in points.values())
    assert all(row["evidence"]["ast_path"] == [2, 2] for row in points.values())
    for wrong in [sp.Interval(0, 1), sp.Interval.open(0, 1), sp.Interval.Ropen(-1, 1)]:
        result = verify(value, TARGET, context, wrong)
        assert result["status"] == "math_failed", result
        assert result["counterexample"]["original_holds"] != result["counterexample"]["candidate_includes"]
        assert endpoint_check(value, TARGET, wrong)["status"] == "failed"


def test_pure_root_keeps_its_non_strict_reduction():
    context = build_context(candidate("sqrt(k*x^2+1)"), TARGET)
    extracted = extract_domain_parameter_conditions(context)["outputs"]
    assert len(extracted["constraints"]) == 1
    assert extracted["constraints"][0]["ast_path"] == [2]
    reduced = reduce_domain_equality_to_universal(**{
        key: extracted[key] for key in ("constraints", "description", "variable", "parameter", "goal", "context")
    })["outputs"]
    assert reduced["strict"] is False and reduced["relation"].rel_op == ">="


def test_polynomial_numerator_and_strict_solver_use_current_variable_parameter_names():
    value = candidate("(a*t+1)/sqrt(a*t^2-4*a*t+a+6)", parameter="a")
    value["original_text"] = "函数 g(t)=(a*t+1)/sqrt(a*t^2-4*a*t+a+6) 定义域为 ℝ，求 a 的范围。"
    value["root"]["definitions"] = ["g(t)=(a*t+1)/sqrt(a*t^2-4*a*t+a+6)"]
    value["root"]["goals"][0]["object"] = "g"
    context, state = execute(value)
    expected = sp.Interval.Ropen(0, 2)
    assert state["status"] == "method_complete", state.get("diagnostics")
    assert driver.export_values(state)["feasible_set"] == expected
    assert verify(value, TARGET, context, expected)["status"] == "verified"
    assert endpoint_check(value, TARGET, expected)["status"] == "passed"
