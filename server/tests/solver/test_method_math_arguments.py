import json
from copy import deepcopy
from dataclasses import replace

import pytest
from _math_runtime_binding_support import (
    CASES,
    ROOT,
    assert_expected,
    binding,
    candidate,
    execution_audit,
    replay,
    replay_errors,
    reviewed_authority,
)

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContentCompiler,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.method_math_arguments import (
    MATH_EXPRESSIONS,
    MethodMathArgumentError,
    MethodMathArgumentResolver,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import StrategyPlanner


def resolver_for(bound):
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        bound.inputs.family_spec, bound.inputs.method_specs
    )
    return MethodMathArgumentResolver(
        bound.bundle, bound.planning_context, bound.binding_catalog, catalog
    )


@pytest.mark.parametrize("authored", [False, True], ids=["recorded", "authored"])
@pytest.mark.parametrize("case", CASES)
def test_ten_plans_have_identical_canonical_calls_and_execution(
    case, authored, tmp_path
):
    bound = binding(case, authored)
    original = replay(case, bound, tmp_path / "source")
    assert original.status == "accepted", replay_errors(original)
    resolver = resolver_for(bound)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(bound.planning_context)
    content = functional_plan_content_from_plan(
        original.final_plan, frame=frame
    ).to_payload()
    math_content, _ = resolver.transform(content, encode=True)
    decoded, audit = resolver.transform(math_content)
    assert decoded == content
    assert audit and all(a["source_paths"] and a["source_unit_ids"] for a in audit)
    compiler = FunctionalPlanContentCompiler()
    source_compiled = compiler.compile_payload(
        content, frame=frame, capability_catalog=resolver.catalog
    )
    math_compiled = compiler.compile_payload(
        math_content,
        frame=frame,
        capability_catalog=resolver.catalog,
        math_argument_resolver=resolver,
    )
    assert math_compiled.report == source_compiled.report
    assert math_compiled.plan.to_payload() == source_compiled.plan.to_payload()
    folder = tmp_path / "math"
    folder.mkdir()
    (folder / f"{case}.functional-plan-content.json").write_text(
        json.dumps(math_content, ensure_ascii=False)
    )
    planner = StrategyPlanner(
        ContextBuilder().build(bound.bundle.build_solver_problem()),
        problem_authority=reviewed_authority(bound),
        argument_encoding=MATH_EXPRESSIONS,
        scoped_functional_plan_fixture_dir=folder,
    )
    result = planner.run_scoped(bound.inputs, max_attempts=1)
    assert result.status == "accepted", replay_errors(result)
    assert result.final_plan.to_payload() == original.final_plan.to_payload()
    # Includes exact Method input values, identities, dependencies, versions,
    # goal verification and answers. No normalization of mismatches is allowed.
    assert execution_audit(bound, result) == execution_audit(bound, original)
    assert result.attempts[0].math_argument_bindings
    assert_expected(case, bound, result)


@pytest.mark.parametrize("text", ["a=1", "1=a", "2*a=2", "a/2=1/2"])
def test_equivalent_conditions_bind_same_existing_evidence(text):
    resolver = resolver_for(binding(CASES[3]))
    ref, audit = resolver.resolve(
        "quadratic_from_constraints", "known_coefficients", text, scope_id="i"
    )
    assert ref == "symbol_value_a"
    assert audit["source_paths"] == ["/root/children/0/facts/0"]


def test_perpendicular_line_spelling_binds_to_right_angle_condition():
    raw = candidate("tj-2026-hexi-yimo-25", authored=True)
    raw["root"]["children"][1]["facts"][5] = "line(A,C) ⟂ line(A,D)"
    resolver = resolver_for(binding("tj-2026-hexi-yimo-25", payload=raw))

    ref, audit = resolver.resolve(
        "right_angle_equal_length_candidates",
        "angle",
        "line(A,C) ⟂ line(A,D)",
        scope_id="ii",
    )

    assert ref.startswith("right_angle_equal_length_")
    assert "/root/children/1/facts/5" in audit["source_paths"]


def test_math_binding_failure_preserves_decoded_content_for_retry(tmp_path) -> None:
    bound = binding(CASES[3])
    baseline = replay(CASES[3], bound, tmp_path)
    assert baseline.status == "accepted", replay_errors(baseline)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        bound.planning_context
    )
    content = functional_plan_content_from_plan(
        baseline.final_plan, frame=frame
    ).to_payload()
    resolver = resolver_for(bound)
    math_content, _ = resolver.transform(content, encode=True)
    math_content["goal_plans"]["i.P"]["steps"][0]["args"][
        "known_coefficients"
    ] = ["z = 99"]

    compilation = FunctionalPlanContentCompiler().compile_payload(
        math_content,
        frame=frame,
        capability_catalog=resolver.catalog,
        math_argument_resolver=resolver,
    )

    assert not compilation.report.ok
    assert compilation.plan is None
    assert compilation.normalized_payload == math_content


