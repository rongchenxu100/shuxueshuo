"""Named singleton-intersection shorthand requires a scoped uniqueness proof."""

import json
from copy import deepcopy
from hashlib import sha256
from itertools import product
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_normalization import (
    normalize_bound,
)
from shuxueshuo_server.problem_understanding.notation_semantics import compare, evaluate
from shuxueshuo_server.problem_understanding.notation_service import parse_candidate

RECORDED = (
    Path(__file__).parent / "fixtures/math-notation-v1/recorded-doubao-20260916-153340"
)


def candidate(facts=(), **fields):
    return {
        "root": {"facts": list(facts), **fields},
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "synthetic",
    }


@pytest.mark.parametrize(
    "point,reverse,field,inherit",
    product(("P", "D"), (False, True), ("facts", "definitions"), (False, True)),
)
def test_axis_intersection_definition_binds_point_and_preserves_original(
    point, reverse, field, inherit
):
    common = ["Γ:y=a*x^2+b*x+c", "a>0"]
    expression = f"x_axis∩axis(Γ)={point}" if reverse else f"{point}=axis(Γ)∩x_axis"
    scope = {
        field: [expression],
        "goals": [{"kind": "find_coordinates", "object": point}],
    }
    if inherit:
        actual = candidate(common, children=[scope])
    else:
        scope[field] = [*common, expression]
        actual = candidate(**scope)
    expected = deepcopy(actual)
    target = expected["root"]["children"][0] if inherit else expected["root"]
    target[field][-1] = f"{point}∈axis(Γ)∩x_axis"
    before = deepcopy(actual)
    assert compare(expected, actual)["ok"]
    assert compare(actual, expected)["ok"]
    assert actual == before
    report = NotationValidator().validate(actual)
    assert report.ok, report.issues
    assert any(
        p["rule"] == "point_intersection_definition"
        for p in report.payload()["normalization_proofs"]
    )
    assert any(
        p["rule"] == "quadratic_axis_unique" and p["premises"]
        for p in report.payload()["normalization_proofs"]
    )
    assert any(o["name"] == point and o["kind"] == "point" for o in report.objects)
    normalized = report.semantic_normalization
    assert (
        normalize_bound(normalized["root"], normalized["objects"])["root"]
        == normalized["root"]
    )


@pytest.mark.parametrize(
    "facts,expression",
    [
        ([], "P=x_axis∩y_axis"),
        (["parallelogram(A,B,C,D)"], "O=segment(A,C)∩segment(B,D)"),
        (["A=(1,3)", "B=(5,3)", "C=(3,1)", "D=(3,5)"], "P=segment(A,B)∩segment(C,D)"),
    ],
)
def test_other_certified_unique_intersections_use_same_rule(facts, expression):
    equivalent = expression.replace("=", "∈", 1)
    assert compare(candidate([*facts, expression]), candidate([*facts, equivalent]))[
        "ok"
    ]


@pytest.mark.parametrize(
    "facts,expression",
    [
        (["Γ:y=a*x^2+b*x+c"], "P=axis(Γ)∩x_axis"),
        (["Γ:y=a*x^2+b*x+c", "a>=0"], "P=axis(Γ)∩x_axis"),
        (["Γ:y=x^2"], "P=axis(Γ)∩y_axis"),
        (["Γ:y=x^2-1"], "P=Γ∩x_axis"),
        ([], "P=line(A,B)∩line(C,D)"),
        ([], "P=x_axis∩x_axis"),
        (["A=(1,1)", "B=(5,1)", "C=(1,3)", "D=(5,3)"], "P=line(A,B)∩line(C,D)"),
        (["A=(1,3)", "B=(5,3)", "C=(3,1)", "D=(3,2)"], "P=segment(A,B)∩segment(C,D)"),
        (["A=(1,3)", "B=(1,3)", "C=(3,1)", "D=(3,5)"], "P=line(A,B)∩line(C,D)"),
        (["square(A,B,C,D)"], "P=ray(A,C)∩line(B,D)"),
    ],
)
def test_uncertain_nonunique_or_out_of_range_intersections_fail_with_source(
    facts, expression
):
    report = NotationValidator().validate(candidate([*facts, expression]))
    assert not report.ok
    issue = next(
        i for i in report.issues if "intersection_not_proven_unique" in i["message"]
    )
    assert issue["source"] == expression
    assert issue["path"] == f"r.facts[{len(facts)}]"


