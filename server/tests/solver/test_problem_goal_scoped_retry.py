from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from shuxueshuo_server.solver import engine as solver_engine
from shuxueshuo_server.solver.extraction.problem_planning_retry import (
    ProblemPlanningRetryError,
    ProblemPlanningRetryProjector,
    _audit_prompt_payload,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DoubaoMultimodalExtractionProvider,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainProjector,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryGraphCheckpoint,
    FunctionalRetryProblemAuthority,
    FunctionalRetryCheckpointError,
    verify_restored_checkpoint,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
)

from _problem_planning_support import (
    CASES,
    scope_native_reconciliation_fixture,
    scope_native_retry_checkpoint_fixture,
)


CASE = "tj-2026-nankai-yimo-25"


def _prompt_scopes(payload: dict) -> tuple[dict, ...]:
    result: list[dict] = []

    def visit(scope: dict) -> None:
        result.append(scope)
        for child in scope.get("children", []):
            visit(child)

    visit(payload["root_scope"])
    return tuple(result)


def _prompt_goals(payload: dict) -> tuple[dict, ...]:
    return tuple(
        goal
        for scope in _prompt_scopes(payload)
        for goal in scope.get("goals", [])
    )


@pytest.mark.parametrize("case", CASES)
def test_five_case_goal_retry_projection_is_deterministic(
    tmp_path,
    case,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path / case, case=case)
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    call_id = next(iter(sidecar.call_goal_bindings))
    checkpoint = _checkpoint(
        planner_context,
        reconciliation=reconciliation,
    )

    first = ProblemPlanningRetryProjector().project(
        planning_context,
        checkpoint,
        (call_id,),
    )
    second = ProblemPlanningRetryProjector().project(
        planning_context,
        checkpoint,
        (call_id,),
    )

    assert first == second
    assert first.projection_signature == second.projection_signature
    assert set(first.goal_unit_ids) == set(
        sidecar.call_goal_bindings[call_id]
    )
    _assert_prompt_hides_authority(
        first.to_prompt_payload(),
        planning_context=planning_context,
    )


def test_single_goal_repair_projects_only_its_goal_view(tmp_path) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASE)
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    call_id, goal_ids = next(
        (call_id, goal_ids)
        for call_id, goal_ids in sidecar.call_goal_bindings.items()
        if len(goal_ids) == 1
    )
    checkpoint = _checkpoint(
        planner_context,
        reconciliation=reconciliation,
    )

    projected = ProblemPlanningRetryProjector().project(
        planning_context,
        checkpoint,
        (call_id,),
    )

    assert projected.goal_unit_ids == goal_ids
    assert projected.to_prompt_payload() == planning_context.to_prompt_payload(
        goal_unit_ids=goal_ids,
    )
    assert len(_prompt_goals(projected.to_prompt_payload())) == 1
    prompt = projected.to_prompt_payload()
    emitted_scope_ids = {item["id"] for item in _prompt_scopes(prompt)}
    selected_goal = next(
        item
        for item in planning_context.goal_views
        if item.goal_unit_id in goal_ids
    )
    assert emitted_scope_ids == set(selected_goal.visible_scope_ids)
    _assert_prompt_hides_authority(
        prompt,
        planning_context=planning_context,
    )


def test_shared_call_projects_goal_union_and_deduplicates_shared_scope(
    tmp_path,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASE)
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    call_id, goal_ids = next(
        (call_id, goal_ids)
        for call_id, goal_ids in sidecar.call_goal_bindings.items()
        if len(goal_ids) >= 2
    )

    projected = ProblemPlanningRetryProjector().project(
        planning_context,
        _checkpoint(planner_context, reconciliation=reconciliation),
        (call_id,),
    )
    prompt = projected.to_prompt_payload()

    assert set(projected.goal_unit_ids) == set(goal_ids)
    assert len(_prompt_goals(prompt)) == len(goal_ids)
    scope_ids = [item["id"] for item in _prompt_scopes(prompt)]
    assert len(scope_ids) == len(set(scope_ids))


def test_shared_source_identity_does_not_expand_repair_goals(tmp_path) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        _catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASE)
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    authorities = [
        sidecar.source_provenance_for_call(call_id)
        for call_id in sidecar.call_goal_bindings
    ]
    pair = next(
        (left, right)
        for left in authorities
        for right in authorities
        if left.canonical_call_id != right.canonical_call_id
        and set(left.input_source_unit_ids)
        & set(right.input_source_unit_ids)
        and set(left.goal_unit_ids) != set(right.goal_unit_ids)
    )

    projected = ProblemPlanningRetryProjector().project(
        planning_context,
        _checkpoint(planner_context, reconciliation=reconciliation),
        (pair[0].canonical_call_id,),
    )

    assert set(projected.goal_unit_ids) == set(pair[0].goal_unit_ids)
    assert not (
        set(pair[1].goal_unit_ids) - set(pair[0].goal_unit_ids)
    ) <= set(projected.goal_unit_ids)