@pytest.mark.parametrize(
    "scope,text", [("ii", "a=1"), ("i", "b=99"), ("problem", "a=1"), ("i", "z=1")]
)
def test_wrong_or_invisible_conditions_do_not_create_facts(scope, text):
    resolver = resolver_for(binding(CASES[3]))
    with pytest.raises(MethodMathArgumentError, match="functional.math_argument_"):
        resolver.resolve(
            "quadratic_from_constraints", "known_coefficients", text, scope_id=scope
        )


def test_same_named_objects_keep_scope_identity_and_parameter_kind():
    resolver = resolver_for(binding(CASES[3]))
    _, second = resolver.resolve(
        "quadratic_from_constraints", "curve_point", "A", scope_id="ii"
    )
    _, third = resolver.resolve(
        "quadratic_from_constraints", "curve_point", "A", scope_id="iii"
    )
    assert second["source_unit_ids"] != third["source_unit_ids"]
    assert (
        resolver.resolve(
            "quadratic_from_constraints", "free_parameters", "b", scope_id="iii"
        )[0]
        == "b"
    )
    with pytest.raises(MethodMathArgumentError):
        resolver.resolve(
            "quadratic_from_constraints", "curve_point", "M", scope_id="ii"
        )
    with pytest.raises(MethodMathArgumentError):
        resolver.resolve(
            "quadratic_from_constraints", "free_parameters", "b=2", scope_id="i"
        )


def test_point_coordinate_spelling_falls_back_to_existing_point_identity():
    resolver = resolver_for(binding(CASES[3]))
    ref, audit = resolver.resolve(
        "quadratic_from_constraints", "curve_point", "A=(-1,0)", scope_id="ii"
    )
    assert ref == "A"
    assert audit["source_unit_ids"]
    assert audit["source_paths"]
    with pytest.raises(MethodMathArgumentError, match="unresolved"):
        resolver.resolve(
            "quadratic_from_constraints", "curve_point", "A=(-1,1)", scope_id="ii"
        )


def test_geometry_equivalence_preserves_ratio_and_ray_orientation():
    resolver = resolver_for(binding(CASES[2]))
    method = "equal_length_ray_path_reduction"
    assert resolver.resolve(method, "point_on_ray", "N∈ray(C,D)", scope_id="ii")[0]
    for text in ("N∈ray(D,C)", "N∈line(C,D)"):
        with pytest.raises(MethodMathArgumentError, match="unresolved"):
            resolver.resolve(method, "point_on_ray", text, scope_id="ii")
    resolver = resolver_for(binding(CASES[0]))
    method = "coupled_segment_endpoint_replacement_path_minimum"
    expected = resolver.resolve(
        method, "segment_binding_relation", "DE=sqrt(2)*NG", scope_id="ii"
    )[0]
    assert (
        resolver.resolve(
            method, "segment_binding_relation", "NG*sqrt(2)=ED", scope_id="ii"
        )[0]
        == expected
    )
    with pytest.raises(MethodMathArgumentError, match="unresolved"):
        resolver.resolve(
            method, "segment_binding_relation", "sqrt(2)*DE=NG", scope_id="ii"
        )


def test_minimum_target_value_and_attainment_are_not_interchangeable():
    resolver = resolver_for(binding(CASES[3]))
    method = "weighted_axis_path_minimum"
    expected = resolver.resolve(
        method, "path_minimum_target", "sqrt(2)*MN+AN", scope_id="iii"
    )[0]
    assert (
        resolver.resolve(
            method, "path_minimum_target", "AN+MN*sqrt(2)", scope_id="iii"
        )[0]
        == expected
    )
    for text in (
        "min(sqrt(2)*MN+AN)",
        "min_{n}(AN+MN*sqrt(2))",
        "min_{b}(AN+sqrt(2)*MN)",
        "min(sqrt(2)*MN+AN)=21/4",
        "sqrt(2)*MN+AN=min(sqrt(2)*MN+AN)",
    ):
        with pytest.raises(MethodMathArgumentError):
            resolver.resolve(method, "path_minimum_target", text, scope_id="iii")
    assert (
        resolver.resolve(
            "parameter_from_expression_value",
            "minimum_value",
            "21/4=min(AN+sqrt(2)*MN)",
            scope_id="iii",
        )[0]
        == "minimum_value"
    )
    with pytest.raises(MethodMathArgumentError):
        resolver.resolve(
            "evaluate_point_at_parameter",
            "point",
            "min(sqrt(2)*MN+AN)=21/4",
            scope_id="iii",
        )


