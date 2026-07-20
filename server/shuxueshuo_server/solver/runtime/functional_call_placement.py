"""Deterministic execution placement and state sharing for FunctionalPlan."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_graph import (
    canonical_call_aliases as _canonical_aliases,
    canonical_call_id as _canonical,
    least_common_scope as _least_common_scope,
    rewrite_call_aliases as _rewrite_call_aliases,
    wire_inputs_are_stable as _wire_inputs_are_stable,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    CanonicalStateHandleFactory,
    FunctionalCapability,
    FunctionalCall,
    FunctionalCallPlacement,
    FunctionalCallReconciliation,
    FunctionalCallReport,
    FunctionalPlan,
    FunctionalPlanIssue,
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
    _issue,
)
from shuxueshuo_server.solver.runtime.functional_symbol_flow import (
    return_free_symbol_refs,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.semantic_reads import (
    SemanticReadCatalogItem,
)
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef


@dataclass(frozen=True)
class FunctionalCallPlacementResult:
    plan: FunctionalPlan
    calls: tuple[FunctionalCallReconciliation, ...]
    call_reports: tuple[FunctionalCallReport, ...]
    dependency_graph: dict[str, tuple[str, ...]]
    placements: tuple[FunctionalCallPlacement, ...]
    aliases: dict[str, str]
    repairs: tuple[FunctionalDeterministicRepair, ...]
    issues: tuple[FunctionalPlanIssue, ...] = ()


class FunctionalCallPlacementService:
    """Canonicalize equivalent calls before StepIntent projection.

    Reconciliation may use temporary scope-local allocations while resolving a
    forward-only call graph. This pass is the sole owner of the final execution
    scope, return publication scope, canonical call aliases, handles and slots.
    """

    def preliminary_execution_scopes(
        self,
        plan: FunctionalPlan,
        *,
        source_plan: FunctionalPlan,
        catalog: FunctionalCapabilityCatalog,
        semantic_index: FunctionalSemanticIndex,
        handle_registry: CanonicalHandleRegistry,
        default_scopes: Mapping[str, str],
        initial_aliases: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Hoist only calls whose wire inputs are immutable and identical.

        Role/auto args are resolved after this pass. Resolving them at the
        shared ancestor prevents a child-specific latest-state view from
        accidentally specializing an otherwise common parent computation.
        Mutable object refs are deliberately excluded from this early proof.
        """
        aliases = _canonical_aliases(dict(initial_aliases or {}))
        source_scopes = {
            call.call_id: scope.scope_id
            for scope in source_plan.scopes
            for call in scope.calls
        }
        initial_groups = _alias_groups(
            tuple(source_scopes),
            aliases=aliases,
            canonical_call_ids=tuple(call.call_id for call in plan.calls),
        )
        grouped: dict[tuple[Any, ...], list[FunctionalCall]] = {}
        for call in plan.calls:
            capability = catalog.get(call.capability_id)
            if (
                capability is None
                or not _is_shareable(call, capability)
                or not _wire_inputs_are_stable(call, capability)
            ):
                continue
            grouped.setdefault(_wire_call_signature(call), []).append(call)
        result = dict(default_scopes)
        for calls in grouped.values():
            member_ids = tuple(
                dict.fromkeys(
                    member
                    for call in calls
                    for member in initial_groups.get(call.call_id, (call.call_id,))
                )
            )
            if len(member_ids) < 2:
                continue
            proposed = _least_common_scope(
                tuple(source_scopes[call_id] for call_id in member_ids),
                handle_registry,
            )
            if not all(
                _wire_inputs_visible_at_scope(
                    call,
                    proposed,
                    capability=catalog.items[call.capability_id],
                    semantic_index=semantic_index,
                )
                for call in calls
            ):
                continue
            for call in calls:
                result[call.call_id] = proposed
        for canonical, members in initial_groups.items():
            if len(members) < 2 or canonical not in result:
                continue
            proposed = _least_common_scope(
                tuple(source_scopes[call_id] for call_id in members),
                handle_registry,
            )
            call = next(item for item in plan.calls if item.call_id == canonical)
            capability = catalog.items[call.capability_id]
            if _wire_inputs_visible_at_scope(
                call,
                proposed,
                capability=capability,
                semantic_index=semantic_index,
            ):
                result[canonical] = proposed
        return result

    def place(
        self,
        plan: FunctionalPlan,
        *,
        source_plan: FunctionalPlan,
        reconciled: Sequence[FunctionalCallReconciliation],
        call_reports: Sequence[FunctionalCallReport],
        catalog: FunctionalCapabilityCatalog,
        handle_registry: CanonicalHandleRegistry,
        semantic_items: Sequence[SemanticReadCatalogItem],
        question_goals: Sequence[QuestionGoal],
        initial_aliases: Mapping[str, str] | None = None,
    ) -> FunctionalCallPlacementResult:
        source_calls = {call.call_id: call for call in source_plan.calls}
        source_scopes = {
            call.call_id: scope.scope_id
            for scope in source_plan.scopes
            for call in scope.calls
        }
        call_by_id = {call.call_id: call for call in plan.calls}
        reconciled_by_id = {item.call_id: item for item in reconciled}
        aliases = _canonical_aliases(dict(initial_aliases or {}))
        groups = _alias_groups(
            tuple(source_calls),
            aliases=aliases,
            canonical_call_ids=tuple(call_by_id),
        )
        signatures: dict[tuple[Any, ...], str] = {}
        repairs: list[FunctionalDeterministicRepair] = []
        issues: list[FunctionalPlanIssue] = []
        transferred_return_expectations: dict[str, dict[str, str]] = {}

        for call in plan.calls:
            item = reconciled_by_id.get(call.call_id)
            capability = catalog.get(call.capability_id)
            if item is None or capability is None or not _is_shareable(call, capability):
                continue
            signature = _resolved_call_signature(call, item, aliases=aliases)
            previous_id = signatures.get(signature)
            if previous_id is None:
                signatures[signature] = call.call_id
                continue
            previous = reconciled_by_id.get(previous_id)
            previous_call = call_by_id.get(previous_id)
            if previous is None or previous_call is None:
                signatures[signature] = call.call_id
                continue
            candidate_scopes = (
                *groups.get(previous_id, (previous_id,)),
                *groups.get(call.call_id, (call.call_id,)),
            )
            lca = _least_common_scope(
                tuple(source_scopes[item_id] for item_id in candidate_scopes),
                handle_registry,
            )
            if not _inputs_shareable_at_scope(
                (*previous.resolved_args.values(), *item.resolved_args.values()),
                lca,
                aliases=aliases,
                groups=groups,
                source_scopes=source_scopes,
                registry=handle_registry,
            ):
                continue
            expectation_owner = replace(
                previous_call,
                return_expectations=transferred_return_expectations.get(
                    previous_id,
                    previous_call.return_expectations,
                ),
            )
            merged_expectations = _merged_return_expectations(
                expectation_owner,
                call,
            )
            if merged_expectations is None:
                issues.append(
                    _return_expectation_conflict_issue(
                        expectation_owner,
                        call,
                    )
                )
            else:
                transferred_return_expectations[previous_id] = merged_expectations
            aliases[call.call_id] = previous_id
            aliases = _canonical_aliases(aliases)
            groups.setdefault(previous_id, (previous_id,))
            groups[previous_id] = tuple(
                dict.fromkeys((*groups[previous_id], *groups.pop(call.call_id, (call.call_id,))))
            )
            repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    (
                        "isolate_conflicting_equivalent_call"
                        if merged_expectations is None
                        else "merge_resolved_equivalent_call"
                    ),
                    call.call_id,
                    previous_id,
                )
            )

        # An answer-bound call may also materialize the state of its target
        # object. If a later pure call repeats the same computation only to
        # bind that already-materialized object or answer, keep the first
        # producer, transfer the answer destination to it and rewrite downstream
        # call-result edges. Transitions and conflicting answer destinations are
        # deliberately excluded.
        state_producers: dict[tuple[Any, ...], str] = {}
        transferred_return_bindings: dict[str, dict[str, SemanticRef]] = {}
        for call in plan.calls:
            if call.call_id in aliases:
                continue
            item = reconciled_by_id.get(call.call_id)
            capability = catalog.get(call.capability_id)
            if (
                item is None
                or capability is None
                or not _can_produce_reusable_object_state(call, item, capability)
            ):
                continue
            signature = _resolved_object_state_signature(
                call,
                item,
                aliases=aliases,
            )
            previous_id = state_producers.get(signature)
            if previous_id is None:
                state_producers[signature] = call.call_id
                continue
            answer_bindings = _answer_return_bindings(call)
            if answer_bindings:
                previous_call = call_by_id.get(previous_id)
                previous = reconciled_by_id.get(previous_id)
                if (
                    previous_call is None
                    or previous is None
                    or not _can_transfer_answer_bindings(
                        previous_call,
                        call,
                        answer_bindings=answer_bindings,
                        transferred=transferred_return_bindings.get(previous_id, {}),
                    )
                ):
                    state_producers[signature] = call.call_id
                    continue
            elif not _is_redundant_existing_object_call(call):
                continue
            previous = reconciled_by_id.get(previous_id)
            if previous is None:
                state_producers[signature] = call.call_id
                continue
            candidate_scopes = (
                *groups.get(previous_id, (previous_id,)),
                *groups.get(call.call_id, (call.call_id,)),
            )
            lca = _least_common_scope(
                tuple(source_scopes[item_id] for item_id in candidate_scopes),
                handle_registry,
            )
            if not _inputs_shareable_at_scope(
                (*previous.resolved_args.values(), *item.resolved_args.values()),
                lca,
                aliases=aliases,
                groups=groups,
                source_scopes=source_scopes,
                registry=handle_registry,
            ):
                continue
            previous_call = call_by_id.get(previous_id)
            if previous_call is None:
                state_producers[signature] = call.call_id
                continue
            expectation_owner = replace(
                previous_call,
                return_expectations=transferred_return_expectations.get(
                    previous_id,
                    previous_call.return_expectations,
                ),
            )
            merged_expectations = _merged_return_expectations(
                expectation_owner,
                call,
            )
            if merged_expectations is None:
                issues.append(
                    _return_expectation_conflict_issue(
                        expectation_owner,
                        call,
                    )
                )
                answer_bindings = {}
            elif answer_bindings:
                transferred_return_bindings.setdefault(previous_id, {}).update(
                    answer_bindings
                )
                reconciled_by_id[previous_id] = _transfer_answer_allocations(
                    previous,
                    item,
                    answer_bindings=answer_bindings,
                )
            if merged_expectations is not None:
                transferred_return_expectations[previous_id] = merged_expectations
            aliases[call.call_id] = previous_id
            aliases = _canonical_aliases(aliases)
            groups.setdefault(previous_id, (previous_id,))
            groups[previous_id] = tuple(
                dict.fromkeys(
                    (
                        *groups[previous_id],
                        *groups.pop(call.call_id, (call.call_id,)),
                    )
                )
            )
            repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    (
                        "isolate_conflicting_equivalent_call"
                        if merged_expectations is None
                        else (
                            "reuse_existing_state_for_answer"
                            if answer_bindings
                            else "merge_redundant_existing_state_call"
                        )
                    ),
                    call.call_id,
                    previous_id,
                )
            )

        aliases = _canonical_aliases(aliases)
        plan = _apply_transferred_return_bindings(
            plan,
            transferred_return_bindings,
        )
        plan = _apply_transferred_return_expectations(
            plan,
            transferred_return_expectations,
        )
        canonical_plan = _rewrite_call_aliases(plan, aliases)
        canonical_calls = {call.call_id: call for call in canonical_plan.calls}
        canonical_reconciled = {
            call_id: item
            for call_id, item in reconciled_by_id.items()
            if call_id in canonical_calls
        }
        groups = _alias_groups(
            tuple(source_calls),
            aliases=aliases,
            canonical_call_ids=tuple(canonical_calls),
        )
        canonical_dependencies = _canonical_dependency_graph(
            canonical_plan,
            canonical_reconciled,
            aliases=aliases,
        )
        consumer_scopes = _dependency_consumer_scopes(
            canonical_dependencies,
            call_scopes={
                call_id: tuple(source_scopes[item] for item in members)
                for call_id, members in groups.items()
            },
        )
        provisional_execution_scopes: dict[str, str] = {}
        answer_scope_by_ref = {
            goal.id: goal.question_id
            for goal in question_goals
            if goal.required
        }
        for call in canonical_plan.calls:
            member_scopes = tuple(
                source_scopes[item_id]
                for item_id in groups.get(call.call_id, (call.call_id,))
            )
            destinations = consumer_scopes.get(call.call_id, ())
            answer_destinations = tuple(
                answer_scope_by_ref[binding.ref]
                for binding in call.return_bindings.values()
                if binding.kind == "answer"
                and binding.ref in answer_scope_by_ref
            )
            proposed = _call_execution_scope(
                declared_scopes=member_scopes,
                destination_scopes=destinations,
                answer_scopes=answer_destinations,
                registry=handle_registry,
            )
            item = canonical_reconciled.get(call.call_id)
            if item is not None and _inputs_visible_at_scope(
                item.resolved_args.values(),
                proposed,
                aliases=aliases,
                execution_scopes=provisional_execution_scopes,
                registry=handle_registry,
            ):
                provisional_execution_scopes[call.call_id] = proposed
            else:
                provisional_execution_scopes[call.call_id] = source_scopes[
                    call.call_id
                ]

        return_scopes: dict[str, dict[str, str]] = {}
        for call in canonical_plan.calls:
            item = canonical_reconciled.get(call.call_id)
            if item is None:
                continue
            scopes_by_return: dict[str, str] = {}
            for allocation in item.returns:
                member_allocations = tuple(
                    candidate
                    for member_id in groups.get(call.call_id, (call.call_id,))
                    for candidate in reconciled_by_id.get(member_id, item).returns
                    if candidate.return_name == allocation.return_name
                )
                proposed = _least_common_scope(
                    (
                        provisional_execution_scopes[call.call_id],
                        *(candidate.valid_scope for candidate in member_allocations),
                    ),
                    handle_registry,
                )
                if not _inputs_visible_at_scope(
                    item.resolved_args.values(),
                    proposed,
                    aliases=aliases,
                    execution_scopes=provisional_execution_scopes,
                    registry=handle_registry,
                ):
                    proposed = provisional_execution_scopes[call.call_id]
                scopes_by_return[allocation.return_name] = proposed
            return_scopes[call.call_id] = scopes_by_return

        final_calls = _reallocate_calls(
            canonical_plan,
            reconciled=canonical_reconciled,
            aliases=aliases,
            execution_scopes=provisional_execution_scopes,
            return_scopes=return_scopes,
            catalog=catalog,
            handle_registry=handle_registry,
            semantic_items=semantic_items,
        )
        final_by_id = {item.call_id: item for item in final_calls}
        placements = tuple(
            FunctionalCallPlacement(
                canonical_call_id=call.call_id,
                alias_call_ids=tuple(
                    item_id
                    for item_id in groups.get(call.call_id, ())
                    if item_id != call.call_id
                ),
                declared_scope_id=source_scopes[call.call_id],
                execution_scope_id=provisional_execution_scopes[call.call_id],
                return_scopes=return_scopes.get(call.call_id, {}),
                dependency_call_ids=canonical_dependencies.get(call.call_id, ()),
                placement_reason=_placement_reason(
                    call.call_id,
                    aliases=aliases,
                    declared_scope=source_scopes[call.call_id],
                    execution_scope=provisional_execution_scopes[call.call_id],
                ),
            )
            for call in canonical_plan.calls
            if call.call_id in final_by_id
        )
        placement_by_id = {item.canonical_call_id: item for item in placements}
        for placement in placements:
            if placement.execution_scope_id != placement.declared_scope_id:
                repairs.append(
                    FunctionalDeterministicRepair(
                        placement.canonical_call_id,
                        "place_call_at_shared_scope",
                        placement.declared_scope_id,
                        placement.execution_scope_id,
                    )
                )
        canonical_reports = tuple(
            replace(
                report,
                scope_id=(
                    placement_by_id[report.call_id].declared_scope_id
                    if report.call_id in placement_by_id
                    else report.scope_id
                ),
            )
            for report in call_reports
            if report.call_id not in aliases
        )
        return FunctionalCallPlacementResult(
            plan=canonical_plan,
            calls=final_calls,
            call_reports=canonical_reports,
            dependency_graph=canonical_dependencies,
            placements=placements,
            aliases=aliases,
            repairs=tuple(repairs),
            issues=tuple(issues),
        )


