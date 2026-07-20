"""Context reconciliation and canonical StepIntent projection for FunctionalPlan."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.condition_roles import (
    ConditionRoleResolutionError,
    ConditionRoleResolver,
)
from shuxueshuo_server.solver.runtime.context_closure import (
    CONDITION_OBJECT_ROLES_RESOLVER,
    PATH_REDUCTION_ROLES_RESOLVER,
    ContextClosureResolverSpec,
    context_closure_resolver,
    midpoint_endpoint_position,
)
from shuxueshuo_server.solver.runtime.binding_selector_semantics import (
    selector_semantics,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
    FunctionalPlanElaborationResult,
    FunctionalPlanElaborator,
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_liveness import (
    FunctionalCallLivenessAnalyzer,
)
from shuxueshuo_server.solver.runtime.functional_reconciliation_validators import (
    functional_reconciliation_issues,
)
from shuxueshuo_server.solver.runtime.functional_symbol_flow import (
    return_free_symbol_refs,
)
from shuxueshuo_server.solver.runtime.functional_plan_graph import (
    least_common_scope as _least_common_scope,
    topological_scoped_calls,
    topologically_order_plan,
)
from shuxueshuo_server.solver.runtime.functional_call_placement import (
    FunctionalCallPlacementService,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    CanonicalStateHandleFactory,
    FunctionalAggregation,
    FunctionalCapability,
    FunctionalCall,
    FunctionalCallReport,
    FunctionalCapabilityReturn,
    FunctionalCallReconciliation,
    FunctionalPlan,
    FunctionalPlanIssue,
    FunctionalPlanReconciliationResult,
    FunctionalProjectionEntry,
    FunctionalRef,
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
    _issue,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import visible_from_valid_scope
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.path_reduction_roles import (
    PathReductionRoleError,
    PathReductionRoleResolver,
)
from shuxueshuo_server.solver.runtime.planner_state_context import PlannerStateContext
from shuxueshuo_server.solver.runtime.semantic_reads import SemanticReadCatalogItem
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    SemanticRef,
    StepIntent,
    StepIntentDraft,
    StepIntentScope,
    answer_output_type_compatible,
    answer_value_type_requires_closed_scalar,
)
from shuxueshuo_server.solver.state_semantics import (
    derived_role_object_ref,
    is_object_handle,
    is_object_semantic_kind,
    object_kind_for_runtime_type,
    object_semantic_kind_for_handle,
    runtime_type_for_object_semantic_kind,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class _PreparedFunctionalReconciliation:
    plan: FunctionalPlan
    semantic_items: tuple[SemanticReadCatalogItem, ...]
    semantic_index: FunctionalSemanticIndex
    catalog: FunctionalCapabilityCatalog
    elaboration: FunctionalPlanElaborationResult
    issues: tuple[FunctionalPlanIssue, ...]
    repairs: tuple[FunctionalDeterministicRepair, ...]
    future_identity_hints: dict[str, tuple[str, ...]]
    future_return_object_hints: dict[tuple[str, str], tuple[str, ...]]
    call_scopes: dict[str, str]
    call_result_consumers: dict[tuple[str, str], tuple[str, ...]]
    call_execution_scopes: dict[str, str]
    semantic_object_consumers: dict[str, tuple[tuple[str, str], ...]]
    requested_scopes: dict[tuple[str, str], str]
    dependency_graph: dict[str, tuple[str, ...]]
    planned_target_objects: dict[tuple[str, str], str]
    explicitly_bound_answer_refs: frozenset[str]
    placement_service: FunctionalCallPlacementService


class _NormalizeElaborateScopeStage:
    """Normalize wire intent, elaborate args and establish preliminary scopes."""

    def run(
        self,
        plan: FunctionalPlan,
        *,
        planner_state_context: PlannerStateContext,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        handle_registry: CanonicalHandleRegistry,
        question_goals: Sequence[QuestionGoal],
    ) -> _PreparedFunctionalReconciliation:
        semantic_items = planner_state_context.semantic_read_catalog()
        semantic_index = FunctionalSemanticIndex.from_context(
            planner_state_context,
            handle_registry=handle_registry,
        )
        catalog = FunctionalCapabilityCatalog.from_family_spec(
            family_spec,
            method_specs,
        ).contextualized(semantic_index)
        plan, moved_call_ids, cyclic_call_ids = topologically_order_plan(plan)
        ordering_repairs = tuple(
            FunctionalDeterministicRepair(
                call_id,
                "reorder_call_by_dependency",
                "wire_order",
                "topological_order",
            )
            for call_id in moved_call_ids
            if call_id not in cyclic_call_ids
        )
        ordering_issues = tuple(
            _issue(
                "functional_reconciliation",
                "functional.call_cycle",
                "FunctionalPlan calls contain a cyclic dependency",
                call_id=call_id,
                details={"cyclic_call_ids": list(cyclic_call_ids)},
            )
            for call_id in cyclic_call_ids
        )
        plan, answer_binding_repairs = _normalize_functional_answer_bindings(
            plan,
            catalog=catalog,
            question_goals=question_goals,
            handle_registry=handle_registry,
        )
        elaboration = FunctionalPlanElaborator().elaborate(
            plan,
            catalog=catalog,
            semantic_index=semantic_index,
        )
        elaboration = replace(
            elaboration,
            issues=(*ordering_issues, *elaboration.issues),
            deterministic_repairs=(
                *ordering_repairs,
                *elaboration.deterministic_repairs,
            ),
        )
        plan = elaboration.plan
        call_scopes = {
            call.call_id: scope.scope_id
            for scope in plan.scopes
            for call in scope.calls
        }
        consumers = _call_result_consumers(plan)
        consumer_scopes = _call_consumer_scopes(plan)
        placement_service = FunctionalCallPlacementService()
        call_execution_scopes = {
            call.call_id: _projected_execution_scope(
                call,
                functional_scope=scope.scope_id,
                consumer_scopes=consumer_scopes,
                question_goals=question_goals,
                handle_registry=handle_registry,
            )
            for scope in plan.scopes
            for call in scope.calls
        }
        call_execution_scopes = placement_service.preliminary_execution_scopes(
            plan,
            source_plan=elaboration.raw_plan,
            catalog=catalog,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
            default_scopes=call_execution_scopes,
            initial_aliases=elaboration.call_aliases or {},
        )
        requested_scopes = {
            (call_id, return_name): _least_common_scope(
                (call_scopes[call_id], *scopes),
                handle_registry,
            )
            for (call_id, return_name), scopes in consumers.items()
            if call_id in call_scopes
        }
        return _PreparedFunctionalReconciliation(
            plan=plan,
            semantic_items=semantic_items,
            semantic_index=semantic_index,
            catalog=catalog,
            elaboration=elaboration,
            issues=elaboration.issues,
            repairs=answer_binding_repairs,
            future_identity_hints=_future_return_identity_hints(
                plan,
                catalog=catalog,
                semantic_index=semantic_index,
            ),
            future_return_object_hints=_future_return_object_hints(
                plan,
                catalog=catalog,
                semantic_index=semantic_index,
            ),
            call_scopes=call_scopes,
            call_result_consumers=consumers,
            call_execution_scopes=call_execution_scopes,
            semantic_object_consumers=_semantic_object_consumer_scopes(
                plan,
                semantic_index=semantic_index,
            ),
            requested_scopes=requested_scopes,
            dependency_graph=_functional_dependency_graph(plan),
            planned_target_objects=_planned_target_objects(
                plan,
                catalog=catalog,
            ),
            explicitly_bound_answer_refs=frozenset(
                binding.ref
                for functional_scope in plan.scopes
                for functional_call in functional_scope.calls
                for binding in functional_call.return_bindings.values()
                if binding.kind == "answer"
            ),
            placement_service=placement_service,
        )


class FunctionalPlanReconciler:
    """Resolve FunctionalPlan refs against Context and project canonical steps."""

    def reconcile(
        self,
        plan: FunctionalPlan,
        *,
        planner_state_context: PlannerStateContext,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        handle_registry: CanonicalHandleRegistry,
        question_goals: Sequence[QuestionGoal],
    ) -> FunctionalPlanReconciliationResult:
        prepared = _NormalizeElaborateScopeStage().run(
            plan,
            planner_state_context=planner_state_context,
            family_spec=family_spec,
            method_specs=method_specs,
            handle_registry=handle_registry,
            question_goals=question_goals,
        )
        plan = prepared.plan
        semantic_items = prepared.semantic_items
        semantic_index = prepared.semantic_index
        catalog = prepared.catalog
        elaboration = prepared.elaboration
        issues = list(prepared.issues)
        reconciliation_repairs = list(prepared.repairs)
        future_identity_hints = prepared.future_identity_hints
        future_return_object_hints = prepared.future_return_object_hints
        call_scopes = prepared.call_scopes
        consumers = prepared.call_result_consumers
        call_execution_scopes = prepared.call_execution_scopes
        semantic_object_consumers = prepared.semantic_object_consumers
        requested_scopes = prepared.requested_scopes
        placement_service = prepared.placement_service
        produced: dict[tuple[str, str], ResolvedFunctionalValue] = {}
        effective_calls: dict[str, FunctionalCall] = {}
        return_role_aliases: dict[tuple[str, str], str] = {}
        processed_call_ids: set[str] = set()
        invalid_call_ids = {
            issue.call_id for issue in elaboration.issues if issue.call_id is not None
        }
        blocked_call_ids: set[str] = set()
        reconciled: list[FunctionalCallReconciliation] = []
        call_reports: list[FunctionalCallReport] = []
        dependency_graph = prepared.dependency_graph
        planned_target_objects = prepared.planned_target_objects
        answer_bindings: dict[str, str] = {}
        explicitly_bound_answer_refs = set(
            prepared.explicitly_bound_answer_refs
        )
        factory = CanonicalStateHandleFactory()
        scope_by_id = {scope.scope_id: scope for scope in plan.scopes}
        for scope_id, _, call in topological_scoped_calls(plan)[0]:
            scope = scope_by_id[scope_id]
            blockers = tuple(
                dependency
                for dependency in dependency_graph.get(call.call_id, ())
                if dependency in invalid_call_ids | blocked_call_ids
            )
            if blockers:
                blocked_call_ids.add(call.call_id)
                call_reports.append(
                    FunctionalCallReport(
                        call.call_id,
                        scope.scope_id,
                        call.capability_id,
                        "blocked_by_dependency",
                        blocked_by=blockers,
                    )
                )
                continue
            issue_start = len(issues)
            capability = catalog.get(call.capability_id)
            if capability is None:
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.capability_unknown",
                        (
                            "capability is not executable in FunctionalPlan: "
                            f"{call.capability_id}"
                        ),
                        call_id=call.call_id,
                        scope_id=scope.scope_id,
                    )
                )
                invalid_call_ids.add(call.call_id)
                call_reports.append(
                    FunctionalCallReport(
                        call.call_id,
                        scope.scope_id,
                        call.capability_id,
                        "invalid",
                        issue_codes=tuple(
                            item.code for item in issues[issue_start:]
                        ),
                    )
                )
                continue
            resolution_scope_id = call_execution_scopes[call.call_id]
            resolved_args = _resolve_explicit_call_args(
                capability,
                call,
                declared_scope_id=scope.scope_id,
                resolution_scope_id=resolution_scope_id,
                semantic_index=semantic_index,
                produced=produced,
                handle_registry=handle_registry,
                known_call_ids=set(call_scopes),
                processed_call_ids=processed_call_ids,
                deterministic_repairs=reconciliation_repairs,
                issues=issues,
            )
            reads_closed = False
            for (planned_call_id, arg_name), planned_object in (
                planned_target_objects.items()
            ):
                if (
                    planned_call_id != call.call_id
                    or arg_name in resolved_args
                ):
                    continue
                resolved_args[arg_name] = (
                    ResolvedFunctionalValue(
                        planned_object,
                        "PointRef",
                        resolution_scope_id,
                        object_ref=planned_object,
                        dependency_object_refs=(planned_object,),
                    ),
                )
                reconciliation_repairs.append(
                    FunctionalDeterministicRepair(
                        call.call_id,
                        "allocate_planned_target_object",
                        f"{arg_name}=omitted",
                        planned_object,
                    )
                )
            deterministic_args, deterministic_repairs = (
                _resolve_deterministic_optional_args(
                    capability,
                    resolved_args,
                    call_id=call.call_id,
                    scope_id=resolution_scope_id,
                    produced=produced,
                    semantic_index=semantic_index,
                    handle_registry=handle_registry,
                )
            )
            resolved_args.update(deterministic_args)
            reconciliation_repairs.extend(deterministic_repairs)
            auto_args, auto_repairs, auto_issues = _resolve_context_auto_args(
                capability,
                resolved_args,
                call_id=call.call_id,
                scope_id=resolution_scope_id,
                produced=produced,
                semantic_index=semantic_index,
                handle_registry=handle_registry,
            )
            resolved_args.update(auto_args)
            reconciliation_repairs.extend(auto_repairs)
            issues.extend(auto_issues)
            (
                closure_args,
                closure_repairs,
                closure_issues,
                reads_closed,
            ) = _resolve_context_closure_args(
                capability,
                call,
                resolved_args,
                call_id=call.call_id,
                scope_id=resolution_scope_id,
                produced=produced,
                semantic_index=semantic_index,
                handle_registry=handle_registry,
            )
            resolved_args.update(closure_args)
            reconciliation_repairs.extend(closure_repairs)
            issues.extend(closure_issues)
            if (
                capability.kind == "macro"
                and len(resolved_args) == 1
                and any(
                    value.runtime_type == "PathTransformation"
                    for values in resolved_args.values()
                    for value in values
                )
            ):
                reads_closed = True
            active_return_specs = _active_return_specs(
                capability,
                resolved_args,
            )
            (
                call,
                variant_repairs,
                call_return_aliases,
                variant_issues,
            ) = _normalize_polymorphic_return_roles(
                call,
                capability=capability,
                active_returns=active_return_specs,
                referenced_return_names={
                    return_name
                    for (source_call, return_name) in consumers
                    if source_call == call.call_id
                },
                scope_id=scope.scope_id,
            )
            reconciliation_repairs.extend(variant_repairs)
            return_role_aliases.update(
                {
                    (call.call_id, source): target
                    for source, target in call_return_aliases.items()
                }
            )
            issues.extend(variant_issues)
            effective_calls[call.call_id] = call
            issues.extend(
                _functional_return_contract_issues(
                    capability,
                    call,
                    scope_id=scope.scope_id,
                )
            )
            if len(issues) > issue_start:
                invalid_call_ids.add(call.call_id)
                call_reports.append(
                    FunctionalCallReport(
                        call.call_id,
                        scope.scope_id,
                        call.capability_id,
                        "invalid",
                        issue_codes=tuple(
                            item.code for item in issues[issue_start:]
                        ),
                    )
                )
                continue
            issues.extend(
                _functional_symbol_identity_issues(
                    capability,
                    call,
                    resolved_args,
                    identity_hints=future_identity_hints.get(
                        call.call_id,
                        (),
                    ),
                    produced=produced,
                    scope_id=resolution_scope_id,
                    semantic_index=semantic_index,
                )
            )
            if len(issues) > issue_start:
                invalid_call_ids.add(call.call_id)
                call_reports.append(
                    FunctionalCallReport(
                        call.call_id,
                        scope.scope_id,
                        call.capability_id,
                        "invalid",
                        issue_codes=tuple(
                            item.code for item in issues[issue_start:]
                        ),
                    )
                )
                continue
            dynamic_dependencies = unique_ordered(
                value.source_call_id
                for values in resolved_args.values()
                for value in values
                if value.source_call_id is not None
            )
            dependency_graph[call.call_id] = unique_ordered(
                (
                    *dependency_graph.get(call.call_id, ()),
                    *dynamic_dependencies,
                )
            )
            call, allocations = _allocate_functional_returns(
                call=call,
                capability=capability,
                active_return_specs=active_return_specs,
                call_return_aliases=call_return_aliases,
                consumers=consumers,
                requested_scopes=requested_scopes,
                declared_scope_id=scope.scope_id,
                resolution_scope_id=resolution_scope_id,
                call_execution_scopes=call_execution_scopes,
                resolved_args=resolved_args,
                handle_registry=handle_registry,
                question_goals=question_goals,
                explicitly_bound_answer_refs=explicitly_bound_answer_refs,
                effective_calls=effective_calls,
                semantic_items=semantic_items,
                semantic_index=semantic_index,
                planner_state_context=planner_state_context,
                produced=produced,
                issues=issues,
                reconciliation_repairs=reconciliation_repairs,
                answer_bindings=answer_bindings,
                factory=factory,
                    semantic_object_consumers=semantic_object_consumers,
                    processed_call_ids=processed_call_ids,
                    future_return_object_hints=future_return_object_hints,
                )
            if len(issues) > issue_start:
                invalid_call_ids.add(call.call_id)
                call_reports.append(
                    FunctionalCallReport(
                        call.call_id,
                        scope.scope_id,
                        call.capability_id,
                        "invalid",
                        issue_codes=tuple(
                            item.code for item in issues[issue_start:]
                        ),
                    )
                )
                continue
            processed_call_ids.add(call.call_id)
            reconciled.append(
                FunctionalCallReconciliation(
                    call_id=call.call_id,
                    scope_id=scope.scope_id,
                    capability_id=call.capability_id,
                    resolved_args=resolved_args,
                    returns=tuple(allocations),
                    reads_closed=reads_closed,
                )
            )
            call_reports.append(
                FunctionalCallReport(
                    call.call_id,
                    scope.scope_id,
                    call.capability_id,
                    "valid",
                )
            )
        return _PlacementLivenessProjectionStage().run(
            plan=plan,
            elaboration=elaboration,
            effective_calls=effective_calls,
            return_role_aliases=return_role_aliases,
            reconciled=reconciled,
            call_reports=call_reports,
            catalog=catalog,
            semantic_items=semantic_items,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
            question_goals=question_goals,
            answer_bindings=answer_bindings,
            issues=issues,
            reconciliation_repairs=reconciliation_repairs,
            placement_service=placement_service,
        )


class _PlacementLivenessProjectionStage:
    """Canonicalize, prune and project an already-resolved call graph."""

    def run(
        self,
        *,
        plan: FunctionalPlan,
        elaboration: FunctionalPlanElaborationResult,
        effective_calls: Mapping[str, FunctionalCall],
        return_role_aliases: Mapping[tuple[str, str], str],
        reconciled: Sequence[FunctionalCallReconciliation],
        call_reports: Sequence[FunctionalCallReport],
        catalog: FunctionalCapabilityCatalog,
        semantic_items: tuple[SemanticReadCatalogItem, ...],
        semantic_index: FunctionalSemanticIndex,
        handle_registry: CanonicalHandleRegistry,
        question_goals: Sequence[QuestionGoal],
        answer_bindings: Mapping[str, str],
        issues: list[FunctionalPlanIssue],
        reconciliation_repairs: list[FunctionalDeterministicRepair],
        placement_service: FunctionalCallPlacementService,
    ) -> FunctionalPlanReconciliationResult:
        plan = _rewrite_effective_functional_plan(
            plan,
            effective_calls=effective_calls,
            return_role_aliases=return_role_aliases,
        )
        placement = placement_service.place(
            plan,
            source_plan=elaboration.raw_plan,
            reconciled=reconciled,
            call_reports=call_reports,
            catalog=catalog,
            handle_registry=handle_registry,
            semantic_items=semantic_items,
            question_goals=question_goals,
            initial_aliases=elaboration.call_aliases or {},
        )
        plan = placement.plan
        reconciled = list(placement.calls)
        call_reports = list(placement.call_reports)
        dependency_graph = _with_closed_scalar_dependencies(
            plan,
            reconciled=tuple(reconciled),
            dependency_graph=placement.dependency_graph,
            handle_registry=handle_registry,
        )
        reconciliation_repairs.extend(placement.repairs)
        issues.extend(placement.issues)
        liveness = FunctionalCallLivenessAnalyzer().analyze(
            plan,
            reconciled=reconciled,
            call_reports=call_reports,
            dependency_graph=dependency_graph,
            catalog=catalog,
            protected_call_ids=_calls_protected_for_unbound_goals(
                plan,
                reconciled,
                catalog=catalog,
                question_goals=question_goals,
                answer_bindings=answer_bindings,
                handle_registry=handle_registry,
            )
            + (
                _terminal_valid_calls(plan, call_reports)
                if not question_goals
                else ()
            ),
            drop_invalid_calls=bool(question_goals),
        )
        plan = liveness.plan
        reconciled = list(liveness.calls)
        call_reports = list(liveness.call_reports)
        dependency_graph = liveness.dependency_graph
        reconciliation_repairs.extend(liveness.repairs)
        if liveness.dropped_call_ids:
            dropped_call_ids = set(liveness.dropped_call_ids)
            dropped_capabilities = {
                repair.call_id: repair.from_value
                for repair in liveness.repairs
                if repair.call_id in dropped_call_ids
            }
            for call_id in liveness.dropped_call_ids:
                issue_codes = unique_ordered(
                    issue.code for issue in issues if issue.call_id == call_id
                )
                if not issue_codes:
                    continue
                reconciliation_repairs.append(
                    FunctionalDeterministicRepair(
                        call_id,
                        "record_pruned_call_issues",
                        dropped_capabilities.get(call_id, "<unknown-capability>"),
                        ",".join(issue_codes),
                    )
                )
            issues[:] = [
                issue
                for issue in issues
                if issue.call_id not in dropped_call_ids
            ]
        live_call_ids = {call.call_id for call in plan.calls}
        call_placements = tuple(
            item
            for item in placement.placements
            if item.canonical_call_id in live_call_ids
        )
        call_aliases = {
            alias: canonical
            for alias, canonical in placement.aliases.items()
            if canonical in live_call_ids
        }
        for goal in question_goals:
            handle = f"answer:{goal.id}"
            scope_has_invalid_call = any(
                report.scope_id == goal.question_id
                and report.status != "valid"
                for report in call_reports
            )
            if (
                goal.required
                and handle not in answer_bindings
                and not scope_has_invalid_call
            ):
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.required_goal_unbound",
                        f"required answer is not bound: {handle}",
                        scope_id=goal.question_id,
                    )
                )
        elaboration = replace(
            elaboration,
            plan=plan,
            issues=tuple(
                issue
                for issue in elaboration.issues
                if issue.call_id in live_call_ids or issue.call_id is None
            ),
            deterministic_repairs=(
                *elaboration.deterministic_repairs,
                *reconciliation_repairs,
            ),
            auto_args=_filtered_call_mapping(elaboration.auto_args, plan=plan),
            resolved_args=_filtered_call_mapping(
                elaboration.resolved_args,
                plan=plan,
            ),
            aggregations=_filtered_call_mapping(
                elaboration.aggregations,
                plan=plan,
            ),
        )
        partial_projected, partial_projection_map = (
            FunctionalPlanProjector().project(
                plan,
                reconciled=tuple(reconciled),
                placements=call_placements,
                catalog=catalog,
                semantic_items=semantic_items,
                semantic_index=semantic_index,
            )
        )
        if issues:
            return FunctionalPlanReconciliationResult(
                plan=plan,
                calls=tuple(reconciled),
                issues=tuple(issues),
                projection_map=partial_projection_map,
                context_delta=_context_delta(reconciled),
                partial_projected_draft=partial_projected,
                call_reports=tuple(call_reports),
                dependency_graph=dependency_graph,
                call_placements=call_placements,
                call_aliases=call_aliases,
                elaboration=elaboration.to_payload(),
            )
        projected, projection_map = FunctionalPlanProjector().project(
            plan,
            reconciled=tuple(reconciled),
            placements=call_placements,
            catalog=catalog,
            semantic_items=semantic_items,
            semantic_index=semantic_index,
        )
        return FunctionalPlanReconciliationResult(
            plan=plan,
            calls=tuple(reconciled),
            projection_map=projection_map,
            context_delta=_context_delta(reconciled),
            projected_draft=projected,
            partial_projected_draft=projected,
            call_reports=tuple(call_reports),
            dependency_graph=dependency_graph,
            call_placements=call_placements,
            call_aliases=call_aliases,
            elaboration=elaboration.to_payload(),
        )


class FunctionalPlanProjector:
    """Project reconciled calls to the existing canonical StepIntentDraft."""

    def project(
        self,
        plan: FunctionalPlan,
        *,
        reconciled: tuple[FunctionalCallReconciliation, ...],
        placements: tuple[Any, ...],
        catalog: FunctionalCapabilityCatalog,
        semantic_items: tuple[SemanticReadCatalogItem, ...],
        semantic_index: FunctionalSemanticIndex,
    ) -> tuple[StepIntentDraft, tuple[FunctionalProjectionEntry, ...]]:
        by_call = {item.call_id: item for item in reconciled}
        placement_by_call = {
            item.canonical_call_id: item for item in placements
        }
        semantic_by_ref = {(item.kind, item.ref): item for item in semantic_items}
        known_handles = {item.handle for item in semantic_items}
        return_by_state_slot = {
            allocation.state_slot_id: allocation
            for call in reconciled
            for allocation in call.returns
        }
        projected_scopes: list[StepIntentScope] = []
        projection: list[FunctionalProjectionEntry] = []
        prior_parameter_values: dict[str, list[FunctionalReturnAllocation]] = {}
        for declared_scope_id, scope_label, call in topological_scoped_calls(plan)[0]:
                item = by_call.get(call.call_id)
                if item is None:
                    continue
                capability = catalog.items[call.capability_id]
                placement = placement_by_call.get(call.call_id)
                execution_scope = (
                    placement.execution_scope_id
                    if placement is not None
                    else item.scope_id
                )
                reads = [
                    handle
                    for values in item.resolved_args.values()
                    for value in values
                    for handle in _projected_read_handles(
                        value,
                        scope_id=declared_scope_id,
                        handle_registry=semantic_index.handle_registry,
                    )
                ]
                reads.extend(
                    allocation.handle
                    for values in item.resolved_args.values()
                    for value in values
                    for state_slot_id in value.source_state_slot_ids
                    if (
                        allocation := return_by_state_slot.get(state_slot_id)
                    ) is not None
                    and allocation.runtime_type == "ParameterValue"
                )
                if not item.reads_closed:
                    reads.extend(
                        _source_condition_handles(
                            item.resolved_args,
                            reconciled_by_call=by_call,
                        )
                    )
                if capability.kind == "macro" and not item.reads_closed:
                    dependency_scope = (
                        item.returns[0].valid_scope
                        if item.returns
                        else declared_scope_id
                    )
                    reads.extend(
                        handle
                        for values in item.resolved_args.values()
                        for value in values
                        for handle in semantic_index.dependency_read_handles(
                            value.dependency_object_refs,
                            scope_id=dependency_scope,
                        )
                    )
                for binding in call.return_bindings.values():
                    semantic = semantic_by_ref.get((binding.kind, binding.ref))
                    if semantic is not None and semantic.kind != "answer":
                        reads.append(semantic.handle)
                reads.extend(
                    _closed_scalar_parameter_reads(
                        call,
                        item=item,
                        prior_parameter_values=prior_parameter_values,
                        scope_id=execution_scope,
                        handle_registry=semantic_index.handle_registry,
                    )
                )
                produces = tuple(
                    ProducedFact(
                        handle=allocation.handle,
                        valid_scope=allocation.valid_scope,
                        description=(
                            f"{call.capability_id} return {allocation.return_name}"
                        ),
                        output_type=allocation.runtime_type,
                    )
                    for allocation in item.returns
                )
                target = next(
                    (
                        allocation.handle
                        for allocation in item.returns
                        if allocation.handle.startswith("answer:")
                    ),
                    (
                        produces[0].handle
                        if capability.kind == "macro" and produces
                        else next(
                            (
                                allocation.object_ref
                                for allocation in item.returns
                                if allocation.object_ref is not None
                            ),
                            produces[0].handle if produces else capability.goal_type,
                        )
                    ),
                )
                creates = _projected_creates(
                    item.returns,
                    resolved_args=item.resolved_args,
                    known_handles=known_handles,
                    capability_id=capability.capability_id,
                )
                step = StepIntent(
                    scope_id=execution_scope,
                    step_id=call.call_id,
                    recipe_hint=call.capability_id,
                    goal_type=capability.goal_type,
                    target=target,
                    strategy=call.strategy,
                    reads=tuple(unique_ordered(reads)),
                    creates=creates,
                    produces=produces,
                    reason=call.reason,
                )
                known_handles.update(created.handle for created in creates)
                # StepIntentDraft is an ordered compatibility projection of the
                # Functional call graph. Group only adjacent calls that share an
                # execution scope; collecting every scope into one global bucket
                # can move a producer behind its consumer when calls alternate
                # between parent and child scopes.
                if (
                    projected_scopes
                    and projected_scopes[-1].scope_id == execution_scope
                ):
                    previous_scope = projected_scopes[-1]
                    projected_scopes[-1] = replace(
                        previous_scope,
                        steps=(*previous_scope.steps, step),
                    )
                else:
                    projected_scopes.append(
                        StepIntentScope(
                            execution_scope,
                            scope_label,
                            (step,),
                        )
                    )
                projection.append(
                    FunctionalProjectionEntry(
                        call_id=call.call_id,
                        step_ids=(call.call_id,),
                        state_slot_ids=tuple(
                            allocation.state_slot_id for allocation in item.returns
                        ),
                        canonical_call_id=call.call_id,
                        alias_call_ids=(
                            placement.alias_call_ids
                            if placement is not None
                            else ()
                        ),
                        declared_scope_id=declared_scope_id,
                        execution_scope_id=execution_scope,
                    )
                )
                for allocation in item.returns:
                    if (
                        allocation.runtime_type == "ParameterValue"
                        and allocation.object_ref is not None
                    ):
                        prior_parameter_values.setdefault(
                            allocation.object_ref,
                            [],
                        ).append(allocation)
        return StepIntentDraft(tuple(projected_scopes)), tuple(projection)


def _with_closed_scalar_dependencies(
    plan: FunctionalPlan,
    *,
    reconciled: tuple[FunctionalCallReconciliation, ...],
    dependency_graph: Mapping[str, tuple[str, ...]],
    handle_registry: CanonicalHandleRegistry,
) -> dict[str, tuple[str, ...]]:
    """Make deterministic scalar-closure inputs visible to graph passes."""
    calls = {call.call_id: call for call in plan.calls}
    ordered_calls = tuple(
        call for _, _, call in topological_scoped_calls(plan)[0]
    )
    positions = {
        call.call_id: index for index, call in enumerate(ordered_calls)
    }
    reconciled_by_id = {item.call_id: item for item in reconciled}
    parameter_producers: dict[
        str,
        list[tuple[str, FunctionalReturnAllocation]],
    ] = {}
    for item in reconciled:
        for allocation in item.returns:
            if (
                allocation.runtime_type == "ParameterValue"
                and allocation.object_ref is not None
            ):
                parameter_producers.setdefault(allocation.object_ref, []).append(
                    (item.call_id, allocation)
                )
    result = {call_id: tuple(values) for call_id, values in dependency_graph.items()}
    for call_id, call in calls.items():
        item = reconciled_by_id.get(call_id)
        if item is None:
            continue
        allocations = {
            allocation.return_name: allocation for allocation in item.returns
        }
        dependencies = list(result.get(call_id, ()))
        for return_name, expectation in call.return_expectations.items():
            if expectation != "closed_value":
                continue
            allocation = allocations.get(return_name)
            if allocation is None:
                continue
            for symbol_ref in allocation.free_symbol_refs:
                candidates = tuple(
                    producer_id
                    for producer_id, produced in parameter_producers.get(
                        symbol_ref,
                        (),
                    )
                    if positions.get(producer_id, len(positions))
                    < positions.get(call_id, -1)
                    and visible_from_valid_scope(
                        produced.valid_scope,
                        scope_id=item.scope_id,
                        registry=handle_registry,
                    )
                )
                if len(candidates) == 1:
                    dependencies.append(candidates[0])
        result[call_id] = unique_ordered(dependencies)
    return result


def _closed_scalar_parameter_reads(
    call: FunctionalCall,
    *,
    item: FunctionalCallReconciliation,
    prior_parameter_values: Mapping[
        str,
        Sequence[FunctionalReturnAllocation],
    ],
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """Close a scalar with uniquely available values for its free Symbols.

    This is capability-agnostic: result-form metadata states the intended
    closure, return provenance states the remaining Symbol identities, and the
    timeline supplies candidate ParameterValue states. Ambiguous or missing
    values are left untouched so normal retry diagnostics retain the choice.
    """
    allocations = {allocation.return_name: allocation for allocation in item.returns}
    reads: list[str] = []
    for return_name, expectation in call.return_expectations.items():
        if expectation != "closed_value":
            continue
        allocation = allocations.get(return_name)
        if allocation is None:
            continue
        for symbol_ref in allocation.free_symbol_refs:
            candidates = tuple(
                candidate
                for candidate in prior_parameter_values.get(symbol_ref, ())
                if visible_from_valid_scope(
                    candidate.valid_scope,
                    scope_id=scope_id,
                    registry=handle_registry,
                )
            )
            if len(candidates) == 1:
                reads.append(candidates[0].handle)
    return unique_ordered(reads)



def _allocate_functional_returns(
    *,
    call: FunctionalCall,
    capability: FunctionalCapability,
    active_return_specs: Sequence[FunctionalCapabilityReturn],
    call_return_aliases: Mapping[str, str],
    consumers: Mapping[tuple[str, str], tuple[str, ...]],
    requested_scopes: Mapping[tuple[str, str], str],
    declared_scope_id: str,
    resolution_scope_id: str,
    call_execution_scopes: Mapping[str, str],
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    handle_registry: CanonicalHandleRegistry,
    question_goals: Sequence[QuestionGoal],
    explicitly_bound_answer_refs: set[str],
    effective_calls: dict[str, FunctionalCall],
    semantic_items: tuple[SemanticReadCatalogItem, ...],
    semantic_index: FunctionalSemanticIndex,
    planner_state_context: PlannerStateContext,
    produced: dict[tuple[str, str], ResolvedFunctionalValue],
    issues: list[FunctionalPlanIssue],
    reconciliation_repairs: list[FunctionalDeterministicRepair],
    answer_bindings: dict[str, str],
    factory: CanonicalStateHandleFactory,
    semantic_object_consumers: Mapping[str, tuple[tuple[str, str], ...]],
    processed_call_ids: set[str],
    future_return_object_hints: Mapping[
        tuple[str, str],
        tuple[str, ...],
    ],
) -> tuple[FunctionalCall, list[FunctionalReturnAllocation]]:
    """Allocate visible returns, identities, scopes, handles and StateSlots."""
    referenced_returns = {
        call_return_aliases.get(return_name, return_name)
        for (source_call, return_name), _consumer_scopes in consumers.items()
        if source_call == call.call_id
    }
    allocations: list[FunctionalReturnAllocation] = []
    for return_spec in active_return_specs:
        if not (
            return_spec.required
            or return_spec.name in referenced_returns
            or return_spec.name in call.return_bindings
        ):
            continue
        requested_scope = _initial_return_scope(
            call=call,
            return_spec=return_spec,
            call_return_aliases=call_return_aliases,
            requested_scopes=requested_scopes,
            declared_scope_id=declared_scope_id,
            execution_scope_id=call_execution_scopes[call.call_id],
            resolved_args=resolved_args,
            handle_registry=handle_registry,
            issues=issues,
            reconciliation_repairs=reconciliation_repairs,
        )
        call, bound_ref, bound_item = _resolve_allocated_return_binding(
            call=call,
            return_spec=return_spec,
            referenced_returns=referenced_returns,
            resolution_scope_id=resolution_scope_id,
            declared_scope_id=declared_scope_id,
            question_goals=question_goals,
            explicitly_bound_answer_refs=explicitly_bound_answer_refs,
            effective_calls=effective_calls,
            semantic_items=semantic_items,
            handle_registry=handle_registry,
            issues=issues,
            reconciliation_repairs=reconciliation_repairs,
            answer_bindings=answer_bindings,
        )
        requested_scope = _align_return_scope_with_binding(
            call=call,
            return_spec=return_spec,
            requested_scope=requested_scope,
            bound_item=bound_item,
            resolved_args=resolved_args,
            question_goals=question_goals,
            declared_scope_id=declared_scope_id,
            handle_registry=handle_registry,
            issues=issues,
        )
        bound_ref, bound_item, object_ref = _resolve_return_identity(
            call=call,
            return_spec=return_spec,
            requested_scope=requested_scope,
            resolution_scope_id=resolution_scope_id,
            declared_scope_id=declared_scope_id,
            bound_ref=bound_ref,
            bound_item=bound_item,
            resolved_args=resolved_args,
            produced=produced,
            semantic_items=semantic_items,
            semantic_index=semantic_index,
            planner_state_context=planner_state_context,
            handle_registry=handle_registry,
            factory=factory,
            sibling_returns=tuple(allocations),
            issues=issues,
            reconciliation_repairs=reconciliation_repairs,
            future_object_hints=(
                ()
                if return_spec.name in call.return_bindings
                else future_return_object_hints.get(
                    (call.call_id, return_spec.name),
                    (),
                )
            ),
        )
        if (
            bound_ref is not None
            and call.return_bindings.get(return_spec.name) != bound_ref
        ):
            call = _with_functional_return_binding(
                call,
                return_spec.name,
                bound_ref,
            )
            effective_calls[call.call_id] = call
        requested_scope, object_ref = _publish_return_scope(
            call=call,
            return_spec=return_spec,
            requested_scope=requested_scope,
            bound_ref=bound_ref,
            bound_item=bound_item,
            object_ref=object_ref,
            resolved_args=resolved_args,
            question_goals=question_goals,
            semantic_object_consumers=semantic_object_consumers,
            processed_call_ids=processed_call_ids,
            handle_registry=handle_registry,
            factory=factory,
            sibling_returns=tuple(allocations),
            reconciliation_repairs=reconciliation_repairs,
        )
        allocation = _materialize_functional_return(
            call=call,
            return_spec=return_spec,
            requested_scope=requested_scope,
            bound_ref=bound_ref,
            bound_item=bound_item,
            object_ref=object_ref,
            resolved_args=resolved_args,
            semantic_index=semantic_index,
            call_return_aliases=call_return_aliases,
            factory=factory,
            produced=produced,
        )
        allocations.append(allocation)
    return call, allocations


def _initial_return_scope(
    *,
    call: FunctionalCall,
    return_spec: FunctionalCapabilityReturn,
    call_return_aliases: Mapping[str, str],
    requested_scopes: Mapping[tuple[str, str], str],
    declared_scope_id: str,
    execution_scope_id: str,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    handle_registry: CanonicalHandleRegistry,
    issues: list[FunctionalPlanIssue],
    reconciliation_repairs: list[FunctionalDeterministicRepair],
) -> str:
    """Choose the broadest initially requested scope visible to all inputs."""

    requested_scope = _requested_return_scope(
        call.call_id,
        return_spec.name,
        aliases=call_return_aliases,
        requested_scopes=requested_scopes,
        default_scope=declared_scope_id,
        handle_registry=handle_registry,
    )
    atomic_scope = _least_common_scope(
        (requested_scope, execution_scope_id),
        handle_registry,
    )
    if atomic_scope != requested_scope:
        reconciliation_repairs.append(
            FunctionalDeterministicRepair(
                call.call_id,
                "promote_return_scope_for_atomic_call",
                requested_scope,
                atomic_scope,
            )
        )
        requested_scope = atomic_scope
    if _inputs_visible_from_scope(
        resolved_args,
        requested_scope,
        handle_registry,
    ):
        return requested_scope
    issues.append(
        _issue(
            "functional_reconciliation",
            "functional.output_scope_not_shareable",
            (
                f"return {call.call_id}.{return_spec.name} "
                f"cannot be visible from {requested_scope}"
            ),
            call_id=call.call_id,
            scope_id=declared_scope_id,
            details={"requested_scope": requested_scope},
        )
    )
    return declared_scope_id


def _resolve_allocated_return_binding(
    *,
    call: FunctionalCall,
    return_spec: FunctionalCapabilityReturn,
    referenced_returns: set[str],
    resolution_scope_id: str,
    declared_scope_id: str,
    question_goals: Sequence[QuestionGoal],
    explicitly_bound_answer_refs: set[str],
    effective_calls: dict[str, FunctionalCall],
    semantic_items: tuple[SemanticReadCatalogItem, ...],
    handle_registry: CanonicalHandleRegistry,
    issues: list[FunctionalPlanIssue],
    reconciliation_repairs: list[FunctionalDeterministicRepair],
    answer_bindings: dict[str, str],
) -> tuple[
    FunctionalCall,
    SemanticRef | None,
    SemanticReadCatalogItem | None,
]:
    """Resolve an explicit binding and promote unique answer destinations."""

    bound_ref = call.return_bindings.get(return_spec.name)
    has_explicit_binding = bound_ref is not None
    if (
        bound_ref is not None
        and bound_ref.kind != "answer"
        and return_spec.name not in referenced_returns
    ):
        compatible_goals = _compatible_unbound_goals_for_return(
            return_spec,
            scope_id=declared_scope_id,
            question_goals=question_goals,
            bound_answer_refs=explicitly_bound_answer_refs,
            handle_registry=handle_registry,
        )
        if len(compatible_goals) == 1:
            goal = compatible_goals[0]
            answer_ref = SemanticRef(
                goal.id,
                "answer",
                value_type=goal.value_type,
            )
            reconciliation_repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    "promote_unique_object_binding_to_answer",
                    f"{bound_ref.kind}:{bound_ref.ref}",
                    goal.id,
                )
            )
            bound_ref = answer_ref
            call = _with_functional_return_binding(
                call,
                return_spec.name,
                answer_ref,
            )
            effective_calls[call.call_id] = call
            explicitly_bound_answer_refs.add(goal.id)

    bound_item: SemanticReadCatalogItem | None = None
    if bound_ref is None:
        return call, bound_ref, bound_item
    bound_item, binding_issues = _resolve_return_binding(
        bound_ref,
        call_id=call.call_id,
        scope_id=resolution_scope_id,
        return_type=return_spec.runtime_type,
        semantic_items=semantic_items,
        question_goals=question_goals,
    )
    issues.extend(binding_issues)
    if bound_item is not None and return_spec.identity_policy == "derived_role":
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_identity_mismatch",
                (
                    f"derived-role return {call.capability_id}."
                    f"{return_spec.name} cannot be bound to an "
                    "existing object or answer identity"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
                details={
                    "return": return_spec.name,
                    "semantic_role": return_spec.semantic_role,
                    "identity_policy": return_spec.identity_policy,
                    "bound_ref": bound_ref.ref,
                },
            )
        )
        bound_item = None
    if (
        bound_item is not None
        and bound_item.kind != "answer"
        and has_explicit_binding
        and return_spec.name not in referenced_returns
    ):
        answer_item = _unique_answer_for_object_binding(
            bound_item,
            return_type=return_spec.runtime_type,
            question_goals=question_goals,
            semantic_items=semantic_items,
            handle_registry=handle_registry,
        )
        if (
            answer_item is not None
            and answer_item.ref not in explicitly_bound_answer_refs
        ):
            reconciliation_repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    "promote_object_binding_to_answer",
                    bound_item.ref,
                    answer_item.ref,
                )
            )
            bound_item = answer_item
            bound_ref = SemanticRef(
                answer_item.ref,
                "answer",
                value_type=return_spec.runtime_type,
            )
            call = _with_functional_return_binding(
                call,
                return_spec.name,
                bound_ref,
            )
            effective_calls[call.call_id] = call
            explicitly_bound_answer_refs.add(answer_item.ref)
    if bound_item is not None and bound_item.kind == "answer":
        previous = answer_bindings.get(bound_item.handle)
        if previous is not None:
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.answer_duplicate",
                    f"answer is bound by both {previous} and {call.call_id}",
                    call_id=call.call_id,
                    scope_id=declared_scope_id,
                )
            )
        answer_bindings[bound_item.handle] = call.call_id
    return call, bound_ref, bound_item


def _align_return_scope_with_binding(
    *,
    call: FunctionalCall,
    return_spec: FunctionalCapabilityReturn,
    requested_scope: str,
    bound_item: SemanticReadCatalogItem | None,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    question_goals: Sequence[QuestionGoal],
    declared_scope_id: str,
    handle_registry: CanonicalHandleRegistry,
    issues: list[FunctionalPlanIssue],
) -> str:
    """Align a value scope with its answer or existing-object destination."""

    if bound_item is None:
        return requested_scope
    if bound_item.kind == "answer":
        # Object identity may live at problem scope while the answer state is
        # only valid in one question; align to the answer's question scope.
        destination_goal = next(
            (
                goal
                for goal in question_goals
                if f"answer:{goal.id}" == bound_item.handle
            ),
            None,
        )
        destination_scope = (
            destination_goal.question_id
            if destination_goal is not None
            else bound_item.scope
        )
        destination_lca = _least_common_scope(
            (requested_scope, destination_scope),
            handle_registry,
        )
        if destination_lca == requested_scope:
            return requested_scope
        if _inputs_visible_from_scope(
            resolved_args,
            destination_lca,
            handle_registry,
        ):
            return destination_lca
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_scope_incompatible",
                (
                    f"return {call.call_id}.{return_spec.name} "
                    f"cannot be written to {destination_scope}"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
            )
        )
        return requested_scope

    destination_lca = _least_common_scope(
        (requested_scope, bound_item.valid_scope),
        handle_registry,
    )
    if (
        destination_lca != requested_scope
        and _inputs_visible_from_scope(
            resolved_args,
            destination_lca,
            handle_registry,
        )
    ):
        return destination_lca
    return requested_scope


def _resolve_return_identity(
    *,
    call: FunctionalCall,
    return_spec: FunctionalCapabilityReturn,
    requested_scope: str,
    resolution_scope_id: str,
    declared_scope_id: str,
    bound_ref: SemanticRef | None,
    bound_item: SemanticReadCatalogItem | None,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_items: tuple[SemanticReadCatalogItem, ...],
    semantic_index: FunctionalSemanticIndex,
    planner_state_context: PlannerStateContext,
    handle_registry: CanonicalHandleRegistry,
    factory: CanonicalStateHandleFactory,
    sibling_returns: tuple[FunctionalReturnAllocation, ...],
    issues: list[FunctionalPlanIssue],
    reconciliation_repairs: list[FunctionalDeterministicRepair],
    future_object_hints: tuple[str, ...],
) -> tuple[
    SemanticRef | None,
    SemanticReadCatalogItem | None,
    str | None,
]:
    """Resolve object identity through the return's declared policy."""

    if return_spec.identity_policy == "target_object":
        bound_ref, bound_item = _resolve_target_return_binding(
            call=call,
            return_spec=return_spec,
            resolution_scope_id=resolution_scope_id,
            declared_scope_id=declared_scope_id,
            bound_ref=bound_ref,
            bound_item=bound_item,
            resolved_args=resolved_args,
            produced=produced,
            semantic_items=semantic_items,
            semantic_index=semantic_index,
            planner_state_context=planner_state_context,
            handle_registry=handle_registry,
            issues=issues,
            reconciliation_repairs=reconciliation_repairs,
            future_object_hints=future_object_hints,
        )

    object_ref = factory.object_ref_for(
        call_id=call.call_id,
        return_spec=return_spec,
        valid_scope=requested_scope,
        binding=bound_item,
        resolved_args=resolved_args,
        handle_registry=handle_registry,
        sibling_returns=sibling_returns,
    )
    if (
        return_spec.identity_policy == "preserve_input_object"
        and object_ref is None
    ):
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_identity_unresolved",
                (
                    f"return {call.capability_id}."
                    f"{return_spec.name} cannot resolve input identity"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
            )
        )
    return bound_ref, bound_item, object_ref


