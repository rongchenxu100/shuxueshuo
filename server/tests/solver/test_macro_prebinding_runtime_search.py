from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
import sympy as sp

from shuxueshuo_server.solver.contracts import MacroSearchSpec
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
)
from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateEvaluation,
    CandidateSelectionSpec,
    FunctionalPlanFragment,
    SearchCandidate,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    _macro_candidate_failure_or_raise,
    _require_macro_canonical_plan_id,
    _runtime_authority_value_payload,
)
from shuxueshuo_server.solver.runtime.macro_blueprints import (
    MacroSemanticBlueprint,
)
from shuxueshuo_server.solver.runtime.macro_definitions import (
    MacroDefinition,
    MacroDefinitionPreparationContext,
    MacroDefinitionRegistry,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationRequest,
    MacroPreparationService,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRuntimeSearchError,
)
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalStep,
)


SPEC = MacroSearchSpec(
    searchable_roles=("moving_point",),
    candidate_builder_id="test_role_builder",
    validation_policy_id="test_runtime_validation",
    lowerer_id="test_lowerer",
    postcondition_id="test_postcondition",
    evidence_builder_id="test_evidence",
    max_candidates=4,
)


def _candidate(
    candidate_id: str,
    point: str,
    *,
    call_count: int = 1,
    complexity: int = 1,
) -> SearchCandidate:
    steps = tuple(
        ScopedFunctionalStep(
            step_id=f"{candidate_id}.step_{index}",
            capability_id="test_function",
            args={"point": (point,)},
            return_bindings={},
            return_expectations={},
        )
        for index in range(call_count)
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        fragment=FunctionalPlanFragment(
            scope_id="ii",
            steps=steps,
            exports={"result": (steps[-1].step_id, "result")},
            dependency_envelope=(point,),
            blueprint_id="test_macro",
        ),
        role_bindings={"moving_point": point},
        strategy_id=f"strategy:{candidate_id}",
        symbolic_complexity=complexity,
    )


def _request(*, authored: str = "E", envelope=("E", "G")):
    return MacroPreparationRequest(
        planning_context_id="planning:test",
        problem_revision_id="revision:test",
        problem_semantic_hash="semantic:test",
        plan_id="plan:test",
        call_id="reduce_path",
        goal_unit_ids=("ii.a",),
        scope_id="ii",
        macro_id="test_macro",
        catalog_signature="catalog:test",
        authored_roles={"moving_point": authored},
        candidate_dependency_envelope=tuple(envelope),
        upstream_exact_state_signature="state:test",
    )


def _service(candidates) -> MacroPreparationService:
    blueprint = MacroSemanticBlueprint(
        macro_id="test_macro",
        summary="test blueprint",
        applicable_structure=("test structure",),
        role_invariants=("test role",),
        construction_purpose=("test construction",),
        proof_obligations=("test proof",),
        reduction_strategies=("test strategy",),
        attainment_checks=("test attainment",),
        function_capability_ids=("test_function",),
    )
    definitions = MacroDefinitionRegistry(
        (
            MacroDefinition(
                macro_id="test_macro",
                implementation_id="test-macro/v1",
                blueprint=blueprint,
                search_contract=SPEC,
                preparation_context_builder=lambda request: (
                    MacroDefinitionPreparationContext(
                        payload={},
                        candidate_dependency_envelope=(
                            request.candidate_dependency_envelope or ("E", "G")
                        ),
                    )
                ),
                expander=lambda _request: tuple(candidates),
                selection=CandidateSelectionSpec("equivalent"),
                export_names=("result",),
            ),
        )
    )
    return MacroPreparationService(definitions)


def _evaluation(candidate_id: str, output: str) -> CandidateEvaluation:
    return CandidateEvaluation(
        candidate_id=candidate_id,
        passed=True,
        standard_outputs={"result": output},
        shadow_execution_signature=f"shadow:{candidate_id}:{output}",
    )


def test_prebinding_search_corrects_authored_hint_before_authority_finalization() -> None:
    candidates = (_candidate("candidate-e", "E"), _candidate("candidate-g", "G"))
    evaluated: list[str] = []

    def evaluate(authority):
        evaluated.append(authority.candidate.candidate_id)
        passed = authority.candidate.role_bindings["moving_point"] == "G"
        return (
            _evaluation(authority.candidate.candidate_id, "minimum:verified")
            if passed
            else CandidateEvaluation(
                authority.candidate.candidate_id,
                False,
                failure_code="functional.candidate_not_feasible",
            )
        )

    prepared = _service(candidates).prepare(
        _request(),
        search_spec=SPEC,
        evaluator=evaluate,
    )

    assert evaluated[0] == "candidate-e"
    assert prepared.authority.authored_roles == {"moving_point": "E"}
    assert prepared.authority.winner.candidate.role_bindings == {
        "moving_point": "G"
    }
    assert prepared.authority.winner.allowed_source_handles == ("G",)


