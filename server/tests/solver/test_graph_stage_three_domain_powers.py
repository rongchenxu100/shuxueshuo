"""Integer powers retain original domain guards through the shared method."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_one.function_domain import (
    inspect_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    interaction,
    runner,
    selection,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_domain import (
    _critical,
    _evaluate,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    endpoint_check,
    verify,
)
from tests.solver.test_graph_stage_three_execution import constructed_upstream, store
from tests.solver.test_graph_stage_three_function_domain import (
    METHOD,
    TARGET,
    candidate,
    execute,
)

Q01_EXPRESSION = "(x+4)^0*(x^2-1)/(x-1)"
Q01_DOMAIN = sp.S.Reals - sp.FiniteSet(-4, 1)


@pytest.mark.parametrize("expression,expected", [
    (Q01_EXPRESSION, Q01_DOMAIN),
    ("(x-1)^0", sp.S.Reals - sp.FiniteSet(1)),
    ("(x-1)^1", sp.S.Reals),
    ("x^2", sp.S.Reals),
    ("x^12", sp.S.Reals),
    ("(x^8)^8", sp.S.Reals),
    ("sqrt(x-1)^2", sp.Interval(1, sp.oo)),
    ("((x-1)/(x-1))^2", sp.S.Reals - sp.FiniteSet(1)),
    ("((x+4)^0)^2", sp.S.Reals - sp.FiniteSet(-4)),
    ("(x+4)^0*sqrt(x-1)^2/(x-2)",
     sp.Union(sp.Interval.Ropen(1, 2), sp.Interval.open(2, sp.oo))),
])
def test_integer_powers_execute_with_original_definedness(expression, expected):
    original = candidate(expression)
    context, state = execute(original)
    assert state["status"] == "method_complete", state["diagnostics"]
    actual = driver.export_values(state)["feasible_set"]
    assert actual == expected
    assert state["verification"]["status"] == "verified"
    assert verify(original, TARGET, context, actual)["status"] == "verified"
    assert endpoint_check(original, TARGET, actual)["status"] == "passed"
    chunks, pending = interaction.compile_route(state["interaction_seeds"], interaction.load_registry())
    assert not pending and len(chunks) == 4
    for chunk, _ in chunks:
        assert chunk["status"] == "interactive", chunk
        interaction.validate_chunk(chunk)


def test_q01_condition_and_endpoint_provenance_survives_cancellation():
    original = candidate(Q01_EXPRESSION)
    context, state = execute(original)
    assert state["status"] == "method_complete", state["diagnostics"]
    calls = [call for step in state["trajectory"]["steps"] for call in step["calls"]]
    extracted = calls[0]["outputs"]["constraints"]
    x = sp.Symbol("x", real=True)
    assert [decode_value(row["condition"]["exact"]) for row in extracted] == [sp.Ne(x + 4, 0), sp.Ne(x - 1, 0)]
    assert [row["ast_path"] for row in extracted] == [[1, 1, 1], [2]]
    assert [row["kind"] for row in extracted] == ["zero_power_base_nonzero", "denominator_nonzero"]
    assert [row["basis_refs"] for row in extracted] == [
        ["integer-power#zero-exponent"], ["rational-expression#meaning"]]
    for row in extracted:
        assert row["source_ref"] == "/root/definitions/0"
        node = context["domain_goal"]["expression_ast"]
        for part in row["ast_path"]:
            node = node[part]
        assert row["expression_ast"] == node
    solve = next(call for call in calls if call["capability"] == "solve_conditions")
    assert solve["public_ref"] == "skill-inequality-transform"
    assert driver.export_values(state)["feasible_set"] == Q01_DOMAIN
    points, polynomials = _critical(context["domain_goal"])
    assert points == [-4, 1]
    assert {tuple(row["ast_path"]) for row in polynomials} == {(1, 1, 1), (2,)}
    endpoints = endpoint_check(original, TARGET, Q01_DOMAIN)
    assert endpoints["status"] == "passed"
    for row in endpoints["points"]:
        point = decode_value(row["point"]["exact"])
        failures = [source for source in row["evidence"]["sources"] if not source["holds"]]
        (failure,) = failures
        assert not row["included"] and not row["holds"] and row["passed"]
        expected = extracted[0 if point == -4 else 1]
        assert {key: failure[key] for key in ("source_ref", "ast_path", "kind", "basis_refs")} == {
            key: expected[key] for key in ("source_ref", "ast_path", "kind", "basis_refs")}


@pytest.mark.parametrize("wrong,omitted", [
    (sp.S.Reals - sp.FiniteSet(1), -4),
    (sp.S.Reals - sp.FiniteSet(-4), 1),
])
def test_independent_verifier_rejects_either_lost_q01_guard(wrong, omitted):
    original = candidate(Q01_EXPRESSION)
    context = build_context(original, TARGET)
    result = verify(original, TARGET, context, wrong)
    assert result["status"] == "math_failed"
    assert result["counterexample"]["variable"]["expression"] == str(omitted)
    assert result["counterexample"]["original_holds"] is False
    assert result["counterexample"]["candidate_includes"] is True


def test_positive_power_has_no_new_guard_but_does_not_restore_undefined_base():
    for expression,point,defined in [("x^2", 0, True), ("(x+4)^0", -4, False),
                                     ("sqrt(x-1)^2", 0, False), ("((x-1)/(x-1))^2", 1, False)]:
        description = inspect_domain_target(candidate(expression), TARGET)
        assert _evaluate(description["expression_ast"], sp.Integer(point))[0] is defined
    _, state = execute(candidate("x^2"))
    values = decode_value(state["result"])["domain_evidence"]
    assert values["constraints"] == [] and values["domain"] == sp.S.Reals


@pytest.mark.parametrize("expression", [
    "x^-1", "x^(1/2)", "x^m", "x^13", "(x^9)^8", "(x^2-2)^0", "1/(x^2-2)",
])
def test_forged_features_and_direct_method_cannot_bypass_power_admission(expression):
    original = candidate(expression)
    context = build_context(original, TARGET)
    fake = [{"target_ref": TARGET, "feature_id": "function_domain", "status": "known",
             "value": {"structure_supported": True}}]
    assert selection.evaluate_goal(original, TARGET, fake, "type-function-domain")["status"] == "no_applicable_method"
    state = driver.create_state(features=fake, context=context, method=METHOD, route_id="domain-intersection",
                                branch="direct", target_ref=TARGET, run_id="power-override", lesson_version="v2")
    assert state["status"] == "capability_gap"


def test_q01_runs_through_shared_durable_execution_and_interactions(tmp_path):
    original = candidate(Q01_EXPRESSION)
    original["original_text"] = r"求函数 $f(x)=(x+4)^0\frac{x^2-1}{x-1}$ 的定义域。"
    features = extract_features(original)
    assert features["ok"], features
    source = constructed_upstream(tmp_path, original)
    result = runner.run_sample(source, tmp_path / "out")
    (goal,) = result["goals"]
    assert goal["status"] == "solved", goal
    (route,) = goal["routes"]
    assert route["status"] == "verified", route
    assert decode_value(route["feasible_set_exact"]) == Q01_DOMAIN
    durable = store(tmp_path / "out")
    public = durable.snapshot()
    assert len(public["math_steps"]) == len(public["interactions"]) == 4
    assert all(chunk["status"] == "interactive" for chunk in public["interactions"])
    assert any(event["type"] == "lesson.route_status" and event["payload"]["status"] == "verified"
               for event in durable.events())
