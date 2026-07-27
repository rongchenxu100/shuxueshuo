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
)
from shuxueshuo_server.solver.runtime.functional_plan_graph import (
    canonical_call_aliases as _canonical_aliases,
    canonical_call_id as _canonical,
    least_common_scope as _least_common_scope,
    rewrite_call_aliases as _rewrite_call_aliases,
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
    apply_symbolic_closure_effect,
    return_free_symbol_refs,
)
from shuxueshuo_server.solver.runtime.functional_state_allocation import (
    functional_computation_key,
    functional_source_version_ids,
    project_sibling_symbol_dependencies,
)
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpec
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    parse_scoped_non_answer_handle,
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.semantic_reads import (
    SemanticReadCatalogItem,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    ComputationKey,
    FunctionalCallIdentityKey,
    LogicalReturnEffect,
    LogicalStateKey,
    RuntimeDestinationKey,
    StateAllocationRequest,
    StateAllocationService,
    StateEffectKey,
    StateIdentityFactory,
    StateIdentityIndex,
    StatePlacementMode,
    StateVersionId,
    StateVersionPlacementRewrite,
    TypedCallPlacementDecision,
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
    typed_decisions: tuple[TypedCallPlacementDecision, ...] = ()
    mismatches: tuple[dict[str, Any], ...] = ()


class FunctionalCallPlacementService:
    """Canonicalize equivalent calls before StepIntent projection.

    Reconciliation may use temporary scope-local allocations while resolving a
    forward-only call graph. This pass is the sole owner of the final execution
    scope, return publication scope, canonical call aliases, handles and slots.
    """

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
        identity_factory: StateIdentityFactory | None = None,
        base_identity_index: StateIdentityIndex | None = None,
        allocation_service: StateAllocationService | None = None,
        placement_mode: StatePlacementMode = "authoritative",
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
        repairs: list[FunctionalDeterministicRepair] = []
        issues: list[FunctionalPlanIssue] = []
        transferred_return_expectations: dict[str, dict[str, str]] = {}
        transferred_return_bindings: dict[str, dict[str, SemanticRef]] = {}
        (
            aliases,
            groups,
            reconciled_by_id,
            typed_identity_keys,
            typed_repairs,
            typed_issues,
            transferred_return_bindings,
            transferred_return_expectations,
        ) = _canonicalize_typed_calls(
            plan,
            source_scopes=source_scopes,
            reconciled_by_id=reconciled_by_id,
            catalog=catalog,
            aliases=aliases,
            groups=groups,
            handle_registry=handle_registry,
        )
        repairs.extend(typed_repairs)
        issues.extend(typed_issues)

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
        requested_execution_scopes: dict[str, str] = {}
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
            answer_target_scopes = _answer_target_object_scopes(
                call,
                handle_registry=handle_registry,
            )
            proposed = _call_execution_scope(
                declared_scopes=member_scopes,
                destination_scopes=destinations,
                answer_scopes=answer_destinations,
                answer_target_scopes=answer_target_scopes,
                registry=handle_registry,
            )
            requested_execution_scopes[call.call_id] = proposed

        provisional_execution_scopes = _close_execution_scope_dependencies(
            canonical_plan,
            reconciled=canonical_reconciled,
            dependency_graph=canonical_dependencies,
            requested_scopes=requested_execution_scopes,
            declared_scopes={
                call_id: source_scopes[call_id]
                for call_id in canonical_calls
            },
            aliases=aliases,
            registry=handle_registry,
        )

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

        materialized_calls = _project_placed_calls(
            canonical_plan,
            reconciled=canonical_reconciled,
            aliases=aliases,
            execution_scopes=provisional_execution_scopes,
            return_scopes=return_scopes,
            catalog=catalog,
            semantic_items=semantic_items,
        )
        version_rewrites: tuple[StateVersionPlacementRewrite, ...] = ()
        if (
            placement_mode == "authoritative"
            and identity_factory is not None
            and base_identity_index is not None
            and allocation_service is not None
        ):
            (
                final_calls,
                version_rewrites,
                typed_finalization_issues,
            ) = _finalize_typed_allocations(
                canonical_plan,
                reconciled=materialized_calls,
                catalog=catalog,
                execution_scopes=provisional_execution_scopes,
                return_scopes=return_scopes,
                identity_factory=identity_factory,
                identity_index=base_identity_index.clone(),
                allocation_service=allocation_service,
            )
            issues.extend(typed_finalization_issues)
        else:
            final_calls = materialized_calls
        issues.extend(
            _post_placement_scope_issues(
                final_calls,
                registry=handle_registry,
            )
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
        rewrites_by_call = _version_rewrites_by_call(
            final_calls,
            version_rewrites,
        )
        typed_decisions = tuple(
            TypedCallPlacementDecision(
                canonical_call_id=call.call_id,
                alias_call_ids=tuple(
                    item_id
                    for item_id in groups.get(call.call_id, ())
                    if item_id != call.call_id
                ),
                identity_key=(
                    _typed_call_identity_key(
                        final_by_id[call.call_id],
                        capability=catalog.items[call.capability_id],
                        aliases=aliases,
                    )
                    or typed_identity_keys[call.call_id]
                ),
                declared_scope_ids=tuple(
                    source_scopes[item_id]
                    for item_id in groups.get(
                        call.call_id,
                        (call.call_id,),
                    )
                ),
                execution_scope_id=provisional_execution_scopes[
                    call.call_id
                ],
                return_scope_ids=return_scopes.get(call.call_id, {}),
                version_rewrites=rewrites_by_call.get(call.call_id, ()),
                reason_code="typed_identity_placement",
            )
            for call in canonical_plan.calls
            if call.call_id in final_by_id
            and call.call_id in typed_identity_keys
        )
        placement_mismatches = _typed_placement_mismatches(
            final_calls,
            decisions=typed_decisions,
            registry=handle_registry,
        )
        if placement_mode == "authoritative":
            issues.extend(
                _issue(
                    "functional_reconciliation",
                    "planner.state_placement_drift",
                    item["message"],
                    call_id=item["call_id"],
                    scope_id=item.get("execution_scope_id"),
                    details=item,
                )
                for item in placement_mismatches
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
            typed_decisions=typed_decisions,
            mismatches=placement_mismatches,
        )


def _is_shareable(
    call: FunctionalCall,
    capability: FunctionalCapability,
) -> bool:
    if not capability.is_pure:
        return False
    return not any(item.runtime_type == "Condition" for item in capability.returns)


def _canonicalize_typed_calls(
    plan: FunctionalPlan,
    *,
    source_scopes: Mapping[str, str],
    reconciled_by_id: Mapping[str, FunctionalCallReconciliation],
    catalog: FunctionalCapabilityCatalog,
    aliases: Mapping[str, str],
    groups: Mapping[str, tuple[str, ...]],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    dict[str, str],
    dict[str, tuple[str, ...]],
    dict[str, FunctionalCallReconciliation],
    dict[str, FunctionalCallIdentityKey],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
    dict[str, dict[str, SemanticRef]],
    dict[str, dict[str, str]],
]:
    """Merge calls only when B1 typed computation and effects are identical."""

    aliases = _canonical_aliases(dict(aliases))
    groups = dict(groups)
    reconciled_by_id = dict(reconciled_by_id)
    call_by_id = {call.call_id: call for call in plan.calls}
    owners_by_key: dict[FunctionalCallIdentityKey, list[str]] = {}
    keys_by_call: dict[str, FunctionalCallIdentityKey] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []
    transferred_bindings: dict[str, dict[str, SemanticRef]] = {}
    transferred_expectations: dict[str, dict[str, str]] = {}

    for call in plan.calls:
        if call.call_id in aliases:
            continue
        item = reconciled_by_id.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if item is None or capability is None:
            continue
        identity_key = _typed_call_identity_key(
            item,
            capability=capability,
            aliases=aliases,
        )
        if identity_key is None:
            continue
        keys_by_call[call.call_id] = identity_key
        if not _is_shareable(call, capability):
            continue
        owner_ids = owners_by_key.setdefault(identity_key, [])
        if not owner_ids:
            owner_ids.append(call.call_id)
            continue
        binding_conflicts: list[FunctionalCall] = []
        merged_into_owner = False
        for previous_id in tuple(owner_ids):
            previous = reconciled_by_id.get(previous_id)
            previous_call = call_by_id.get(previous_id)
            if previous is None or previous_call is None:
                continue
            effective_previous_call = replace(
                previous_call,
                return_bindings={
                    **previous_call.return_bindings,
                    **transferred_bindings.get(previous_id, {}),
                },
            )
            merged_bindings = _merged_return_bindings(
                effective_previous_call,
                call,
                transferred={},
            )
            if merged_bindings is None:
                binding_conflicts.append(effective_previous_call)
                continue
            candidate_members = tuple(
                dict.fromkeys(
                    (
                        *groups.get(previous_id, (previous_id,)),
                        *groups.get(call.call_id, (call.call_id,)),
                    )
                )
            )
            candidate_scope = _least_common_scope(
                tuple(source_scopes[item_id] for item_id in candidate_members),
                handle_registry,
            )
            if not _inputs_shareable_at_scope(
                (*previous.resolved_args.values(), *item.resolved_args.values()),
                candidate_scope,
                aliases=aliases,
                groups=groups,
                source_scopes=source_scopes,
                registry=handle_registry,
            ):
                continue

            expectation_owner = replace(
                previous_call,
                return_expectations=transferred_expectations.get(
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
                transferred_expectations[previous_id] = merged_expectations

            effective_previous_bindings = (
                effective_previous_call.return_bindings
            )
            changed_bindings = {
                return_name: binding
                for return_name, binding in merged_bindings.items()
                if effective_previous_bindings.get(return_name) != binding
            }
            if changed_bindings:
                transferred_bindings[previous_id] = merged_bindings
                reconciled_by_id[previous_id] = _transfer_return_allocations(
                    previous,
                    item,
                    transferred_bindings=changed_bindings,
                )
            transferred_answer = any(
                binding.kind == "answer"
                for binding in changed_bindings.values()
            )

            aliases[call.call_id] = previous_id
            aliases = _canonical_aliases(aliases)
            groups.setdefault(previous_id, (previous_id,))
            groups[previous_id] = candidate_members
            groups.pop(call.call_id, None)
            repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    (
                        "reuse_existing_state_for_answer"
                        if transferred_answer
                        else (
                            "merge_typed_equivalent_call"
                            if merged_expectations is not None
                            else "merge_typed_call_with_expectation_conflict"
                        )
                    ),
                    call.call_id,
                    previous_id,
                )
            )
            merged_into_owner = True
            break

        if merged_into_owner:
            continue
        owner_ids.append(call.call_id)
        if binding_conflicts:
            issues.append(
                _return_binding_conflict_issue(
                    tuple(binding_conflicts),
                    call,
                )
            )

    return (
        aliases,
        groups,
        reconciled_by_id,
        keys_by_call,
        tuple(repairs),
        tuple(issues),
        transferred_bindings,
        transferred_expectations,
    )


def _typed_call_identity_key(
    reconciliation: FunctionalCallReconciliation,
    *,
    capability: FunctionalCapability,
    aliases: Mapping[str, str] | None = None,
) -> FunctionalCallIdentityKey | None:
    computation_keys = {
        _canonicalize_computation_key(
            item.computation_key,
            aliases=aliases or {},
        )
        for item in reconciliation.returns
        if item.computation_key is not None
    }
    if len(computation_keys) != 1:
        return None
    state_effect_key = _state_effect_key_for_returns(
        reconciliation.returns,
        capability=capability,
    )
    if state_effect_key is None:
        return None
    return FunctionalCallIdentityKey(
        computation_key=next(iter(computation_keys)),
        state_effect_key=state_effect_key,
    )


def _state_effect_key_for_returns(
    returns: Sequence[FunctionalReturnAllocation],
    *,
    capability: FunctionalCapability,
    logical_keys: Mapping[str, LogicalStateKey | None] | None = None,
) -> StateEffectKey | None:
    """Build one call effect from the returns actually materialized."""

    specs = {item.name: item for item in capability.returns}
    effects: list[LogicalReturnEffect] = []
    for item in returns:
        spec = specs.get(item.return_name)
        if spec is None:
            return None
        effects.append(
            LogicalReturnEffect(
                return_name=spec.equivalent_to or item.return_name,
                logical_key=(
                    logical_keys.get(item.return_name)
                    if logical_keys is not None
                    else item.logical_state_key
                ),
                identity_policy=spec.identity_policy,
                write_mode=spec.write_mode,
            )
        )
    return StateEffectKey(tuple(effects))


def _canonicalize_computation_key(
    key: ComputationKey | None,
    *,
    aliases: Mapping[str, str],
) -> ComputationKey | None:
    if key is None or not aliases:
        return key
    bindings = []
    for binding in key.arg_bindings:
        call_result_id = binding.call_result_id
        if call_result_id is not None and "." in call_result_id:
            call_id, return_name = call_result_id.split(".", 1)
            call_result_id = (
                f"{_canonical(call_id, aliases)}.{return_name}"
            )
        bindings.append(
            replace(binding, call_result_id=call_result_id)
        )
    return replace(key, arg_bindings=tuple(bindings))


def _merged_return_bindings(
    previous: FunctionalCall,
    duplicate: FunctionalCall,
    *,
    transferred: Mapping[str, SemanticRef],
) -> dict[str, SemanticRef] | None:
    merged = {
        **previous.return_bindings,
        **transferred,
    }
    for return_name in set(previous.return_bindings) | set(
        duplicate.return_bindings
    ):
        left = merged.get(return_name)
        right = duplicate.return_bindings.get(return_name)
        if left is None or right is None or left == right:
            if left is None and right is not None:
                merged[return_name] = right
            continue
        if left.kind == "answer" and right.kind == "answer":
            return None
        if left.kind != "answer" and right.kind != "answer":
            return None
        if right.kind == "answer":
            merged[return_name] = right
    return merged


def _return_binding_conflict_issue(
    previous_calls: tuple[FunctionalCall, ...],
    duplicate: FunctionalCall,
) -> FunctionalPlanIssue:
    conflicts = []
    for previous in previous_calls:
        conflicting_returns = []
        for return_name in sorted(
            set(previous.return_bindings) & set(duplicate.return_bindings)
        ):
            left = previous.return_bindings[return_name]
            right = duplicate.return_bindings[return_name]
            if left == right:
                continue
            if (
                left.kind == "answer"
                and right.kind != "answer"
            ) or (
                left.kind != "answer"
                and right.kind == "answer"
            ):
                continue
            conflicting_returns.append(
                {
                    "return_name": return_name,
                    "existing": left.to_payload(),
                    "incoming": right.to_payload(),
                }
            )
        if conflicting_returns:
            conflicts.append(
                {
                    "call_id": previous.call_id,
                    "returns": conflicting_returns,
                }
            )
    return _issue(
        "functional_reconciliation",
        "functional.return_binding_conflict",
        (
            f"equivalent call {duplicate.call_id} declares return destinations "
            "that conflict with an existing typed computation cluster"
        ),
        call_id=duplicate.call_id,
        details={
            "conflicting_calls": conflicts,
        },
    )


def _has_answer_binding(call: FunctionalCall) -> bool:
    return any(
        binding.kind == "answer" for binding in call.return_bindings.values()
    )


def _transfer_return_allocations(
    previous: FunctionalCallReconciliation,
    duplicate: FunctionalCallReconciliation,
    *,
    transferred_bindings: Mapping[str, SemanticRef],
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
            if item.return_name in transferred_bindings
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


def _close_execution_scope_dependencies(
    plan: FunctionalPlan,
    *,
    reconciled: Mapping[str, FunctionalCallReconciliation],
    dependency_graph: Mapping[str, tuple[str, ...]],
    requested_scopes: Mapping[str, str],
    declared_scopes: Mapping[str, str],
    aliases: Mapping[str, str],
    registry: CanonicalHandleRegistry,
) -> dict[str, str]:
    """Solve producer/consumer placement as a dependency-closure fixed point.

    A consumer may request an ancestor scope because sibling questions share
    it. The requested scope first propagates backwards through the complete
    producer graph. Once that fixed point is known, calls whose external
    inputs are not visible there fall back to their declared scope; that
    fallback then propagates forward to dependent consumers.
    """

    result = dict(requested_scopes)
    calls = {call.call_id: call for call in plan.calls}
    max_rounds = max(1, len(calls) * 2)
    # Move the entire producer closure before checking visibility. Checking a
    # partial closure creates an order-dependent deadlock: a producer cannot
    # move until its own producer moves, but that upstream producer is never
    # considered after the immediate move is rejected.
    for _ in range(max_rounds):
        changed = False
        for call in plan.calls:
            for dependency_id in dependency_graph.get(call.call_id, ()):
                dependency_call = calls.get(dependency_id)
                if dependency_call is None:
                    continue
                if _has_answer_binding(dependency_call):
                    continue
                proposed = _least_common_scope(
                    (result[dependency_id], result[call.call_id]),
                    registry,
                )
                if proposed == result[dependency_id]:
                    continue
                result[dependency_id] = proposed
                changed = True
        if not changed:
            break

    # Reject unsafe hoists after the closure is complete. Repeating in reverse
    # topological order lets a producer fallback force each dependent consumer
    # back to a readable scope as well.
    for _ in range(max_rounds):
        changed = False
        for call in reversed(plan.calls):
            item = reconciled.get(call.call_id)
            if item is None or _inputs_visible_at_scope(
                item.resolved_args.values(),
                result[call.call_id],
                aliases=aliases,
                execution_scopes=result,
                registry=registry,
            ):
                continue
            declared = declared_scopes[call.call_id]
            if result[call.call_id] == declared:
                continue
            result[call.call_id] = declared
            changed = True
        if not changed:
            break
    return result


def _project_placed_calls(
    plan: FunctionalPlan,
    *,
    reconciled: Mapping[str, FunctionalCallReconciliation],
    aliases: Mapping[str, str],
    execution_scopes: Mapping[str, str],
    return_scopes: Mapping[str, Mapping[str, str]],
    catalog: FunctionalCapabilityCatalog,
    semantic_items: Sequence[SemanticReadCatalogItem],
) -> tuple[FunctionalCallReconciliation, ...]:
    """Project final scopes to legacy handles without deciding typed identity."""

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
            object_ref = old.object_ref
            handle = factory.handle_for(
                call_id=call.call_id,
                return_spec=spec,
                valid_scope=valid_scope,
                binding=binding,
            )
            if old.handle.startswith("answer:"):
                handle = old.handle
            state_handle = (
                factory.handle_for(
                    call_id=call.call_id,
                    return_spec=spec,
                    valid_scope=valid_scope,
                    binding=None,
                )
                if old.state_handle is not None
                else None
            )
            state_slot_id = (
                f"{object_ref}.{spec.state_kind}@{valid_scope}:"
                f"{spec.runtime_type}"
                if object_ref is not None
                else f"functional:{valid_scope}:{call.call_id}:{old.return_name}"
            )
            inferred_free_symbol_refs = return_free_symbol_refs(
                spec.runtime_type,
                resolved_args,
                object_ref=object_ref,
                ignored_input_args=spec.result_form_ignored_input_args,
            )
            allocation = replace(
                old,
                call_id=call.call_id,
                handle=handle,
                state_handle=state_handle,
                valid_scope=valid_scope,
                state_slot_id=state_slot_id,
                object_ref=object_ref,
                dependency_object_refs=_argument_dependencies(resolved_args),
                free_symbol_refs=apply_symbolic_closure_effect(
                    inferred_free_symbol_refs,
                    return_name=spec.name,
                    args=resolved_args,
                    spec=(
                        capability.source.symbolic_closure
                        if isinstance(capability.source, FunctionSpec)
                        else None
                    ),
                ),
                source_state_slot_ids=_argument_source_slots(resolved_args),
            )
            allocations.append(allocation)
            produced[(call.call_id, old.return_name)] = allocation
        allocations = list(
            project_sibling_symbol_dependencies(
                tuple(specs.values()),
                tuple(allocations),
                capability_id=call.capability_id,
            )
        )
        for allocation in allocations:
            produced[(call.call_id, allocation.return_name)] = allocation
        result.append(
            replace(
                item,
                scope_id=execution_scopes[call.call_id],
                resolved_args=resolved_args,
                returns=tuple(allocations),
            )
        )
    return tuple(result)


def _finalize_typed_allocations(
    plan: FunctionalPlan,
    *,
    reconciled: Sequence[FunctionalCallReconciliation],
    catalog: FunctionalCapabilityCatalog,
    execution_scopes: Mapping[str, str],
    return_scopes: Mapping[str, Mapping[str, str]],
    identity_factory: StateIdentityFactory,
    identity_index: StateIdentityIndex,
    allocation_service: StateAllocationService,
) -> tuple[
    tuple[FunctionalCallReconciliation, ...],
    tuple[StateVersionPlacementRewrite, ...],
    tuple[FunctionalPlanIssue, ...],
]:
    """Replay B1 allocation after canonicalization and final scope placement."""

    reconciled_by_id = {item.call_id: item for item in reconciled}
    produced: dict[tuple[str, str], FunctionalReturnAllocation] = {}
    version_map: dict[StateVersionId, StateVersionId] = {}
    rewrites: list[StateVersionPlacementRewrite] = []
    issues: list[FunctionalPlanIssue] = []
    result: list[FunctionalCallReconciliation] = []

    for call in plan.calls:
        item = reconciled_by_id.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if item is None or capability is None:
            continue
        scope_id = execution_scopes[call.call_id]
        resolved_args = {
            name: tuple(
                _rewrite_resolved_value_versions(
                    _rewrite_resolved_value(
                        value,
                        produced=produced,
                        aliases={},
                    ),
                    version_map,
                )
                for value in values
            )
            for name, values in item.resolved_args.items()
        }
        computation_key = functional_computation_key(
            call,
            resolved_args=resolved_args,
            scope_id=scope_id,
            identity_factory=identity_factory,
            identity_index=identity_index,
        )
        specs = {spec.name: spec for spec in capability.returns}
        logical_keys = {
            old.return_name: identity_factory.logical_key(
                object_ref=old.object_ref,
                state_kind=specs[old.return_name].state_kind,
                runtime_type=specs[old.return_name].runtime_type,
            )
            for old in item.returns
            if old.return_name in specs
        }
        state_effect_key = _state_effect_key_for_returns(
            item.returns,
            capability=capability,
            logical_keys=logical_keys,
        )
        if state_effect_key is None:
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "planner.state_placement_drift",
                    (
                        "final typed allocation cannot rebuild the declared "
                        f"return effect for {call.call_id}"
                    ),
                    call_id=call.call_id,
                    scope_id=scope_id,
                    details={
                        "reason_code": "return_effect_spec_missing",
                        "returns": [
                            old.return_name for old in item.returns
                        ],
                    },
                )
            )
            continue
        source_version_ids = tuple(
            _rewrite_version_id(version_id, version_map)
            for version_id in functional_source_version_ids(
                resolved_args,
                scope_id=scope_id,
                identity_index=identity_index,
            )
        )
        allocations: list[FunctionalReturnAllocation] = []
        for old in item.returns:
            spec = specs.get(old.return_name)
            if spec is None:
                continue
            valid_scope = return_scopes[call.call_id][old.return_name]
            math_object_id = identity_factory.object_id(old.object_ref)
            runtime_destination = (
                RuntimeDestinationKey(
                    math_object_id,
                    spec.state_kind,
                    spec.runtime_type,
                )
                if math_object_id is not None
                else None
            )
            request = StateAllocationRequest(
                call_id=call.call_id,
                capability_id=call.capability_id,
                return_name=old.return_name,
                object_id=math_object_id,
                state_kind=spec.state_kind,
                runtime_type=spec.runtime_type,
                storage_scope_id=valid_scope,
                valid_scope_id=valid_scope,
                requested_write_mode=spec.write_mode,
                identity_policy=spec.identity_policy,
                is_shareable=capability.is_pure,
                computation_key=computation_key,
                state_effect_key=state_effect_key,
                source_version_ids=source_version_ids,
                free_symbol_refs=old.free_symbol_refs,
                runtime_destination=runtime_destination,
                result_form=call.return_expectations.get(old.return_name),
            )
            decision = allocation_service.allocate(request, identity_index)
            if decision.action == "conflict":
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "planner.state_placement_drift",
                        (
                            "typed allocation changed after call placement: "
                            f"{call.call_id}.{old.return_name}"
                        ),
                        call_id=call.call_id,
                        scope_id=scope_id,
                        details={
                            "return": old.return_name,
                            "reason_code": decision.reason_code,
                            "conflict_code": decision.conflict_code,
                        },
                    )
                )
            selected_version_id = decision.selected_version_id
            if (
                old.selected_version_id is not None
                and selected_version_id is not None
                and old.selected_version_id != selected_version_id
            ):
                version_map[old.selected_version_id] = selected_version_id
                rewrites.append(
                    StateVersionPlacementRewrite(
                        old.selected_version_id,
                        selected_version_id,
                    )
                )
            effective_write_mode = old.write_mode
            if decision.action in {"create", "isolated"}:
                effective_write_mode = "create"
            elif decision.action == "transition":
                effective_write_mode = "transition"
            state_slot_id = (
                identity_factory.legacy_slot_id(decision.selected_slot_id)
                if decision.selected_slot_id is not None
                else old.state_slot_id
            )
            allocation = replace(
                old,
                valid_scope=valid_scope,
                state_slot_id=state_slot_id,
                write_mode=effective_write_mode,
                math_object_id=math_object_id,
                logical_state_key=decision.logical_state_key,
                typed_slot_id=decision.selected_slot_id,
                selected_version_id=selected_version_id,
                previous_version_id=decision.previous_version_id,
                computation_key=computation_key,
                source_version_ids=source_version_ids,
                allocation_action=decision.action,
                canonical_producer_call_id=decision.canonical_producer_call_id,
                allocation_reason_code=decision.reason_code,
                allocation_conflict_code=decision.conflict_code,
                transition_kind=decision.transition_kind,
                previous_write_step_id=decision.previous_producer_call_id,
            )
            allocations.append(allocation)
            produced[(call.call_id, old.return_name)] = allocation
            indexed = allocation_service.indexed_version(
                request,
                decision,
                produced_handle=allocation.state_handle or allocation.handle,
            )
            if indexed is not None:
                identity_index.register(
                    indexed,
                    legacy_slot_id=state_slot_id,
                )
        allocations = list(
            project_sibling_symbol_dependencies(
                tuple(specs.values()),
                tuple(allocations),
                capability_id=call.capability_id,
            )
        )
        for allocation in allocations:
            produced[(call.call_id, allocation.return_name)] = allocation
        result.append(
            replace(
                item,
                scope_id=scope_id,
                resolved_args=resolved_args,
                returns=tuple(allocations),
            )
        )
    return tuple(result), tuple(rewrites), tuple(issues)


