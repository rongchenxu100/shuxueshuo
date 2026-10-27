"""Full 1b execution boundary regressions through the public artifact entry."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import domain_expression
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from tests.solver.graph_stage_three_faults import (
    advance_error,
    advance_gap,
    failed_local_check,
    later_conflict,
    later_unknown,
)
from tests.solver.test_graph_stage_three_contracts import accepted, upstream

TARGET = "/root/goals/0"
EXPECTED = sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(4, sp.oo))


class Interrupted(BaseException):
    """A simulated process death, deliberately outside ordinary error handling."""


def read(path):
    return json.loads(path.read_text())


def events(output):
    # A running/interrupted route need not have exported any debug files.
    return store(output).events()


def store(output):
    return open_store(output)


def constructed_upstream(tmp_path, candidate):
    # Deliberate deterministic unit-test input, not fresh image/model evidence.
    value = accepted()
    value.update(candidate=candidate, features=extract_features(candidate)["features"])
    folder = tmp_path / "stage-two"
    result = run_result(value, folder, unsupported_root=tmp_path / "unsupported")
    assert result["status"] == "completed", result
    return folder / "stage-two-result.json"


def simple(*facts, symbol="a"):
    return {"original_text": " ".join(facts), "root": {"facts": list(facts), "goals": [{"kind": "find_range", "symbol": symbol}]}}


@pytest.mark.parametrize("milestone, routes", [("1a", set()), ("1b-1", {"discriminant"}), ("1b", {"discriminant", "extremum"})])
def test_q01_milestones_have_exact_registered_routes(tmp_path, milestone, routes):
    output = tmp_path / "out"
    result = runner.run_sample(upstream(tmp_path), output, milestone=milestone)
    assert result["status"] == "completed", result
    goal = result["goals"][0]
    assert {r["route_id"] for r in goal["routes"]} == routes
    assert all(r["status"] == "verified" for r in goal["routes"]), goal
    assert goal["status"] == ("solved" if routes else "no_verified_route")
    if routes:
        assert all(decode_value(r["feasible_set_exact"]) == EXPECTED for r in goal["routes"])
        assert len(read(output / "checkpoint.json")["handoffs"]) == len(routes)
    assert not any(result["llm"].values())


@pytest.mark.parametrize("facts,expected", [
    (("a<1", "∀x∈ℝ:x^2+a>=0"), sp.Interval.Ropen(0, 1)),
    (("a∈[-2,2)", "∀x∈ℝ:x^2+a^2-1>=0"), sp.Union(sp.Interval(-2, -1), sp.Interval.Ropen(1, 2))),
    (("a<0", "∀x∈ℝ:x^2+a>=0"), sp.S.EmptySet),
])
def test_complete_visible_constraints_reach_verified_answers(tmp_path, facts, expected):
    source = constructed_upstream(tmp_path, simple(*facts))
    result = runner.run_sample(source, tmp_path / "out")
    goal = result["goals"][0]
    assert result["status"] == "completed" and goal["status"] == "solved", goal
    assert goal["routes"] and all(r["status"] == "verified" for r in goal["routes"]), goal
    assert all(decode_value(r["feasible_set_exact"]) == expected for r in goal["routes"])
    assert goal["answer"]["kind"] == "find_range" and goal["answer"]["status"] == "set"


def test_first_route_publishes_before_second_is_verified_and_values_stay_isolated(tmp_path):
    observed = []
    first_state = None

    def before_verification(state, durable):
        nonlocal first_state
        snapshot = durable.snapshot()
        readable = [step for step in snapshot["math_steps"] if step["route_id"] == state["route_id"]]
        assert readable
        completed = [e for e in durable.events() if e["payload"].get("kind") == "route_completion"]
        if state["route_id"] == "discriminant":
            assert not completed and not snapshot["handoffs"]
            first_state = deepcopy(state["input_values"])
        else:
            assert len(completed) == 1 and completed[0]["route_id"] == "discriminant"
            assert len(snapshot["handoffs"]) == 1
            assert snapshot["goals"][TARGET]["status"] == "solved"
            assert durable.checkpoint(TARGET, "discriminant")["driver_state"]["input_values"] == first_state
        observed.append(state["route_id"])

    output = tmp_path / "out"
    result = runner.run_sample(upstream(tmp_path), output, hooks={"before_verification": before_verification})
    assert result["status"] == "completed", result
    assert observed == ["discriminant", "extremum"]
    saved = store(output)
    first = saved.checkpoint(TARGET, "discriminant")
    second = saved.checkpoint(TARGET, "extremum")
    assert first["driver_state"]["input_values"] == first_state
    assert first["route_id"] != second["route_id"]
    assert {s["step_id"] for s in first["math_steps"]}.isdisjoint(s["step_id"] for s in second["math_steps"])


def test_local_postcondition_failure_keeps_readable_prefix_and_other_route_runs(tmp_path):
    output = tmp_path / "out"
    result = runner.run_sample(upstream(tmp_path), output, hooks={"calculation_dispatch": failed_local_check})
    routes = {r["route_id"]: r for r in result["goals"][0]["routes"]}
    assert routes["discriminant"]["status"] == "math_failed", result
    assert routes["extremum"]["status"] == "verified"
    snapshot = read(output / "checkpoint.json")
    prefix = [s for s in snapshot["math_steps"] if s["route_id"] == "discriminant"]
    assert prefix and all(s["local_check"] == "passed" for s in prefix)
    assert not any(s["method_ref"].endswith("#solve") for s in prefix)
    assert {h["route_id"] for h in snapshot["handoffs"]} == {"extremum"}
    assert (output / "stage-three-result.json").is_file() and (output / "index.html").is_file()


@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_interrupted_commit_resumes_without_duplicate_cards_or_calls(tmp_path, position):
    source = upstream(tmp_path)
    output = tmp_path / "out"
    crashed = False

    def fail_once(state, durable):
        nonlocal crashed
        if state["fragments"] and not crashed:
            crashed = True
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(source, output, hooks={position: fail_once})
    resumed = runner.resume_sample(output)
    assert resumed["status"] == "completed", resumed
    assert all(r["status"] == "verified" for r in resumed["goals"][0]["routes"])
    snapshot = read(output / "checkpoint.json")
    identities = [(s["target_ref"], s["route_id"], s["step_id"]) for s in snapshot["math_steps"]]
    assert len(identities) == len(set(identities))
    saved_events = events(output)
    seq = [e["seq"] for e in saved_events]
    assert seq == list(range(1, len(seq)+1))
    published = [e for e in saved_events if e["payload"].get("kind") == "math_step"]
    assert len(published) == len(identities)
    again = runner.resume_sample(output)
    assert again["status"] == "completed"
    assert events(output) == saved_events


@pytest.mark.parametrize("tamper", ["source", "implementation"])
def test_resume_rejects_changed_input_and_implementation(tmp_path, monkeypatch, tamper):
    output = tmp_path / "out"

    def stop(state, durable):
        raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path), output, hooks={"before_verification": stop})
    if tamper == "source":
        candidate = read(output / "stage-one-input.json")
        candidate["candidate"]["original_text"] += " changed"
        (output / "stage-one-input.json").write_text(json.dumps(candidate))
        expected = "input_changed"
    else:
        current = runner.fingerprint()
        monkeypatch.setattr(runner, "fingerprint", lambda: {**current, "changed-test-module": "1"})
        expected = "revisions_changed"
    with pytest.raises(ValueError, match=expected):
        runner.resume_sample(output)


def test_domain_expression_change_rejects_resume_and_preserves_checkpoint(tmp_path, monkeypatch):
    output = tmp_path / "out"
    source = constructed_upstream(tmp_path, {
        "original_text": "求函数定义域",
        "root": {"definitions": ["f(x)=sqrt(x-1)/(x-2)"], "facts": [],
                 "goals": [{"kind": "find_domain", "object": "f"}]},
    })

    def stop(state, durable):
        raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(source, output, hooks={"before_verification": stop})
    prefix, frozen = events(output), read(output / "frozen.json")
    checkpoint = store(output).checkpoint(TARGET, "domain-intersection")
    conversion_source = Path(domain_expression.__file__).resolve()
    read_bytes = Path.read_bytes

    def changed_conversion(path):
        content = read_bytes(path)
        return content + b"\n# revised domain conversion\n" if path.resolve() == conversion_source else content

    # Exercise the real fingerprint collector without changing workspace files.
    with monkeypatch.context() as changed:
        changed.setattr(Path, "read_bytes", changed_conversion)
        with pytest.raises(ValueError, match=r"checkpoint\.revisions_changed"):
            runner.resume_sample(output)
        assert read(output / "frozen.json") == frozen
        assert events(output) == prefix
        assert store(output).checkpoint(TARGET, "domain-intersection") == checkpoint

    resumed = runner.resume_sample(output)
    assert resumed["goals"][0]["status"] == "solved"
    assert events(output)[:len(prefix)] == prefix


@pytest.mark.parametrize("failure,dispatch", [
    ("math_failed", failed_local_check),
    ("capability_gap", advance_gap),
    ("execution_error", advance_error),
])
def test_failed_operation_recovers_terminal_status_after_commit_interruption(tmp_path, failure, dispatch):
    output = tmp_path / "out"

    def interrupt_failed_operation(state, durable):
        if state["status"] == failure:
            assert durable.checkpoint(TARGET, state["route_id"])["status"] == "running"
            raise Interrupted()

    with pytest.raises(Interrupted):
        runner.run_sample(upstream(tmp_path), output, milestone="1b-1",
                          hooks={"after_commit": interrupt_failed_operation, "calculation_dispatch": dispatch})
    interrupted = store(output).checkpoint(TARGET, "discriminant")
    assert interrupted["status"] == "running" and interrupted["driver_state"]["status"] == failure
    result = runner.resume_sample(output)
    assert result["goals"][0]["routes"][0]["status"] == failure
    saved = store(output)
    checkpoint = saved.checkpoint(TARGET, "discriminant")
    assert checkpoint["status"] == failure and checkpoint["phase"] == "complete"
    assert checkpoint["driver_state"]["trajectory"] == interrupted["driver_state"]["trajectory"]
    terminal_events = [event for event in saved.events() if event["type"] == "lesson.route_status"
                       and event["payload"]["status"] == failure]
    assert len(terminal_events) == 1
    assert not saved.snapshot()["handoffs"]
    prior_events = saved.events()
    runner.resume_sample(output)
    assert saved.events() == prior_events


def test_one_goal_error_does_not_abort_other_goal_routes(tmp_path):
    from tests.solver.stage_three_preparation_probes import hooks

    candidate = {"original_text": "（1）∀x∈ℝ:x^2+a>=0，求a。（2）∀x∈ℝ:x^2+b>=0，求b。", "root": {"children": [
        {"label": "（1）", "facts": ["∀x∈ℝ:x^2+a>=0"], "goals": [{"kind": "find_range", "symbol": "a"}]},
        {"label": "（2）", "facts": ["∀x∈ℝ:x^2+b>=0"], "goals": [{"kind": "find_range", "symbol": "b"}]},
    ]}}
    source = constructed_upstream(tmp_path, candidate)
    result = runner.run_sample(source, tmp_path / "out", hooks=hooks(
        "build_context", target_ref="/root/children/0/goals/0", error="KeyError", message="injected target failure"))
    assert result["status"] == "partial", result
    assert [g["status"] for g in result["goals"]] == ["execution_error", "solved"]
    assert result["goals"][1]["routes"] and all(r["status"] == "verified" for r in result["goals"][1]["routes"])


def test_orchestration_error_after_first_route_invalidates_published_goal(tmp_path, monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three import execution

    original = execution.execute_route

    def fail_second(candidate, goal, branch, *args, **kwargs):
        if branch["route_id"] == "extremum":
            raise KeyError("broken route initialization")
        return original(candidate, goal, branch, *args, **kwargs)

    monkeypatch.setattr(execution, "execute_route", fail_second)
    output = tmp_path / "out"
    result = runner.run_sample(upstream(tmp_path), output)
    assert result["status"] == "failed"
    assert result["goals"][0]["execution_evidence"]["routes"][0]["status"] == "verified"
    snapshot = read(output / "checkpoint.json")
    assert snapshot["goals"][TARGET]["available"] is False
    assert snapshot["handoffs"] and all(not task["available"] for task in snapshot["handoffs"])
    assert result["goals"][0]["answer"] is None
    published = {event["payload"]["kind"].lower(): event["payload"]["chunk"] for event in events(output)
                 if event["type"] == "lesson.chunk_ready" and event["payload"].get("kind") in ("D3", "D4")}
    for kind in ("d3", "d4"):
        assert result["goals"][0][kind] == published[kind]
        assert read(output / "goals/goal-001" / (kind + ".json")) == published[kind]


@pytest.mark.parametrize("dispatch,status", [(later_conflict, "conflict"), (later_unknown, "no_verified_route")])
def test_later_consistency_failure_revokes_earlier_completion(tmp_path, dispatch, status):
    output = tmp_path / "out"
    result = runner.run_sample(upstream(tmp_path), output, hooks={"calculation_dispatch": dispatch})
    goal = result["goals"][0]
    assert all(route["status"] == "verified" for route in goal["routes"])
    assert goal["status"] == status and goal["answer"] is None
    snapshot = read(output / "checkpoint.json")
    assert snapshot["goals"][TARGET]["available"] is False
    assert len(snapshot["handoffs"]) == 1 and snapshot["handoffs"][0]["status"] == "cancelled"
    completions = [event for event in events(output) if event["payload"].get("kind") == "route_completion"]
    assert len(completions) == 1


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_budget_is_rejected_before_creating_output(tmp_path, value):
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="invalid_options"):
        runner.run_sample("unused.json", output, solve_budget_seconds=value)
    assert not output.exists()
