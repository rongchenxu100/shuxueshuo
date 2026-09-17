"""Typed endpoints and reviewed extraction rules, without live model calls."""

import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from _math_notation_test_support import assert_removed_at_rejected

from shuxueshuo_server.problem_understanding.batch_smoke import prepare_fixture
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_contract import SYSTEM, schema
from shuxueshuo_server.problem_understanding.notation_semantics import compare, evaluate
from shuxueshuo_server.problem_understanding.notation_service import parse_candidate
from shuxueshuo_server.problem_understanding.smoke import build_request
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

FIXTURES = Path(__file__).parent / "fixtures/math-notation-v1"
RECORDED = FIXTURES / "recorded-latest-20260916"


def candidate(facts=(), **scope):
    return {
        "root": {"facts": list(facts), **scope},
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "synthetic",
    }


def parse(payload):
    return parse_candidate(
        json.dumps(payload),
        problem_id="synthetic",
        source_sha256="0" * 64,
        registry_snapshot="0" * 64,
        registered_families=[],
    )


@pytest.mark.parametrize(
    "expression,names",
    [
        ("bisects(BD,AC)", "ABCD"),
        ("cut_ratio(BD,AC)=r", "ABCD"),
        ("P∈segment(A,B)", "ABP"),
        ("line(A,B)∩line(C,D)={P}", "ABCDP"),
        ("length(A,B)=3", "AB"),
        ("angle(A,B,C)=60°", "ABC"),
        ("P=midpoint(A,B)", "ABP"),
        ("area(△ABC)=2", "ABC"),
    ],
)
def test_operator_signature_establishes_points_without_extra_output(expression, names):
    payload = candidate([expression])
    report = NotationValidator().validate(payload)
    assert report.ok, report.issues
    assert {o["name"] for o in report.objects if o["kind"] == "point"} == set(names)
    assert report.normalized["root"]["facts"] == [expression]
    assert all(o["scope"] == "r" for o in report.objects)


def test_complex_endpoint_names_and_signature_binding_have_same_semantics():
    actual = candidate(
        [
            "bisects(segment(B1,D1),line(A1,C1))",
            "cut_ratio(segment(B1,D1),line(A1,C1))=r",
        ]
    )
    report = NotationValidator().validate(actual)
    assert report.ok, report.issues
    assert {o["name"] for o in report.objects if o["kind"] == "point"} == {
        "A1",
        "B1",
        "C1",
        "D1",
    }


def test_endpoint_identity_uses_ancestors_but_isolates_siblings():
    payload = candidate(
        ["A=(0,0)"],
        children=[{"facts": ["bisects(BD,AC)"]}, {"facts": ["cut_ratio(BD,AC)=r"]}],
    )
    report = NotationValidator().validate(payload)
    assert report.ok, report.issues
    assert [o["scope"] for o in report.objects if o["name"] == "A"] == ["r"]
    for name in "BCD":
        assert {o["scope"] for o in report.objects if o["name"] == name} == {
            "r.c0",
            "r.c1",
        }
    payload["root"]["children"][1] = {
        "goals": [{"kind": "find_coordinates", "object": "B"}]
    }
    assert not NotationValidator().validate(payload).ok


@pytest.mark.parametrize(
    "facts", [["A∈ℝ", "bisects(BD,AC)"], ["bisects(BD,AC)", "A∈ℝ"]]
)
def test_point_signatures_never_override_conflicting_types(facts):
    report = NotationValidator().validate(candidate(facts))
    assert not report.ok and any(
        e["reason_code"] == "binding.type_conflict" and e["source"] == facts[1]
        for e in report.issues
    )


@pytest.mark.parametrize(
    "expression",
    [
        "bisects(ray(A,B),line(C,D))",
        "bisects(AB)",
        "bisects(ABC,DE)",
        "bisects(segment(A,B,C),DE)",
    ],
)
def test_invalid_endpoint_forms_remain_errors(expression):
    assert not NotationValidator().validate(candidate([expression])).ok


def test_endpoint_binding_does_not_invent_polygon_or_change_locus_types():
    minimal = candidate(["bisects(BD,AC)"])
    polygon = candidate(["quadrilateral(A,B,C,D)", "bisects(BD,AC)"])
    assert not compare(minimal, polygon)["ok"]
    report = NotationValidator().validate(
        candidate(["quadrilateral(A,B,C,D)", "AC∩BD={O}"])
    )
    assert not report.ok and any(
        e["message"] == "type.intersection" for e in report.issues
    )


def test_k_saved_response_only_loses_cascade_errors():
    actual = json.loads((RECORDED / "k-quad.txt").read_text())
    report = NotationValidator().validate(actual)
    assert len(report.issues) == 1
    assert report.issues[0]["source"] == "AC ∩ BD = {O}"
    # Diagnostic replacement resolves the type error, but not missing content.
    diagnostic = deepcopy(actual)
    diagnostic["root"]["children"][0]["children"][0]["facts"][1] = (
        "segment(A,C)∩segment(B,D)={O}"
    )
    assert NotationValidator().validate(diagnostic).ok
    gold = json.loads((FIXTURES / "k-quad.json").read_text())
    assert not compare(gold, diagnostic)["ok"]
    assert parse(diagnostic)["continuation"]["status"] == "candidate_only"
    # Content-only parsing cannot detect a missing diagram not reported by LLM.
    diagnostic["root"]["uncertainties"] = [
        {"kind": "missing_figure", "text": "题面引用的图未提供。"}
    ]
    assert (
        parse(diagnostic)["continuation"]["error_code"] == "extraction.missing_figure"
    )


