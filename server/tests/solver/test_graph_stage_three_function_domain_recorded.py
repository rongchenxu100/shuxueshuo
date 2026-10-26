"""Real photo replay plus independent holdouts through the durable shared runner."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.search.lesson import run_stage_two
from shuxueshuo_server.search.stage_three import run_stage_three
from tests.search.function_domain_recording import revalidate_recording


def execute(tmp_path, result):
    def forbidden(*args, **kwargs):
        raise AssertionError("recognition and exact execution must not call a model")

    stage_two = run_stage_two(tmp_path, result, provider=forbidden,
                              unsupported_root=tmp_path / "unsupported")
    assert stage_two["status"] == "completed", stage_two
    assert stage_two["goals"][0]["primary"] == "type-function-domain"
    directory = tmp_path / "stage-two-1"
    result = run_stage_three(directory)
    assert result["status"] == "completed", result
    (goal,) = result["goals"]
    assert goal["status"] == "solved", goal
    (route,) = goal["routes"]
    assert route["status"] == "verified", route
    assert route["method"] == "method-domain-intersection"
    return route, open_store(directory / "stage-three").snapshot()


def test_real_photo_replay_solves_and_publishes_interactions(tmp_path):
    route, snapshot = execute(tmp_path, revalidate_recording())
    assert decode_value(route["feasible_set_exact"]) == sp.Union(sp.Interval.Ropen(1, 2), sp.Interval.open(2, sp.oo))
    assert snapshot["goals"]["/root/goals/0"]["status"] == "solved"
    assert snapshot["math_steps"] and snapshot["handoffs"]
    assert snapshot["interactions"]
    assert all(row["status"] != "pending" for row in snapshot["interaction_states"])
    assert not any(chunk.get("diagnostics") for chunk in snapshot["interactions"])


@pytest.mark.parametrize(("definition", "input_domain", "expected"), [
    ("h(t)=sqrt(7-2*t)/(3*t+6)", None,
     sp.Union(sp.Interval.open(-sp.oo, -2), sp.Interval.Lopen(-2, sp.Rational(7, 2)))),
    ("p(z)=sqrt(z+3)/(2*z+6)", None, sp.Interval.open(-3, sp.oo)),
    ("r(u)=sqrt(2*u+5)+1/sqrt(11-3*u)", "[-4,5)",
     sp.Interval.Ropen(sp.Rational(-5, 2), sp.Rational(11, 3))),
])
def test_independent_coefficient_variable_and_interval_holdouts(tmp_path, definition, input_domain, expected):
    goal = {"kind": "find_domain", "object": definition.split("(")[0]}
    if input_domain is not None:
        goal["input_domain"] = input_domain
    limit = f"，输入另限于 ${input_domain}$" if input_domain else ""
    candidate = {"original_text": f"求函数 ${definition}$ 的定义域{limit}。",
                 "root": {"definitions": [definition], "facts": [], "goals": [goal]}}
    extracted = candidate_features(candidate)
    assert extracted["ok"], extracted
    result = {"status": "reviewed_candidate", "source_reviewed": True,
              "candidate": candidate, "features": extracted["features"], "features_ok": True}
    route, _ = execute(tmp_path, result)
    assert decode_value(route["feasible_set_exact"]) == expected
