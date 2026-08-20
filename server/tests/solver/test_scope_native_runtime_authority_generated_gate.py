from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json
import os

from shuxueshuo_server.solver.contracts import MacroSearchSpec
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
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    CallResultReadSource,
    CompilerSelectorReadSource,
    ConditionReadSource,
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


VIEW_MODES = ("identity", "latest_state", "immutable_value", "exact_result")
SOURCE_KINDS = (
    "entity_identity",
    "state_version",
    "condition",
    "call_result",
    "invocation_result",
    "compiler_selector",
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
    return CompilerSelectorReadSource("selector:value", path)


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
        "identity": {"entity_identity", "compiler_selector"},
        "latest_state": {"state_version", "invocation_result"},
        "immutable_value": {
            "entity_identity",
            "state_version",
            "condition",
            "invocation_result",
            "compiler_selector",
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


def test_generated_method_view_and_dependency_authority_gate() -> None:
    scenarios = tuple(
        itertools.product(
            VIEW_MODES,
            SOURCE_KINDS,
            SCOPE_RELATIONS,
            MUTATIONS,
            CARDINALITIES,
        )
    )
    assert len(scenarios) == 4_608

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
    candidates = (
        MacroRoleAssignmentCandidate(
            "candidate-e",
            {"moving_point": "E"},
            ("E",),
            call_count=2,
        ),
        MacroRoleAssignmentCandidate(
            "candidate-g",
            {"moving_point": "G"},
            ("G",),
            call_count=1,
        ),
    )
    return MacroImplementationRegistry(
        (
            MacroImplementation(
                implementation_id="generated/v1",
                macro_id="generated_macro",
                candidate_builder_id=LIFECYCLE_SPEC.candidate_builder_id,
                validation_policy_id=LIFECYCLE_SPEC.validation_policy_id,
                lowerer_id=LIFECYCLE_SPEC.lowerer_id or "",
                postcondition_id=LIFECYCLE_SPEC.postcondition_id or "",
                evidence_builder_id=LIFECYCLE_SPEC.evidence_builder_id or "",
                preparation_context_builder=lambda request: (
                    MacroImplementationPreparationContext(
                        payload=request.builder_context,
                        candidate_dependency_envelope=("E", "G"),
                    )
                ),
                candidate_builder=lambda _request: candidates,
                lowerer=lambda value, _authority: value,
                postcondition=lambda _value: (),
                evidence_builder=lambda *args, **kwargs: None,
            ),
        )
    )


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
            return MacroCandidateEvaluation(candidate_id, False)
        if scenario.candidate_outcome == "ambiguous":
            return MacroCandidateEvaluation(candidate_id, True, candidate_id)
        if scenario.candidate_outcome == "unique":
            passed = candidate_id == "candidate-g"
            return MacroCandidateEvaluation(
                candidate_id,
                passed,
                "winner" if passed else None,
            )
        return MacroCandidateEvaluation(candidate_id, True, "equivalent")

    try:
        prepared = MacroPreparationService(_lifecycle_registry()).prepare(
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
    assert prepared.authority.winner.candidate.roles["moving_point"] in {"E", "G"}
    return True, None


def test_generated_content_to_restore_authority_lifecycle_gate() -> None:
    scenarios = tuple(
        _LifecycleScenario(*values)
        for values in itertools.product(
            ("E", "G"),
            ("unique", "equivalent", "ambiguous", "none"),
            ("exact", "stale_revision", "winner_drift", "failed_goal"),
            ("same", "ancestor", "root", "sibling"),
            ("preserve", "replace"),
        )
    )
    assert len(scenarios) == 256
    requested = os.environ.get("SCOPE_NATIVE_RUNTIME_AUTHORITY_SCENARIO_ID")
    if requested:
        scenarios = tuple(item for item in scenarios if item.scenario_id == requested)
        assert scenarios, requested

    mismatches = []
    for scenario in scenarios:
        expected = _lifecycle_oracle(scenario)
        actual = _run_lifecycle(scenario)
        if actual != expected:
            mismatches.append((scenario.scenario_id, scenario, expected, actual))

    assert not mismatches, mismatches[:5]
