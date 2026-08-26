from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from shuxueshuo_server.solver.runtime import (
    functional_transaction_execution as transaction_module,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateEvaluation,
    FunctionalPlanFragment,
    SearchCandidate,
)
from shuxueshuo_server.solver.runtime.macro_definitions import (
    MacroDefinitionPreparationContext,
    MacroDefinitionRegistry,
    default_macro_definition_registry,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationRequest,
    MacroPreparationService,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRuntimeSearchError,
)
from shuxueshuo_server.solver.runtime.models import TypedValue
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalStep,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload
from test_coupled_segment_explicit_function_plan import (
    CASE,
    PATH_STEP_IDS,
    _execute,
    _explicit_function_payload,
)
from test_macro_explicit_plan_equivalence import (
    _alpha_normalized_conditions,
    _alpha_normalized_f5c_graph,
    _alpha_normalized_runtime_authority,
    _export_value,
    _fragment_from_result,
)


pytestmark = pytest.mark.solver_contract


MACRO_ID = "coupled_segment_endpoint_replacement_path_minimum"


def _macro_payload() -> dict:
    return deepcopy(load_v3_fixture_payload(CASE))


def test_coupled_segment_macro_matches_independent_c1_function_plan(
    tmp_path,
    monkeypatch,
) -> None:
    macro_fixture = planning_binding_fixture(tmp_path / "macro", case=CASE)
    macro = _execute(macro_fixture, _macro_payload())
    assert macro.checkpoint is not None
    assert macro.checkpoint.all_required_goals_verified
    expansion = next(
        item for item in macro.macro_expansions if item.macro_id == MACRO_ID
    )
    assert len(expansion.generated_step_ids) == 7
    assert not {
        "two_moving_points_path_reduction",
        "broken_path_straightening_minimum_expression",
    }.intersection(
        step.capability_id
        for step in macro.canonical_plan.steps
        if step.step_id in expansion.generated_step_ids
    )

    def forbidden_prepare(*_args, **_kwargs):
        raise AssertionError("the independent C1 Function Plan must not search a Macro")

    monkeypatch.setattr(MacroPreparationService, "prepare", forbidden_prepare)
    authored_fixture = planning_binding_fixture(tmp_path / "authored", case=CASE)
    authored_payload, authored_fragment = _explicit_function_payload()
    authored = _execute(authored_fixture, authored_payload)
    assert authored.checkpoint is not None
    assert authored.checkpoint.all_required_goals_verified
    assert authored.macro_expansions == ()

    macro_ids = tuple(expansion.generated_step_ids)
    authored_ids = PATH_STEP_IDS
    macro_graph = _fragment_from_result(
        macro,
        macro_ids,
        {
            name: {"step_id": value[0], "return": value[1]}
            for name, value in expansion.export_map.items()
        },
    )
    authored_graph = _fragment_from_result(
        authored,
        authored_ids,
        authored_fragment["exports"],
    )

    assert macro_graph.alpha_normalized_payload() == (
        authored_graph.alpha_normalized_payload()
    )
    assert _alpha_normalized_f5c_graph(macro, macro_ids) == (
        _alpha_normalized_f5c_graph(authored, authored_ids)
    )
    assert _alpha_normalized_conditions(macro, macro_ids) == (
        _alpha_normalized_conditions(authored, authored_ids)
    )
    assert _alpha_normalized_runtime_authority(macro, macro_ids) == (
        _alpha_normalized_runtime_authority(authored, authored_ids)
    )
    macro_export = {
        "step_id": expansion.export_map["minimum_expression"][0],
        "return": expansion.export_map["minimum_expression"][1],
    }
    assert _export_value(macro, macro_export) == _export_value(
        authored,
        authored_fragment["exports"]["minimum_expression"],
    )


def test_coupled_segment_macro_checkpoint_restores_materialized_functions(
    tmp_path,
    monkeypatch,
) -> None:
    first_fixture = planning_binding_fixture(tmp_path / "first", case=CASE)
    first = _execute(first_fixture, _macro_payload())
    assert first.checkpoint is not None
    seed = first.checkpoint.restore_state.runtime_seed
    assert seed is not None
    expansion = next(
        item for item in first.macro_expansions if item.macro_id == MACRO_ID
    )

    def forbidden_prepare(*_args, **_kwargs):
        raise AssertionError("restored ordinary Functions must not search the Macro")

    monkeypatch.setattr(MacroPreparationService, "prepare", forbidden_prepare)
    restore_fixture = planning_binding_fixture(tmp_path / "restore", case=CASE)
    restored = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(first.canonical_plan.to_payload(), ensure_ascii=False),
        inputs=restore_fixture[3],
        planning_context=restore_fixture[1],
        problem_binding_catalog=restore_fixture[7],
        handle_registry=restore_fixture[5],
        context=ContextBuilder().build(restore_fixture[2]),
        planner_state_context=restore_fixture[6],
        problem_payload=restore_fixture[4],
        restored_seed=seed,
        macro_expansions=first.macro_expansions,
    )

    assert restored.checkpoint is not None
    assert restored.checkpoint.all_required_goals_verified
    transaction = restored.replay.transactional_attempt_result
    assert transaction is not None
    assert set(expansion.generated_step_ids) <= set(
        transaction.execution_report.restored_call_ids
    )


