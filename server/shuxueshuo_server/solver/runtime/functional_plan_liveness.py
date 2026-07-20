"""Conservative dead-call elimination for reconciled FunctionalPlan graphs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalCallReconciliation,
    FunctionalCallReport,
    FunctionalPlan,
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
    ) -> FunctionalCallLivenessResult:
        reconciled_by_id = {item.call_id: item for item in reconciled}
        statuses = {item.call_id: item.status for item in call_reports}
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

        reachable = _dependency_closure(roots, dependency_graph)
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
) -> bool:
    if call.return_bindings:
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
