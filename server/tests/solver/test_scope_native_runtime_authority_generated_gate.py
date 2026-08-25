from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json
import os

import pytest

from shuxueshuo_server.solver.contracts import (
    CoefficientExtractionDerivationSpec,
    MacroSearchSpec,
    MethodInputBindingSpec,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationRequest,
    MacroPreparationService,
)
from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateEvaluation,
    CandidateSelectionSpec,
    FunctionalPlanFragment,
    SearchCandidate,
)
from shuxueshuo_server.solver.runtime.macro_blueprints import (
    MacroSemanticBlueprint,
)
from shuxueshuo_server.solver.runtime.macro_definitions import (
    MacroDefinition,
    MacroDefinitionPreparationContext,
    MacroDefinitionRegistry,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import MacroRuntimeSearchError
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalStep,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    CallResultReadSource,
    ConditionReadSource,
    DerivedInputReadSource,
    EntityIdentityReadSource,
    InvocationResultReadSource,
    MethodInputReadAuthority,
    StateVersionReadSource,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    ScopeVisibilityResolver,
    StateSlotId,
    StateVersionId,
)
from support.generated_gate_profiles import (
    FULL_SHARD_COUNT,
    assert_complete_partition,
    coverage_first_sample,
    select_shard,
)


VIEW_MODES = ("identity", "latest_state", "immutable_value", "exact_result")
SOURCE_KINDS = (
    "entity_identity",
    "state_version",
    "condition",
    "call_result",
    "invocation_result",
    "typed_derivation",
)
SCOPE_RELATIONS = ("same", "ancestor", "root", "sibling")
MUTATIONS = ("exact", "signature_drift", "path_drift", "scope_drift")
CARDINALITIES = tuple(range(1, 13))


class _VisibilityRegistry:
    def ancestor_scopes(self, scope_id):
        return {
            "problem": ("problem",),
            "ii": ("ii", "problem"),
            "ii_1": ("ii_1", "ii", "problem"),
            "ii_2": ("ii_2", "ii", "problem"),
        }[scope_id]


def _source_scope(relation: str) -> str:
    return {
        "same": "ii_1",
        "ancestor": "ii",
        "root": "problem",
        "sibling": "ii_2",
    }[relation]


def _state_version(source_scope: str) -> StateVersionId:
    return StateVersionId(
        StateSlotId(
            LogicalStateKey(
                MathObjectId(f"point:{source_scope}:P", "point", source_scope),
                "coordinate",
                "Point",
            ),
            source_scope,
        ),
        1,
    )


def _source(kind: str, source_scope: str, path: str):
    if kind == "entity_identity":
        return EntityIdentityReadSource(f"point:{source_scope}:P", path)
    if kind == "state_version":
        return StateVersionReadSource(_state_version(source_scope), path)
    if kind == "condition":
        return ConditionReadSource(f"condition:{source_scope}:P", path)
    if kind == "call_result":
        return CallResultReadSource("producer", "value", path)
    if kind == "invocation_result":
        return InvocationResultReadSource("producer:method", "value", path)
    return DerivedInputReadSource(
        MethodInputBindingSpec(
            input_name="value",
            derivation=CoefficientExtractionDerivationSpec("source"),
        ),
        StateVersionReadSource(_state_version(source_scope), path),
        path,
    )


def _types(view_mode: str) -> tuple[str, str]:
    return {
        "identity": ("Point", "PointRef"),
        "latest_state": ("Point", "Point"),
        "immutable_value": ("Fact", "Condition"),
        "exact_result": ("PathWitness", "PathTransformation"),
    }[view_mode]


def _oracle_accepts(
    view_mode: str,
    source_kind: str,
    relation: str,
    mutation: str,
) -> bool:
    allowed = {
        "identity": {"entity_identity"},
        "latest_state": {"state_version", "invocation_result"},
        "immutable_value": {
            "entity_identity",
            "state_version",
            "condition",
            "invocation_result",
            "typed_derivation",
        },
        "exact_result": {"call_result", "invocation_result"},
    }
    return (
        source_kind in allowed[view_mode]
        and relation != "sibling"
        and mutation == "exact"
    )