def test_coupled_segment_macro_corrects_wrong_authored_role_hint(
    tmp_path,
    monkeypatch,
) -> None:
    observed = []
    original_prepare = MacroPreparationService.prepare

    def capture_prepare(self, request, **kwargs):
        selected = original_prepare(self, request, **kwargs)
        observed.append(selected.authority)
        return selected

    monkeypatch.setattr(
        transaction_module,
        "_authored_macro_roles",
        lambda _prepared, _macro: {
            "first_moving_point": "point:ii:G",
        },
    )
    monkeypatch.setattr(MacroPreparationService, "prepare", capture_prepare)

    fixture = planning_binding_fixture(tmp_path / "wrong-hint", case=CASE)
    result = _execute(fixture, _macro_payload())

    assert result.checkpoint is not None
    assert result.checkpoint.all_required_goals_verified
    authority = next(item for item in observed if item.macro_id == MACRO_ID)
    assert authority.authored_roles == {
        "first_moving_point": "point:ii:G",
    }
    assert authority.winner.candidate.role_bindings[
        "first_moving_point"
    ] == "point:ii:E"


def test_coupled_segment_macro_rejects_non_equivalent_valid_candidates() -> None:
    definition = default_macro_definition_registry().require(MACRO_ID)
    role_bindings = {
        role: f"point:problem:{index}"
        for index, role in enumerate(
            definition.search_contract.searchable_roles,
            start=1,
        )
    }

    def candidate(candidate_id: str) -> SearchCandidate:
        step = ScopedFunctionalStep(
            step_id=f"{candidate_id}.publish",
            capability_id="certify_minimum_expression",
            args={},
            return_bindings={},
            return_expectations={},
        )
        return SearchCandidate(
            candidate_id=candidate_id,
            fragment=FunctionalPlanFragment(
                scope_id="ii",
                steps=(step,),
                exports={
                    "minimum_expression": (step.step_id, "minimum_expression"),
                    "attainment_point": (step.step_id, "attainment_point"),
                },
                dependency_envelope=tuple(role_bindings.values()),
                blueprint_id=definition.blueprint.blueprint_version,
            ),
            role_bindings=role_bindings,
            strategy_id="coupled_segment_endpoint_replacement",
        )

    candidates = (candidate("candidate-a"), candidate("candidate-b"))
    registry = MacroDefinitionRegistry(
        (
            replace(
                definition,
                preparation_context_builder=lambda _request: (
                    MacroDefinitionPreparationContext(
                        payload={},
                        candidate_dependency_envelope=tuple(
                            role_bindings.values()
                        ),
                    )
                ),
                expander=lambda _request: candidates,
            ),
        )
    )
    request = MacroPreparationRequest(
        planning_context_id="planning:test",
        problem_revision_id="revision:test",
        problem_semantic_hash="semantic:test",
        plan_id="plan:test",
        call_id="reduce-path",
        goal_unit_ids=("ii.a",),
        scope_id="ii",
        macro_id=MACRO_ID,
        catalog_signature="catalog:test",
        authored_roles={},
        candidate_dependency_envelope=(),
        upstream_exact_state_signature="state:test",
    )

    with pytest.raises(MacroRuntimeSearchError) as error:
        MacroPreparationService(registry).prepare(
            request,
            search_spec=definition.search_contract,
            evaluator=lambda authority: CandidateEvaluation(
                candidate_id=authority.candidate.candidate_id,
                passed=True,
                standard_outputs={
                    "minimum_expression": (
                        "x"
                        if authority.candidate.candidate_id.endswith("a")
                        else "y"
                    ),
                    "attainment_point": "point:problem:G",
                },
            ),
        )

    assert error.value.code == "functional.macro_search_ambiguous"
    assert error.value.retryability == "planner_repairable"


def test_coupled_segment_shadow_candidate_has_zero_ghost_writes(
    tmp_path,
    monkeypatch,
) -> None:
    sentinel_path = "$question.ii.temp.coupled_macro_shadow_sentinel"
    shadow_pairs = []
    fork_parents = {}
    runtime_context_type = transaction_module.RuntimeContext
    original_fork = runtime_context_type.fork
    original_shadow = transaction_module._execute_macro_candidate_shadow_fragment

    def track_fork(self):
        branch = original_fork(self)
        fork_parents[id(branch)] = self
        return branch

    def write_shadow_sentinel(*args, branch, **kwargs):
        parent = fork_parents[id(branch)]
        branch.write_path(
            sentinel_path,
            TypedValue("Scalar", 987654321),
            from_scope_id="ii",
        )
        shadow_pairs.append((parent, branch))
        return original_shadow(*args, branch=branch, **kwargs)

    monkeypatch.setattr(runtime_context_type, "fork", track_fork)
    monkeypatch.setattr(
        transaction_module,
        "_execute_macro_candidate_shadow_fragment",
        write_shadow_sentinel,
    )

    fixture = planning_binding_fixture(tmp_path / "shadow", case=CASE)
    result = _execute(fixture, _macro_payload())

    assert result.checkpoint is not None
    assert result.checkpoint.all_required_goals_verified
    assert shadow_pairs
    for parent, branch in shadow_pairs:
        assert branch.read_path(
            sentinel_path,
            from_scope_id="ii",
        ).value == 987654321
        with pytest.raises(KeyError):
            parent.read_path(sentinel_path, from_scope_id="ii")
    assert "987654321" not in json.dumps(
        result.checkpoint.restore_state.authority_payload(),
        ensure_ascii=False,
    )