def test_coupled_path_target_uses_plain_objective_expression():
    resolver = resolver_for(binding(CASES[0]))
    ref, audit = resolver.resolve(
        "coupled_segment_endpoint_replacement_path_minimum",
        "path_minimum_target",
        "EG+FG",
        scope_id="ii_1",
    )
    assert ref == "path_minimum_target_e_g_f"
    assert audit["source_unit_ids"]
    with pytest.raises(MethodMathArgumentError, match="expects the path expression"):
        resolver.resolve(
            "coupled_segment_endpoint_replacement_path_minimum",
            "path_minimum_target",
            "min(EG+FG)",
            scope_id="ii_1",
        )


def test_ambiguous_typed_evidence_is_rejected_without_selecting_a_winner():
    resolver = resolver_for(binding(CASES[3]))
    source = next(
        s
        for s in resolver.sources
        if s.authority.owner_scope_id == "i" and s.expressions == ("a = 1",)
    )
    # Simulate two catalog entries supported by the same mathematical evidence.
    # There is deliberately no priority, newest-entry, or shortest-ref policy.
    other = replace(
        source,
        authority=replace(
            source.authority,
            semantic_ref=replace(
                source.authority.semantic_ref, ref="another_coefficient_evidence"
            ),
        ),
    )
    resolver.sources = (*resolver.sources, other)
    with pytest.raises(MethodMathArgumentError, match="ambiguous"):
        resolver.resolve(
            "quadratic_from_constraints", "known_coefficients", "a=1", scope_id="i"
        )


def test_exact_results_and_invalid_shapes_stay_owned_by_original_compiler():
    bound = binding(CASES[3])
    resolver = resolver_for(bound)
    exact = {"step_id": "producer", "return": "minimum_expression"}
    assert resolver.resolve(
        "parameter_from_expression_value", "expression", exact, scope_id="iii"
    ) == (exact, None)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(bound.planning_context)
    for value in (
        [],
        {"scope_steps": []},
        {"goal_plans": False},
        {"scope_steps": {"i": [False]}},
    ):
        result = FunctionalPlanContentCompiler().compile_payload(
            value,
            frame=frame,
            capability_catalog=resolver.catalog,
            math_argument_resolver=resolver,
        )
        assert not result.report.ok


def test_renamed_objects_bind_and_execute_without_case_name_rules(tmp_path):
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
    bound = binding(CASES[3], payload=raw)
    baseline = replay(CASES[3], bound, tmp_path)
    assert baseline.status == "accepted", replay_errors(baseline)
    resolver = resolver_for(bound)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(bound.planning_context)
    content = functional_plan_content_from_plan(
        baseline.final_plan, frame=frame
    ).to_payload()
    math, _ = resolver.transform(content, encode=True)
    assert "Ω" in json.dumps(math, ensure_ascii=False)
    assert resolver.transform(math)[0] == content