def test_strategy_payload_rebuilds_goal_retry_context_from_authority(
    tmp_path,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        problem_payload,
        _registry,
        planner_context,
        catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASE)
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    call_id = next(
        call_id
        for call_id, goal_ids in sidecar.call_goal_bindings.items()
        if len(goal_ids) == 1
    )
    checkpoint = _checkpoint(
        planner_context,
        reconciliation=reconciliation,
    )
    retry_state = {
        "attempt": 1,
        "repair_call_ids": [call_id],
        "issues": [],
        "functional_retry_graph_checkpoint": checkpoint.to_payload(),
    }
    retry_inputs = replace(
        inputs,
        previous_errors=[{"planner_retry_state": retry_state}],
    )

    payload = StrategyPayloadBuilder().build(
        retry_inputs,
        problem_payload=problem_payload,
        planner_state_context=planner_context,
        problem_planning_context=planning_context,
        problem_binding_catalog=catalog,
    )

    retry_payload = payload["previous_attempt_state"]["latest_retry_state"]
    expected_goals = sidecar.call_goal_bindings[call_id]
    prompt_context = deepcopy(payload["problem_planning_context"])
    assert prompt_context == planning_context.to_prompt_payload(
        goal_unit_ids=expected_goals
    )
    assert "problem_retry_context" not in retry_payload
    _assert_prompt_hides_authority(
        payload["problem_planning_context"],
        planning_context=planning_context,
    )


def test_strategy_payload_without_checkpoint_keeps_full_planning_context(
    tmp_path,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        problem_payload,
        _registry,
        planner_context,
        catalog,
        _plan,
        _validation,
        _reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASE)
    retry_inputs = replace(
        inputs,
        previous_errors=[{"code": "extraction.problem_ir_invalid_json"}],
    )

    payload = StrategyPayloadBuilder().build(
        retry_inputs,
        problem_payload=problem_payload,
        planner_state_context=planner_context,
        problem_planning_context=planning_context,
        problem_binding_catalog=catalog,
    )

    prompt_context = deepcopy(payload["problem_planning_context"])
    assert prompt_context == planning_context.to_prompt_payload()
    assert payload["previous_attempt_state"]["latest_retry_state"] is None


def test_goal_retry_projection_rejects_revision_and_call_authority_drift(
    tmp_path,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        _catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASE)
    checkpoint = _checkpoint(
        planner_context,
        reconciliation=reconciliation,
    )
    call_id = checkpoint.problem_call_authorities[0].canonical_call_id
    drifted = replace(
        checkpoint,
        problem_authority=replace(
            checkpoint.problem_authority,
            problem_revision_id="problem-revision:drifted",
        ),
    )

    with pytest.raises(ProblemPlanningRetryError) as revision_error:
        ProblemPlanningRetryProjector().project(
            planning_context,
            drifted,
            (call_id,),
        )
    assert revision_error.value.code == "planner.retry_problem_revision_drift"

    with pytest.raises(ProblemPlanningRetryError) as source_error:
        ProblemPlanningRetryProjector().project(
            planning_context,
            checkpoint,
            ("call:unknown",),
        )
    assert source_error.value.code == (
        "planner.retry_problem_source_binding_drift"
    )


def test_goal_retry_projection_does_not_reenter_extraction_or_solver(
    tmp_path,
    monkeypatch,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        _catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASE)
    checkpoint = _checkpoint(
        planner_context,
        reconciliation=reconciliation,
    )
    call_id = checkpoint.problem_call_authorities[0].canonical_call_id

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Goal retry reentered a forbidden service")

    monkeypatch.setattr(
        DoubaoMultimodalExtractionProvider,
        "complete",
        forbidden,
    )
    monkeypatch.setattr(ProblemDomainProjector, "project", forbidden)
    monkeypatch.setattr(solver_engine, "solve_problem", forbidden)

    projected = ProblemPlanningRetryProjector().project(
        planning_context,
        checkpoint,
        (call_id,),
    )

    assert projected.repair_call_ids == (call_id,)