def _production_accepts(
    view_mode: str,
    source_kind: str,
    relation: str,
    mutation: str,
    cardinality: int,
) -> bool:
    source_scope = _source_scope(relation)
    path = f"$scope.{source_scope}.values.P"
    domain_type, runtime_type = _types(view_mode)
    try:
        authorities = tuple(
            MethodInputReadAuthority(
                method_id="generated_method",
                invocation_id="generated_invocation",
                input_name="values",
                item_index=index,
                view_mode=view_mode,
                domain_type=domain_type,
                runtime_type=runtime_type,
                scope_id="ii_1",
                source=_source(source_kind, source_scope, path),
            )
            for index in range(cardinality)
        )
        if mutation == "signature_drift":
            payload = authorities[0].authority_payload()
            payload["source"]["runtime_path"] += ".drift"
            MethodInputReadAuthority.from_payload(payload)
            return False
        raw_path = path + (".drift" if mutation == "path_drift" else "")
        expected_scope = "ii_2" if mutation == "scope_drift" else "ii_1"
        for index, authority in enumerate(authorities):
            authority.verify(
                method_id="generated_method",
                invocation_id="generated_invocation",
                input_name="values",
                item_index=index,
                view_mode=view_mode,
                domain_type=domain_type,
                runtime_type=runtime_type,
                scope_id=expected_scope,
                raw_path=raw_path,
                production=True,
            )
        visible = ScopeVisibilityResolver(_VisibilityRegistry()).is_visible(
            source_scope,
            consumer_scope_id="ii_1",
        )
        return visible
    except (KeyError, TypeError, ValueError):
        return False


def _view_scenarios():
    return tuple(
        itertools.product(
            VIEW_MODES,
            SOURCE_KINDS,
            SCOPE_RELATIONS,
            MUTATIONS,
            CARDINALITIES,
        )
    )


def _view_scenario_id(scenario) -> str:
    return "runtime-view:" + ":".join(map(str, scenario))


def _view_dimensions(scenario) -> dict[str, object]:
    view, source, relation, mutation, cardinality = scenario
    return {
        "view": view,
        "source": source,
        "relation": relation,
        "mutation": mutation,
        "cardinality": cardinality,
    }


@pytest.mark.generated_gate
def test_generated_method_view_and_dependency_authority_gate_quick() -> None:
    if os.environ.get("SCOPE_NATIVE_RUNTIME_AUTHORITY_SCENARIO_ID"):
        pytest.skip("lifecycle single-scenario replay bypasses the view matrix")
    scenarios = coverage_first_sample(
        _view_scenarios(),
        256,
        scenario_id=_view_scenario_id,
        dimensions=_view_dimensions,
    )
    assert len(scenarios) == 256
    _assert_view_dimension_values(scenarios)
    _run_view_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
@pytest.mark.parametrize("shard_index", range(FULL_SHARD_COUNT))
def test_generated_method_view_and_dependency_authority_gate_full(
    shard_index: int,
) -> None:
    if os.environ.get("SCOPE_NATIVE_RUNTIME_AUTHORITY_SCENARIO_ID"):
        pytest.skip("lifecycle single-scenario replay bypasses the view matrix")
    scenarios = select_shard(
        _view_scenarios(),
        shard_index,
        scenario_id=_view_scenario_id,
    )
    assert scenarios
    _run_view_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
def test_generated_method_view_authority_full_metadata() -> None:
    scenarios = _view_scenarios()
    assert len(scenarios) == 4_608
    assert_complete_partition(scenarios, scenario_id=_view_scenario_id)
    _assert_view_dimension_values(scenarios)


def _assert_view_dimension_values(scenarios) -> None:
    dimensions = tuple(_view_dimensions(item) for item in scenarios)
    assert {item["view"] for item in dimensions} == set(VIEW_MODES)
    assert {item["source"] for item in dimensions} == set(SOURCE_KINDS)
    assert {item["relation"] for item in dimensions} == set(SCOPE_RELATIONS)
    assert {item["mutation"] for item in dimensions} == set(MUTATIONS)
    assert {item["cardinality"] for item in dimensions} == set(CARDINALITIES)


def _run_view_scenarios(scenarios) -> None:
    mismatches = []
    for scenario in scenarios:
        view, source, relation, mutation, cardinality = scenario
        expected = _oracle_accepts(view, source, relation, mutation)
        actual = _production_accepts(*scenario)
        if actual != expected:
            mismatches.append((scenario, expected, actual))

    assert not mismatches, mismatches[:5]


@dataclass(frozen=True)
class _LifecycleScenario:
    authored_hint: str
    candidate_outcome: str
    restore_mode: str
    scope_relation: str
    repair_mode: str

    @property
    def scenario_id(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True, separators=(",", ":"))
        return "runtime-authority:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


