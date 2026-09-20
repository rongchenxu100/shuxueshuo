"""Candidate safeguards migrated from the retired structured-fact output path."""

import json
from copy import deepcopy

import pytest
from _math_notation_test_support import Recorded

from shuxueshuo_server.problem_understanding.batch_smoke import prepare_fixture
from shuxueshuo_server.problem_understanding.candidate_common import validate_match
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.notation_service import parse_candidate
from shuxueshuo_server.problem_understanding.observation import observation_view
from shuxueshuo_server.problem_understanding.smoke import run


def parse(raw):
    return parse_candidate(
        raw,
        problem_id="test",
        source_sha256="0" * 64,
        registry_snapshot="0" * 64,
        registered_families=["Known"],
    )


@pytest.mark.parametrize(
    "finish,fail,expected",
    [
        ("stop", False, True),
        ("length", False, False),
        ("stop", True, False),
    ],
)
def test_single_call_audit_and_reentry_refuses_payment(
    tmp_path, finish, fail, expected
):
    fixture = prepare_fixture("function-quantifiers", tmp_path)
    provider = Recorded((fixture / "gold.json").read_text(), finish, fail)
    output = tmp_path / "run"
    result = run(fixture, output, provider, [])
    assert result["passed"] is expected and provider.calls == 1
    assert not result["solver_ready"] and not result["source_reviewed"]
    with pytest.raises(FileExistsError):
        run(fixture, output, provider, [])
    assert provider.calls == 1 and (output / "frozen.json").exists()


def test_acceptance_freezes_policy_without_hiding_strict_failure(tmp_path):
    fixture = prepare_fixture("k-quad", tmp_path)
    actual = json.loads((fixture / "gold.json").read_text())
    policy = json.loads((fixture / "acceptance-policy.json").read_text())
    for entry in policy["allowed_omissions"]:
        scope = actual["root"]
        for index in entry["scope"]:
            scope = scope["children"][index]
        scope["facts"].remove(entry["fact"])
    output = tmp_path / "run"
    result = run(fixture, output, Recorded(json.dumps(actual)), [])
    assert result["passed"] and not result["strict_semantics_passed"]
    assert len(result["accepted_omissions"]) == len(policy["allowed_omissions"])
    assert result["continuation"]["blocked"]
    assert (
        json.loads((output / "frozen.json").read_text())["acceptance_policy"] == policy
    )
    assert not json.loads((output / "diff.json").read_text())["ok"]


@pytest.mark.parametrize(
    "raw", ["{", '{"root":', "{}junk", '{"a":1,"a":2}', '{"a":NaN}', "[]"]
)
def test_damaged_json_never_salvaged(raw):
    result = parse(raw)
    assert not result["contract_valid"] and not result["objects"]


@pytest.mark.parametrize(
    "updates",
    [
        {"match_status": "matched", "family_id": "Unknown"},
        {"match_status": "unmatched", "family_id": "Known"},
        {"match_reason": ""},
        {"match_reason": " "},
        {"match_reason": "x" * 4097},
        {"match_status": "x"},
        {"family_id": []},
    ],
)
def test_invalid_match_declarations_remain_rejected(updates):
    value = {
        "root": {},
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "test",
        **updates,
    }
    assert not validate_match(value, ["Known"])["ok"]
    assert not parse(json.dumps(value))["contract_valid"]


@pytest.mark.parametrize("status,family", [("matched", "Known"), ("unmatched", None)])
def test_match_never_promotes_candidate_to_solver_readiness(status, family):
    result = parse(
        json.dumps(
            {
                "root": {},
                "match_status": status,
                "family_id": family,
                "match_reason": "test",
            }
        )
    )
    assert result["contract_valid"]
    assert not result["solver_ready"] and not result["source_reviewed"]


def test_observation_projection_preserves_evidence_without_mutation():
    observation = {
        "pages": [{"page_id": "p1"}, {"page_id": "p2"}],
        "text_spans": [
            {"page_id": "p1", "text": "分母", "origin": "printed", "reading_order": 1},
            {"page_id": "p2", "text": "批注", "origin": "mixed", "reading_order": 0},
        ],
        "formulas": [
            {"page_id": "p1", "latex": "x+1", "source_observation_ids": ["a"]},
            {"page_id": "p1", "latex": "x+1", "source_observation_ids": ["a"]},
            {"page_id": "p1", "latex": "x-1", "source_observation_ids": ["a"]},
        ],
        "occlusions": [{"page_id": "p2"}],
    }
    before = deepcopy(observation)
    view, aliases = observation_view(observation)
    assert observation == before and revision(observation) == revision(before)
    assert view["pages"][0]["lines"] == [{"text": "分母"}]
    assert len(view["pages"][0]["formula_candidates"]) == 2
    assert "不同公式候选" in view["pages"][0]["notes"][0]
    assert "需看图核查" in view["pages"][1]["lines"][0]["note"]
    assert view["pages"][1]["notes"] == ["存在遮挡区域"]
    assert aliases == [
        {"page": 1, "source_page_id": "p1"},
        {"page": 2, "source_page_id": "p2"},
    ]