def _resolve_target_return_binding(
    *,
    call: FunctionalCall,
    return_spec: FunctionalCapabilityReturn,
    resolution_scope_id: str,
    declared_scope_id: str,
    bound_ref: SemanticRef | None,
    bound_item: SemanticReadCatalogItem | None,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_items: tuple[SemanticReadCatalogItem, ...],
    semantic_index: FunctionalSemanticIndex,
    planner_state_context: PlannerStateContext,
    handle_registry: CanonicalHandleRegistry,
    issues: list[FunctionalPlanIssue],
    reconciliation_repairs: list[FunctionalDeterministicRepair],
    future_object_hints: tuple[str, ...],
) -> tuple[SemanticRef | None, SemanticReadCatalogItem | None]:
    structured_target = _infer_target_object_binding(
        return_spec=return_spec,
        scope_id=resolution_scope_id,
        resolved_args=resolved_args,
        produced=produced,
        semantic_items=semantic_items,
        semantic_index=semantic_index,
        planner_state_context=planner_state_context,
        handle_registry=handle_registry,
        allow_role_inference=bound_item is None,
    )
    downstream_target = _target_item_from_object_hints(
        future_object_hints,
        return_spec=return_spec,
        scope_id=resolution_scope_id,
        semantic_items=semantic_items,
        handle_registry=handle_registry,
    )
    if (
        structured_target is not None
        and downstream_target is not None
        and _target_binding_identity(
            structured_target,
            handle_registry=handle_registry,
        )
        != _target_binding_identity(
            downstream_target,
            handle_registry=handle_registry,
        )
    ):
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_identity_mismatch",
                (
                    f"return {call.capability_id}.{return_spec.name} has "
                    "conflicting structured and downstream object identities"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
                details={
                    "return": return_spec.name,
                    "structured_ref": structured_target.ref,
                    "downstream_ref": downstream_target.ref,
                },
            )
        )
        downstream_target = None
    inferred_target = downstream_target or structured_target
    if bound_item is None and inferred_target is not None:
        bound_item = inferred_target
        bound_ref = SemanticRef(
            ref=bound_item.ref,
            kind=bound_item.kind,
            value_type=return_spec.runtime_type,
        )
        reconciliation_repairs.append(
            FunctionalDeterministicRepair(
                call.call_id,
                (
                    "propagate_downstream_object_identity"
                    if downstream_target is not None
                    else "auto_bind_target_object"
                ),
                f"<unbound:{return_spec.name}>",
                bound_item.ref,
            )
        )
    elif (
        bound_item is not None
        and inferred_target is not None
        and _target_binding_identity(
            bound_item,
            handle_registry=handle_registry,
        )
        != _target_binding_identity(
            inferred_target,
            handle_registry=handle_registry,
        )
    ):
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_identity_mismatch",
                (
                    f"return {call.capability_id}.{return_spec.name} is bound "
                    f"to {bound_item.ref}, but structured input evidence "
                    f"identifies {inferred_target.ref}"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
                details={
                    "return": return_spec.name,
                    "bound_ref": bound_item.ref,
                    "inferred_ref": inferred_target.ref,
                    "semantic_role": return_spec.semantic_role,
                },
            )
        )
    target_values = resolved_args.get(return_spec.identity_arg or "", ())
    if bound_item is None and not target_values:
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_identity_unresolved",
                (
                    "target-object return requires an answer or existing "
                    "object binding: "
                    f"{call.capability_id}.{return_spec.name}"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
                details={
                    "return": return_spec.name,
                    "semantic_role": return_spec.semantic_role,
                    "accepted_item_types": [return_spec.runtime_type],
                    "compatible_refs": list(
                        _compatible_target_object_refs(
                            return_spec=return_spec,
                            scope_id=resolution_scope_id,
                            semantic_items=semantic_items,
                            handle_registry=handle_registry,
                        )
                    ),
                },
            )
        )
    return bound_ref, bound_item