def _is_shareable(
    call: FunctionalCall,
    capability: FunctionalCapability,
) -> bool:
    if _has_answer_binding(call):
        return False
    if not capability.is_pure:
        return False
    return not any(item.runtime_type == "Condition" for item in capability.returns)


_OBJECT_BINDING_KINDS = {
    "point",
    "line",
    "segment",
    "ray",
    "function",
    "symbol",
    "angle",
    "circle",
    "polygon",
}


def _has_answer_binding(call: FunctionalCall) -> bool:
    return any(
        binding.kind == "answer" for binding in call.return_bindings.values()
    )


def _can_produce_reusable_object_state(
    call: FunctionalCall,
    reconciliation: FunctionalCallReconciliation,
    capability: FunctionalCapability,
) -> bool:
    if (
        capability.kind != "function"
        or not capability.is_pure
        or not reconciliation.returns
    ):
        return False
    return all(
        item.runtime_type != "Condition"
        and item.write_mode != "transition"
        and item.object_ref is not None
        and bool(item.state_slot_id)
        for item in reconciliation.returns
    )


def _is_redundant_existing_object_call(call: FunctionalCall) -> bool:
    return bool(call.return_bindings) and all(
        binding.kind in _OBJECT_BINDING_KINDS
        for binding in call.return_bindings.values()
    )