def test_types_and_siblings_are_never_guessed_or_rebound():
    for facts in (["P∈ℝ", "P=x_axis∩y_axis"], ["P:y=x^2", "P=x_axis∩y_axis"]):
        assert not NotationValidator().validate(candidate(facts)).ok
    siblings = candidate(
        children=[
            {"facts": ["P=x_axis∩y_axis"]},
            {"goals": [{"kind": "find_coordinates", "object": "P"}]},
        ]
    )
    assert not NotationValidator().validate(siblings).ok
    siblings = candidate(
        children=[{"definitions": ["Γ:y=x^2"]}, {"facts": ["P=axis(Γ)∩x_axis"]}]
    )
    assert not NotationValidator().validate(siblings).ok


def test_or_premises_do_not_prove_unique_intersection():
    for known in ["a>0 ∨ a=0", "a>0 ∨ a<0"]:
        report = NotationValidator().validate(
            candidate(["Γ:y=a*x^2", known, "P=axis(Γ)∩x_axis"])
        )
        assert not report.ok  # No proof is borrowed from a disjunct.


def test_declaration_order_is_independent_and_child_errors_keep_their_source():
    a = candidate(["P=axis(Δ)∩x_axis", "Δ:y=2*x^2+1"])
    b = candidate(["Δ:y=2*x^2+1", "P∈axis(Δ)∩x_axis"])
    assert compare(a, b)["ok"]
    expression = "P=axis(Δ)∩x_axis"
    report = NotationValidator().validate(
        candidate(["Δ:y=a*x^2"], children=[{"facts": [expression]}])
    )
    assert not report.ok
    assert report.issues[0]["path"] == "r.c0.facts[0]"
    assert report.issues[0]["source"] == expression


def test_shorthand_inside_logic_and_at_keeps_the_condition():
    common = ["Γ:y=x^2+1", "P∈x_axis"]
    a = candidate([*common, "P=axis(Γ)∩x_axis ∨ x(P)=2"])
    b = candidate([*common, "P∈axis(Γ)∩x_axis ∨ x(P)=2"])
    assert compare(a, b)["ok"]
    a = candidate(
        common,
        goals=[{"kind": "find_coordinates", "object": "P", "at": "P=axis(Γ)∩x_axis"}],
    )
    b = deepcopy(a)
    b["root"]["goals"][0]["at"] = "P∈axis(Γ)∩x_axis"
    assert compare(a, b)["ok"]
    b["root"]["goals"][0].pop("at")
    assert not compare(a, b)["ok"]


@pytest.mark.parametrize(
    "entry",
    json.loads((RECORDED / "manifest.json").read_text())["cases"],
    ids=lambda r: r["case"],
)
def test_original_doubao_responses_replay_six_of_seven_without_editing(entry):
    for name, digest in entry["files"].items():
        assert sha256((RECORDED / name).read_bytes()).hexdigest() == digest
    case = entry["case"]
    raw = (RECORDED / (case + ".txt")).read_text()
    gold = json.loads((RECORDED / (case + ".gold.json")).read_text())
    policy_file = RECORDED / (case + ".policy.json")
    result = evaluate(
        gold,
        json.loads(raw),
        json.loads(policy_file.read_text()) if policy_file.exists() else None,
    )
    assert result["ok"] is entry["expected_offline_passed"], result
    if case in ("tj-2026-heping-ermo-25", "tj-2026-nankai-yimo-25"):
        parsed = parse_candidate(
            raw,
            problem_id=case,
            source_sha256="0" * 64,
            registry_snapshot="0" * 64,
            registered_families=[gold["family_id"]],
        )
        assert parsed["contract_valid"] and not parsed["continuation"]["blocked"]