LIFECYCLE_SPEC = MacroSearchSpec(
    searchable_roles=("moving_point",),
    candidate_builder_id="generated_builder",
    validation_policy_id="generated_runtime",
    lowerer_id="generated_lowerer",
    postcondition_id="generated_postcondition",
    evidence_builder_id="generated_evidence",
    max_candidates=4,
)


def _lifecycle_registry():
    def candidate(candidate_id: str, moving_point: str) -> SearchCandidate:
        step = ScopedFunctionalStep(
            step_id=f"{candidate_id}_step",
            capability_id="generated_function",
            args={},
            return_bindings={},
            return_expectations={},
        )
        return SearchCandidate(
            candidate_id=candidate_id,
            fragment=FunctionalPlanFragment(
                source="macro",
                scope_id="ii_1",
                steps=(step,),
                exports={"value": (step.step_id, "value")},
                dependency_envelope=(moving_point,),
                blueprint_id="generated-blueprint/v1",
            ),
            role_bindings={"moving_point": moving_point},
            strategy_id="generated",
        )

    candidates = (
        candidate("candidate-e", "E"),
        candidate("candidate-g", "G"),
    )
    blueprint = MacroSemanticBlueprint(
        macro_id="generated_macro",
        summary="generated lifecycle Macro",
        applicable_structure=("generated structure",),
        role_invariants=("moving point is visible",),
        construction_purpose=("exercise candidate lifecycle",),
        proof_obligations=("verify generated result",),
        reduction_strategies=("generated",),
        attainment_checks=("result is attained",),
        function_capability_ids=("generated_function",),
        blueprint_version="generated-blueprint/v1",
    )
    definition_registry = MacroDefinitionRegistry(
        (
            MacroDefinition(
                macro_id="generated_macro",
                implementation_id="generated/v1",
                blueprint=blueprint,
                search_contract=LIFECYCLE_SPEC,
                preparation_context_builder=lambda request: (
                    MacroDefinitionPreparationContext(
                        payload=request.builder_context or {},
                        candidate_dependency_envelope=("E", "G"),
                    )
                ),
                expander=lambda _request: candidates,
                selection=CandidateSelectionSpec("equivalent"),
                export_names=("value",),
            ),
        )
    )
    return definition_registry


def _lifecycle_oracle(scenario: _LifecycleScenario) -> tuple[bool, str | None]:
    if scenario.scope_relation == "sibling":
        return False, "scope_not_visible"
    if scenario.candidate_outcome == "ambiguous":
        return False, "functional.macro_search_ambiguous"
    if scenario.candidate_outcome == "none":
        return False, "functional.macro_search_no_valid_candidate"
    if scenario.restore_mode == "stale_revision":
        return False, "planner.problem_revision_drift"
    if scenario.restore_mode == "winner_drift":
        return False, "planner.macro_winner_replay_drift"
    if scenario.restore_mode == "failed_goal" and scenario.repair_mode != "replace":
        return False, "failed_goal_not_replaced"
    return True, None


def _run_lifecycle(scenario: _LifecycleScenario) -> tuple[bool, str | None]:
    if not ScopeVisibilityResolver(_VisibilityRegistry()).is_visible(
        _source_scope(scenario.scope_relation),
        consumer_scope_id="ii_1",
    ):
        return False, "scope_not_visible"
    request = MacroPreparationRequest(
        planning_context_id="planning:test",
        problem_revision_id="revision:test",
        problem_semantic_hash="semantic:test",
        plan_id="plan:test",
        call_id="macro",
        goal_unit_ids=("ii.answer",),
        scope_id="ii_1",
        macro_id="generated_macro",
        catalog_signature="catalog:test",
        authored_roles={"moving_point": scenario.authored_hint},
        candidate_dependency_envelope=("E", "G"),
        upstream_exact_state_signature="state:test",
    )

    def evaluate(authority):
        candidate_id = authority.candidate.candidate_id
        if scenario.candidate_outcome == "none":
            return CandidateEvaluation(
                candidate_id,
                False,
                failure_code="generated_candidate_failed",
            )
        if scenario.candidate_outcome == "ambiguous":
            return CandidateEvaluation(
                candidate_id,
                True,
                standard_outputs={"value": candidate_id},
            )
        if scenario.candidate_outcome == "unique":
            passed = candidate_id == "candidate-g"
            return CandidateEvaluation(
                candidate_id,
                passed,
                standard_outputs={"value": "winner"} if passed else {},
                failure_code=None if passed else "generated_candidate_failed",
            )
        return CandidateEvaluation(
            candidate_id,
            True,
            standard_outputs={"value": "equivalent"},
        )

    try:
        definitions = _lifecycle_registry()
        prepared = MacroPreparationService(definitions).prepare(
            request,
            search_spec=LIFECYCLE_SPEC,
            evaluator=evaluate,
        )
    except MacroRuntimeSearchError as error:
        return False, error.code
    if scenario.restore_mode == "stale_revision":
        return False, "planner.problem_revision_drift"
    if scenario.restore_mode == "winner_drift":
        return False, "planner.macro_winner_replay_drift"
    if scenario.restore_mode == "failed_goal" and scenario.repair_mode != "replace":
        return False, "failed_goal_not_replaced"
    assert prepared.authority.winner.candidate.role_bindings[
        "moving_point"
    ] in {"E", "G"}
    return True, None