def test_failed_plan_has_identical_scope_retry_and_committed_state(tmp_path):
    bound = binding(CASES[3])
    baseline = replay(CASES[3], bound, tmp_path)
    assert baseline.status == "accepted", replay_errors(baseline)
    resolver = resolver_for(bound)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(bound.planning_context)
    correct = functional_plan_content_from_plan(
        baseline.final_plan, frame=frame
    ).to_payload()
    failed = deepcopy(correct)
    failed["goal_plans"]["iii.b"]["steps"][0]["args"]["free_parameters"] = "n"
    goals = deepcopy(correct["goal_plans"])
    for goal in goals.values():
        for step in goal.get("steps", []):
            step.pop("return_expectations", None)
    repair = {
        "schema_version": "functional-scope-repair/v1",
        "scope_replacements": {
            "iii": {
                "scope_steps": correct.get("scope_steps", {}).get("iii", []),
                "goals": {"iii.b": goals["iii.b"]},
            }
        },
    }

    class Client:
        provider_name = "recorded-test"

        def __init__(self, math):
            self.responses = [
                resolver.transform(p, encode=True)[0] if math else p
                for p in (failed, repair)
            ]

        def complete(self, request):
            return json.dumps(self.responses.pop(0), ensure_ascii=False)

    results = []
    for mode in ("source-ref", MATH_EXPRESSIONS):
        planner = StrategyPlanner(
            ContextBuilder().build(bound.bundle.build_solver_problem()),
            problem_authority=reviewed_authority(bound),
            mode="deepseek",
            client=Client(mode == MATH_EXPRESSIONS),
            argument_encoding=mode,
        )
        results.append(planner.run_scoped(bound.inputs, max_attempts=2))
    source, math = results
    for result in results:
        assert result.status == "accepted", replay_errors(result)
        assert [a.planner_protocol for a in result.attempts] == [
            "functional-plan-content/v2",
            "functional-scope-repair/v1",
        ]
        assert result.attempts[1].scope_authority.editable_scope_refs == ("iii",)
        assert result.attempts[1].restored_call_ids
    for old, new in zip(source.attempts, math.attempts):
        assert old.requested_restore_call_ids == new.requested_restore_call_ids
        assert old.restored_call_ids == new.restored_call_ids
        assert (
            old.execution.checkpoint.authority_payload()
            == new.execution.checkpoint.authority_payload()
        )
        if old.scope_authority:
            assert (
                old.scope_authority.debug_payload()
                == new.scope_authority.debug_payload()
            )
            assert (
                resolver.transform(old.payload["annotated_previous_plan"], encode=True)[
                    0
                ]
                == new.payload["annotated_previous_plan"]
            )
    assert execution_audit(bound, source) == execution_audit(bound, math)

    # Scope retry must expose the same mathematical spelling as the first
    # content prompt.  Canonical SourceRef values are internal bookkeeping and
    # must not leak into the annotated math retry context.
    retry_prompt_payload = json.dumps(
        math.attempts[1].payload["annotated_previous_plan"], ensure_ascii=False
    )
    assert "path_minimum_target_" not in retry_prompt_payload
    assert "sqrt(2)*MN" in retry_prompt_payload
    from shuxueshuo_server.solver.runtime.strategy_payload import StrategyPromptRenderer

    retry_prompt = StrategyPromptRenderer().render_scope_repair(
        math.attempts[1].payload
    )
    assert "不要复制内部 SourceRef" in retry_prompt.system
    assert "路径目标用`min(sqrt(2)*MN+AN)`" not in retry_prompt.system

    from shuxueshuo_server.solver.runtime.functional_scope_retry import (
        FunctionalScopeRepairCompiler,
        FunctionalScopeRetryError,
    )

    authority = math.attempts[1].scope_authority
    before = authority.debug_payload()
    bad, _ = resolver.transform(repair, encode=True)
    bad["scope_replacements"]["iii"]["goals"]["iii.b"]["steps"][0]["args"][
        "free_parameters"
    ] = "z"
    with pytest.raises(
        FunctionalScopeRetryError, match="functional.math_argument_invalid"
    ) as error:
        FunctionalScopeRepairCompiler().parse_json(
            json.dumps(bad),
            authority=authority,
            capability_catalog=resolver.catalog,
            math_argument_resolver=resolver,
        )

    assert error.value.retryable
    assert authority.debug_payload() == before
    # The original closed-Scope boundary is checked before mathematical binding.
    bad["scope_replacements"]["i"] = bad["scope_replacements"].pop("iii")
    with pytest.raises(
        FunctionalScopeRetryError, match="functional.scope_repair_schema_invalid"
    ):
        FunctionalScopeRepairCompiler().parse_json(
            json.dumps(bad),
            authority=authority,
            capability_catalog=resolver.catalog,
            math_argument_resolver=resolver,
        )


@pytest.mark.parametrize("encoding", ["source-ref", MATH_EXPRESSIONS])
def test_live_harness_records_existing_terminal_executor_failure_without_retry(
    encoding, tmp_path, monkeypatch
):
    import pickle

    from tools import compare_method_math_arguments as comparison

    raw = json.loads(
        (
            ROOT
            / "server/tests/solver/fixtures/method-math-arguments/heping-ermo-missing-curve-state.content.json"
        ).read_text()
    )
    bound = binding(CASES[1])
    if encoding == "source-ref":
        raw, _ = resolver_for(bound).transform(raw)

    class Client:
        provider_name = "recorded-regression"
        calls = 0

        def complete(self, request):
            self.calls += 1
            return json.dumps(raw, ensure_ascii=False)

    client = Client()

    class Config:
        max_llm_attempts = 3

        def build_llm_client(self, **kwargs):
            return client

    monkeypatch.setattr(
        comparison.SolverRuntimeConfig, "from_sources", lambda **kw: Config()
    )
    result = comparison.live_job(str(tmp_path), CASES[1], encoding, 1, "test-freeze")
    assert client.calls == 1
    assert result["status"] == "execution_failed"
    assert result["terminal_exception"]["type"] == "FunctionalBindingContextError"
    assert (
        "intercept_A.parabola[0] has no StateVersionId"
        in result["terminal_exception"]["message"]
    )
    assert result["attempts"][0]["errors"][0]["retryable"] is False
    assert pickle.loads(pickle.dumps(result)) == result
    assert (
        comparison.live_job(str(tmp_path), CASES[1], encoding, 1, "test-freeze")
        == result
    )
    assert client.calls == 1
