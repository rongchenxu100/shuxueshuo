"""Typed allocation wiring shared by Functional reconciliation stages."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalCapabilityReturn,
    FunctionalCallReconciliation,
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    ArgVersionBinding,
    ComputationKey,
    IdentityShadowComparison,
    StateAllocationAction,
    StateIdentityFactory,
    StateIdentityIndex,
    StateVersionId,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class LiveStateVersionRebase:
    """One transition rewired after liveness removed a provisional writer."""

    call_id: str
    return_name: str
    removed_previous_version_id: StateVersionId
    selected_previous_version_id: StateVersionId
    selected_previous_call_id: str


def project_sibling_symbol_dependencies(
    return_specs: tuple[FunctionalCapabilityReturn, ...],
    allocations: tuple[FunctionalReturnAllocation, ...],
    *,
    capability_id: str,
) -> tuple[FunctionalReturnAllocation, ...]:
    """Attach declared sibling Symbol outputs to the states that contain them."""

    specs_by_name = {item.name: item for item in return_specs}
    allocations_by_name = {item.return_name: item for item in allocations}
    result: list[FunctionalReturnAllocation] = []
    for allocation in allocations:
        spec = specs_by_name[allocation.return_name]
        sources: list[FunctionalReturnAllocation] = []
        for source_name in spec.free_symbol_return_names:
            source = allocations_by_name.get(source_name)
            if (
                source is None
                or source.runtime_type != "Symbol"
                or source.object_ref is None
            ):
                raise ValueError(
                    "planner_configuration_error: declared free-Symbol "
                    "sibling return is unavailable: "
                    f"{capability_id}.{allocation.return_name} "
                    f"<- {source_name}"
                )
            sources.append(source)
        if not sources:
            result.append(allocation)
            continue
        result.append(
            replace(
                allocation,
                dependency_object_refs=unique_ordered(
                    (
                        *allocation.dependency_object_refs,
                        *(source.object_ref for source in sources),
                    )
                ),
                free_symbol_refs=unique_ordered(
                    (
                        *allocation.free_symbol_refs,
                        *(source.object_ref for source in sources),
                    )
                ),
                source_state_slot_ids=unique_ordered(
                    (
                        *allocation.source_state_slot_ids,
                        *(source.state_slot_id for source in sources),
                    )
                ),
                source_version_ids=unique_ordered(
                    (
                        *allocation.source_version_ids,
                        *(
                            source.selected_version_id
                            for source in sources
                            if source.selected_version_id is not None
                        ),
                    )
                ),
            )
        )
    return tuple(result)


def rebase_live_state_versions(
    calls: tuple[FunctionalCallReconciliation, ...],
) -> tuple[
    tuple[FunctionalCallReconciliation, ...],
    tuple[LiveStateVersionRebase, ...],
]:
    """Reconnect live transitions to the nearest surviving state version.

    Typed allocation runs before goal-directed liveness. A provisional
    same-object writer may therefore receive an ordinal and later be pruned.
    Surviving transitions must not retain that removed version as their
    predecessor.
    """

    live_allocations = tuple(
        allocation
        for call in calls
        for allocation in call.returns
        if allocation.selected_version_id is not None
    )
    live_by_version = {
        allocation.selected_version_id: allocation
        for allocation in live_allocations
        if allocation.selected_version_id is not None
    }
    order_by_call = {
        call.call_id: index for index, call in enumerate(calls)
    }
    rebases: list[LiveStateVersionRebase] = []
    updated_calls: list[FunctionalCallReconciliation] = []
    for call in calls:
        updated_returns: list[FunctionalReturnAllocation] = []
        for allocation in call.returns:
            previous_id = allocation.previous_version_id
            selected_id = allocation.selected_version_id
            if (
                allocation.write_mode != "transition"
                or previous_id is None
                or selected_id is None
                or previous_id in live_by_version
            ):
                updated_returns.append(allocation)
                continue
            candidates = [
                item
                for item in live_allocations
                if item.selected_version_id is not None
                and item.typed_slot_id == allocation.typed_slot_id
                and item.selected_version_id.ordinal < selected_id.ordinal
                and order_by_call.get(item.call_id, -1)
                < order_by_call[call.call_id]
            ]
            if not candidates:
                updated_returns.append(allocation)
                continue
            previous = max(
                candidates,
                key=lambda item: item.selected_version_id.ordinal,  # type: ignore[union-attr]
            )
            replacement_id = previous.selected_version_id
            assert replacement_id is not None
            source_version_ids = unique_ordered(
                replacement_id if item == previous_id else item
                for item in allocation.source_version_ids
            )
            computation_key = allocation.computation_key
            if computation_key is not None:
                computation_key = replace(
                    computation_key,
                    arg_bindings=tuple(
                        replace(binding, version_id=replacement_id)
                        if binding.version_id == previous_id
                        else binding
                        for binding in computation_key.arg_bindings
                    ),
                )
            updated_returns.append(
                replace(
                    allocation,
                    previous_version_id=replacement_id,
                    previous_write_step_id=previous.call_id,
                    source_version_ids=source_version_ids,
                    computation_key=computation_key,
                )
            )
            rebases.append(
                LiveStateVersionRebase(
                    call_id=call.call_id,
                    return_name=allocation.return_name,
                    removed_previous_version_id=previous_id,
                    selected_previous_version_id=replacement_id,
                    selected_previous_call_id=previous.call_id,
                )
            )
        updated_calls.append(
            replace(call, returns=tuple(updated_returns))
        )
    return tuple(updated_calls), tuple(rebases)


def functional_computation_key(
    call: FunctionalCall,
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    scope_id: str,
    identity_factory: StateIdentityFactory,
    identity_index: StateIdentityIndex,
) -> ComputationKey:
    del scope_id, identity_index
    bindings: list[ArgVersionBinding] = []
    for arg_name in sorted(resolved_args):
        for item_index, value in enumerate(resolved_args[arg_name]):
            version_id = value.state_version_id
            object_id = value.math_object_id or identity_factory.object_id(
                value.object_ref
            )
            bindings.append(
                ArgVersionBinding(
                    arg_name=arg_name,
                    item_index=item_index,
                    version_id=version_id,
                    condition_id=value.condition_id,
                    object_id=object_id if version_id is None else None,
                    call_result_id=(
                        f"{value.source_call_id}.{value.return_name}"
                        if version_id is None
                        and value.source_call_id is not None
                        and value.return_name is not None
                        else None
                    ),
                )
            )
    return ComputationKey(call.capability_id, tuple(bindings))


def functional_source_version_ids(
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    scope_id: str,
    identity_index: StateIdentityIndex,
) -> tuple[StateVersionId, ...]:
    del scope_id, identity_index
    versions: list[StateVersionId] = []
    for values in resolved_args.values():
        for value in values:
            if value.state_version_id is not None:
                versions.append(value.state_version_id)
                continue
            if (
                value.source_call_id is not None
                and value.return_name is not None
            ):
                # A public call-local return is a direct CallResult input. Its
                # source versions remain provenance of the producer and must
                # not become direct state reads of every downstream call.
                # Structured object roles are different: a locus whose subject
                # is Point G is also direct identity evidence for a transition
                # that writes G. Keep only role versions whose typed object
                # matches the role, never the role's transitive ancestors.
                role_object_ids = {
                    object_id
                    for binding in value.lineage.object_roles
                    for object_id in binding.object_ids
                }
                versions.extend(
                    version_id
                    for binding in value.lineage.object_roles
                    for version_id in binding.source_version_ids
                    if (
                        version_id.slot_id.logical_key.object_id
                        in role_object_ids
                    )
                )
                continue
            versions.extend(value.source_version_ids)
    return unique_ordered(versions)


def identity_shadow_comparison(
    *,
    call_id: str,
    return_name: str,
    legacy_object_ref: str | None,
    legacy_slot_id: str | None,
    legacy_write_mode: str,
    typed_object_ref: str | None,
    typed_slot_id: str | None,
    typed_action: StateAllocationAction,
) -> IdentityShadowComparison:
    details: list[str] = []
    if legacy_object_ref != typed_object_ref:
        details.append(
            "object identity differs: "
            f"legacy={legacy_object_ref}, typed={typed_object_ref}"
        )
    if legacy_slot_id != typed_slot_id:
        details.append(
            "slot projection differs: "
            f"legacy={legacy_slot_id}, typed={typed_slot_id}"
        )
    compatible_actions = {
        "create": {"create", "isolated", "reuse", "transition"},
        "transition": {
            "call_local_value",
            "create",
            "transition",
            "reuse",
        },
        "value": {
            "call_local_value",
            "create",
            "isolated",
            "transition",
            "reuse",
        },
    }
    if typed_action not in compatible_actions.get(
        legacy_write_mode,
        {typed_action},
    ):
        details.append(
            "write classification differs: "
            f"legacy={legacy_write_mode}, typed={typed_action}"
        )
    return IdentityShadowComparison(
        call_id=call_id,
        return_name=return_name,
        legacy_object_ref=legacy_object_ref,
        typed_object_ref=typed_object_ref,
        legacy_slot_id=legacy_slot_id,
        typed_slot_id=typed_slot_id,
        legacy_write_mode=legacy_write_mode,
        typed_action=typed_action,
        matches=not details,
        details=tuple(details),
    )