def _lifecycle_scenarios():
    return tuple(
        _LifecycleScenario(*values)
        for values in itertools.product(
            ("E", "G"),
            ("unique", "equivalent", "ambiguous", "none"),
            ("exact", "stale_revision", "winner_drift", "failed_goal"),
            ("same", "ancestor", "root", "sibling"),
            ("preserve", "replace"),
        )
    )


def _lifecycle_dimensions(scenario: _LifecycleScenario) -> dict[str, object]:
    return dict(scenario.__dict__)


def _requested_lifecycle_scenarios(scenarios):
    requested = os.environ.get("SCOPE_NATIVE_RUNTIME_AUTHORITY_SCENARIO_ID")
    if requested:
        selected = tuple(
            item for item in scenarios if item.scenario_id == requested
        )
        assert selected, requested
        return selected
    return None


@pytest.mark.generated_gate
def test_generated_content_to_restore_authority_lifecycle_gate_quick() -> None:
    all_scenarios = _lifecycle_scenarios()
    scenarios = _requested_lifecycle_scenarios(all_scenarios)
    if scenarios is None:
        scenarios = coverage_first_sample(
            all_scenarios,
            64,
            scenario_id=lambda item: item.scenario_id,
            dimensions=_lifecycle_dimensions,
        )
        assert len(scenarios) == 64
        _assert_lifecycle_dimension_values(scenarios)
    _run_lifecycle_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
@pytest.mark.parametrize("shard_index", range(FULL_SHARD_COUNT))
def test_generated_content_to_restore_authority_lifecycle_gate_full(
    shard_index: int,
) -> None:
    if os.environ.get("SCOPE_NATIVE_RUNTIME_AUTHORITY_SCENARIO_ID"):
        pytest.skip("single-scenario replay is handled by the quick gate")
    scenarios = select_shard(
        _lifecycle_scenarios(),
        shard_index,
        scenario_id=lambda item: item.scenario_id,
    )
    assert scenarios
    _run_lifecycle_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
def test_generated_runtime_authority_lifecycle_full_metadata() -> None:
    scenarios = _lifecycle_scenarios()
    assert len(scenarios) == 256
    assert_complete_partition(
        scenarios,
        scenario_id=lambda item: item.scenario_id,
    )
    _assert_lifecycle_dimension_values(scenarios)


def _assert_lifecycle_dimension_values(scenarios) -> None:
    dimensions = tuple(_lifecycle_dimensions(item) for item in scenarios)
    assert {item["authored_hint"] for item in dimensions} == {"E", "G"}
    assert {item["candidate_outcome"] for item in dimensions} == {
        "unique",
        "equivalent",
        "ambiguous",
        "none",
    }
    assert {item["restore_mode"] for item in dimensions} == {
        "exact",
        "stale_revision",
        "winner_drift",
        "failed_goal",
    }
    assert {item["scope_relation"] for item in dimensions} == set(
        SCOPE_RELATIONS
    )
    assert {item["repair_mode"] for item in dimensions} == {
        "preserve",
        "replace",
    }


def _run_lifecycle_scenarios(scenarios) -> None:
    mismatches = []
    for scenario in scenarios:
        expected = _lifecycle_oracle(scenario)
        actual = _run_lifecycle(scenario)
        if actual != expected:
            mismatches.append((scenario.scenario_id, scenario, expected, actual))

    assert not mismatches, mismatches[:5]