def _answer_return_bindings(call: FunctionalCall) -> dict[str, SemanticRef]:
    return {
        name: binding
        for name, binding in call.return_bindings.items()
        if binding.kind == "answer"
    }


def _can_transfer_answer_bindings(
    previous: FunctionalCall,
    duplicate: FunctionalCall,
    *,
    answer_bindings: Mapping[str, SemanticRef],
    transferred: Mapping[str, SemanticRef],
) -> bool:
    """Return whether one producer can carry the duplicate's answer binding.

    One return role has one external destination in FunctionalPlan v1. Replacing
    an existing object binding is safe because the reconciled StateSlot identity
    has already proved that both calls write the same object state. Two distinct
    answers for the same role stay as separate calls until the wire format gains
    an explicit multi-destination answer projection.
    """
    if not answer_bindings:
        return False
    for return_name, answer in answer_bindings.items():
        current = transferred.get(return_name) or previous.return_bindings.get(
            return_name
        )
        if current is not None and current.kind == "answer" and current != answer:
            return False
        if return_name not in duplicate.return_bindings:
            return False
    return True


def _transfer_answer_allocations(
    previous: FunctionalCallReconciliation,
    duplicate: FunctionalCallReconciliation,
    *,
    answer_bindings: Mapping[str, SemanticRef],
) -> FunctionalCallReconciliation:
    duplicate_returns = {item.return_name: item for item in duplicate.returns}
    return replace(
        previous,
        returns=tuple(
            replace(
                duplicate_returns[item.return_name],
                call_id=previous.call_id,
                dependency_object_refs=item.dependency_object_refs,
                free_symbol_refs=item.free_symbol_refs,
                source_state_slot_ids=item.source_state_slot_ids,
            )
            if item.return_name in answer_bindings
            and item.return_name in duplicate_returns
            else item
            for item in previous.returns
        ),
    )