def _publish_return_scope(
    *,
    call: FunctionalCall,
    return_spec: FunctionalCapabilityReturn,
    requested_scope: str,
    bound_ref: SemanticRef | None,
    bound_item: SemanticReadCatalogItem | None,
    object_ref: str | None,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    question_goals: Sequence[QuestionGoal],
    semantic_object_consumers: Mapping[str, tuple[tuple[str, str], ...]],
    processed_call_ids: set[str],
    handle_registry: CanonicalHandleRegistry,
    factory: CanonicalStateHandleFactory,
    sibling_returns: tuple[FunctionalReturnAllocation, ...],
    reconciliation_repairs: list[FunctionalDeterministicRepair],
) -> tuple[str, str | None]:
    """Publish an object state only as broadly as proven consumers require."""

    if object_ref is None:
        return requested_scope, object_ref
    answer_object_scope = _answer_object_target_scope(
        bound_ref,
        object_ref=object_ref,
        question_goals=question_goals,
    )
    if (
        answer_object_scope is not None
        and answer_object_scope != requested_scope
    ):
        reconciliation_repairs.append(
            FunctionalDeterministicRepair(
                call.call_id,
                "publish_answer_state_to_object_scope",
                requested_scope,
                answer_object_scope,
            )
        )
        requested_scope = answer_object_scope
    future_consumer_scopes = tuple(
        consumer_scope
        for consumer_call_id, consumer_scope in semantic_object_consumers.get(
            object_ref,
            (),
        )
        if consumer_call_id != call.call_id
        and consumer_call_id not in processed_call_ids
    )
    if not future_consumer_scopes:
        return requested_scope, object_ref
    shared_scope = _broadest_shareable_ancestor_scope(
        requested_scope,
        consumer_scopes=future_consumer_scopes,
        args=resolved_args,
        registry=handle_registry,
    )
    if shared_scope == requested_scope:
        return requested_scope, object_ref
    reconciliation_repairs.append(
        FunctionalDeterministicRepair(
            call.call_id,
            "promote_return_scope_for_object_consumers",
            requested_scope,
            shared_scope,
        )
    )
    requested_scope = shared_scope
    object_ref = factory.object_ref_for(
        call_id=call.call_id,
        return_spec=return_spec,
        valid_scope=requested_scope,
        binding=bound_item,
        resolved_args=resolved_args,
        handle_registry=handle_registry,
        sibling_returns=sibling_returns,
    )
    return requested_scope, object_ref


def _materialize_functional_return(
    *,
    call: FunctionalCall,
    return_spec: FunctionalCapabilityReturn,
    requested_scope: str,
    bound_ref: SemanticRef | None,
    bound_item: SemanticReadCatalogItem | None,
    object_ref: str | None,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    semantic_index: FunctionalSemanticIndex,
    call_return_aliases: Mapping[str, str],
    factory: CanonicalStateHandleFactory,
    produced: dict[tuple[str, str], ResolvedFunctionalValue],
) -> FunctionalReturnAllocation:
    """Allocate the canonical handle/slot and register every return alias."""

    handle = factory.handle_for(
        call_id=call.call_id,
        return_spec=return_spec,
        valid_scope=requested_scope,
        binding=bound_item,
    )
    slot_id = (
        f"{object_ref}.{return_spec.state_kind}@{requested_scope}"
        if object_ref is not None
        else f"functional:{requested_scope}:{call.call_id}:{return_spec.name}"
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name=return_spec.name,
        handle=handle,
        runtime_type=return_spec.runtime_type,
        valid_scope=requested_scope,
        state_slot_id=slot_id,
        object_ref=object_ref,
        identity_policy=return_spec.identity_policy,
        write_mode=return_spec.write_mode,
        bound_ref=bound_ref,
        dependency_object_refs=unique_ordered(
            (
                *_argument_dependencies(resolved_args),
                *semantic_index.dependencies_for_object(object_ref),
            )
        ),
        free_symbol_refs=return_free_symbol_refs(
            return_spec.runtime_type,
            resolved_args,
            object_ref=object_ref,
        ),
        source_state_slot_ids=_argument_source_slots(resolved_args),
    )
    produced_value = ResolvedFunctionalValue(
        handle=handle,
        runtime_type=return_spec.runtime_type,
        valid_scope=requested_scope,
        state_slot_id=slot_id,
        source_call_id=call.call_id,
        return_name=return_spec.name,
        object_ref=object_ref,
        dependency_object_refs=allocation.dependency_object_refs,
        free_symbol_refs=allocation.free_symbol_refs,
        source_state_slot_ids=allocation.source_state_slot_ids,
    )
    produced[(call.call_id, return_spec.name)] = produced_value
    for alias_name, canonical_name in call_return_aliases.items():
        if canonical_name == return_spec.name:
            produced[(call.call_id, alias_name)] = produced_value
    return allocation


