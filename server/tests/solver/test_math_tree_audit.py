"""Migration audit tests: independent parsing, semantic mutations and scope loss."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.math_tree_audit import (
    build_math_tree,
    compare_math_trees,
)
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator

ROOT = Path(__file__).resolve().parents[3]
CASES = ("nankai-yimo", "heping-ermo", "heping-yimo", "hexi-yimo", "xiqing-yimo")


def midpoint_pair():
    old = {
        "schema_version": "problem-domain/v1",
        "problem_id": "audit-midpoint",
        "family_id": "QuadraticPathMinimumSolver",
        "source": {"question_number": "25", "score": "10"},
        "root": {
            "id": "problem",
            "label": "整题",
            "source_text": ["D、N 的中点为 F，求 F 的坐标。"],
            "entities": [
                {
                    "id": name,
                    "label": name,
                    "kind": kind,
                    **({"role": "dynamic_parameter"} if kind == "symbol" else {}),
                }
                for name, kind in (
                    ("D", "point"),
                    ("N", "point"),
                    ("F", "point"),
                    ("u", "symbol"),
                    ("v", "symbol"),
                )
            ],
            "facts": [
                {"kind": "point_coordinate", "point": "D", "value": ["1", "0"]},
                {"kind": "point_coordinate", "point": "N", "value": ["u", "v"]},
                {
                    "kind": "midpoint",
                    "point": "F",
                    "segment": {"start": "D", "end": "N"},
                },
            ],
            "goals": [{"kind": "point_coordinate", "answer_key": "F", "target": "F"}],
            "children": [],
        },
    }
    new = {
        "family_id": old["family_id"],
        "match_status": "matched",
        "match_reason": "audit fixture",
        "root": {
            "facts": ["D=(1,0)", "N=(u,v)", "F=midpoint(D,N)"],
            "goals": [{"kind": "find_coordinates", "object": "F"}],
        },
    }
    return old, new


def compare(old, new):
    return compare_math_trees(
        build_math_tree(old, format="legacy"), build_math_tree(new, format="notation")
    )


def fixture_pair(case):
    name = f"tj-2026-{case}-25.json"
    return (
        json.loads((ROOT / "internal/problem-domain-fixtures" / name).read_text()),
        json.loads(
            (ROOT / "server/tests/solver/fixtures/math-notation-v1" / name).read_text()
        ),
    )


def test_structural_legacy_adapter_does_not_reparse_old_data_as_new_notation(
    monkeypatch,
):
    old, _ = midpoint_pair()
    monkeypatch.setattr(
        NotationValidator,
        "validate",
        lambda *a: pytest.fail("legacy path reused new parser"),
    )
    snapshot = build_math_tree(old, format="legacy")
    assert snapshot["parse_valid"]
    assert {x["ref"] for x in snapshot["raw_objects"]} == {
        "r:point:D",
        "r:point:N",
        "r:point:F",
        "r:scalar:u",
        "r:scalar:v",
    }
    assert len(snapshot["source_coverage"]) == 9


def test_equivalent_midpoint_keeps_identity_and_symbolic_coordinates_without_solving():
    old, new = midpoint_pair()
    assert compare(old, new)["equivalent"]
    snapshot = build_math_tree(new, format="notation")
    assert not snapshot["solver_ready"] and not snapshot["runtime_bound"]
    assert {s["object"][1] for s in snapshot["initial_states"]} == {
        "r:point:D",
        "r:point:N",
    }
    assert len(snapshot["source_coverage"]) == 4


@pytest.mark.parametrize("replacement", ["D=(2,0)", "D=(1,1)"])
def test_changed_coordinate_fails_even_when_all_objects_and_scopes_match(replacement):
    old, new = midpoint_pair()
    new["root"]["facts"][0] = replacement
    result = compare(old, new)
    assert not result["equivalent"]
    assert any(d["category"] == "facts" for d in result["differences"])
    assert not any(d["category"] == "objects" for d in result["differences"])


def test_missing_midpoint_relation_is_not_recovered_by_name_or_expected_goal():
    old, new = midpoint_pair()
    new["root"]["facts"][2] = "F ∈ segment(D,N)"
    assert not compare(old, new)["equivalent"]


def test_changed_goal_detected():
    old, new = midpoint_pair()
    new["root"]["goals"][0]["object"] = "D"
    assert any(d["category"] == "goals" for d in compare(old, new)["differences"])


def test_state_and_answer_form_are_not_erased_by_comparison():
    old, new = midpoint_pair()
    new["root"]["facts"].append("u=2")
    new["root"]["goals"][0].update(in_terms_of=["v"])
    result = compare(old, new)
    assert not result["equivalent"]
    assert any(d["category"] == "qualifiers" for d in result["differences"])


def test_extremum_variables_are_compared_even_when_existing_equivalence_ignores_them():
    _, new = midpoint_pair()
    new["root"]["goals"] = [
        {"kind": "find_minimum", "expression": "u^2+v^2", "variables": ["u"]}
    ]
    changed = deepcopy(new)
    changed["root"]["goals"][0]["variables"] = ["v"]
    result = compare_math_trees(
        build_math_tree(new, format="notation"),
        build_math_tree(changed, format="notation"),
    )
    assert result["bounded_semantic_equivalence"]
    assert not result["equivalent"]
    assert result["differences"][0]["category"] == "qualifiers"


def test_parameter_answer_equivalence_does_not_hide_different_source_states():
    _, original = fixture_pair("hexi-yimo")
    changed = deepcopy(original)
    changed["root"]["children"][2]["facts"].append(
        "sqrt(2)*MN+AN=min_{n}(sqrt(2)*MN+AN)"
    )
    left, right = (
        build_math_tree(value, format="notation") for value in (original, changed)
    )
    result = compare_math_trees(left, right)
    assert result["bounded_semantic_equivalence"]
    assert any(
        p["rule"] == "parameter_state_extremum_witness"
        for p in right["normalization"]["proofs"]
    )
    assert not result["equivalent"]
    assert [d["category"] for d in result["differences"]] == ["state_conditions"]
    assert not left["state_conditions"] and len(right["state_conditions"]) == 1


@pytest.mark.parametrize("change", ["remove", "parent", "sibling", "value", "or"])
def test_state_fact_scope_and_boolean_context_survive_tree_audit(change):
    _, source = midpoint_pair()
    source["root"] = {
        "facts": ["P=(t,t^2)"],
        "goals": [{"kind": "find_minimum", "expression": "y(P)"}],
        "children": [
            {
                "facts": ["y(P)=min(y(P))"],
                "goals": [{"kind": "find_coordinates", "object": "P"}],
            }
        ],
    }
    changed = deepcopy(source)
    child = changed["root"]["children"][0]
    state = child["facts"].pop()
    if change == "parent":
        changed["root"]["facts"].append(state)
    elif change == "sibling":
        changed["root"]["children"].append({"facts": [state]})
    elif change == "value":
        child["facts"].append("min(y(P))=0")
    elif change == "or":
        child["facts"].append(f"({state}) ∨ t=1")
    before = deepcopy((source, changed))
    left, right = (
        build_math_tree(value, format="notation") for value in (source, changed)
    )
    assert left["parse_valid"] and right["parse_valid"]
    result = compare_math_trees(left, right)
    assert not result["equivalent"]
    assert any(d["category"] == "state_conditions" for d in result["differences"])
    assert (source, changed) == before


def test_symmetric_attained_state_relation_is_not_a_tree_difference():
    _, source = fixture_pair("nankai-yimo")
    changed = deepcopy(source)
    facts = changed["root"]["children"][1]["children"][1]["facts"]
    facts[facts.index("EG+FG = min_{E,G}(EG+FG)")] = "min_{E,G}(FG+EG)=FG+EG"
    result = compare_math_trees(
        build_math_tree(source, format="notation"),
        build_math_tree(changed, format="notation"),
    )
    assert result["equivalent"]


def test_sibling_conditions_cannot_supply_missing_object():
    _, new = midpoint_pair()
    new["root"] = {
        "children": [
            {"facts": ["D=(1,0)"]},
            {"goals": [{"kind": "find_coordinates", "object": "D"}]},
        ]
    }
    snapshot = build_math_tree(new, format="notation")
    assert not snapshot["parse_valid"]
    assert "unknown_or_invisible" in json.dumps(snapshot["issues"])


def test_moving_same_named_point_to_another_scope_is_detected():
    old, new = midpoint_pair()
    new["root"] = {"children": [new["root"]]}
    result = compare(old, new)
    assert not result["equivalent"]
    assert any(d["category"] == "scopes" for d in result["differences"])


def test_symmetric_midpoint_arguments_are_equivalent():
    old, new = midpoint_pair()
    new["root"]["facts"][2] = "F=midpoint(N,D)"
    assert compare(old, new)["equivalent"]


@pytest.mark.parametrize(
    "field,value", [("family_id", "InventedFamily"), ("match_status", "unmatched")]
)
def test_invalid_match_is_not_a_valid_candidate(field, value):
    old, new = midpoint_pair()
    new[field] = value
    assert compare(old, new)["status"] == "invalid_input"


def test_unknown_legacy_fact_is_not_silently_dropped():
    old, _ = midpoint_pair()
    old["root"]["facts"].append({"kind": "unknown_relation"})
    with pytest.raises(ValueError):
        build_math_tree(old, format="legacy")


def test_invalid_nonobject_payload_is_reported_as_invalid():
    assert not build_math_tree([], format="notation")["parse_valid"]


def test_function_expression_in_goal_uses_its_lexical_definition():
    _, new = midpoint_pair()
    new["root"] = {
        "definitions": ["f(t)=t^2"],
        "facts": ["u ∈ ℝ"],
        "children": [
            {
                "goals": [
                    {"kind": "find_minimum", "expression": "f(u)", "variables": ["u"]}
                ]
            }
        ],
    }
    snapshot = build_math_tree(new, format="notation")
    assert snapshot["parse_valid"]
    assert snapshot["qualifiers"] and snapshot["objective_uses"]


@pytest.mark.parametrize("case", CASES)
def test_five_authored_fixtures_align_objects_but_do_not_hide_remaining_differences(
    case,
):
    old, new = fixture_pair(case)
    before = deepcopy((old, new))
    a, b = (
        build_math_tree(old, format="legacy"),
        build_math_tree(new, format="notation"),
    )
    assert a["parse_valid"] and b["parse_valid"]
    assert a["objects"] == b["objects"]
    assert a["scopes"] == b["scopes"]
    result = compare_math_trees(a, b)
    assert result["status"] == "needs_review"
    category = "facts" if case == "heping-ermo" else "qualifiers"
    assert any(d["category"] == category for d in result["differences"])
    assert (old, new) == before


def test_legacy_target_descriptor_change_is_not_ignored_as_metadata():
    old, new = fixture_pair("nankai-yimo")
    target = next(
        f for f in old["root"]["children"][1]["facts"] if f["kind"] == "minimum_target"
    )
    target["expression"]["terms"][0]["scale"] = "2"
    result = compare(old, new)
    assert any(
        d["category"] == "legacy_objective_unmatched" for d in result["differences"]
    )


def test_ratio_direction_change_remains_a_fact_difference():
    old, new = fixture_pair("nankai-yimo")
    facts = new["root"]["children"][1]["facts"]
    facts[facts.index("DE = sqrt(2)*NG")] = "sqrt(2)*DE = NG"
    result = compare(old, new)
    assert any(
        d["category"] == "facts" and d["scope"] == "r.c1" for d in result["differences"]
    )


def test_named_vertex_and_unnamed_vertex_preserve_raw_difference_and_proven_normalization():
    old, new = fixture_pair("xiqing-yimo")
    a, b = (
        build_math_tree(old, format="legacy"),
        build_math_tree(new, format="notation"),
    )
    assert len(a["raw_objects"]) == len(b["raw_objects"]) + 1
    assert a["objects"] == b["objects"]
    assert a["normalization"]["object_bindings"]


def test_report_freezes_inputs_and_actual_runtime_values_without_claiming_migration(
    tmp_path,
):
    from tools.compare_problem_math_trees import run

    case = "tj-2026-hexi-yimo-25"
    output = tmp_path / "audit"
    manifest = run(output, cases=[case])
    assert manifest["complete"] and manifest["source_stable"]
    assert manifest["input_class"] == "authored_fixture"
    assert (
        "internal/schemas/problem-math-notation-v1.schema.json"
        in manifest["source_hashes"]
    )
    assert manifest["llm_calls"] == 0 and not manifest["new_runtime_bound"]
    assert manifest["cases"][0]["status"] == "needs_review"
    snapshot = json.loads((output / case / "legacy-domain-runtime.json").read_text())
    assert snapshot["runtime_bound"] and snapshot["runtime_values"]
    assert snapshot["state_slots"]
    assert (output / case / "input-notation.json").read_bytes() == (
        ROOT / "server/tests/solver/fixtures/math-notation-v1" / f"{case}.json"
    ).read_bytes()


def test_cli_gate_reports_invalid_external_candidate_and_returns_failure(
    tmp_path, monkeypatch
):
    from tools.compare_problem_math_trees import main

    case = "tj-2026-hexi-yimo-25"
    inputs = tmp_path / "candidates"
    inputs.mkdir()
    (inputs / f"{case}.json").write_text("[]")
    output = tmp_path / "audit"
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit",
            "--output",
            str(output),
            "--case",
            case,
            "--notation-dir",
            str(inputs),
            "--require-equivalent",
        ],
    )
    assert main() == 1
    comparison = json.loads((output / case / "comparison.json").read_text())
    assert comparison["status"] == "invalid_input"
    assert "INVALID INPUT" in (output / case / "notation-tree.txt").read_text()


def test_recorded_workflow_reads_actual_candidate_and_freezes_its_exact_bytes(tmp_path):
    from tools.compare_problem_math_trees import run

    case = "tj-2026-hexi-yimo-25"
    batch = tmp_path / "batch"
    workflow = batch / case / "workflow"
    workflow.mkdir(parents=True)
    _, candidate = fixture_pair("hexi-yimo")
    candidate["root"]["children"][0]["facts"][0] = "a=2"
    raw = json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode()
    (workflow / "candidate.json").write_bytes(raw)
    output = tmp_path / "audit"
    manifest = run(output, cases=[case], workflow_batch=batch)
    assert manifest["input_class"] == "recorded_workflow_candidate"
    assert manifest["llm_calls"] == 0
    assert (output / case / "input-notation.json").read_bytes() == raw
    assert manifest["cases"][0]["inputs"]["notation"]["path"] == str(
        workflow / "candidate.json"
    )
    assert not manifest["cases"][0]["bounded_semantic_equivalence"]