def test_reviewed_nankai_gold_uses_one_shared_state_fact(tmp_path):
    name = "tj-2026-nankai-yimo-25"
    current = json.loads((FIXTURES / (name + ".json")).read_text())
    scope = current["root"]["children"][1]["children"][1]
    assert scope["facts"] == [
        "min_{E,G}(EG+FG) = 5*sqrt(10)/2",
        "EG+FG = min_{E,G}(EG+FG)",
    ]
    assert scope["goals"] == [
        {"kind": "find_equation", "object": "Γ"},
        {"kind": "find_coordinates", "object": "G"},
    ]
    actual = json.loads((RECORDED / (name + ".txt")).read_text())
    assert assert_removed_at_rejected(actual)
    assert compare(current, current)["ok"]
    fixture = prepare_fixture(name, tmp_path)
    revision = json.loads((fixture / "gold-revision.json").read_text())
    assert (
        revision["sha256"] == sha256((fixture / "gold.json").read_bytes()).hexdigest()
    )
    request = build_request(fixture, ExtractionArtifactStore(tmp_path / "request"), [])
    assert "gold-revision" not in request.prompt.user_prefix
    assert revision["source_quote"] not in request.prompt.user_prefix


@pytest.mark.parametrize(
    "change", ["remove", "maximum", "different_path", "unrelated_goal"]
)
def test_state_fact_stays_strict_after_review(change):
    gold = json.loads((FIXTURES / "tj-2026-nankai-yimo-25.json").read_text())
    actual = deepcopy(gold)
    facts = actual["root"]["children"][1]["children"][1]["facts"]
    if change == "remove":
        facts.pop()
    elif change == "maximum":
        facts[-1] = facts[-1].replace("min", "max")
    elif change == "different_path":
        facts[-1] = facts[-1].replace("EG+FG", "EG")
    else:
        actual["root"]["children"][1]["children"][0]["facts"].append(facts.pop())
    assert not compare(gold, actual)["ok"]


def test_current_gold_revision_is_hashed_and_preserves_every_previous_gold():
    revision = json.loads((FIXTURES / "gold-revisions.json").read_text())
    assert [case for case, row in revision["cases"].items() if row["changed"]] == [
        "tj-2026-heping-ermo-25",
        "tj-2026-nankai-yimo-25",
    ]
    for case, row in revision["cases"].items():
        assert (
            sha256((FIXTURES / (case + ".json")).read_bytes()).hexdigest()
            == row["sha256"]
        )
        assert (
            sha256((FIXTURES / row["previous_file"]).read_bytes()).hexdigest()
            == row["previous_sha256"]
        )


def test_old_recordings_do_not_become_current_passes_through_implicit_migration():
    manifest = json.loads((RECORDED / "manifest.json").read_text())
    for row in manifest["cases"]:
        case = row["case"]
        gold = json.loads((FIXTURES / (case + ".json")).read_text())
        actual = json.loads((RECORDED / (case + ".txt")).read_text())
        policy = (
            json.loads((RECORDED / (case + ".policy.json")).read_text())
            if "policy_sha256" in row
            else None
        )
        result = evaluate(gold, actual, policy)
        if assert_removed_at_rejected(actual):
            assert not result["ok"]
        else:
            assert result["ok"] is row["expected_offline_passed"]


def test_few_shots_cover_state_scope_missing_diagrams_and_preserve_branches():
    examples = [
        json.loads(s) for s in re.findall(r"```json\n(.*?)\n```", SYSTEM, re.DOTALL)
    ]
    assert len(examples) == 6
    single = examples[1]["root"]["goals"]
    parallel = examples[3]["root"]["goals"]
    assert len(single) == 1 and single[0]["kind"] == "find_minimum"
    child = examples[1]["root"]["children"][0]
    assert child["facts"] == ["PT+TW = min(PT+TW)"]
    assert child["goals"] == [{"kind": "find_coordinates", "object": "T"}]
    assert len(parallel) == 2
    assert "PT+TR = min(PT+TR)" in examples[3]["root"]["facts"]
    assert "UV = 2 ∨ UV = 5" in examples[2]["root"]["facts"]
    assert "UV > 3" in examples[2]["root"]["facts"]
    changed = deepcopy(examples[2])
    changed["root"]["facts"][-1] = "UV=5"
    assert not compare(examples[2], changed)["ok"]
    assert (
        parse(examples[4])["continuation"]["error_code"] == "extraction.missing_figure"
    )
    assert not parse(examples[5])["continuation"]["blocked"]
    parent = examples[4]["root"]["children"][0]
    assert parent["label"] == "(1)" and len(parent["children"]) == 2
    assert "uncertainties" not in parent["children"][0]
    assert parent["children"][1]["uncertainties"][0]["kind"] == "missing_figure"
    assert "不将“(1)图甲”“(1)图乙”平铺" in SYSTEM
    assert "文字完整、可转写全部关系或可凭文字作图" in SYSTEM
    assert (
        "保留(1)父节点"
        in schema()["$defs"]["Scope"]["properties"]["children"]["description"]
    )
    assert "仅部分目标" in schema()["$defs"]["Scope"]["description"]


def test_model_output_shape_explicitly_removes_goal_state_field():
    def shape(value):
        if isinstance(value, dict):
            return {k: shape(v) for k, v in value.items() if k != "description"}
        if isinstance(value, list):
            return [shape(v) for v in value]
        return value

    previous = json.loads((RECORDED / "wire-shape.json").read_text())
    obsolete = previous["shape"]
    assert shape(schema()) != obsolete
    for goal in obsolete["$defs"]["Scope"]["properties"]["goals"]["items"]["oneOf"]:
        del goal["properties"]["at"]
    assert shape(schema()) == obsolete
