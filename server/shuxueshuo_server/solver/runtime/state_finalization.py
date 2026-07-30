"""Typed logical-state and runtime-destination finalization.

B1 allocates state versions and B2 places their canonical producers.  This
module is the final validation boundary: it never reallocates or moves a call;
it only proves that the projected and compiled writes preserve those typed
decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.binding_selector_semantics import (
    selector_semantics,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.models import StepPlan
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    LogicalStateKey,
    RuntimeDestinationKey,
    StateAllocationAction,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateDependency,
    ProjectedStateWrite,
    StateWriteProvenance,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.utils import unique_ordered

StateFinalizerMode = Literal["shadow", "authoritative"]
StateProjectionKind = Literal["object", "answer", "fact", "call_local"]


@dataclass(frozen=True)
class StateProjectionDestination:
    semantic_ref: str
    runtime_path: str
    destination_key: RuntimeDestinationKey
    projection_kind: StateProjectionKind

    def to_payload(self) -> dict[str, Any]:
        return {
            "semantic_ref": self.semantic_ref,
            "runtime_path": self.runtime_path,
            "destination_key": self.destination_key.to_payload(),
            "projection_kind": self.projection_kind,
        }


@dataclass(frozen=True)
class CompiledStateDestination:
    step_id: str
    return_name: str
    source_output_path: str
    promoted_runtime_path: str
    runtime_type: str
    projected_version_id: StateVersionId
    destination_key: RuntimeDestinationKey
    semantic_ref: str
    projection_kind: StateProjectionKind

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "return_name": self.return_name,
            "source_output_path": self.source_output_path,
            "promoted_runtime_path": self.promoted_runtime_path,
            "runtime_type": self.runtime_type,
            "projected_version_id": self.projected_version_id.to_payload(),
            "destination_key": self.destination_key.to_payload(),
            "semantic_ref": self.semantic_ref,
            "projection_kind": self.projection_kind,
        }


@dataclass(frozen=True)
class FinalizedStateWrite:
    call_id: str
    return_name: str
    logical_state_key: LogicalStateKey
    selected_version_id: StateVersionId
    previous_version_id: StateVersionId | None
    source_version_ids: tuple[StateVersionId, ...]
    allocation_action: StateAllocationAction
    runtime_destinations: tuple[StateProjectionDestination, ...] = ()
    projection_handles: tuple[str, ...] = ()
    canonical_producer_call_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "return_name": self.return_name,
            "logical_state_key": self.logical_state_key.to_payload(),
            "selected_version_id": self.selected_version_id.to_payload(),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "source_version_ids": [
                item.to_payload() for item in self.source_version_ids
            ],
            "allocation_action": self.allocation_action,
            "runtime_destinations": [
                item.to_payload() for item in self.runtime_destinations
            ],
            "projection_handles": list(self.projection_handles),
            "canonical_producer_call_id": self.canonical_producer_call_id,
        }


@dataclass(frozen=True)
class StateFinalizationDecision:
    version_id: StateVersionId
    call_id: str
    return_name: str
    logical_writer_status: str
    destination_writer_status: str = "not_compiled"
    projection_handles: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id.to_payload(),
            "call_id": self.call_id,
            "return_name": self.return_name,
            "logical_writer_status": self.logical_writer_status,
            "destination_writer_status": self.destination_writer_status,
            "projection_handles": list(self.projection_handles),
        }


@dataclass(frozen=True)
class StateFinalizationMismatch:
    code: str
    message: str
    call_id: str | None = None
    return_name: str | None = None
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "call_id": self.call_id,
            "return_name": self.return_name,
        }
        if self.details is not None:
            payload["details"] = dict(self.details)
        return payload


@dataclass(frozen=True)
class StateFinalizationResult:
    finalized_writes: tuple[FinalizedStateWrite, ...] = ()
    decisions: tuple[StateFinalizationDecision, ...] = ()
    mismatches: tuple[StateFinalizationMismatch, ...] = ()
    runtime_destinations: tuple[CompiledStateDestination, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "finalized_writes": [
                item.to_payload() for item in self.finalized_writes
            ],
            "decisions": [item.to_payload() for item in self.decisions],
            "mismatches": [item.to_payload() for item in self.mismatches],
            "runtime_destinations": [
                item.to_payload() for item in self.runtime_destinations
            ],
        }

    def raise_for_mismatches(self) -> None:
        if not self.mismatches:
            return
        first = self.mismatches[0]
        location = ""
        if first.call_id is not None:
            location = f" call={first.call_id}"
        if first.return_name is not None:
            location += f" return={first.return_name}"
        details = f" details={first.details}" if first.details else ""
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            f"{first.code}: {first.message}{location}{details}"
        )


class StateFinalizationService:
    """Validate typed state versions and their compiled destinations."""

    def finalize_logical_graph(
        self,
        writes: Sequence[ProjectedStateWrite],
        *,
        dependencies: Sequence[ProjectedStateDependency] = (),
        known_versions: Sequence[IndexedStateVersion] = (),
        step_scopes: Mapping[str, str],
        handle_registry: CanonicalHandleRegistry,
        mode: StateFinalizerMode = "authoritative",
    ) -> StateFinalizationResult:
        typed_writes = tuple(
            item for item in writes if _requires_typed_finalization(item)
        )
        mismatches: list[StateFinalizationMismatch] = []
        writes_by_version = _writer_writes_by_version(typed_writes)
        order_by_step = _topological_step_order(
            step_scopes,
            writes=typed_writes,
            writes_by_version=writes_by_version,
            dependencies=dependencies,
        )
        typed_writes = tuple(
            sorted(
                typed_writes,
                key=lambda item: order_by_step.get(
                    item.step_id,
                    len(order_by_step),
                ),
            )
        )
        known_by_version = {
            item.version_id: item for item in known_versions
        }
        first_writer_by_logical: dict[
            LogicalStateKey, list[ProjectedStateWrite]
        ] = {}
        finalized: list[FinalizedStateWrite] = []
        decisions: list[StateFinalizationDecision] = []

        for write in typed_writes:
            mismatch_count = len(mismatches)
            _validate_typed_write_shape(write, mismatches)
            version_id = write.selected_version_id
            logical_key = write.logical_state_key
            action = write.allocation_action
            if version_id is None or logical_key is None or action is None:
                continue
            if version_id.slot_id.logical_key != logical_key:
                mismatches.append(
                    _mismatch(
                        "state.object_slot_identity_mismatch",
                        "selected StateVersion belongs to a different logical state",
                        write,
                    )
                )
            if (
                write.typed_slot_id is not None
                and version_id.slot_id != write.typed_slot_id
            ):
                mismatches.append(
                    _mismatch(
                        "state.object_slot_identity_mismatch",
                        "selected StateVersion does not use the allocated slot",
                        write,
                    )
                )
            _validate_allocation_action(write, mismatches)
            if action == "reuse":
                _validate_reused_version(
                    write,
                    writes_by_version=writes_by_version,
                    known_by_version=known_by_version,
                    order_by_step=order_by_step,
                    step_scopes=step_scopes,
                    handle_registry=handle_registry,
                    mismatches=mismatches,
                )
            previous = write.previous_version_id
            if previous is not None:
                _validate_source_version(
                    write,
                    previous,
                    relation="transition",
                    writes_by_version=writes_by_version,
                    known_by_version=known_by_version,
                    order_by_step=order_by_step,
                    step_scopes=step_scopes,
                    handle_registry=handle_registry,
                    mismatches=mismatches,
                )
                if previous.slot_id.logical_key != logical_key:
                    mismatches.append(
                        _mismatch(
                            "state.object_slot_identity_mismatch",
                            "transition predecessor belongs to another logical state",
                            write,
                        )
                    )
            for source in write.source_version_ids:
                _validate_source_version(
                    write,
                    source,
                    relation="source",
                    writes_by_version=writes_by_version,
                    known_by_version=known_by_version,
                    order_by_step=order_by_step,
                    step_scopes=step_scopes,
                    handle_registry=handle_registry,
                    mismatches=mismatches,
                )
            if (
                write.transition_kind == "dependency_refinement"
                and previous is not None
            ):
                prior = _first_write(writes_by_version.get(previous, ()))
                prior_free_symbols = (
                    prior.free_symbol_refs
                    if prior is not None
                    else (
                        known_by_version[previous].free_symbol_refs
                        if previous in known_by_version
                        else ()
                    )
                )
                if (
                    (prior is not None or previous in known_by_version)
                    and not set(write.free_symbol_refs)
                    <= set(prior_free_symbols)
                ):
                    mismatches.append(
                        _mismatch(
                            "planner.state_finalization_drift",
                            "dependency refinement adds free symbols",
                            write,
                            details={
                                "previous_free_symbols": list(
                                    prior_free_symbols
                                ),
                                "current_free_symbols": list(
                                    write.free_symbol_refs
                                ),
                            },
                        )
                    )

            if action != "reuse":
                prior_versions = writes_by_version.get(version_id, ())
                if any(
                    item.step_id != write.step_id for item in prior_versions
                ):
                    mismatches.append(
                        _mismatch(
                            "state.logical_duplicate_writer",
                            "multiple canonical calls write the same StateVersion",
                            write,
                        )
                    )
            if action == "create":
                for prior in first_writer_by_logical.get(logical_key, ()):
                    if prior.selected_version_id == version_id:
                        continue
                    if _writes_overlap(
                        prior,
                        write,
                        step_scopes=step_scopes,
                        handle_registry=handle_registry,
                    ):
                        mismatches.append(
                            _mismatch(
                                "state.logical_duplicate_writer",
                                "unrelated creates overlap for one logical state",
                                write,
                                details={"previous_call_id": prior.step_id},
                            )
                        )
                        break
            elif action == "isolated":
                for prior in first_writer_by_logical.get(logical_key, ()):
                    prior_version = prior.selected_version_id
                    if prior_version is None:
                        continue
                    same_slot = prior_version.slot_id == version_id.slot_id
                    prior_scope = step_scopes.get(
                        prior.step_id,
                        prior.step_id,
                    )
                    widens_into_prior = _write_visible_from(
                        write,
                        prior_scope,
                        handle_registry=handle_registry,
                    )
                    if same_slot or widens_into_prior:
                        mismatches.append(
                            _mismatch(
                                "state.logical_duplicate_writer",
                                (
                                    "isolated write overlaps an earlier "
                                    "state in the same or narrower scope"
                                ),
                                write,
                                details={
                                    "previous_call_id": prior.step_id
                                },
                            )
                        )
                        break

            if action != "reuse":
                first_writer_by_logical.setdefault(logical_key, []).append(
                    write
                )
            finalized.append(
                FinalizedStateWrite(
                    call_id=write.step_id,
                    return_name=write.return_name or "",
                    logical_state_key=logical_key,
                    selected_version_id=version_id,
                    previous_version_id=write.previous_version_id,
                    source_version_ids=write.source_version_ids,
                    allocation_action=action,
                    projection_handles=(write.produced_handle,),
                    canonical_producer_call_id=(
                        write.canonical_producer_call_id or write.step_id
                    ),
                )
            )
            decisions.append(
                StateFinalizationDecision(
                    version_id=version_id,
                    call_id=write.step_id,
                    return_name=write.return_name or "",
                    logical_writer_status=(
                        "reused"
                        if action == "reuse"
                        and len(mismatches) == mismatch_count
                        else "valid"
                        if len(mismatches) == mismatch_count
                        else "invalid"
                    ),
                    projection_handles=(write.produced_handle,),
                )
            )

        _validate_exact_dependencies(
            dependencies,
            typed_writes=typed_writes,
            writes_by_version=writes_by_version,
            known_by_version=known_by_version,
            order_by_step=order_by_step,
            step_scopes=step_scopes,
            handle_registry=handle_registry,
            mismatches=mismatches,
        )
        result = StateFinalizationResult(
            finalized_writes=tuple(finalized),
            decisions=tuple(decisions),
            mismatches=tuple(mismatches),
        )
        if mode == "authoritative":
            result.raise_for_mismatches()
        return result

    def finalize_compiled_graph(
        self,
        writes: Sequence[ProjectedStateWrite],
        provenance: Sequence[StateWriteProvenance],
        plans: Sequence[StepPlan],
        *,
        question_goals: Sequence[QuestionGoal] = (),
        handle_registry: CanonicalHandleRegistry,
        mode: StateFinalizerMode = "authoritative",
    ) -> StateFinalizationResult:
        mismatches: list[StateFinalizationMismatch] = []
        projected_by_handle = {
            (item.step_id, item.produced_handle): item
            for item in writes
            if _requires_typed_finalization(item)
        }
        call_local_by_handle = {
            (item.step_id, item.produced_handle): item
            for item in writes
            if not _requires_typed_finalization(item)
        }
        projected_by_return: dict[
            tuple[str, str], list[ProjectedStateWrite]
        ] = {}
        for write in projected_by_handle.values():
            if write.return_name is not None:
                projected_by_return.setdefault(
                    (write.step_id, write.return_name),
                    [],
                ).append(write)
        call_local_by_return = {
            (item.step_id, item.return_name)
            for item in call_local_by_handle.values()
            if item.return_name is not None
        }
        plans_by_step = {item.step_id: item for item in plans}
        destinations: list[CompiledStateDestination] = []
        goal_by_handle = {f"answer:{item.id}": item for item in question_goals}

        for item in provenance:
            if _projection_kind(item.produced_handle) == "answer":
                _validate_answer_provenance_identity(
                    item,
                    handle_registry=handle_registry,
                    mismatches=mismatches,
                )
            projected = projected_by_handle.get(
                (item.step_id, item.produced_handle)
            )
            if projected is None and item.return_name is not None:
                candidates = projected_by_return.get(
                    (item.step_id, item.return_name),
                    (),
                )
                if len(candidates) == 1:
                    projected = candidates[0]
            if projected is None:
                if (
                    (item.step_id, item.produced_handle)
                    in call_local_by_handle
                    or (
                        item.return_name is not None
                        and (item.step_id, item.return_name)
                        in call_local_by_return
                    )
                ):
                    continue
                if _has_typed_provenance(item):
                    mismatches.append(
                        StateFinalizationMismatch(
                            "planner.contract_runtime_destination_drift",
                            "compiler produced a typed state write that B2 did not allocate",
                            call_id=item.step_id,
                            return_name=item.return_name,
                            details={
                                "produced_handle": item.produced_handle,
                                "output_key": item.output_key,
                            },
                        )
                    )
                continue
            _validate_compiled_identity(projected, item, mismatches)
            version_id = projected.selected_version_id
            logical_key = projected.logical_state_key
            if version_id is None or logical_key is None:
                continue
            plan = plans_by_step.get(item.step_id)
            source_path = (
                _compiled_source_output_path(plan, item.output_key)
                if plan is not None
                else None
            )
            target_path = (
                plan.promote_outputs.get(source_path)
                if plan is not None and source_path is not None
                else None
            )
            if source_path is None or target_path is None:
                mismatches.append(
                    _mismatch(
                        "planner.contract_runtime_destination_drift",
                        "compiled return has no unique promoted runtime destination",
                        projected,
                        details={"output_key": item.output_key},
                    )
                )
                continue
            destination_key = RuntimeDestinationKey(
                logical_key.object_id,
                logical_key.state_kind,
                logical_key.runtime_type,
                target_path,
            )
            kind = _projection_kind(item.produced_handle)
            destinations.append(
                CompiledStateDestination(
                    step_id=item.step_id,
                    return_name=projected.return_name or item.return_name or "",
                    source_output_path=source_path,
                    promoted_runtime_path=target_path,
                    runtime_type=item.runtime_type,
                    projected_version_id=version_id,
                    destination_key=destination_key,
                    semantic_ref=item.produced_handle,
                    projection_kind=kind,
                )
            )
            if kind == "answer":
                target_object = handle_registry.answer_target_handles.get(
                    item.produced_handle
                )
                if (
                    target_object is not None
                    and target_object != logical_key.object_id.value
                ):
                    mismatches.append(
                        _mismatch(
                            "state.answer_object_identity_mismatch",
                            "answer destination targets a different MathObject",
                            projected,
                            details={
                                "answer_handle": item.produced_handle,
                                "target_object_ref": target_object,
                            },
                        )
                    )
                goal = goal_by_handle.get(item.produced_handle)
                if (
                    goal is not None
                    and goal.value_type != item.runtime_type
                    and logical_key.runtime_type != goal.value_type
                ):
                    mismatches.append(
                        _mismatch(
                            "planner.contract_runtime_destination_drift",
                            "answer destination runtime type differs from its goal",
                            projected,
                        )
                    )

        _validate_destination_ledger(
            destinations,
            writes=projected_by_handle,
            mismatches=mismatches,
        )
        decisions = _compiled_decisions(destinations, mismatches)
        result = StateFinalizationResult(
            decisions=decisions,
            mismatches=tuple(mismatches),
            runtime_destinations=tuple(destinations),
        )
        if mode == "authoritative":
            result.raise_for_mismatches()
        return result


def _validate_answer_provenance_identity(
    provenance: StateWriteProvenance,
    *,
    handle_registry: CanonicalHandleRegistry,
    mismatches: list[StateFinalizationMismatch],
) -> None:
    """Fail closed when an answer alias carries another MathObject."""

    target_object_ref = handle_registry.answer_target_handles.get(
        provenance.produced_handle
    )
    actual_object_ref = (
        provenance.logical_state_key.object_id.value
        if provenance.logical_state_key is not None
        else provenance.object_ref
    )
    if (
        target_object_ref is None
        or actual_object_ref is None
        or target_object_ref == actual_object_ref
    ):
        return
    mismatches.append(
        StateFinalizationMismatch(
            "state.answer_object_identity_mismatch",
            "answer provenance belongs to a different MathObject",
            call_id=provenance.step_id,
            return_name=provenance.return_name,
            details={
                "answer_handle": provenance.produced_handle,
                "target_object_ref": target_object_ref,
                "actual_object_ref": actual_object_ref,
            },
        )
    )


def project_functional_state_writes(
    plan: Any,
    reconciled_calls: Sequence[Any],
) -> tuple[ProjectedStateWrite, ...]:
    """Project B2 allocations into the shared Functional compiler sidecar."""

    calls_by_id = {call.call_id: call for call in plan.calls}
    result: list[ProjectedStateWrite] = []
    for call in reconciled_calls:
        functional_call = calls_by_id.get(call.call_id)
        for output in call.returns:
            if output.write_mode not in {"create", "transition", "value"}:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: invalid functional return "
                    f"write mode: call={call.call_id}, "
                    f"return={output.return_name}, "
                    f"write_mode={output.write_mode}"
                )
            result.append(
                ProjectedStateWrite(
                    step_id=call.call_id,
                    produced_handle=output.state_handle or output.handle,
                    state_slot_id=output.state_slot_id,
                    write_mode=output.write_mode,
                    runtime_type=output.runtime_type,
                    object_ref=output.object_ref,
                    source_state_slot_ids=output.source_state_slot_ids,
                    dependency_object_refs=output.dependency_object_refs,
                    return_name=output.return_name,
                    expected_result_form=(
                        functional_call.return_expectations.get(
                            output.return_name
                        )
                        if functional_call is not None
                        else None
                    ),
                    transition_kind=output.transition_kind,
                    previous_write_step_id=output.previous_write_step_id,
                    lineage=output.lineage,
                    math_object_id=output.math_object_id,
                    logical_state_key=output.logical_state_key,
                    typed_slot_id=output.typed_slot_id,
                    selected_version_id=output.selected_version_id,
                    previous_version_id=output.previous_version_id,
                    computation_key=output.computation_key,
                    source_version_ids=output.source_version_ids,
                    allocation_action=output.allocation_action,
                    free_symbol_refs=output.free_symbol_refs,
                    canonical_producer_call_id=(
                        output.canonical_producer_call_id
                    ),
                    valid_scope_id=output.valid_scope,
                )
            )
    return tuple(result)


def project_functional_state_dependencies(
    plan: Any,
    reconciled_calls: Sequence[Any],
    *,
    catalog: Any,
    legacy_projection_adapter: Any | None = None,
) -> tuple[ProjectedStateDependency, ...]:
    """Project every exact Functional StateVersion read for B3 validation."""

    calls_by_id = {call.call_id: call for call in plan.calls}
    result: list[ProjectedStateDependency] = []
    from shuxueshuo_server.solver.runtime.functional_legacy_projection import (
        FunctionalLegacyProjectionAdapter,
    )

    adapter = (
        legacy_projection_adapter
        if legacy_projection_adapter is not None
        else FunctionalLegacyProjectionAdapter()
    )
    seen: set[tuple[str, str, StateVersionId]] = set()
    return_by_version = {
        allocation.selected_version_id: (
            call.call_id,
            allocation.return_name,
            allocation,
        )
        for call in reconciled_calls
        for allocation in call.returns
        if allocation.selected_version_id is not None
    }
    for call in reconciled_calls:
        functional_call = calls_by_id.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if functional_call is None or capability is None:
            continue
        public_by_name = {item.name: item for item in capability.args}
        auto_by_name = {item.name: item for item in capability.auto_args}
        for arg_name, values in call.resolved_args.items():
            auto_arg = auto_by_name.get(arg_name)
            if (
                auto_arg is not None
                and auto_arg.binding_authority == "compiler"
                and selector_semantics(auto_arg.selector).mechanical
                and all(
                    value.state_version_id is None
                    for value in values
                )
            ):
                # Compiler-owned target/reference arguments establish identity;
                # they are not materialized state reads. A mechanical role
                # that resolved to an actual StateVersion is different: the
                # compiler must consume that exact version rather than infer a
                # same-object state again from the flattened reads list.
                continue
            if arg_name in functional_call.args:
                source: Literal["wire", "resolver", "context"] = "wire"
            elif (
                (public := public_by_name.get(arg_name)) is not None
                and public.deterministic_resolver is not None
            ) or (
                (auto := auto_by_name.get(arg_name)) is not None
                and auto.binding_authority == "resolver"
            ):
                source = "resolver"
            else:
                source = "context"
            for value in values:
                if value.state_version_id is not None:
                    version_ids = (value.state_version_id,)
                elif value.source_call_id is not None:
                    # A call-local public return is read through its
                    # CallResult edge. Its source_version_ids are transitive
                    # provenance, not exact state reads of this consumer.
                    version_ids = ()
                else:
                    version_ids = unique_ordered(value.source_version_ids)
                for state_version_id in version_ids:
                    producer = return_by_version.get(state_version_id)
                    source_step_id = (
                        producer[0]
                        if producer is not None
                        else value.source_call_id
                    )
                    source_return_name = (
                        producer[1]
                        if producer is not None
                        else value.return_name
                    )
                    source_allocation = (
                        producer[2] if producer is not None else None
                    )
                    state_slot_id = adapter.state_slot_id(
                        state_version_id.slot_id
                    )
                    key = (call.call_id, arg_name, state_version_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append(
                        ProjectedStateDependency(
                            step_id=call.call_id,
                            state_slot_id=state_slot_id,
                            produced_handle=(
                                source_allocation.state_handle
                                or source_allocation.handle
                                if source_allocation is not None
                                else value.handle
                            ),
                            runtime_type=(
                                source_allocation.runtime_type
                                if source_allocation is not None
                                else value.runtime_type
                            ),
                            object_ref=(
                                source_allocation.object_ref
                                if source_allocation is not None
                                else value.object_ref
                            ),
                            arg_name=arg_name,
                            source=source,
                            source_step_id=source_step_id,
                            source_return_name=source_return_name,
                            state_version_id=state_version_id,
                        )
                    )
    return tuple(result)


def expand_functional_dependency_graph(
    dependency_graph: Mapping[str, Sequence[str]],
    *,
    projected_state_writes: Sequence[ProjectedStateWrite],
    projected_state_dependencies: Sequence[ProjectedStateDependency],
) -> dict[str, tuple[str, ...]]:
    """Promote every typed StateVersion dependency to a canonical call edge."""

    result = {
        call_id: list(dependencies)
        for call_id, dependencies in dependency_graph.items()
    }
    writer_call_ids_by_version: dict[StateVersionId, list[str]] = {}
    for write in projected_state_writes:
        if (
            write.selected_version_id is None
            or write.allocation_action == "reuse"
        ):
            continue
        writer_call_ids_by_version.setdefault(
            write.selected_version_id,
            [],
        )
        writers = writer_call_ids_by_version[write.selected_version_id]
        if write.step_id not in writers:
            writers.append(write.step_id)

    def add_dependency(call_id: str, source_call_id: str) -> None:
        if (
            call_id == source_call_id
            or call_id not in result
            or source_call_id not in result
        ):
            return
        dependencies = result[call_id]
        if source_call_id not in dependencies:
            dependencies.append(source_call_id)

    for dependency in projected_state_dependencies:
        source_call_ids: list[str] = []
        if dependency.source_step_id is not None:
            source_call_ids.append(dependency.source_step_id)
        if dependency.state_version_id is not None:
            for source_call_id in writer_call_ids_by_version.get(
                dependency.state_version_id,
                (),
            ):
                if source_call_id not in source_call_ids:
                    source_call_ids.append(source_call_id)
        for source_call_id in source_call_ids:
            add_dependency(dependency.step_id, source_call_id)

    for write in projected_state_writes:
        source_version_ids = list(write.source_version_ids)
        if write.previous_version_id is not None:
            source_version_ids.append(write.previous_version_id)
        if (
            write.allocation_action == "reuse"
            and write.selected_version_id is not None
        ):
            source_version_ids.append(write.selected_version_id)
        for version_id in source_version_ids:
            for source_call_id in writer_call_ids_by_version.get(
                version_id,
                (),
            ):
                add_dependency(write.step_id, source_call_id)

    return {
        call_id: tuple(dependencies)
        for call_id, dependencies in result.items()
    }


def _requires_typed_finalization(write: ProjectedStateWrite) -> bool:
    return not (
        write.allocation_action == "call_local_value"
        or (
            write.write_mode == "value"
            and write.math_object_id is None
            and write.logical_state_key is None
        )
    )


def _has_typed_provenance(item: StateWriteProvenance) -> bool:
    return any(
        value is not None
        for value in (
            item.math_object_id,
            item.logical_state_key,
            item.typed_slot_id,
            item.selected_version_id,
            item.previous_version_id,
            item.allocation_action,
        )
    )


def _validate_typed_write_shape(
    write: ProjectedStateWrite,
    mismatches: list[StateFinalizationMismatch],
) -> None:
    missing = []
    if write.math_object_id is None:
        missing.append("math_object_id")
    if write.logical_state_key is None:
        missing.append("logical_state_key")
    if write.typed_slot_id is None:
        missing.append("typed_slot_id")
    if write.selected_version_id is None:
        missing.append("selected_version_id")
    if write.allocation_action is None:
        missing.append("allocation_action")
    if missing:
        mismatches.append(
            _mismatch(
                "planner.state_finalization_drift",
                "typed allocation metadata is incomplete",
                write,
                details={"missing": missing},
            )
        )
        return
    logical = write.logical_state_key
    if (
        logical.object_id != write.math_object_id
        or logical.runtime_type != write.runtime_type
    ):
        mismatches.append(
            _mismatch(
                "state.object_slot_identity_mismatch",
                "projected object/type differs from its logical state",
                write,
            )
        )


def _validate_allocation_action(
    write: ProjectedStateWrite,
    mismatches: list[StateFinalizationMismatch],
) -> None:
    action = write.allocation_action
    if action == "transition":
        if write.previous_version_id is None:
            mismatches.append(
                _mismatch(
                    "state.transition_source_unresolved",
                    "authoritative transition has no previous StateVersion",
                    write,
                )
            )
        if write.write_mode != "transition":
            mismatches.append(
                _mismatch(
                    "planner.state_finalization_drift",
                    "transition allocation was projected with another write mode",
                    write,
                )
            )
    elif action in {"create", "isolated"}:
        if write.previous_version_id is not None:
            mismatches.append(
                _mismatch(
                    "planner.state_finalization_drift",
                    "create/isolated allocation unexpectedly has a predecessor",
                    write,
                )
            )
    elif action == "conflict":
        mismatches.append(
            _mismatch(
                "planner.state_finalization_drift",
                "conflicting allocation reached finalization",
                write,
            )
        )


def _writes_by_version(
    writes: Sequence[ProjectedStateWrite],
) -> dict[StateVersionId, list[ProjectedStateWrite]]:
    result: dict[StateVersionId, list[ProjectedStateWrite]] = {}
    for write in writes:
        if write.selected_version_id is not None:
            result.setdefault(write.selected_version_id, []).append(write)
    return result


def _writer_writes_by_version(
    writes: Sequence[ProjectedStateWrite],
) -> dict[StateVersionId, list[ProjectedStateWrite]]:
    return _writes_by_version(
        tuple(
            write
            for write in writes
            if write.allocation_action in {"create", "transition", "isolated"}
        )
    )


def _topological_step_order(
    step_scopes: Mapping[str, str],
    *,
    writes: Sequence[ProjectedStateWrite],
    writes_by_version: Mapping[
        StateVersionId, Sequence[ProjectedStateWrite]
    ],
    dependencies: Sequence[ProjectedStateDependency],
) -> dict[str, int]:
    """Order steps from typed version edges, independent of sidecar ordering."""

    step_ids = list(step_scopes)
    for version_writes in writes_by_version.values():
        for write in version_writes:
            if write.step_id not in step_ids:
                step_ids.append(write.step_id)
    for dependency in dependencies:
        if dependency.step_id not in step_ids:
            step_ids.append(dependency.step_id)
        if (
            dependency.source_step_id is not None
            and dependency.source_step_id not in step_ids
        ):
            step_ids.append(dependency.source_step_id)
    original_position = {
        step_id: index for index, step_id in enumerate(step_ids)
    }
    required_by_step: dict[str, set[str]] = {
        step_id: set() for step_id in step_ids
    }
    for version_writes in writes_by_version.values():
        for write in version_writes:
            source_version_ids = list(write.source_version_ids)
            if write.previous_version_id is not None:
                source_version_ids.append(write.previous_version_id)
            for version_id in source_version_ids:
                for source in writes_by_version.get(version_id, ()):
                    if source.step_id != write.step_id:
                        required_by_step[write.step_id].add(source.step_id)
    for write in writes:
        if (
            write.allocation_action != "reuse"
            or write.selected_version_id is None
        ):
            continue
        for source in writes_by_version.get(write.selected_version_id, ()):
            if source.step_id != write.step_id:
                required_by_step[write.step_id].add(source.step_id)
    for dependency in dependencies:
        source_step_ids = set()
        if dependency.source_step_id is not None:
            source_step_ids.add(dependency.source_step_id)
        if dependency.state_version_id is not None:
            source_step_ids.update(
                write.step_id
                for write in writes_by_version.get(
                    dependency.state_version_id,
                    (),
                )
            )
        required_by_step[dependency.step_id].update(
            source_step_id
            for source_step_id in source_step_ids
            if source_step_id != dependency.step_id
        )

    pending = set(step_ids)
    ordered: list[str] = []
    while pending:
        ready = min(
            (
                step_id
                for step_id in pending
                if not (required_by_step.get(step_id, set()) & pending)
            ),
            key=original_position.__getitem__,
            default=None,
        )
        if ready is None:
            ordered.extend(sorted(pending, key=original_position.__getitem__))
            break
        ordered.append(ready)
        pending.remove(ready)
    return {step_id: index for index, step_id in enumerate(ordered)}


def _validate_reused_version(
    write: ProjectedStateWrite,
    *,
    writes_by_version: Mapping[
        StateVersionId, Sequence[ProjectedStateWrite]
    ],
    known_by_version: Mapping[StateVersionId, IndexedStateVersion],
    order_by_step: Mapping[str, int],
    step_scopes: Mapping[str, str],
    handle_registry: CanonicalHandleRegistry,
    mismatches: list[StateFinalizationMismatch],
) -> None:
    version_id = write.selected_version_id
    if version_id is None:
        return
    source = _first_write(writes_by_version.get(version_id, ()))
    if source is not None:
        if source.step_id == write.step_id:
            return
        if order_by_step.get(source.step_id, -1) >= order_by_step.get(
            write.step_id,
            -1,
        ):
            mismatches.append(
                _mismatch(
                    "state.read_version_unresolved",
                    "reused StateVersion is not produced before its consumer",
                    write,
                    details={"source_call_id": source.step_id},
                )
            )
            return
        consumer_scope = step_scopes.get(write.step_id, write.step_id)
        if not _write_visible_from(
            source,
            consumer_scope,
            handle_registry=handle_registry,
        ):
            mismatches.append(
                _mismatch(
                    "state.read_version_unresolved",
                    "reused StateVersion is not visible to the consumer",
                    write,
                    details={"source_call_id": source.step_id},
                )
            )
        return
    known = known_by_version.get(version_id)
    if known is None:
        mismatches.append(
            _mismatch(
                "state.read_version_unresolved",
                "reused StateVersion is absent from Context and the current graph",
                write,
                details={"version_id": version_id.to_payload()},
            )
        )
        return
    consumer_scope = step_scopes.get(write.step_id, write.step_id)
    if not visible_from_valid_scope(
        known.valid_scope_id,
        scope_id=consumer_scope,
        registry=handle_registry,
    ):
        mismatches.append(
            _mismatch(
                "state.read_version_unresolved",
                "reused Context StateVersion is not visible to the consumer",
                write,
            )
        )


def _validate_source_version(
    write: ProjectedStateWrite,
    version_id: StateVersionId,
    *,
    relation: str,
    writes_by_version: Mapping[
        StateVersionId, Sequence[ProjectedStateWrite]
    ],
    known_by_version: Mapping[StateVersionId, IndexedStateVersion],
    order_by_step: Mapping[str, int],
    step_scopes: Mapping[str, str],
    handle_registry: CanonicalHandleRegistry,
    mismatches: list[StateFinalizationMismatch],
) -> None:
    prior = _first_write(writes_by_version.get(version_id, ()))
    if prior is None:
        known = known_by_version.get(version_id)
        if known is not None:
            consumer_scope = step_scopes.get(write.step_id, write.step_id)
            if not visible_from_valid_scope(
                known.valid_scope_id,
                scope_id=consumer_scope,
                registry=handle_registry,
            ):
                mismatches.append(
                    _mismatch(
                        "state.transition_source_invisible"
                        if relation == "transition"
                        else "state.read_version_unresolved",
                        f"{relation} Context StateVersion is not visible to the consumer",
                        write,
                    )
                )
            return
        mismatches.append(
            _mismatch(
                "state.transition_source_unresolved"
                if relation == "transition"
                else "state.read_version_unresolved",
                f"{relation} StateVersion is absent from Context and the current graph",
                write,
                details={"version_id": version_id.to_payload()},
            )
        )
        return
    if prior.step_id == write.step_id:
        return
    if order_by_step.get(prior.step_id, -1) >= order_by_step.get(
        write.step_id,
        -1,
    ):
        mismatches.append(
            _mismatch(
                "state.transition_source_unresolved"
                if relation == "transition"
                else "state.read_version_unresolved",
                f"{relation} StateVersion is not produced before its consumer",
                write,
                details={"source_call_id": prior.step_id},
            )
        )
        return
    consumer_scope = step_scopes.get(write.step_id, write.step_id)
    if not _write_visible_from(
        prior,
        consumer_scope,
        handle_registry=handle_registry,
    ):
        mismatches.append(
            _mismatch(
                "state.transition_source_invisible"
                if relation == "transition"
                else "state.read_version_unresolved",
                f"{relation} StateVersion is not visible to the consumer",
                write,
                details={"source_call_id": prior.step_id},
            )
        )


def _validate_exact_dependencies(
    dependencies: Sequence[ProjectedStateDependency],
    *,
    typed_writes: Sequence[ProjectedStateWrite],
    writes_by_version: Mapping[
        StateVersionId, Sequence[ProjectedStateWrite]
    ],
    known_by_version: Mapping[StateVersionId, IndexedStateVersion],
    order_by_step: Mapping[str, int],
    step_scopes: Mapping[str, str],
    handle_registry: CanonicalHandleRegistry,
    mismatches: list[StateFinalizationMismatch],
) -> None:
    writes_by_step_return = {
        (item.step_id, item.return_name): item
        for item in typed_writes
        if item.return_name is not None
    }
    for dependency in dependencies:
        version_id = dependency.state_version_id
        if version_id is None and dependency.source_step_id is not None:
            source = writes_by_step_return.get(
                (dependency.source_step_id, dependency.source_return_name)
            )
            if source is None:
                # B1 deliberately keeps value-only/call-local returns outside
                # the cross-call StateVersion ledger. Their producer edge is
                # still validated by the Functional DAG.
                continue
            version_id = source.selected_version_id
        if version_id is None:
            mismatches.append(
                StateFinalizationMismatch(
                    "state.read_version_unresolved",
                    "exact Functional dependency has no StateVersion",
                    call_id=dependency.step_id,
                    details={
                        "arg_name": dependency.arg_name,
                        "produced_handle": dependency.produced_handle,
                    },
                )
            )
            continue
        source = _first_write(writes_by_version.get(version_id, ()))
        if source is None:
            known = known_by_version.get(version_id)
            if known is None:
                mismatches.append(
                    StateFinalizationMismatch(
                        "state.read_version_unresolved",
                        "exact Functional dependency references an unknown StateVersion",
                        call_id=dependency.step_id,
                        details={
                            "arg_name": dependency.arg_name,
                            "version_id": version_id.to_payload(),
                        },
                    )
                )
                continue
            consumer_scope = step_scopes.get(
                dependency.step_id,
                dependency.step_id,
            )
            if not visible_from_valid_scope(
                known.valid_scope_id,
                scope_id=consumer_scope,
                registry=handle_registry,
            ):
                mismatches.append(
                    StateFinalizationMismatch(
                        "state.read_version_unresolved",
                        "exact Context StateVersion dependency is not visible",
                        call_id=dependency.step_id,
                    )
                )
            continue
        if order_by_step.get(source.step_id, -1) >= order_by_step.get(
            dependency.step_id,
            -1,
        ):
            mismatches.append(
                StateFinalizationMismatch(
                    "state.read_version_unresolved",
                    "exact Functional dependency is not produced earlier",
                    call_id=dependency.step_id,
                )
            )
            continue
        consumer_scope = step_scopes.get(
            dependency.step_id,
            dependency.step_id,
        )
        if not _write_visible_from(
            source,
            consumer_scope,
            handle_registry=handle_registry,
        ):
            mismatches.append(
                StateFinalizationMismatch(
                    "state.read_version_unresolved",
                    "exact Functional dependency is not visible",
                    call_id=dependency.step_id,
                )
            )


def _validate_compiled_identity(
    projected: ProjectedStateWrite,
    actual: StateWriteProvenance,
    mismatches: list[StateFinalizationMismatch],
) -> None:
    fields = (
        ("math_object_id", projected.math_object_id, actual.math_object_id),
        (
            "logical_state_key",
            projected.logical_state_key,
            actual.logical_state_key,
        ),
        (
            "selected_version_id",
            projected.selected_version_id,
            actual.selected_version_id,
        ),
        (
            "previous_version_id",
            projected.previous_version_id,
            actual.previous_version_id,
        ),
        ("runtime_type", projected.runtime_type, actual.runtime_type),
    )
    drift = [name for name, expected, observed in fields if expected != observed]
    if drift:
        mismatches.append(
            _mismatch(
                "planner.contract_runtime_destination_drift",
                "compiler state provenance differs from the B2 projection",
                projected,
                details={"fields": drift},
            )
        )


def _compiled_source_output_path(
    plan: StepPlan,
    output_key: str,
) -> str | None:
    method_id: str | None = None
    output_name = output_key
    if "." in output_key:
        method_id, output_name = output_key.rsplit(".", 1)
    matches = [
        invocation.outputs[output_name]
        for invocation in plan.invocations
        if output_name in invocation.outputs
        and (method_id is None or invocation.method_id == method_id)
    ]
    return matches[0] if len(set(matches)) == 1 else None


def _validate_destination_ledger(
    destinations: Sequence[CompiledStateDestination],
    *,
    writes: Mapping[tuple[str, str], ProjectedStateWrite],
    mismatches: list[StateFinalizationMismatch],
) -> None:
    by_path: dict[str, list[CompiledStateDestination]] = {}
    writes_by_version = _writes_by_version(tuple(writes.values()))
    for destination in destinations:
        prior_items = by_path.setdefault(
            destination.promoted_runtime_path,
            [],
        )
        for prior in prior_items:
            if prior.projected_version_id == destination.projected_version_id:
                continue
            if (
                prior.destination_key.object_id
                != destination.destination_key.object_id
                or prior.destination_key.state_kind
                != destination.destination_key.state_kind
                or prior.destination_key.runtime_type
                != destination.destination_key.runtime_type
            ):
                mismatches.append(
                    StateFinalizationMismatch(
                        "state.runtime_destination_collision",
                        "different logical states write the same runtime path",
                        call_id=destination.step_id,
                        return_name=destination.return_name,
                        details={
                            "previous_call_id": prior.step_id,
                            "runtime_path": destination.promoted_runtime_path,
                        },
                    )
                )
                continue
            if not _version_descends_from(
                destination.projected_version_id,
                prior.projected_version_id,
                writes_by_version=writes_by_version,
            ):
                mismatches.append(
                    StateFinalizationMismatch(
                        "state.runtime_destination_collision",
                        "unrelated StateVersions write the same runtime path",
                        call_id=destination.step_id,
                        return_name=destination.return_name,
                        details={
                            "previous_call_id": prior.step_id,
                            "runtime_path": destination.promoted_runtime_path,
                        },
                    )
                )
        prior_items.append(destination)


def _version_descends_from(
    candidate: StateVersionId,
    ancestor: StateVersionId,
    *,
    writes_by_version: Mapping[
        StateVersionId, Sequence[ProjectedStateWrite]
    ],
) -> bool:
    pending = [candidate]
    visited: set[StateVersionId] = set()
    while pending:
        current = pending.pop()
        if current == ancestor:
            return True
        if current in visited:
            continue
        visited.add(current)
        for write in writes_by_version.get(current, ()):
            if write.previous_version_id is not None:
                pending.append(write.previous_version_id)
    return False


def _compiled_decisions(
    destinations: Sequence[CompiledStateDestination],
    mismatches: Sequence[StateFinalizationMismatch],
) -> tuple[StateFinalizationDecision, ...]:
    invalid_calls = {
        item.call_id for item in mismatches if item.call_id is not None
    }
    grouped: dict[
        tuple[str, str, StateVersionId], list[CompiledStateDestination]
    ] = {}
    for item in destinations:
        grouped.setdefault(
            (item.step_id, item.return_name, item.projected_version_id),
            [],
        ).append(item)
    return tuple(
        StateFinalizationDecision(
            version_id=version_id,
            call_id=step_id,
            return_name=return_name,
            logical_writer_status="valid",
            destination_writer_status=(
                "invalid" if step_id in invalid_calls else "valid"
            ),
            projection_handles=tuple(
                dict.fromkeys(item.semantic_ref for item in items)
            ),
        )
        for (step_id, return_name, version_id), items in grouped.items()
    )


def _writes_overlap(
    left: ProjectedStateWrite,
    right: ProjectedStateWrite,
    *,
    step_scopes: Mapping[str, str],
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    left_scope = step_scopes.get(left.step_id, left.step_id)
    right_scope = step_scopes.get(right.step_id, right.step_id)
    return _write_visible_from(
        left,
        right_scope,
        handle_registry=handle_registry,
    ) or _write_visible_from(
        right,
        left_scope,
        handle_registry=handle_registry,
    )


def _write_visible_from(
    write: ProjectedStateWrite,
    consumer_scope: str,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    # B3 typed storage scope is authoritative. A return may also project to a
    # global object or answer handle, but that destination must not widen the
    # visibility of a sibling-private StateVersion.
    valid_scope = (
        write.selected_version_id.slot_id.storage_scope_id
        if write.selected_version_id is not None
        else handle_registry.handle_valid_scopes.get(write.produced_handle)
    )
    return (
        valid_scope is not None
        and visible_from_valid_scope(
            valid_scope,
            scope_id=consumer_scope,
            registry=handle_registry,
        )
    )


def _projection_kind(handle: str) -> StateProjectionKind:
    if handle.startswith("answer:"):
        return "answer"
    if handle.startswith("fact:"):
        return "fact"
    if ":" in handle:
        return "object"
    return "call_local"


def _first_write(
    writes: Sequence[ProjectedStateWrite],
) -> ProjectedStateWrite | None:
    return writes[0] if writes else None


def _mismatch(
    code: str,
    message: str,
    write: ProjectedStateWrite,
    *,
    details: dict[str, Any] | None = None,
) -> StateFinalizationMismatch:
    return StateFinalizationMismatch(
        code,
        message,
        call_id=write.step_id,
        return_name=write.return_name,
        details=details,
    )


__all__ = [
    "CompiledStateDestination",
    "FinalizedStateWrite",
    "StateFinalizationDecision",
    "StateFinalizationMismatch",
    "StateFinalizationResult",
    "StateFinalizationService",
    "StateFinalizerMode",
    "StateProjectionDestination",
    "expand_functional_dependency_graph",
    "project_functional_state_dependencies",
    "project_functional_state_writes",
]