def _apply_transferred_return_bindings(
    plan: FunctionalPlan,
    transferred: Mapping[str, Mapping[str, SemanticRef]],
) -> FunctionalPlan:
    if not transferred:
        return plan
    return replace(
        plan,
        scopes=tuple(
            replace(
                scope,
                calls=tuple(
                    replace(
                        call,
                        return_bindings={
                            **call.return_bindings,
                            **transferred.get(call.call_id, {}),
                        },
                    )
                    for call in scope.calls
                ),
            )
            for scope in plan.scopes
        ),
    )


def _apply_transferred_return_expectations(
    plan: FunctionalPlan,
    transferred: Mapping[str, Mapping[str, str]],
) -> FunctionalPlan:
    if not transferred:
        return plan
    return replace(
        plan,
        scopes=tuple(
            replace(
                scope,
                calls=tuple(
                    replace(
                        call,
                        return_expectations={
                            **call.return_expectations,
                            **transferred.get(call.call_id, {}),
                        },
                    )
                    for call in scope.calls
                ),
            )
            for scope in plan.scopes
        ),
    )


def _merged_return_expectations(
    previous: FunctionalCall,
    duplicate: FunctionalCall,
) -> dict[str, str] | None:
    merged = dict(previous.return_expectations)
    for name, expectation in duplicate.return_expectations.items():
        current = merged.get(name)
        if current is not None and current != expectation:
            return None
        merged[name] = expectation
    return merged


