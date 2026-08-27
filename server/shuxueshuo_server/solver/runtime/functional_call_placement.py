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
    _may_merge_into_owner,
)
from shuxueshuo_server.solver.runtime.functional_plan_graph import (
    canonical_call_aliases as _canonical_aliases,
    canonical_call_id as _canonical,
    least_common_scope as _least_common_scope,
    rewrite_call_aliases as _rewrite_call_aliases,
)
from shuxueshuo_server.solver.runtime.functional_debug_aliases import (
    functional_call_local_debug_alias,
    functional_state_slot_debug_alias,
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
from shuxueshuo_server.solver.runtime.functional_symbol_identity import (
    symbol_ids_from_refs,
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
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    ComputationKey,
    FunctionalCallIdentityKey,
    IndexedStateVersion,
    LogicalReturnEffect,
    LogicalStateKey,
    MathObjectRegistry,
    RuntimeDestinationKey,
    StateAllocationRequest,
    StateAllocationService,
    StateEffectKey,
    StateIdentityFactory,
    StateIdentityIndex,
    StatePlacementMode,
    StateSlotId,
    StateVersionId,
    StateVersionPlacementRewrite,
    TypedCallPlacementDecision,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    SemanticRef,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    state_semantic_lineage,
)
from shuxueshuo_server.solver.utils import unique_ordered


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
    """Canonicalize equivalent calls before direct compilation.

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
        pinned_canonical_call_ids: Sequence[str] = (),
        pinned_execution_scopes: Mapping[str, str] | None = None,
        pinned_return_scopes: Mapping[str, Mapping[str, str]] | None = None,
        pinned_call_reconciliations: Mapping[
            str,
            FunctionalCallReconciliation,
        ] | None = None,
        scoped_semantic_owner_scopes: Mapping[str, str] | None = None,
    ) -> FunctionalCallPlacementResult:
        source_calls = {call.call_id: call for call in source_plan.calls}
        source_scopes = {
            call.call_id: scope.scope_id
            for scope in source_plan.scopes
            for call in scope.calls
        }
        call_by_id = {call.call_id: call for call in plan.calls}
        pinned_execution_scopes = dict(pinned_execution_scopes or {})
        pinned_return_scopes = {
            call_id: dict(scopes)
            for call_id, scopes in (pinned_return_scopes or {}).items()
        }
        pinned_call_reconciliations = dict(
            pinned_call_reconciliations or {}
        )
        scoped_semantic_owner_scopes = dict(
            scoped_semantic_owner_scopes or {}
        )
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
        typed_identity_keys = _typed_runtime_equivalence_candidate_keys(
            plan,
            reconciled_by_id=reconciled_by_id,
            catalog=catalog,
            aliases=aliases,
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
        semantic_return_dependencies = (
            _semantic_object_return_dependencies(
                canonical_plan,
                reconciled=canonical_reconciled,
                dependency_graph=canonical_dependencies,
                handle_registry=handle_registry,
                pinned_return_scopes=pinned_return_scopes,
            )
        )
        canonical_dependencies = _merge_dependency_graph(
            canonical_dependencies,
            {
                consumer_id: tuple(
                    producer_id
                    for producer_id, _return_name in dependencies
                )
                for consumer_id, dependencies in (
                    semantic_return_dependencies.items()
                )
            },
        )
        placement_dependencies = canonical_dependencies
        consumer_scopes = _dependency_consumer_scopes(
            placement_dependencies,
            call_scopes={
                call_id: tuple(source_scopes[item] for item in members)
                for call_id, members in groups.items()
            },
        )
        transitive_consumer_scopes = _transitive_dependency_consumer_scopes(
            placement_dependencies,
            call_scopes={
                call_id: tuple(source_scopes[item] for item in members)
                for call_id, members in groups.items()
            },
        )
        branch_private_scopes = _branch_private_state_storage_scopes(
            canonical_reconciled,
            consumer_scopes=transitive_consumer_scopes,
            registry=handle_registry,
            enforce_semantic_owner=bool(scoped_semantic_owner_scopes),
        )
        state_owner_scopes = _state_bearing_semantic_owner_scopes(
            canonical_reconciled,
            plan=canonical_plan,
            catalog=catalog,
            semantic_owner_scopes=scoped_semantic_owner_scopes,
        )
        restored_execution_scopes = {
            call_id: item.scope_id
            for call_id, item in pinned_call_reconciliations.items()
            if call_id in canonical_reconciled
        }
        restored_return_scopes = {
            call_id: {
                allocation.return_name: allocation.valid_scope
                for allocation in item.returns
            }
            for call_id, item in pinned_call_reconciliations.items()
            if call_id in canonical_reconciled
        }
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
            reconciliation = canonical_reconciled.get(call.call_id)
            isolated_scope = branch_private_scopes.get(
                call.call_id,
                _isolated_state_storage_scope(reconciliation),
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
            state_target_scopes = _state_target_object_scopes(
                reconciliation,
                base_identity_index=base_identity_index,
            )
            proposed = _call_execution_scope(
                declared_scopes=member_scopes,
                destination_scopes=destinations,
                answer_scopes=answer_destinations,
                answer_target_scopes=answer_target_scopes,
                state_target_scopes=state_target_scopes,
                registry=handle_registry,
            )
            pinned_execution_scope = pinned_execution_scopes.get(
                call.call_id
            )
            state_owner_scope = state_owner_scopes.get(call.call_id)
            if state_owner_scope is not None:
                proposed = state_owner_scope
                restored_scope = restored_execution_scopes.get(call.call_id)
                if (
                    restored_scope is not None
                    and restored_scope != state_owner_scope
                ):
                    issues.append(
                        _issue(
                            "functional_reconciliation",
                            "planner.retry_problem_source_binding_drift",
                            "restored state writer belongs to another scope",
                            call_id=call.call_id,
                            scope_id=state_owner_scope,
                            details={
                                "semantic_owner_scope": state_owner_scope,
                                "restored_execution_scope": restored_scope,
                            },
                        )
                    )
                if (
                    pinned_execution_scope is not None
                    and pinned_execution_scope != state_owner_scope
                ):
                    issues.append(
                        _issue(
                            "functional_reconciliation",
                            "planner.state_scope_authority_drift",
                            (
                                "checkpoint execution scope conflicts with "
                                "the state writer's semantic owner scope"
                            ),
                            call_id=call.call_id,
                            scope_id=state_owner_scope,
                            details={
                                "semantic_owner_scope": state_owner_scope,
                                "checkpoint_scope": pinned_execution_scope,
                            },
                        )
                    )
            elif call.call_id in restored_execution_scopes:
                proposed = restored_execution_scopes[call.call_id]
            elif pinned_execution_scope is not None:
                proposed = _scope_at_or_above_checkpoint(
                    proposed,
                    checkpoint_scope=pinned_execution_scope,
                    registry=handle_registry,
                )
            elif isolated_scope is not None:
                # The state remains private even if a pure computation could
                # execute at an ancestor. Its return scope is fixed below.
                proposed = isolated_scope
            requested_execution_scopes[call.call_id] = proposed

        provisional_execution_scopes = _close_execution_scope_dependencies(
            canonical_plan,
            reconciled=canonical_reconciled,
            dependency_graph=placement_dependencies,
            requested_scopes=requested_execution_scopes,
            declared_scopes={
                call_id: source_scopes[call_id]
                for call_id in canonical_calls
            },
            aliases=aliases,
            registry=handle_registry,
            fixed_scopes={
                **branch_private_scopes,
                **restored_execution_scopes,
                **state_owner_scopes,
            },
        )
        for call_id, scope_id in pinned_execution_scopes.items():
            if (
                call_id in provisional_execution_scopes
                and call_id not in state_owner_scopes
                and call_id not in restored_execution_scopes
            ):
                provisional_execution_scopes[call_id] = (
                    _scope_at_or_above_checkpoint(
                        provisional_execution_scopes[call_id],
                        checkpoint_scope=scope_id,
                        registry=handle_registry,
                    )
                )
        for call_id, scope_id in branch_private_scopes.items():
            if (
                call_id in provisional_execution_scopes
                and call_id not in pinned_execution_scopes
                and call_id not in restored_execution_scopes
                and call_id not in state_owner_scopes
            ):
                provisional_execution_scopes[call_id] = scope_id

        # A branch-private storage hint may narrow a pure value producer, but
        # it cannot override the semantic owner of a StateVersion writer.  The
        # latter is authored scope authority, not a placement heuristic.
        for call_id, scope_id in state_owner_scopes.items():
            if provisional_execution_scopes.get(call_id) != scope_id:
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "planner.state_scope_authority_drift",
                        "state writer execution scope differs from its semantic owner",
                        call_id=call_id,
                        scope_id=scope_id,
                        details={
                            "semantic_owner_scope": scope_id,
                            "execution_scope": provisional_execution_scopes.get(
                                call_id
                            ),
                        },
                    )
                )
                provisional_execution_scopes[call_id] = scope_id

        return_consumer_scopes = _return_consumer_scopes(
            canonical_plan,
            reconciled=canonical_reconciled,
            aliases=aliases,
            execution_scopes=provisional_execution_scopes,
            semantic_return_dependencies=semantic_return_dependencies,
        )
        return_scopes: dict[str, dict[str, str]] = {}
        for call in canonical_plan.calls:
            item = canonical_reconciled.get(call.call_id)
            if item is None:
                continue
            scopes_by_return: dict[str, str] = {}
            for allocation in item.returns:
                state_owner_scope = state_owner_scopes.get(call.call_id)
                restored_return_scope = restored_return_scopes.get(
                    call.call_id,
                    {},
                ).get(allocation.return_name)
                consumers = return_consumer_scopes.get(
                    (call.call_id, allocation.return_name),
                    (),
                )
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
                        *consumers,
                    ),
                    handle_registry,
                )
                state_target_scope = _allocation_target_object_scope(
                    allocation,
                    base_identity_index=base_identity_index,
                )
                if state_owner_scope is not None:
                    proposed = state_owner_scope
                elif restored_return_scope is not None:
                    proposed = restored_return_scope
                elif (
                    state_target_scope is not None
                    and all(
                        source_scopes[member_id]
                        in handle_registry.ancestor_scopes(state_target_scope)
                        for member_id in groups.get(
                            call.call_id,
                            (call.call_id,),
                        )
                    )
                ):
                    # An ancestor-declared call that first materializes a
                    # child-owned target must not publish that new state back
                    # to the ancestor. A call already declared below the
                    # object's origin keeps its narrower consumer-derived
                    # return scope.
                    proposed = state_target_scope
                if (
                    state_owner_scope is None
                    and restored_return_scope is None
                    and not _inputs_publishable_at_scope(
                        item.resolved_args.values(),
                        proposed,
                        aliases=aliases,
                        execution_scopes=provisional_execution_scopes,
                        registry=handle_registry,
                    )
                ):
                    # A return cannot be published above the visibility
                    # boundary of the exact StateVersions used to compute it.
                    # Downstream consumers do not widen those source versions.
                    proposed = provisional_execution_scopes[call.call_id]
                pinned_return_scope = pinned_return_scopes.get(
                    call.call_id,
                    {},
                ).get(allocation.return_name)
                if state_owner_scope is not None:
                    if (
                        pinned_return_scope is not None
                        and pinned_return_scope != state_owner_scope
                    ):
                        issues.append(
                            _issue(
                                "functional_reconciliation",
                                "planner.state_scope_authority_drift",
                                (
                                    "checkpoint return scope conflicts with "
                                    "the state writer's semantic owner scope"
                                ),
                                call_id=call.call_id,
                                scope_id=state_owner_scope,
                                details={
                                    "return": allocation.return_name,
                                    "semantic_owner_scope": state_owner_scope,
                                    "checkpoint_scope": pinned_return_scope,
                                },
                            )
                        )
                    proposed = state_owner_scope
                elif restored_return_scope is not None:
                    proposed = restored_return_scope
                elif (
                    allocation.allocation_action == "isolated"
                    and allocation.typed_slot_id is not None
                ):
                    proposed = allocation.typed_slot_id.storage_scope_id
                elif pinned_return_scope is not None:
                    proposed = _scope_at_or_above_checkpoint(
                        proposed,
                        checkpoint_scope=pinned_return_scope,
                        registry=handle_registry,
                    )
                elif call.call_id in branch_private_scopes:
                    proposed = branch_private_scopes[call.call_id]
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
            handle_registry=handle_registry,
            dependency_graph=canonical_dependencies,
        )
        canonical_dependencies = _canonical_dependency_graph(
            canonical_plan,
            {
                item.call_id: item
                for item in materialized_calls
            },
            aliases=aliases,
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
                dependency_graph=canonical_dependencies,
                execution_scopes=provisional_execution_scopes,
                return_scopes=return_scopes,
                pinned_return_scopes=pinned_return_scopes,
                pinned_call_reconciliations=pinned_call_reconciliations,
                identity_factory=identity_factory,
                identity_index=base_identity_index.clone(),
                allocation_service=allocation_service,
            )
            issues.extend(typed_finalization_issues)
        else:
            final_calls = materialized_calls
        scope_issues = _post_placement_scope_issues(
            final_calls,
            registry=handle_registry,
            declared_scopes={
                call_id: source_scopes[call_id]
                for call_id in canonical_calls
            },
            dependency_graph=canonical_dependencies,
        )
        issues.extend(scope_issues)
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
        placement_mismatches = _suppress_repairable_scope_mismatches(
            _typed_placement_mismatches(
                final_calls,
                decisions=typed_decisions,
                registry=handle_registry,
            ),
            scope_issues=scope_issues,
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


def _typed_runtime_equivalence_candidate_keys(
    plan: FunctionalPlan,
    *,
    reconciled_by_id: Mapping[str, FunctionalCallReconciliation],
    catalog: FunctionalCapabilityCatalog,
    aliases: Mapping[str, str],
) -> dict[str, FunctionalCallIdentityKey]:
    """Index possible reuse candidates without authorizing a call alias.

    Typed computation/effect identity is useful for allocation and placement,
    but it is not a semantic equality proof. The transactional interpreter
    must execute each candidate and compare its actual runtime result before a
    step can be merged or deleted.
    """

    result: dict[str, FunctionalCallIdentityKey] = {}
    for call in plan.calls:
        if call.call_id in aliases:
            continue
        reconciled = reconciled_by_id.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if reconciled is None or capability is None:
            continue
        identity_key = _typed_call_identity_key(
            reconciled,
            capability=capability,
            aliases=aliases,
            version_aliases={},
        )
        if identity_key is not None:
            result[call.call_id] = identity_key
    return result


def _canonicalize_typed_calls(
    plan: FunctionalPlan,
    *,
    source_scopes: Mapping[str, str],
    reconciled_by_id: Mapping[str, FunctionalCallReconciliation],
    catalog: FunctionalCapabilityCatalog,
    aliases: Mapping[str, str],
    groups: Mapping[str, tuple[str, ...]],
    handle_registry: CanonicalHandleRegistry,
    pinned_canonical_call_ids: frozenset[str] = frozenset(),
    pinned_return_scopes: (
        Mapping[str, Mapping[str, str]] | None
    ) = None,
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

    pinned_return_scopes = pinned_return_scopes or {}
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
    version_aliases: dict[StateVersionId, StateVersionId] = {}
    for duplicate_id, owner_id in aliases.items():
        _register_return_version_aliases(
            reconciled_by_id.get(duplicate_id),
            reconciled_by_id.get(owner_id),
            version_aliases=version_aliases,
        )

    ordered_calls = tuple(
        sorted(
            enumerate(plan.calls),
            key=lambda item: (
                item[1].call_id not in pinned_canonical_call_ids,
                item[0],
            ),
        )
    )
    for _, call in ordered_calls:
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
            version_aliases=version_aliases,
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
            owner_is_pinned = previous_id in pinned_canonical_call_ids
            owner_is_mutable = _may_merge_into_owner(
                owner_call_id=previous_id,
                current_call_id=call.call_id,
                pinned_canonical_call_ids=pinned_canonical_call_ids,
            )
            safe_pinned_alias_candidate = (
                owner_is_pinned
                and call.call_id not in pinned_canonical_call_ids
            )
            if not owner_is_mutable and not safe_pinned_alias_candidate:
                continue
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
            if safe_pinned_alias_candidate and not (
                _pinned_returns_visible_to_alias_members(
                    previous_id,
                    previous,
                    member_call_ids=candidate_members,
                    source_scopes=source_scopes,
                    pinned_return_scopes=pinned_return_scopes,
                    registry=handle_registry,
                )
            ):
                continue
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
            if not _resolved_arg_producers_compatible(
                previous.resolved_args,
                item.resolved_args,
                aliases=aliases,
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
                if safe_pinned_alias_candidate:
                    continue
            else:
                if safe_pinned_alias_candidate and (
                    merged_bindings
                    != effective_previous_call.return_bindings
                    or merged_expectations
                    != expectation_owner.return_expectations
                ):
                    continue
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
            _register_return_version_aliases(
                item,
                previous,
                version_aliases=version_aliases,
            )
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


def _pinned_returns_visible_to_alias_members(
    owner_call_id: str,
    owner: FunctionalCallReconciliation,
    *,
    member_call_ids: Sequence[str],
    source_scopes: Mapping[str, str],
    pinned_return_scopes: Mapping[str, Mapping[str, str]],
    registry: CanonicalHandleRegistry,
) -> bool:
    """Require a pinned result to be readable from every aliased call scope."""

    explicit_scopes = pinned_return_scopes.get(owner_call_id, {})
    for allocation in owner.returns:
        valid_scope = explicit_scopes.get(
            allocation.return_name,
            allocation.valid_scope,
        )
        if any(
            member_id in source_scopes
            and not visible_from_valid_scope(
                valid_scope,
                scope_id=source_scopes[member_id],
                registry=registry,
            )
            for member_id in member_call_ids
        ):
            return False
    return True


def _resolved_arg_producers_compatible(
    left: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    right: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    aliases: Mapping[str, str],
) -> bool:
    """Reject a merge when exact state inputs come from distinct producers.

    StateVersion identity remains the primary key. This guard catches the
    provisional-allocation window where two sibling transitions temporarily
    project to the same version before final placement replay. Once their
    producers are canonical aliases they remain mergeable.
    """

    for arg_name in set(left) & set(right):
        left_values = left[arg_name]
        right_values = right[arg_name]
        if len(left_values) != len(right_values):
            return False
        for left_value, right_value in zip(
            left_values,
            right_values,
            strict=True,
        ):
            if (
                left_value.source_call_id is None
                or right_value.source_call_id is None
            ):
                continue
            if _canonical(
                left_value.source_call_id,
                aliases,
            ) != _canonical(
                right_value.source_call_id,
                aliases,
            ):
                return False
    return True


def _typed_call_identity_key(
    reconciliation: FunctionalCallReconciliation,
    *,
    capability: FunctionalCapability,
    aliases: Mapping[str, str] | None = None,
    version_aliases: Mapping[StateVersionId, StateVersionId] | None = None,
) -> FunctionalCallIdentityKey | None:
    computation_keys = {
        _canonicalize_computation_key(
            item.computation_key,
            aliases=aliases or {},
            version_aliases=version_aliases or {},
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
    version_aliases: Mapping[StateVersionId, StateVersionId] | None = None,
) -> ComputationKey | None:
    if key is None:
        return key
    version_aliases = version_aliases or {}
    bindings = []
    for binding in key.arg_bindings:
        call_result_id = binding.call_result_id
        if call_result_id is not None and "." in call_result_id:
            call_id, return_name = call_result_id.split(".", 1)
            call_result_id = (
                f"{_canonical(call_id, aliases)}.{return_name}"
            )
        version_id = binding.version_id
        visited: set[StateVersionId] = set()
        while version_id in version_aliases and version_id not in visited:
            visited.add(version_id)
            version_id = version_aliases[version_id]
        bindings.append(
            replace(
                binding,
                version_id=version_id,
                call_result_id=call_result_id,
            )
        )
    return replace(key, arg_bindings=tuple(bindings))


def _register_return_version_aliases(
    duplicate: FunctionalCallReconciliation | None,
    owner: FunctionalCallReconciliation | None,
    *,
    version_aliases: dict[StateVersionId, StateVersionId],
) -> None:
    if duplicate is None or owner is None:
        return
    owner_returns = {item.return_name: item for item in owner.returns}
    for item in duplicate.returns:
        previous = owner_returns.get(item.return_name)
        if (
            item.selected_version_id is None
            or previous is None
            or previous.selected_version_id is None
        ):
            continue
        version_aliases[item.selected_version_id] = (
            previous.selected_version_id
        )


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
        if (
            left is None
            or right is None
            or _same_semantic_destination(left, right)
        ):
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


def _same_semantic_destination(
    left: SemanticRef,
    right: SemanticRef,
) -> bool:
    return (
        left.kind == right.kind
        and left.ref == right.ref
        and (
            left.value_type is None
            or right.value_type is None
            or left.value_type == right.value_type
        )
    )


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
            if _same_semantic_destination(left, right):
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
                free_symbol_ids=item.free_symbol_ids,
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
                if not _planned_state_publishable_at_scope(
                    value,
                    scope_id=scope_id,
                    registry=registry,
                ):
                    return False
    return True


def _planned_state_publishable_at_scope(
    value: ResolvedFunctionalValue,
    *,
    scope_id: str,
    registry: CanonicalHandleRegistry,
) -> bool:
    """Allow typed clustering before producer return-scope placement.

    Exact CallResult/StateVersion identity is already part of ComputationKey.
    A state produced in one branch may therefore be published to an ancestor
    when its MathObject originates there. Sibling-private MathObjects remain
    non-shareable.
    """

    if value.source_call_id is None:
        return False
    object_id = value.math_object_id
    if object_id is None and value.logical_state_key is not None:
        object_id = value.logical_state_key.object_id
    if object_id is None:
        return False
    return visible_from_valid_scope(
        object_id.origin_scope_id,
        scope_id=scope_id,
        registry=registry,
    )


def _inputs_publishable_at_scope(
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
                    valid_scope = _least_common_scope(
                        (valid_scope, execution_scope),
                        registry,
                    )
            if visible_from_valid_scope(
                valid_scope,
                scope_id=scope_id,
                registry=registry,
            ):
                continue
            # Producer placement has already reached its fixed point here.
            # MathObject origin alone cannot widen an exact StateVersion that
            # is still produced in a child branch.
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
    fixed_scopes: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Solve producer/consumer placement as a dependency-closure fixed point.

    A consumer may request an ancestor scope because sibling questions share
    it. The requested scope first propagates backwards through the complete
    producer graph. Once that fixed point is known, calls whose external
    inputs are not visible there fall back to their declared scope; that
    fallback then propagates forward to dependent consumers.
    """

    fixed_scopes = dict(fixed_scopes or {})
    result = {**requested_scopes, **fixed_scopes}
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
                if dependency_id in fixed_scopes:
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
            if call.call_id in fixed_scopes:
                fixed_scope = fixed_scopes[call.call_id]
                if result[call.call_id] != fixed_scope:
                    result[call.call_id] = fixed_scope
                    changed = True
                continue
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
    handle_registry: CanonicalHandleRegistry,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> tuple[FunctionalCallReconciliation, ...]:
    """Project final scopes to legacy handles without deciding typed identity."""

    semantic_by_ref = {(item.kind, item.ref): item for item in semantic_items}
    produced: dict[tuple[str, str], FunctionalReturnAllocation] = {}
    result: list[FunctionalCallReconciliation] = []
    factory = CanonicalStateHandleFactory()
    object_registry = MathObjectRegistry.from_sources(handle_registry)
    for call in _topological_calls(
        plan.calls,
        dependency_graph=dependency_graph,
    ):
        item = reconciled.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if item is None or capability is None:
            continue
        execution_scope = execution_scopes[call.call_id]
        resolved_args = {
            name: tuple(
                _rewrite_placed_resolved_value(
                    value,
                    produced=produced,
                    aliases=aliases,
                    consumer_scope_id=execution_scope,
                    registry=handle_registry,
                )
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
            if old.logical_state_key is not None:
                state_slot_id = functional_state_slot_debug_alias(
                    StateSlotId(old.logical_state_key, valid_scope)
                )
            elif object_ref is not None:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.state_identity_incomplete: "
                    f"call={call.call_id}, return={old.return_name}, "
                    "placed object return has no LogicalStateKey"
                )
            else:
                state_slot_id = (
                    functional_call_local_debug_alias(
                        scope_id=valid_scope,
                        call_id=call.call_id,
                        return_name=old.return_name,
                    )
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
                free_symbol_refs=return_free_symbol_refs(
                    spec.runtime_type,
                    resolved_args,
                    object_ref=object_ref,
                    ignored_input_args=(
                        spec.result_form_ignored_input_args
                    ),
                ),
                source_state_slot_ids=_argument_source_slots(resolved_args),
            )
            allocation = replace(
                allocation,
                free_symbol_ids=symbol_ids_from_refs(
                    allocation.free_symbol_refs,
                    registry=object_registry,
                ),
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
        allocations = _reproject_final_return_object_roles(
            allocations,
            specs=specs,
            resolved_args=resolved_args,
            object_registry=object_registry,
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
    dependency_graph: Mapping[str, tuple[str, ...]],
    execution_scopes: Mapping[str, str],
    return_scopes: Mapping[str, Mapping[str, str]],
    pinned_return_scopes: Mapping[str, Mapping[str, str]],
    pinned_call_reconciliations: Mapping[
        str,
        FunctionalCallReconciliation,
    ],
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

    ordered_calls = _topological_calls(
        plan.calls,
        dependency_graph=dependency_graph,
    )
    for call in ordered_calls:
        item = reconciled_by_id.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if item is None or capability is None:
            continue
        pinned = pinned_call_reconciliations.get(call.call_id)
        if pinned is not None:
            for allocation in pinned.returns:
                produced[(call.call_id, allocation.return_name)] = allocation
                _register_pinned_allocation(
                    allocation,
                    identity_index=identity_index,
                )
            result.append(pinned)
            continue
        scope_id = execution_scopes[call.call_id]
        resolved_args = {
            name: tuple(
                _rewrite_finalized_resolved_value(
                    value,
                    produced=produced,
                    version_map=version_map,
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
        final_object_refs = {
            old.return_name: _finalized_return_object_ref(
                old,
                return_spec=specs[old.return_name],
                computation_key=computation_key,
                identity_factory=identity_factory,
            )
            for old in item.returns
            if old.return_name in specs
        }
        logical_keys = {
            old.return_name: identity_factory.logical_key(
                object_ref=final_object_refs[old.return_name],
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
        finalized_producer_versions = {
            allocation.selected_version_id
            for allocation in produced.values()
            if allocation.selected_version_id is not None
        }
        source_version_ids = tuple(
            (
                version_id
                if version_id in finalized_producer_versions
                else _rewrite_version_id(version_id, version_map)
            )
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
            # State-bearing returns are owned by their authored semantic
            # scope. Checkpoints may pin a pure published value, but they may
            # never widen or relocate a StateVersion.
            if old.logical_state_key is not None and old.typed_slot_id is not None:
                storage_scope = valid_scope
            else:
                storage_scope = pinned_return_scopes.get(
                    call.call_id,
                    {},
                ).get(old.return_name, valid_scope)
            object_ref = final_object_refs[old.return_name]
            state_math_object_id = identity_factory.object_id(object_ref)
            projection_math_object_id = (
                state_math_object_id or old.math_object_id
            )
            runtime_destination = (
                RuntimeDestinationKey(
                    state_math_object_id,
                    spec.state_kind,
                    spec.runtime_type,
                )
                if state_math_object_id is not None
                else None
            )
            request = StateAllocationRequest(
                call_id=call.call_id,
                capability_id=call.capability_id,
                return_name=old.return_name,
                object_id=state_math_object_id,
                state_kind=spec.state_kind,
                runtime_type=spec.runtime_type,
                storage_scope_id=storage_scope,
                valid_scope_id=valid_scope,
                requested_write_mode=spec.write_mode,
                identity_policy=spec.identity_policy,
                is_shareable=capability.is_pure,
                computation_key=computation_key,
                state_effect_key=state_effect_key,
                source_version_ids=source_version_ids,
                free_symbol_refs=old.free_symbol_refs,
                free_symbol_ids=old.free_symbol_ids,
                runtime_destination=runtime_destination,
                result_form=call.return_expectations.get(old.return_name),
                allow_runtime_equivalence_probe=True,
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
                functional_state_slot_debug_alias(
                    decision.selected_slot_id
                )
                if decision.selected_slot_id is not None
                else old.state_slot_id
            )
            allocation = replace(
                old,
                valid_scope=valid_scope,
                state_slot_id=state_slot_id,
                object_ref=object_ref,
                write_mode=effective_write_mode,
                math_object_id=projection_math_object_id,
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
        allocations = _reproject_final_return_object_roles(
            allocations,
            specs=specs,
            resolved_args=resolved_args,
            object_registry=identity_factory.objects,
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


def _reproject_final_return_object_roles(
    allocations: Sequence[FunctionalReturnAllocation],
    *,
    specs: Mapping[str, Any],
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    object_registry: MathObjectRegistry,
) -> list[FunctionalReturnAllocation]:
    """Bind all declared roles to B2's final StateVersion allocations."""

    by_name = {item.return_name: item for item in allocations}
    result: list[FunctionalReturnAllocation] = []
    for allocation in allocations:
        return_spec = specs.get(allocation.return_name)
        projections = tuple(
            return_spec.object_role_projections
            if return_spec is not None
            else ()
        )
        if not projections:
            result.append(allocation)
            continue

        replaced_names = {projection.role for projection in projections}
        replaced_roles = tuple(
            role
            for role in allocation.lineage.object_roles
            if role.role in replaced_names
        )
        retained_roles = tuple(
            role
            for role in allocation.lineage.object_roles
            if role.role not in replaced_names
        )
        removed_versions = {
            version_id
            for role in replaced_roles
            for version_id in role.source_version_ids
        }
        removed_slots = {
            slot_id
            for role in replaced_roles
            for slot_id in role.source_state_slot_ids
        }
        projected_roles: list[StateObjectRoleBinding] = []
        for projection in projections:
            if projection.source_return is not None:
                source = by_name.get(projection.source_return)
                if source is None:
                    _raise_role_projection_incomplete(
                        allocation,
                        projection.role,
                        f"source_return={projection.source_return}",
                    )
                if projection.source_object_role is not None:
                    matches = tuple(
                        StateObjectRoleBinding(
                            role=projection.role,
                            object_refs=role.object_refs,
                            source_state_slot_ids=(
                                role.source_state_slot_ids
                            ),
                            source_handles=role.source_handles,
                            object_ids=role.object_ids,
                            source_version_ids=role.source_version_ids,
                            state_requirement=projection.state_requirement,
                        )
                        for role in source.lineage.object_roles
                        if role.role == projection.source_object_role
                    )
                    if not matches:
                        _raise_role_projection_incomplete(
                            allocation,
                            projection.role,
                            (
                                "source_return="
                                f"{projection.source_return}, "
                                "source_object_role="
                                f"{projection.source_object_role}"
                            ),
                        )
                    projected_roles.extend(matches)
                    continue
                projected_roles.append(
                    _role_from_final_return(
                        projection.role,
                        source,
                        state_requirement=projection.state_requirement,
                    )
                )
                continue
            if projection.source_arg is None:
                _raise_role_projection_incomplete(
                    allocation,
                    projection.role,
                    "missing source_return/source_arg declaration",
                )
            source_values = resolved_args.get(projection.source_arg, ())
            if not source_values:
                _raise_role_projection_incomplete(
                    allocation,
                    projection.role,
                    f"source_arg={projection.source_arg}",
                )
            if projection.source_object_role is not None:
                matches = tuple(
                    StateObjectRoleBinding(
                        role=projection.role,
                        object_refs=role.object_refs,
                        source_state_slot_ids=role.source_state_slot_ids,
                        source_handles=role.source_handles,
                        object_ids=role.object_ids,
                        source_version_ids=role.source_version_ids,
                        state_requirement=projection.state_requirement,
                    )
                    for value in source_values
                    for role in value.lineage.object_roles
                    if role.role == projection.source_object_role
                )
                if not matches:
                    _raise_role_projection_incomplete(
                        allocation,
                        projection.role,
                        (
                            f"source_arg={projection.source_arg}, "
                            "source_object_role="
                            f"{projection.source_object_role}"
                        ),
                    )
                projected_roles.extend(matches)
                continue
            projected_roles.extend(
                StateObjectRoleBinding(
                    role=projection.role,
                    object_refs=(
                        (value.object_ref,)
                        if value.object_ref is not None
                        else ()
                    ),
                    source_state_slot_ids=(
                        (value.state_slot_id,)
                        if value.state_slot_id is not None
                        else value.source_state_slot_ids
                    ),
                    source_handles=(value.handle,),
                    object_ids=(
                        (value.math_object_id,)
                        if value.math_object_id is not None
                        else ()
                    ),
                    source_version_ids=(
                        (value.state_version_id,)
                        if value.state_version_id is not None
                        else value.source_version_ids
                    ),
                    state_requirement=projection.state_requirement,
                )
                for value in source_values
            )

        projected_roles = [
            _resolve_projected_role_object_ids(
                role,
                object_registry=object_registry,
            )
            for role in projected_roles
        ]
        lineage = state_semantic_lineage(
            semantic_roles=allocation.lineage.semantic_roles,
            evidence_tags=allocation.lineage.evidence_tags,
            object_roles=(*retained_roles, *projected_roles),
            symbol_closures=allocation.lineage.symbol_closures,
            source_state_slot_ids=(
                *(
                    slot_id
                    for slot_id in allocation.lineage.source_state_slot_ids
                    if slot_id not in removed_slots
                ),
                *(
                    slot_id
                    for role in projected_roles
                    for slot_id in role.source_state_slot_ids
                ),
            ),
            source_version_ids=(
                *(
                    version_id
                    for version_id in allocation.lineage.source_version_ids
                    if version_id not in removed_versions
                ),
                *(
                    version_id
                    for role in projected_roles
                    for version_id in role.source_version_ids
                ),
            ),
            source_call_result_ids=(
                allocation.lineage.source_call_result_ids
            ),
            source_call_ids=allocation.lineage.source_call_ids,
        )
        result.append(replace(allocation, lineage=lineage))
    return result


def _resolve_projected_role_object_ids(
    role: StateObjectRoleBinding,
    *,
    object_registry: MathObjectRegistry,
) -> StateObjectRoleBinding:
    """Keep typed role identity while B2 reprojects final return lineage."""

    resolved_ids = list(role.object_ids)
    for object_ref in role.object_refs:
        object_id = object_registry.resolve(object_ref)
        if object_id is None:
            object_id = object_registry.register_handle(object_ref)
        if object_id is not None:
            resolved_ids.append(object_id)
    return replace(role, object_ids=unique_ordered(resolved_ids))


def _raise_role_projection_incomplete(
    allocation: FunctionalReturnAllocation,
    role: str,
    source: str,
) -> None:
    raise StrategyDraftValidationError(
        "planner_configuration_error: "
        "planner.state_identity_incomplete: "
        f"return={allocation.return_name}, role={role}, {source}"
    )


def _role_from_final_return(
    role: str,
    source: FunctionalReturnAllocation,
    *,
    state_requirement: str,
) -> StateObjectRoleBinding:
    return StateObjectRoleBinding(
        role=role,
        object_refs=(
            (source.object_ref,) if source.object_ref is not None else ()
        ),
        source_state_slot_ids=(
            (source.state_slot_id,)
            if source.state_slot_id is not None
            else ()
        ),
        source_handles=(source.state_handle or source.handle,),
        object_ids=(
            (source.math_object_id,)
            if source.math_object_id is not None
            else ()
        ),
        source_version_ids=(
            (source.selected_version_id,)
            if source.selected_version_id is not None
            else ()
        ),
        state_requirement=state_requirement,  # type: ignore[arg-type]
    )


def _finalized_return_object_ref(
    allocation: FunctionalReturnAllocation,
    *,
    return_spec: Any,
    computation_key: ComputationKey,
    identity_factory: StateIdentityFactory,
) -> str | None:
    """Rebuild derived identity from the final placed computation.

    Provisional reconciliation may later canonicalize an input producer or
    rewrite its StateVersion. A derived MathObject must follow the final
    ComputationKey; carrying the provisional object ref into B3 makes the same
    committed call acquire a different identity on retry.
    """

    if (
        return_spec.identity_policy != "derived_role"
        or return_spec.identity_arg is not None
        or allocation.logical_state_key is None
    ):
        return allocation.object_ref
    return (
        identity_factory.derived_computation_object_ref(
            computation_key=computation_key,
            semantic_role=(
                return_spec.equivalent_to
                or return_spec.semantic_role
                or return_spec.name
            ),
            runtime_type=return_spec.runtime_type,
        )
        or allocation.object_ref
    )


def _rewrite_finalized_resolved_value(
    value: ResolvedFunctionalValue,
    *,
    produced: Mapping[tuple[str, str], FunctionalReturnAllocation],
    version_map: Mapping[StateVersionId, StateVersionId],
) -> ResolvedFunctionalValue:
    """Prefer the final producer allocation over provisional version rewrites."""

    rewritten = _rewrite_resolved_value(
        value,
        produced=produced,
        aliases={},
    )
    if (
        value.source_call_id is not None
        and value.return_name is not None
        and (value.source_call_id, value.return_name) in produced
    ):
        return rewritten
    return _rewrite_resolved_value_versions(
        rewritten,
        version_map,
    )


def _topological_calls(
    calls: Sequence[FunctionalCall],
    *,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> tuple[FunctionalCall, ...]:
    """Order allocation replay by the complete typed dependency graph."""

    call_by_id = {call.call_id: call for call in calls}
    original_rank = {
        call.call_id: index for index, call in enumerate(calls)
    }
    pending = set(call_by_id)
    ordered: list[FunctionalCall] = []
    while pending:
        ready = min(
            (
                call_id
                for call_id in pending
                if not (
                    set(dependency_graph.get(call_id, ())) & pending
                )
            ),
            key=original_rank.__getitem__,
            default=None,
        )
        if ready is None:
            # Reconciliation reports cycles separately. Preserve a stable
            # remainder here so final allocation stays deterministic.
            ordered.extend(
                call_by_id[call_id]
                for call_id in sorted(
                    pending,
                    key=original_rank.__getitem__,
                )
            )
            break
        ordered.append(call_by_id[ready])
        pending.remove(ready)
    return tuple(ordered)


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
        state_slot_id=functional_state_slot_debug_alias(target.slot_id),
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
                and allocation.allocation_action != "reuse"
                and allocation.typed_slot_id.storage_scope_id
                != allocation.valid_scope
                and allocation.valid_scope
                not in registry.ancestor_scopes(
                    allocation.typed_slot_id.storage_scope_id
                )
            ):
                mismatches.append(
                    {
                        "call_id": call.call_id,
                        "return": allocation.return_name,
                        "reason_code": "slot_scope_drift",
                        "message": (
                            "typed StateSlot cannot publish to the declared "
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
        free_symbol_ids=allocation.free_symbol_ids,
        source_state_slot_ids=allocation.source_state_slot_ids,
        provides_semantic_roles=allocation.provides_semantic_roles,
        lineage=allocation.lineage,
        math_object_id=allocation.math_object_id,
        logical_state_key=allocation.logical_state_key,
        typed_slot_id=allocation.typed_slot_id,
        state_version_id=allocation.selected_version_id,
        source_version_ids=allocation.source_version_ids,
    )


def _rewrite_placed_resolved_value(
    value: ResolvedFunctionalValue,
    *,
    produced: Mapping[tuple[str, str], FunctionalReturnAllocation],
    aliases: Mapping[str, str],
    consumer_scope_id: str,
    registry: CanonicalHandleRegistry | None,
) -> ResolvedFunctionalValue:
    """Bind a semantic object read to the final visible producer version."""

    rewritten = _rewrite_resolved_value(
        value,
        produced=produced,
        aliases=aliases,
    )
    if (
        rewritten.state_version_id is not None
        or rewritten.source_call_id is not None
        or rewritten.math_object_id is None
        or rewritten.runtime_type in {"PointRef", "Symbol", "Function"}
        or registry is None
    ):
        return rewritten
    candidates = [
        allocation
        for allocation in produced.values()
        if allocation.selected_version_id is not None
        and allocation.math_object_id == rewritten.math_object_id
        and runtime_type_compatible(
            rewritten.runtime_type,
            allocation.runtime_type,
        )
        and visible_from_valid_scope(
            allocation.valid_scope,
            scope_id=consumer_scope_id,
            registry=registry,
        )
    ]
    if not candidates:
        return rewritten
    # ``produced`` follows final topological call order. The last compatible
    # allocation is therefore the exact state visible at this call boundary.
    selected = candidates[-1]
    return ResolvedFunctionalValue(
        handle=selected.state_handle or selected.handle,
        runtime_type=selected.runtime_type,
        valid_scope=selected.valid_scope,
        state_slot_id=selected.state_slot_id,
        source_call_id=selected.call_id,
        return_name=selected.return_name,
        object_ref=selected.object_ref,
        dependency_object_refs=selected.dependency_object_refs,
        free_symbol_refs=selected.free_symbol_refs,
        source_state_slot_ids=selected.source_state_slot_ids,
        provides_semantic_roles=selected.provides_semantic_roles,
        lineage=selected.lineage,
        math_object_id=selected.math_object_id,
        logical_state_key=selected.logical_state_key,
        typed_slot_id=selected.typed_slot_id,
        state_version_id=selected.selected_version_id,
        source_version_ids=selected.source_version_ids,
    )


def _canonical_dependency_graph(
    plan: FunctionalPlan,
    reconciled: Mapping[str, FunctionalCallReconciliation],
    *,
    aliases: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    call_ids = {call.call_id for call in plan.calls}
    producers_by_version: dict[StateVersionId, str] = {}
    for producer_id, item in reconciled.items():
        for allocation in item.returns:
            if allocation.selected_version_id is not None:
                canonical_producer_id = (
                    allocation.canonical_producer_call_id
                    if allocation.allocation_action == "reuse"
                    and allocation.canonical_producer_call_id is not None
                    else producer_id
                )
                producers_by_version.setdefault(
                    allocation.selected_version_id,
                    canonical_producer_id,
                )

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
                if value.source_call_id is None
                for version_id in unique_ordered(
                    (value.state_version_id,)
                    if value.state_version_id is not None
                    else value.source_version_ids
                )
                if (
                    producer_id := producers_by_version.get(version_id)
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


def _transitive_dependency_consumer_scopes(
    dependency_graph: Mapping[str, tuple[str, ...]],
    *,
    call_scopes: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Collect every downstream scope reached through the call DAG.

    Independent sibling writers stay isolated, but the first materialized
    state may need to be published to an ancestor because one of its
    consumers is itself shared by later Goals. Direct consumers alone miss
    that case and can pin a producer below the scope where its dependent call
    executes.
    """

    consumers_by_producer: dict[str, list[str]] = {}
    for consumer_id, dependency_ids in dependency_graph.items():
        for dependency_id in dependency_ids:
            consumers_by_producer.setdefault(dependency_id, []).append(
                consumer_id
            )

    result: dict[str, tuple[str, ...]] = {}
    for producer_id in call_scopes:
        pending = list(consumers_by_producer.get(producer_id, ()))
        seen: set[str] = set()
        scopes: list[str] = []
        while pending:
            consumer_id = pending.pop()
            if consumer_id in seen:
                continue
            seen.add(consumer_id)
            scopes.extend(call_scopes.get(consumer_id, ()))
            pending.extend(consumers_by_producer.get(consumer_id, ()))
        if scopes:
            result[producer_id] = tuple(dict.fromkeys(scopes))
    return result


def _return_consumer_scopes(
    plan: FunctionalPlan,
    *,
    reconciled: Mapping[str, FunctionalCallReconciliation],
    aliases: Mapping[str, str],
    execution_scopes: Mapping[str, str],
    semantic_return_dependencies: Mapping[
        str,
        tuple[tuple[str, str], ...],
    ] | None = None,
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Collect the exact consumers of each public return.

    A call may execute in a child scope because its inputs are local while a
    proven result is intentionally reused by a later sibling. That result is
    exported to the consumers' least common scope without hoisting the call or
    any of its inputs.
    """

    result: dict[tuple[str, str], list[str]] = {}
    semantic_return_dependencies = semantic_return_dependencies or {}
    for consumer in plan.calls:
        consumer_scope = execution_scopes[consumer.call_id]
        refs = [
            ref
            for values in consumer.args.values()
            for ref in values
            if isinstance(ref, CallResultRef)
        ]
        item = reconciled.get(consumer.call_id)
        if item is not None:
            refs.extend(
                CallResultRef(
                    from_call=value.source_call_id,
                    return_name=value.return_name,
                )
                for values in item.resolved_args.values()
                for value in values
                if value.source_call_id is not None
                and value.return_name is not None
            )
        for ref in refs:
            producer = _canonical(ref.from_call, aliases)
            key = (producer, ref.return_name)
            result.setdefault(key, []).append(consumer_scope)
        for producer_id, return_name in semantic_return_dependencies.get(
            consumer.call_id,
            (),
        ):
            result.setdefault(
                (producer_id, return_name),
                [],
            ).append(consumer_scope)
    return {
        key: tuple(dict.fromkeys(scopes))
        for key, scopes in result.items()
    }


def _semantic_object_return_dependencies(
    plan: FunctionalPlan,
    *,
    reconciled: Mapping[str, FunctionalCallReconciliation],
    dependency_graph: Mapping[str, tuple[str, ...]],
    handle_registry: CanonicalHandleRegistry,
    pinned_return_scopes: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Resolve unique materialized SemanticRef reads without wire-order bias."""

    pinned_return_scopes = pinned_return_scopes or {}
    producers = tuple(
        (call.call_id, allocation)
        for call in plan.calls
        for item in (reconciled.get(call.call_id),)
        if item is not None
        for allocation in item.returns
        if allocation.math_object_id is not None
        and allocation.selected_version_id is not None
    )
    producer_by_version = {
        allocation.selected_version_id: allocation
        for _producer_id, allocation in producers
        if allocation.selected_version_id is not None
    }

    def publishable_at_scope(
        producer_id: str,
        allocation: FunctionalReturnAllocation,
        *,
        scope_id: str,
        visited: frozenset[object] = frozenset(),
    ) -> bool:
        version_id = allocation.selected_version_id
        if version_id is not None and version_id in visited:
            return False
        effective_valid_scope = pinned_return_scopes.get(
            producer_id,
            {},
        ).get(
            allocation.return_name,
            allocation.valid_scope,
        )
        if visible_from_valid_scope(
            effective_valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        ):
            return True
        if allocation.allocation_action == "isolated":
            return False
        next_visited = (
            visited | {version_id}
            if version_id is not None
            else visited
        )
        for source_version_id in allocation.source_version_ids:
            source = producer_by_version.get(source_version_id)
            if source is not None:
                if not publishable_at_scope(
                    source.call_id,
                    source,
                    scope_id=scope_id,
                    visited=next_visited,
                ):
                    return False
                continue
            if not visible_from_valid_scope(
                source_version_id.slot_id.storage_scope_id,
                scope_id=scope_id,
                registry=handle_registry,
            ):
                return False
        return True

    result: dict[str, list[tuple[str, str]]] = {}
    for consumer in plan.calls:
        item = reconciled.get(consumer.call_id)
        if item is None:
            continue
        for values in item.resolved_args.values():
            for value in values:
                if (
                    value.state_version_id is not None
                    or value.source_call_id is not None
                    or value.math_object_id is None
                    or value.runtime_type
                    in {"PointRef", "Symbol", "Function"}
                ):
                    continue
                ancestors = handle_registry.ancestor_scopes(
                    item.scope_id,
                )
                viable_candidates = tuple(
                    (producer_id, allocation)
                    for producer_id, allocation in producers
                    if producer_id != consumer.call_id
                    and allocation.math_object_id == value.math_object_id
                    and runtime_type_compatible(
                        value.runtime_type,
                        allocation.runtime_type,
                    )
                )
                visible_candidates = tuple(
                    (producer_id, allocation)
                    for producer_id, allocation in viable_candidates
                    if pinned_return_scopes.get(
                        producer_id,
                        {},
                    ).get(
                        allocation.return_name,
                        allocation.valid_scope,
                    )
                    in ancestors
                )
                publishable_candidates = tuple(
                    (producer_id, allocation)
                    for producer_id, allocation in viable_candidates
                    if publishable_at_scope(
                        producer_id,
                        allocation,
                        scope_id=_least_common_scope(
                            (
                                pinned_return_scopes.get(
                                    producer_id,
                                    {},
                                ).get(
                                    allocation.return_name,
                                    allocation.valid_scope,
                                ),
                                item.scope_id,
                            ),
                            handle_registry,
                        ),
                    )
                )
                closest_rank = min(
                    (
                        ancestors.index(
                            pinned_return_scopes.get(
                                producer_id,
                                {},
                            ).get(
                                allocation.return_name,
                                allocation.valid_scope,
                            )
                        )
                        for producer_id, allocation in visible_candidates
                    ),
                    default=None,
                )
                candidates = tuple(
                    (producer_id, allocation.return_name)
                    for producer_id, allocation in (
                        visible_candidates or publishable_candidates
                    )
                    if (
                        not visible_candidates
                        or (
                            closest_rank is not None
                            and ancestors.index(
                                pinned_return_scopes.get(
                                    producer_id,
                                    {},
                                ).get(
                                    allocation.return_name,
                                    allocation.valid_scope,
                                )
                            )
                            == closest_rank
                        )
                    )
                )
                maximal_candidates = tuple(
                    candidate
                    for candidate in candidates
                    if not any(
                        other[0] != candidate[0]
                        and _call_depends_on(
                            other[0],
                            candidate[0],
                            dependency_graph=dependency_graph,
                        )
                        for other in candidates
                    )
                )
                if len(maximal_candidates) != 1:
                    continue
                if _call_depends_on(
                    maximal_candidates[0][0],
                    consumer.call_id,
                    dependency_graph=dependency_graph,
                ):
                    continue
                result.setdefault(consumer.call_id, []).append(
                    maximal_candidates[0]
                )
    return {
        call_id: tuple(dict.fromkeys(dependencies))
        for call_id, dependencies in result.items()
    }


def _call_depends_on(
    call_id: str,
    dependency_id: str,
    *,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> bool:
    pending = [call_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == dependency_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(dependency_graph.get(current, ()))
    return False


def _merge_dependency_graph(
    primary: Mapping[str, tuple[str, ...]],
    additional: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    return {
        call_id: tuple(
            dict.fromkeys(
                (
                    *primary.get(call_id, ()),
                    *additional.get(call_id, ()),
                )
            )
        )
        for call_id in dict.fromkeys((*primary, *additional))
    }


def _post_placement_scope_issues(
    calls: Sequence[FunctionalCallReconciliation],
    *,
    registry: CanonicalHandleRegistry,
    declared_scopes: Mapping[str, str] | None = None,
    dependency_graph: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[FunctionalPlanIssue, ...]:
    """Report candidate dependencies that placement could not make visible.

    A producer may be pinned to a child scope by one of its own inputs. In that
    case a sibling consumer cannot safely reuse the result. This is a
    repairable plan dependency error, not a planner configuration failure.

    Resolver-owned inputs may only become materialized after the first scope
    fixed point. If a downstream publication hoists such a call above the
    input's valid scope, report the same retryable issue even though the input
    has no ``source_call_id``. The call must remain invalid; the repair is to
    split the common ancestor computation from child-private evaluation.
    """

    declared_scopes = dict(declared_scopes or {})
    dependency_graph = dict(dependency_graph or {})
    result: list[FunctionalPlanIssue] = []
    seen: set[tuple[str, str, str | None]] = set()
    for call in calls:
        for arg_name, values in call.resolved_args.items():
            for value in values:
                if visible_from_valid_scope(
                    value.valid_scope,
                    scope_id=call.scope_id,
                    registry=registry,
                ):
                    continue
                declared_scope = declared_scopes.get(
                    call.call_id,
                    call.scope_id,
                )
                was_hoisted = declared_scope != call.scope_id
                if value.source_call_id is None and not was_hoisted:
                    continue
                key = (call.call_id, arg_name, value.source_call_id)
                if key in seen:
                    continue
                seen.add(key)
                if value.source_call_id is not None:
                    repair_call_ids = [
                        value.source_call_id,
                        call.call_id,
                    ]
                    message = (
                        f"call result {value.source_call_id}."
                        f"{value.return_name or 'result'} is not visible "
                        f"from {call.scope_id}"
                    )
                    placement_reason = "cross_scope_call_result_invisible"
                else:
                    repair_call_ids = list(
                        _mixed_scope_placement_repair_cone(
                            call.call_id,
                            calls=calls,
                            declared_scopes=declared_scopes,
                            dependency_graph=dependency_graph,
                            registry=registry,
                        )
                    )
                    message = (
                        f"call {call.call_id} was moved from "
                        f"{declared_scope} to {call.scope_id}, but argument "
                        f"{arg_name} is only visible from "
                        f"{value.valid_scope}"
                    )
                    placement_reason = "private_input_blocks_ancestor_execution"
                result.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.arg_scope_invisible",
                        message,
                        call_id=call.call_id,
                        scope_id=call.scope_id,
                        details={
                            "arg": arg_name,
                            "source_call_id": value.source_call_id,
                            "source_return": value.return_name,
                            "producer_valid_scope": value.valid_scope,
                            "input_valid_scope": value.valid_scope,
                            "declared_scope_id": declared_scope,
                            "consumer_execution_scope": call.scope_id,
                            "placement_reason": placement_reason,
                            "repair_call_ids": repair_call_ids,
                            "repair_guidance": (
                                "Keep child-private inputs and their evaluation "
                                "in the child scope. Produce any state needed by "
                                "multiple sibling scopes in their common ancestor "
                                "without child-private arguments, then evaluate it "
                                "separately in each child scope."
                            ),
                        },
                    )
                )
    return tuple(result)


def _mixed_scope_placement_repair_cone(
    root_call_id: str,
    *,
    calls: Sequence[FunctionalCallReconciliation],
    declared_scopes: Mapping[str, str],
    dependency_graph: Mapping[str, tuple[str, ...]],
    registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """Return the publication chain that made a private input unsafe.

    Keep ordinary same-branch consumers out of the diagnostic cone. Include
    hoisted dependents that propagated ancestor placement and the first
    consumer in another branch; those are the calls the planner may need to
    split or reconnect.
    """

    call_by_id = {call.call_id: call for call in calls}
    consumers: dict[str, list[str]] = {}
    for consumer_id, dependencies in dependency_graph.items():
        for dependency_id in dependencies:
            consumers.setdefault(dependency_id, []).append(consumer_id)

    root_declared_scope = declared_scopes.get(
        root_call_id,
        call_by_id[root_call_id].scope_id,
    )
    result = [root_call_id]
    pending = list(consumers.get(root_call_id, ()))
    visited: set[str] = set()
    while pending:
        consumer_id = pending.pop(0)
        if consumer_id in visited:
            continue
        visited.add(consumer_id)
        consumer = call_by_id.get(consumer_id)
        if consumer is None:
            continue
        consumer_declared_scope = declared_scopes.get(
            consumer_id,
            consumer.scope_id,
        )
        stays_in_root_branch = root_declared_scope in registry.ancestor_scopes(
            consumer_declared_scope
        )
        was_hoisted = consumer.scope_id != consumer_declared_scope
        if not stays_in_root_branch or was_hoisted:
            result.append(consumer_id)
        if was_hoisted:
            pending.extend(consumers.get(consumer_id, ()))
    return tuple(dict.fromkeys(result))


def _suppress_repairable_scope_mismatches(
    mismatches: Sequence[dict[str, Any]],
    *,
    scope_issues: Sequence[FunctionalPlanIssue],
) -> tuple[dict[str, Any], ...]:
    """Do not classify an invalid candidate edge as planner drift.

    ``functional.arg_scope_invisible`` already tells the LLM how to reconnect
    an explicit cross-scope dependency. The typed audit should still report
    genuine placement inconsistencies, but must not turn that same repairable
    candidate error into a non-retryable configuration failure.
    """

    repairable_inputs = {
        (issue.call_id, issue.details.get("arg"))
        for issue in scope_issues
        if (
            issue.code == "functional.arg_scope_invisible"
            and issue.call_id is not None
            and issue.details is not None
        )
    }
    return tuple(
        item
        for item in mismatches
        if not (
            item.get("reason_code") == "input_version_not_visible"
            and (item.get("call_id"), item.get("arg"))
            in repairable_inputs
        )
    )


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
    state_target_scopes: Sequence[str],
    registry: CanonicalHandleRegistry,
) -> str:
    # A child-scoped answer object is a real write destination, not merely a
    # narrative owner. If every declared/consumer scope is compatible with
    # that destination, execute there so the runtime can materialize it. An
    # answer backed by a shared problem object does not pin execution.
    target_scopes = tuple(
        dict.fromkeys((*answer_target_scopes, *state_target_scopes))
    )
    if target_scopes:
        target_scope = _least_common_scope(target_scopes, registry)
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


def _scope_at_or_above_checkpoint(
    proposed_scope: str,
    *,
    checkpoint_scope: str,
    registry: CanonicalHandleRegistry,
) -> str:
    """Keep a committed placement stable while allowing safe publication.

    B4 pins the computation and version chain, not a narrower presentation
    boundary. B2 may therefore expand execution/return visibility to an
    ancestor when new sibling consumers require the same committed result.
    Descendant or sibling movement would narrow/change the checkpoint and is
    rejected by retaining the checkpoint scope.
    """

    if proposed_scope in registry.ancestor_scopes(checkpoint_scope):
        return proposed_scope
    return checkpoint_scope


def _state_target_object_scopes(
    reconciliation: FunctionalCallReconciliation | None,
    *,
    base_identity_index: StateIdentityIndex | None,
) -> tuple[str, ...]:
    """Return non-root scopes required by target-object state writes.

    A call declared in an ancestor may create a child-owned MathObject. The
    typed object origin is then the lowest legal execution boundary; compiling
    at the ancestor would leave an identity-only runtime input without a
    visible binding.
    """

    if reconciliation is None:
        return ()
    return tuple(
        dict.fromkeys(
            scope
            for allocation in reconciliation.returns
            for scope in (
                _allocation_target_object_scope(
                    allocation,
                    base_identity_index=base_identity_index,
                ),
            )
            if scope is not None
        )
    )


def _allocation_target_object_scope(
    allocation: FunctionalReturnAllocation,
    *,
    base_identity_index: StateIdentityIndex | None,
) -> str | None:
    object_id = allocation.math_object_id
    logical_key = allocation.logical_state_key
    if (
        allocation.identity_policy != "target_object"
        or object_id is None
        or object_id.origin_scope_id == "problem"
    ):
        return None
    if (
        base_identity_index is not None
        and logical_key is not None
        and base_identity_index.versions_for(logical_key)
    ):
        return None
    return object_id.origin_scope_id


def _isolated_state_storage_scope(
    reconciliation: FunctionalCallReconciliation | None,
) -> str | None:
    """Return the sole storage boundary imposed by provisional isolation."""

    if reconciliation is None:
        return None
    scopes = {
        allocation.typed_slot_id.storage_scope_id
        for allocation in reconciliation.returns
        if allocation.allocation_action == "isolated"
        and allocation.typed_slot_id is not None
    }
    return next(iter(scopes)) if len(scopes) == 1 else None


def _branch_private_state_storage_scopes(
    reconciled: Mapping[str, FunctionalCallReconciliation],
    *,
    consumer_scopes: Mapping[str, tuple[str, ...]] | None = None,
    registry: CanonicalHandleRegistry | None = None,
    enforce_semantic_owner: bool = True,
) -> dict[str, str]:
    """Pin every independent sibling writer to its allocated owner scope.

    B1 labels the first branch writer ``create`` and later sibling writers
    ``isolated``. Looking only for ``isolated`` leaves the first writer free to
    hoist and can turn two valid sibling states into overlapping writers.
    Consumer scopes never widen storage authority.
    """

    by_state: dict[
        LogicalStateKey,
        list[tuple[str, FunctionalReturnAllocation]],
    ] = {}
    for call_id, item in reconciled.items():
        for allocation in item.returns:
            if (
                allocation.logical_state_key is None
                or allocation.typed_slot_id is None
                or allocation.allocation_action not in {"create", "isolated"}
            ):
                continue
            by_state.setdefault(allocation.logical_state_key, []).append(
                (call_id, allocation)
            )

    consumer_scopes = consumer_scopes or {}
    scopes_by_call: dict[str, set[str]] = {}
    for allocations in by_state.values():
        storage_scopes = {
            allocation.typed_slot_id.storage_scope_id
            for _, allocation in allocations
        }
        version_ids = {
            allocation.selected_version_id
            for _, allocation in allocations
            if allocation.selected_version_id is not None
        }
        if len(storage_scopes) <= 1 or len(version_ids) <= 1:
            continue
        for call_id, allocation in allocations:
            storage_scope = allocation.typed_slot_id.storage_scope_id
            if (
                not enforce_semantic_owner
                and registry is not None
                and allocation.allocation_action != "isolated"
            ):
                storage_scope = _least_common_scope(
                    (
                        storage_scope,
                        *consumer_scopes.get(call_id, ()),
                    ),
                    registry,
                )
            scopes_by_call.setdefault(call_id, set()).add(
                storage_scope
            )
    return {
        call_id: next(iter(scopes))
        for call_id, scopes in scopes_by_call.items()
        if len(scopes) == 1
    }


def _state_bearing_semantic_owner_scopes(
    reconciled: Mapping[str, FunctionalCallReconciliation],
    *,
    semantic_owner_scopes: Mapping[str, str],
    plan: FunctionalPlan | None = None,
    catalog: FunctionalCapabilityCatalog | None = None,
) -> dict[str, str]:
    """Return the immutable semantic owner for every StateVersion writer.

    B2 may place pure computations at an LCA, but a call that allocates a
    logical state belongs to the scope where the scoped Plan authored it. Its
    execution, storage, and publication scopes cannot be widened by consumers.
    """

    result: dict[str, str] = {}
    calls = (
        tuple((call.call_id, call.capability_id) for call in plan.calls)
        if plan is not None
        else tuple((call_id, None) for call_id in reconciled)
    )
    for call_id, capability_id in calls:
        if call_id not in semantic_owner_scopes:
            continue
        item = reconciled.get(call_id)
        capability = (
            catalog.get(capability_id)
            if catalog is not None and capability_id is not None
            else None
        )
        writes_state = item is not None and any(
            allocation.logical_state_key is not None
            and allocation.typed_slot_id is not None
            for allocation in item.returns
        )
        if capability is not None:
            writes_state = writes_state or any(
                output.identity_policy != "value_only"
                for output in capability.returns
            )
        if writes_state:
            result[call_id] = semantic_owner_scopes[call_id]
    return result


def _register_pinned_allocation(
    allocation: FunctionalReturnAllocation,
    *,
    identity_index: StateIdentityIndex,
) -> None:
    """Restore one checkpointed version into the attempt-local identity index."""

    if allocation.selected_version_id is None:
        return
    identity_index.register(
        IndexedStateVersion(
            version_id=allocation.selected_version_id,
            valid_scope_id=allocation.valid_scope,
            producer_call_id=allocation.call_id,
            produced_handle=allocation.state_handle or allocation.handle,
            computation_key=allocation.computation_key,
            free_symbol_refs=allocation.free_symbol_refs,
            free_symbol_ids=allocation.free_symbol_ids,
            previous_version_id=allocation.previous_version_id,
            source_version_ids=allocation.source_version_ids,
        )
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
