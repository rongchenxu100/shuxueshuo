"""Domain execution, independent original-syntax proof and shared stream acceptance."""

import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    interaction,
    runner,
    selection,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities import REGISTRY
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.goals import (
    finalize_goal,
    verify_goal_answer,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    endpoint_check,
    verify,
)
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_stage_three_execution import constructed_upstream, store
from tests.solver.test_graph_stage_three_methods import finish

TARGET = "/root/goals/0"
METHOD = "method-domain-intersection"
Q15 = sp.Union(sp.Interval.Ropen(1, 2), sp.Interval.open(2, sp.oo))


def candidate(expression="sqrt(x-1)/(x-2)", input_domain=None):
    goal = {"kind": "find_domain", "object": "f"}
    if input_domain is not None:
        goal["input_domain"] = input_domain
    return {
        "original_text": "求函数定义域",
        "root": {"definitions": ["f(x)=" + expression], "facts": [], "goals": [goal]},
    }


def execute(c):
    context = build_context(c, TARGET)
    state = finish(
        driver.create_state(
            features=extract_features(c)["features"],
            context=context,
            method=METHOD,
            route_id="domain-intersection",
            branch="direct",
            target_ref=TARGET,
            run_id="domain-test",
            lesson_version="v1",
        )
    )
    if state["status"] == "method_complete":
        feasible = driver.export_values(state)["feasible_set"]
        state["verification"] = verify(c, TARGET, context, feasible)
        if state["verification"]["status"] == "verified":
            state = driver.append_endpoint(
                state, feasible, endpoint_check(c, TARGET, feasible)
            )
    return context, state


def test_day_zero_real_shared_not_equal_capability():
    x = sp.Symbol("x", real=True)
    assert REGISTRY["solve_conditions"](
        conditions=[sp.Ne(x - 2, 0, evaluate=False)], combiner="all", variable=x
    )["outputs"]["solution"] == sp.S.Reals - sp.FiniteSet(2)
    assert (
        REGISTRY["solve_conditions"](
            conditions=[
                sp.Ge(x - 1, 0, evaluate=False),
                sp.Ne(x - 2, 0, evaluate=False),
            ],
            combiner="all",
            variable=x,
        )["outputs"]["solution"]
        == Q15
    )


@pytest.mark.parametrize(
    "expr,interval,expected",
    [
        ("sqrt(x-1)/(x-2)", None, Q15),
        (
            "sqrt(x-3)/(x-5)",
            None,
            sp.Union(sp.Interval.Ropen(3, 5), sp.Interval.open(5, sp.oo)),
        ),
        ("sqrt(x-2)/(x-2)", None, sp.Interval.open(2, sp.oo)),
        ("sqrt(x-1)/(x+1)", None, sp.Interval(1, sp.oo)),
        (
            "sqrt(3-x)/(x-2)",
            None,
            sp.Union(sp.Interval.open(-sp.oo, 2), sp.Interval.Lopen(2, 3)),
        ),
        ("1/sqrt(x-2)", None, sp.Interval.open(2, sp.oo)),
        ("sqrt(x-2)+sqrt(1-x)", None, sp.S.EmptySet),
        ("sqrt(x-1)/(x-2)", "[0,1]", sp.FiniteSet(1)),
        ("(x-2)/(x-2)", None, sp.S.Reals - sp.FiniteSet(2)),
        ("sqrt(-2*x+4)", None, sp.Interval(-sp.oo, 2)),
        ("sqrt(x-1)/(x-2)", "(1,2)", sp.Interval.open(1, 2)),
        ("1/sqrt(-1)", None, sp.S.EmptySet),
        ("1/sqrt(0)", None, sp.S.EmptySet),
        ("sqrt(0)", None, sp.S.Reals),
        ("sqrt(4)", None, sp.S.Reals),
        ("1/0", None, sp.S.EmptySet),
        ("sqrt(x^2-1)", None, sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(1, sp.oo))),
        ("sqrt(3-2*x-x^2)", None, sp.Interval(-3, 1)),
        ("1/sqrt(3-2*x-x^2)", None, sp.Interval.open(-3, 1)),
        (
            "(2*x+1)/((2*x-1)^0*sqrt(3-2*x-x^2))",
            None,
            sp.Union(sp.Interval.open(-3, sp.Rational(1, 2)), sp.Interval.open(sp.Rational(1, 2), 1)),
        ),
    ],
)
def test_original_domain_exact_boundary_cases(expr, interval, expected):
    c = candidate(expr, interval)
    context, state = execute(c)
    assert state["status"] == "method_complete", state["diagnostics"]
    actual = driver.export_values(state)["feasible_set"]
    assert actual == expected
    assert verify(c, TARGET, context, actual)["status"] == "verified"
    assert endpoint_check(c, TARGET, actual)["status"] == "passed"
    answer = finalize_goal(c["root"]["goals"][0], actual)
    assert answer["kind"] == "find_domain"
    assert verify_goal_answer(c["root"]["goals"][0], actual, answer)["status"] == "set"
    chunks, pending = interaction.compile_route(
        state["interaction_seeds"], interaction.load_registry()
    )
    assert not pending and len(chunks) == 4
    for chunk, diagnostics in chunks:
        assert chunk["status"] == "interactive", (expr, chunk, diagnostics)
        interaction.validate_chunk(chunk)
    assert len(chunks[-1][0]["parts"][0]["expected_answer"]["one_of"]) == 2


