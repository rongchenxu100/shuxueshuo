from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    StepGoal,
    StepPlan,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.state_finalization import (
    StateFinalizationService,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateDependency,
    ProjectedStateWrite,
    StateWriteProvenance,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PROBLEM = REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


def _registry() -> CanonicalHandleRegistry:
    return CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(load_problem_ir(PROBLEM))
    )


def _identity(
    object_ref: str = "point:problem:D",
    *,
    storage_scope: str = "problem",
    ordinal: int = 1,
) -> tuple[MathObjectId, LogicalStateKey, StateSlotId, StateVersionId]:
    object_id = MathObjectId(object_ref, "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, storage_scope)
    return object_id, logical_key, slot_id, StateVersionId(slot_id, ordinal)


def _write(
    step_id: str,
    produced_handle: str,
    *,
    object_ref: str = "point:problem:D",
    storage_scope: str = "problem",
    ordinal: int = 1,
    action: str = "create",
    previous_version_id: StateVersionId | None = None,
    source_version_ids: tuple[StateVersionId, ...] = (),
) -> ProjectedStateWrite:
    object_id, logical_key, slot_id, version_id = _identity(
        object_ref,
        storage_scope=storage_scope,
        ordinal=ordinal,
    )
    return ProjectedStateWrite(
        step_id=step_id,
        produced_handle=produced_handle,
        state_slot_id=(
            f"{object_ref}.coordinate@{storage_scope}:Point"
        ),
        write_mode="transition" if action == "transition" else "create",
        runtime_type="Point",
        object_ref=object_ref,
        return_name="point",
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=slot_id,
        selected_version_id=version_id,
        previous_version_id=previous_version_id,
        source_version_ids=source_version_ids,
        allocation_action=action,
    )


def _plan(
    step_id: str,
    *,
    source_path: str,
    target_path: str,
) -> StepPlan:
    return StepPlan(
        step_id=step_id,
        goal=StepGoal(
            goal_id=f"{step_id}_goal",
            type="derive_point",
            target_path=target_path,
            scope_id="problem",
        ),
        scope="problem",
        invocations=[
            MethodInvocation(
                invocation_id=f"{step_id}_invocation",
                method_id="synthetic_point",
                scope="problem",
                outputs={"point": source_path},
            )
        ],
        promote_outputs={source_path: target_path},
    )


def _provenance(write: ProjectedStateWrite) -> StateWriteProvenance:
    assert write.math_object_id is not None
    assert write.logical_state_key is not None
    assert write.typed_slot_id is not None
    assert write.selected_version_id is not None
    return StateWriteProvenance(
        step_id=write.step_id,
        scope_id="problem",
        capability_id="synthetic_point",
        produced_handle=write.produced_handle,
        output_key="point",
        runtime_type="Point",
        identity_policy="target_object",
        identity_role="point",
        object_ref=write.object_ref,
        state_slot_id=write.state_slot_id,
        write_mode=write.write_mode,
        math_object_id=write.math_object_id,
        logical_state_key=write.logical_state_key,
        typed_slot_id=write.typed_slot_id,
        selected_version_id=write.selected_version_id,
        previous_version_id=write.previous_version_id,
        allocation_action=write.allocation_action,
        return_name=write.return_name,
    )


def test_logical_finalizer_treats_answer_projection_as_writer_alias() -> None:
    state = _write("derive_d", "point:problem:D")
    answer = _write("derive_d", "answer:i.axis_point")

    result = StateFinalizationService().finalize_logical_graph(
        (state, answer),
        step_scopes={"derive_d": "problem"},
        handle_registry=_registry(),
    )

    assert result.ok
    assert {item.selected_version_id for item in result.finalized_writes} == {
        state.selected_version_id
    }


def test_logical_finalizer_accepts_transition_and_rejects_stale_read() -> None:
    first = _write("create_d", "fact:problem:d_v1")
    assert first.selected_version_id is not None
    second = _write(
        "close_d",
        "fact:problem:d_v2",
        ordinal=2,
        action="transition",
        previous_version_id=first.selected_version_id,
    )
    service = StateFinalizationService()

    assert service.finalize_logical_graph(
        (first, second),
        step_scopes={"create_d": "problem", "close_d": "problem"},
        handle_registry=_registry(),
    ).ok

    dependency = ProjectedStateDependency(
        step_id="create_d",
        state_slot_id=second.state_slot_id,
        produced_handle=second.produced_handle,
        source_step_id="close_d",
        source_return_name="point",
        state_version_id=second.selected_version_id,
    )
    with pytest.raises(
        StrategyDraftValidationError,
        match="state.read_version_unresolved",
    ):
        service.finalize_logical_graph(
            (first, second),
            dependencies=(dependency,),
            step_scopes={"create_d": "problem", "close_d": "problem"},
            handle_registry=_registry(),
        )


def test_compiled_finalizer_accepts_transition_on_one_destination() -> None:
    first = _write("create_d", "fact:problem:d_v1")
    assert first.selected_version_id is not None
    second = _write(
        "close_d",
        "fact:problem:d_v2",
        ordinal=2,
        action="transition",
        previous_version_id=first.selected_version_id,
    )
    target = "$problem.facts.D_coordinate"
    result = StateFinalizationService().finalize_compiled_graph(
        (first, second),
        (_provenance(first), _provenance(second)),
        (
            _plan(
                "create_d",
                source_path="$step.create_d.facts.point",
                target_path=target,
            ),
            _plan(
                "close_d",
                source_path="$step.close_d.facts.point",
                target_path=target,
            ),
        ),
        handle_registry=_registry(),
    )

    assert result.ok
    assert len(result.runtime_destinations) == 2
    assert (
        result.to_payload()
        == StateFinalizationService().finalize_compiled_graph(
            (first, second),
            (_provenance(first), _provenance(second)),
            (
                _plan(
                    "create_d",
                    source_path="$step.create_d.facts.point",
                    target_path=target,
                ),
                _plan(
                    "close_d",
                    source_path="$step.close_d.facts.point",
                    target_path=target,
                ),
            ),
            handle_registry=_registry(),
        ).to_payload()
    )


def test_compiled_finalizer_accepts_three_version_transition_chain() -> None:
    first = _write("create_d", "fact:problem:d_v1")
    assert first.selected_version_id is not None
    second = _write(
        "refine_d",
        "fact:problem:d_v2",
        ordinal=2,
        action="transition",
        previous_version_id=first.selected_version_id,
    )
    assert second.selected_version_id is not None
    third = _write(
        "close_d",
        "fact:problem:d_v3",
        ordinal=3,
        action="transition",
        previous_version_id=second.selected_version_id,
    )
    target = "$problem.facts.D_coordinate"

    result = StateFinalizationService().finalize_compiled_graph(
        (first, second, third),
        (
            _provenance(first),
            _provenance(second),
            _provenance(third),
        ),
        tuple(
            _plan(
                write.step_id,
                source_path=f"$step.{write.step_id}.facts.point",
                target_path=target,
            )
            for write in (first, second, third)
        ),
        handle_registry=_registry(),
    )

    assert result.ok
    assert [
        item.projected_version_id.ordinal
        for item in result.runtime_destinations
    ] == [1, 2, 3]


def test_logical_finalizer_uses_typed_topology_not_write_order() -> None:
    producer = _write("create_d", "fact:problem:d_v1")
    assert producer.selected_version_id is not None
    consumer = _write(
        "close_d",
        "fact:problem:d_v2",
        ordinal=2,
        action="transition",
        previous_version_id=producer.selected_version_id,
        source_version_ids=(producer.selected_version_id,),
    )
    dependency = ProjectedStateDependency(
        step_id="close_d",
        state_slot_id=producer.state_slot_id,
        produced_handle=producer.produced_handle,
        source_step_id="create_d",
        source_return_name="point",
        state_version_id=producer.selected_version_id,
    )

    result = StateFinalizationService().finalize_logical_graph(
        (consumer, producer),
        dependencies=(dependency,),
        step_scopes={"close_d": "problem", "create_d": "problem"},
        handle_registry=_registry(),
    )

    assert result.ok
    assert [item.call_id for item in result.finalized_writes] == [
        "create_d",
        "close_d",
    ]


def test_compiled_finalizer_rejects_different_objects_on_one_destination() -> None:
    first = _write("derive_d", "fact:problem:d")
    second = _write(
        "derive_n",
        "fact:problem:n",
        object_ref="point:ii:N",
    )
    target = "$problem.facts.shared_coordinate"

    with pytest.raises(
        StrategyDraftValidationError,
        match="state.runtime_destination_collision",
    ):
        StateFinalizationService().finalize_compiled_graph(
            (first, second),
            (_provenance(first), _provenance(second)),
            (
                _plan(
                    "derive_d",
                    source_path="$step.derive_d.facts.point",
                    target_path=target,
                ),
                _plan(
                    "derive_n",
                    source_path="$step.derive_n.facts.point",
                    target_path=target,
                ),
            ),
            handle_registry=_registry(),
        )


def test_compiled_finalizer_rejects_answer_for_another_math_object() -> None:
    answer = _write(
        "derive_wrong_answer",
        "answer:i.axis_point",
        object_ref="point:ii:N",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="state.answer_object_identity_mismatch",
    ):
        StateFinalizationService().finalize_compiled_graph(
            (answer,),
            (_provenance(answer),),
            (
                _plan(
                    "derive_wrong_answer",
                    source_path="$step.derive_wrong_answer.facts.point",
                    target_path="$question.i.answers.axis_point",
                ),
            ),
            handle_registry=_registry(),
        )


def test_compiled_finalizer_rejects_mismatched_answer_alias_provenance() -> None:
    state = _write(
        "derive_wrong_answer",
        "fact:i_2:g_candidates",
        object_ref="point:i_2:G",
    )
    answer_alias = replace(
        _provenance(state),
        produced_handle="answer:i.axis_point",
        math_object_id=None,
        logical_state_key=None,
        typed_slot_id=None,
        selected_version_id=None,
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="state.answer_object_identity_mismatch",
    ):
        StateFinalizationService().finalize_compiled_graph(
            (state,),
            (answer_alias,),
            (
                _plan(
                    "derive_wrong_answer",
                    source_path="$step.derive_wrong_answer.facts.point",
                    target_path="$question.i.answers.axis_point",
                ),
            ),
            handle_registry=_registry(),
        )


def test_logical_finalizer_rejects_sibling_private_source_version() -> None:
    source = _write(
        "derive_private_d",
        "fact:ii_1:private_d",
        storage_scope="ii_1",
    )
    assert source.selected_version_id is not None
    consumer = _write(
        "derive_other_d",
        "fact:ii_2:other_d",
        storage_scope="ii_2",
        source_version_ids=(source.selected_version_id,),
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="state.read_version_unresolved",
    ):
        StateFinalizationService().finalize_logical_graph(
            (source, consumer),
            step_scopes={
                "derive_private_d": "ii_1",
                "derive_other_d": "ii_2",
            },
            handle_registry=_registry(),
        )


def test_compiled_finalizer_allows_unmaterialized_optional_return() -> None:
    optional = _write("derive_optional", "fact:problem:optional_point")

    result = StateFinalizationService().finalize_compiled_graph(
        (optional,),
        (),
        (),
        handle_registry=_registry(),
    )

    assert result.ok
    assert result.runtime_destinations == ()


def test_logical_finalizer_rejects_unknown_transition_predecessor() -> None:
    _, _, slot_id, _ = _identity()
    missing = StateVersionId(slot_id, 99)
    transition = _write(
        "close_d",
        "fact:problem:d_v2",
        ordinal=2,
        action="transition",
        previous_version_id=missing,
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="state.transition_source_unresolved",
    ):
        StateFinalizationService().finalize_logical_graph(
            (transition,),
            step_scopes={"close_d": "problem"},
            handle_registry=_registry(),
        )


def test_logical_finalizer_rejects_unknown_reused_version() -> None:
    reused = _write(
        "reuse_d",
        "fact:problem:d_reused",
        ordinal=99,
        action="reuse",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="state.read_version_unresolved",
    ):
        StateFinalizationService().finalize_logical_graph(
            (reused,),
            step_scopes={"reuse_d": "problem"},
            handle_registry=_registry(),
        )


def test_logical_finalizer_treats_cross_step_reuse_as_reference() -> None:
    producer = _write("create_d", "fact:problem:d")
    reused = _write(
        "reuse_d",
        "answer:i.axis_point",
        action="reuse",
    )

    result = StateFinalizationService().finalize_logical_graph(
        (reused, producer),
        step_scopes={"reuse_d": "i", "create_d": "problem"},
        handle_registry=_registry(),
    )

    assert result.ok
    assert [item.call_id for item in result.finalized_writes] == [
        "create_d",
        "reuse_d",
    ]
    assert {
        item.call_id: item.logical_writer_status
        for item in result.decisions
    } == {
        "create_d": "valid",
        "reuse_d": "reused",
    }


def test_logical_finalizer_requires_exact_dependency_version_to_exist() -> None:
    write = _write("derive_d", "fact:problem:d")
    _, _, slot_id, _ = _identity(ordinal=0)
    missing = StateVersionId(slot_id, 99)
    dependency = ProjectedStateDependency(
        step_id="derive_d",
        state_slot_id=write.state_slot_id,
        produced_handle="point:problem:D",
        arg_name="point",
        state_version_id=missing,
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="state.read_version_unresolved",
    ):
        StateFinalizationService().finalize_logical_graph(
            (write,),
            dependencies=(dependency,),
            step_scopes={"derive_d": "problem"},
            handle_registry=_registry(),
        )


def test_logical_finalizer_accepts_whitelisted_context_version() -> None:
    object_id, logical_key, slot_id, initial = _identity(ordinal=0)
    transition = _write(
        "close_d",
        "fact:problem:d_v1",
        ordinal=1,
        action="transition",
        previous_version_id=initial,
        source_version_ids=(initial,),
    )
    known = IndexedStateVersion(
        version_id=initial,
        valid_scope_id="problem",
        producer_call_id=None,
        produced_handle="point:problem:D",
    )

    result = StateFinalizationService().finalize_logical_graph(
        (transition,),
        known_versions=(known,),
        dependencies=(
            ProjectedStateDependency(
                step_id="close_d",
                state_slot_id=transition.state_slot_id,
                produced_handle="point:problem:D",
                arg_name="point",
                state_version_id=initial,
            ),
        ),
        step_scopes={"close_d": "problem"},
        handle_registry=_registry(),
    )

    assert result.ok
    assert transition.logical_state_key == logical_key
    assert transition.math_object_id == object_id
    assert transition.typed_slot_id == slot_id


def test_dependency_refinement_compares_typed_symbol_identity() -> None:
    _object_id, _logical_key, _slot_id, initial = _identity(ordinal=0)
    symbol_id = MathObjectId(
        "symbol:problem:a",
        "symbol",
        "problem",
    )
    transition = replace(
        _write(
            "close_d",
            "fact:problem:d_v1",
            ordinal=1,
            action="transition",
            previous_version_id=initial,
            source_version_ids=(initial,),
        ),
        transition_kind="dependency_refinement",
        free_symbol_refs=("symbol:problem:a",),
        free_symbol_ids=(symbol_id,),
    )
    known = IndexedStateVersion(
        version_id=initial,
        valid_scope_id="problem",
        producer_call_id=None,
        produced_handle="point:problem:D",
        free_symbol_refs=("a",),
        free_symbol_ids=(symbol_id,),
    )

    result = StateFinalizationService().finalize_logical_graph(
        (transition,),
        known_versions=(known,),
        step_scopes={"close_d": "problem"},
        handle_registry=_registry(),
    )

    assert result.ok


def test_dependency_refinement_rejects_distinct_symbol_identity() -> None:
    _object_id, _logical_key, _slot_id, initial = _identity(ordinal=0)
    previous_symbol = MathObjectId(
        "symbol:problem:a",
        "symbol",
        "problem",
    )
    current_symbol = MathObjectId(
        "symbol:ii:a",
        "symbol",
        "ii",
    )
    transition = replace(
        _write(
            "refine_d",
            "fact:problem:d_v1",
            ordinal=1,
            action="transition",
            previous_version_id=initial,
            source_version_ids=(initial,),
        ),
        transition_kind="dependency_refinement",
        free_symbol_refs=("a",),
        free_symbol_ids=(current_symbol,),
    )
    known = IndexedStateVersion(
        version_id=initial,
        valid_scope_id="problem",
        producer_call_id=None,
        produced_handle="point:problem:D",
        free_symbol_refs=("a",),
        free_symbol_ids=(previous_symbol,),
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="dependency refinement adds free symbols",
    ):
        StateFinalizationService().finalize_logical_graph(
            (transition,),
            known_versions=(known,),
            step_scopes={"refine_d": "problem"},
            handle_registry=_registry(),
        )


def test_compiled_finalizer_rejects_unallocated_typed_provenance() -> None:
    allocated = _write("derive_d", "fact:problem:d")
    extra = replace(
        _provenance(allocated),
        produced_handle="fact:problem:unexpected_d",
        return_name="unexpected_point",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.contract_runtime_destination_drift",
    ):
        StateFinalizationService().finalize_compiled_graph(
            (allocated,),
            (extra,),
            (
                _plan(
                    "derive_d",
                    source_path="$step.derive_d.facts.point",
                    target_path="$problem.facts.D_coordinate",
                ),
            ),
            handle_registry=_registry(),
        )