def _return_expectation_conflict_issue(
    previous: FunctionalCall,
    duplicate: FunctionalCall,
) -> FunctionalPlanIssue:
    conflicts = {
        name: [previous.return_expectations[name], expectation]
        for name, expectation in duplicate.return_expectations.items()
        if name in previous.return_expectations
        and previous.return_expectations[name] != expectation
    }
    return _issue(
        "functional_reconciliation",
        "functional.return_expectation_conflict",
        (
            f"equivalent calls {previous.call_id} and {duplicate.call_id} "
            "declare conflicting result forms"
        ),
        call_id=duplicate.call_id,
        details={
            "canonical_call_id": previous.call_id,
            "conflicts": conflicts,
        },
    )


def _resolved_object_state_signature(
    call: FunctionalCall,
    reconciliation: FunctionalCallReconciliation,
    *,
    aliases: Mapping[str, str],
) -> tuple[Any, ...]:
    return (
        call.capability_id,
        tuple(
            sorted(
                (
                    name,
                    tuple(
                        _value_fingerprint(value, aliases=aliases)
                        for value in values
                    ),
                )
                for name, values in reconciliation.resolved_args.items()
            )
        ),
        tuple(
            (
                item.return_name,
                item.runtime_type,
                item.state_slot_id,
                item.object_ref,
                item.identity_policy,
                item.write_mode,
            )
            for item in reconciliation.returns
        ),
    )


