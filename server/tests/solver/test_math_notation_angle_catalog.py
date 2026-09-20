"""Packed angles bind only visible points; catalog examples preserve roles."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.batch_smoke import prepare_fixture
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_contract import expression_catalog
from shuxueshuo_server.problem_understanding.notation_semantics import compare, evaluate
from shuxueshuo_server.problem_understanding.smoke import build_request
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore


def candidate(**root):
    return {
        "root": root,
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "synthetic",
    }


@pytest.mark.parametrize("field", ["facts", "definitions", "goal", "state"])
@pytest.mark.parametrize("inherit", [False, True])
def test_compact_angle_matches_explicit_angle_without_changing_source(field, inherit):
    scope = {}
    if field in ("facts", "definitions"):
        scope[field] = ["angle(BDC)=2*angle(ABD)"]
    else:
        scope["goals"] = [{"kind": "find_value", "expression": "tan(angle(BDC))"}]
        if field == "state":
            scope["facts"] = ["angle(BAC)=angle(DAC)"]
    root = {"facts": ["quadrilateral(A,B,C,D)"]}
    if inherit:
        root["children"] = [scope]
    else:
        for key, values in scope.items():
            root.setdefault(key, []).extend(values)
    actual = candidate(**root)
    original = deepcopy(actual)
    expected = json.loads(
        json.dumps(actual)
        .replace("angle(BDC)", "angle(B,D,C)")
        .replace("angle(ABD)", "∠ABD")
        .replace("angle(BAC)", "∠BAC")
        .replace("angle(DAC)", "∠DAC")
    )
    assert compare(expected, actual)["ok"]
    assert compare(actual, expected)["ok"]
    report = NotationValidator().validate(actual)
    assert report.ok, report.issues
    assert actual == original
    assert not {"BDC", "ABD", "BAC", "DAC"} & {o["name"] for o in report.objects}


def test_direct_angle_expression_is_the_llm_facing_form_and_normalizes_to_right_angle():
    payload = candidate(
        facts=["quadrilateral(A,B,C,D)", "∠ABC=90°"]
    )
    report = NotationValidator().validate(payload)
    assert report.ok, report.issues
    assert payload["root"]["facts"][-1] == "∠ABC=90°"
    assert any(
        fact["rule_id"] == "right_angle_from_angle"
        for fact in report.normalization_report["derived_facts"]
    ) or any(
        fact.get("fact", [None])[0] == "="
        for fact in report.normalization_report["derived_facts"]
    )
    assert report.normalization_report["ruleset_hash"]


@pytest.mark.parametrize(
    "facts,expression",
    [
        ([], "angle(ABC)=45°"),
        (["A∈x_axis", "B∈x_axis"], "angle(ABC)=45°"),
        (["quadrilateral(A,B,C,D)", "ABC=(0,0)"], "angle(ABC)=45°"),
        (["A∈ℝ", "B∈x_axis", "C∈y_axis"], "angle(ABC)=45°"),
        (["quadrilateral(A,B,C,D)"], "∀A∈ℝ: angle(ABC)=45°"),
        (["quadrilateral(A,B,C,D)"], "∀ABC∈ℝ: angle(ABC)=45°"),
        (["quadrilateral(A,B,C,D)"], "angle(AB)=45°"),
        (["quadrilateral(A,B,C,D)"], "angle(ABCD)=45°"),
        (["quadrilateral(A,B,C,D)"], "angle(abc)=45°"),
    ],
)
def test_ambiguous_invisible_or_nonpoint_arguments_are_not_guessed(facts, expression):
    report = NotationValidator().validate(candidate(facts=[*facts, expression]))
    assert not report.ok
    assert any(i.get("source") == expression for i in report.issues)


def test_siblings_do_not_supply_angle_points_and_vertex_is_preserved():
    assert (
        not NotationValidator()
        .validate(
            candidate(
                children=[
                    {"facts": ["quadrilateral(A,B,C,D)"]},
                    {"facts": ["angle(ABC)=45°"]},
                ]
            )
        )
        .ok
    )

    def value(angle):
        return candidate(
            facts=["quadrilateral(A,B,C,D)"],
            goals=[{"kind": "find_value", "expression": angle}],
        )

    assert compare(value("angle(ABC)"), value("angle(CBA)"))["ok"]
    assert not compare(value("angle(ABC)"), value("angle(BAC)"))["ok"]


def test_few_shots_are_sent_and_compile_without_swapping_ratio_arguments(tmp_path):
    entry = next(
        e for e in expression_catalog()["expressions"] if e["id"] == "cut_ratio"
    )
    assert len(entry["few_shots"]) == 3
    fixture = prepare_fixture("function-quantifiers", tmp_path)
    request = build_request(fixture, ExtractionArtifactStore(tmp_path / "request"), [])
    sent = json.loads(request.prompt.user_prefix)["math_expression_catalog"]
    assert entry in sent["expressions"]
    for shot in entry["few_shots"]:
        actual = candidate(**shot["output"])
        report = NotationValidator().validate(actual)
        assert report.ok, report.issues
        assert compare(actual, actual)["ok"]
    expected = candidate(**entry["few_shots"][0]["output"])
    wrong = deepcopy(expected)
    wrong["root"]["facts"][1] = wrong["root"]["facts"][1].replace("UV,PQ", "PQ,UV")
    assert not compare(expected, wrong)["ok"]


def test_saved_deepseek_k_compiles_but_keeps_unresolved_semantic_failures():
    directory = (
        Path(__file__).parent
        / "fixtures/math-notation-v1/recorded-deepseek-k-20260916-153340"
    )
    for name, digest in json.loads((directory / "manifest.json").read_text()).items():
        assert sha256((directory / name).read_bytes()).hexdigest() == digest
    actual = json.loads((directory / "raw-response.txt").read_text())
    expected = json.loads((directory / "gold.json").read_text())
    report = NotationValidator().validate(actual)
    assert report.ok, report.issues
    assert not evaluate(
        expected, actual, json.loads((directory / "acceptance-policy.json").read_text())
    )["ok"]
