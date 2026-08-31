from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
import sympy as sp

from shuxueshuo_server.solver.contracts import MacroSearchSpec
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroImplementation,
    MacroImplementationPreparationContext,
    MacroImplementationRegistry,
    MacroPreparationRequest,
    MacroPreparationService,
    MacroRoleAssignmentCandidate,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroCandidateEvaluation,
    MacroRuntimeSearchError,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    _macro_candidate_failure_or_raise,
    _require_macro_canonical_plan_id,
    _runtime_authority_value_payload,
)
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry


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
) -> MacroRoleAssignmentCandidate:
    return MacroRoleAssignmentCandidate(
        candidate_id=candidate_id,
        roles={"moving_point": point},
        dependency_handles=(point,),
        call_count=call_count,
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


def _registry(candidates):
    implementation = MacroImplementation(
        implementation_id="test-macro/v1",
        macro_id="test_macro",
        candidate_builder_id=SPEC.candidate_builder_id,
        validation_policy_id=SPEC.validation_policy_id,
        lowerer_id=SPEC.lowerer_id or "",
        postcondition_id=SPEC.postcondition_id or "",
        evidence_builder_id=SPEC.evidence_builder_id or "",
        preparation_context_builder=lambda request: (
            MacroImplementationPreparationContext(
                payload=request.builder_context,
                candidate_dependency_envelope=(
                    request.candidate_dependency_envelope or ("E", "G")
                ),
            )
        ),
        candidate_builder=lambda _request: tuple(candidates),
        lowerer=lambda value, _authority: value,
        postcondition=lambda _value: (),
        evidence_builder=lambda *args, **kwargs: None,
    )
    return MacroImplementationRegistry((implementation,))


def test_prebinding_search_corrects_authored_hint_before_authority_finalization() -> None:
    candidates = (_candidate("candidate-e", "E"), _candidate("candidate-g", "G"))
    evaluated: list[str] = []

    def evaluate(authority):
        evaluated.append(authority.candidate.candidate_id)
        passed = authority.candidate.roles["moving_point"] == "G"
        return MacroCandidateEvaluation(
            authority.candidate.candidate_id,
            passed,
            "minimum:verified" if passed else None,
            ("method_checks", "macro_postcondition"),
        )

    prepared = MacroPreparationService(_registry(candidates)).prepare(
        _request(),
        search_spec=SPEC,
        evaluator=evaluate,
    )

    assert evaluated[0] == "candidate-e"
    assert prepared.authority.authored_roles == {"moving_point": "E"}
    assert prepared.authority.winner.candidate.roles == {"moving_point": "G"}
    resolution = prepared.authority.search_report.role_resolutions[0]
    assert (resolution.authored_ref, resolution.chosen_ref, resolution.corrected) == (
        "E",
        "G",
        True,
    )
    assert prepared.authority.winner.allowed_source_handles == ("G",)


def test_equivalent_prebinding_winners_use_declared_deterministic_order() -> None:
    candidates = (
        _candidate("large", "E", call_count=3, complexity=8),
        _candidate("small", "G", call_count=2, complexity=4),
    )
    prepared = MacroPreparationService(_registry(candidates)).prepare(
        _request(authored="E"),
        search_spec=SPEC,
        evaluator=lambda authority: MacroCandidateEvaluation(
            authority.candidate.candidate_id,
            True,
            "equivalent-output",
        ),
    )

    assert prepared.authority.winner.candidate.candidate_id == "small"


def test_non_equivalent_prebinding_winners_fail_before_f5c_finalization() -> None:
    candidates = (_candidate("candidate-e", "E"), _candidate("candidate-g", "G"))

    with pytest.raises(MacroRuntimeSearchError) as error:
        MacroPreparationService(_registry(candidates)).prepare(
            _request(),
            search_spec=SPEC,
            evaluator=lambda authority: MacroCandidateEvaluation(
                authority.candidate.candidate_id,
                True,
                f"output:{authority.candidate.candidate_id}",
            ),
        )

    assert error.value.code == "functional.macro_search_ambiguous"
    assert error.value.retryability == "planner_repairable"


@pytest.mark.parametrize(
    ("candidates", "spec"),
    [
        ((), SPEC),
        (
            (_candidate("candidate-e", "E"), _candidate("candidate-g", "G")),
            replace(SPEC, max_candidates=1),
        ),
    ],
)
def test_empty_or_over_budget_builder_is_a_macro_contract_error(candidates, spec) -> None:
    with pytest.raises(MacroRuntimeSearchError) as error:
        MacroPreparationService(_registry(candidates)).prepare(
            _request(),
            search_spec=spec,
            evaluator=lambda authority: MacroCandidateEvaluation(
                authority.candidate.candidate_id,
                True,
                "output",
            ),
        )

    assert error.value.code == "planner.macro_contract_invalid"
    assert error.value.retryability == "configuration"


def test_candidate_cannot_escape_typed_dependency_envelope() -> None:
    candidate = _candidate("candidate-sibling", "point:sibling:G")

    with pytest.raises(MacroRuntimeSearchError) as error:
        MacroPreparationService(_registry((candidate,))).prepare(
            _request(envelope=("point:ancestor:G",)),
            search_spec=SPEC,
            evaluator=lambda authority: MacroCandidateEvaluation(
                authority.candidate.candidate_id,
                True,
                "output",
            ),
        )

    assert error.value.code == "planner.macro_contract_invalid"
    assert error.value.details["outside_dependency_handles"] == [
        "point:sibling:G"
    ]


def test_atomic_path_macros_are_registered_for_runtime_search() -> None:
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

    assert runtime_search_ids == {
        "coupled_segment_endpoint_replacement_path_minimum",
        "equal_length_ray_path_reduction",
        "quadratic_square_path_minimum",
        "weighted_axis_path_minimum",
    }


def test_shadow_unknown_exception_is_configuration_not_candidate_miss() -> None:
    with pytest.raises(MacroRuntimeSearchError) as error:
        _macro_candidate_failure_or_raise(
            KeyError("missing compiler selector"),
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


def test_runtime_search_requires_scoped_v2_canonical_plan_id() -> None:
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
        SimpleNamespace(canonical_plan_id="scoped-plan:v2"),
        call_id="reduce_path",
    ) == "scoped-plan:v2"