def test_original_provenance_and_no_shared_skill_boundary_drift():
    context, state = execute(candidate())
    calls = [call for step in state["trajectory"]["steps"] for call in step["calls"]]
    extracted = calls[0]["outputs"]["constraints"]
    assert [row["ast_path"] for row in extracted] == [[1, 2], [2]]
    assert all(row["source_ref"] == "/root/definitions/0" for row in extracted)
    assert [r["basis_refs"] for r in extracted] == [
        ["square-root-expression#meaning"],
        ["rational-expression#meaning"],
    ]
    assert calls[0]["public_ref"] == "skill-expression-defined"
    solve = next(call for call in calls if call["capability"] == "solve_conditions")
    assert solve["public_ref"] == "skill-inequality-transform"
    assert all("quantif" not in check["kind"] for check in solve["postconditions"])
    assert len(state["fragments"]) == 4
    chunks, _ = interaction.compile_route(
        state["interaction_seeds"], interaction.load_registry()
    )
    regions = chunks[0][0]["parts"][0]["source_regions"]
    assert regions["expression_ast"] == context["domain_goal"]["expression_ast"]
    assert [row["option_value"] for row in regions["regions"]] == ["o1", "o2"]


@pytest.mark.parametrize(
    "wrong", [sp.Interval(1, sp.oo), sp.Interval.open(1, 2), sp.S.Reals, sp.S.EmptySet]
)
def test_verifier_rejects_incomplete_or_extra_sets(wrong):
    c = candidate()
    context = build_context(c, TARGET)
    checked = verify(c, TARGET, context, wrong)
    assert checked["status"] == "math_failed" and checked["counterexample"]


def test_verifier_rejects_tampered_context_and_ignores_forged_features():
    c = candidate()
    context = build_context(c, TARGET)
    context["domain_goal"]["expression_ast"] = ["number", "1"]
    assert verify(c, TARGET, context, Q15)["status"] == "math_failed"
    assert (
        driver.create_state(
            features=[],
            context=context,
            method=METHOD,
            route_id="domain-intersection",
            branch="direct",
            target_ref=TARGET,
            run_id="bad",
            lesson_version="v1",
        )["status"]
        == "capability_gap"
    )


@pytest.mark.parametrize(
    "expression",
    ["sqrt(a*x-1)/(x-2)", "sqrt(x^3-1)", "sqrt(1/(x-1))", "abs(x^2)", "(x^2-1)^0"],
)
def test_direct_type_and_method_overrides_cannot_bypass_admission(expression):
    c = candidate(expression)
    context = build_context(c, TARGET)
    fake = [
        {
            "target_ref": TARGET,
            "feature_id": "function_domain",
            "status": "known",
            "value": {"structure_supported": True},
        }
    ]
    selected = selection.evaluate_goal(c, TARGET, fake, "type-function-domain")
    assert selected["status"] == "no_applicable_method"
    state = driver.create_state(
        features=fake,
        context=context,
        method=METHOD,
        route_id="domain-intersection",
        branch="direct",
        target_ref=TARGET,
        run_id="bad",
        lesson_version="v1",
    )
    assert state["status"] == "capability_gap"


def test_direct_override_rejects_other_goal_and_hidden_constraints():
    c = candidate()
    c["root"]["facts"] = ["x>3"]
    assert (
        selection.evaluate_goal(c, TARGET, [], "type-function-domain")["status"]
        == "no_applicable_method"
    )
    other = {
        "original_text": "求a范围",
        "root": {
            "facts": ["∀x∈ℝ:x^2+a>=0"],
            "goals": [{"kind": "find_range", "symbol": "a"}],
        },
    }
    assert (
        selection.evaluate_goal(other, TARGET, [], "type-function-domain")["status"]
        == "no_applicable_method"
    )