def _functional_return_contract_issues(
    capability: FunctionalCapability,
    call: FunctionalCall,
    *,
    scope_id: str,
) -> tuple[FunctionalPlanIssue, ...]:
    """Validate only wire-level return names, forms and declared types."""
    issues: list[FunctionalPlanIssue] = []
    return_specs = {item.name: item for item in capability.returns}
    for name in sorted(set(call.return_bindings) - set(return_specs)):
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_unknown",
                f"unknown return role: {call.capability_id}.{name}",
                call_id=call.call_id,
                scope_id=scope_id,
            )
        )
    for name in sorted(set(call.return_expectations) - set(return_specs)):
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_expectation_unknown",
                (
                    "return expectation references an unknown role: "
                    f"{call.capability_id}.{name}"
                ),
                call_id=call.call_id,
                scope_id=scope_id,
                details={"return": name},
            )
        )
    for name, expectation in call.return_expectations.items():
        return_spec = return_specs.get(name)
        if return_spec is None:
            continue
        binding = call.return_bindings.get(name)
        if (
            expectation == "open_expression"
            and binding is not None
            and binding.kind == "answer"
        ):
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.return_expectation_answer_conflict",
                    (
                        f"open expression {call.call_id}.{name} cannot be "
                        "bound directly to a numeric answer"
                    ),
                    call_id=call.call_id,
                    scope_id=scope_id,
                    details={"return": name},
                )
            )
    for name, binding in call.return_bindings.items():
        return_spec = return_specs.get(name)
        if (
            return_spec is not None
            and binding.value_type is not None
            and not runtime_type_compatible(
                return_spec.runtime_type,
                binding.value_type,
            )
        ):
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.return_type_mismatch",
                    (
                        f"return {return_spec.runtime_type} cannot bind to "
                        f"semantic value_type {binding.value_type}"
                    ),
                    call_id=call.call_id,
                    scope_id=scope_id,
                    details={"return": name},
                )
            )
    return tuple(issues)


def _functional_symbol_identity_issues(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: dict[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    identity_hints: tuple[str, ...],
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[FunctionalPlanIssue, ...]:
    return (
        *_resolve_auto_symbol_args(
            capability,
            resolved_args,
            call_id=call.call_id,
            scope_id=scope_id,
            identity_hints=(
                *_return_binding_identity_hints(
                    capability,
                    call,
                    scope_id=scope_id,
                    semantic_index=semantic_index,
                ),
                *identity_hints,
            ),
        ),
        *functional_reconciliation_issues(
            capability,
            resolved_args,
            produced=produced,
            call_id=call.call_id,
            scope_id=scope_id,
        ),
    )


def _resolve_explicit_call_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    *,
    declared_scope_id: str,
    resolution_scope_id: str,
    semantic_index: FunctionalSemanticIndex,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    handle_registry: CanonicalHandleRegistry,
    known_call_ids: set[str],
    processed_call_ids: set[str],
    deterministic_repairs: list[FunctionalDeterministicRepair],
    issues: list[FunctionalPlanIssue],
) -> dict[str, tuple[ResolvedFunctionalValue, ...]]:
    """Resolve only LLM-visible arguments and collect independent failures."""
    arg_specs = {item.name: item for item in capability.args}
    for name in sorted(set(call.args) - set(arg_specs)):
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.arg_unknown",
                f"unknown or auto argument: {call.capability_id}.{name}",
                call_id=call.call_id,
                scope_id=declared_scope_id,
            )
        )

    resolved: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    for arg in capability.args:
        refs = call.args.get(arg.name, ())
        accepted_types = arg.accepted_item_types or (arg.runtime_type,)

        def compatible_refs(*, materialized: bool | None = None) -> list[str]:
            return list(
                semantic_index.available_refs(
                    scope_id=resolution_scope_id,
                    accepted_types=accepted_types,
                    accepted_condition_kinds=arg.accepted_condition_kinds,
                    accepted_semantic_roles=arg.accepted_semantic_roles,
                    requires_materialized_state=(
                        arg.requires_materialized_state
                        if materialized is None
                        else materialized
                    ),
                )
            )

        if arg.required and not refs:
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.arg_missing",
                    (
                        "missing required argument: "
                        f"{call.capability_id}.{arg.name}"
                    ),
                    call_id=call.call_id,
                    scope_id=declared_scope_id,
                    details={
                        "arg": arg.name,
                        "semantic_role": arg.semantic_role or arg.name,
                        "accepted_item_types": list(accepted_types),
                        "accepted_condition_kinds": list(
                            arg.accepted_condition_kinds
                        ),
                        "compatible_refs": compatible_refs(),
                    },
                )
            )
            continue
        if arg.cardinality != "many" and len(refs) > 1:
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.arg_cardinality",
                    (
                        "argument expects one value: "
                        f"{call.capability_id}.{arg.name}"
                    ),
                    call_id=call.call_id,
                    scope_id=declared_scope_id,
                )
            )
            continue

        values: list[ResolvedFunctionalValue] = []
        for ref in refs:
            if (
                arg.accepted_semantic_roles
                and _functional_ref_role(ref)
                not in arg.accepted_semantic_roles
            ):
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.arg_role_mismatch",
                        (
                            f"argument {call.capability_id}.{arg.name} "
                            "requires semantic role "
                            f"{', '.join(arg.accepted_semantic_roles)}"
                        ),
                        call_id=call.call_id,
                        scope_id=declared_scope_id,
                        details={
                            "arg": arg.name,
                            "semantic_role": arg.semantic_role or arg.name,
                            "accepted_item_types": list(accepted_types),
                            "accepted_semantic_roles": list(
                                arg.accepted_semantic_roles
                            ),
                            "current_binding": ref.to_payload(),
                            "compatible_refs": compatible_refs(),
                        },
                    )
                )
                continue
            value, ref_issues = _resolve_functional_ref(
                ref,
                arg_name=arg.name,
                call_id=call.call_id,
                scope_id=resolution_scope_id,
                accepted_types=accepted_types,
                accepted_condition_kinds=arg.accepted_condition_kinds,
                aggregation=arg.aggregation,
                semantic_index=semantic_index,
                produced=produced,
                handle_registry=handle_registry,
                known_call_ids=known_call_ids,
                processed_call_ids=processed_call_ids,
                deterministic_repairs=deterministic_repairs,
            )
            issues.extend(ref_issues)
            if value is None:
                continue
            if arg.requires_materialized_state and value.state_slot_id is None:
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.arg_state_unavailable",
                        (
                            f"argument {call.capability_id}.{arg.name} requires "
                            "a materialized state, not only an object reference"
                        ),
                        call_id=call.call_id,
                        scope_id=declared_scope_id,
                        details={
                            "arg": arg.name,
                            "semantic_role": arg.semantic_role or arg.name,
                            "accepted_item_types": list(accepted_types),
                            "current_binding": ref.to_payload(),
                            "state_requirement": "materialized_state",
                            "compatible_refs": compatible_refs(
                                materialized=True
                            ),
                        },
                    )
                )
                continue
            values.append(value)
        if values:
            resolved[arg.name] = tuple(values)
    return resolved


def _resolve_functional_ref(
    ref: FunctionalRef,
    *,
    arg_name: str,
    call_id: str,
    scope_id: str,
    accepted_types: tuple[str, ...],
    accepted_condition_kinds: tuple[str, ...],
    aggregation: FunctionalAggregation,
    semantic_index: FunctionalSemanticIndex,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    handle_registry: CanonicalHandleRegistry,
    known_call_ids: set[str],
    processed_call_ids: set[str],
    deterministic_repairs: list[FunctionalDeterministicRepair],
) -> tuple[ResolvedFunctionalValue | None, tuple[FunctionalPlanIssue, ...]]:
    if isinstance(ref, CallResultRef):
        value = produced.get((ref.from_call, ref.return_name))
        if value is None:
            if ref.from_call not in known_call_ids:
                code = "functional.call_unknown"
            elif ref.from_call not in processed_call_ids:
                code = "functional.forward_reference"
            else:
                code = "functional.return_unknown"
            return None, (
                _issue(
                    "functional_reconciliation",
                    code,
                    f"unavailable call result: {ref.from_call}.{ref.return_name}",
                    call_id=call_id,
                    scope_id=scope_id,
                ),
            )
        if not visible_from_valid_scope(
            value.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        ):
            return None, (
                _issue(
                    "functional_reconciliation",
                    "functional.arg_scope_invisible",
                    f"call result is not visible: {ref.from_call}.{ref.return_name}",
                    call_id=call_id,
                    scope_id=scope_id,
                ),
            )
        if not (
            any(
                runtime_type_compatible(expected, value.runtime_type)
                for expected in accepted_types
            )
            or _aggregated_call_result_is_compatible(
                aggregation,
                value.runtime_type,
            )
        ):
            return None, (
                _issue(
                    "functional_reconciliation",
                    "functional.arg_type_mismatch",
                    (
                        "call result has an incompatible semantic state: "
                        f"{ref.from_call}.{ref.return_name}"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": arg_name,
                        "accepted_item_types": list(accepted_types),
                        "actual_type": value.runtime_type,
                    },
                ),
            )
        return value, ()
    value_type_mismatch = (
        ref.value_type is not None
        and not any(
            runtime_type_compatible(expected, ref.value_type)
            for expected in accepted_types
        )
        and ref.value_type not in accepted_condition_kinds
    )
    if value_type_mismatch and not is_object_semantic_kind(ref.kind):
        return None, (
            _issue(
                "functional_reconciliation",
                "functional.arg_type_mismatch",
                f"semantic value_type cannot satisfy argument: {ref.ref}",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg": arg_name,
                    "accepted_item_types": list(accepted_types),
                    "actual_type": ref.value_type,
                },
            ),
        )
    object_refs = (
        set(semantic_index.object_refs_for(ref, scope_id=scope_id))
        if is_object_semantic_kind(ref.kind)
        else set()
    )
    dynamic_candidates = tuple(
        value
        for value in produced.values()
        if value.object_ref in object_refs
        and visible_from_valid_scope(
            value.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
        and any(
            runtime_type_compatible(expected, value.runtime_type)
            for expected in accepted_types
        )
    )
    if dynamic_candidates:
        dynamic_objects = {item.object_ref for item in dynamic_candidates}
        if len(dynamic_objects) == 1:
            selected = dynamic_candidates[-1]
            deterministic_repairs.append(
                FunctionalDeterministicRepair(
                    call_id,
                    "select_latest_object_state",
                    f"{ref.kind}:{ref.ref}",
                    (
                        f"{selected.source_call_id or 'context'}:"
                        f"{selected.runtime_type}"
                    ),
                )
            )
            return selected, ()
        return None, (
            _issue(
                "functional_reconciliation",
                "functional.arg_ambiguous",
                f"semantic ref resolves to multiple current object states: {ref.ref}",
                call_id=call_id,
                scope_id=scope_id,
                details={"object_refs": sorted(item for item in dynamic_objects if item)},
            ),
        )
    resolved, candidates = semantic_index.resolve(
        ref,
        scope_id=scope_id,
        accepted_types=accepted_types,
        accepted_condition_kinds=accepted_condition_kinds,
    )
    if resolved is None:
        if value_type_mismatch:
            return None, (
                _issue(
                    "functional_reconciliation",
                    "functional.arg_type_mismatch",
                    f"semantic value_type cannot satisfy argument: {ref.ref}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": arg_name,
                        "accepted_item_types": list(accepted_types),
                        "actual_type": ref.value_type,
                    },
                ),
            )
        visible_candidates = tuple(
            item
            for item in candidates
            if visible_from_valid_scope(
                item.valid_scope,
                scope_id=scope_id,
                registry=handle_registry,
            )
        )
        compatible_candidates = tuple(
            item
            for item in visible_candidates
            if any(
                runtime_type_compatible(expected, item.runtime_type)
                for expected in accepted_types
            )
            and (
                not accepted_condition_kinds
                or item.condition_kind in accepted_condition_kinds
            )
        )
        available_condition_kinds = sorted(
            {
                item.condition_kind
                for item in visible_candidates
                if item.condition_kind is not None
            }
        )
        if candidates and not visible_candidates:
            code = "functional.arg_scope_invisible"
        elif (
            accepted_condition_kinds
            and visible_candidates
            and not compatible_candidates
        ):
            code = "functional.arg_semantic_role_mismatch"
        elif len(compatible_candidates) > 1:
            code = "functional.arg_ambiguous"
        elif visible_candidates:
            code = "functional.arg_type_mismatch"
        else:
            code = "functional.arg_unknown"
        return None, (
            _issue(
                "functional_reconciliation",
                code,
                f"semantic ref cannot satisfy argument: {ref.ref}",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg": arg_name,
                    "accepted_item_types": list(accepted_types),
                    "available_value_types": sorted(
                        {item.runtime_type for item in candidates}
                    ),
                    "available_refs": sorted({item.ref for item in candidates}),
                    "accepted_condition_kinds": list(accepted_condition_kinds),
                    "available_condition_kinds": available_condition_kinds,
                    "compatible_refs": list(
                        semantic_index.available_refs(
                            scope_id=scope_id,
                            accepted_types=accepted_types,
                            accepted_condition_kinds=accepted_condition_kinds,
                        )
                    ),
                },
            ),
        )
    if (
        value_type_mismatch
        and is_object_semantic_kind(ref.kind)
    ):
        deterministic_repairs.append(
            FunctionalDeterministicRepair(
                call_id,
                "select_compatible_object_state",
                f"{ref.kind}:{ref.ref}",
                f"context:{resolved.runtime_type}",
            )
        )
    return ResolvedFunctionalValue(
        resolved.handle,
        resolved.runtime_type,
        resolved.valid_scope,
        resolved.state_slot_id,
        object_ref=resolved.object_ref,
        condition_id=resolved.condition_id,
        object_roles=resolved.object_roles,
        dependency_object_refs=resolved.dependency_object_refs,
        free_symbol_refs=resolved.free_symbol_refs,
        source_state_slot_ids=resolved.source_state_slot_ids,
    ), ()


def _aggregated_call_result_is_compatible(
    aggregation: FunctionalAggregation,
    runtime_type: str,
) -> bool:
    """Accept an already-aggregated prior-call container for a lowered arg."""
    return runtime_type == {
        "coefficients_by_symbol": "Coefficients",
        "point_list": "PointList",
        "symbol_list": "SymbolList",
    }.get(aggregation)


def _resolve_return_binding(
    ref: SemanticRef,
    *,
    call_id: str,
    scope_id: str,
    return_type: str,
    semantic_items: tuple[SemanticReadCatalogItem, ...],
    question_goals: Sequence[QuestionGoal],
) -> tuple[SemanticReadCatalogItem | None, tuple[FunctionalPlanIssue, ...]]:
    # A return binding is a write destination, not an input read. Resolve it
    # globally by its exact semantic identity; placement later proves that the
    # call inputs are visible at the destination execution scope.
    candidates = [
        item for item in semantic_items
        if item.prompt_visible
        and item.ref == ref.ref
        and item.kind == ref.kind
    ]
    if len({item.handle for item in candidates}) != 1:
        code = (
            "functional.return_binding_unknown"
            if not candidates
            else "functional.return_binding_ambiguous"
        )
        return None, (
            _issue(
                "functional_reconciliation",
                code,
                f"return binding cannot be resolved: {ref.to_payload()}",
                call_id=call_id,
                scope_id=scope_id,
            ),
        )
    item = candidates[0]
    if (
        ref.value_type is not None
        and not runtime_type_compatible(return_type, ref.value_type)
    ):
        return None, (
            _issue(
                "functional_reconciliation",
                "functional.return_type_mismatch",
                (
                    f"return {return_type} cannot bind to semantic value_type "
                    f"{ref.value_type}"
                ),
                call_id=call_id,
                scope_id=scope_id,
            ),
        )
    if item.kind != "answer" and not is_object_semantic_kind(item.kind):
        return None, (
            _issue(
                "functional_reconciliation",
                "functional.return_binding_not_object",
                (
                    "return binding must target an answer or existing object: "
                    f"{ref.to_payload()}"
                ),
                call_id=call_id,
                scope_id=scope_id,
            ),
        )
    if item.kind == "answer":
        goal = next(
            (
                goal
                for goal in question_goals
                if f"answer:{goal.id}" == item.handle
            ),
            None,
        )
        if goal is None or not answer_output_type_compatible(goal.value_type, return_type):
            return None, (
                _issue(
                    "functional_reconciliation",
                    "functional.answer_type_mismatch",
                    f"return {return_type} cannot satisfy {item.handle}",
                    call_id=call_id,
                    scope_id=scope_id,
                ),
            )
    return item, ()


