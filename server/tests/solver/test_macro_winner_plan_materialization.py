from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateEvaluation,
    CandidateSearchReport,
    FunctionalPlanFragment,
    SearchCandidate,
)
from shuxueshuo_server.solver.runtime.macro_plan_materialization import (
    MacroExpansionRecord,
    MacroPlanMaterializationError,
    MacroWinnerPlanMaterializationRequest,
    macro_expansion_record_schema,
    materialize_macro_winner,
    rebase_macro_expansion_records,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroCandidateBindingAuthority,
    MacroPreparationAuthority,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedDerivedResultRef,
    ScopedFunctionalAnswerSource,
    ScopedFunctionalGoalPlan,
    ScopedFunctionalPlan,
    ScopedFunctionalScope,
    ScopedFunctionalStep,
    ScopedReturnBinding,
    ScopedStepResultRef,
    scoped_functional_plan_id,
)


pytestmark = pytest.mark.solver_contract


class _FunctionCatalog:
    def get(self, capability_id: str):
        if capability_id.startswith("function_"):
            returns = {
                "function_construct": (
                    SimpleNamespace(
                        name="point",
                        semantic_role="auxiliary_point",
                    ),
                ),
                "function_distance": (
                    SimpleNamespace(name="distance", semantic_role=None),
                ),
                "function_solve_parameter": (),
            }.get(capability_id, ())
            return SimpleNamespace(kind="function", returns=returns)
        return SimpleNamespace(kind="macro", returns=())


def _fixture():
    macro = ScopedFunctionalStep(
        step_id="macro_path",
        capability_id="macro_path_minimum",
        args={"target": ("path_target",)},
        return_bindings={
            "minimum_expression": ScopedReturnBinding(
                kind="derived",
                ref="minimum_value_expression",
            )
        },
        return_expectations={"minimum_expression": "open_expression"},
    )
    consumer = ScopedFunctionalStep(
        step_id="solve_parameter",
        capability_id="function_solve_parameter",
        args={
            "expression": (
                ScopedStepResultRef("macro_path", "minimum_expression"),
            )
        },
        return_bindings={},
        return_expectations={},
    )
    plan = ScopedFunctionalPlan(
        root_scope=ScopedFunctionalScope(
            scope_ref="problem",
            steps=(macro, consumer),
            goals=(
                ScopedFunctionalGoalPlan(
                    goal_ref="ii.a",
                    steps=(),
                    answer_from=ScopedFunctionalAnswerSource(
                        "macro_path",
                        "minimum_expression",
                    ),
                ),
            ),
        )
    )
    first = ScopedFunctionalStep(
        step_id="macro_path__construct",
        capability_id="function_construct",
        args={"source": ("A",)},
        return_bindings={
            "point": ScopedReturnBinding(kind="derived", ref="helper_point")
        },
        return_expectations={},
    )
    helper = ScopedDerivedResultRef(
        step_id=first.step_id,
        return_name="point",
        local_ref="helper_point",
        canonical_ref="problem::helper_point",
        domain_type="Point",
        semantic_role="auxiliary_point",
        owner_scope="problem",
    )
    second = ScopedFunctionalStep(
        step_id="macro_path__distance",
        capability_id="function_distance",
        args={"point": (helper,)},
        return_bindings={},
        return_expectations={},
    )
    fragment = FunctionalPlanFragment(
        scope_id="problem",
        steps=(first, second),
        exports={"minimum_expression": (second.step_id, "distance")},
    )
    candidate = SearchCandidate(
        candidate_id="candidate:direct",
        fragment=fragment,
        role_bindings={"fixed_point": "A"},
        strategy_id="direct",
    )
    evaluation = CandidateEvaluation(
        candidate_id=candidate.candidate_id,
        passed=True,
        standard_outputs={"minimum_expression": "sqrt(2)"},
        shadow_execution_signature="shadow:verified",
    )
    report = CandidateSearchReport(
        macro_id=macro.capability_id,
        winner_candidate_id=candidate.candidate_id,
        evaluations=(evaluation,),
        equivalent_candidate_ids=(candidate.candidate_id,),
    )
    winner = MacroCandidateBindingAuthority(
        macro_id=macro.capability_id,
        call_id=macro.step_id,
        scope_id="problem",
        candidate=candidate,
        allowed_source_handles=("A",),
        upstream_exact_state_signature="state:exact",
    )
    authority = MacroPreparationAuthority(
        planning_context_id="planning:test",
        problem_revision_id="revision:test",
        problem_semantic_hash="problem:test",
        plan_id=scoped_functional_plan_id(plan),
        call_id=macro.step_id,
        goal_unit_ids=("ii.a",),
        scope_id="problem",
        macro_id=macro.capability_id,
        implementation_id="implementation:test",
        catalog_signature="catalog:test",
        authored_roles={},
        candidate_dependency_envelope=("A",),
        upstream_exact_state_signature="state:exact",
        winner=winner,
        search_report=report,
    )
    return plan, MacroWinnerPlanMaterializationRequest(authority)


