import json
from dataclasses import replace

import pytest
from _math_runtime_binding_support import (
    CASES,
    answers,
    assert_expected,
    binding,
    candidate,
    replay,
    replay_errors,
)
from shuxueshuo_server.problem_understanding.compact_planner_input import (
    compact_methods,
    compact_problem,
    coverage,
)
from shuxueshuo_server.problem_understanding.runtime_binding import bind_notation
from shuxueshuo_server.problem_understanding.runtime_lowering import BindingError


@pytest.mark.parametrize("case", CASES)
def test_review_input_preserves_every_mathematical_source_unit(case):
    b = binding(case)
    value = compact_problem(b)
    assert value["root"] == candidate(case)["root"]
    assert value["known_results"] == []
    assert set(value) == {
        "problem_id",
        "planning_scope",
        "scope_policy",
        "solution_policy",
        "known_results",
        "root",
    }
    assert not any(
        w in json.dumps(value)
        for w in ["optimizations", "source_hash", "state_version", "original_text"]
    )
    signatures = compact_methods(b)["capabilities"]
    assert all(s["preconditions"] and s["method"] for s in signatures)
    assert not any(
        w in json.dumps(signatures)
        for w in [
            "runtime_path",
            "source_unit_id",
            "output_targets",
            "open_state",
            "SourceRef",
        ]
    )
    assert coverage(b)["entries"]
    artifacts = b.artifacts()
    assert artifacts["initial-state.json"]["state"]
    assert all(
        p["source_identity"]["candidate_hash"] == b.source_identity["candidate_hash"]
        for p in artifacts["source-map.json"].values()
    )


def test_local_view_includes_ancestors_without_sibling_conditions(tmp_path):
    case = CASES[1]
    b = binding(case)
    r = replay(case, b, tmp_path)
    assert r.status == "accepted", replay_errors(r)
    local = compact_problem(b, scope_path=(0, 1), execution=r.verified_execution)
    raw = candidate(case)["root"]
    assert local["root"]["facts"] == raw["facts"]
    assert len(local["root"]["children"]) == 1
    parent = local["root"]["children"][0]
    assert parent["facts"] == raw["children"][0]["facts"]
    assert parent["children"] == [raw["children"][0]["children"][1]]
    assert len(local["known_results"]) == 1
    assert "E ∈ {" in local["known_results"][0]["facts"][0]
    assert "2 - sqrt(6)" in local["known_results"][0]["facts"][0]
    assert "2 + sqrt(6)" in local["known_results"][0]["facts"][0]
    with pytest.raises(BindingError, match="result_version_changed"):
        compact_problem(
            b, execution=replace(r.verified_execution, problem_revision_id="older")
        )
    with pytest.raises(BindingError, match="scope_unresolved"):
        compact_problem(b, scope_path=(99,))


def test_original_transcription_is_stored_but_not_duplicated_in_math_input():
    raw = candidate(CASES[3])
    raw["original_text"] = "原题文字保留在候选中。"
    b = binding(CASES[3], payload=raw)
    assert b.bundle.candidate["original_text"] == raw["original_text"]
    assert raw["original_text"] not in json.dumps(
        compact_problem(b), ensure_ascii=False
    )


def test_renamed_objects_and_problem_id_use_audit_map_for_plan_rebinding(tmp_path):
    raw = candidate(CASES[3])

    def rename(value):
        if isinstance(value, str):
            return value.replace("M", "U").replace("N", "V").replace("Γ", "Ω")
        if isinstance(value, list):
            return [rename(v) for v in value]
        if isinstance(value, dict):
            return {k: rename(v) for k, v in value.items()}
        return value

    raw["root"] = rename(raw["root"])
    b = bind_notation(
        raw,
        problem_id="unrelated-id",
        candidate_id="variant",
        source_version_id="source",
        source_hash="hash",
    )
    r = replay(CASES[3], b, tmp_path)
    assert r.status == "accepted", replay_errors(r)
    assert_expected(CASES[3], b, r)
    assert {e["name"] for e in b.bundle.canonical_solver_input["entities"]} >= {
        "U",
        "V",
    }
    assert "y_U" in {
        e["name"]
        for e in b.bundle.canonical_solver_input["entities"]
        if e.get("role") == "coordinate_alias"
    }


@pytest.mark.parametrize("case", [CASES[0], CASES[1]])
def test_equivalent_path_order_and_comparison_direction_execute(case, tmp_path):
    raw = candidate(case)

    def equivalent(node):
        node["facts"] = [
            s.replace("EG+FG", "FG+EG").replace("x(A) < x(B)", "x(B) > x(A)")
            for s in node.get("facts", [])
        ]
        for goal in node.get("goals", []):
            if "expression" in goal:
                goal["expression"] = goal["expression"].replace("EG+FG", "FG+EG")
        for child in node.get("children", []):
            equivalent(child)

    equivalent(raw["root"])
    b = binding(case, payload=raw)
    r = replay(case, b, tmp_path)
    assert r.status == "accepted", replay_errors(r)
    assert_expected(case, b, r)


def test_reversed_ratio_is_consumed_and_cannot_replay_original_answer(tmp_path):
    case = CASES[0]
    raw = candidate(case)
    raw["root"]["children"][1]["facts"][-1] = "sqrt(2)*DE = NG"
    try:
        b = binding(case, payload=raw)
    except BindingError as error:
        assert error.code == "binding.source_input_unavailable"
        return
    r = replay(case, b, tmp_path)
    if r.status == "accepted":
        original = replay(case, binding(case), tmp_path / "original")
        assert answers(b, r) != answers(binding(case), original)
    else:
        assert replay_errors(r)


def test_coefficient_cannot_be_selected_as_the_motion_variable():
    raw = candidate(CASES[3])
    raw["root"]["children"][2]["facts"][-1] = "min_{b}(sqrt(2)*MN + AN) = 21/4"
    with pytest.raises(BindingError, match="motion_variables_mismatch"):
        binding(CASES[3], payload=raw)


def test_coordinate_alias_constraint_cannot_disappear():
    raw = candidate(CASES[3])
    raw["root"]["children"][2]["facts"].append("y_M = 99")
    with pytest.raises(BindingError, match="coordinate_alias_constraint_unbound"):
        binding(CASES[3], payload=raw)


def test_plan_cannot_read_a_sibling_point(tmp_path, monkeypatch):
    import _math_runtime_binding_support as support

    b = binding(CASES[3])
    plan = support.trusted_plan(CASES[3], b)
    plan["root_scope"]["children"][0]["goals"][0]["steps"][0]["args"]["curve_point"] = (
        "M"
    )
    monkeypatch.setattr(support, "trusted_plan", lambda *_: plan)
    result = replay(CASES[3], b, tmp_path)
    assert result.status == "blocked"
    assert replay_errors(result)