def _normalize_functional_answer_bindings(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    question_goals: Sequence[QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Repair answer destinations that are uniquely implied by the call graph.

    FunctionalPlan return bindings are intentionally lightweight. The LLM may
    bind a terminal value to its existing object view, or may label a consumed
    intermediate as an answer. QuestionGoal scope/type metadata and explicit
    CallResultRef consumers make a small subset of those mistakes deterministic
    to repair without guessing mathematical intent.
    """
    repairs: list[FunctionalDeterministicRepair] = []
    plan, intermediate_repairs = _drop_redundant_open_answer_bindings(
        plan,
        catalog=catalog,
        question_goals=question_goals,
    )
    repairs.extend(intermediate_repairs)
    goals_by_ref = {goal.id: goal for goal in question_goals}
    consumers = _call_result_consumers(plan)

    normalized_scopes = []
    for scope in plan.scopes:
        normalized_calls = []
        for call in scope.calls:
            capability = catalog.get(call.capability_id)
            returns_by_name = (
                {item.name: item for item in capability.returns}
                if capability is not None
                else {}
            )
            bindings = dict(call.return_bindings)
            for return_name, binding in tuple(bindings.items()):
                if binding.kind != "answer" or binding.ref in goals_by_ref:
                    continue
                return_spec = returns_by_name.get(return_name)
                compatible_goals = (
                    _compatible_unbound_goals_for_return(
                        return_spec,
                        scope_id=scope.scope_id,
                        question_goals=question_goals,
                        bound_answer_refs=_bound_answer_refs(plan),
                        handle_registry=handle_registry,
                    )
                    if return_spec is not None
                    else ()
                )
                if len(compatible_goals) == 1:
                    goal = compatible_goals[0]
                    bindings[return_name] = SemanticRef(
                        ref=goal.id,
                        kind="answer",
                        value_type=goal.value_type,
                    )
                    repairs.append(
                        FunctionalDeterministicRepair(
                            call.call_id,
                            "rewrite_unknown_answer_binding",
                            binding.ref,
                            goal.id,
                        )
                    )
                elif (call.call_id, return_name) in consumers:
                    del bindings[return_name]
                    repairs.append(
                        FunctionalDeterministicRepair(
                            call.call_id,
                            "drop_unknown_intermediate_answer_binding",
                            binding.ref,
                            f"<internal:{return_name}>",
                        )
                    )
            normalized_calls.append(replace(call, return_bindings=bindings))
        normalized_scopes.append(replace(scope, calls=tuple(normalized_calls)))
    plan = replace(plan, scopes=tuple(normalized_scopes))
    plan, superseded_repairs = _drop_superseded_unobserved_object_bindings(
        plan,
        catalog=catalog,
        consumers=consumers,
    )
    repairs.extend(superseded_repairs)

    bound_answer_refs = _bound_answer_refs(plan)
    latest_return_by_scope_type = _latest_return_by_scope_type(plan, catalog)
    candidate_by_goal: dict[str, list[tuple[str, str]]] = {}
    for scope in plan.scopes:
        for call in scope.calls:
            capability = catalog.get(call.capability_id)
            if capability is None:
                continue
            for return_spec in capability.returns:
                if return_spec.identity_policy == "derived_role":
                    continue
                binding = call.return_bindings.get(return_spec.name)
                if binding is not None and binding.kind == "answer":
                    continue
                if not (
                    binding is not None
                    or (call.call_id, return_spec.name) in consumers
                    or latest_return_by_scope_type.get(
                        (scope.scope_id, return_spec.runtime_type)
                    )
                    == (call.call_id, return_spec.name)
                ):
                    continue
                for goal in _compatible_unbound_goals_for_return(
                    return_spec,
                    scope_id=scope.scope_id,
                    question_goals=question_goals,
                    bound_answer_refs=bound_answer_refs,
                    handle_registry=handle_registry,
                ):
                    candidate_by_goal.setdefault(goal.id, []).append(
                        (call.call_id, return_spec.name)
                    )

    proposed_bindings: list[tuple[str, str, QuestionGoal]] = []
    for goal in question_goals:
        if not goal.required or goal.id in bound_answer_refs:
            continue
        candidates = candidate_by_goal.get(goal.id, [])
        if len(candidates) != 1:
            continue
        call_id, return_name = candidates[0]
        proposed_bindings.append((call_id, return_name, goal))

    proposal_counts: dict[tuple[str, str], int] = {}
    for call_id, return_name, _goal in proposed_bindings:
        key = (call_id, return_name)
        proposal_counts[key] = proposal_counts.get(key, 0) + 1
    unique_bindings = {
        (call_id, return_name): goal
        for call_id, return_name, goal in proposed_bindings
        if proposal_counts[(call_id, return_name)] == 1
    }

    if unique_bindings:
        rebound_scopes = []
        for scope in plan.scopes:
            rebound_calls = []
            for call in scope.calls:
                declarations = [
                    (return_name, goal)
                    for (call_id, return_name), goal in unique_bindings.items()
                    if call_id == call.call_id
                ]
                if not declarations:
                    rebound_calls.append(call)
                    continue
                bindings = dict(call.return_bindings)
                for return_name, goal in declarations:
                    previous = bindings.get(return_name)
                    bindings[return_name] = SemanticRef(
                        ref=goal.id,
                        kind="answer",
                        value_type=goal.value_type,
                    )
                    repairs.append(
                        FunctionalDeterministicRepair(
                            call.call_id,
                            "bind_unique_required_answer",
                            (
                                f"{previous.kind}:{previous.ref}"
                                if previous is not None
                                else f"<unbound:{return_name}>"
                            ),
                            goal.id,
                        )
                    )
                rebound_calls.append(replace(call, return_bindings=bindings))
            rebound_scopes.append(replace(scope, calls=tuple(rebound_calls)))
        plan = replace(plan, scopes=tuple(rebound_scopes))

    plan, expectation_repairs = _infer_closed_answer_expectations(
        plan,
        catalog=catalog,
        question_goals=question_goals,
    )
    repairs.extend(expectation_repairs)
    return plan, tuple(repairs)


def _infer_closed_answer_expectations(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    question_goals: Sequence[QuestionGoal],
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Infer closed scalar intent from a required answer destination."""
    goals = {goal.id: goal for goal in question_goals if goal.required}
    repairs: list[FunctionalDeterministicRepair] = []
    scopes = []
    for scope in plan.scopes:
        calls = []
        for call in scope.calls:
            capability = catalog.get(call.capability_id)
            returns = (
                {item.name: item for item in capability.returns}
                if capability is not None
                else {}
            )
            expectations = dict(call.return_expectations)
            for return_name, binding in call.return_bindings.items():
                goal = goals.get(binding.ref) if binding.kind == "answer" else None
                result = returns.get(return_name)
                if (
                    goal is None
                    or result is None
                    or return_name in expectations
                    or "closed_value" not in result.possible_forms
                    or not answer_value_type_requires_closed_scalar(goal.value_type)
                ):
                    continue
                expectations[return_name] = "closed_value"
                repairs.append(
                    FunctionalDeterministicRepair(
                        call.call_id,
                        "infer_closed_answer_result_form",
                        f"{return_name}=omitted",
                        "closed_value",
                    )
                )
            calls.append(replace(call, return_expectations=expectations))
        scopes.append(replace(scope, calls=tuple(calls)))
    return replace(plan, scopes=tuple(scopes)), tuple(repairs)


def _drop_redundant_open_answer_bindings(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    question_goals: Sequence[QuestionGoal],
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Demote a consumed open expression when one closed descendant owns its answer.

    The rule is intentionally graph- and contract-driven. It does not invent a
    missing evaluation call: the exact downstream answer producer must already
    exist, depend on this return, and declare ``closed_value``.
    """

    goals_by_ref = {goal.id: goal for goal in question_goals}
    consumer_calls = _call_result_consumer_calls(plan)
    adjacency = _call_adjacency(consumer_calls)
    calls_by_id = {call.call_id: call for call in plan.calls}
    repairs: list[FunctionalDeterministicRepair] = []
    dropped: set[tuple[str, str]] = set()

    for call in plan.calls:
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        returns_by_name = {item.name: item for item in capability.returns}
        for return_name, binding in call.return_bindings.items():
            return_spec = returns_by_name.get(return_name)
            if (
                binding.kind != "answer"
                or binding.ref not in goals_by_ref
                or call.return_expectations.get(return_name) != "open_expression"
                or return_spec is None
                or "open_expression" not in return_spec.possible_forms
                or (call.call_id, return_name) not in consumer_calls
            ):
                continue
            reachable = _reachable_consumer_calls(
                consumer_calls[(call.call_id, return_name)],
                adjacency=adjacency,
            )
            closed_producers = _closed_answer_producers(
                reachable,
                calls_by_id=calls_by_id,
                catalog=catalog,
                answer_ref=binding.ref,
                answer_value_type=goals_by_ref[binding.ref].value_type,
            )
            if len(closed_producers) != 1:
                continue
            dropped.add((call.call_id, return_name))
            closed_call_id, closed_return_name = closed_producers[0]
            repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    "drop_intermediate_open_expression_answer_binding",
                    binding.ref,
                    f"{closed_call_id}.{closed_return_name}",
                )
            )

    if not dropped:
        return plan, ()
    dropped_call_ids = {call_id for call_id, _name in dropped}
    normalized_scopes = tuple(
        replace(
            scope,
            calls=tuple(
                replace(
                    call,
                    return_bindings={
                        name: binding
                        for name, binding in call.return_bindings.items()
                        if (call.call_id, name) not in dropped
                    },
                )
                if call.call_id in dropped_call_ids
                else call
                for call in scope.calls
            ),
        )
        for scope in plan.scopes
    )
    return replace(plan, scopes=normalized_scopes), tuple(repairs)


def _closed_answer_producers(
    reachable_call_ids: Sequence[str],
    *,
    calls_by_id: Mapping[str, FunctionalCall],
    catalog: FunctionalCapabilityCatalog,
    answer_ref: str,
    answer_value_type: str,
) -> tuple[tuple[str, str], ...]:
    """Return reachable closed-form producers for one exact answer."""

    result: list[tuple[str, str]] = []
    for call_id in reachable_call_ids:
        call = calls_by_id.get(call_id)
        if call is None:
            continue
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        for return_spec in capability.returns:
            binding = call.return_bindings.get(return_spec.name)
            if (
                binding is None
                or binding.kind != "answer"
                or binding.ref != answer_ref
                or call.return_expectations.get(return_spec.name) != "closed_value"
                or "closed_value" not in return_spec.possible_forms
                or not answer_output_type_compatible(
                    answer_value_type,
                    return_spec.runtime_type,
                )
            ):
                continue
            result.append((call.call_id, return_spec.name))
    return tuple(unique_ordered(result))


def _drop_superseded_unobserved_object_bindings(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    consumers: dict[tuple[str, str], tuple[str, ...]],
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Remove an older pure write when a later call replaces the same view.

    This is deliberately version-aware: a binding is removed only when no
    explicit CallResultRef or semantic object read observes it before the next
    write. The call itself is left in the graph so the ordinary liveness pass
    decides whether its other returns are still needed.
    """
    calls = list(plan.calls)
    scope_by_call = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    previous_by_key: dict[
        tuple[str, str, str, str],
        tuple[int, str, str],
    ] = {}
    dropped: set[tuple[str, str]] = set()
    repairs: list[FunctionalDeterministicRepair] = []

    for index, call in enumerate(calls):
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        returns_by_name = {item.name: item for item in capability.returns}
        for return_name, binding in call.return_bindings.items():
            if binding.kind == "answer":
                continue
            return_spec = returns_by_name.get(return_name)
            if return_spec is None:
                continue
            key = (
                scope_by_call[call.call_id],
                binding.kind,
                binding.ref,
                return_spec.runtime_type,
            )
            previous = previous_by_key.get(key)
            if previous is not None:
                previous_index, previous_call_id, previous_return_name = previous
                previous_call = calls[previous_index]
                previous_capability = catalog.get(previous_call.capability_id)
                if (
                    previous_capability is not None
                    and previous_capability.kind == "function"
                    and previous_capability.is_pure
                    and (previous_call_id, previous_return_name) not in consumers
                    and not _semantic_binding_read_between(
                        calls,
                        start=previous_index + 1,
                        stop=index,
                        binding=binding,
                    )
                ):
                    dropped.add((previous_call_id, previous_return_name))
                    repairs.append(
                        FunctionalDeterministicRepair(
                            previous_call_id,
                            "drop_superseded_unobserved_object_binding",
                            f"{binding.kind}:{binding.ref}",
                            f"{call.call_id}:{return_name}",
                        )
                    )
            previous_by_key[key] = (index, call.call_id, return_name)

    if not dropped:
        return plan, ()
    scopes = []
    for scope in plan.scopes:
        scope_calls = []
        for call in scope.calls:
            bindings = {
                name: binding
                for name, binding in call.return_bindings.items()
                if (call.call_id, name) not in dropped
            }
            scope_calls.append(replace(call, return_bindings=bindings))
        scopes.append(replace(scope, calls=tuple(scope_calls)))
    return replace(plan, scopes=tuple(scopes)), tuple(repairs)


def _semantic_binding_read_between(
    calls: Sequence[FunctionalCall],
    *,
    start: int,
    stop: int,
    binding: SemanticRef,
) -> bool:
    return any(
        isinstance(ref, SemanticRef)
        and ref.kind == binding.kind
        and ref.ref == binding.ref
        for call in calls[start:stop]
        for refs in call.args.values()
        for ref in refs
    )


def _latest_return_by_scope_type(
    plan: FunctionalPlan,
    catalog: FunctionalCapabilityCatalog,
) -> dict[tuple[str, str], tuple[str, str]]:
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for scope in plan.scopes:
        for call in scope.calls:
            capability = catalog.get(call.capability_id)
            if capability is None:
                continue
            for return_spec in capability.returns:
                result[(scope.scope_id, return_spec.runtime_type)] = (
                    call.call_id,
                    return_spec.name,
                )
    return result


def _bound_answer_refs(plan: FunctionalPlan) -> set[str]:
    return {
        binding.ref
        for call in plan.calls
        for binding in call.return_bindings.values()
        if binding.kind == "answer"
    }


def _compatible_unbound_goals_for_return(
    return_spec: FunctionalCapabilityReturn,
    *,
    scope_id: str,
    question_goals: Sequence[QuestionGoal],
    bound_answer_refs: set[str],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[QuestionGoal, ...]:
    return tuple(
        goal
        for goal in question_goals
        if goal.required
        and goal.id not in bound_answer_refs
        and goal.question_id == scope_id
        and f"answer:{goal.id}" not in handle_registry.answer_target_handles
        and answer_output_type_compatible(
            goal.value_type,
            return_spec.runtime_type,
        )
    )


def _call_result_consumers(plan: FunctionalPlan) -> dict[tuple[str, str], tuple[str, ...]]:
    scope_by_call = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    return {
        key: tuple(scope_by_call[call_id] for call_id in call_ids)
        for key, call_ids in _call_result_consumer_calls(plan).items()
    }


def _call_result_consumer_calls(
    plan: FunctionalPlan,
) -> dict[tuple[str, str], tuple[str, ...]]:
    result: dict[tuple[str, str], list[str]] = {}
    for call in plan.calls:
        for refs in call.args.values():
            for ref in refs:
                if isinstance(ref, CallResultRef):
                    result.setdefault(
                        (ref.from_call, ref.return_name),
                        [],
                    ).append(call.call_id)
    return {key: tuple(value) for key, value in result.items()}


def _call_adjacency(
    consumers: Mapping[tuple[str, str], tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for (source_call_id, _return_name), consumer_ids in consumers.items():
        result.setdefault(source_call_id, []).extend(consumer_ids)
    return {
        call_id: unique_ordered(consumer_ids)
        for call_id, consumer_ids in result.items()
    }


def _reachable_consumer_calls(
    initial_call_ids: Sequence[str],
    *,
    adjacency: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    ordered: list[str] = []
    pending = list(initial_call_ids)
    while pending:
        call_id = pending.pop(0)
        if call_id in ordered:
            continue
        ordered.append(call_id)
        pending.extend(adjacency.get(call_id, ()))
    return tuple(ordered)


def _call_consumer_scopes(plan: FunctionalPlan) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for scope in plan.scopes:
        for call in scope.calls:
            for refs in call.args.values():
                for ref in refs:
                    if isinstance(ref, CallResultRef):
                        result.setdefault(ref.from_call, []).append(scope.scope_id)
    return {
        call_id: unique_ordered(scopes)
        for call_id, scopes in result.items()
    }


def _semantic_object_consumer_scopes(
    plan: FunctionalPlan,
    *,
    semantic_index: FunctionalSemanticIndex,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Index future object-facing reads independently of wire ref spelling."""
    result: dict[str, list[tuple[str, str]]] = {}
    for scope in plan.scopes:
        for call in scope.calls:
            for refs in call.args.values():
                for ref in refs:
                    if not isinstance(ref, SemanticRef):
                        continue
                    for object_ref in semantic_index.object_refs_for(
                        ref,
                        scope_id=scope.scope_id,
                    ):
                        result.setdefault(object_ref, []).append(
                            (call.call_id, scope.scope_id)
                        )
    return {
        object_ref: unique_ordered(consumers)
        for object_ref, consumers in result.items()
    }


def _projected_execution_scope(
    call: Any,
    *,
    functional_scope: str,
    consumer_scopes: Mapping[str, tuple[str, ...]],
    question_goals: Sequence[QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
) -> str:
    answer_scope_by_ref = {
        goal.id: goal.question_id for goal in question_goals if goal.required
    }
    destinations = [
        *consumer_scopes.get(call.call_id, ()),
        *(
        answer_scope_by_ref[binding.ref]
        for binding in call.return_bindings.values()
        if binding.kind == "answer" and binding.ref in answer_scope_by_ref
        ),
    ]
    if not destinations:
        return functional_scope
    destination_scope = _least_common_scope(
        unique_ordered(destinations),
        handle_registry,
    )
    if functional_scope in handle_registry.ancestor_scopes(destination_scope):
        return destination_scope
    return _least_common_scope(
        (functional_scope, destination_scope),
        handle_registry,
    )


def _answer_object_target_scope(
    bound_ref: SemanticRef | None,
    *,
    object_ref: str,
    question_goals: Sequence[QuestionGoal],
) -> str | None:
    """Return the explicit shared object scope of an answer destination.

    A subquestion may compute an answer whose authoritative target path is a
    problem/question object. Publishing that state at the object's scope is
    safe because the QuestionGoal, rather than a naming heuristic, declares
    the shared destination.
    """
    if bound_ref is None or bound_ref.kind != "answer":
        return None
    goal = next(
        (item for item in question_goals if item.id == bound_ref.ref),
        None,
    )
    if goal is None:
        return None
    try:
        target = ContextPath.parse(goal.target_path)
    except ValueError:
        return None
    object_scope = object_ref.split(":", 2)[1] if object_ref.count(":") >= 2 else None
    if target.container != "points" or target.scope_id != object_scope:
        return None
    return target.scope_id


def _inputs_visible_from_scope(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    scope_id: str,
    registry: CanonicalHandleRegistry,
) -> bool:
    return all(
        visible_from_valid_scope(value.valid_scope, scope_id=scope_id, registry=registry)
        for values in args.values()
        for value in values
    )


def _broadest_shareable_ancestor_scope(
    scope_id: str,
    *,
    consumer_scopes: Sequence[str],
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    registry: CanonicalHandleRegistry,
) -> str:
    """Promote a return only as far as its evidence remains visible.

    A producer may serve some sibling consumers without being valid for every
    consumer in the plan. Selecting the feasible ancestor that covers the most
    consumers preserves that partial graph instead of either leaking the state
    globally or leaving all sibling reads unresolved.
    """

    best_scope = scope_id
    best_coverage = sum(
        visible_from_valid_scope(
            scope_id,
            scope_id=consumer_scope,
            registry=registry,
        )
        for consumer_scope in consumer_scopes
    )
    for candidate in registry.ancestor_scopes(scope_id):
        if not _inputs_visible_from_scope(args, candidate, registry):
            continue
        coverage = sum(
            visible_from_valid_scope(
                candidate,
                scope_id=consumer_scope,
                registry=registry,
            )
            for consumer_scope in consumer_scopes
        )
        if coverage > best_coverage:
            best_scope = candidate
            best_coverage = coverage
    return best_scope


def _projected_creates(
    allocations: tuple[FunctionalReturnAllocation, ...],
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    known_handles: set[str],
    capability_id: str,
) -> tuple[CreatedEntity, ...]:
    result: list[CreatedEntity] = []
    for values in resolved_args.values():
        for value in values:
            entity_type = (
                object_semantic_kind_for_handle(value.object_ref)
                or object_kind_for_runtime_type(value.runtime_type)
            )
            if (
                not value.runtime_type.endswith("Ref")
                or value.object_ref is None
                or value.object_ref in known_handles
                or entity_type is None
            ):
                continue
            result.append(
                CreatedEntity(
                    handle=value.object_ref,
                    entity_type=entity_type,
                    valid_scope=value.valid_scope,
                    description=(
                        f"{capability_id} planned target object"
                    ),
                )
            )
    for item in allocations:
        entity_type = (
            object_semantic_kind_for_handle(item.object_ref)
            or object_kind_for_runtime_type(item.runtime_type)
        )
        if (
            item.write_mode != "create"
            or item.object_ref is None
            or item.object_ref in known_handles
            or entity_type is None
        ):
            continue
        result.append(
            CreatedEntity(
                handle=item.object_ref,
                entity_type=entity_type,
                valid_scope=item.valid_scope,
                description=(
                    f"{capability_id} generated object for {item.return_name}"
                ),
            )
        )
    return tuple(
        {
            item.handle: item
            for item in result
        }.values()
    )


def _active_return_specs(
    capability: FunctionalCapability,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[FunctionalCapabilityReturn, ...]:
    if capability.kind != "function":
        return capability.returns
    actual_types_by_arg = {
        name: {value.runtime_type for value in values}
        for name, values in resolved_args.items()
    }
    variant_types: set[str] = set()
    active_variant_types: set[str] = set()
    return_types = {item.runtime_type for item in capability.returns}
    for arg in capability.args:
        accepted = set(arg.accepted_item_types or (arg.runtime_type,))
        matching = accepted & return_types
        if len(matching) <= 1:
            continue
        variant_types.update(matching)
        for actual in actual_types_by_arg.get(arg.name, ()):
            exact = {return_type for return_type in matching if return_type == actual}
            active_variant_types.update(
                exact
                or {
                    return_type
                    for return_type in matching
                    if runtime_type_compatible(return_type, actual)
                }
            )
    if not variant_types or not active_variant_types:
        return capability.returns
    return tuple(
        item
        for item in capability.returns
        if item.runtime_type not in variant_types
        or item.runtime_type in active_variant_types
    )


def _normalize_polymorphic_return_roles(
    call: FunctionalCall,
    *,
    capability: FunctionalCapability,
    active_returns: tuple[FunctionalCapabilityReturn, ...],
    referenced_return_names: set[str],
    scope_id: str,
) -> tuple[
    FunctionalCall,
    tuple[FunctionalDeterministicRepair, ...],
    dict[str, str],
    tuple[FunctionalPlanIssue, ...],
]:
    """Select the unique runtime return variant after args have been typed.

    The wire plan may name a sibling return such as ``evaluated_expression``
    before object/state elaboration reveals that the actual input is a
    Parabola. The capability contract already declares all variants, so this
    correction is mechanical and should not be delegated back to the LLM.
    """
    all_returns = {item.name: item for item in capability.returns}
    active_by_name = {item.name: item for item in active_returns}
    variant_types = _polymorphic_return_types(capability)
    if not variant_types:
        return call, (), {}, ()

    active_variants = tuple(
        item for item in active_returns if item.runtime_type in variant_types
    )
    used_names = (
        set(call.return_bindings)
        | set(call.return_expectations)
        | referenced_return_names
    )
    aliases: dict[str, str] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []
    for name in sorted(used_names):
        declared = all_returns.get(name)
        if (
            declared is None
            or name in active_by_name
            or declared.runtime_type not in variant_types
        ):
            continue
        if len(active_variants) != 1:
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.return_variant_ambiguous",
                    (
                        f"return role {capability.capability_id}.{name} is not "
                        "active for the resolved input state"
                    ),
                    call_id=call.call_id,
                    scope_id=scope_id,
                    details={
                        "return": name,
                        "active_returns": [item.name for item in active_variants],
                    },
                )
            )
            continue
        active = active_variants[0]
        aliases[name] = active.name
        repairs.append(
            FunctionalDeterministicRepair(
                call.call_id,
                "select_runtime_return_variant",
                name,
                active.name,
            )
        )

    if not aliases:
        return call, tuple(repairs), aliases, tuple(issues)

    bindings = dict(call.return_bindings)
    expectations = dict(call.return_expectations)
    for source_name, target_name in aliases.items():
        binding = bindings.pop(source_name, None)
        if binding is not None and target_name in bindings:
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.return_variant_collision",
                    (
                        f"both {source_name} and {target_name} bind the same "
                        "active return variant"
                    ),
                    call_id=call.call_id,
                    scope_id=scope_id,
                )
            )
        elif binding is not None:
            bindings[target_name] = binding
        expectation = expectations.pop(source_name, None)
        if expectation is None:
            continue
        current = expectations.get(target_name)
        if current is not None and current != expectation:
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.return_expectation_conflict",
                    (
                        f"return variants {source_name} and {target_name} declare "
                        "conflicting result forms"
                    ),
                    call_id=call.call_id,
                    scope_id=scope_id,
                    details={
                        "return": target_name,
                        "expectations": [current, expectation],
                    },
                )
            )
            continue
        expectations[target_name] = expectation
    return (
        replace(
            call,
            return_bindings=bindings,
            return_expectations=expectations,
        ),
        tuple(repairs),
        aliases,
        tuple(issues),
    )


def _polymorphic_return_types(capability: FunctionalCapability) -> set[str]:
    return_types = {item.runtime_type for item in capability.returns}
    result: set[str] = set()
    for arg in capability.args:
        matching = set(arg.accepted_item_types or (arg.runtime_type,)) & return_types
        if len(matching) > 1:
            result.update(matching)
    return result


def _requested_return_scope(
    call_id: str,
    return_name: str,
    *,
    aliases: Mapping[str, str],
    requested_scopes: Mapping[tuple[str, str], str],
    default_scope: str,
    handle_registry: CanonicalHandleRegistry,
) -> str:
    scopes = [
        scope
        for (source_call, source_return), scope in requested_scopes.items()
        if source_call == call_id
        and aliases.get(source_return, source_return) == return_name
    ]
    return (
        _least_common_scope(scopes, handle_registry)
        if scopes
        else default_scope
    )


def _with_functional_return_binding(
    call: FunctionalCall,
    return_name: str,
    binding: SemanticRef,
) -> FunctionalCall:
    bindings = dict(call.return_bindings)
    bindings[return_name] = binding
    return replace(call, return_bindings=bindings)


def _rewrite_effective_functional_plan(
    plan: FunctionalPlan,
    *,
    effective_calls: Mapping[str, FunctionalCall],
    return_role_aliases: Mapping[tuple[str, str], str],
) -> FunctionalPlan:
    scopes = []
    for scope in plan.scopes:
        calls = []
        for original_call in scope.calls:
            call = effective_calls.get(original_call.call_id, original_call)
            args = {
                name: tuple(
                    CallResultRef(
                        ref.from_call,
                        return_role_aliases.get(
                            (ref.from_call, ref.return_name),
                            ref.return_name,
                        ),
                    )
                    if isinstance(ref, CallResultRef)
                    else ref
                    for ref in refs
                )
                for name, refs in call.args.items()
            }
            calls.append(replace(call, args=args))
        scopes.append(replace(scope, calls=tuple(calls)))
    return replace(plan, scopes=tuple(scopes))


def _projected_read_handles(
    value: ResolvedFunctionalValue,
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    if (
        value.runtime_type == "PointRef"
        and value.handle not in handle_registry.initial_handles
    ):
        # Planned objects are declared through creates. Their PointRef identity
        # is consumed by target selectors, not as a value read.
        return ()
    # Point values have two deliberate views. The state handle carries the
    # produced coordinate value for typed slot binding, while the object handle
    # carries PointRef identity for geometry methods. FunctionalPlan keeps this
    # distinction away from the LLM; the compiler's typed selectors choose the
    # view required by each runtime input.
    if (
        value.runtime_type == "Point"
        and value.object_ref is not None
        and value.object_ref.startswith("point:")
    ):
        state_valid_scope = handle_registry.handle_valid_scopes.get(
            value.handle,
            value.valid_scope,
        )
        handles = [value.object_ref]
        if visible_from_valid_scope(
            state_valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        ):
            handles.insert(0, value.handle)
        return tuple(unique_ordered(handles))
    return (value.handle,)


def _source_condition_handles(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    reconciled_by_call: Mapping[str, FunctionalCallReconciliation],
) -> tuple[str, ...]:
    result: list[str] = []
    visited: set[str] = set()

    def visit(call_id: str) -> None:
        if call_id in visited:
            return
        visited.add(call_id)
        source = reconciled_by_call.get(call_id)
        if source is None:
            return
        for values in source.resolved_args.values():
            for value in values:
                if value.runtime_type == "Condition":
                    result.append(value.handle)
                if value.source_call_id is not None:
                    visit(value.source_call_id)

    for values in args.values():
        for value in values:
            if value.source_call_id is not None:
                visit(value.source_call_id)
    return tuple(unique_ordered(result))


def _context_delta(
    calls: Sequence[FunctionalCallReconciliation],
) -> dict[str, Any]:
    return {
        "planned_state_slots": [
            {
                "slot_id": item.state_slot_id,
                "canonical_handle": item.handle,
                "runtime_type": item.runtime_type,
                "valid_scope": item.valid_scope,
                "produced_by": call.call_id,
            }
            for call in calls
            for item in call.returns
        ]
    }


def _functional_dependency_graph(
    plan: FunctionalPlan,
) -> dict[str, tuple[str, ...]]:
    return {
        call.call_id: unique_ordered(
            ref.from_call
            for refs in call.args.values()
            for ref in refs
            if isinstance(ref, CallResultRef)
        )
        for call in plan.calls
    }


def _planned_target_objects(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
) -> dict[tuple[str, str], str]:
    """Allocate a shared internal PointRef for a closed relation-to-point chain.

    The target is planned only when an unbound Point-producing call consumes a
    prior non-Point result whose producer also needs a hidden target PointRef.
    Standalone Point calls continue to recover identity from structured
    ProblemIR evidence or return bindings.
    """
    calls = {call.call_id: call for call in plan.calls}
    scopes = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    result: dict[tuple[str, str], str] = {}
    for call in plan.calls:
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        target_arg = _hidden_point_target_arg(capability, call)
        if target_arg is None:
            continue
        point_returns = [
            item
            for item in capability.returns
            if item.runtime_type == "Point"
            and item.identity_policy == "target_object"
            and item.name not in call.return_bindings
        ]
        if len(point_returns) != 1:
            continue
        source_ids = {
            ref.from_call
            for refs in call.args.values()
            for ref in refs
            if isinstance(ref, CallResultRef)
        }
        source_target_args: list[tuple[str, str]] = []
        for source_id in source_ids:
            source = calls.get(source_id)
            source_capability = (
                catalog.get(source.capability_id)
                if source is not None
                else None
            )
            if source is None or source_capability is None:
                continue
            source_target = _hidden_point_target_arg(
                source_capability,
                source,
            )
            if source_target is None or any(
                item.runtime_type == "Point"
                for item in source_capability.returns
            ):
                continue
            source_target_args.append((source_id, source_target))
        if not source_target_args:
            continue
        point_return = point_returns[0]
        object_ref = derived_role_object_ref(
            call_id=call.call_id,
            semantic_role=point_return.semantic_role,
            scope_id=scopes[call.call_id],
            runtime_type="Point",
        )
        result[(call.call_id, target_arg)] = object_ref
        for source_id, source_target in source_target_args:
            result[(source_id, source_target)] = object_ref
    return result


def _hidden_point_target_arg(
    capability: Any,
    call: FunctionalCall,
) -> str | None:
    candidates = [
        item.name
        for item in capability.auto_args
        if selector_semantics(item.selector).mechanical
        and "target" in item.name.lower()
        and not call.args.get(item.name)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _calls_protected_for_unbound_goals(
    plan: FunctionalPlan,
    reconciled: Sequence[FunctionalCallReconciliation],
    *,
    catalog: FunctionalCapabilityCatalog,
    question_goals: Sequence[QuestionGoal],
    answer_bindings: Mapping[str, str],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """Keep plausible producers while a compatible required answer is unbound."""
    unbound_goals = tuple(
        goal
        for goal in question_goals
        if goal.required and f"answer:{goal.id}" not in answer_bindings
    )
    reconciled_by_id = {call.call_id: call for call in reconciled}
    scope_by_call = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    protected: list[str] = []
    for call in plan.calls:
        resolved = reconciled_by_id.get(call.call_id)
        capability = catalog.get(call.capability_id)
        output_types = (
            tuple(output.runtime_type for output in resolved.returns)
            if resolved is not None
            else tuple(
                output.runtime_type
                for output in (capability.returns if capability is not None else ())
            )
        )
        if any(
            answer_output_type_compatible(goal.value_type, output_type)
            and visible_from_valid_scope(
                scope_by_call[call.call_id],
                scope_id=goal.question_id,
                registry=handle_registry,
            )
            for goal in unbound_goals
            for output_type in output_types
        ):
            protected.append(call.call_id)
    return tuple(unique_ordered(protected))


def _filtered_call_mapping(
    values: Mapping[str, Any] | None,
    *,
    plan: FunctionalPlan,
) -> dict[str, Any] | None:
    if values is None:
        return None
    call_ids = {call.call_id for call in plan.calls}
    return {key: value for key, value in values.items() if key in call_ids}


def _terminal_valid_calls(
    plan: FunctionalPlan,
    call_reports: Sequence[FunctionalCallReport],
) -> tuple[str, ...]:
    """Preserve observable terminals in goal-free partial/unit-test plans."""
    valid = {item.call_id for item in call_reports if item.status == "valid"}
    return tuple(
        next(
            call.call_id
            for call in reversed(scope.calls)
            if call.call_id in valid
        )
        for scope in plan.scopes
        if any(call.call_id in valid for call in scope.calls)
    )


def _future_return_identity_hints(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> dict[str, tuple[str, ...]]:
    """Infer unresolved return identity from later explicit semantic consumers."""

    ordered_calls = [
        (scope.scope_id, call)
        for scope in plan.scopes
        for call in scope.calls
    ]
    result: dict[str, tuple[str, ...]] = {}
    for index, (_scope_id, call) in enumerate(ordered_calls):
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        identity_return_types = {
            item.runtime_type
            for item in capability.returns
            if item.identity_policy == "preserve_input_object"
            and item.identity_arg
            and any(
                auto.name == item.identity_arg
                for auto in capability.auto_args
            )
        }
        if not identity_return_types:
            continue
        object_refs: list[str] = []
        for consumer_scope, consumer in ordered_calls[index + 1 :]:
            consumer_capability = catalog.get(consumer.capability_id)
            if consumer_capability is None:
                continue
            args_by_name = {
                item.name: item for item in consumer_capability.args
            }
            for arg_name, refs in consumer.args.items():
                arg = args_by_name.get(arg_name)
                if arg is None or not any(
                    runtime_type_compatible(expected, return_type)
                    for expected in (
                        arg.accepted_item_types or (arg.runtime_type,)
                    )
                    for return_type in identity_return_types
                ):
                    continue
                for ref in refs:
                    if (
                        isinstance(ref, CallResultRef)
                        and ref.from_call == call.call_id
                    ):
                        object_refs.extend(
                            _consumer_semantic_dependencies(
                                consumer,
                                scope_id=consumer_scope,
                                semantic_index=semantic_index,
                            )
                        )
                        continue
                    if not isinstance(ref, SemanticRef):
                        continue
                    object_refs.extend(
                        semantic_index.object_refs_for(
                            ref,
                            scope_id=consumer_scope,
                        )
                    )
        hints = unique_ordered(object_refs)
        if hints:
            result[call.call_id] = hints
    return result


def _future_return_object_hints(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Propagate explicit object destinations backwards through identity calls.

    Only ``preserve_input_object`` returns carry identity backwards. This makes
    a later answer binding usable as deterministic evidence without guessing a
    mathematical target from call text or capability names.
    """

    ordered_calls = [
        (scope.scope_id, call)
        for scope in plan.scopes
        for call in scope.calls
    ]
    hints: dict[tuple[str, str], set[str]] = {}
    for scope_id, call in ordered_calls:
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        for return_spec in capability.returns:
            binding = call.return_bindings.get(return_spec.name)
            if binding is None:
                continue
            object_refs = semantic_index.object_refs_for(
                binding,
                scope_id=scope_id,
            )
            if binding.kind == "answer":
                answer_target = (
                    semantic_index.handle_registry.answer_target_handles.get(
                        f"answer:{binding.ref}"
                    )
                )
                if answer_target is not None:
                    object_refs = (answer_target,)
            if object_refs:
                hints.setdefault(
                    (call.call_id, return_spec.name),
                    set(),
                ).update(object_refs)

    changed = True
    while changed:
        changed = False
        for _scope_id, call in reversed(ordered_calls):
            capability = catalog.get(call.capability_id)
            if capability is None:
                continue
            for return_spec in capability.returns:
                if (
                    return_spec.identity_policy != "preserve_input_object"
                    or not return_spec.identity_arg
                ):
                    continue
                return_hints = hints.get(
                    (call.call_id, return_spec.name),
                    set(),
                )
                if not return_hints:
                    continue
                for ref in call.args.get(return_spec.identity_arg, ()):
                    if not isinstance(ref, CallResultRef):
                        continue
                    target = hints.setdefault(
                        (ref.from_call, ref.return_name),
                        set(),
                    )
                    before = len(target)
                    target.update(return_hints)
                    changed = changed or len(target) != before
    return {
        key: unique_ordered(values)
        for key, values in hints.items()
    }


def _consumer_semantic_dependencies(
    call: Any,
    *,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[str, ...]:
    dependencies: list[str] = []
    for refs in call.args.values():
        for ref in refs:
            if not isinstance(ref, SemanticRef):
                continue
            runtime_type = runtime_type_for_object_semantic_kind(ref.kind)
            if runtime_type is None:
                continue
            resolved, _candidates = semantic_index.resolve(
                ref,
                scope_id=scope_id,
                accepted_types=(runtime_type,),
            )
            if resolved is None:
                continue
            dependencies.extend(resolved.free_symbol_refs)
            if resolved.object_ref is not None:
                dependencies.append(resolved.object_ref)
    return unique_ordered(dependencies)


def _resolve_context_closure_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
    bool,
]:
    """Run only the Context-closure resolvers declared by the contract."""
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []
    reads_closed = False
    handlers = {
        CONDITION_OBJECT_ROLES_RESOLVER: _resolve_condition_role_args,
        PATH_REDUCTION_ROLES_RESOLVER: _resolve_path_reduction_args,
    }
    for resolver_id in capability.context_resolvers:
        resolver = context_closure_resolver(resolver_id)
        handler = handlers[resolver_id]
        resolved, current_repairs, current_issues, closed = handler(
            capability,
            call,
            {**resolved_args, **additions},
            resolver,
            call_id=call_id,
            scope_id=scope_id,
            produced=produced,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
        )
        for arg_name, values in resolved.items():
            previous = additions.get(arg_name) or resolved_args.get(arg_name)
            if previous is not None and previous != values:
                if not _same_context_object_values(previous, values):
                    raise ValueError(
                        "planner_configuration_error: context resolvers produced "
                        f"conflicting values for {capability.capability_id}.{arg_name}"
                    )
            additions[arg_name] = values
        repairs.extend(current_repairs)
        issues.extend(current_issues)
        reads_closed = reads_closed or closed
    return additions, tuple(repairs), tuple(issues), reads_closed


def _same_context_object_values(
    first: tuple[ResolvedFunctionalValue, ...],
    second: tuple[ResolvedFunctionalValue, ...],
) -> bool:
    """Allow a resolver to select the required view of the same object."""

    return (
        len(first) == len(second) == 1
        and first[0].object_ref is not None
        and first[0].object_ref == second[0].object_ref
    )


def _resolve_condition_role_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolver: ContextClosureResolverSpec,
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
    bool,
]:
    """Expand a structured Condition into complete internal macro inputs."""

    conditions = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if value.runtime_type == "Condition"
        and value.object_roles
        and ConditionRoleResolver.supports(
            handle_registry.fact_types.get(value.handle, "")
        )
    )
    if not conditions:
        return {}, (), (), False
    if len(conditions) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.condition_role_ambiguous",
                    "multiple structured Conditions require role expansion",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"conditions": [item.handle for item in conditions]},
                ),
            ),
            False,
        )
    condition = conditions[0]
    target_hints = _condition_target_hints(
        call,
        scope_id=scope_id,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
    )
    endpoints = dict(condition.object_roles).get("endpoint", ())
    target_hints = unique_ordered(
        (
            *target_hints,
            *(
                endpoint
                for endpoint in endpoints
                if _condition_views_for_subject(
                    semantic_index,
                    condition_kind="orientation_constraint",
                    subject=endpoint,
                    scope_id=scope_id,
                )
            ),
        )
    )
    materialized_points = unique_ordered(
        (
            *(
                value.object_ref
                for value in produced.values()
                if value.runtime_type == "Point"
                and value.object_ref is not None
                and visible_from_valid_scope(
                    value.valid_scope,
                    scope_id=scope_id,
                    registry=handle_registry,
                )
            ),
            *(
                view.object_ref
                for view in semantic_index.compatible_views(
                    scope_id=scope_id,
                    accepted_types=("Point",),
                )
                if view.state_slot_id is not None
                and view.object_ref is not None
            ),
        )
    )
    try:
        roles = ConditionRoleResolver.resolve_constructed_point_roles(
            condition.object_roles,
            target_hints=target_hints,
            materialized_points=materialized_points,
        )
    except ConditionRoleResolutionError as exc:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    f"functional.{exc.code}",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details=exc.details,
                ),
            ),
            False,
        )

    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    anchor = _latest_point_state_for_object(
        roles.anchor,
        scope_id=scope_id,
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
    )
    reference = _latest_point_state_for_object(
        roles.reference,
        scope_id=scope_id,
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
    )
    for role_name, object_ref, value in (
        ("anchor", roles.anchor, anchor),
        ("reference", roles.reference, reference),
    ):
        if not _condition_resolver_role_is_used(
            capability,
            resolver,
            role_name,
        ):
            continue
        if value is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.condition_role_state_unavailable",
                    f"condition role {role_name} requires a computed Point state",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "role": role_name,
                        "object_ref": object_ref,
                        "accepted_item_types": ["Point"],
                    },
                )
            )
        else:
            additions[
                resolver.arg_name(role_name, capability.context_arg_bindings)
            ] = (value,)
    if _condition_resolver_role_is_used(
        capability,
        resolver,
        "target",
    ):
        additions[
            resolver.arg_name("target", capability.context_arg_bindings)
        ] = (
            ResolvedFunctionalValue(
                handle=roles.target,
                runtime_type="PointRef",
                valid_scope=handle_registry.handle_valid_scopes.get(
                    roles.target,
                    scope_id,
                ),
                object_ref=roles.target,
                dependency_object_refs=(roles.target,),
            ),
        )

    if _condition_resolver_role_is_used(
        capability,
        resolver,
        "orientation",
    ):
        orientation = _unique_condition_value(
            _condition_views_for_subject(
                semantic_index,
                condition_kind="orientation_constraint",
                subject=roles.target,
                scope_id=scope_id,
            ),
            role="orientation",
            call_id=call_id,
            scope_id=scope_id,
            issues=issues,
        )
        if orientation is not None:
            additions[
                resolver.arg_name(
                    "orientation",
                    capability.context_arg_bindings,
                )
            ] = (orientation,)

    symbol_refs = unique_ordered(
        dependency
        for value in (reference,)
        if value is not None
        for dependency in value.free_symbol_refs
        if dependency.startswith("symbol:")
    )
    needs_parameter = _condition_resolver_role_is_used(
        capability,
        resolver,
        "parameter",
    )
    parameter = None
    if needs_parameter and len(symbol_refs) != 1:
        issues.append(
            _issue(
                "functional_elaboration",
                (
                    "functional.condition_parameter_unresolved"
                    if not symbol_refs
                    else "functional.condition_parameter_ambiguous"
                ),
                "condition selection requires one parameter Symbol",
                call_id=call_id,
                scope_id=scope_id,
                details={"symbol_candidates": list(symbol_refs)},
            )
        )
    elif needs_parameter:
        parameter_handle = symbol_refs[0]
        parameter = ResolvedFunctionalValue(
            handle=parameter_handle,
            runtime_type="Symbol",
            valid_scope=handle_registry.handle_valid_scopes.get(
                parameter_handle,
                scope_id,
            ),
            object_ref=parameter_handle,
            dependency_object_refs=(parameter_handle,),
            free_symbol_refs=(parameter_handle,),
        )
        additions[
            resolver.arg_name("parameter", capability.context_arg_bindings)
        ] = (parameter,)

    if parameter is not None and _condition_resolver_role_is_used(
        capability,
        resolver,
        "parameter_constraint",
    ):
        parameter_constraint = _unique_condition_value(
            _condition_views_for_subject(
                semantic_index,
                condition_kind="symbol_constraint",
                subject=parameter.object_ref or parameter.handle,
                scope_id=scope_id,
            ),
            role="parameter_constraint",
            call_id=call_id,
            scope_id=scope_id,
            issues=issues,
        )
        if parameter_constraint is not None:
            additions[
                resolver.arg_name(
                    "parameter_constraint",
                    capability.context_arg_bindings,
                )
            ] = (
                parameter_constraint,
            )

    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "expand_condition_object_roles",
                condition.handle,
                ",".join(
                    (
                        f"anchor={roles.anchor}",
                        f"reference={roles.reference}",
                        f"target={roles.target}",
                    )
                ),
            ),
        ),
        (),
        True,
    )