def test_equivalent_prebinding_winners_use_fragment_cost_order() -> None:
    candidates = (
        _candidate("large", "E", call_count=3, complexity=8),
        _candidate("small", "G", call_count=2, complexity=4),
    )
    prepared = _service(candidates).prepare(
        _request(authored="E"),
        search_spec=SPEC,
        evaluator=lambda authority: _evaluation(
            authority.candidate.candidate_id,
            "equivalent-output",
        ),
    )

    assert prepared.authority.winner.candidate.candidate_id == "small"


def test_non_equivalent_prebinding_winners_fail_before_f5c_finalization() -> None:
    candidates = (_candidate("candidate-e", "E"), _candidate("candidate-g", "G"))

    with pytest.raises(MacroRuntimeSearchError) as error:
        _service(candidates).prepare(
            _request(),
            search_spec=SPEC,
            evaluator=lambda authority: _evaluation(
                authority.candidate.candidate_id,
                f"output:{authority.candidate.candidate_id}",
            ),
        )

    assert error.value.code == "functional.macro_search_ambiguous"
    assert error.value.retryability == "planner_repairable"


def test_empty_builder_is_a_repairable_math_search_failure() -> None:
    with pytest.raises(MacroRuntimeSearchError) as error:
        _service(()).prepare(
            _request(),
            search_spec=SPEC,
            evaluator=lambda authority: _evaluation(
                authority.candidate.candidate_id,
                "output",
            ),
        )

    assert error.value.code == "functional.macro_search_no_candidates"
    assert error.value.retryability == "planner_repairable"


def test_over_budget_builder_is_a_macro_contract_error() -> None:
    candidates = (_candidate("candidate-e", "E"), _candidate("candidate-g", "G"))
    with pytest.raises(MacroRuntimeSearchError) as error:
        _service(candidates).prepare(
            _request(),
            search_spec=replace(SPEC, max_candidates=1),
            evaluator=lambda authority: _evaluation(
                authority.candidate.candidate_id,
                "output",
            ),
        )

    assert error.value.code == "functional.macro_search_budget_exceeded"
    assert error.value.retryability == "configuration"


def test_candidate_cannot_escape_typed_dependency_envelope() -> None:
    candidate = _candidate("candidate-sibling", "point:sibling:G")

    with pytest.raises(MacroRuntimeSearchError) as error:
        _service((candidate,)).prepare(
            _request(envelope=("point:ancestor:G",)),
            search_spec=SPEC,
            evaluator=lambda authority: _evaluation(
                authority.candidate.candidate_id,
                "output",
            ),
        )

    assert error.value.code == "planner.macro_contract_invalid"
    assert error.value.details["outside_dependency_handles"] == [
        "point:sibling:G"
    ]


def test_only_equal_length_ray_macro_is_registered_for_runtime_search() -> None:
    method_specs = MethodSpecRegistry.load_from_code()
    runtime_search_ids = {
        macro.macro_id
        for family in DEFAULT_FAMILY_REGISTRY.families
        for macro in MacroSpecRegistry.from_family_spec(
            family,
            method_specs,
        ).specs.values()
        if macro.execution_mode == "runtime_search"
    }

    assert runtime_search_ids == {"equal_length_ray_path_reduction"}


def test_shadow_unknown_exception_is_configuration_not_candidate_miss() -> None:
    with pytest.raises(MacroRuntimeSearchError) as error:
        _macro_candidate_failure_or_raise(
            KeyError("missing compiler authority"),
            macro_id="test_macro",
            call_id="reduce_path",
            candidate_id="candidate-g",
        )

    assert error.value.code == "planner.macro_candidate_execution_error"
    assert error.value.retryability == "configuration"


def test_shadow_explicit_planner_failure_remains_candidate_miss() -> None:
    error = StatelessMethodError(
        "functional.method_precondition_failed",
        "candidate geometry is not feasible",
        category="precondition",
        retryability="planner_repairable",
        repair_action="choose_compatible_macro_role",
    )

    evaluation = _macro_candidate_failure_or_raise(
        error,
        macro_id="test_macro",
        call_id="reduce_path",
        candidate_id="candidate-e",
    )

    assert not evaluation.passed
    assert evaluation.candidate_id == "candidate-e"


def test_macro_authority_uses_canonical_sympy_payload_not_repr() -> None:
    x, y = sp.symbols("x y")

    assert _runtime_authority_value_payload(x + y) == {
        "sympy": sp.srepr(x + y)
    }
    with pytest.raises(MacroRuntimeSearchError) as error:
        _runtime_authority_value_payload(object())
    assert error.value.code == "planner.macro_contract_invalid"


def test_runtime_search_requires_scoped_v3_canonical_plan_id() -> None:
    with pytest.raises(MacroRuntimeSearchError) as error:
        _require_macro_canonical_plan_id(
            SimpleNamespace(canonical_plan_id=None),
            call_id="reduce_path",
        )

    assert error.value.code == "planner.macro_contract_invalid"
    assert error.value.retryability == "configuration"
    assert error.value.details == {
        "call_id": "reduce_path",
        "missing_authority": "canonical_plan_id",
    }
    assert _require_macro_canonical_plan_id(
        SimpleNamespace(canonical_plan_id="scoped-plan:v3"),
        call_id="reduce_path",
    ) == "scoped-plan:v3"
