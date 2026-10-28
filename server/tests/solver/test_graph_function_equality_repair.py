"""Constructed Q20 extraction repairs through the real offline search workflow.

The provider responses below are authored probes, not new photo-review evidence.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from _math_notation_test_support import Recorded

from shuxueshuo_server.graph_lesson.stage_one.function_equality import (
    inspect_comparison_target,
)
from shuxueshuo_server.graph_lesson.stage_one.repair_authority import repair_violations
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

FIXTURE = Path(__file__).parent / "fixtures/function-equality/q20-public-candidate.json"
IMAGE = Path(__file__).parents[1] / "search/fixtures/function-equality/q20-recorded-20261028/question.png"
TARGET = "/root/goals/0"
CONFIRMED = {"status": "confirmed", "findings": []}


class Sequence(Recorded):
    def __init__(self, *responses):
        super().__init__("")
        self.responses = list(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected additional provider call")
        self.text = json.dumps(self.responses.pop(0), ensure_ascii=False)
        return super().complete(request)


def candidate():
    return json.loads(FIXTURE.read_text())


def run(tmp_path, provider):
    request = build_search_request(IMAGE.read_bytes(), ExtractionArtifactStore(tmp_path / "inputs"))
    return run_workflow(request, provider, tmp_path / "workflow", [],
                        problem_id="q20-offline-repair", contract_adapter=SearchStageOneContract())


def diagnostics(value):
    contract = SearchStageOneContract()
    parsed = contract.parse(json.dumps(value), problem_id="q20", source_hash="source", registry=[], store=None)
    return contract.diagnose(parsed, value)


ERRORS = [
    ("dangling_left", "comparison.unresolved_function_ref", TARGET + "/options/0/left"),
    ("dangling_right", "comparison.unresolved_function_ref", TARGET + "/options/0/right"),
    ("duplicate_id", "comparison.duplicate_option", TARGET + "/options/1/id"),
    ("duplicate_label", "comparison.duplicate_option", TARGET + "/options/1/label"),
    ("duplicate_function_id", "comparison.duplicate_function_id", TARGET + "/options/0/functions/1/id"),
]


def damaged(error):
    value = candidate()
    options = value["root"]["goals"][0]["options"]
    if error == "dangling_left":
        options[0]["left"] = "local:typo"
    elif error == "dangling_right":
        options[0]["right"] = "local:typo"
    elif error == "duplicate_id":
        options[1]["id"] = options[0]["id"]
    elif error == "duplicate_label":
        options[1]["label"] = options[0]["label"]
    elif error == "duplicate_function_id":
        options[0]["functions"][1]["id"] = options[0]["functions"][0]["id"]
    else:
        raise AssertionError(error)
    return value


@pytest.mark.parametrize("assignment", ["=", ":=", "≔", "≡"])
def test_parser_supported_assignment_spellings_reach_source_review(tmp_path, assignment):
    value = candidate()
    definition = f"g(x){assignment}(sqrt(x))^2"
    value["root"]["goals"][0]["options"][0]["functions"][1]["definition"] = definition
    provider = Sequence(value, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert result["source_reviewed"] is True
    assert provider.calls == 2
    assert [event["stage"] for event in result["events"]] == ["extract", "review"]
    assert result["candidate"] == value
    inspected = inspect_comparison_target(value, TARGET)
    original = inspect_comparison_target(candidate(), TARGET)
    assert inspected["structure_supported"] is True
    right = inspected["options"][0]["right"]
    assert right["expression"] == "(sqrt(x))^2"
    assert right["expression_ast"] == original["options"][0]["right"]["expression_ast"]
    assert right["expression_latex"] == r"\left(\sqrt{x}\right)^{2}"
    assert json.loads(provider.requests[1].prompt.user_prefix)["candidate"] == value


@pytest.mark.parametrize("error,code,path", ERRORS)
def test_local_bookkeeping_error_repairs_then_reviews_the_corrected_candidate(tmp_path, error, code, path):
    incorrect, correct = damaged(error), candidate()
    provider = Sequence(incorrect, correct, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert result["source_reviewed"] is True
    assert result["candidate"] == correct
    assert provider.calls == 3
    assert [event["stage"] for event in result["events"]] == ["extract", "repair", "review"]
    repair = json.loads(provider.requests[1].prompt.user_prefix)
    assert repair["base_candidate"] == incorrect
    compile_diagnostics = [item for item in repair["diagnostics"] if item["stage"] == "compile"]
    assert [(item["code"], item["path"], item["action"]) for item in compile_diagnostics] == [(code, path, "repair")]
    assert json.loads(provider.requests[2].prompt.user_prefix)["candidate"] == correct


@pytest.mark.parametrize("error,code,path", ERRORS)
def test_local_id_repair_cannot_change_math_or_polarity_in_the_same_goal(tmp_path, error, code, path):
    incorrect, correct = damaged(error), candidate()
    changed = deepcopy(correct)
    goal = changed["root"]["goals"][0]
    goal["options"][0]["functions"][0]["definition"] = "f(x)=x+1"
    goal["options"][2]["functions"][1]["definition"] = "g(x)=abs(x+1)"
    goal["select_relation"] = "different"
    provider = Sequence(incorrect, changed, correct, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert result["candidate"] == correct
    assert provider.calls == 4
    rejected = result["events"][1]
    assert rejected["stage"] == "repair" and rejected["adopted"] is False
    assert {item["path"] for item in rejected["repair_rejected"]} >= {
        TARGET + "/options/0/functions/0/definition",
        TARGET + "/options/2/functions/1/definition",
        TARGET + "/select_relation",
    }
    assert json.loads(provider.requests[2].prompt.user_prefix)["base_candidate"] == incorrect
    assert json.loads(provider.requests[3].prompt.user_prefix)["candidate"] == correct
    reordered = deepcopy(correct)
    reordered["root"]["goals"][0]["options"][:2] = reversed(reordered["root"]["goals"][0]["options"][:2])
    assert repair_violations(incorrect, reordered, diagnostics(incorrect))


def test_ambiguous_unused_function_does_not_gain_a_whole_option_repair_grant(tmp_path):
    value = candidate()
    value["root"]["goals"][0]["options"][0]["right"] = "local:f"
    provider = Sequence(value)
    result = run(tmp_path, provider)
    assert result["status"] == "code_gap"
    assert provider.calls == 1
    assert [(item["code"], item["action"]) for item in result["diagnostics"]] == [
        ("comparison.unused_local_definition", "code_gap"),
    ]