def _condition_resolver_role_is_used(
    capability: FunctionalCapability,
    resolver: ContextClosureResolverSpec,
    semantic_role: str,
) -> bool:
    """Return whether this capability has the resolver's internal argument."""

    return resolver.arg_name_or_none(
        semantic_role,
        capability.context_arg_bindings,
    ) is not None


def _resolve_path_reduction_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolver: ContextClosureResolverSpec,
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
    bool,
]:
    if capability.kind != "macro" or not any(
        item.runtime_type == "PathTransformation"
        for item in capability.returns
    ):
        return {}, (), (), False
    path_targets = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if handle_registry.fact_types.get(value.handle)
        == "path_minimum_target"
    )
    if not path_targets:
        return {}, (), (), False
    if len(path_targets) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.path_reduction_target_ambiguous",
                    "path reduction requires one path-minimum target",
                    call_id=call_id,
                    scope_id=scope_id,
                ),
            ),
            False,
        )
    try:
        roles = PathReductionRoleResolver.resolve(
            path_target=path_targets[0].handle,
            scope_id=scope_id,
            registry=handle_registry,
        )
    except PathReductionRoleError as exc:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    f"functional.{exc.code}",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details=exc.details,
                ),
            ),
            False,
        )
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    for semantic_role, handle in (
        ("first_membership", roles.first_membership),
        ("second_membership", roles.second_membership),
        ("binding_relation", roles.binding_relation),
    ):
        arg_name = resolver.arg_name(
            semantic_role,
            capability.context_arg_bindings,
        )
        condition = _condition_value_by_handle(
            handle,
            semantic_index=semantic_index,
            scope_id=scope_id,
        )
        if condition is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.path_reduction_condition_unavailable",
                    f"path reduction condition is unavailable: {handle}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"arg": arg_name, "condition_handle": handle},
                )
            )
        else:
            additions[arg_name] = (condition,)
    for semantic_role, object_ref in (
        ("first_segment_start", roles.first_segment_start),
        ("joint_point", roles.joint_point),
        ("second_segment_end", roles.second_segment_end),
    ):
        arg_name = resolver.arg_name(
            semantic_role,
            capability.context_arg_bindings,
        )
        point = _latest_point_state_for_object(
            object_ref,
            scope_id=scope_id,
            produced=produced,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
        )
        if point is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.path_reduction_point_state_unavailable",
                    f"path reduction requires a computed Point state: {object_ref}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"arg": arg_name, "object_ref": object_ref},
                )
            )
        else:
            additions[arg_name] = (point,)
    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "expand_path_reduction_roles",
                roles.path_target,
                ",".join(
                    (
                        f"first_moving={roles.first_moving_point}",
                        f"second_moving={roles.second_moving_point}",
                        f"joint={roles.joint_point}",
                    )
                ),
            ),
        ),
        (),
        True,
    )


