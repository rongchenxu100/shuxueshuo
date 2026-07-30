"""Conservative dead-call elimination for reconciled FunctionalPlan graphs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
    FunctionalSemanticView,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalCallReconciliation,
    FunctionalCallReport,
    FunctionalPlan,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    normalize_runtime_type,
)
from shuxueshuo_server.solver.state_semantics import (
    state_kind_for_runtime_type,
)


@dataclass(frozen=True)
class FunctionalCallLivenessResult:
    plan: FunctionalPlan
    calls: tuple[FunctionalCallReconciliation, ...]
    call_reports: tuple[FunctionalCallReport, ...]
    dependency_graph: dict[str, tuple[str, ...]]
    repairs: tuple[FunctionalDeterministicRepair, ...] = ()
    dropped_call_ids: tuple[str, ...] = ()


class FunctionalCallLivenessAnalyzer:
    """Remove only unobservable, side-effect-free FunctionSpec calls.

    The dependency graph includes both explicit CallResultRef edges and
    implicit object-state reads. Invalid/blocked pure calls are removable when
    their entire subgraph is unobservable; this prevents an unused speculative
    branch from blocking an otherwise complete plan.
    """

    def analyze(
        self,
        plan: FunctionalPlan,
        *,
        reconciled: Sequence[FunctionalCallReconciliation],
        call_reports: Sequence[FunctionalCallReport],
        dependency_graph: Mapping[str, tuple[str, ...]],
        catalog: FunctionalCapabilityCatalog,
        protected_call_ids: Sequence[str] = (),
        drop_invalid_calls: bool = True,
        existing_state_views: Sequence[FunctionalSemanticView] = (),
        handle_registry: object | None = None,
    ) -> FunctionalCallLivenessResult:
        reconciled_by_id = {item.call_id: item for item in reconciled}
        statuses = {item.call_id: item.status for item in call_reports}
        redundant_object_binding_calls = _redundant_object_binding_calls(
            plan,
            reconciled_by_id=reconciled_by_id,
            existing_state_views=existing_state_views,
            handle_registry=handle_registry,
        )
        candidates = {
            call.call_id
            for call in plan.calls
            if (
                drop_invalid_calls
                or statuses.get(call.call_id) == "valid"
            )
            if _is_dead_call_candidate(
                call,
                reconciliation=reconciled_by_id.get(call.call_id),
                catalog=catalog,
                redundant_object_binding=(
                    call.call_id in redundant_object_binding_calls
                ),
            )
        }
        if not candidates:
            return _unchanged_result(
                plan,
                reconciled=reconciled,
                call_reports=call_reports,
                dependency_graph=dependency_graph,
            )

        all_call_ids = {call.call_id for call in plan.calls}
        roots = (all_call_ids - candidates) | set(protected_call_ids)
        # With no observable root, liveness is unknown. Preserve the candidate
        # rather than deleting a standalone partial plan speculatively.
        if not roots:
            return _unchanged_result(
                plan,
                reconciled=reconciled,
                call_reports=call_reports,
                dependency_graph=dependency_graph,
            )

        liveness_graph = _dependency_graph_without_unproven_predecessors(
            reconciled=reconciled,
            dependency_graph=dependency_graph,
        )
        reachable = _dependency_closure(roots, liveness_graph)
        dropped = candidates - reachable
        if not dropped:
            return _unchanged_result(
                plan,
                reconciled=reconciled,
                call_reports=call_reports,
                dependency_graph=dependency_graph,
            )

        kept = all_call_ids - dropped
        ordered_kept = tuple(
            call.call_id for call in plan.calls if call.call_id in kept
        )
        calls_by_id = {call.call_id: call for call in plan.calls}
        scopes = []
        for scope in plan.scopes:
            scope_calls = tuple(
                call for call in scope.calls if call.call_id in kept
            )
            if scope_calls:
                scopes.append(replace(scope, calls=scope_calls))
        pruned_plan = replace(plan, scopes=tuple(scopes))
        ordered_dropped = tuple(
            call.call_id for call in plan.calls if call.call_id in dropped
        )
        repairs = tuple(
            FunctionalDeterministicRepair(
                call_id,
                (
                    "drop_dead_pure_function_call"
                    if statuses.get(call_id) == "valid"
                    else "drop_dead_invalid_call"
                ),
                calls_by_id[call_id].capability_id,
                "unconsumed_state_writes",
            )
            for call_id in ordered_dropped
        )
        return FunctionalCallLivenessResult(
            plan=pruned_plan,
            calls=tuple(
                item for item in reconciled if item.call_id in kept
            ),
            call_reports=tuple(
                item for item in call_reports if item.call_id in kept
            ),
            dependency_graph={
                call_id: tuple(
                    dependency
                    for dependency in dependency_graph.get(call_id, ())
                    if dependency in kept
                )
                for call_id in ordered_kept
            },
            repairs=repairs,
            dropped_call_ids=ordered_dropped,
        )


def _is_dead_call_candidate(
    call: FunctionalCall,
    *,
    reconciliation: FunctionalCallReconciliation | None,
    catalog: FunctionalCapabilityCatalog,
    redundant_object_binding: bool,
) -> bool:
    if call.return_bindings and not redundant_object_binding:
        return False
    capability = catalog.get(call.capability_id)
    if (
        capability is None
        or capability.kind != "function"
        or not capability.is_pure
    ):
        return False
    if reconciliation is not None and any(
        item.handle.startswith("answer:") for item in reconciliation.returns
    ):
        return False
    return not any(item.runtime_type == "Condition" for item in capability.returns)


def _redundant_object_binding_calls(
    plan: FunctionalPlan,
    *,
    reconciled_by_id: Mapping[str, FunctionalCallReconciliation],
    existing_state_views: Sequence[FunctionalSemanticView],
    handle_registry: object | None,
) -> set[str]:
    """Find unconsumed creates whose logical object state already exists."""
    visible_states = [
        (
            _logical_state_key(
                object_ref=item.object_ref,
                runtime_type=item.runtime_type,
            ),
            item.valid_scope,
        )
        for item in existing_state_views
        if item.state_slot_id is not None and item.object_ref is not None
    ]
    scope_by_call = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    redundant: set[str] = set()
    for call in plan.calls:
        item = reconciled_by_id.get(call.call_id)
        object_writes = (
            tuple(
                result
                for result in item.returns
                if (
                    result.state_slot_id
                    and result.object_ref is not None
                    and result.write_mode == "create"
                )
            )
            if item is not None
            else ()
        )
        call_scope = scope_by_call.get(call.call_id, "")
        if (
            object_writes
            and call.return_bindings
            and all(
                binding.kind != "answer"
                for binding in call.return_bindings.values()
            )
            and all(
                any(
                    previous_key
                    == _logical_state_key(
                        object_ref=result.object_ref,
                        runtime_type=result.runtime_type,
                    )
                    and _state_visible_from_scope(
                        previous_scope,
                        call_scope=call_scope,
                        handle_registry=handle_registry,
                    )
                    for previous_key, previous_scope in visible_states
                )
                for result in object_writes
            )
        ):
            redundant.add(call.call_id)
        visible_states.extend(
            (
                _logical_state_key(
                    object_ref=result.object_ref,
                    runtime_type=result.runtime_type,
                ),
                result.valid_scope,
            )
            for result in object_writes
        )
    return redundant


def _logical_state_key(
    *,
    object_ref: str | None,
    runtime_type: str,
) -> tuple[str, str, str]:
    normalized_type = normalize_runtime_type(runtime_type)
    return (
        object_ref or "",
        state_kind_for_runtime_type(normalized_type),
        normalized_type,
    )


def _state_visible_from_scope(
    valid_scope: str,
    *,
    call_scope: str,
    handle_registry: object | None,
) -> bool:
    if handle_registry is None:
        return valid_scope == call_scope
    return visible_from_valid_scope(
        valid_scope,
        scope_id=call_scope,
        registry=handle_registry,
    )


def _dependency_closure(
    roots: set[str],
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> set[str]:
    reachable: set[str] = set()
    pending = list(roots)
    while pending:
        call_id = pending.pop()
        if call_id in reachable:
            continue
        reachable.add(call_id)
        pending.extend(dependency_graph.get(call_id, ()))
    return reachable


def _dependency_graph_without_unproven_predecessors(
    *,
    reconciled: Sequence[FunctionalCallReconciliation],
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Ignore provisional predecessor edges that do not prove a transition.

    Typed allocation runs before liveness, so two same-object writes may
    temporarily form a version sequence. That sequence alone must not keep an
    otherwise unused writer alive. A predecessor remains a liveness dependency
    when the consumer explicitly reads its call result or version.
    """

    producer_by_version = {
        allocation.selected_version_id: call.call_id
        for call in reconciled
        for allocation in call.returns
        if allocation.selected_version_id is not None
    }
    direct_source_calls = {
        call.call_id: {
            value.source_call_id
            for values in call.resolved_args.values()
            for value in values
            if value.source_call_id is not None
        }
        for call in reconciled
    }
    removable: set[tuple[str, str]] = set()
    for call in reconciled:
        for allocation in call.returns:
            previous = allocation.previous_version_id
            if previous is None or previous in allocation.source_version_ids:
                continue
            producer = producer_by_version.get(previous)
            if (
                producer is None
                or producer in direct_source_calls.get(call.call_id, set())
            ):
                continue
            removable.add((call.call_id, producer))
    return {
        call_id: tuple(
            dependency
            for dependency in dependencies
            if (call_id, dependency) not in removable
        )
        for call_id, dependencies in dependency_graph.items()
    }


def _unchanged_result(
    plan: FunctionalPlan,
    *,
    reconciled: Sequence[FunctionalCallReconciliation],
    call_reports: Sequence[FunctionalCallReport],
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> FunctionalCallLivenessResult:
    return FunctionalCallLivenessResult(
        plan=plan,
        calls=tuple(reconciled),
        call_reports=tuple(call_reports),
        dependency_graph=dict(dependency_graph),
    )


__all__ = [
    "FunctionalCallLivenessAnalyzer",
    "FunctionalCallLivenessResult",
]
