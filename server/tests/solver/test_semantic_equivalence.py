"""Focused regression tests for direct mathematical notation normalization."""

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.equivalence_rules import known_rule


def candidate(*facts, goals=(), children=()):
    return {
        "root": {
            "label": "题目",
            "definitions": [],
            "facts": list(facts),
            "goals": list(goals),
            "children": list(children),
            "uncertainties": [],
        },
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "synthetic",
    }


def derived(report, rule_id):
    return [item for item in report.normalization_report["derived_facts"] if item["rule_id"] == rule_id]


def test_direct_angle_and_perpendicular_share_right_angle_canonical_fact():
    validator = NotationValidator()
    angle = validator.validate(candidate("∠ABC=90°"))
    perpendicular = validator.validate(candidate("line(A,B) ⟂ line(B,C)"))

    assert angle.ok, angle.issues
    assert perpendicular.ok, perpendicular.issues
    angle_fact = derived(angle, "right_angle_from_angle")[0]["fact"]
    perpendicular_fact = derived(perpendicular, "right_angle_from_perpendicular")[0]["fact"]
    assert angle_fact == perpendicular_fact
    assert angle.normalization_report["derived_facts"][0]["source_expression"] == "∠ABC=90°"
    assert angle.normalization_report["derived_facts"][0]["source_paths"] == ["r.facts[0]"]

    reversed_perpendicular = validator.validate(candidate("line(B,C) ⟂ line(A,B)"))
    assert reversed_perpendicular.ok, reversed_perpendicular.issues
    assert derived(reversed_perpendicular, "right_angle_from_perpendicular")[0]["fact"] == angle_fact


def test_perpendicular_without_shared_vertex_fails_closed_without_derived_fact():
    report = NotationValidator().validate(candidate("line(A,B) ⟂ line(C,D)"))

    assert report.ok, report.issues
    assert not derived(report, "right_angle_from_perpendicular")
    assert report.normalization_report["canonical_facts"]
    assert report.normalization_report["blocked"][0]["code"] == "ambiguous_entity_scope"


def test_direct_angle_relations_and_tangent_goal_compile_without_internal_angle_syntax():
    report = NotationValidator().validate(
        candidate(
            "∠BDC=2∠ABD",
            goals=[{"kind": "find_value", "expression": "tan(∠ABC)"}],
        )
    )

    assert report.ok, report.issues
    assert report.semantic["facts"]
    assert report.semantic["goals"]


def test_canonical_facts_exclude_removal_sentinels_and_registry_covers_all_rules():
    report = NotationValidator().validate(
        candidate("segment(A,B)", "A∈x_axis", "A∈x_axis")
    )

    assert report.ok, report.issues
    assert known_rule("bisector_unit_ratio")
    assert all(item["fact"] != ["and"] for item in report.normalization_report["canonical_facts"])
    assert all(
        not (
            isinstance(item["fact"], list)
            and item["fact"][:1] == ["="]
            and len(item["fact"]) == 3
            and item["fact"][1] == item["fact"][2]
        )
        for item in report.normalization_report["canonical_facts"]
    )