def _wire_call_signature(call: FunctionalCall) -> tuple[Any, ...]:
    return (
        call.capability_id,
        tuple(
            sorted(
                (
                    name,
                    tuple(
                        tuple(sorted(ref.to_payload().items()))
                        for ref in refs
                    ),
                )
                for name, refs in call.args.items()
            )
        ),
        tuple(
            sorted(
                (name, tuple(sorted(binding.to_payload().items())))
                for name, binding in call.return_bindings.items()
            )
        ),
    )


def _wire_inputs_visible_at_scope(
    call: FunctionalCall,
    scope_id: str,
    *,
    capability: Any,
    semantic_index: FunctionalSemanticIndex,
) -> bool:
    args = {item.name: item for item in capability.args}
    for name, refs in call.args.items():
        arg = args.get(name)
        if arg is None:
            return False
        for ref in refs:
            if isinstance(ref, CallResultRef):
                continue
            resolved, _ = semantic_index.resolve(
                ref,
                scope_id=scope_id,
                accepted_types=arg.accepted_item_types or (arg.runtime_type,),
                accepted_condition_kinds=arg.accepted_condition_kinds,
            )
            if resolved is None:
                return False
    return True


def _resolved_call_signature(
    call: FunctionalCall,
    reconciliation: FunctionalCallReconciliation,
    *,
    aliases: Mapping[str, str],
) -> tuple[Any, ...]:
    return (
        call.capability_id,
        tuple(
            sorted(
                (
                    name,
                    tuple(_value_fingerprint(value, aliases=aliases) for value in values),
                )
                for name, values in reconciliation.resolved_args.items()
            )
        ),
        tuple(
            sorted(
                (name, binding.kind, binding.ref, binding.value_type)
                for name, binding in call.return_bindings.items()
            )
        ),
        tuple(
            (
                item.return_name,
                item.runtime_type,
                item.object_ref,
                item.identity_policy,
                item.write_mode,
            )
            for item in reconciliation.returns
        ),
    )


def _value_fingerprint(
    value: ResolvedFunctionalValue,
    *,
    aliases: Mapping[str, str],
) -> tuple[Any, ...]:
    if value.source_call_id is not None:
        return (
            "call_result",
            _canonical(value.source_call_id, aliases),
            value.return_name,
            value.runtime_type,
            value.object_ref,
        )
    if value.condition_id is not None:
        return (
            "condition",
            value.condition_id,
            value.runtime_type,
            value.object_ref,
        )
    if value.state_slot_id is not None:
        return (
            "state_slot",
            value.state_slot_id,
            value.runtime_type,
            value.object_ref,
            value.source_state_slot_ids,
        )
    return (
        "handle",
        value.handle,
        value.runtime_type,
        value.object_ref,
        value.dependency_object_refs,
    )


def _inputs_shareable_at_scope(
    value_groups: Sequence[tuple[ResolvedFunctionalValue, ...]],
    scope_id: str,
    *,
    aliases: Mapping[str, str],
    groups: Mapping[str, tuple[str, ...]],
    source_scopes: Mapping[str, str],
    registry: CanonicalHandleRegistry,
) -> bool:
    for values in value_groups:
        for value in values:
            valid_scope = value.valid_scope
            if value.source_call_id is not None:
                source = _canonical(value.source_call_id, aliases)
                members = groups.get(source, (source,))
                valid_scope = _least_common_scope(
                    (
                        value.valid_scope,
                        *(source_scopes[item] for item in members),
                    ),
                    registry,
                )
            if not visible_from_valid_scope(
                valid_scope,
                scope_id=scope_id,
                registry=registry,
            ):
                return False
    return True