def test_shared_store_runner_events_and_projection(tmp_path):
    c = candidate()
    source = constructed_upstream(tmp_path, c)
    result = runner.run_sample(source, tmp_path / "out")
    (goal,) = result["goals"]
    assert goal["status"] == "solved", goal
    (route,) = goal["routes"]
    assert route["status"] == "verified", route
    assert decode_value(route["feasible_set_exact"]) == Q15
    assert (
        goal["selection"]["rule"] is None
        and goal["selection"]["kind"] == "direct_method"
    )
    durable = store(tmp_path / "out")
    public = durable.snapshot()
    assert len(public["math_steps"]) == 4
    assert len(public["interactions"]) == 4
    assert all(chunk["status"] == "interactive" for chunk in public["interactions"])
    assert any(
        event["type"] == "lesson.route_status"
        and event["payload"]["status"] == "verified"
        for event in durable.events()
    )
    stage_two = json.loads(source.read_text())
    evidence = {
        "lesson": present_lesson(
            stage_two,
            extract_features(c)["features"],
            c["original_text"],
            "function-concepts-q15",
            candidate=c,
        ),
        "stream": public,
    }
    Path("/private/tmp/q15-shared-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2)
    )


def test_redundant_denominator_retains_original_condition_and_its_solution():
    _, state = execute(candidate("sqrt(x-1)/(x+1)"))
    calls = [call for step in state["trajectory"]["steps"] for call in step["calls"]]
    denominator = calls[0]["outputs"]["constraints"][1]
    x = sp.Symbol("x", real=True)
    assert denominator["ast_path"] == [2]
    assert denominator["source_ref"] == "/root/definitions/0"
    assert denominator["basis_refs"] == ["rational-expression#meaning"]
    assert decode_value(denominator["condition"]["exact"]) == sp.Ne(
        x + 1, 0, evaluate=False
    )
    solve = next(call for call in calls if call["capability"] == "solve_conditions")
    assert decode_value(
        solve["outputs"]["solutions"][1]["exact"]
    ) == sp.S.Reals - sp.FiniteSet(-1)
    assert driver.export_values(state)["feasible_set"] == sp.Interval(1, sp.oo)


def test_math_presentation_and_interaction_have_separate_revision_ownership():
    revisions = runner.fingerprint()
    prefix = "server/shuxueshuo_server/graph_lesson/stage_three/"
    assert prefix + "domain_presentation.py" in revisions
    assert prefix + "function_domain.py" in revisions
    assert prefix + "domain_interaction.py" not in revisions
    assert any(
        path.name == "domain_interaction.py" for path in interaction.ENGINE_FILES
    )


def test_number_lines_and_endpoint_projection_keep_exact_original_sources():
    _, state = execute(candidate())
    chunks, _ = interaction.compile_route(state["interaction_seeds"], interaction.load_registry())
    solution = chunks[2][0]["parts"][0]
    final = chunks[3][0]["parts"][0]
    assert len(solution["condition_number_lines"]) == 2
    assert len(final["condition_number_lines"]) == 2
    lines = final["condition_number_lines"] + [final["completion_number_line"]]
    assert all(line["bounds"] == lines[0]["bounds"] for line in lines)
    assert [(p["left"], p["right"], p["left_closed"], p["right_closed"])
            for p in final["completion_number_line"]["intervals"]] == [
                (1.0, 2.0, True, False), (2.0, None, False, False)]
    endpoints = final["endpoint_checks"]
    assert [(row["at"], row["included"], row["passed"]) for row in endpoints] == [
        (1.0, True, True), (2.0, False, True)]
    excluded = endpoints[1]
    assert "分母为 0" in excluded["reason"]
    assert any(source["source_ref"] == "/root/definitions/0" and source["ast_path"] == [2]
               and source["kind"] == "denominator_nonzero" and not source["holds"]
               for source in excluded["sources"])


def test_explicit_input_interval_has_its_own_line_ticks_and_endpoint_source():
    _, state = execute(candidate(input_domain="[0,1]"))
    chunks, _ = interaction.compile_route(state["interaction_seeds"], interaction.load_registry())
    final = chunks[3][0]["parts"][0]
    explicit = final["condition_number_lines"][-1]
    assert explicit["source_ref"] == "/root/goals/0/input_domain"
    assert explicit["condition_id"] == "input-domain"
    assert {tick["at"] for tick in explicit["ticks"]} == {0.0, 1.0, 2.0}
    assert final["completion_number_line"]["intervals"] == []
    assert [point["at"] for point in final["completion_number_line"]["points"]] == [1.0]
    assert any(source["source_ref"] == "/root/goals/0/input_domain"
               for row in final["endpoint_checks"] for source in row["sources"])