def _rewrite_resolved_value_versions(
    value: ResolvedFunctionalValue,
    rewrites: Mapping[StateVersionId, StateVersionId],
) -> ResolvedFunctionalValue:
    version_id = value.state_version_id
    if version_id is None:
        return value
    target = _rewrite_version_id(version_id, rewrites)
    if target == version_id:
        return value
    return replace(
        value,
        state_version_id=target,
        typed_slot_id=target.slot_id,
        state_slot_id=StateIdentityFactory.legacy_slot_id(target.slot_id),
    )


def _rewrite_version_id(
    version_id: StateVersionId,
    rewrites: Mapping[StateVersionId, StateVersionId],
) -> StateVersionId:
    seen: set[StateVersionId] = set()
    current = version_id
    while current in rewrites and current not in seen:
        seen.add(current)
        current = rewrites[current]
    return current


def _version_rewrites_by_call(
    calls: Sequence[FunctionalCallReconciliation],
    rewrites: Sequence[StateVersionPlacementRewrite],
) -> dict[str, tuple[StateVersionPlacementRewrite, ...]]:
    call_by_target = {
        allocation.selected_version_id: call.call_id
        for call in calls
        for allocation in call.returns
        if allocation.selected_version_id is not None
    }
    result: dict[str, list[StateVersionPlacementRewrite]] = {}
    for rewrite in rewrites:
        call_id = call_by_target.get(rewrite.target_version_id)
        if call_id is not None:
            result.setdefault(call_id, []).append(rewrite)
    return {key: tuple(value) for key, value in result.items()}