def _inputs_visible_at_scope(
    value_groups: Sequence[tuple[ResolvedFunctionalValue, ...]],
    scope_id: str,
    *,
    aliases: Mapping[str, str],
    execution_scopes: Mapping[str, str],
    registry: CanonicalHandleRegistry,
) -> bool:
    for values in value_groups:
        for value in values:
            valid_scope = value.valid_scope
            if value.source_call_id is not None:
                source = _canonical(value.source_call_id, aliases)
                execution_scope = execution_scopes.get(source)
                if execution_scope is not None:
                    # A producer may execute in a child question while its
                    # answer/object state is deliberately published to an
                    # ancestor. Moving a dependent call must preserve that
                    # publication scope; a hoisted producer can only broaden it.
                    valid_scope = _least_common_scope(
                        (valid_scope, execution_scope),
                        registry,
                    )
            if not visible_from_valid_scope(
                valid_scope,
                scope_id=scope_id,
                registry=registry,
            ):
                return False
    return True


def _reallocate_calls(
    plan: FunctionalPlan,
    *,
    reconciled: Mapping[str, FunctionalCallReconciliation],
    aliases: Mapping[str, str],
    execution_scopes: Mapping[str, str],
    return_scopes: Mapping[str, Mapping[str, str]],
    catalog: FunctionalCapabilityCatalog,
    handle_registry: CanonicalHandleRegistry,
    semantic_items: Sequence[SemanticReadCatalogItem],
) -> tuple[FunctionalCallReconciliation, ...]:
    semantic_by_ref = {(item.kind, item.ref): item for item in semantic_items}
    produced: dict[tuple[str, str], FunctionalReturnAllocation] = {}
    result: list[FunctionalCallReconciliation] = []
    factory = CanonicalStateHandleFactory()
    for call in plan.calls:
        item = reconciled.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if item is None or capability is None:
            continue
        resolved_args = {
            name: tuple(
                _rewrite_resolved_value(value, produced=produced, aliases=aliases)
                for value in values
            )
            for name, values in item.resolved_args.items()
        }
        specs = {spec.name: spec for spec in capability.returns}
        allocations: list[FunctionalReturnAllocation] = []
        for old in item.returns:
            spec = specs[old.return_name]
            valid_scope = return_scopes[call.call_id][old.return_name]
            binding = (
                semantic_by_ref.get((old.bound_ref.kind, old.bound_ref.ref))
                if old.bound_ref is not None
                else None
            )
            object_ref = factory.object_ref_for(
                call_id=call.call_id,
                return_spec=spec,
                valid_scope=valid_scope,
                binding=binding,
                resolved_args=resolved_args,
                handle_registry=handle_registry,
                sibling_returns=tuple(allocations),
            )
            if object_ref is None and old.object_ref is not None:
                object_ref = _relocate_ref(old.object_ref, valid_scope)
            handle = factory.handle_for(
                call_id=call.call_id,
                return_spec=spec,
                valid_scope=valid_scope,
                binding=binding,
            )
            if old.handle.startswith("answer:"):
                handle = old.handle
            state_slot_id = (
                f"{object_ref}.{spec.state_kind}@{valid_scope}"
                if object_ref is not None
                else f"functional:{valid_scope}:{call.call_id}:{old.return_name}"
            )
            allocation = replace(
                old,
                call_id=call.call_id,
                handle=handle,
                valid_scope=valid_scope,
                state_slot_id=state_slot_id,
                object_ref=object_ref,
                dependency_object_refs=_argument_dependencies(resolved_args),
                free_symbol_refs=return_free_symbol_refs(
                    spec.runtime_type,
                    resolved_args,
                    object_ref=object_ref,
                ),
                source_state_slot_ids=_argument_source_slots(resolved_args),
            )
            allocations.append(allocation)
            produced[(call.call_id, old.return_name)] = allocation
        result.append(
            replace(
                item,
                scope_id=execution_scopes[call.call_id],
                resolved_args=resolved_args,
                returns=tuple(allocations),
            )
        )
    return tuple(result)


