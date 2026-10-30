"""Published answers retain typed existence states and exact finite values."""

import json
from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import Draft202012Validator, ValidationError

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal


@pytest.fixture(params=["result-v1", "route-v1", "route-v2"])
def answer_validator(request):
    path = ROOT / f"internal/schemas/graph-stage-three-{request.param}.schema.json"
    schema = json.loads(path.read_text())
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/goalAnswer"})


def test_function_range_answer_has_a_function_object(answer_validator):
    answer = finalize_goal({'kind': 'find_range', 'object': 'f'}, sp.Interval(1, 5))
    answer_validator.validate(answer)
    with pytest.raises(ValidationError):
        answer_validator.validate({**answer, 'kind': 'find_domain'})


@pytest.mark.parametrize("kind,feasible", [
    ("find_range", sp.S.EmptySet),
    ("find_minimum", sp.Interval(-sp.Rational(5, 2), sp.oo)),
    ("find_maximum", sp.Interval(-sp.oo, sp.Rational(5, 2))),
    ("find_minimum", sp.Interval.open(0, 1)),
    ("find_maximum", sp.Interval.open(0, 1)),
    ("find_minimum", sp.S.Reals),
    ("find_maximum", sp.S.Reals),
    ("find_minimum", sp.S.EmptySet),
    ("find_maximum", sp.S.EmptySet),
])
def test_each_goal_answer_state_has_a_valid_wire_shape(answer_validator, kind, feasible):
    answer_validator.validate(finalize_goal({"kind": kind}, feasible))


@pytest.mark.parametrize("mutation", ["no_exact", "missing_value", "wrong_kind", "extra_bound", "wrong_unbounded"])
def test_malformed_goal_answer_is_rejected_before_publishing(answer_validator, mutation):
    answer = deepcopy(finalize_goal({"kind": "find_minimum"}, sp.Interval(0, 1)))
    if mutation == "no_exact":
        del answer["value"]["exact"]
    elif mutation == "missing_value":
        del answer["value"]
    elif mutation == "wrong_kind":
        answer["kind"] = "find_range"
    elif mutation == "extra_bound":
        answer["bound"] = deepcopy(answer["value"])
    else:
        answer = {"kind": "find_minimum", "status": "unbounded_above"}
    with pytest.raises(ValidationError):
        answer_validator.validate(answer)