def _typed_placement_mismatches(
    calls: Sequence[FunctionalCallReconciliation],
    *,
    decisions: Sequence[TypedCallPlacementDecision],
    registry: CanonicalHandleRegistry,
) -> tuple[dict[str, Any], ...]:
    """Audit final allocations against their authoritative placement."""

    decision_by_call = {
        item.canonical_call_id: item for item in decisions
    }
    mismatches: list[dict[str, Any]] = []
    for call in calls:
        decision = decision_by_call.get(call.call_id)
        if decision is None:
            mismatches.append(
                {
                    "call_id": call.call_id,
                    "reason_code": "typed_placement_decision_missing",
                    "message": (
                        "final canonical call has no typed placement decision"
                    ),
                    "execution_scope_id": call.scope_id,
                }
            )
            continue
        if call.scope_id != decision.execution_scope_id:
            mismatches.append(
                {
                    "call_id": call.call_id,
                    "reason_code": "execution_scope_drift",
                    "message": (
                        "final call scope differs from typed placement"
                    ),
                    "execution_scope_id": decision.execution_scope_id,
                    "actual_scope_id": call.scope_id,
                }
            )
        for allocation in call.returns:
            expected_scope = decision.return_scope_ids.get(
                allocation.return_name
            )
            if expected_scope != allocation.valid_scope:
                mismatches.append(
                    {
                        "call_id": call.call_id,
                        "return": allocation.return_name,
                        "reason_code": "return_scope_drift",
                        "message": (
                            "final return scope differs from typed placement"
                        ),
                        "execution_scope_id": decision.execution_scope_id,
                        "expected_scope_id": expected_scope,
                        "actual_scope_id": allocation.valid_scope,
                    }
                )
            if (
                allocation.typed_slot_id is not None
                and allocation.typed_slot_id.storage_scope_id
                != allocation.valid_scope
            ):
                mismatches.append(
                    {
                        "call_id": call.call_id,
                        "return": allocation.return_name,
                        "reason_code": "slot_scope_drift",
                        "message": (
                            "typed StateSlot storage scope differs from "
                            "return valid scope"
                        ),
                        "execution_scope_id": decision.execution_scope_id,
                        "slot_scope_id": (
                            allocation.typed_slot_id.storage_scope_id
                        ),
                        "return_scope_id": allocation.valid_scope,
                    }
                )
        for arg_name, values in call.resolved_args.items():
            for value in values:
                if visible_from_valid_scope(
                    value.valid_scope,
                    scope_id=call.scope_id,
                    registry=registry,
                ):
                    continue
                mismatches.append(
                    {
                        "call_id": call.call_id,
                        "arg": arg_name,
                        "reason_code": "input_version_not_visible",
                        "message": (
                            "typed input StateVersion is not visible at the "
                            "final execution scope"
                        ),
                        "execution_scope_id": call.scope_id,
                        "input_valid_scope_id": value.valid_scope,
                        "state_version_id": (
                            value.state_version_id.to_payload()
                            if value.state_version_id is not None
                            else None
                        ),
                    }
                )
    return tuple(mismatches)


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
        handle=allocation.state_handle or allocation.handle,
        runtime_type=allocation.runtime_type,
        valid_scope=allocation.valid_scope,
        state_slot_id=allocation.state_slot_id,
        source_call_id=source,
        return_name=allocation.return_name,
        object_ref=allocation.object_ref,
        dependency_object_refs=allocation.dependency_object_refs,
        free_symbol_refs=allocation.free_symbol_refs,
        source_state_slot_ids=allocation.source_state_slot_ids,
        provides_semantic_roles=allocation.provides_semantic_roles,
        lineage=allocation.lineage,
        math_object_id=allocation.math_object_id,
        logical_state_key=allocation.logical_state_key,
        typed_slot_id=allocation.typed_slot_id,
        state_version_id=allocation.selected_version_id,
    )


