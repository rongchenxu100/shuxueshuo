"""Goal identity and admission boundaries for the first domain-parameter route."""

from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_one.function_domain_parameter import (
    inspect_match_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_domain import (
    admitted_parameter,
)
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_semantics import (
    canonical,
    compare_roots,
)

TARGET = "/root/goals/0"


def candidate(expression="sqrt(k*x^2+2*x+1)", *, parameter="k", domain="ℝ"):
    return {
        "original_text": f"函数 f(x)={expression} 的定义域为 {domain}，求 {parameter} 的取值范围。",
        "root": {
            "definitions": [f"f(x)={expression}"],
            "goals": [
                {
                    "kind": "match_domain",
                    "object": "f",
                    "domain": domain,
                    "symbol": parameter,
                }
            ],
        },
    }


@pytest.mark.parametrize("domain", ["[0,∞)", "(-∞,0)", "(-∞,0]"])
def test_match_domain_comparison_preserves_the_prescribed_domain(domain):
    expected = candidate()["root"]
    actual = candidate(domain=domain)["root"]
    assert not compare_roots(expected, actual)["ok"]


def test_match_domain_comparison_preserves_the_sought_parameter():
    expression = "sqrt(k*x^2+a*x+1)"
    expected = candidate(expression, parameter="k")["root"]
    actual = candidate(expression, parameter="a")["root"]
    assert not compare_roots(expected, actual)["ok"]


def test_match_domain_canonical_goal_keeps_bound_parameter_and_domain():
    root = candidate()["root"]
    frozen = deepcopy(root)
    report = NotationValidator().validate_root(root)
    assert report.ok, report.issues
    goal = canonical(report)["root"]["goals"][0]
    assert goal["parameter"] == report.semantic["goals"][0]["parameter"]
    assert goal["domain"] == ["real"]
    assert root == frozen


def test_match_domain_comparison_still_accepts_consistent_parameter_renaming():
    expected = candidate()["root"]
    actual = candidate("sqrt(m*x^2+2*x+1)", parameter="m")["root"]
    assert compare_roots(expected, actual)["ok"]


@pytest.mark.parametrize(
    "expression",
    [
        "sqrt(k*x+1)",
        "sqrt(k*(x^2-x^2)+k*x+1)",
        "sqrt((k-k)*x^2+k*x+1)",
    ],
)
def test_already_linear_radicands_are_rejected_before_method_execution(expression):
    value = candidate(expression)
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is False
    assert description["reason"] == "domain.parameter_structure_unsupported"
    features = extract_features(value)
    assert features["ok"]
    assert not any(
        row["type_id"] == "type-function-domain" and row["status"] == "supported"
        for row in evaluate_types(features["features"])
    )
    assert not admitted_parameter(build_context(value, TARGET))


@pytest.mark.parametrize(
    "expression",
    ["sqrt(k*x^2+2*x+1)", "sqrt((k-1)*x^2+k*x+1)"],
)
def test_quadratics_that_degenerate_at_special_parameter_values_remain_admitted(expression):
    value = candidate(expression)
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is True
    assert description["has_quadratic_condition"] is True
    assert admitted_parameter(build_context(value, TARGET))


@pytest.mark.parametrize(
    "expression",
    [
        f"sqrt(k*x^2+{2**127}+{2**127})",
        f"sqrt({2**127}*k*x^2+{2**127}*k*x^2+1)",
        f"sqrt(({2**127}*x+{2**127})*(x+1)+k*x^2)",
    ],
)
def test_combining_bounded_terms_cannot_exceed_the_coefficient_budget(expression):
    description = inspect_match_domain_target(candidate(expression), TARGET)
    assert description["structure_supported"] is False
    assert description["reason"] == "domain.coefficient_limit"


def test_coefficients_at_the_bit_budget_remain_admitted():
    expression = f"sqrt(k*x^2+{2**127 - 1}+1)"
    description = inspect_match_domain_target(candidate(expression), TARGET)
    assert description["structure_supported"] is True
