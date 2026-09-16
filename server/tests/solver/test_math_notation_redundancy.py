"""Object mentions and coordinate-axis definitions must not change extraction."""

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

RECORDED = Path(__file__).parent / "fixtures/math-notation-v1/recorded-20260916-135634"
MANIFEST = json.loads((RECORDED / "manifest.json").read_text())


def candidate(facts=(), **fields):
    return {
        "root": {"facts": list(facts), **fields},
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "synthetic",
    }


def equivalent(a, b):
    before = deepcopy((a, b))
    assert compare(a, b)["ok"]
    assert compare(b, a)["ok"]
    assert (a, b) == before


@pytest.mark.parametrize(
    "field,count,reverse", product(("facts", "definitions"), (1, 3), (False, True))
)
def test_standalone_segments_are_typed_mentions_not_constraints(field, count, reverse):
    base = candidate(["A=(0,0)", "B=(2,0)", "AB=2"])
    actual = deepcopy(base)
    actual["root"].setdefault(field, []).extend(
        ["segment(B,A)" if reverse else "segment(A,B)"] * count
    )
    equivalent(base, actual)
    report = NotationValidator().validate(actual)
    assert any(f[0] == "object_declaration" for f in report.semantic["facts"])
    assert all(
        f[0] != "object_declaration"
        for f in report.semantic_normalization["root"]["facts"]
    )
    assert (
        sum(
            p["rule"] == "standalone_segment_declaration"
            for p in report.semantic_normalization["proofs"]
        )
        == count
    )


def test_segment_mentions_still_establish_endpoints_and_keep_relations():
    actual = candidate(["segment(A,B)", "AB=3"])
    report = NotationValidator().validate(actual)
    assert report.ok and {o["name"] for o in report.objects} == {"A", "B"}
    assert not compare(actual, candidate(["segment(A,B)"]))["ok"]
    assert not compare(candidate(["P∈segment(A,B)"]), candidate(["P∈ray(A,B)"]))["ok"]
    siblings = candidate(
        children=[
            {"facts": ["segment(A,B)"]},
            {"goals": [{"kind": "find_coordinates", "object": "A"}]},
        ]
    )
    assert not NotationValidator().validate(siblings).ok


def test_unused_mentions_do_not_obstruct_aliases_but_live_endpoints_remain():
    equivalent(candidate(["Γ:y=x^2"]), candidate(["Δ:y=x^2", "segment(A,B)"]))
    report = NotationValidator().validate(candidate(["segment(A,B)", "x(A)=1"]))
    assert {o["name"] for o in report.objects} == {"A", "B"}
    assert {o["name"] for o in report.semantic_normalization["objects"]} == {"A"}
    assert not compare(candidate([]), candidate(["segment(A,B)", "x(A)=1"]))["ok"]


@pytest.mark.parametrize(
    "expression",
    [
        "segment(A,2)",
        "segment(A)",
        "segment(A,B,C)",
        "segment(A,B) ∨ A∈x_axis",
        "1+2",
        "x(A)",
        "unknown(A,B)",
    ],
)
def test_other_invalid_facts_are_never_silently_deleted(expression):
    assert not NotationValidator().validate(candidate([expression])).ok


@pytest.mark.parametrize(
    "axis,coordinate,point,reverse",
    product(("x_axis", "y_axis"), ("tuple", "property"), ("P", "T"), (False, True)),
)
def test_axis_membership_normalizes_to_zero_coordinate(
    axis, coordinate, point, reverse
):
    x, y = ("n", "0") if axis == "x_axis" else ("0", "n")
    base = (
        [f"{point}=({x},{y})"]
        if coordinate == "tuple"
        else [f"segment({point},Q)", f"{'y' if axis == 'x_axis' else 'x'}({point})=0"]
    )
    actual = [*base, f"{point}∈{axis}"]
    equivalent(
        candidate(base), candidate(list(reversed(actual)) if reverse else actual)
    )
    report = NotationValidator().validate(candidate(actual))
    assert any(
        p["rule"] == "coordinate_axis_membership"
        for p in report.semantic_normalization["proofs"]
    )
    assert any(
        p["rule"] == "duplicate_relation"
        for p in report.semantic_normalization["proofs"]
    )


def test_axes_preserve_nonzero_coordinates_wrong_axis_and_branch_conditions():
    for coord, axis in [("(n,1)", "x_axis"), ("(1,n)", "y_axis"), ("(n,0)", "y_axis")]:
        base = candidate([f"P={coord}"])
        changed = candidate([f"P={coord}", f"P∈{axis}"])
        assert not compare(base, changed)["ok"]
    base = candidate(["P=(n,0) ∨ P=(n,1)"])
    changed = deepcopy(base)
    changed["root"]["facts"].append("P∈x_axis")
    assert not compare(base, changed)["ok"]
    equivalent(
        candidate(["P∈x_axis ∨ P∈y_axis"]),
        candidate(["segment(P,Q)", "y(P)=0 ∨ x(P)=0"]),
    )


def test_axis_membership_inheritance_is_one_way_and_scoped():
    base = candidate(["P=(n,0)"], children=[{}])
    changed = deepcopy(base)
    changed["root"]["children"][0]["facts"] = ["P∈x_axis"]
    equivalent(base, changed)
    base = candidate(children=[{"facts": ["P=(n,0)"]}, {"facts": ["P=(n,t)"]}])
    changed = deepcopy(base)
    changed["root"]["children"][1]["facts"].append("P∈x_axis")
    assert not compare(base, changed)["ok"]


def test_axis_equivalences_also_apply_to_at_without_dropping_the_state():
    base = candidate(
        ["P=(n,t)"],
        goals=[{"kind": "find_coordinates", "object": "P", "at": "P∈x_axis"}],
    )
    changed = deepcopy(base)
    changed["root"]["goals"][0]["at"] = "y(P)=0"
    equivalent(base, changed)
    changed["root"]["goals"][0].pop("at")
    assert not compare(base, changed)["ok"]


def test_declaration_and_axis_rules_compose_idempotently_with_set_redundancy():
    payload = candidate(
        [
            "segment(A,B)",
            "Γ:y=x^2-1",
            "Γ∩x_axis={A,B}",
            "A∈x_axis",
            "N=(n,0)",
            "N∈x_axis",
        ]
    )
    report = NotationValidator().validate(payload)
    first = report.semantic_normalization
    second = normalize_bound(first["root"], first["objects"])
    assert first["root"] == second["root"]
    assert {
        "standalone_segment_declaration",
        "finite_set_membership_redundancy",
        "coordinate_axis_membership",
        "duplicate_relation",
    } <= {p["rule"] for p in first["proofs"]}


@pytest.mark.parametrize("entry", MANIFEST["cases"], ids=lambda row: row["case"])
def test_latest_live_responses_are_immutable_and_replay_six_of_seven(entry):
    for name, digest in entry["files"].items():
        assert sha256((RECORDED / name).read_bytes()).hexdigest() == digest
    case = entry["case"]
    actual = json.loads((RECORDED / (case + ".txt")).read_text())
    gold = json.loads((RECORDED / (case + ".gold.json")).read_text())
    policy_path = RECORDED / (case + ".policy.json")
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
    result = evaluate(gold, actual, policy)
    assert result["ok"] is entry["expected_offline_passed"], result
    assert NotationValidator().validate(actual).ok


def test_live_results_remain_four_of_seven():
    assert sum(row["live_passed"] for row in MANIFEST["cases"]) == 4
    assert sum(row["expected_offline_passed"] for row in MANIFEST["cases"]) == 6