def _rewrite_resolved_value(
    value: ResolvedFunctionalValue,
    *,
    produced: Mapping[tuple[str, str], FunctionalReturnAllocation],
    aliases: Mapping[str, str],
) -> ResolvedFunctionalValue:
    if value.source_call_id is None or value.return_name is None:
        return value
    source = _canonical(value.source_call_id, aliases)
    allocation = produced.get((source, value.return_name))
    if allocation is None:
        return replace(value, source_call_id=source)
    return ResolvedFunctionalValue(
        handle=allocation.handle,
        runtime_type=allocation.runtime_type,
        valid_scope=allocation.valid_scope,
        state_slot_id=allocation.state_slot_id,
        source_call_id=source,
        return_name=allocation.return_name,
        object_ref=allocation.object_ref,
        dependency_object_refs=allocation.dependency_object_refs,
        free_symbol_refs=allocation.free_symbol_refs,
        source_state_slot_ids=allocation.source_state_slot_ids,
    )


def _canonical_dependency_graph(
    plan: FunctionalPlan,
    reconciled: Mapping[str, FunctionalCallReconciliation],
    *,
    aliases: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    call_ids = {call.call_id for call in plan.calls}
    for call in plan.calls:
        dependencies = [
            ref.from_call
            for values in call.args.values()
            for ref in values
            if isinstance(ref, CallResultRef)
        ]
        item = reconciled.get(call.call_id)
        if item is not None:
            dependencies.extend(
                value.source_call_id
                for values in item.resolved_args.values()
                for value in values
                if value.source_call_id is not None
            )
        result[call.call_id] = tuple(
            dict.fromkeys(
                canonical
                for dependency in dependencies
                if (canonical := _canonical(dependency, aliases)) in call_ids
                and canonical != call.call_id
            )
        )
    return result


def _dependency_consumer_scopes(
    dependency_graph: Mapping[str, tuple[str, ...]],
    *,
    call_scopes: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for consumer, dependencies in dependency_graph.items():
        for dependency in dependencies:
            result.setdefault(dependency, []).extend(call_scopes[consumer])
    return {
        call_id: tuple(dict.fromkeys(scopes))
        for call_id, scopes in result.items()
    }


def _alias_groups(
    source_call_ids: Sequence[str],
    *,
    aliases: Mapping[str, str],
    canonical_call_ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    canonical_set = set(canonical_call_ids)
    groups: dict[str, list[str]] = {call_id: [] for call_id in canonical_call_ids}
    for call_id in source_call_ids:
        canonical = _canonical(call_id, aliases)
        if canonical in canonical_set:
            groups.setdefault(canonical, []).append(call_id)
    return {key: tuple(value or (key,)) for key, value in groups.items()}


def _call_execution_scope(
    *,
    declared_scopes: Sequence[str],
    destination_scopes: Sequence[str],
    answer_scopes: Sequence[str],
    registry: CanonicalHandleRegistry,
) -> str:
    # Execution placement is a graph property. Answer ownership is handled by
    # the independent student narrative projection and must not pin a shared
    # canonical computation to one child question.
    return _least_common_scope(
        (*declared_scopes, *destination_scopes, *answer_scopes),
        registry,
    )


def _relocate_ref(value: str, scope_id: str) -> str:
    if "@" in value:
        return value.rsplit("@", 1)[0] + f"@{scope_id}"
    parts = value.split(":", 2)
    if len(parts) == 3:
        return f"{parts[0]}:{scope_id}:{parts[2]}"
    return value


def _argument_dependencies(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            dependency
            for values in args.values()
            for value in values
            for dependency in (
                *((value.object_ref,) if value.object_ref else ()),
                *value.dependency_object_refs,
            )
        )
    )


def _argument_source_slots(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            slot_id
            for values in args.values()
            for value in values
            for slot_id in (
                *((value.state_slot_id,) if value.state_slot_id else ()),
                *value.source_state_slot_ids,
            )
        )
    )


def _placement_reason(
    call_id: str,
    *,
    aliases: Mapping[str, str],
    declared_scope: str,
    execution_scope: str,
) -> str:
    if any(owner == call_id for owner in aliases.values()):
        return "shared_equivalent_calls"
    if declared_scope != execution_scope:
        return "consumer_scope_lca"
    return "declared_scope"


__all__ = [
    "FunctionalCallPlacementResult",
    "FunctionalCallPlacementService",
]