def test_prompt_audit_is_structural_and_allows_source_text_collision(
    tmp_path,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        _catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASE)
    checkpoint = _checkpoint(
        planner_context,
        reconciliation=reconciliation,
    )
    call_id = checkpoint.problem_call_authorities[0].canonical_call_id
    source_unit_id = next(
        source_id
        for authority in planning_context.ref_authorities.values()
        for source_id in authority.source_unit_ids
    )
    visible_scope_id = next(
        goal.owner_scope_id
        for goal in planning_context.goal_views
        if goal.goal_unit_id
        in checkpoint.problem_call_authorities[0].goal_unit_ids
    )
    colliding_scopes = tuple(
        replace(
            scope,
            source_text=(*scope.source_text, source_unit_id),
        )
        if scope.scope_id == visible_scope_id
        else scope
        for scope in planning_context.scopes
    )
    colliding_context = replace(
        planning_context,
        scopes=colliding_scopes,
    )

    projected = ProblemPlanningRetryProjector().project(
        colliding_context,
        checkpoint,
        (call_id,),
    )

    assert source_unit_id in str(projected.to_prompt_payload())
    with pytest.raises(ProblemPlanningRetryError) as exc_info:
        _audit_prompt_payload(
            {"source_unit_ids": [source_unit_id]},
            planning_context=planning_context,
        )
    assert exc_info.value.code == "planner.problem_scope_visibility_drift"


def test_restored_repair_call_cannot_add_a_foreign_goal(tmp_path) -> None:
    (
        _bundle,
        _planning_context,
        _problem,
        _inputs,
        _problem_payload,
        registry,
        _planner_context,
        _catalog,
        _plan,
        _validation,
        reconciliation,
        replay,
        checkpoint,
    ) = scope_native_retry_checkpoint_fixture(tmp_path, case=CASE)
    reconciliation = replay.functional_reconciliation
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    all_goal_ids = {
        goal_id
        for authority in checkpoint.problem_call_authorities
        for goal_id in authority.goal_unit_ids
    }
    repair_authority = next(
        authority
        for authority in checkpoint.problem_call_authorities
        if set(authority.goal_unit_ids) != all_goal_ids
    )
    foreign_goal_id = next(
        goal_id
        for goal_id in all_goal_ids
        if goal_id not in repair_authority.goal_unit_ids
    )
    repair_checkpoint = replace(
        checkpoint,
        committed_calls=tuple(
            call
            for call in checkpoint.committed_calls
            if call.canonical_call_id
            != repair_authority.canonical_call_id
        ),
    )
    mutated_goal_bindings = dict(sidecar.call_goal_bindings)
    mutated_goal_bindings[repair_authority.canonical_call_id] = tuple(
        sorted((*repair_authority.goal_unit_ids, foreign_goal_id))
    )
    mutated_reconciliation = replace(
        reconciliation,
        functional_problem_binding_context=replace(
            sidecar,
            call_goal_bindings=mutated_goal_bindings,
        ),
    )

    with pytest.raises(FunctionalRetryCheckpointError) as exc_info:
        verify_restored_checkpoint(
            repair_checkpoint,
            reconciliation=mutated_reconciliation,
            handle_registry=registry,
        )

    assert exc_info.value.code == (
        "planner.retry_problem_source_binding_drift"
    )


def _checkpoint(planner_context, *, reconciliation):
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    manifest = planner_context.manifest
    return FunctionalRetryGraphCheckpoint(
        source_context_id=manifest.context_id,
        problem_id=manifest.problem_id,
        family_id=manifest.family_id,
        family_spec_hash=manifest.family_spec_hash,
        capability_pack_hash=manifest.capability_pack_hash,
        problem_authority=FunctionalRetryProblemAuthority(
            planning_context_id=sidecar.planning_context_id,
            problem_revision_id=sidecar.problem_revision_id,
            problem_semantic_hash=sidecar.problem_semantic_hash,
            functional_problem_binding_signature=sidecar.binding_signature,
        ),
        problem_call_authorities=tuple(
            sidecar.source_provenance_for_call(call.call_id)
            for call in reconciliation.plan.calls
        ),
    )


def _assert_prompt_hides_authority(payload, *, planning_context) -> None:
    text = str(payload)
    forbidden = {
        planning_context.planning_context_id,
        planning_context.problem_revision_id,
        planning_context.problem_semantic_hash,
        *(
            source_id
            for authority in planning_context.ref_authorities.values()
            for source_id in authority.source_unit_ids
        ),
        *(
            authority.runtime_node_id
            for authority in planning_context.ref_authorities.values()
        ),
    }
    assert not any(item and item in text for item in forbidden)
