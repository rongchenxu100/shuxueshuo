"""Parameter extrema use the quantified structure without solving the extremum."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_two.contracts import FEATURE_VALUES_PATH
from shuxueshuo_server.graph_lesson.stage_two.recognition import (
    build_d2,
    evaluate_types,
)
from shuxueshuo_server.graph_lesson.stage_two.verification import verify_amgm
from tests.solver.test_graph_stage_one_features import FUNCTION_GOAL_FEATURES

QUADRATIC = "type-quantified-quadratic"
AMGM = "type-amgm-quantified"
PARAMETER = "type-parameter-quadratic-solve"


def candidate(kind, fact, symbol="a"):
    return {"original_text": f"{fact}，求 {symbol} 的最值。", "root": {
        "facts": [fact], "goals": [{"kind": kind, "expression": symbol}],
    }}


@pytest.mark.parametrize("kind", ["find_minimum", "find_maximum"])
@pytest.mark.parametrize("quantifier", ["∀", "∃"])
@pytest.mark.parametrize("fact,symbol,branch", [
    ("x∈(0,1/2]:x^2+a*x+1>=0", "a", "bound-quadratic"),
    ("m∈[1,3]:(x^2-x+1)*m-6<0", "x", "variable-swap"),
])
def test_parameter_extrema_keep_kind_and_quadratic_branch(kind, quantifier, fact, symbol, branch):
    value = candidate(kind, quantifier + fact, symbol)
    before = deepcopy(value)
    extracted = extract_features(value)
    assert extracted["ok"]
    assert all(f["status"] == ("unknown" if f["feature_id"] in FUNCTION_GOAL_FEATURES else "known")
               for f in extracted["features"])
    goal = next(f for f in extracted["features"] if f["feature_id"] == "goal")
    assert goal["value"] == {"kind": kind, "symbol": symbol}
    schema = json.loads(FEATURE_VALUES_PATH.read_text())
    Draft202012Validator({**schema, "$ref": "#/$defs/goal"}).validate(goal["value"])
    reports = evaluate_types(extracted["features"])
    assert [r["type_id"] for r in reports if r["status"] == "supported"] == [QUADRATIC]
    quadratic = next(r for r in reports if r["type_id"] == QUADRATIC)
    assert quadratic["status"] == "supported"
    assert [b["branch_id"] for b in quadratic["branches"] if b["status"] == "supported"] == [branch]
    assert next(r for r in reports if r["type_id"] == PARAMETER)["status"] == "conflict"
    assert next(r for r in reports if r["type_id"] == AMGM)["status"] == "unknown"
    assert next(o for o in build_d2(reports, QUADRATIC)["options"] if o["role"] == "primary")["type_id"] == QUADRATIC
    # Type recognition makes no claim that a minimum/maximum exists or is attained.
    assert value == before


@pytest.mark.parametrize("fact", ["∀x∈ℝ:a*x+1>=0", "∃x∈ℝ:x^2=a", "∃x∈ℝ:x^2!=a"])
def test_extremum_does_not_turn_nonquadratic_or_noninequality_into_supported(fact):
    rows = extract_features(candidate("find_minimum", fact))["features"]
    assert next(r for r in evaluate_types(rows) if r["type_id"] == QUADRATIC)["status"] == "conflict"


def test_conditional_extremum_structure_remains_unknown():
    rows = extract_features(candidate("find_minimum", "∀x∈[1/a,2]:x^2>=a"))["features"]
    assert any(f["status"] == "conditional" for f in rows)
    assert next(r for r in evaluate_types(rows) if r["type_id"] == QUADRATIC)["status"] == "unknown"


@pytest.mark.parametrize("kind", ["find_minimum", "find_maximum"])
def test_verified_amgm_bound_is_available_for_parameter_extrema(kind):
    value = candidate(kind, "∀x∈ℝ:-x^2+2*x+3<=a")
    rows = extract_features(value)["features"]
    verification = verify_amgm(value, "/root/goals/0", rows, enabled=True)
    assert verification["status"] == "supported"
    assert verification["variables"]["goal"] == {"kind": kind, "symbol": "a"}
    reports = evaluate_types(rows, verification)
    assert {r["type_id"] for r in reports if r["status"] == "supported"} == {QUADRATIC, AMGM}
    # This certifies a bound on the quantified expression, not a solution for a.
    assert not any("answer" in step for step in verification["steps"])