def test_macro_winner_replaces_one_step_with_ordinary_function_steps() -> None:
    plan, request = _fixture()

    materialized, record = materialize_macro_winner(
        plan,
        request,
        capability_catalog=_FunctionCatalog(),
    )

    assert [step.step_id for step in materialized.root_scope.steps] == [
        "macro_path__construct",
        "macro_path__distance",
        "solve_parameter",
    ]
    producer = materialized.root_scope.steps[1]
    assert producer.return_bindings["distance"].ref == (
        "minimum_value_expression"
    )
    assert producer.return_expectations["distance"] == "open_expression"
    consumer_ref = materialized.root_scope.steps[2].args["expression"][0]
    assert consumer_ref == ScopedStepResultRef(
        "macro_path__distance",
        "distance",
    )
    answer = materialized.root_scope.goals[0].answer_from
    assert (answer.step_id, answer.return_name) == (
        "macro_path__distance",
        "distance",
    )
    assert record.authored_plan_id == scoped_functional_plan_id(plan)
    assert record.materialized_plan_id == scoped_functional_plan_id(materialized)
    assert record.generated_step_ids == (
        "macro_path__construct",
        "macro_path__distance",
    )
    assert dict(record.export_map) == {
        "minimum_expression": ("macro_path__distance", "distance")
    }
    assert dict(record.chosen_roles) == {"fixed_point": "A"}
    assert {
        step_id: dict(roles)
        for step_id, roles in record.generated_return_roles.items()
    } == {
        "macro_path__construct": {"point": "auxiliary_point"},
        "macro_path__distance": {"distance": "distance"},
    }


def test_macro_expansion_record_round_trips_with_a_stable_signature() -> None:
    plan, request = _fixture()
    _materialized, record = materialize_macro_winner(
        plan,
        request,
        capability_catalog=_FunctionCatalog(),
    )

    payload = record.to_payload()

    assert not list(
        Draft202012Validator(macro_expansion_record_schema()).iter_errors(
            payload
        )
    )
    assert MacroExpansionRecord.from_payload(payload) == record


def test_macro_materialization_rejects_generated_macro_steps() -> None:
    plan, request = _fixture()
    bad_fragment = FunctionalPlanFragment(
        scope_id=request.fragment.scope_id,
        steps=(
            ScopedFunctionalStep(
                step_id="nested_macro",
                capability_id="macro_nested",
                args={},
                return_bindings={},
                return_expectations={},
            ),
        ),
        exports={"minimum_expression": ("nested_macro", "value")},
    )
    bad_candidate = replace_candidate_fragment(request, bad_fragment)

    with pytest.raises(MacroPlanMaterializationError) as error:
        materialize_macro_winner(
            plan,
            bad_candidate,
            capability_catalog=_FunctionCatalog(),
        )

    assert error.value.code == "planner.macro_contract_invalid"


def test_expansion_provenance_rebases_only_while_generated_steps_are_unchanged(
) -> None:
    plan, request = _fixture()
    materialized, record = materialize_macro_winner(
        plan,
        request,
        capability_catalog=_FunctionCatalog(),
    )
    unrelated = replace_root_step(
        materialized,
        "solve_parameter",
        lambda step: replace(step, intent="repair an unrelated consumer"),
    )

    rebased = rebase_macro_expansion_records((record,), unrelated)

    assert len(rebased) == 1
    assert rebased[0].materialized_plan_id == scoped_functional_plan_id(
        unrelated
    )
    changed_generated = replace_root_step(
        unrelated,
        "macro_path__construct",
        lambda step: replace(step, intent="LLM replaced the generated step"),
    )
    assert rebase_macro_expansion_records(rebased, changed_generated) == ()


def replace_candidate_fragment(
    request: MacroWinnerPlanMaterializationRequest,
    fragment: FunctionalPlanFragment,
) -> MacroWinnerPlanMaterializationRequest:
    authority = request.authority
    candidate = replace(authority.winner.candidate, fragment=fragment)
    winner = replace(authority.winner, candidate=candidate)
    evaluation = CandidateEvaluation(
        candidate_id=candidate.candidate_id,
        passed=True,
        standard_outputs={"minimum_expression": "sqrt(2)"},
        shadow_execution_signature="shadow:verified",
    )
    report = CandidateSearchReport(
        macro_id=authority.macro_id,
        winner_candidate_id=candidate.candidate_id,
        evaluations=(evaluation,),
        equivalent_candidate_ids=(candidate.candidate_id,),
    )
    return MacroWinnerPlanMaterializationRequest(
        replace(authority, winner=winner, search_report=report)
    )


def replace_root_step(plan, step_id, transform):
    return replace(
        plan,
        root_scope=replace(
            plan.root_scope,
            steps=tuple(
                transform(step) if step.step_id == step_id else step
                for step in plan.root_scope.steps
            ),
        ),
    )
