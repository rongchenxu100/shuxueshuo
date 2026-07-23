"""Deterministic closure expectations and same-object state refinements."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Mapping, Sequence

from shuxueshuo_server.solver.contracts import FunctionalResultForm
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalCallReconciliation,
    FunctionalPlan,
    FunctionalPlanIssue,
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
)


@dataclass(frozen=True)
class FunctionalStateRefinementResult:
    plan: FunctionalPlan
    calls: tuple[FunctionalCallReconciliation, ...]
    repairs: tuple[FunctionalDeterministicRepair, ...]
    issues: tuple[FunctionalPlanIssue, ...] = ()


def refine_functional_object_states(
    plan: FunctionalPlan,
    *,
    reconciled: Sequence[FunctionalCallReconciliation],
    catalog: FunctionalCapabilityCatalog,
) -> FunctionalStateRefinementResult:
    """Infer object closure forms and monotone writes to the same StateSlot.

    An LLM expectation remains optional. The authoritative pre-runtime proof is
    the exact Symbol and source-state lineage projected by reconciliation.
    Runtime provenance validates the inferred transition again after SymPy has
    produced the concrete value.
    """

    calls_by_id = {call.call_id: call for call in plan.calls}
    reconciled_by_id = {item.call_id: item for item in reconciled}
    previous_by_slot: dict[str, FunctionalReturnAllocation] = {}
    writes_by_call_slot: dict[
        tuple[str, str],
        FunctionalReturnAllocation,
    ] = {}
    updated_calls: dict[str, FunctionalCallReconciliation] = {}
    updated_plan_calls: dict[str, FunctionalCall] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []

    for call in plan.calls:
        item = reconciled_by_id.get(call.call_id)
        capability = catalog.items.get(call.capability_id)
        if item is None or capability is None:
            continue
        return_specs = {result.name: result for result in capability.returns}
        expectations = dict(call.return_expectations)
        allocations: list[FunctionalReturnAllocation] = []
        for allocation in item.returns:
            return_spec = return_specs.get(allocation.return_name)
            if return_spec is not None and {
                "open_state",
                "closed_state",
            } <= set(return_spec.possible_forms):
                inferred_form = _inferred_object_form(
                    allocation,
                    resolved_args=item.resolved_args,
                )
                if (
                    inferred_form is not None
                    and allocation.return_name not in expectations
                ):
                    expectations[allocation.return_name] = inferred_form
                    repairs.append(
                        FunctionalDeterministicRepair(
                            call.call_id,
                            "infer_object_result_form",
                            f"<missing:{allocation.return_name}>",
                            inferred_form,
                        )
                    )

            source_call_ids = {
                value.source_call_id
                for values in item.resolved_args.values()
                for value in values
                if value.source_call_id is not None
                and value.state_slot_id == allocation.state_slot_id
                and value.object_ref == allocation.object_ref
            }
            source_previous = (
                writes_by_call_slot.get(
                    (next(iter(source_call_ids)), allocation.state_slot_id)
                )
                if len(source_call_ids) == 1
                else None
            )
            latest_previous = previous_by_slot.get(allocation.state_slot_id)
            if (
                allocation.write_mode == "transition"
                and source_previous is not None
                and latest_previous is not None
                and source_previous.call_id != latest_previous.call_id
            ):
                issues.append(
                    FunctionalPlanIssue(
                        layer="functional_reconciliation",
                        code="functional.stale_state_transition",
                        message=(
                            f"call {call.call_id} updates an older version of "
                            f"{allocation.object_ref or allocation.state_slot_id}"
                        ),
                        call_id=call.call_id,
                        scope_id=item.scope_id,
                        details={
                            "state_slot_id": allocation.state_slot_id,
                            "source_call_id": source_previous.call_id,
                            "latest_call_id": latest_previous.call_id,
                            "repair_call_ids": [call.call_id],
                        },
                    )
                )
            previous = source_previous or (
                latest_previous if not source_call_ids else None
            )
            transition_kind = _state_transition_kind(previous, allocation)
            if transition_kind is not None:
                assert previous is not None
                previous_mode = allocation.write_mode
                allocation = replace(
                    allocation,
                    write_mode="transition",
                    transition_kind=transition_kind,
                    previous_write_step_id=previous.call_id,
                )
                repairs.append(
                    FunctionalDeterministicRepair(
                        call.call_id,
                        (
                            "promote_state_write_to_dependency_refinement"
                            if transition_kind == "dependency_refinement"
                            else "promote_state_write_to_direct_transition"
                        ),
                        previous_mode,
                        f"transition:{previous.call_id}",
                    )
                )
            allocations.append(allocation)
            previous_by_slot[allocation.state_slot_id] = allocation
            writes_by_call_slot[(call.call_id, allocation.state_slot_id)] = allocation

        if expectations != call.return_expectations:
            updated_plan_calls[call.call_id] = replace(
                call,
                return_expectations=expectations,
            )
        if tuple(allocations) != item.returns:
            updated_calls[item.call_id] = replace(
                item,
                returns=tuple(allocations),
            )

    return FunctionalStateRefinementResult(
        plan=_replace_plan_calls(plan, updated_plan_calls),
        calls=tuple(updated_calls.get(item.call_id, item) for item in reconciled),
        repairs=tuple(repairs),
        issues=tuple(issues),
    )


def _inferred_object_form(
    allocation: FunctionalReturnAllocation,
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> FunctionalResultForm | None:
    """Infer only closure forms proven by reconciliation metadata.

    Runtime methods and upstream object states can carry hidden companion
    Symbols that are absent from input-derived ``free_symbol_refs``. Therefore
    an empty projected set alone is not proof of closure. Reconciliation only
    infers ``closed_state`` when every structurally visible source Symbol is
    covered by an input ParameterValue with the same object identity; runtime
    provenance still validates the concrete result.
    """
    if allocation.free_symbol_refs:
        return "open_state"
    source_symbol_refs = {
        symbol_ref
        for values in resolved_args.values()
        for value in values
        if value.runtime_type != "ParameterValue"
        for symbol_ref in value.free_symbol_refs
    }
    closed_symbol_refs = {
        object_ref
        for values in resolved_args.values()
        for value in values
        if value.runtime_type == "ParameterValue"
        and (object_ref := value.object_ref) is not None
    }
    if source_symbol_refs and source_symbol_refs <= closed_symbol_refs:
        return "closed_state"
    return None


def _state_transition_kind(
    previous: FunctionalReturnAllocation | None,
    current: FunctionalReturnAllocation,
) -> Literal["direct", "dependency_refinement"] | None:
    if previous is None or current.write_mode not in {
        "create",
        "transition",
        "value",
    }:
        return None
    if current.object_ref is None or current.object_ref != previous.object_ref:
        return None
    if current.runtime_type != previous.runtime_type:
        return None
    if current.identity_policy not in {"target_object", "preserve_input_object"}:
        return None
    current_sources = set(current.source_state_slot_ids)
    if previous.state_slot_id not in current_sources:
        return None
    previous_dependencies = set(previous.dependency_object_refs)
    current_dependencies = set(current.dependency_object_refs)
    if not previous_dependencies <= current_dependencies:
        return None
    previous_symbols = set(previous.free_symbol_refs)
    current_symbols = set(current.free_symbol_refs)
    if current_symbols < previous_symbols:
        return "dependency_refinement"
    return "direct"


def _replace_plan_calls(
    plan: FunctionalPlan,
    replacements: Mapping[str, FunctionalCall],
) -> FunctionalPlan:
    if not replacements:
        return plan
    return replace(
        plan,
        scopes=tuple(
            replace(
                scope,
                calls=tuple(replacements.get(call.call_id, call) for call in scope.calls),
            )
            for scope in plan.scopes
        ),
    )


__all__ = [
    "FunctionalStateRefinementResult",
    "refine_functional_object_states",
]