def _condition_value_by_handle(
    handle: str,
    *,
    semantic_index: FunctionalSemanticIndex,
    scope_id: str,
) -> ResolvedFunctionalValue | None:
    candidates = tuple(
        view
        for view in semantic_index.compatible_views(
            scope_id=scope_id,
            accepted_types=("Condition",),
        )
        if view.handle == handle
    )
    if len(candidates) != 1:
        return None
    item = candidates[0]
    return ResolvedFunctionalValue(
        handle=item.handle,
        runtime_type="Condition",
        valid_scope=item.valid_scope,
        condition_id=item.condition_id,
        object_roles=item.object_roles,
        dependency_object_refs=item.dependency_object_refs,
        free_symbol_refs=item.free_symbol_refs,
        source_state_slot_ids=item.source_state_slot_ids,
    )


def _condition_target_hints(
    call: FunctionalCall,
    *,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    result: list[str] = []
    for binding in call.return_bindings.values():
        result.extend(
            semantic_index.object_refs_for(binding, scope_id=scope_id)
        )
        if binding.kind == "answer":
            target = handle_registry.answer_target_handles.get(
                f"answer:{binding.ref}"
            )
            if target is not None:
                result.append(target)
    return unique_ordered(result)


def _latest_point_state_for_object(
    object_ref: str,
    *,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> ResolvedFunctionalValue | None:
    dynamic = tuple(
        value
        for value in produced.values()
        if value.runtime_type == "Point"
        and value.object_ref == object_ref
        and visible_from_valid_scope(
            value.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    )
    if dynamic:
        return dynamic[-1]
    views = tuple(
        view
        for view in semantic_index.compatible_views(
            scope_id=scope_id,
            accepted_types=("Point",),
        )
        if view.object_ref == object_ref and view.state_slot_id is not None
    )
    if not views:
        return None
    view = views[-1]
    return ResolvedFunctionalValue(
        handle=view.handle,
        runtime_type=view.runtime_type,
        valid_scope=view.valid_scope,
        state_slot_id=view.state_slot_id,
        object_ref=view.object_ref,
        dependency_object_refs=view.dependency_object_refs,
        free_symbol_refs=view.free_symbol_refs,
        source_state_slot_ids=view.source_state_slot_ids,
    )


def _condition_views_for_subject(
    semantic_index: FunctionalSemanticIndex,
    *,
    condition_kind: str,
    subject: str,
    scope_id: str,
) -> tuple[Any, ...]:
    return tuple(
        view
        for view in semantic_index.compatible_views(
            scope_id=scope_id,
            accepted_types=("Condition",),
            accepted_condition_kinds=(condition_kind,),
        )
        if semantic_index.handle_registry.fact_payloads.get(
            view.handle,
            {},
        ).get("subject") == subject
    )


def _unique_condition_value(
    candidates: Sequence[Any],
    *,
    role: str,
    call_id: str,
    scope_id: str,
    issues: list[FunctionalPlanIssue],
) -> ResolvedFunctionalValue | None:
    unique = {item.handle: item for item in candidates}
    if len(unique) != 1:
        issues.append(
            _issue(
                "functional_elaboration",
                (
                    "functional.condition_role_condition_missing"
                    if not unique
                    else "functional.condition_role_condition_ambiguous"
                ),
                f"condition role {role} requires one matching Condition",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "role": role,
                    "condition_candidates": sorted(unique),
                },
            )
        )
        return None
    item = next(iter(unique.values()))
    return ResolvedFunctionalValue(
        handle=item.handle,
        runtime_type="Condition",
        valid_scope=item.valid_scope,
        condition_id=item.condition_id,
        object_roles=item.object_roles,
        dependency_object_refs=item.dependency_object_refs,
        free_symbol_refs=item.free_symbol_refs,
        source_state_slot_ids=item.source_state_slot_ids,
    )


def _resolve_deterministic_optional_args(
    capability: Any,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
]:
    """Resolve optional state views only through declared generic primitives."""

    existing_handles = {
        value.handle for values in resolved_args.values() for value in values
    }
    related_objects = {
        dependency
        for values in resolved_args.values()
        for value in values
        for dependency in (
            *value.dependency_object_refs,
            *((value.object_ref,) if value.object_ref else ()),
        )
    }
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    for arg in capability.args:
        if (
            arg.name in resolved_args
            or arg.required
            or arg.cardinality == "many"
            or arg.deterministic_resolver != "unique_related_state"
        ):
            continue
        accepted_types = arg.accepted_item_types or (arg.runtime_type,)
        candidates = [
            value
            for value in produced.values()
            if value.handle not in existing_handles
            and visible_from_valid_scope(
                value.valid_scope,
                scope_id=scope_id,
                registry=handle_registry,
            )
            and any(
                runtime_type_compatible(expected, value.runtime_type)
                for expected in accepted_types
            )
        ]
        candidates.extend(
            ResolvedFunctionalValue(
                handle=view.handle,
                runtime_type=view.runtime_type,
                valid_scope=view.valid_scope,
                state_slot_id=view.state_slot_id,
                object_ref=view.object_ref,
                dependency_object_refs=view.dependency_object_refs,
                free_symbol_refs=view.free_symbol_refs,
                source_state_slot_ids=view.source_state_slot_ids,
            )
            for view in semantic_index.compatible_views(
                scope_id=scope_id,
                accepted_types=accepted_types,
                accepted_condition_kinds=arg.accepted_condition_kinds,
            )
            if view.handle not in existing_handles
        )
        if related_objects:
            candidates = [
                value
                for value in candidates
                if related_objects
                & {
                    *value.dependency_object_refs,
                    *((value.object_ref,) if value.object_ref else ()),
                }
            ]
        unique_candidates: dict[
            tuple[str, str | None, str | None], ResolvedFunctionalValue
        ] = {}
        for value in candidates:
            unique_candidates.setdefault(
                (value.handle, value.object_ref, value.source_call_id),
                value,
            )
        if len(unique_candidates) != 1:
            continue
        selected = next(iter(unique_candidates.values()))
        additions[arg.name] = (selected,)
        existing_handles.add(selected.handle)
        repairs.append(
            FunctionalDeterministicRepair(
                call_id,
                "auto_fill_optional_arg",
                f"{arg.name}=omitted",
                f"{arg.name}={selected.object_ref or selected.handle}",
            )
        )
    return additions, tuple(repairs)


def _resolve_context_auto_args(
    capability: Any,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
]:
    """Resolve hidden object selectors through Context object identity."""
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []
    for auto in capability.auto_args:
        if auto.name in resolved_args:
            continue
        if midpoint_endpoint_position(auto.selector) is not None:
            value, repair, issue = _resolve_midpoint_auto_arg(
                auto,
                resolved_args=resolved_args,
                produced=produced,
                semantic_index=semantic_index,
                handle_registry=handle_registry,
                call_id=call_id,
                scope_id=scope_id,
            )
            if value is not None:
                additions[auto.name] = (value,)
            if repair is not None:
                repairs.append(repair)
            if issue is not None:
                issues.append(issue)
            continue
        if not auto.selector.startswith("function:"):
            continue
        object_name = auto.selector.split(":", 1)[1]
        dynamic = [
            value
            for value in produced.values()
            if value.object_ref is not None
            and value.object_ref.startswith("function:")
            and value.object_ref.rsplit(":", 1)[-1] == object_name
            and value.runtime_type in {"Function", "Parabola"}
            and visible_from_valid_scope(
                value.valid_scope,
                scope_id=scope_id,
                registry=handle_registry,
            )
        ]
        if dynamic:
            candidates = [dynamic[-1]]
        else:
            candidates = [
                ResolvedFunctionalValue(
                    handle=view.handle,
                    runtime_type=view.runtime_type,
                    valid_scope=view.valid_scope,
                    state_slot_id=view.state_slot_id,
                    object_ref=view.object_ref,
                    dependency_object_refs=view.dependency_object_refs,
                    free_symbol_refs=view.free_symbol_refs,
                    source_state_slot_ids=view.source_state_slot_ids,
                )
                for view in semantic_index.compatible_views(
                    scope_id=scope_id,
                    accepted_types=("Function", "Parabola"),
                )
                if view.object_ref is not None
                and view.object_ref.startswith("function:")
                and view.object_ref.rsplit(":", 1)[-1] == object_name
            ]
        candidates_by_object = {
            candidate.object_ref: candidate
            for candidate in candidates
            if candidate.object_ref is not None
        }
        if len(candidates_by_object) == 1:
            selected = next(iter(candidates_by_object.values()))
            object_ref = selected.object_ref
            if object_ref is None:
                issues.append(
                    _issue(
                        "functional_elaboration",
                        "functional.auto_arg_identity_unresolved",
                        (
                            "auto-selected function state has no object "
                            f"identity for argument {auto.name}"
                        ),
                        call_id=call_id,
                        scope_id=scope_id,
                        details={
                            "arg": auto.name,
                            "selector": auto.selector,
                            "selected_handle": selected.handle,
                        },
                    )
                )
                continue
            # ``function:<name>`` selectors bind object identity. They must not
            # turn the latest Parabola value into an implicit data dependency;
            # an intervening function-state write is relevant only when a
            # public semantic arg explicitly reads that value.
            additions[auto.name] = (
                ResolvedFunctionalValue(
                    handle=object_ref,
                    runtime_type="Function",
                    valid_scope=handle_registry.handle_valid_scopes.get(
                        object_ref,
                        selected.valid_scope,
                    ),
                    object_ref=object_ref,
                    dependency_object_refs=(object_ref,),
                ),
            )
            repairs.append(
                FunctionalDeterministicRepair(
                    call_id,
                    "auto_fill_object_arg",
                    f"{auto.name}=omitted",
                    f"{auto.name}={object_ref}",
                )
            )
            continue
        if auto.required:
            issues.append(
                _issue(
                    "functional_elaboration",
                    (
                        "functional.auto_arg_unresolved"
                        if not candidates_by_object
                        else "functional.auto_arg_ambiguous"
                    ),
                    f"object identity cannot be determined for {auto.name}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": auto.name,
                        "available_refs": sorted(
                            item for item in candidates_by_object if item
                        ),
                    },
                )
            )
    return additions, tuple(repairs), tuple(issues)


def _resolve_midpoint_auto_arg(
    auto: Any,
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
    call_id: str,
    scope_id: str,
) -> tuple[
    ResolvedFunctionalValue | None,
    FunctionalDeterministicRepair | None,
    FunctionalPlanIssue | None,
]:
    """Resolve midpoint endpoints from structured Condition evidence."""
    condition_match = next(
        (
            (arg_name, value)
            for arg_name, values in resolved_args.items()
            for value in values
            if handle_registry.fact_types.get(value.handle)
            == "midpoint_definition"
        ),
        None,
    )
    condition_arg = condition_match[0] if condition_match is not None else None
    condition = condition_match[1] if condition_match is not None else None
    payload = (
        handle_registry.fact_payloads.get(condition.handle, {})
        if condition is not None
        else {}
    )
    endpoints = payload.get("of")
    position = midpoint_endpoint_position(auto.selector)
    if position is None:
        raise ValueError(
            "planner_configuration_error: unsupported midpoint selector: "
            f"{auto.selector}"
        )
    endpoint_value = (
        str(endpoints[position])
        if isinstance(endpoints, list) and len(endpoints) > position
        else None
    )
    endpoint_ref = endpoint_value
    if endpoint_value is not None and endpoint_value.startswith("point:"):
        object_refs = (endpoint_value,)
        entity = handle_registry.entity_payloads.get(endpoint_value, {})
        visible_refs = unique_ordered(
            view.ref
            for view in semantic_index.views
            if view.kind == "point"
            and view.object_ref == endpoint_value
        )
        endpoint_ref = next(
            (ref for ref in visible_refs if "." in ref),
            str(
                entity.get("semantic_ref")
                or endpoint_value.rsplit(":", 1)[-1]
            ),
        )
    else:
        object_refs = (
            semantic_index.object_refs_for(
                SemanticRef(ref=endpoint_value, kind="point"),
                scope_id=scope_id,
            )
            if endpoint_value is not None
            else ()
        )
    dynamic = [
        value
        for value in produced.values()
        if value.runtime_type == "Point"
        and value.state_slot_id is not None
        and value.object_ref in object_refs
        and visible_from_valid_scope(
            value.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    ]
    selected = dynamic[-1] if dynamic else None
    if selected is None and endpoint_ref is not None:
        state_views = [
            view
            for view in semantic_index.compatible_views(
                scope_id=scope_id,
                accepted_types=("Point",),
            )
            if view.state_slot_id is not None
            and view.object_ref in object_refs
        ]
        selected_view = state_views[-1] if state_views else None
        if selected_view is not None:
            selected = ResolvedFunctionalValue(
                handle=selected_view.handle,
                runtime_type=selected_view.runtime_type,
                valid_scope=selected_view.valid_scope,
                state_slot_id=selected_view.state_slot_id,
                object_ref=selected_view.object_ref,
                dependency_object_refs=selected_view.dependency_object_refs,
                free_symbol_refs=selected_view.free_symbol_refs,
                source_state_slot_ids=selected_view.source_state_slot_ids,
            )
    if selected is not None:
        return (
            selected,
            FunctionalDeterministicRepair(
                call_id,
                "resolve_condition_endpoint_state",
                f"{auto.name}=omitted",
                f"{auto.name}={endpoint_ref}",
            ),
            None,
        )
    return (
        None,
        None,
        _issue(
            "functional_elaboration",
            "functional.arg_state_unavailable",
            (
                f"argument {condition_arg or 'midpoint_definition'} requires "
                f"a materialized Point state for "
                f"{endpoint_ref or 'a midpoint endpoint'}"
            ),
            call_id=call_id,
            scope_id=scope_id,
            details={
                "arg": condition_arg or "midpoint_definition",
                "hidden_arg": auto.name,
                "selector": auto.selector,
                "semantic_role": "midpoint_endpoint",
                "accepted_item_types": ["Point"],
                "state_requirement": "materialized_state",
                "required_ref": endpoint_ref,
                "unresolved_point_ref": endpoint_ref,
                "error_code": "function.arg_state_unavailable",
                **(
                    {"object_ref": object_refs[0]}
                    if len(object_refs) == 1
                    else {}
                ),
            },
        ),
    )


def _resolve_auto_symbol_args(
    capability: Any,
    resolved_args: dict[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
    identity_hints: Sequence[str] = (),
) -> tuple[FunctionalPlanIssue, ...]:
    identity_args = {
        item.identity_arg
        for item in capability.returns
        if item.identity_policy == "preserve_input_object" and item.identity_arg
    }
    auto_by_name = {item.name: item for item in capability.auto_args}
    semantic_auto_by_name = {
        item.name: item
        for item in capability.args
        if item.deterministic_resolver == "unique_parameter_symbol"
    }
    issues: list[FunctionalPlanIssue] = []
    for arg_name in identity_args:
        if arg_name in resolved_args:
            continue
        auto = auto_by_name.get(arg_name)
        semantic_auto = semantic_auto_by_name.get(arg_name)
        if (
            semantic_auto is None
            and (auto is None or "parameter" not in auto.selector)
        ):
            continue
        hinted_symbols = tuple(
            dependency
            for dependency in unique_ordered(identity_hints)
            if dependency.startswith("symbol:")
        )
        input_symbols = tuple(
            dependency
            for dependency in unique_ordered(
                dependency
                for values in resolved_args.values()
                for value in values
                for dependency in (
                    *value.free_symbol_refs,
                    *(
                        (value.object_ref,)
                        if value.runtime_type == "Symbol" and value.object_ref
                        else ()
                    ),
                )
            )
            if dependency.startswith("symbol:")
        )
        # A later explicit consumer is stronger identity evidence than the
        # producer's unresolved-symbol estimate.
        candidates = hinted_symbols if hinted_symbols else input_symbols
        if len(candidates) != 1:
            issues.append(
                _issue(
                    "functional_elaboration",
                    (
                        "functional.auto_arg_unresolved"
                        if not candidates
                        else "functional.auto_arg_ambiguous"
                    ),
                    f"parameter identity cannot be determined for {arg_name}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": arg_name,
                        "available_symbol_refs": list(candidates),
                    },
                )
            )
            continue
        symbol = candidates[0]
        resolved_args[arg_name] = (
            ResolvedFunctionalValue(
                handle=symbol,
                runtime_type="Symbol",
                valid_scope=scope_id,
                object_ref=symbol,
                dependency_object_refs=(symbol,),
                free_symbol_refs=(symbol,),
            ),
        )
    return tuple(issues)


def _functional_ref_role(ref: FunctionalRef) -> str:
    if isinstance(ref, CallResultRef):
        return ref.return_name
    return ref.ref.rsplit(".", 1)[-1]


def _return_binding_identity_hints(
    capability: Any,
    call: FunctionalCall,
    *,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[str, ...]:
    """Use declared return identity to recover its hidden input object.

    A ``preserve_input_object`` return is the same semantic object as its
    ``identity_arg``. When the LLM binds that return to an existing object, the
    binding is stronger identity evidence than transitive dependencies of the
    input expression. This is contract-driven and applies to any object type;
    the auto-symbol resolver below selects the Symbol subset it understands.
    """
    return unique_ordered(
        object_ref
        for item in capability.returns
        if item.identity_policy == "preserve_input_object"
        and item.identity_arg
        for binding in (call.return_bindings.get(item.name),)
        if binding is not None
        for object_ref in semantic_index.object_refs_for(
            binding,
            scope_id=scope_id,
        )
    )


def _argument_dependencies(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[str, ...]:
    return unique_ordered(
        dependency
        for values in args.values()
        for value in values
        for dependency in (
            *value.dependency_object_refs,
            *(
                (value.object_ref,)
                if value.runtime_type == "Symbol" and value.object_ref
                else ()
            ),
        )
    )


def _argument_source_slots(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[str, ...]:
    return unique_ordered(
        slot_id
        for values in args.values()
        for value in values
        for slot_id in (
            *value.source_state_slot_ids,
            *((value.state_slot_id,) if value.state_slot_id else ()),
        )
    )


def _infer_target_object_binding(
    *,
    return_spec: FunctionalCapabilityReturn,
    scope_id: str,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_items: Sequence[SemanticReadCatalogItem],
    semantic_index: FunctionalSemanticIndex,
    planner_state_context: PlannerStateContext,
    handle_registry: CanonicalHandleRegistry,
    allow_role_inference: bool,
) -> SemanticReadCatalogItem | None:
    """Resolve a target object only when structured evidence is unique.

    The resolver consumes ProblemIR relationships and Context state identity. It
    deliberately ignores descriptions and capability ids, so a missing binding
    cannot turn into a method-specific naming heuristic.
    """

    entity_kind = object_kind_for_runtime_type(return_spec.runtime_type)
    if entity_kind is None:
        return None
    problem_ir = planner_state_context.state.problem_ir
    entity_payloads = {
        item.get("handle"): item
        for item in problem_ir.get("entities", ())
        if isinstance(item, dict)
        and isinstance(item.get("handle"), str)
        and item.get("entity_type") == entity_kind
    }
    if not entity_payloads:
        return None
    visible_entities = {
        handle: payload
        for handle, payload in entity_payloads.items()
        if visible_from_valid_scope(
            str(payload.get("scope_id") or "problem"),
            scope_id=scope_id,
            registry=handle_registry,
        )
    }
    catalog_items = {
        item.handle: item
        for item in semantic_items
        if item.handle in visible_entities
        and item.kind == entity_kind
        and item.prompt_visible
    }
    if not catalog_items:
        return None
    if return_spec.identity_arg:
        identity_handles = {
            value.object_ref
            for value in resolved_args.get(return_spec.identity_arg, ())
            if value.object_ref in catalog_items
        }
        if len(identity_handles) == 1:
            return catalog_items[next(iter(identity_handles))]

    fact_payloads = {
        item.get("handle"): item
        for item in problem_ir.get("facts", ())
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    direct_targets = {
        handle
        for values in resolved_args.values()
        for value in values
        for handle in _structured_target_handles(
            fact_payloads.get(value.handle, {})
        )
        if handle in visible_entities
    }
    available_objects = {
        item.object_ref
        for item in semantic_index.views
        if item.object_ref in visible_entities
        and item.state_slot_id is not None
        and runtime_type_compatible(return_spec.runtime_type, item.runtime_type)
        and visible_from_valid_scope(
            item.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    }
    available_objects.update(
        value.object_ref
        for value in produced.values()
        if value.object_ref in visible_entities
        and runtime_type_compatible(return_spec.runtime_type, value.runtime_type)
    )
    unresolved_targets = direct_targets - available_objects
    if len(unresolved_targets) == 1:
        return catalog_items.get(next(iter(unresolved_targets)))
    if not allow_role_inference:
        return None
    structural_dependencies = {
        handle
        for values in resolved_args.values()
        for value in values
        for handle in _structured_object_handles(
            fact_payloads.get(value.handle, {})
        )
        if handle in visible_entities
    }
    unresolved_dependencies = structural_dependencies - available_objects
    if len(unresolved_dependencies) == 1:
        return catalog_items.get(next(iter(unresolved_dependencies)))

    argument_objects = {
        value.object_ref
        for values in resolved_args.values()
        for value in values
        if value.object_ref in visible_entities
    }
    role_tokens = _identity_tokens(return_spec.semantic_role)
    role_key = _identity_key(return_spec.semantic_role)
    answer_targets = set(handle_registry.answer_target_handles.values())
    scored: list[tuple[int, str]] = []
    for handle, payload in visible_entities.items():
        structural_score = 0
        definition = str(payload.get("definition") or payload.get("role") or "")
        definition_tokens = _identity_tokens(definition)
        overlap = role_tokens & definition_tokens
        definition_key = _identity_key(definition)
        role_matches_definition = bool(overlap) or bool(
            role_key and role_key == definition_key
        )
        # Related input objects identify a target only inside a compatible
        # structural role. Without this guard, an arbitrary construction that
        # reads D and N could incorrectly infer their midpoint as its output.
        if not role_matches_definition:
            continue
        if overlap:
            structural_score += 3 * len(overlap)
        if role_key and role_key == definition_key:
            structural_score += 8
        related_objects = {
            item
            for item in _structured_object_handles(payload.get("of"))
            if item != handle
        }
        if related_objects and related_objects <= argument_objects:
            structural_score += 8 + len(related_objects)
        if structural_score == 0:
            continue
        if str(payload.get("scope_id") or "problem") == scope_id:
            structural_score += 5
        score = structural_score + (4 if handle in answer_targets else 0)
        scored.append((score, handle))
    if not scored:
        return None
    best_score = max(score for score, _handle in scored)
    best_handles = [handle for score, handle in scored if score == best_score]
    if len(best_handles) != 1:
        return None
    return catalog_items.get(best_handles[0])


def _target_item_from_object_hints(
    object_hints: Sequence[str],
    *,
    return_spec: FunctionalCapabilityReturn,
    scope_id: str,
    semantic_items: Sequence[SemanticReadCatalogItem],
    handle_registry: CanonicalHandleRegistry,
) -> SemanticReadCatalogItem | None:
    """Resolve one downstream-proven object identity to its semantic item."""
    if len(set(object_hints)) != 1:
        return None
    object_ref = object_hints[0]
    entity_kind = object_kind_for_runtime_type(return_spec.runtime_type)
    candidates = tuple(
        item
        for item in semantic_items
        if item.prompt_visible
        and item.handle == object_ref
        and item.kind == entity_kind
        and visible_from_valid_scope(
            item.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    )
    return candidates[0] if len(candidates) == 1 else None


def _compatible_target_object_refs(
    *,
    return_spec: FunctionalCapabilityReturn,
    scope_id: str,
    semantic_items: Sequence[SemanticReadCatalogItem],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """List visible object refs for an unresolved target identity ticket.

    This is intentionally a candidate list, not an inference rule. When
    structured evidence cannot choose one object, the LLM receives the exact
    semantic refs it may bind without exposing canonical handles.
    """
    entity_kind = object_kind_for_runtime_type(return_spec.runtime_type)
    if entity_kind is None:
        return ()
    return unique_ordered(
        item.ref
        for item in semantic_items
        if item.prompt_visible
        and item.kind == entity_kind
        and visible_from_valid_scope(
            item.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    )


def _target_binding_identity(
    item: SemanticReadCatalogItem,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> str:
    """Return object identity behind an entity or answer semantic binding."""
    if item.kind == "answer":
        return handle_registry.answer_target_handles.get(item.handle, item.handle)
    return item.handle


def _unique_answer_for_object_binding(
    binding: SemanticReadCatalogItem,
    *,
    return_type: str,
    question_goals: Sequence[QuestionGoal],
    semantic_items: Sequence[SemanticReadCatalogItem],
    handle_registry: CanonicalHandleRegistry,
) -> SemanticReadCatalogItem | None:
    """Promote an explicit terminal object binding to its unique answer slot."""
    compatible_handles = {
        f"answer:{goal.id}"
        for goal in question_goals
        if goal.required
        and answer_output_type_compatible(goal.value_type, return_type)
        and handle_registry.answer_target_handles.get(f"answer:{goal.id}")
        == binding.handle
    }
    candidates = [
        item
        for item in semantic_items
        if item.kind == "answer"
        and item.handle in compatible_handles
        and item.prompt_visible
    ]
    return candidates[0] if len(candidates) == 1 else None


def _structured_object_handles(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if is_object_handle(value) else ()
    if isinstance(value, Mapping):
        return unique_ordered(
            handle
            for item in value.values()
            for handle in _structured_object_handles(item)
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return unique_ordered(
            handle
            for item in value
            for handle in _structured_object_handles(item)
        )
    return ()


def _structured_target_handles(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Read only fields that explicitly name the semantic target object."""
    return unique_ordered(
        handle
        for key in (
            "point",
            "target",
            "target_point",
            "subject",
        )
        for handle in _structured_object_handles(payload.get(key))
    )


def _identity_tokens(value: str) -> set[str]:
    generic = {
        "coordinate",
        "derived",
        "object",
        "output",
        "point",
        "result",
        "selected",
        "target",
        "value",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token not in generic
    }


def _identity_key(value: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", value.lower()))