def _canonical_dependency_graph(
    plan: FunctionalPlan,
    reconciled: Mapping[str, FunctionalCallReconciliation],
    *,
    aliases: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    call_ids = {call.call_id for call in plan.calls}
    call_index = {
        call.call_id: index
        for index, call in enumerate(plan.calls)
    }
    producers_by_version: dict[StateVersionId, str] = {}
    producers_by_slot: dict[str, list[str]] = {}
    for producer_id, item in reconciled.items():
        for allocation in item.returns:
            if allocation.selected_version_id is not None:
                producers_by_version[
                    allocation.selected_version_id
                ] = producer_id
            producers_by_slot.setdefault(
                allocation.state_slot_id,
                [],
            ).append(producer_id)

    def producer_for_slot(slot_id: str, consumer_id: str) -> str | None:
        consumer_index = call_index[consumer_id]
        candidates = tuple(
            producer_id
            for producer_id in producers_by_slot.get(slot_id, ())
            if producer_id in call_index
            and call_index[producer_id] < consumer_index
        )
        return candidates[-1] if candidates else None

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
            dependencies.extend(
                producer_id
                for values in item.resolved_args.values()
                for value in values
                if value.state_version_id is not None
                if (
                    producer_id := producers_by_version.get(
                        value.state_version_id
                    )
                )
                is not None
            )
            dependencies.extend(
                producer_id
                for allocation in item.returns
                for version_id in (
                    (allocation.previous_version_id,)
                    if allocation.previous_version_id is not None
                    else ()
                )
                if (
                    producer_id := producers_by_version.get(version_id)
                )
                is not None
            )
            dependencies.extend(
                producer_id
                for values in item.resolved_args.values()
                for value in values
                if value.source_call_id is None
                and value.state_version_id is None
                for slot_id in (
                    *((value.state_slot_id,) if value.state_slot_id else ()),
                    *value.source_state_slot_ids,
                )
                if (
                    producer_id := producer_for_slot(
                        slot_id,
                        call.call_id,
                    )
                )
                is not None
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


def _post_placement_scope_issues(
    calls: Sequence[FunctionalCallReconciliation],
    *,
    registry: CanonicalHandleRegistry,
) -> tuple[FunctionalPlanIssue, ...]:
    """Report explicit DAG edges that placement could not make visible.

    A producer may be pinned to a child scope by one of its own inputs. In that
    case a sibling consumer cannot safely reuse the result. This is a
    repairable plan dependency error, not a projector configuration failure.
    """

    result: list[FunctionalPlanIssue] = []
    seen: set[tuple[str, str, str | None]] = set()
    for call in calls:
        for arg_name, values in call.resolved_args.items():
            for value in values:
                if (
                    value.source_call_id is None
                    or visible_from_valid_scope(
                        value.valid_scope,
                        scope_id=call.scope_id,
                        registry=registry,
                    )
                ):
                    continue
                key = (call.call_id, arg_name, value.source_call_id)
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.arg_scope_invisible",
                        (
                            f"call result {value.source_call_id}."
                            f"{value.return_name or 'result'} is not visible "
                            f"from {call.scope_id}"
                        ),
                        call_id=call.call_id,
                        scope_id=call.scope_id,
                        details={
                            "arg": arg_name,
                            "source_call_id": value.source_call_id,
                            "source_return": value.return_name,
                            "producer_valid_scope": value.valid_scope,
                            "consumer_execution_scope": call.scope_id,
                            "repair_call_ids": [
                                value.source_call_id,
                                call.call_id,
                            ],
                        },
                    )
                )
    return tuple(result)


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
    answer_target_scopes: Sequence[str],
    registry: CanonicalHandleRegistry,
) -> str:
    # A child-scoped answer object is a real write destination, not merely a
    # narrative owner. If every declared/consumer scope is compatible with
    # that destination, execute there so the runtime can materialize it. An
    # answer backed by a shared problem object does not pin execution.
    if answer_target_scopes:
        target_scope = _least_common_scope(answer_target_scopes, registry)
        declared_are_ancestors = all(
            scope in registry.ancestor_scopes(target_scope)
            for scope in declared_scopes
        )
        consumers_can_read = all(
            target_scope in registry.ancestor_scopes(scope)
            for scope in destination_scopes
        )
        answers_are_descendants = all(
            target_scope in registry.ancestor_scopes(scope)
            for scope in answer_scopes
        )
        if declared_are_ancestors and consumers_can_read and answers_are_descendants:
            return target_scope
    return _least_common_scope(
        (*declared_scopes, *destination_scopes, *answer_scopes),
        registry,
    )


def _answer_target_object_scopes(
    call: FunctionalCall,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """Return child/local scopes that physically own answer-bound objects."""

    scopes: list[str] = []
    for binding in call.return_bindings.values():
        if binding.kind != "answer":
            continue
        target = handle_registry.answer_target_handles.get(
            f"answer:{binding.ref}"
        )
        parsed = parse_scoped_non_answer_handle(target) if target else None
        if parsed is None:
            continue
        _kind, target_scope, _name = parsed
        if target_scope != "problem":
            scopes.append(target_scope)
    return tuple(dict.fromkeys(scopes))


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
