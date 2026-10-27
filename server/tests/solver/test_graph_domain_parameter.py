"""M6 match_domain recognition and discriminant-backed execution."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_one.function_domain_parameter import (
    inspect_match_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.graph_lesson.stage_three import driver, selection
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal, verify_goal_answer
from shuxueshuo_server.graph_lesson.stage_three.verification import endpoint_check, verify
from tests.solver.test_graph_stage_three_methods import finish

TARGET = "/root/goals/0"
METHOD = "method-domain-parameter"
Q22 = sp.Interval(1, sp.oo)


def candidate(expression="sqrt(k*x^2+2*x+1)", *, parameter="k", domain="ℝ", goal=None):
    target = goal or {
        "kind": "match_domain",
        "object": "f",
        "domain": domain,
        "symbol": parameter,
    }
    return {
        "original_text": (
            rf"函数 $f(x)={expression}$ 的定义域为 $\mathbb R$，求实数 ${parameter}$ 的取值范围。"
        ),
        "root": {
            "definitions": [f"f(x)={expression}"],
            "goals": [target],
        },
    }


def rows(value):
    result = extract_features(value)
    assert result["ok"], result
    return result["features"]


def recognized(value):
    return [report["type_id"] for report in evaluate_types(rows(value)) if report["status"] == "supported"]


def execute(value):
    context = build_context(value, TARGET)
    state = finish(
        driver.create_state(
            features=extract_features(value)["features"],
            context=context,
            method=METHOD,
            route_id="domain-parameter",
            branch="direct",
            target_ref=TARGET,
            run_id="domain-parameter-test",
            lesson_version="v1",
        )
    )
    if state["status"] == "method_complete":
        feasible = driver.export_values(state)["feasible_set"]
        state["verification"] = verify(value, TARGET, context, feasible)
        if state["verification"]["status"] == "verified":
            state = driver.append_endpoint(
                state, feasible, endpoint_check(value, TARGET, feasible)
            )
    return context, state


def test_q22_structure_and_type_recognition():
    value = candidate()
    frozen = deepcopy(value)
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is True
    assert description["parameter"] == "k"
    assert description["prescribed_domain_ast"] == ["real"]
    assert description["task"] == "match_domain"
    assert recognized(value) == ["type-function-domain"]
    assert value == frozen


def test_find_domain_never_selects_parameter_method():
    value = {
        "original_text": "求定义域",
        "root": {
            "definitions": ["f(x)=sqrt(x-1)/(x-2)"],
            "goals": [{"kind": "find_domain", "object": "f"}],
        },
    }
    result = selection.evaluate_goal(value, TARGET, rows(value), "type-function-domain")
    assert result["status"] == "no_verified_route"
    assert result["selection"]["branches"][0]["target"] == "method-domain-intersection"


def test_match_domain_never_selects_intersection_method():
    value = candidate()
    result = selection.evaluate_goal(value, TARGET, rows(value), "type-function-domain")
    assert result["status"] == "no_verified_route"
    assert result["selection"]["branches"][0]["target"] == "method-domain-parameter"


@pytest.mark.parametrize(
    "expression",
    [
        "sqrt(x-1)",  # no parameter
        "sqrt(k*x-1)/(x-2)",  # denominator
        "1/sqrt(k*x^2+1)",  # not pure sqrt
        "sqrt(k^2*x^2+1)",  # parameter degree >1 in a coefficient product path
    ],
)
def test_out_of_scope_parameter_structures_are_rejected(expression):
    value = candidate(expression)
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is False
    assert "type-function-domain" not in recognized(value)


def test_same_formula_find_domain_does_not_become_match_domain():
    value = candidate(goal={"kind": "find_domain", "object": "f"})
    assert "type-function-domain" not in recognized(value)


def test_q22_exact_parameter_range_via_discriminant_submethod():
    value = candidate()
    context, state = execute(value)
    assert state["status"] == "method_complete", state.get("diagnostics") or state["trajectory"]
    actual = driver.export_values(state)["feasible_set"]
    assert actual == Q22
    assert state["verification"]["status"] == "verified"
    assert endpoint_check(value, TARGET, actual)["status"] == "passed"
    answer = finalize_goal(value["root"]["goals"][0], actual)
    assert answer["kind"] == "match_domain"
    assert verify_goal_answer(value["root"]["goals"][0], actual, answer)["status"] == "set"
    methods = [step["method"] for step in state["trajectory"]["steps"]]
    assert "method-domain-parameter" in methods
    assert "method-discriminant" in methods
