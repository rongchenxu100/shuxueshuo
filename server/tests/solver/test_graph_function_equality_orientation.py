"""Replay Q19's first photo representation failure, without new model calls.

The retained public candidate came from bbfef9d71384 after JSON repair. That
historical run stopped at code_gap before source review; these are local IR and
recognition regressions, not a successful photograph/source-review recording.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.repair_authority import repair_violations
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search.extraction import SearchStageOneContract
from tests.solver.test_graph_function_equality_ir import identity
from tests.solver.test_graph_function_equality_q19_ir import compiled
from tests.solver.test_graph_function_equality_recognition import envelope, feature

FIXTURE = Path(__file__).parent / "fixtures/function-equality/q19-first-photo-reversed-shared-public-candidate.json"


def public_candidate():
    return json.loads(FIXTURE.read_text())


def mathematical(public):
    return {key: deepcopy(public[key]) for key in ("original_text", "root")}


def forward(public, labels="ABCD"):
    value = deepcopy(public)
    for option in value["root"]["goals"][0]["options"]:
        if option["label"] in labels:
            option["left"], option["right"] = option["right"], option["left"]
    return value


def test_real_reversed_shared_references_compile_without_rewriting_the_candidate():
    public = public_candidate()
    frozen = deepcopy(public)
    assert all(option["left"] == "local:candidate" and option["right"] == "shared:baseline"
               for option in public["root"]["goals"][0]["options"])
    report = SearchStageOneContract().parse(json.dumps(public), problem_id="q19-regression", source_hash="fixture", registry=None, store=None)
    assert report["contract_valid"], report
    goal = compiled(mathematical(public))
    for index, option in enumerate(goal["options"]):
        assert option["left"]["function_ref"] == "/root/goals/0/shared_functions/baseline"
        assert option["left"]["source_ref"] == "/root/goals/0/shared_functions/0/definition"
        assert option["right"]["function_ref"] == f"/root/goals/0/options/{option['option_id']}/functions/candidate"
        assert option["right"]["source_ref"] == f"/root/goals/0/options/{index}/functions/0/definition"
        assert option["text"] == public["root"]["goals"][0]["options"][index]["text"]
    assert len({option["right"]["function_ref"] for option in goal["options"]}) == 4
    assert public == frozen


@pytest.mark.parametrize("labels", ["ABCD", "AC", "B"])
def test_each_option_orientation_has_the_same_compiled_roles_features_and_content_identity(labels):
    reversed_source = public_candidate()
    changed = forward(reversed_source, labels)
    assert revision(reversed_source) != revision(changed)  # Raw provenance remains distinct.
    assert compiled(mathematical(reversed_source)) == compiled(mathematical(changed))
    assert identity(reversed_source) == identity(changed)
    original_feature = feature(envelope(mathematical(reversed_source)), "function_comparison")["value"]
    changed_feature = feature(envelope(mathematical(changed)), "function_comparison")["value"]
    assert original_feature == changed_feature
    assert original_feature["structure_supported"]


def test_real_reversed_candidate_reaches_program_recognition(tmp_path):
    value = envelope(mathematical(public_candidate()))
    result = run_result(value, tmp_path / "q19-reversed", verify=True)
    assert result["status"] == "completed"
    goal, = result["goals"]
    assert goal["primary"] == "type-function-equality" and goal["primary_source"] == "program"
    assert not goal["d1"]["diagnostics"]
    assert result["llm"]["new_semantic_calls"] == 0


@pytest.mark.parametrize("mutation", ["both_shared", "both_local", "cross_option", "unused_local", "second_shared"])
def test_symmetric_baseline_acceptance_does_not_relax_scope_completeness(mutation):
    value = mathematical(public_candidate())
    goal = value["root"]["goals"][0]
    option = goal["options"][0]
    if mutation == "both_shared":
        option["left"] = "shared:baseline"
    elif mutation == "both_local":
        option["right"] = "local:candidate"
    elif mutation == "cross_option":
        option["left"] = "B:local:candidate"
    elif mutation == "unused_local":
        option["functions"].append({"id": "extra", "definition": "g(x)=x"})
    else:
        goal["shared_functions"].append({"id": "extra", "definition": "g(x)=x"})
        goal["options"][1]["right"] = "shared:extra"
    assert not validate_candidate(value)["contract_valid"]


def test_normalized_roles_do_not_expand_source_repair_authority():
    before = mathematical(public_candidate())
    after = deepcopy(before)
    after["root"]["goals"][0]["options"][0]["functions"][0]["definition"] = "f(x)=x^2+abs(x^2+2)"
    grant = [{"stage": "review", "action": "repair", "code": "wrong_expression",
              "path": "/root/goals/0/options/0/functions/0/definition"}]
    assert not repair_violations(before, after, grant)
    option = after["root"]["goals"][0]["options"][0]
    option["left"], option["right"] = option["right"], option["left"]
    assert repair_violations(before, after, grant)
