"""Typed Context reconciliation for FunctionalPlan."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.contracts import (
    FunctionalResultForm,
    SymbolicClosureSpec,
)
from shuxueshuo_server.solver.family.models import (
    CapabilityStateClosurePolicy,
    EvidenceInputGroupSpec,
    SolverFamilySpec,
    StateIdentityConstraintSpec,
)
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.context_closure import (
    midpoint_endpoint_position,
)
from shuxueshuo_server.solver.runtime.binding_selector_semantics import (
    selector_semantics,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_context_values import (
    latest_point_state_for_object as _latest_point_state_for_object,
)
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalBindingContextBuilder,
    audit_functional_arg_binding_projection,
    build_functional_runtime_arg_bindings_from_context,
)
from shuxueshuo_server.solver.runtime.functional_context_closure_handlers import (
    resolve_context_closure_args as _resolve_context_closure_args,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
    FunctionalPlanElaborationResult,
    FunctionalPlanElaborator,
    FunctionalSemanticIndex,
    FunctionalSemanticView,
)
from shuxueshuo_server.solver.runtime.functional_input_closure import (
    resolve_functional_input_closure,
)
from shuxueshuo_server.solver.runtime.functional_plan_liveness import (
    FunctionalCallLivenessAnalyzer,
)
from shuxueshuo_server.solver.runtime.functional_object_identity_hints import (
    infer_future_return_object_hints,
)
from shuxueshuo_server.solver.runtime.functional_reconciliation_validators import (
    functional_reconciliation_issues,
)
from shuxueshuo_server.solver.runtime.functional_symbol_flow import (
    align_free_parameter_basis_with_consumers,
    infer_unique_target_symbol_ref,
    return_free_symbol_refs,
)
from shuxueshuo_server.solver.runtime.functional_symbol_identity import (
    symbol_ids_from_refs,
)
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpec
from shuxueshuo_server.solver.runtime.functional_debug_aliases import (
    functional_call_local_debug_alias,
    functional_state_slot_debug_alias,
    legacy_state_slot_aliases,
)
from shuxueshuo_server.solver.runtime.functional_typed_identity import (
    FunctionalTypedIdentityCompleteness,
    FunctionalTypedIdentityValidator,
)
from shuxueshuo_server.solver.runtime.functional_evidence import (
    closure_lineages as successful_closure_lineages,
    evaluate_lineage_closure,
)
from shuxueshuo_server.solver.runtime.functional_state_allocation import (
    functional_computation_key,
    functional_source_version_ids,
    identity_shadow_comparison,
    project_sibling_symbol_dependencies,
    rebase_live_state_versions,
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
    FunctionalCapabilityArg,
    FunctionalCall,
    FunctionalCallReport,
    FunctionalCapabilityReturn,
    FunctionalCallExecutionEntry,
    FunctionalCallReconciliation,
    FunctionalPlan,
    FunctionalPlanIssue,
    FunctionalPlanReconciliationResult,
    FunctionalRef,
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
    _issue,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import visible_from_valid_scope
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.planner_state_context import PlannerStateContext
from shuxueshuo_server.solver.runtime.semantic_reads import SemanticReadCatalogItem
from shuxueshuo_server.solver.runtime.state_identity import (
    IdentityShadowComparison,
    LogicalReturnEffect,
    MathObjectId,
    MathObjectRegistry,
    RuntimeDestinationKey,
    ScopeVisibilityResolver,
    StateAllocationRequest,
    StateAllocationService,
    StateEffectKey,
    StateIdentityFactory,
    StateIdentityIndex,
    StateIdentityMode,
    StatePlacementMode,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    StateFinalizationResult,
    StateFinalizationService,
    StateFinalizerMode,
    expand_functional_dependency_graph,
    build_functional_state_dependencies,
    build_functional_state_write_manifest,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    normalize_runtime_type,
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)
from shuxueshuo_server.solver.runtime.straightening_metadata import (
    canonical_straightening_endpoint_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    SemanticRef,
    answer_value_type_requires_closed_scalar,
    functional_answer_output_type_compatible,
)
from shuxueshuo_server.solver.runtime.state_identity_constraints import (
    StateIdentityConstraintValidator,
    infer_unique_return_object_refs,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    StateSemanticLineage,
    StateSymbolClosureBinding,
    derived_role_object_ref,
    is_object_handle,
    is_object_semantic_kind,
    merge_state_semantic_lineages,
    object_kind_for_runtime_type,
    object_semantic_kind_for_handle,
    runtime_type_for_object_semantic_kind,
    state_object_refs_for_role,
    state_semantic_lineage,
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
    semantic_object_consumers: dict[
        tuple[str, str],
        tuple[tuple[str, str], ...],
    ]
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
        pinned_canonical_call_ids: frozenset[str] = frozenset(),
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
        plan, semantic_return_role_repairs = (
            _normalize_declared_return_role_aliases(
                plan,
                catalog=catalog,
            )
        )
        plan, return_role_repairs = _normalize_unique_return_roles(
            plan,
            catalog=catalog,
            semantic_index=semantic_index,
        )
        plan, answer_binding_repairs = _normalize_functional_answer_bindings(
            plan,
            catalog=catalog,
            question_goals=question_goals,
            handle_registry=handle_registry,
            semantic_items=semantic_items,
        )
        plan, existing_state_repairs = _drop_redundant_existing_state_creates(
            plan,
            catalog=catalog,
            semantic_index=semantic_index,
        )
        plan, incomplete_transition_repairs = (
            _drop_redundant_incomplete_identity_transitions(
                plan,
                catalog=catalog,
                semantic_index=semantic_index,
            )
        )
        plan, basis_repairs = align_free_parameter_basis_with_consumers(
            plan,
            catalog=catalog,
            semantic_index=semantic_index,
        )
        plan, target_identity_repairs = (
            _infer_symbolic_target_args_from_consumers(
                plan,
                catalog=catalog,
            )
        )
        elaboration = FunctionalPlanElaborator().elaborate(
            plan,
            catalog=catalog,
            semantic_index=semantic_index,
            pinned_canonical_call_ids=pinned_canonical_call_ids,
        )
        elaboration = replace(
            elaboration,
            issues=(*ordering_issues, *elaboration.issues),
            deterministic_repairs=(
                *ordering_repairs,
                *semantic_return_role_repairs,
                *return_role_repairs,
                *existing_state_repairs,
                *incomplete_transition_repairs,
                *basis_repairs,
                *target_identity_repairs,
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
        placement_service = FunctionalCallPlacementService()
        # Resolve logical values in the declared scope first. Final execution
        # placement needs the dynamic StateSlot dependencies discovered during
        # reconciliation; moving a consumer before those edges exist can make
        # an otherwise valid producer result appear invisible.
        call_execution_scopes = dict(call_scopes)
        requested_scopes = {
            (call_id, return_name): _least_common_scope(
                (call_scopes[call_id], *scopes),
                handle_registry,
            )
            for (call_id, return_name), scopes in consumers.items()
            if call_id in call_scopes
        }
        future_return_object_hints = _future_return_object_hints(
            plan,
            catalog=catalog,
            semantic_index=semantic_index,
        )
        dependency_graph = _with_hidden_condition_object_dependencies(
            plan,
            dependency_graph=_functional_dependency_graph(plan),
            catalog=catalog,
            semantic_index=semantic_index,
            future_return_object_hints=future_return_object_hints,
        )
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
            future_return_object_hints=future_return_object_hints,
            call_scopes=call_scopes,
            call_result_consumers=consumers,
            call_execution_scopes=call_execution_scopes,
            semantic_object_consumers=_semantic_object_consumer_scopes(
                plan,
                semantic_index=semantic_index,
                catalog=catalog,
                future_return_object_hints=future_return_object_hints,
            ),
            requested_scopes=requested_scopes,
            dependency_graph=dependency_graph,
            planned_target_objects=_planned_target_objects(
                plan,
                catalog=catalog,
                handle_registry=handle_registry,
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


def _drop_redundant_existing_state_creates(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Replace redundant pure creates with the existing materialized state.

    This normalization runs before call resolution so later semantic object
    reads select the Context state instead of the invalid duplicate producer.
    Explicit CallResultRefs are rewritten before the producer is removed, so
    graph editing never leaves a dangling reference.
    """
    consumers = _call_result_consumers(plan)
    dropped: set[str] = set()
    replacement_refs: dict[tuple[str, str], SemanticRef] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    for scope in plan.scopes:
        for call in scope.calls:
            capability = catalog.get(call.capability_id)
            if (
                capability is None
                or capability.kind != "function"
                or not capability.is_pure
                or not call.return_bindings
            ):
                continue
            if any(
                binding.kind == "answer"
                for binding in call.return_bindings.values()
            ):
                continue
            return_by_name = {
                item.name: item for item in capability.returns
            }
            existing_results = []
            for return_name, binding in call.return_bindings.items():
                returned = return_by_name.get(return_name)
                if returned is None or returned.write_mode != "create":
                    break
                resolved, _candidates = semantic_index.resolve(
                    binding,
                    scope_id=scope.scope_id,
                    accepted_types=(returned.runtime_type,),
                )
                if (
                    resolved is None
                    or resolved.state_slot_id is None
                    or resolved.object_ref is None
                ):
                    break
                existing_results.append((return_name, binding, resolved))
            else:
                if len(existing_results) != len(call.return_bindings):
                    continue
                consumed_returns = {
                    return_name
                    for (call_id, return_name) in consumers
                    if call_id == call.call_id
                }
                replacement_by_return = {
                    return_name: binding
                    for return_name, binding, _resolved in existing_results
                }
                if not consumed_returns.issubset(replacement_by_return):
                    continue
                dropped.add(call.call_id)
                replacement_refs.update(
                    {
                        (call.call_id, return_name): binding
                        for return_name, binding in replacement_by_return.items()
                    }
                )
                repairs.append(
                    FunctionalDeterministicRepair(
                        call.call_id,
                        (
                            "rewrite_redundant_pure_function_call_to_existing_state"
                            if consumed_returns
                            else "drop_dead_pure_function_call"
                        ),
                        call.capability_id,
                        "existing_materialized_object_state",
                    )
                )
    if not dropped:
        return plan, ()

    def rewrite_call_result_ref(ref: FunctionalRef) -> FunctionalRef:
        if not isinstance(ref, CallResultRef):
            return ref
        return replacement_refs.get((ref.from_call, ref.return_name), ref)

    return (
        replace(
            plan,
            scopes=tuple(
                replace(
                    scope,
                    calls=tuple(
                        replace(
                            call,
                            args={
                                name: tuple(
                                    rewrite_call_result_ref(ref)
                                    for ref in refs
                                )
                                for name, refs in call.args.items()
                            },
                        )
                        for call in scope.calls
                        if call.call_id not in dropped
                    ),
                )
                for scope in plan.scopes
                if any(
                    call.call_id not in dropped for call in scope.calls
                )
            ),
        ),
        tuple(repairs),
    )


def _drop_redundant_incomplete_identity_transitions(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Replace a provable no-op transition with its existing input state.

    This only handles an incomplete same-object transition whose sole missing
    required input is a ParameterValue and whose requested result remains open.
    It never invents a parameter value or claims that an open state is closed.
    """

    consumers = _call_result_consumers(plan)
    dropped: set[str] = set()
    replacement_refs: dict[tuple[str, str], FunctionalRef] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    for scope in plan.scopes:
        for call in scope.calls:
            capability = catalog.get(call.capability_id)
            if (
                capability is None
                or capability.kind != "function"
                or not capability.is_pure
            ):
                continue
            missing = tuple(
                arg
                for arg in capability.args
                if arg.required and not call.args.get(arg.name)
            )
            if not missing or any(
                not all(
                    normalize_runtime_type(item) == "ParameterValue"
                    for item in (
                        arg.accepted_item_types or (arg.runtime_type,)
                    )
                )
                for arg in missing
            ):
                continue
            transitions = tuple(
                returned
                for returned in capability.returns
                if returned.write_mode == "transition"
                and returned.identity_policy == "preserve_input_object"
                and returned.identity_arg
            )
            if len(transitions) != 1 or len(capability.returns) != 1:
                continue
            returned = transitions[0]
            if (
                set(call.return_bindings) - {returned.name}
                or set(call.return_expectations) - {returned.name}
            ):
                continue
            identity_refs = call.args.get(returned.identity_arg or "", ())
            if len(identity_refs) != 1:
                continue
            source_ref = identity_refs[0]
            if isinstance(source_ref, SemanticRef):
                resolved, _candidates = semantic_index.resolve(
                    source_ref,
                    scope_id=scope.scope_id,
                    accepted_types=(returned.runtime_type,),
                )
                if resolved is None or resolved.state_slot_id is None:
                    continue
            elif not isinstance(source_ref, CallResultRef):
                continue
            binding = call.return_bindings.get(returned.name)
            if binding is not None and (
                binding.kind == "answer"
                or not isinstance(source_ref, SemanticRef)
                or binding.ref != source_ref.ref
                or binding.kind != source_ref.kind
            ):
                continue
            expectation = call.return_expectations.get(returned.name)
            if expectation not in {None, "open_state", "open_expression"}:
                continue
            consumed_returns = {
                return_name
                for (call_id, return_name) in consumers
                if call_id == call.call_id
            }
            if consumed_returns - {returned.name}:
                continue
            dropped.add(call.call_id)
            replacement_refs[(call.call_id, returned.name)] = source_ref
            repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    "reuse_open_state_for_incomplete_transition",
                    call.capability_id,
                    (
                        f"{returned.identity_arg}:existing_state;"
                        "missing_parameter_value"
                    ),
                )
            )
    if not dropped:
        return plan, ()

    def rewrite(ref: FunctionalRef) -> FunctionalRef:
        if not isinstance(ref, CallResultRef):
            return ref
        return replacement_refs.get((ref.from_call, ref.return_name), ref)

    return (
        replace(
            plan,
            scopes=tuple(
                replace(
                    scope,
                    calls=tuple(
                        replace(
                            call,
                            args={
                                name: tuple(rewrite(ref) for ref in refs)
                                for name, refs in call.args.items()
                            },
                        )
                        for call in scope.calls
                        if call.call_id not in dropped
                    ),
                )
                for scope in plan.scopes
                if any(call.call_id not in dropped for call in scope.calls)
            ),
        ),
        tuple(repairs),
    )


class FunctionalPlanReconciler:
    """Resolve FunctionalPlan refs against Context and project canonical steps."""

    def __init__(
        self,
        *,
        state_identity_mode: StateIdentityMode = "authoritative",
        state_placement_mode: StatePlacementMode = "authoritative",
        state_finalizer_mode: StateFinalizerMode = "authoritative",
    ) -> None:
        self.state_identity_mode = state_identity_mode
        self.state_placement_mode = state_placement_mode
        self.state_finalizer_mode = state_finalizer_mode

    def reconcile(
        self,
        plan: FunctionalPlan,
        *,
        planner_state_context: PlannerStateContext,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        handle_registry: CanonicalHandleRegistry,
        question_goals: Sequence[QuestionGoal],
        pinned_canonical_call_ids: Sequence[str] = (),
        pinned_execution_scopes: Mapping[str, str] | None = None,
        pinned_return_scopes: Mapping[str, Mapping[str, str]] | None = None,
        pinned_resolver_arg_names: Mapping[str, Sequence[str]] | None = None,
    ) -> FunctionalPlanReconciliationResult:
        prepared = _NormalizeElaborateScopeStage().run(
            plan,
            planner_state_context=planner_state_context,
            family_spec=family_spec,
            method_specs=method_specs,
            handle_registry=handle_registry,
            question_goals=question_goals,
            pinned_canonical_call_ids=frozenset(
                pinned_canonical_call_ids
            ),
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
        planned_return_expectations = {
            (planned_call.call_id, return_name): expectation
            for planned_call in plan.calls
            for return_name, expectation in (
                planned_call.return_expectations.items()
            )
        }
        answer_bindings: dict[str, str] = {}
        explicitly_bound_answer_refs = set(
            prepared.explicitly_bound_answer_refs
        )
        factory = CanonicalStateHandleFactory()
        typed_object_registry = MathObjectRegistry.from_sources(
            handle_registry,
            math_objects=planner_state_context.state.math_objects,
        )
        typed_identity_factory = StateIdentityFactory(
            typed_object_registry
        )
        typed_visibility = ScopeVisibilityResolver(handle_registry)
        identity_index = StateIdentityIndex.from_context(
            state_slots=planner_state_context.state.state_slots,
            factory=typed_identity_factory,
            visibility=typed_visibility,
        )
        base_identity_index = identity_index.clone()
        allocation_service = StateAllocationService()
        typed_identity_validator = FunctionalTypedIdentityValidator()
        typed_identity_completeness = FunctionalTypedIdentityCompleteness()
        identity_decisions: list[dict[str, Any]] = []
        identity_comparisons: list[IdentityShadowComparison] = []
        preallocated_aliases: dict[str, str] = {}
        scope_by_id = {scope.scope_id: scope for scope in plan.scopes}
        for scope_id, _, call in topological_scoped_calls(
            plan,
            dependency_graph=dependency_graph,
        )[0]:
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
            call, resolved_args = _resolve_explicit_call_args(
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
            supplied_context_auto_names = {
                auto.name
                for auto in capability.auto_args
                if auto.name in resolved_args
                and _has_context_auto_resolver(auto.selector)
            }
            auto_resolution_args = {
                name: values
                for name, values in resolved_args.items()
                if name not in supplied_context_auto_names
            }
            auto_args, auto_repairs, auto_issues = _resolve_context_auto_args(
                capability,
                auto_resolution_args,
                call_id=call.call_id,
                scope_id=resolution_scope_id,
                produced=produced,
                semantic_index=semantic_index,
                handle_registry=handle_registry,
                planned_return_expectations=planned_return_expectations,
            )
            (
                accepted_auto_args,
                accepted_auto_repairs,
                accepted_auto_issues,
            ) = _reconcile_supplied_context_auto_args(
                capability,
                resolved_args=resolved_args,
                resolved_auto_args=auto_args,
                resolver_repairs=auto_repairs,
                resolver_issues=auto_issues,
                supplied_names=supplied_context_auto_names,
                call_id=call.call_id,
                scope_id=scope.scope_id,
            )
            resolved_args.update(accepted_auto_args)
            reconciliation_repairs.extend(accepted_auto_repairs)
            issues.extend(accepted_auto_issues)
            for optional_arg_name in tuple(deterministic_args):
                optional_arg = next(
                    (
                        item
                        for item in capability.args
                        if item.name == optional_arg_name
                    ),
                    None,
                )
                if (
                    optional_arg is None
                    or optional_arg.semantic_role != "parameter_value"
                ):
                    continue
                substitutable_inputs = tuple(
                    value
                    for arg_name, values in resolved_args.items()
                    if arg_name != optional_arg_name
                    for value in values
                    if value.runtime_type
                    in {
                        "Expression",
                        "MinimumExpression",
                        "Parabola",
                        "Point",
                    }
                )
                if not substitutable_inputs or any(
                    value.free_symbol_refs for value in substitutable_inputs
                ):
                    continue
                selected = resolved_args.pop(optional_arg_name, ())
                for value in selected:
                    reconciliation_repairs.append(
                        FunctionalDeterministicRepair(
                            call.call_id,
                            (
                                "suppress_redundant_parameter_value_for_"
                                "closed_inputs"
                            ),
                            (
                                f"{optional_arg_name}="
                                f"{value.object_ref or value.handle}"
                            ),
                            f"{optional_arg_name}=omitted",
                        )
                    )
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
            input_closure = resolve_functional_input_closure(
                capability,
                resolved_args,
                call_id=call.call_id,
                scope_id=resolution_scope_id,
                produced=produced,
                semantic_index=semantic_index,
                handle_registry=handle_registry,
            )
            resolved_args.update(input_closure.additions)
            reconciliation_repairs.extend(input_closure.repairs)
            issues.extend(input_closure.issues)
            reads_closed = reads_closed or input_closure.reads_closed
            (
                post_closure_args,
                post_closure_repairs,
            ) = _resolve_deterministic_optional_args(
                capability,
                resolved_args,
                call_id=call.call_id,
                scope_id=resolution_scope_id,
                produced=produced,
                semantic_index=semantic_index,
                handle_registry=handle_registry,
            )
            resolved_args.update(post_closure_args)
            reconciliation_repairs.extend(post_closure_repairs)
            issues.extend(
                _required_identity_auto_arg_issues(
                    capability,
                    resolved_args,
                    call_id=call.call_id,
                    scope_id=scope.scope_id,
                    has_downstream_consumer=any(
                        source_call_id == call.call_id
                        for source_call_id, _return_name in consumers
                    ),
                )
            )
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
            resolved_args, call_identity_completeness = (
                typed_identity_validator.validate_resolved_args(
                    resolved_args,
                    call_id=call.call_id,
                    identity_factory=typed_identity_factory,
                )
            )
            typed_identity_completeness = (
                typed_identity_completeness.merge(
                    call_identity_completeness
                )
            )
            symbol_issues, symbol_repairs = _functional_symbol_identity_issues(
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
            issues.extend(symbol_issues)
            reconciliation_repairs.extend(symbol_repairs)
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
            call_identity_index = identity_index.clone()
            call, allocations = _allocate_functional_returns(
                call=call,
                active_return_specs=active_return_specs,
                context=_FunctionalReturnAllocationContext(
                    capability=capability,
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
                    identity_factory=typed_identity_factory,
                    identity_index=call_identity_index,
                    allocation_service=allocation_service,
                    identity_mode=self.state_identity_mode,
                    identity_decisions=identity_decisions,
                    identity_comparisons=identity_comparisons,
                ),
            )
            issues.extend(
                StateIdentityConstraintValidator().validate(
                    capability.identity_constraints,
                    call_id=call.call_id,
                    scope_id=scope.scope_id,
                    resolved_args=resolved_args,
                    returns=allocations,
                )
            )
            call_identity_comparisons = tuple(
                item
                for item in identity_comparisons
                if item.call_id == call.call_id
            )
            non_conflict_drift = tuple(
                item
                for item in call_identity_comparisons
                if not item.matches and item.typed_action != "conflict"
            )
            if self.state_identity_mode == "authoritative" and non_conflict_drift:
                raise ValueError(
                    "planner.state_projection_drift: "
                    + " | ".join(
                        f"{item.call_id}.{item.return_name}: "
                        + "; ".join(item.details)
                        for item in non_conflict_drift
                    )
                )
            if (
                self.state_identity_mode == "authoritative"
                and len(issues) == issue_start
            ):
                for allocation in allocations:
                    if allocation.allocation_action != "conflict":
                        continue
                    previous_version = (
                        call_identity_index.version(
                            allocation.previous_version_id
                        )
                        if allocation.previous_version_id is not None
                        else None
                    )
                    previous_call_id = (
                        allocation.previous_write_step_id
                        or (
                            previous_version.producer_call_id
                            if previous_version is not None
                            else None
                        )
                    )
                    issue_code = (
                        "functional.state_transition_dependency_unproven"
                        if allocation.allocation_conflict_code
                        == "state.transition_dependency_unproven"
                        else "functional.state_allocation_conflict"
                    )
                    issues.append(
                        _issue(
                            "functional_reconciliation",
                            issue_code,
                            (
                                "the same mathematical object has a visible "
                                "state writer, but the new write is not proven "
                                "to consume or refine that state"
                                if issue_code
                                == "functional.state_transition_dependency_unproven"
                                else (
                                    "return conflicts with an unrelated "
                                    "visible state writer"
                                )
                            ),
                            call_id=call.call_id,
                            scope_id=scope.scope_id,
                            details={
                                "return": allocation.return_name,
                                "object_ref": allocation.object_ref,
                                "previous_writer_call_id": previous_call_id,
                                "current_writer_call_id": call.call_id,
                                "previous_free_symbols": list(
                                    previous_version.free_symbol_refs
                                    if previous_version is not None
                                    else ()
                                ),
                                "current_free_symbols": list(
                                    allocation.free_symbol_refs
                                ),
                                "repair_call_ids": list(
                                    unique_ordered(
                                        (
                                            *(
                                                (previous_call_id,)
                                                if previous_call_id is not None
                                                else ()
                                            ),
                                            call.call_id,
                                        )
                                    )
                                ),
                                "logical_state_key": (
                                    allocation.logical_state_key.to_payload()
                                    if allocation.logical_state_key is not None
                                    else None
                                ),
                                "reason_code": (
                                    allocation.allocation_reason_code
                                ),
                                "conflict_code": (
                                    allocation.allocation_conflict_code
                                ),
                            },
                        )
                    )
            if len(issues) > issue_start:
                _drop_produced_call_values(produced, call.call_id)
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
            canonical_producers = unique_ordered(
                allocation.canonical_producer_call_id
                for allocation in allocations
                if allocation.allocation_action == "reuse"
                and allocation.canonical_producer_call_id is not None
            )
            if (
                allocations
                and all(
                    allocation.allocation_action == "reuse"
                    for allocation in allocations
                )
                and len(canonical_producers) == 1
                and not any(
                    binding.kind == "answer"
                    for binding in call.return_bindings.values()
                )
            ):
                preallocated_aliases[call.call_id] = canonical_producers[0]
                reconciliation_repairs.append(
                    FunctionalDeterministicRepair(
                        call.call_id,
                        "merge_redundant_existing_state_call",
                        call.call_id,
                        canonical_producers[0],
                    )
                )
            identity_index = call_identity_index
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
        (
            effective_calls,
            reconciled,
            resolved_answer_repairs,
        ) = _bind_unique_resolved_object_answers(
            plan,
            effective_calls=effective_calls,
            reconciled=reconciled,
            question_goals=question_goals,
            handle_registry=handle_registry,
            answer_bindings=answer_bindings,
        )
        reconciliation_repairs.extend(resolved_answer_repairs)
        return _PlacementLivenessProjectionStage().run(
            plan=plan,
            elaboration=elaboration,
            effective_calls=effective_calls,
            return_role_aliases=return_role_aliases,
            reconciled=reconciled,
            produced=produced,
            call_reports=call_reports,
            catalog=catalog,
            semantic_items=semantic_items,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
            question_goals=question_goals,
            family_spec=family_spec,
            answer_bindings=answer_bindings,
            issues=issues,
            reconciliation_repairs=reconciliation_repairs,
            placement_service=placement_service,
            preallocated_aliases=preallocated_aliases,
            identity_decisions=identity_decisions,
            identity_comparisons=identity_comparisons,
            typed_identity_completeness=typed_identity_completeness,
            identity_mode=self.state_identity_mode,
            identity_factory=typed_identity_factory,
            base_identity_index=base_identity_index,
            allocation_service=allocation_service,
            placement_mode=self.state_placement_mode,
            state_finalizer_mode=self.state_finalizer_mode,
            pinned_canonical_call_ids=tuple(pinned_canonical_call_ids),
            pinned_execution_scopes=dict(pinned_execution_scopes or {}),
            pinned_return_scopes={
                call_id: dict(scopes)
                for call_id, scopes in (pinned_return_scopes or {}).items()
            },
            pinned_resolver_arg_names={
                call_id: tuple(arg_names)
                for call_id, arg_names in (
                    pinned_resolver_arg_names or {}
                ).items()
            },
        )


def _bind_unique_resolved_object_answers(
    plan: FunctionalPlan,
    *,
    effective_calls: Mapping[str, FunctionalCall],
    reconciled: Sequence[FunctionalCallReconciliation],
    question_goals: Sequence[QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
    answer_bindings: dict[str, str],
) -> tuple[
    dict[str, FunctionalCall],
    list[FunctionalCallReconciliation],
    tuple[FunctionalDeterministicRepair, ...],
]:
    """Bind a terminal object state to its uniquely matching QuestionGoal.

    This runs after return allocation, when object identity is authoritative.
    It therefore handles the common LLM omission where a call writes the
    correct existing Point but forgets to label that final state as an answer.
    """
    calls = dict(effective_calls)
    reconciled_calls = list(reconciled)
    consumers = _call_result_consumer_calls(plan)
    repairs: list[FunctionalDeterministicRepair] = []
    candidates_by_goal: dict[
        str,
        list[tuple[int, int, FunctionalReturnAllocation]],
    ] = {}
    for goal in question_goals:
        answer_handle = f"answer:{goal.id}"
        if not goal.required or answer_handle in answer_bindings:
            continue
        target_object = handle_registry.answer_target_handles.get(answer_handle)
        if target_object is None:
            continue
        candidates: list[tuple[int, int, FunctionalReturnAllocation]] = []
        for call_index, resolved in enumerate(reconciled_calls):
            for return_index, allocation in enumerate(resolved.returns):
                if (
                    allocation.identity_policy == "derived_role"
                    or allocation.object_ref != target_object
                    or not functional_answer_output_type_compatible(
                        goal.value_type,
                        allocation.runtime_type,
                    )
                    or not visible_from_valid_scope(
                        allocation.valid_scope,
                        scope_id=goal.question_id,
                        registry=handle_registry,
                    )
                    or _has_downstream_object_write(
                        allocation,
                        consumers=consumers,
                        reconciled=reconciled_calls,
                    )
                ):
                    continue
                candidates.append((call_index, return_index, allocation))
        candidates_by_goal[goal.id] = candidates

    proposed: list[
        tuple[QuestionGoal, int, int, FunctionalReturnAllocation]
    ] = []
    used_returns: set[tuple[str, str]] = set()
    for goal in question_goals:
        candidates = candidates_by_goal.get(goal.id, ())
        if len(candidates) != 1:
            continue
        call_index, return_index, allocation = candidates[0]
        key = (allocation.call_id, allocation.return_name)
        if key in used_returns:
            continue
        used_returns.add(key)
        proposed.append((goal, call_index, return_index, allocation))

    for goal, call_index, return_index, allocation in proposed:
        answer_handle = f"answer:{goal.id}"
        answer_ref = SemanticRef(
            ref=goal.id,
            kind="answer",
            value_type=goal.value_type,
        )
        call = calls[allocation.call_id]
        bindings = dict(call.return_bindings)
        previous = bindings.get(allocation.return_name)
        bindings[allocation.return_name] = answer_ref
        calls[allocation.call_id] = replace(call, return_bindings=bindings)
        resolved = reconciled_calls[call_index]
        returns = list(resolved.returns)
        returns[return_index] = replace(
            allocation,
            handle=answer_handle,
            bound_ref=answer_ref,
            state_handle=allocation.state_handle or allocation.handle,
        )
        reconciled_calls[call_index] = replace(
            resolved,
            returns=tuple(returns),
        )
        answer_bindings[answer_handle] = allocation.call_id
        repairs.append(
            FunctionalDeterministicRepair(
                allocation.call_id,
                "bind_resolved_object_state_to_required_answer",
                (
                    f"{previous.kind}:{previous.ref}"
                    if previous is not None
                    else f"<unbound:{allocation.return_name}>"
                ),
                goal.id,
            )
        )
    return calls, reconciled_calls, tuple(repairs)


def _has_downstream_object_write(
    allocation: FunctionalReturnAllocation,
    *,
    consumers: Mapping[tuple[str, str], tuple[str, ...]],
    reconciled: Sequence[FunctionalCallReconciliation],
) -> bool:
    """Return whether a dependent call writes a newer state of this object."""
    reconciled_by_id = {item.call_id: item for item in reconciled}
    pending = list(
        consumers.get((allocation.call_id, allocation.return_name), ())
    )
    visited: set[str] = set()
    while pending:
        call_id = pending.pop()
        if call_id in visited:
            continue
        visited.add(call_id)
        resolved = reconciled_by_id.get(call_id)
        if resolved is None:
            continue
        if any(
            item.object_ref == allocation.object_ref
            and runtime_type_compatible(
                allocation.runtime_type,
                item.runtime_type,
            )
            for item in resolved.returns
        ):
            return True
        for item in resolved.returns:
            pending.extend(consumers.get((call_id, item.return_name), ()))
    return False


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
        produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
        call_reports: Sequence[FunctionalCallReport],
        catalog: FunctionalCapabilityCatalog,
        semantic_items: tuple[SemanticReadCatalogItem, ...],
        semantic_index: FunctionalSemanticIndex,
        handle_registry: CanonicalHandleRegistry,
        question_goals: Sequence[QuestionGoal],
        family_spec: SolverFamilySpec,
        answer_bindings: Mapping[str, str],
        issues: list[FunctionalPlanIssue],
        reconciliation_repairs: list[FunctionalDeterministicRepair],
        placement_service: FunctionalCallPlacementService,
        preallocated_aliases: Mapping[str, str],
        identity_decisions: Sequence[Mapping[str, Any]],
        identity_comparisons: Sequence[IdentityShadowComparison],
        typed_identity_completeness: FunctionalTypedIdentityCompleteness,
        identity_mode: StateIdentityMode,
        identity_factory: StateIdentityFactory,
        base_identity_index: StateIdentityIndex,
        allocation_service: StateAllocationService,
        placement_mode: StatePlacementMode,
        state_finalizer_mode: StateFinalizerMode,
        pinned_canonical_call_ids: tuple[str, ...],
        pinned_execution_scopes: Mapping[str, str],
        pinned_return_scopes: Mapping[str, Mapping[str, str]],
        pinned_resolver_arg_names: Mapping[str, Sequence[str]],
    ) -> FunctionalPlanReconciliationResult:
        plan = _rewrite_effective_functional_plan(
            plan,
            effective_calls=effective_calls,
            return_role_aliases=return_role_aliases,
        )
        (
            reconciled,
            wire_arg_repairs,
            wire_arg_issues,
        ) = _synchronize_wire_resolved_args(
            plan,
            reconciled=reconciled,
            catalog=catalog,
            semantic_index=semantic_index,
            produced=produced,
        )
        reconciliation_repairs.extend(wire_arg_repairs)
        issues.extend(wire_arg_issues)
        (
            reconciled,
            context_arg_repairs,
            context_arg_issues,
        ) = _refresh_context_auto_args_for_effective_order(
            plan,
            reconciled=reconciled,
            catalog=catalog,
            semantic_index=semantic_index,
            produced=produced,
            handle_registry=handle_registry,
        )
        reconciliation_repairs.extend(context_arg_repairs)
        issues.extend(context_arg_issues)
        initial_aliases = {
            **(elaboration.call_aliases or {}),
            **preallocated_aliases,
        }
        placement = placement_service.place(
            plan,
            source_plan=elaboration.raw_plan,
            reconciled=reconciled,
            call_reports=call_reports,
            catalog=catalog,
            handle_registry=handle_registry,
            semantic_items=semantic_items,
            question_goals=question_goals,
            initial_aliases=initial_aliases,
            identity_factory=identity_factory,
            base_identity_index=base_identity_index,
            allocation_service=allocation_service,
            placement_mode=placement_mode,
            pinned_canonical_call_ids=pinned_canonical_call_ids,
            pinned_execution_scopes=pinned_execution_scopes,
            pinned_return_scopes=pinned_return_scopes,
        )
        plan = placement.plan
        reconciled = list(placement.calls)
        call_reports = list(placement.call_reports)
        # B1 allocation and B3 finalization own state transitions. Runtime
        # closure owns actual free Symbols and result form; reconciliation must
        # not synthesize either from provisional return metadata.
        reconciliation_repairs.extend(placement.repairs)
        issues.extend(placement.issues)
        answer_identity_issues = _answer_allocation_identity_issues(
            reconciled,
            catalog=catalog,
            handle_registry=handle_registry,
        )
        issues.extend(answer_identity_issues)
        dependency_graph = _with_closed_scalar_dependencies(
            plan,
            reconciled=tuple(reconciled),
            dependency_graph=placement.dependency_graph,
            handle_registry=handle_registry,
        )
        pre_liveness_writes = build_functional_state_write_manifest(
            plan,
            tuple(reconciled),
        )
        pre_liveness_dependencies = build_functional_state_dependencies(
            plan,
            tuple(reconciled),
            catalog=catalog,
        )
        dependency_graph = expand_functional_dependency_graph(
            dependency_graph,
            projected_state_writes=pre_liveness_writes,
            projected_state_dependencies=pre_liveness_dependencies,
        )
        evidence_issues = _functional_evidence_preflight_issues(
            plan,
            reconciled=tuple(reconciled),
            catalog=catalog,
            question_goals=question_goals,
            family_spec=family_spec,
        )
        issues.extend(evidence_issues)
        reconciled, call_reports = _exclude_late_invalid_call_graph(
            reconciled,
            call_reports,
            dependency_graph=dependency_graph,
            issues=(
                *placement.issues,
                *answer_identity_issues,
                *evidence_issues,
            ),
        )
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
            existing_state_views=semantic_index.views,
            handle_registry=handle_registry,
        )
        plan = liveness.plan
        reconciled = list(liveness.calls)
        call_reports = list(liveness.call_reports)
        dependency_graph = liveness.dependency_graph
        reconciliation_repairs.extend(liveness.repairs)
        reconciled_tuple, version_rebases = rebase_live_state_versions(
            tuple(reconciled)
        )
        reconciled = list(reconciled_tuple)
        reconciliation_repairs.extend(
            FunctionalDeterministicRepair(
                item.call_id,
                "rebase_transition_after_liveness",
                str(item.removed_previous_version_id.to_payload()),
                str(item.selected_previous_version_id.to_payload()),
            )
            for item in version_rebases
        )
        if liveness.dropped_call_ids:
            dropped_call_ids = set(liveness.dropped_call_ids)
            required_answer_handles = {
                f"answer:{goal.id}"
                for goal in question_goals
                if goal.required
            }
            answer_failure_call_ids = {
                issue.call_id
                for issue in issues
                if issue.call_id is not None
                and (issue.details or {}).get("answer_handle")
                in required_answer_handles
            }
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
                or issue.call_id in answer_failure_call_ids
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
                producer_call_ids = _unbound_goal_producer_call_ids(
                    plan,
                    reconciled,
                    goal=goal,
                    handle_registry=handle_registry,
                )
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.required_goal_unbound",
                        f"required answer is not bound: {handle}",
                        call_id=(
                            producer_call_ids[0]
                            if len(producer_call_ids) == 1
                            else None
                        ),
                        scope_id=goal.question_id,
                        details={
                            "answer_handle": handle,
                            "target_object_ref": (
                                handle_registry.answer_target_handles.get(handle)
                            ),
                            "candidate_producer_call_ids": list(
                                producer_call_ids
                            ),
                            "repair_call_ids": list(producer_call_ids),
                        },
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
        projected_state_writes = build_functional_state_write_manifest(
            plan,
            tuple(reconciled),
        )
        projected_state_dependencies = (
            build_functional_state_dependencies(
                plan,
                tuple(reconciled),
                catalog=catalog,
            )
        )
        dependency_graph = expand_functional_dependency_graph(
            dependency_graph,
            projected_state_writes=projected_state_writes,
            projected_state_dependencies=projected_state_dependencies,
        )
        logical_finalization = StateFinalizationResult()
        if not issues:
            execution_scope_by_call = {
                item.canonical_call_id: item.execution_scope_id
                for item in call_placements
            }
            logical_finalization = (
                StateFinalizationService().finalize_logical_graph(
                    projected_state_writes,
                    dependencies=projected_state_dependencies,
                    known_versions=base_identity_index.all_versions(),
                    step_scopes={
                        call.call_id: execution_scope_by_call.get(
                            call.call_id,
                            call.scope_id,
                        )
                        for call in reconciled
                    },
                    handle_registry=handle_registry,
                    mode=state_finalizer_mode,
                )
            )
        dependency_kinds = _functional_dependency_kinds(
            plan,
            tuple(reconciled),
            dependency_graph=dependency_graph,
            projected_state_dependencies=projected_state_dependencies,
        )
        functional_binding_context = FunctionalBindingContextBuilder().build(
            plan,
            tuple(reconciled),
            catalog=catalog,
            object_registry=identity_factory.objects,
            resolver_injected_arg_keys=_resolver_injected_binding_keys(
                plan,
                elaboration.deterministic_repairs,
                catalog=catalog,
            )
            | frozenset(
                (call_id, arg_name)
                for call_id, arg_names in (
                    pinned_resolver_arg_names or {}
                ).items()
                for arg_name in arg_names
            ),
        )
        functional_binding_audit = audit_functional_arg_binding_projection(
            functional_binding_context,
            build_functional_runtime_arg_bindings_from_context(
                tuple(reconciled),
                functional_binding_context,
            ),
        )
        execution_entries = _functional_execution_entries(
            plan,
            reconciled=tuple(reconciled),
            placements=call_placements,
        )
        if issues:
            return FunctionalPlanReconciliationResult(
                plan=plan,
                calls=tuple(reconciled),
                issues=tuple(issues),
                execution_entries=execution_entries,
                context_delta=_context_delta(reconciled),
                call_reports=tuple(call_reports),
                dependency_graph=dependency_graph,
                dependency_kinds=dependency_kinds,
                call_placements=call_placements,
                call_aliases=call_aliases,
                elaboration=elaboration.to_payload(),
                state_identity_decisions=tuple(
                    dict(item) for item in identity_decisions
                ),
                identity_mismatches=tuple(
                    item.to_payload()
                    for item in identity_comparisons
                    if not item.matches
                ),
                state_placement_decisions=tuple(
                    item.to_payload() for item in placement.typed_decisions
                ),
                placement_mismatches=placement.mismatches,
                state_finalization_decisions=tuple(
                    item.to_payload()
                    for item in logical_finalization.decisions
                ),
                state_finalization_mismatches=tuple(
                    item.to_payload()
                    for item in logical_finalization.mismatches
                ),
                state_dependencies=(
                    projected_state_dependencies
                ),
                typed_identity_completeness=(
                    typed_identity_completeness.to_payload()
                ),
                legacy_identity_fallback_count=0,
                functional_binding_context=functional_binding_context,
                functional_binding_decisions=(
                    functional_binding_audit.decisions
                ),
                functional_binding_mismatches=(
                    functional_binding_audit.mismatches
                ),
                legacy_binding_role_fallback_count=(
                    functional_binding_audit.legacy_fallback_count
                ),
            )
        return FunctionalPlanReconciliationResult(
            plan=plan,
            calls=tuple(reconciled),
            execution_entries=execution_entries,
            context_delta=_context_delta(reconciled),
            call_reports=tuple(call_reports),
            dependency_graph=dependency_graph,
            dependency_kinds=dependency_kinds,
            call_placements=call_placements,
            call_aliases=call_aliases,
            elaboration=elaboration.to_payload(),
            state_identity_decisions=tuple(
                dict(item) for item in identity_decisions
            ),
            identity_mismatches=tuple(
                item.to_payload()
                for item in identity_comparisons
                if not item.matches
            ),
            state_placement_decisions=tuple(
                item.to_payload() for item in placement.typed_decisions
            ),
            placement_mismatches=placement.mismatches,
            state_finalization_decisions=tuple(
                item.to_payload()
                for item in logical_finalization.decisions
            ),
            state_finalization_mismatches=tuple(
                item.to_payload()
                for item in logical_finalization.mismatches
            ),
            state_dependencies=projected_state_dependencies,
            typed_identity_completeness=(
                typed_identity_completeness.to_payload()
            ),
            legacy_identity_fallback_count=0,
            functional_binding_context=functional_binding_context,
            functional_binding_decisions=functional_binding_audit.decisions,
            functional_binding_mismatches=functional_binding_audit.mismatches,
            legacy_binding_role_fallback_count=(
                functional_binding_audit.legacy_fallback_count
            ),
        )


def _answer_allocation_identity_issues(
    reconciled: Sequence[FunctionalCallReconciliation],
    *,
    catalog: FunctionalCapabilityCatalog,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[FunctionalPlanIssue, ...]:
    """Validate answer identity after B2 has replayed typed allocations."""

    result: list[FunctionalPlanIssue] = []
    for call in reconciled:
        capability = catalog.get(call.capability_id)
        returns_by_name = (
            {item.name: item for item in capability.returns}
            if capability is not None
            else {}
        )
        for allocation in call.returns:
            if (
                allocation.bound_ref is None
                or allocation.bound_ref.kind != "answer"
                or allocation.object_ref is None
            ):
                continue
            target_object_ref = handle_registry.answer_target_handles.get(
                allocation.handle
            )
            if (
                target_object_ref is None
                or target_object_ref == allocation.object_ref
            ):
                continue
            return_spec = returns_by_name.get(allocation.return_name)
            result.append(
                _issue(
                    "functional_reconciliation",
                    "functional.return_answer_object_identity_mismatch",
                    (
                        f"return {call.capability_id}."
                        f"{allocation.return_name} belongs to "
                        f"{allocation.object_ref}, but {allocation.handle} "
                        f"targets {target_object_ref}"
                    ),
                    call_id=call.call_id,
                    scope_id=call.scope_id,
                    details={
                        "return": allocation.return_name,
                        "answer_handle": allocation.handle,
                        "expected_object_ref": target_object_ref,
                        "actual_object_ref": allocation.object_ref,
                        "identity_policy": allocation.identity_policy,
                        "identity_arg": (
                            return_spec.identity_arg
                            if return_spec is not None
                            else None
                        ),
                    },
                )
            )
    return tuple(result)


def _exclude_late_invalid_call_graph(
    reconciled: Sequence[FunctionalCallReconciliation],
    call_reports: Sequence[FunctionalCallReport],
    *,
    dependency_graph: Mapping[str, tuple[str, ...]],
    issues: Sequence[FunctionalPlanIssue],
) -> tuple[list[FunctionalCallReconciliation], list[FunctionalCallReport]]:
    """Keep late semantic failures out of the partial runtime projection."""

    root_codes: dict[str, tuple[str, ...]] = {}
    for call_id in unique_ordered(
        issue.call_id for issue in issues if issue.call_id is not None
    ):
        root_codes[call_id] = unique_ordered(
            issue.code for issue in issues if issue.call_id == call_id
        )
    if not root_codes:
        return list(reconciled), list(call_reports)

    excluded = set(root_codes)
    blockers_by_call: dict[str, tuple[str, ...]] = {}
    changed = True
    while changed:
        changed = False
        for call_id, dependencies in dependency_graph.items():
            if call_id in excluded:
                continue
            blockers = tuple(
                dependency for dependency in dependencies if dependency in excluded
            )
            if not blockers:
                continue
            excluded.add(call_id)
            blockers_by_call[call_id] = blockers
            changed = True

    reports: list[FunctionalCallReport] = []
    for report in call_reports:
        if report.call_id in root_codes:
            reports.append(
                replace(
                    report,
                    status="invalid",
                    issue_codes=root_codes[report.call_id],
                    blocked_by=(),
                )
            )
        elif report.call_id in blockers_by_call:
            reports.append(
                replace(
                    report,
                    status="blocked_by_dependency",
                    issue_codes=(),
                    blocked_by=blockers_by_call[report.call_id],
                )
            )
        else:
            reports.append(report)
    return (
        [item for item in reconciled if item.call_id not in excluded],
        reports,
    )



def _functional_execution_entries(
    plan: FunctionalPlan,
    *,
    reconciled: tuple[FunctionalCallReconciliation, ...],
    placements: tuple[FunctionalCallPlacement, ...],
) -> tuple[FunctionalCallExecutionEntry, ...]:
    """Build the typed call-to-execution ledger from canonical calls."""
    placement_by_call = {
        item.canonical_call_id: item for item in placements
    }
    declared_scope_by_call = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    return tuple(
        FunctionalCallExecutionEntry(
            call_id=call.call_id,
            canonical_call_id=call.call_id,
            alias_call_ids=(
                placement_by_call[call.call_id].alias_call_ids
                if call.call_id in placement_by_call
                else ()
            ),
            declared_scope_id=declared_scope_by_call.get(
                call.call_id,
                call.scope_id,
            ),
            execution_scope_id=(
                placement_by_call[call.call_id].execution_scope_id
                if call.call_id in placement_by_call
                else call.scope_id
            ),
        )
        for call in reconciled
    )




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
        call
        for _, _, call in topological_scoped_calls(
            plan,
            dependency_graph=dependency_graph,
        )[0]
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


@dataclass(frozen=True)
class _FunctionalReturnAllocationContext:
    capability: FunctionalCapability
    call_return_aliases: Mapping[str, str]
    consumers: Mapping[tuple[str, str], tuple[str, ...]]
    requested_scopes: Mapping[tuple[str, str], str]
    declared_scope_id: str
    resolution_scope_id: str
    call_execution_scopes: Mapping[str, str]
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]]
    handle_registry: CanonicalHandleRegistry
    question_goals: Sequence[QuestionGoal]
    explicitly_bound_answer_refs: set[str]
    effective_calls: dict[str, FunctionalCall]
    semantic_items: tuple[SemanticReadCatalogItem, ...]
    semantic_index: FunctionalSemanticIndex
    planner_state_context: PlannerStateContext
    produced: dict[tuple[str, str], ResolvedFunctionalValue]
    issues: list[FunctionalPlanIssue]
    reconciliation_repairs: list[FunctionalDeterministicRepair]
    answer_bindings: dict[str, str]
    factory: CanonicalStateHandleFactory
    semantic_object_consumers: Mapping[
        tuple[str, str],
        tuple[tuple[str, str], ...],
    ]
    processed_call_ids: set[str]
    future_return_object_hints: Mapping[
        tuple[str, str],
        tuple[str, ...],
    ]
    identity_factory: StateIdentityFactory
    identity_index: StateIdentityIndex
    allocation_service: StateAllocationService
    identity_mode: StateIdentityMode
    identity_decisions: list[dict[str, Any]]
    identity_comparisons: list[IdentityShadowComparison]


def _allocate_functional_returns(
    *,
    call: FunctionalCall,
    active_return_specs: Sequence[FunctionalCapabilityReturn],
    context: _FunctionalReturnAllocationContext,
) -> tuple[FunctionalCall, list[FunctionalReturnAllocation]]:
    """Allocate each externally relevant return through one staged pipeline."""
    referenced_returns = {
        context.call_return_aliases.get(return_name, return_name)
        for (source_call, return_name), _consumer_scopes in context.consumers.items()
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
        call, allocation = _allocate_single_functional_return(
            call=call,
            return_spec=return_spec,
            referenced_returns=referenced_returns,
            sibling_returns=tuple(allocations),
            context=context,
        )
        allocations.append(allocation)
    allocations = _project_cross_return_object_roles(
        call=call,
        return_specs=active_return_specs,
        allocations=allocations,
        produced=context.produced,
        call_return_aliases=context.call_return_aliases,
        identity_index=context.identity_index,
    )
    return call, allocations


def _project_cross_return_object_roles(
    *,
    call: FunctionalCall,
    return_specs: Sequence[FunctionalCapabilityReturn],
    allocations: Sequence[FunctionalReturnAllocation],
    produced: dict[tuple[str, str], ResolvedFunctionalValue],
    call_return_aliases: Mapping[str, str],
    identity_index: StateIdentityIndex,
) -> list[FunctionalReturnAllocation]:
    """Attach object roles and declared Symbol dependencies from siblings."""

    allocations = project_sibling_symbol_dependencies(
        tuple(return_specs),
        tuple(allocations),
        capability_id=call.capability_id,
    )
    allocations_by_name = {item.return_name: item for item in allocations}
    specs_by_name = {item.name: item for item in return_specs}
    result: list[FunctionalReturnAllocation] = []
    for allocation in allocations:
        return_spec = specs_by_name[allocation.return_name]
        projected_roles: list[StateObjectRoleBinding] = []
        for projection in return_spec.object_role_projections:
            if projection.source_return is None:
                continue
            source = allocations_by_name.get(projection.source_return)
            if source is None:
                raise ValueError(
                    "planner_configuration_error: required sibling return "
                    "was not allocated for object-role projection: "
                    f"{call.capability_id}.{allocation.return_name}."
                    f"{projection.role} <- {projection.source_return}"
                )
            object_refs = (
                state_object_refs_for_role(
                    source.lineage,
                    projection.source_object_role,
                )
                if projection.source_object_role is not None
                else ((source.object_ref,) if source.object_ref is not None else ())
            )
            if not object_refs:
                raise ValueError(
                    "planner_configuration_error: sibling return has no "
                    "object identity for object-role projection: "
                    f"{call.capability_id}.{projection.source_return}"
                )
            projected_roles.append(
                StateObjectRoleBinding(
                    role=projection.role,
                    object_refs=unique_ordered(object_refs),
                    source_state_slot_ids=(
                        (
                            legacy_state_slot_aliases(
                                source.selected_version_id.slot_id
                            )[0],
                        )
                        if source.selected_version_id is not None
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
                    state_requirement=projection.state_requirement,
                )
            )
        symbol_sources = tuple(
            allocations_by_name[source_name]
            for source_name in return_spec.free_symbol_return_names
        )
        if not projected_roles and not symbol_sources:
            result.append(allocation)
            continue
        lineage = merge_state_semantic_lineages(
            allocation.lineage,
            object_roles=projected_roles,
            source_state_slot_ids=tuple(
                (
                    *(
                        slot_id
                        for role in projected_roles
                        for slot_id in role.source_state_slot_ids
                    ),
                    *(source.state_slot_id for source in symbol_sources),
                )
            ),
            source_version_ids=tuple(
                (
                    *(
                        version_id
                        for role in projected_roles
                        for version_id in role.source_version_ids
                    ),
                    *(
                        source.selected_version_id
                        for source in symbol_sources
                        if source.selected_version_id is not None
                    ),
                )
            ),
        )
        updated = replace(
            allocation,
            lineage=lineage,
            source_version_ids=unique_ordered(
                (
                    *allocation.source_version_ids,
                    *lineage.source_version_ids,
                )
            ),
        )
        result.append(updated)
        if updated.selected_version_id is not None:
            identity_index.update_version(
                updated.selected_version_id,
                free_symbol_refs=updated.free_symbol_refs,
                source_version_ids=updated.source_version_ids,
            )
        produced_value = produced[(call.call_id, allocation.return_name)]
        updated_value = replace(
            produced_value,
            dependency_object_refs=updated.dependency_object_refs,
            free_symbol_refs=updated.free_symbol_refs,
            lineage=lineage,
            source_state_slot_ids=updated.source_state_slot_ids,
            source_version_ids=unique_ordered(
                (
                    *updated.source_version_ids,
                    *lineage.source_version_ids,
                )
            ),
        )
        produced[(call.call_id, allocation.return_name)] = updated_value
        for alias_name, canonical_name in call_return_aliases.items():
            if canonical_name == allocation.return_name:
                produced[(call.call_id, alias_name)] = updated_value
    return result


def _allocate_single_functional_return(
    *,
    call: FunctionalCall,
    return_spec: FunctionalCapabilityReturn,
    referenced_returns: set[str],
    sibling_returns: tuple[FunctionalReturnAllocation, ...],
    context: _FunctionalReturnAllocationContext,
) -> tuple[FunctionalCall, FunctionalReturnAllocation]:
    """Bind a destination, resolve identity, publish scope, then allocate a slot."""
    requested_scope = _initial_return_scope(
        call=call,
        return_spec=return_spec,
        call_return_aliases=context.call_return_aliases,
        requested_scopes=context.requested_scopes,
        declared_scope_id=context.declared_scope_id,
        execution_scope_id=context.call_execution_scopes[call.call_id],
        resolved_args=context.resolved_args,
        handle_registry=context.handle_registry,
        issues=context.issues,
        reconciliation_repairs=context.reconciliation_repairs,
    )
    call, bound_ref, bound_item = _resolve_allocated_return_binding(
        call=call,
        return_spec=return_spec,
        referenced_returns=referenced_returns,
        resolution_scope_id=context.resolution_scope_id,
        declared_scope_id=context.declared_scope_id,
        question_goals=context.question_goals,
        explicitly_bound_answer_refs=context.explicitly_bound_answer_refs,
        effective_calls=context.effective_calls,
        semantic_items=context.semantic_items,
        handle_registry=context.handle_registry,
        issues=context.issues,
        reconciliation_repairs=context.reconciliation_repairs,
        answer_bindings=context.answer_bindings,
    )
    requested_scope = _align_return_scope_with_binding(
        call=call,
        return_spec=return_spec,
        requested_scope=requested_scope,
        bound_item=bound_item,
        resolved_args=context.resolved_args,
        question_goals=context.question_goals,
        declared_scope_id=context.declared_scope_id,
        handle_registry=context.handle_registry,
        issues=context.issues,
    )
    bound_ref, bound_item, object_ref = _resolve_return_identity(
        call=call,
        return_spec=return_spec,
        requested_scope=requested_scope,
        resolution_scope_id=context.resolution_scope_id,
        declared_scope_id=context.declared_scope_id,
        bound_ref=bound_ref,
        bound_item=bound_item,
        resolved_args=context.resolved_args,
        produced=context.produced,
        semantic_items=context.semantic_items,
        semantic_index=context.semantic_index,
        planner_state_context=context.planner_state_context,
        handle_registry=context.handle_registry,
        factory=context.factory,
        sibling_returns=sibling_returns,
        issues=context.issues,
        reconciliation_repairs=context.reconciliation_repairs,
        future_object_hints=(
            ()
            if return_spec.name in call.return_bindings
            else context.future_return_object_hints.get(
                (call.call_id, return_spec.name),
                (),
            )
        ),
        identity_constraints=context.capability.identity_constraints,
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
        context.effective_calls[call.call_id] = call
    requested_scope, object_ref = _publish_return_scope(
        call=call,
        return_spec=return_spec,
        requested_scope=requested_scope,
        bound_ref=bound_ref,
        bound_item=bound_item,
        object_ref=object_ref,
        resolved_args=context.resolved_args,
        question_goals=context.question_goals,
        semantic_object_consumers=context.semantic_object_consumers,
        processed_call_ids=context.processed_call_ids,
        handle_registry=context.handle_registry,
        factory=context.factory,
        sibling_returns=sibling_returns,
        reconciliation_repairs=context.reconciliation_repairs,
    )
    return call, _materialize_functional_return(
        call=call,
        return_spec=return_spec,
        requested_scope=requested_scope,
        bound_ref=bound_ref,
        bound_item=bound_item,
        object_ref=object_ref,
        resolved_args=context.resolved_args,
        semantic_index=context.semantic_index,
        call_return_aliases=context.call_return_aliases,
        factory=context.factory,
        produced=context.produced,
        symbolic_closure=(
            context.capability.source.symbolic_closure
            if isinstance(context.capability.source, FunctionSpec)
            else None
        ),
        capability=context.capability,
        identity_factory=context.identity_factory,
        identity_index=context.identity_index,
        allocation_service=context.allocation_service,
        identity_mode=context.identity_mode,
        identity_decisions=context.identity_decisions,
        identity_comparisons=context.identity_comparisons,
        expected_result_form=call.return_expectations.get(return_spec.name),
        question_goals=context.question_goals,
    )


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
    """Allocate a logical return before final graph placement.

    A requested ancestor scope may require moving a whole producer closure.
    That proof is unavailable during per-call reconciliation, so a return that
    is not yet shareable stays local and is widened by the placement service
    after the complete dependency graph exists.
    """

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
    reconciliation_repairs.append(
        FunctionalDeterministicRepair(
            call.call_id,
            "defer_return_scope_to_graph_placement",
            requested_scope,
            declared_scope_id,
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
    if (
        return_spec.return_binding == "call_local_allowed"
        and bound_ref.kind != "answer"
        and binding_issues
        and all(
            item.code == "functional.return_binding_unknown"
            for item in binding_issues
        )
    ):
        reconciliation_repairs.append(
            FunctionalDeterministicRepair(
                call.call_id,
                "drop_unknown_call_local_return_binding",
                f"{bound_ref.kind}:{bound_ref.ref}",
                return_spec.name,
            )
        )
        call = _without_functional_return_binding(
            call,
            return_spec.name,
        )
        effective_calls[call.call_id] = call
        return call, None, None
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
    """Align answer scope without conflating object origin and state scope."""

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

    binding_scope = bound_item.scope
    declared_ancestors = set(
        handle_registry.ancestor_scopes(declared_scope_id)
    )
    binding_ancestors = set(handle_registry.ancestor_scopes(binding_scope))
    if (
        binding_scope not in declared_ancestors
        and declared_scope_id not in binding_ancestors
    ):
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_scope_incompatible",
                (
                    f"return {call.call_id}.{return_spec.name} cannot bind "
                    f"a sibling-private object in {binding_scope} from "
                    f"{declared_scope_id}"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
                details={
                    "return": return_spec.name,
                    "binding_ref": bound_item.ref,
                    "binding_scope_id": binding_scope,
                    "declared_scope_id": declared_scope_id,
                },
            )
        )
        return requested_scope

    # Binding to an existing MathObject establishes identity only. The object
    # may originate at problem scope while this particular open/closed state
    # is valid in one question branch. Structured consumers widen that state
    # later through _publish_return_scope and B2 placement.
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
    identity_constraints: Sequence[StateIdentityConstraintSpec],
) -> tuple[
    SemanticRef | None,
    SemanticReadCatalogItem | None,
    str | None,
]:
    """Resolve object identity through the return's declared policy."""

    if (
        return_spec.identity_policy == "target_object"
        and return_spec.binding_mode != "internal_only"
    ):
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
            identity_constraints=identity_constraints,
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
    identity_constraints: Sequence[StateIdentityConstraintSpec],
) -> tuple[SemanticRef | None, SemanticReadCatalogItem | None]:
    if (
        return_spec.return_binding == "explicit_external_required"
        and bound_item is None
    ):
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_identity_unresolved",
                (
                    f"return {call.capability_id}.{return_spec.name} requires "
                    "an explicit answer or existing-object binding"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
                details={
                    "return": return_spec.name,
                    "semantic_role": return_spec.semantic_role,
                    "binding_requirement": "explicit_answer_or_existing_object",
                    "accepted_item_types": [return_spec.runtime_type],
                    "repair_guidance": (
                        "Bind this return to the intended existing object in "
                        "return_bindings. A downstream CallResultRef proves "
                        "data flow, but does not establish object identity."
                    ),
                    "compatible_refs": list(
                        _compatible_target_object_refs(
                            return_spec=return_spec,
                            scope_id=resolution_scope_id,
                            resolved_args=resolved_args,
                            semantic_items=semantic_items,
                            planner_state_context=planner_state_context,
                            handle_registry=handle_registry,
                        )
                    ),
                },
            )
        )
        return bound_ref, bound_item

    contract_target = _target_item_from_object_hints(
        infer_unique_return_object_refs(
            identity_constraints,
            return_name=return_spec.name,
            resolved_args=resolved_args,
        ),
        return_spec=return_spec,
        scope_id=resolution_scope_id,
        semantic_items=semantic_items,
        handle_registry=handle_registry,
    )
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
    inferred_candidates = tuple(
        item
        for item in (contract_target, downstream_target, structured_target)
        if item is not None
    )
    inferred_identities = {
        _target_binding_identity(item, handle_registry=handle_registry)
        for item in inferred_candidates
    }
    inferred_target = inferred_candidates[0] if len(inferred_identities) == 1 else None
    if len(inferred_identities) > 1:
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.return_identity_mismatch",
                (
                    f"return {call.capability_id}.{return_spec.name} has "
                    "conflicting contract, structured or downstream identities"
                ),
                call_id=call.call_id,
                scope_id=declared_scope_id,
                details={
                    "return": return_spec.name,
                    "inferred_refs": [item.ref for item in inferred_candidates],
                },
            )
        )
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
                    "infer_return_identity_from_contract"
                    if contract_target is not None
                    else (
                        "propagate_downstream_object_identity"
                        if downstream_target is not None
                        else "auto_bind_target_object"
                    )
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
                            resolved_args=resolved_args,
                            semantic_items=semantic_items,
                            planner_state_context=planner_state_context,
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
    semantic_object_consumers: Mapping[
        tuple[str, str],
        tuple[tuple[str, str], ...],
    ],
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
        and requested_scope
        in handle_registry.ancestor_scopes(answer_object_scope)
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
            (call.call_id, object_ref),
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
    symbolic_closure: SymbolicClosureSpec | None = None,
    capability: FunctionalCapability,
    identity_factory: StateIdentityFactory,
    identity_index: StateIdentityIndex,
    allocation_service: StateAllocationService,
    identity_mode: StateIdentityMode,
    identity_decisions: list[dict[str, Any]],
    identity_comparisons: list[IdentityShadowComparison],
    expected_result_form: FunctionalResultForm | None,
    question_goals: Sequence[QuestionGoal],
) -> FunctionalReturnAllocation:
    """Allocate the canonical handle/slot and register every return alias."""

    computation_key = functional_computation_key(
        call,
        resolved_args=resolved_args,
        scope_id=requested_scope,
        identity_factory=identity_factory,
        identity_index=identity_index,
    )
    if (
        return_spec.identity_policy == "derived_role"
        and return_spec.identity_arg is None
        and bound_item is None
        and object_kind_for_runtime_type(return_spec.runtime_type)
        == "path_transformation"
    ):
        object_ref = identity_factory.derived_computation_object_ref(
            computation_key=computation_key,
            semantic_role=(
                return_spec.equivalent_to
                or return_spec.semantic_role
                or return_spec.name
            ),
            runtime_type=return_spec.runtime_type,
        )
    handle = factory.handle_for(
        call_id=call.call_id,
        return_spec=return_spec,
        valid_scope=requested_scope,
        binding=bound_item,
    )
    state_handle = (
        factory.handle_for(
            call_id=call.call_id,
            return_spec=return_spec,
            valid_scope=requested_scope,
            binding=None,
        )
        if bound_item is not None
        and bound_item.kind == "answer"
        and object_ref is not None
        else None
    )
    lineage = _functional_return_lineage(
        return_spec,
        call_id=call.call_id,
        resolved_args=resolved_args,
        symbolic_closure=symbolic_closure,
        object_ref=object_ref,
    )
    free_symbol_refs = return_free_symbol_refs(
        return_spec.runtime_type,
        resolved_args,
        object_ref=object_ref,
        ignored_input_args=return_spec.result_form_ignored_input_args,
    )
    free_symbol_ids = symbol_ids_from_refs(
        free_symbol_refs,
        registry=identity_factory.objects,
    )
    state_math_object_id = identity_factory.object_id(object_ref)
    math_object_id = state_math_object_id or _answer_projection_object_id(
        bound_ref,
        question_goals=question_goals,
    )
    logical_state_key = identity_factory.logical_key(
        object_ref=object_ref,
        state_kind=return_spec.state_kind,
        runtime_type=return_spec.runtime_type,
    )
    legacy_slot_id = (
        functional_state_slot_debug_alias(
            identity_factory.slot_id(
                logical_state_key,
                storage_scope_id=requested_scope,
            )
        )
        if logical_state_key is not None
        else functional_call_local_debug_alias(
            scope_id=requested_scope,
            call_id=call.call_id,
            return_name=return_spec.name,
        )
    )
    state_effect_key = StateEffectKey(
        (
            LogicalReturnEffect(
                return_name=(
                    return_spec.equivalent_to
                    or return_spec.name
                ),
                logical_key=logical_state_key,
                identity_policy=return_spec.identity_policy,
                write_mode=return_spec.write_mode,
            ),
        )
    )
    source_version_ids = functional_source_version_ids(
        resolved_args,
        scope_id=requested_scope,
        identity_index=identity_index,
    )
    runtime_destination = (
        RuntimeDestinationKey(
            state_math_object_id,
            return_spec.state_kind,
            return_spec.runtime_type,
        )
        if state_math_object_id is not None
        else None
    )
    allocation_request = StateAllocationRequest(
        call_id=call.call_id,
        capability_id=call.capability_id,
        return_name=return_spec.name,
        object_id=state_math_object_id,
        state_kind=return_spec.state_kind,
        runtime_type=return_spec.runtime_type,
        storage_scope_id=requested_scope,
        valid_scope_id=requested_scope,
        requested_write_mode=return_spec.write_mode,
        identity_policy=return_spec.identity_policy,
        is_shareable=capability.is_pure,
        computation_key=computation_key,
        state_effect_key=state_effect_key,
        source_version_ids=source_version_ids,
        free_symbol_refs=free_symbol_refs,
        free_symbol_ids=free_symbol_ids,
        runtime_destination=runtime_destination,
        result_form=expected_result_form,
    )
    decision = allocation_service.allocate(
        allocation_request,
        identity_index,
    )
    identity_decisions.append(decision.to_payload())
    typed_slot_id = decision.selected_slot_id
    typed_slot_projection = (
        functional_state_slot_debug_alias(typed_slot_id)
        if typed_slot_id is not None
        else legacy_slot_id
    )
    comparison_slot_id = (
        functional_state_slot_debug_alias(
            identity_factory.slot_id(
                logical_state_key,
                storage_scope_id=requested_scope,
            )
        )
        if logical_state_key is not None
        else legacy_slot_id
    )
    comparison = identity_shadow_comparison(
        call_id=call.call_id,
        return_name=return_spec.name,
        legacy_object_ref=object_ref,
        legacy_slot_id=legacy_slot_id,
        legacy_write_mode=return_spec.write_mode,
        typed_object_ref=(
            decision.logical_state_key.object_id.value
            if decision.logical_state_key is not None
            else object_ref
        ),
        typed_slot_id=comparison_slot_id,
        typed_action=decision.action,
    )
    identity_comparisons.append(comparison)
    effective_write_mode = return_spec.write_mode
    if identity_mode == "authoritative":
        if decision.action in {"create", "isolated"}:
            effective_write_mode = "create"
        elif decision.action == "transition":
            effective_write_mode = "transition"
    slot_id = (
        typed_slot_projection
        if identity_mode == "authoritative"
        and decision.action != "call_local_value"
        else legacy_slot_id
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
        write_mode=effective_write_mode,
        bound_ref=bound_ref,
        state_handle=state_handle,
        dependency_object_refs=unique_ordered(
            (
                *_argument_dependencies(resolved_args),
                *semantic_index.dependencies_for_object(object_ref),
            )
        ),
        free_symbol_refs=free_symbol_refs,
        free_symbol_ids=free_symbol_ids,
        source_state_slot_ids=_argument_source_slots(resolved_args),
        provides_semantic_roles=return_spec.provides_semantic_roles,
        lineage=lineage,
        math_object_id=math_object_id,
        logical_state_key=logical_state_key,
        typed_slot_id=typed_slot_id,
        selected_version_id=decision.selected_version_id,
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
    indexed_version = allocation_service.indexed_version(
        allocation_request,
        decision,
        produced_handle=state_handle or handle,
    )
    if indexed_version is not None:
        identity_index.register(
            indexed_version,
            legacy_slot_id=slot_id,
        )
    produced_value = ResolvedFunctionalValue(
        handle=state_handle or handle,
        runtime_type=return_spec.runtime_type,
        valid_scope=requested_scope,
        state_slot_id=slot_id,
        source_call_id=call.call_id,
        return_name=return_spec.name,
        object_ref=object_ref,
        dependency_object_refs=allocation.dependency_object_refs,
        free_symbol_refs=allocation.free_symbol_refs,
        free_symbol_ids=allocation.free_symbol_ids,
        source_state_slot_ids=allocation.source_state_slot_ids,
        provides_semantic_roles=allocation.provides_semantic_roles,
        lineage=allocation.lineage,
        math_object_id=math_object_id,
        logical_state_key=logical_state_key,
        typed_slot_id=typed_slot_id,
        state_version_id=decision.selected_version_id,
        source_version_ids=source_version_ids,
    )
    produced[(call.call_id, return_spec.name)] = produced_value
    for alias_name, canonical_name in call_return_aliases.items():
        if canonical_name == return_spec.name:
            produced[(call.call_id, alias_name)] = produced_value
    return allocation


def _answer_projection_object_id(
    bound_ref: SemanticRef | None,
    *,
    question_goals: Sequence[QuestionGoal],
) -> MathObjectId | None:
    """Create answer-only identity from a structured QuestionGoal.

    Value-only answers remain call-local allocations. This identity belongs to
    their semantic projection and must never be used to create a StateSlot.
    """

    if bound_ref is None or bound_ref.kind != "answer":
        return None
    answer_id = (
        bound_ref.ref.removeprefix("answer:")
        if bound_ref.ref.startswith("answer:")
        else bound_ref.ref
    )
    goal = next(
        (item for item in question_goals if item.id == answer_id),
        None,
    )
    if goal is None:
        return None
    return MathObjectId(
        value=f"question_goal:{goal.id}",
        kind="answer",
        origin_scope_id=goal.question_id,
    )


def _functional_return_lineage(
    return_spec: FunctionalCapabilityReturn,
    *,
    call_id: str,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    symbolic_closure: SymbolicClosureSpec | None,
    object_ref: str | None,
) -> StateSemanticLineage:
    """Project declared roles and preserve source lineage for true transitions."""
    inherited: tuple[StateSemanticLineage, ...] = ()
    if (
        return_spec.identity_policy == "preserve_input_object"
        and return_spec.write_mode == "transition"
        and return_spec.identity_arg is not None
    ):
        source_values = resolved_args.get(return_spec.identity_arg, ())
        if len(source_values) == 1:
            inherited = (source_values[0].lineage,)
    closure_lineages: list[StateSemanticLineage] = []
    closure_roles: list[str] = []
    closure_evidence: list[str] = []
    for closure in return_spec.lineage_closures:
        evaluation = evaluate_lineage_closure(
            closure,
            resolved_args=resolved_args,
            output_object_ref=object_ref,
        )
        if not evaluation.passed:
            continue
        closure_lineages.extend(
            successful_closure_lineages(
                evaluation,
                resolved_args=resolved_args,
                closure=closure,
            )
        )
        closure_roles.extend(closure.add_semantic_roles)
        closure_evidence.extend(closure.add_evidence_tags)
    return merge_state_semantic_lineages(
        *inherited,
        *closure_lineages,
        semantic_roles=(
            return_spec.semantic_role,
            *((return_spec.equivalent_to,) if return_spec.equivalent_to else ()),
            *closure_roles,
        ),
        evidence_tags=(*return_spec.evidence_tags, *closure_evidence),
        object_roles=_projected_return_object_roles(
            return_spec,
            resolved_args=resolved_args,
        ),
        symbol_closures=_projected_symbol_closures(
            return_spec,
            resolved_args=resolved_args,
            symbolic_closure=symbolic_closure,
        ),
        source_state_slot_ids=_argument_source_slots(resolved_args),
        source_version_ids=_argument_source_versions(resolved_args),
        source_call_result_ids=_argument_source_call_results(
            resolved_args
        ),
        source_call_ids=(
            *_argument_source_calls(resolved_args),
            call_id,
        ),
    )


def _functional_evidence_preflight_issues(
    plan: FunctionalPlan,
    *,
    reconciled: tuple[FunctionalCallReconciliation, ...],
    catalog: FunctionalCapabilityCatalog,
    question_goals: Sequence[QuestionGoal],
    family_spec: SolverFamilySpec,
) -> tuple[FunctionalPlanIssue, ...]:
    """Reject an answer binding whose declared evidence closure cannot hold."""

    calls_by_id = {call.call_id: call for call in plan.calls}
    resolved_by_id = {call.call_id: call for call in reconciled}
    goals_by_id = {goal.id: goal for goal in question_goals if goal.required}
    selected_packs = {
        *family_spec.base_packs,
        *family_spec.mechanism_packs,
    }
    issues: list[FunctionalPlanIssue] = []
    for resolved in reconciled:
        call = calls_by_id.get(resolved.call_id)
        capability = catalog.items.get(resolved.capability_id)
        if call is None or capability is None:
            continue
        return_specs = {item.name: item for item in capability.returns}
        for allocation in resolved.returns:
            binding = allocation.bound_ref
            if binding is None or binding.kind != "answer":
                continue
            goal = goals_by_id.get(binding.ref)
            return_spec = return_specs.get(allocation.return_name)
            if goal is None or return_spec is None:
                continue
            required_tags = unique_ordered(
                tag
                for policy in family_spec.goal_evidence_policies
                if (
                    not policy.goal_types
                    or capability.goal_type in policy.goal_types
                )
                and (
                    not policy.value_types
                    or goal.value_type in policy.value_types
                )
                and (
                    policy.mechanism_pack_id is None
                    or policy.mechanism_pack_id in selected_packs
                )
                for tag in policy.required_evidence_tags
            )
            actual_tags = {
                *allocation.lineage.semantic_roles,
                *allocation.lineage.evidence_tags,
                *allocation.provides_semantic_roles,
            }
            missing_tags = tuple(
                tag for tag in required_tags if tag not in actual_tags
            )
            if not missing_tags:
                continue
            evaluations = tuple(
                (
                    closure,
                    evaluate_lineage_closure(
                        closure,
                        resolved_args=resolved.resolved_args,
                        output_object_ref=allocation.object_ref,
                    ),
                )
                for closure in return_spec.lineage_closures
                if set(closure.add_evidence_tags).intersection(missing_tags)
            )
            if not evaluations:
                continue
            closure, evaluation = min(
                evaluations,
                key=lambda item: (
                    len(item[1].missing_roles)
                    + len(item[1].missing_evidence_tags)
                    + len(item[1].missing_object_roles),
                    -len(item[1].matched_roles),
                ),
            )
            input_producer_call_ids = unique_ordered(
                (
                    *(
                        value.source_call_id
                        for group in (
                            closure.input_groups
                            or (
                                EvidenceInputGroupSpec(
                                    source_args=closure.source_args
                                ),
                            )
                        )
                        for arg_name in group.source_args
                        for value in resolved.resolved_args.get(arg_name, ())
                        if value.source_call_id is not None
                    ),
                    resolved.call_id,
                )
            )
            compatible_refs = _compatible_evidence_result_refs(
                plan,
                catalog=catalog,
                witness_call_ids=evaluation.witness_call_ids,
                missing_roles=evaluation.missing_roles,
            )
            context_call_ids = unique_ordered(
                ref.rsplit(".", 1)[0]
                for ref in compatible_refs
                if "." in ref
            )
            repair_call_ids = tuple(
                call_id
                for call_id in input_producer_call_ids
                if call_id not in set(context_call_ids)
            )
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.evidence_closure_unproven",
                    (
                        f"{resolved.call_id} cannot prove the evidence required "
                        f"by answer {goal.id}: {', '.join(missing_tags)}"
                    ),
                    call_id=resolved.call_id,
                    scope_id=resolved.scope_id,
                    details={
                        "answer": goal.id,
                        "return": allocation.return_name,
                        "required_evidence_tags": list(required_tags),
                        "actual_evidence_tags": sorted(actual_tags),
                        "evidence_gap": evaluation.to_feedback_payload(),
                        "compatible_refs": compatible_refs,
                        "repair_call_ids": list(repair_call_ids),
                        "context_call_ids": list(context_call_ids),
                    },
                )
            )
    return tuple(issues)


def _compatible_evidence_result_refs(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    witness_call_ids: tuple[str, ...],
    missing_roles: tuple[str, ...],
) -> list[str]:
    """Expose declared prior-call returns without allocating optional outputs."""

    calls_by_id = {call.call_id: call for call in plan.calls}
    result: list[str] = []
    missing = {
        canonical_straightening_endpoint_name(role) or role
        for role in missing_roles
    }
    for call_id in witness_call_ids:
        call = calls_by_id.get(call_id)
        capability = (
            catalog.items.get(call.capability_id)
            if call is not None
            else None
        )
        if capability is None:
            continue
        for returned in capability.returns:
            roles = {
                returned.semantic_role,
                returned.equivalent_to,
                *returned.provides_semantic_roles,
            }
            canonical_roles = {
                canonical_straightening_endpoint_name(role) or role
                for role in roles
                if role
            }
            if not canonical_roles.intersection(missing):
                continue
            result.append(f"{call_id}.{returned.name}")
            if len(result) == 4:
                return result
    return result


def _projected_symbol_closures(
    return_spec: FunctionalCapabilityReturn,
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    symbolic_closure: SymbolicClosureSpec | None,
) -> tuple[StateSymbolClosureBinding, ...]:
    if (
        symbolic_closure is None
        or return_spec.name not in symbolic_closure.substitution_outputs
    ):
        return ()
    targets = tuple(
        value
        for value in resolved_args.get(symbolic_closure.target_arg, ())
        if value.runtime_type == "Symbol" and value.object_ref is not None
    )
    if len(targets) != 1:
        return ()
    dependencies = unique_ordered(
        value.object_ref
        for arg_name in symbolic_closure.preserved_symbol_args
        for value in resolved_args.get(arg_name, ())
        if value.runtime_type == "Symbol" and value.object_ref is not None
    )
    return (
        StateSymbolClosureBinding(
            target_object_ref=targets[0].object_ref,
            dependency_object_refs=dependencies,
            source_state_slot_ids=_argument_source_slots(resolved_args),
        ),
    )


def _values_share_lineage_source_call(
    values: Sequence[ResolvedFunctionalValue],
) -> bool:
    """Prove values descend from one shared producing call.

    A state transition has its own immediate ``source_call_id`` but retains
    the original producer in semantic lineage. Comparing the full ancestry
    keeps evidence such as a pair of straightening endpoints intact after
    each endpoint is evaluated independently.
    """
    source_sets = tuple(
        {
            *value.lineage.source_call_ids,
            *((value.source_call_id,) if value.source_call_id else ()),
        }
        for value in values
    )
    return bool(source_sets) and bool(set.intersection(*source_sets))


def _projected_return_object_roles(
    return_spec: FunctionalCapabilityReturn,
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[StateObjectRoleBinding, ...]:
    result: list[StateObjectRoleBinding] = []
    for projection in return_spec.object_role_projections:
        if projection.source_arg is None:
            continue
        source_values = resolved_args.get(projection.source_arg, ())
        object_refs: list[str] = []
        source_slots: list[str] = []
        source_handles: list[str] = []
        object_ids = []
        source_versions = []
        for value in source_values:
            if projection.source_object_role is None:
                source_handles.append(value.handle)
                if value.object_ref is not None:
                    object_refs.append(value.object_ref)
                if value.math_object_id is not None:
                    object_ids.append(value.math_object_id)
                if value.state_version_id is not None:
                    source_slots.append(
                        legacy_state_slot_aliases(
                            value.state_version_id.slot_id
                        )[0]
                    )
                    source_versions.append(value.state_version_id)
                else:
                    source_slots.extend(value.source_state_slot_ids)
                    source_versions.extend(value.source_version_ids)
            else:
                object_refs.extend(
                    state_object_refs_for_role(
                        value.lineage,
                        projection.source_object_role,
                    )
                )
                object_refs.extend(
                    dict(value.object_roles).get(
                        projection.source_object_role,
                        (),
                    )
                )
                matching_roles = tuple(
                    role
                    for role in value.lineage.object_roles
                    if role.role == projection.source_object_role
                )
                object_ids.extend(
                    object_id
                    for role in matching_roles
                    for object_id in role.object_ids
                )
                source_slots.extend(
                    slot_id
                    for role in matching_roles
                    for slot_id in role.source_state_slot_ids
                )
                source_handles.extend(
                    source_handle
                    for role in matching_roles
                    for source_handle in role.source_handles
                )
                source_versions.extend(
                    version_id
                    for role in matching_roles
                    for version_id in role.source_version_ids
                )
        if object_refs:
            result.append(
                StateObjectRoleBinding(
                    role=projection.role,
                    object_refs=unique_ordered(object_refs),
                    source_state_slot_ids=unique_ordered(source_slots),
                    source_handles=unique_ordered(source_handles),
                    object_ids=unique_ordered(object_ids),
                    source_version_ids=unique_ordered(source_versions),
                    state_requirement=projection.state_requirement,
                )
            )
    return tuple(result)


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
            expectation in {"open_expression", "open_state"}
            and binding is not None
            and binding.kind == "answer"
        ):
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.return_expectation_answer_conflict",
                    (
                        f"open result {call.call_id}.{name} cannot be "
                        "bound directly to a final answer"
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


def _drop_produced_call_values(
    produced: dict[tuple[str, str], ResolvedFunctionalValue],
    call_id: str,
) -> None:
    for key in tuple(produced):
        if key[0] == call_id:
            produced.pop(key, None)


def _functional_symbol_identity_issues(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: dict[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    identity_hints: tuple[str, ...],
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[
    tuple[FunctionalPlanIssue, ...],
    tuple[FunctionalDeterministicRepair, ...],
]:
    auto_issues, auto_repairs = _resolve_auto_symbol_args(
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
    )
    return (
        (
            *auto_issues,
            *functional_reconciliation_issues(
                capability,
                resolved_args,
                produced=produced,
                call_id=call.call_id,
                scope_id=scope_id,
            ),
        ),
        auto_repairs,
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
) -> tuple[FunctionalCall, dict[str, tuple[ResolvedFunctionalValue, ...]]]:
    """Resolve only LLM-visible arguments and collect independent failures."""
    arg_specs = {item.name: item for item in capability.args}
    call = _drop_unknown_capability_args(
        call,
        declared_arg_names=set(arg_specs),
        deterministic_repairs=deterministic_repairs,
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
                input_closure_policy=arg.input_closure_policy,
            )
            issues.extend(ref_issues)
            if value is None:
                continue
            actual_roles = _resolved_value_semantic_roles(value, ref)
            if (
                arg.accepted_semantic_roles
                and not set(actual_roles).intersection(
                    arg.accepted_semantic_roles
                )
            ):
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.state_role_mismatch",
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
                            "actual_semantic_roles": list(actual_roles),
                            "current_binding": ref.to_payload(),
                            "compatible_refs": compatible_refs(),
                        },
                    )
                )
                continue
            if (
                arg.requires_materialized_state
                and value.state_version_id is None
                and not (
                    value.source_call_id is not None
                    and value.return_name is not None
                )
                and value.condition_id is None
            ):
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
    return call, resolved


def _drop_unknown_capability_args(
    call: FunctionalCall,
    *,
    declared_arg_names: set[str],
    deterministic_repairs: list[FunctionalDeterministicRepair],
) -> FunctionalCall:
    """Drop every wire argument outside the public capability contract."""
    normalized_args = dict(call.args)
    for name in sorted(set(call.args) - declared_arg_names):
        normalized_args.pop(name, None)
        deterministic_repairs.append(
            FunctionalDeterministicRepair(
                call.call_id,
                "drop_unknown_capability_arg",
                f"{name}=provided",
                f"{name}=omitted",
            )
        )
    if normalized_args == call.args:
        return call
    return replace(call, args=normalized_args)


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
    input_closure_policy: CapabilityStateClosurePolicy,
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
        # CallResultRef is a logical DAG edge. Its temporary allocation scope
        # is not authoritative until the placement service has moved the full
        # producer closure and assigned final return scopes. Canonical scope
        # validation after projection remains the hard visibility gate.
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
            return_variant_mismatch = (
                value.return_name is not None
                and value.return_name != ref.return_name
            )
            return None, (
                _issue(
                    "functional_reconciliation",
                    (
                        "functional.return_variant_mismatch"
                        if return_variant_mismatch
                        else "functional.arg_type_mismatch"
                    ),
                    (
                        (
                            "requested call return is not produced for the "
                            "resolved input state: "
                            f"{ref.from_call}.{ref.return_name}; active return "
                            f"is {value.return_name}"
                        )
                        if return_variant_mismatch
                        else (
                            "call result has an incompatible semantic state: "
                            f"{ref.from_call}.{ref.return_name}"
                        )
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": arg_name,
                        "accepted_item_types": list(accepted_types),
                        "actual_type": value.runtime_type,
                        **(
                            {
                                "requested_return": ref.return_name,
                                "active_return": value.return_name,
                            }
                            if return_variant_mismatch
                            else {}
                        ),
                    },
                ),
            )
        closure_issue = _input_state_closure_issue(
            value,
            policy=input_closure_policy,
            arg_name=arg_name,
            call_id=call_id,
            scope_id=scope_id,
        )
        return (None, (closure_issue,)) if closure_issue is not None else (value, ())
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
        materialization = semantic_index.materialize_function_state(
            ref,
            scope_id=scope_id,
            target_runtime_type=(
                "Parabola" if "Parabola" in accepted_types else ""
            ),
            closure_policy=input_closure_policy,
        )
        if materialization.status in {"determined", "single_free"}:
            assert materialization.source is not None
            deterministic_repairs.append(
                FunctionalDeterministicRepair(
                    call_id,
                    "materialize_function_state",
                    f"{ref.kind}:{ref.ref}",
                    (
                        f"Parabola:{materialization.status}:"
                        f"{len(materialization.free_symbol_refs)}_free"
                    ),
                )
            )
            source = materialization.source
            return ResolvedFunctionalValue(
                source.handle,
                source.runtime_type,
                source.valid_scope,
                object_ref=source.object_ref,
                condition_id=source.condition_id,
                dependency_object_refs=source.dependency_object_refs,
                free_symbol_refs=materialization.free_symbol_refs,
                source_state_slot_ids=source.source_state_slot_ids,
                provides_semantic_roles=source.provides_semantic_roles,
                lineage=source.lineage,
                materialized_runtime_type=materialization.target_runtime_type,
                supporting_handles=materialization.supporting_handles,
                math_object_id=source.math_object_id,
                logical_state_key=source.logical_state_key,
                typed_slot_id=source.typed_slot_id,
                state_version_id=source.state_version_id,
                source_version_ids=source.source_version_ids,
            ), ()
        if materialization.status == "underdetermined":
            return None, (
                _issue(
                    "functional_reconciliation",
                    "functional.arg_state_underdetermined",
                    (
                        f"argument {arg_name} cannot materialize {ref.ref}: "
                        "more than one independent free parameter remains"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": arg_name,
                        "accepted_item_types": list(accepted_types),
                        "free_symbol_refs": list(
                            materialization.free_symbol_refs
                        ),
                        "max_independent_free_parameters": 1,
                    },
                ),
            )
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
    value = ResolvedFunctionalValue(
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
        provides_semantic_roles=resolved.provides_semantic_roles,
        lineage=resolved.lineage,
        math_object_id=resolved.math_object_id,
        logical_state_key=resolved.logical_state_key,
        typed_slot_id=resolved.typed_slot_id,
        state_version_id=resolved.state_version_id,
        source_version_ids=resolved.source_version_ids,
    )
    closure_issue = _input_state_closure_issue(
        value,
        policy=input_closure_policy,
        arg_name=arg_name,
        call_id=call_id,
        scope_id=scope_id,
    )
    return (None, (closure_issue,)) if closure_issue is not None else (value, ())


def _input_state_closure_issue(
    value: ResolvedFunctionalValue,
    *,
    policy: CapabilityStateClosurePolicy,
    arg_name: str,
    call_id: str,
    scope_id: str,
) -> FunctionalPlanIssue | None:
    if policy == "any":
        return None
    # A prior-call return only carries a conservative pre-runtime Symbol
    # estimate. Constraint analyzers may reduce several surface symbols to one
    # independent free basis (for example b=1-c). Runtime provenance performs
    # the authoritative closure check after that producer has executed.
    if value.source_call_id is not None:
        return None
    free_symbol_refs = tuple(dict.fromkeys(value.free_symbol_refs))
    max_free = 0 if policy == "closed_only" else 1
    if len(free_symbol_refs) <= max_free:
        return None
    return _issue(
        "functional_reconciliation",
        "functional.arg_state_underdetermined",
        (
            f"argument {arg_name} has {len(free_symbol_refs)} independent "
            f"free parameters; capability accepts at most {max_free}"
        ),
        call_id=call_id,
        scope_id=scope_id,
        details={
            "arg": arg_name,
            "free_symbol_refs": list(free_symbol_refs),
            "max_independent_free_parameters": max_free,
        },
    )


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
        item.kind != "answer"
        and return_type in {"PointList", "SymbolList", "Coefficients"}
    ):
        compatible_answers = tuple(
            f"answer:{goal.id}"
            for goal in question_goals
            if functional_answer_output_type_compatible(
                goal.value_type,
                return_type,
            )
        )
        return None, (
            _issue(
                "functional_reconciliation",
                "functional.return_cardinality_mismatch",
                (
                    f"aggregate return {return_type} cannot bind to singular "
                    f"object {item.ref}"
                ),
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "expected_binding": {
                        "kind": "answer",
                        "value_type": return_type,
                        "cardinality": "aggregate",
                    },
                    "actual_binding": {
                        "kind": item.kind,
                        "ref": item.ref,
                        "value_type": item.value_type,
                        "cardinality": "singular",
                    },
                    "compatible_answer_refs": list(compatible_answers),
                    "repair_guidance": (
                        "Bind an aggregate return to an answer whose "
                        f"value_type is {return_type}; do not bind it to "
                        "one singular MathObject."
                    ),
                },
            ),
        )
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
        if goal is None or not functional_answer_output_type_compatible(
            goal.value_type,
            return_type,
        ):
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
    semantic_items: Sequence[SemanticReadCatalogItem],
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
        handle_registry=handle_registry,
        semantic_items=semantic_items,
    )
    repairs.extend(intermediate_repairs)
    goals_by_ref = {goal.id: goal for goal in question_goals}
    consumers = _call_result_consumers(plan)
    explicitly_bound_goal_refs = {
        binding.ref
        for call in plan.calls
        for binding in call.return_bindings.values()
        if binding.kind == "answer" and binding.ref in goals_by_ref
    }
    non_answer_goal_binding_counts: dict[str, int] = {}
    for call in plan.calls:
        for binding in call.return_bindings.values():
            if binding.kind == "answer" or binding.ref not in goals_by_ref:
                continue
            non_answer_goal_binding_counts[binding.ref] = (
                non_answer_goal_binding_counts.get(binding.ref, 0) + 1
            )

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
                return_spec = returns_by_name.get(return_name)
                exact_goal = goals_by_ref.get(binding.ref)
                if (
                    binding.kind != "answer"
                    and exact_goal is not None
                    and binding.ref not in explicitly_bound_goal_refs
                    and non_answer_goal_binding_counts.get(binding.ref) == 1
                    and not _return_has_downstream_identity_transition(
                        plan,
                        source_call_id=call.call_id,
                        return_name=return_name,
                        catalog=catalog,
                    )
                    and return_spec is not None
                    and functional_answer_output_type_compatible(
                        exact_goal.value_type,
                        return_spec.runtime_type,
                    )
                ):
                    bindings[return_name] = SemanticRef(
                        ref=exact_goal.id,
                        kind="answer",
                        value_type=exact_goal.value_type,
                    )
                    repairs.append(
                        FunctionalDeterministicRepair(
                            call.call_id,
                            "normalize_question_goal_binding_kind",
                            f"{binding.kind}:{binding.ref}",
                            f"answer:{exact_goal.id}",
                        )
                    )
                    continue
                if binding.kind != "answer" or binding.ref in goals_by_ref:
                    continue
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


def _normalize_unique_return_roles(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Rewrite an unknown return label when the capability has one return.

    The repair is deliberately name-agnostic. It is safe only when the
    capability exposes exactly one return, so no mathematical intent or fuzzy
    role matching is involved. Downstream CallResultRefs are rewritten with
    the same alias to keep the call graph closed.
    """

    aliases: dict[tuple[str, str], str] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    scopes: list[FunctionalScope] = []
    for scope in plan.scopes:
        calls: list[FunctionalCall] = []
        for call in scope.calls:
            capability = catalog.get(call.capability_id)
            declared = tuple(item.name for item in capability.returns) if capability else ()
            if len(declared) != 1:
                calls.append(call)
                continue
            canonical = declared[0]
            unknown = unique_ordered(
                name for name in call.return_bindings if name not in declared
            )
            if len(unknown) != 1:
                calls.append(call)
                continue
            source = unknown[0]
            bindings = dict(call.return_bindings)
            expectations = dict(call.return_expectations)
            if canonical in bindings:
                merged_binding = _merge_unique_return_projection_binding(
                    bindings[canonical],
                    bindings[source],
                    scope_id=scope.scope_id,
                    semantic_index=semantic_index,
                )
                if merged_binding is None:
                    calls.append(call)
                    continue
                bindings[canonical] = merged_binding
                bindings.pop(source)
                repair_code = "merge_unique_return_projection_binding"
            else:
                if source in bindings:
                    bindings[canonical] = bindings.pop(source)
                repair_code = "normalize_unique_return_role"
            if source in expectations:
                source_expectation = expectations.pop(source)
                canonical_expectation = expectations.get(canonical)
                if canonical_expectation is None:
                    expectations[canonical] = source_expectation
                elif canonical_expectation != source_expectation:
                    calls.append(call)
                    continue
            aliases[(call.call_id, source)] = canonical
            repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    repair_code,
                    source,
                    canonical,
                )
            )
            calls.append(
                replace(
                    call,
                    return_bindings=bindings,
                    return_expectations=expectations,
                )
            )
        scopes.append(replace(scope, calls=tuple(calls)))
    if not aliases:
        return plan, ()
    rewritten_scopes: list[FunctionalScope] = []
    for scope in scopes:
        calls = []
        for call in scope.calls:
            args = {
                name: tuple(
                    replace(
                        ref,
                        return_name=aliases.get(
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
        rewritten_scopes.append(replace(scope, calls=tuple(calls)))
    return replace(plan, scopes=tuple(rewritten_scopes)), tuple(repairs)


def _normalize_declared_return_role_aliases(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Normalize shared semantic-role vocabulary before contract validation.

    This is intentionally stricter than fuzzy return-name matching: an alias
    is accepted only when the shared role registry maps it to a return that the
    selected capability actually declares. Conflicting projections remain in
    the plan so normal contract validation can report them.
    """

    aliases: dict[tuple[str, str], str] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    scopes: list[FunctionalScope] = []
    for scope in plan.scopes:
        calls: list[FunctionalCall] = []
        for call in scope.calls:
            capability = catalog.get(call.capability_id)
            declared = (
                {item.name for item in capability.returns}
                if capability is not None
                else set()
            )
            bindings = dict(call.return_bindings)
            expectations = dict(call.return_expectations)
            candidate_names = unique_ordered(
                (*bindings.keys(), *expectations.keys())
            )
            changed = False
            for source in candidate_names:
                if source in declared:
                    continue
                canonical = canonical_straightening_endpoint_name(source)
                if canonical is None or canonical not in declared:
                    continue
                source_binding = bindings.get(source)
                canonical_binding = bindings.get(canonical)
                source_expectation = expectations.get(source)
                canonical_expectation = expectations.get(canonical)
                if (
                    source_binding is not None
                    and canonical_binding is not None
                    and source_binding != canonical_binding
                ):
                    continue
                if (
                    source_expectation is not None
                    and canonical_expectation is not None
                    and source_expectation != canonical_expectation
                ):
                    continue
                if source_binding is not None:
                    bindings[canonical] = source_binding
                    bindings.pop(source, None)
                if source_expectation is not None:
                    expectations[canonical] = source_expectation
                    expectations.pop(source, None)
                aliases[(call.call_id, source)] = canonical
                repairs.append(
                    FunctionalDeterministicRepair(
                        call.call_id,
                        "normalize_declared_return_role_alias",
                        source,
                        canonical,
                    )
                )
                changed = True
            calls.append(
                replace(
                    call,
                    return_bindings=bindings,
                    return_expectations=expectations,
                )
                if changed
                else call
            )
        scopes.append(replace(scope, calls=tuple(calls)))
    if not aliases:
        return plan, ()
    return (
        replace(
            plan,
            scopes=tuple(
                replace(
                    scope,
                    calls=tuple(
                        replace(
                            call,
                            args={
                                name: tuple(
                                    replace(
                                        ref,
                                        return_name=aliases.get(
                                            (ref.from_call, ref.return_name),
                                            ref.return_name,
                                        ),
                                    )
                                    if isinstance(ref, CallResultRef)
                                    else ref
                                    for ref in refs
                                )
                                for name, refs in call.args.items()
                            },
                        )
                        for call in scope.calls
                    ),
                )
                for scope in scopes
            ),
        ),
        tuple(repairs),
    )


def _merge_unique_return_projection_binding(
    canonical: SemanticRef,
    extra: SemanticRef,
    *,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> SemanticRef | None:
    """Merge two destinations only when they project the same MathObject."""

    canonical_objects = _projection_binding_object_refs(
        canonical,
        scope_id=scope_id,
        semantic_index=semantic_index,
    )
    extra_objects = _projection_binding_object_refs(
        extra,
        scope_id=scope_id,
        semantic_index=semantic_index,
    )
    if (
        len(canonical_objects) != 1
        or len(extra_objects) != 1
        or canonical_objects != extra_objects
    ):
        return None
    if canonical.kind == "answer":
        return canonical
    if extra.kind == "answer":
        return extra
    return canonical if canonical == extra else None


def _projection_binding_object_refs(
    binding: SemanticRef,
    *,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[str, ...]:
    if binding.kind == "answer":
        answer_handle = (
            binding.ref
            if binding.ref.startswith("answer:")
            else f"answer:{binding.ref}"
        )
        target = semantic_index.handle_registry.answer_target_handles.get(
            answer_handle
        )
        return (target,) if target is not None else ()
    return semantic_index.object_refs_for(binding, scope_id=scope_id)


def _return_has_downstream_identity_transition(
    plan: FunctionalPlan,
    *,
    source_call_id: str,
    return_name: str,
    catalog: FunctionalCapabilityCatalog,
) -> bool:
    """Whether a later call writes a newer state of this exact return object."""

    for call in plan.calls:
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        identity_args = {
            item.identity_arg
            for item in capability.returns
            if item.identity_policy == "preserve_input_object"
            and item.identity_arg is not None
        }
        for arg_name in identity_args:
            if any(
                isinstance(ref, CallResultRef)
                and ref.from_call == source_call_id
                and ref.return_name == return_name
                for ref in call.args.get(arg_name, ())
            ):
                return True
    return False


def _infer_closed_answer_expectations(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    question_goals: Sequence[QuestionGoal],
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Make the answer destination authoritative for result closure.

    ``return_expectations`` is an LLM memory aid, not an execution fact. An
    explicitly open expectation on a final answer is therefore normalized to
    the return's closed form and verified against runtime provenance later.
    """
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
                ):
                    continue
                required_form = _closed_answer_result_form(
                    result,
                    answer_value_type=goal.value_type,
                )
                if (
                    required_form is None
                    or expectations.get(return_name) == required_form
                ):
                    continue
                previous = expectations.get(return_name)
                expectations[return_name] = required_form
                repairs.append(
                    FunctionalDeterministicRepair(
                        call.call_id,
                        (
                            "infer_closed_answer_result_form"
                            if previous is None
                            else "normalize_answer_result_form"
                        ),
                        (
                            f"{return_name}=omitted"
                            if previous is None
                            else f"{return_name}={previous}"
                        ),
                        required_form,
                    )
                )
            calls.append(replace(call, return_expectations=expectations))
        scopes.append(replace(scope, calls=tuple(calls)))
    return replace(plan, scopes=tuple(scopes)), tuple(repairs)


def _closed_answer_result_form(
    result: FunctionalCapabilityReturn,
    *,
    answer_value_type: str,
) -> FunctionalResultForm | None:
    if (
        "closed_value" in result.possible_forms
        and answer_value_type_requires_closed_scalar(answer_value_type)
    ):
        return "closed_value"
    if "closed_state" in result.possible_forms:
        return "closed_state"
    return None


def _infer_symbolic_target_args_from_consumers(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Recover a missing target Symbol from exact downstream substitution.

    The inference uses only typed return identity and explicit Functional refs:
    a consumer must pass the producer return as a ParameterValue and name one
    Symbol argument for that substitution. Strategy text and symbol names are
    deliberately ignored.
    """

    ordered_calls = list(plan.calls)
    replacements: dict[str, FunctionalCall] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    for position, call in enumerate(ordered_calls):
        capability = catalog.get(call.capability_id)
        closure = (
            capability.source.symbolic_closure
            if capability is not None and isinstance(capability.source, FunctionSpec)
            else None
        )
        if closure is None or closure.target_arg in call.args:
            continue
        identity_returns = {
            item.name
            for item in capability.returns
            if item.identity_policy == "preserve_input_object"
            and item.identity_arg == closure.target_arg
        }
        if not identity_returns:
            continue
        candidates: list[SemanticRef] = []
        for return_name in identity_returns:
            binding = call.return_bindings.get(return_name)
            if binding is not None and binding.kind == "symbol":
                candidates.append(binding)
        for consumer in ordered_calls[position + 1 :]:
            consumer_capability = catalog.get(consumer.capability_id)
            if consumer_capability is None:
                continue
            referenced_value_args = {
                arg_name
                for arg_name, refs in consumer.args.items()
                if any(
                    isinstance(ref, CallResultRef)
                    and ref.from_call == call.call_id
                    and ref.return_name in identity_returns
                    for ref in refs
                )
            }
            if not referenced_value_args:
                continue
            consumer_args = {
                item.name: item for item in consumer_capability.args
            }
            if not any(
                item is not None
                and any(
                    runtime_type_compatible(expected, "ParameterValue")
                    for expected in (
                        item.accepted_item_types or (item.runtime_type,)
                    )
                )
                for item in (
                    consumer_args.get(arg_name)
                    for arg_name in referenced_value_args
                )
            ):
                continue
            candidates.extend(
                ref
                for arg_name, refs in consumer.args.items()
                for arg in (consumer_args.get(arg_name),)
                if arg is not None
                and arg.semantic_role == "parameter"
                and any(
                    runtime_type_compatible(expected, "Symbol")
                    for expected in (
                        arg.accepted_item_types or (arg.runtime_type,)
                    )
                )
                for ref in refs
                if isinstance(ref, SemanticRef) and ref.kind == "symbol"
            )
        unique = {
            (item.kind, item.ref, item.value_type): item for item in candidates
        }
        if len(unique) != 1:
            continue
        target = next(iter(unique.values()))
        args = dict(call.args)
        args[closure.target_arg] = (target,)
        replacements[call.call_id] = replace(call, args=args)
        repairs.append(
            FunctionalDeterministicRepair(
                call.call_id,
                "infer_symbolic_target_from_consumer",
                f"{closure.target_arg}=omitted",
                f"{closure.target_arg}={target.ref}",
            )
        )
    if not replacements:
        return plan, ()
    return (
        replace(
            plan,
            scopes=tuple(
                replace(
                    scope,
                    calls=tuple(
                        replacements.get(call.call_id, call)
                        for call in scope.calls
                    ),
                )
                for scope in plan.scopes
            ),
        ),
        tuple(repairs),
    )


def _resolver_injected_binding_keys(
    plan: FunctionalPlan,
    repairs: Sequence[FunctionalDeterministicRepair],
    *,
    catalog: FunctionalCapabilityCatalog,
) -> frozenset[tuple[str, str]]:
    """Preserve resolver authority for deterministic semantic arg recovery."""
    capability_by_call = {
        call.call_id: catalog.get(call.capability_id) for call in plan.calls
    }
    keys: set[tuple[str, str]] = set()
    for repair in repairs:
        if repair.action != "infer_symbolic_target_from_consumer":
            continue
        capability = capability_by_call.get(repair.call_id)
        closure = (
            getattr(capability.source, "symbolic_closure", None)
            if capability is not None
            else None
        )
        if closure is not None:
            keys.add((repair.call_id, closure.target_arg))
    return frozenset(keys)


def _drop_redundant_open_answer_bindings(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    question_goals: Sequence[QuestionGoal],
    handle_registry: CanonicalHandleRegistry,
    semantic_items: Sequence[SemanticReadCatalogItem],
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Demote a consumed open state when one closed descendant owns its answer.

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
                or call.return_expectations.get(return_name)
                not in {"open_expression", "open_state"}
                or return_spec is None
                or not (
                    {"open_expression", "open_state"}
                    & set(return_spec.possible_forms)
                )
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
            open_form = call.return_expectations.get(return_name)
            repairs.append(
                FunctionalDeterministicRepair(
                    call.call_id,
                    (
                        "drop_intermediate_open_expression_answer_binding"
                        if open_form == "open_expression"
                        else "demote_intermediate_open_state_answer_binding"
                    ),
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
                    return_bindings=_demoted_open_answer_bindings(
                        call,
                        dropped=dropped,
                        handle_registry=handle_registry,
                        semantic_items=semantic_items,
                    ),
                )
                if call.call_id in dropped_call_ids
                else call
                for call in scope.calls
            ),
        )
        for scope in plan.scopes
    )
    return replace(plan, scopes=normalized_scopes), tuple(repairs)


def _demoted_open_answer_bindings(
    call: FunctionalCall,
    *,
    dropped: set[tuple[str, str]],
    handle_registry: CanonicalHandleRegistry,
    semantic_items: Sequence[SemanticReadCatalogItem],
) -> dict[str, SemanticRef]:
    bindings: dict[str, SemanticRef] = {}
    for name, binding in call.return_bindings.items():
        if (call.call_id, name) not in dropped:
            bindings[name] = binding
            continue
        target = _answer_target_object_semantic_ref(
            binding,
            handle_registry=handle_registry,
            semantic_items=semantic_items,
        )
        if target is not None:
            bindings[name] = target
    return bindings


def _answer_target_object_semantic_ref(
    binding: SemanticRef,
    *,
    handle_registry: CanonicalHandleRegistry,
    semantic_items: Sequence[SemanticReadCatalogItem],
) -> SemanticRef | None:
    """Return the prompt-safe object view behind an answer binding, if any."""

    if binding.kind != "answer":
        return None
    answer_handle = f"answer:{binding.ref}"
    target_handle = handle_registry.answer_target_handles.get(answer_handle)
    if target_handle is None:
        return None
    candidates = tuple(
        item
        for item in semantic_items
        if item.prompt_visible
        and item.handle == target_handle
        and item.kind != "answer"
    )
    if len(candidates) != 1:
        return None
    item = candidates[0]
    return SemanticRef(ref=item.ref, kind=item.kind, value_type=item.value_type)


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
                or call.return_expectations.get(return_spec.name)
                not in {"closed_value", "closed_state"}
                or not (
                    {"closed_value", "closed_state"}
                    & set(return_spec.possible_forms)
                )
                or not functional_answer_output_type_compatible(
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
        and functional_answer_output_type_compatible(
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
    catalog: FunctionalCapabilityCatalog,
    future_return_object_hints: Mapping[
        tuple[str, str],
        tuple[str, ...],
    ],
) -> dict[tuple[str, str], tuple[tuple[str, str], ...]]:
    """Assign semantic object reads to their nearest planned producer.

    A semantic reference names a MathObject, not a particular state version.
    Prefer the latest prior producer already visible in the consumer branch.
    A producer in a sibling branch is used only when it is the sole prior
    producer, allowing B2 to hoist that uniquely shared state. Exact
    StateVersion dependencies remain authoritative after reconciliation.
    """
    call_order = {
        call.call_id: index for index, call in enumerate(plan.calls)
    }
    call_scopes = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    calls_by_id = {call.call_id: call for call in plan.calls}
    producers_by_object: dict[str, list[tuple[int, str, str]]] = {}
    for call in plan.calls:
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        for returned in capability.returns:
            object_refs = future_return_object_hints.get(
                (call.call_id, returned.name),
                (),
            )
            if len(object_refs) != 1:
                continue
            producers_by_object.setdefault(object_refs[0], []).append(
                (
                    call_order[call.call_id],
                    call.call_id,
                    call_scopes[call.call_id],
                )
            )

    consumers_by_object: dict[str, list[tuple[str, str]]] = {}
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
                        consumers_by_object.setdefault(object_ref, []).append(
                            (call.call_id, scope.scope_id)
                        )
                    condition, _matches = semantic_index.resolve(
                        ref,
                        scope_id=scope.scope_id,
                        accepted_types=("Condition",),
                    )
                    if condition is not None:
                        for _role, object_refs in condition.object_roles:
                            for object_ref in object_refs:
                                consumers_by_object.setdefault(
                                    object_ref,
                                    [],
                                ).append(
                                    (call.call_id, scope.scope_id)
                                )
            capability = catalog.get(call.capability_id)
            if capability is None:
                continue
            for object_ref in _hidden_auto_arg_object_refs(
                call,
                scope_id=scope.scope_id,
                capability=capability,
                semantic_index=semantic_index,
            ):
                consumers_by_object.setdefault(object_ref, []).append(
                    (call.call_id, scope.scope_id)
                )

    result: dict[tuple[str, str], list[tuple[str, str]]] = {}
    registry = semantic_index.handle_registry
    for object_ref, consumers in consumers_by_object.items():
        producers = producers_by_object.get(object_ref, ())
        for consumer_call_id, consumer_scope in unique_ordered(consumers):
            consumer_index = call_order[consumer_call_id]
            prior = tuple(
                producer
                for producer in producers
                if producer[0] < consumer_index
                and producer[1] != consumer_call_id
            )
            visible = tuple(
                producer
                for producer in prior
                if visible_from_valid_scope(
                    producer[2],
                    scope_id=consumer_scope,
                    registry=registry,
                )
            )
            selected = (
                max(visible, key=lambda item: item[0])
                if visible
                else (prior[0] if len(prior) == 1 else None)
            )
            if selected is None:
                continue
            result.setdefault((selected[1], object_ref), []).append(
                (consumer_call_id, consumer_scope)
            )
    return {
        producer_key: unique_ordered(consumers)
        for producer_key, consumers in result.items()
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


def _without_functional_return_binding(
    call: FunctionalCall,
    return_name: str,
) -> FunctionalCall:
    bindings = dict(call.return_bindings)
    bindings.pop(return_name, None)
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


def _synchronize_wire_resolved_args(
    plan: FunctionalPlan,
    *,
    reconciled: Sequence[FunctionalCallReconciliation],
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
    produced: (
        Mapping[tuple[str, str], ResolvedFunctionalValue] | None
    ) = None,
) -> tuple[
    list[FunctionalCallReconciliation],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
]:
    """Keep typed wire bindings aligned with the final effective plan.

    Deterministic plan normalization may narrow a many-valued wire argument
    after an earlier resolution pass. Resolver/compiler-owned arguments remain
    untouched; public wire arguments are filtered only by exact typed identity.
    """

    calls_by_id = {call.call_id: call for call in plan.calls}
    updated: list[FunctionalCallReconciliation] = []
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []
    for item in reconciled:
        call = calls_by_id.get(item.call_id)
        capability = catalog.get(item.capability_id)
        if call is None or capability is None:
            updated.append(item)
            continue
        args = dict(item.resolved_args)
        for spec in capability.args:
            if spec.binding_authority != "wire" or spec.name not in call.args:
                continue
            refs = call.args[spec.name]
            existing = args.get(spec.name, ())
            selected: list[ResolvedFunctionalValue] = []
            remaining = list(existing)
            for ref in refs:
                matches = [
                    candidate
                    for candidate in remaining
                    if _resolved_value_matches_wire_ref(
                        candidate,
                        ref,
                        spec=spec,
                        scope_id=item.scope_id,
                        semantic_index=semantic_index,
                        produced=produced or {},
                    )
                ]
                replacement = None
                if not matches and isinstance(ref, CallResultRef):
                    replacement = (produced or {}).get(
                        (ref.from_call, ref.return_name)
                    )
                elif not matches and isinstance(ref, SemanticRef):
                    replacement = _resolved_wire_semantic_value(
                        ref,
                        spec=spec,
                        scope_id=item.scope_id,
                        semantic_index=semantic_index,
                        produced=produced or {},
                        plan=plan,
                        consumer_call_id=item.call_id,
                    )
                if replacement is not None:
                    accepted_types = (
                        spec.accepted_item_types or (spec.runtime_type,)
                    )
                    if any(
                        runtime_type_compatible(
                            accepted,
                            replacement.runtime_type,
                        )
                        for accepted in accepted_types
                    ):
                        matches = [replacement]
                if len(matches) > 1:
                    identities = {
                        (
                            candidate.state_version_id,
                            candidate.condition_id,
                            candidate.math_object_id,
                            candidate.source_call_id,
                            candidate.return_name,
                            candidate.handle,
                        )
                        for candidate in matches
                    }
                    if len(identities) == 1:
                        matches = [matches[0]]
                if len(matches) != 1:
                    issues.append(
                        _issue(
                            "functional_reconciliation",
                            "planner.state_placement_drift",
                            (
                                "effective wire argument cannot be matched "
                                "to one typed resolved value"
                            ),
                            call_id=item.call_id,
                            scope_id=item.scope_id,
                            details={
                                "arg": spec.name,
                                "wire_ref": ref.to_payload(),
                                "resolved_count": len(existing),
                                "matching_count": len(matches),
                            },
                        )
                    )
                    selected = []
                    break
                selected.append(matches[0])
                if matches[0] in remaining:
                    remaining.remove(matches[0])
            if len(selected) != len(refs):
                continue
            args[spec.name] = tuple(selected)
            repairs.append(
                FunctionalDeterministicRepair(
                    item.call_id,
                    "synchronize_typed_wire_arg",
                    f"{spec.name}:{len(existing)}_resolved_values",
                    f"{spec.name}:{len(selected)}_wire_values",
                )
            )
        updated.append(replace(item, resolved_args=args))
    return updated, tuple(repairs), tuple(issues)


def _refresh_context_auto_args_for_effective_order(
    plan: FunctionalPlan,
    *,
    reconciled: Sequence[FunctionalCallReconciliation],
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    list[FunctionalCallReconciliation],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
]:
    """Re-resolve hidden Context selectors at their final call position.

    The first reconciliation pass may run before deterministic plan rewriting
    has established the effective call order. Context-owned selectors must not
    retain a stale object version from that provisional pass. Replaying only
    those selectors here gives both the legacy bridge and the transactional
    interpreter the same call-time typed dependency.
    """

    calls_by_id = {call.call_id: call for call in plan.calls}
    reconciled_by_id = {item.call_id: item for item in reconciled}
    call_order = {
        call.call_id: index for index, call in enumerate(plan.calls)
    }
    planned_return_expectations = {
        (call.call_id, return_name): expectation
        for call in plan.calls
        for return_name, expectation in call.return_expectations.items()
    }
    updated_by_id: dict[str, FunctionalCallReconciliation] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []
    for call in plan.calls:
        item = reconciled_by_id.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if item is None or capability is None:
            continue
        context_auto_names = {
            auto.name
            for auto in capability.auto_args
            if _has_context_auto_resolver(auto.selector)
            and any(
                value.state_version_id is not None
                for value in item.resolved_args.get(auto.name, ())
            )
        }
        if not context_auto_names:
            updated_by_id[call.call_id] = item
            continue
        current_order = call_order[call.call_id]
        prior_produced = {
            key: value
            for key, value in produced.items()
            if value.source_call_id in call_order
            and call_order[value.source_call_id] < current_order
        }
        base_args = {
            name: values
            for name, values in item.resolved_args.items()
            if name not in context_auto_names
        }
        additions, call_repairs, call_issues = _resolve_context_auto_args(
            capability,
            base_args,
            call_id=call.call_id,
            scope_id=item.scope_id,
            produced=prior_produced,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
            planned_return_expectations=planned_return_expectations,
        )
        base_args.update(additions)
        updated_by_id[call.call_id] = replace(
            item,
            resolved_args=base_args,
        )
        repairs.extend(call_repairs)
        issues.extend(call_issues)
    return (
        [
            updated_by_id.get(item.call_id, item)
            for item in reconciled
            if item.call_id in calls_by_id
        ],
        tuple(repairs),
        tuple(issues),
    )


def _resolved_wire_semantic_value(
    ref: SemanticRef,
    *,
    spec: FunctionalCapabilityArg,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    plan: FunctionalPlan,
    consumer_call_id: str,
) -> ResolvedFunctionalValue | None:
    accepted_types = spec.accepted_item_types or (spec.runtime_type,)
    view, _ = semantic_index.resolve(
        ref,
        scope_id=scope_id,
        accepted_types=accepted_types,
        accepted_condition_kinds=spec.accepted_condition_kinds,
    )
    if view is None:
        return None
    call_order = {
        call.call_id: index for index, call in enumerate(plan.calls)
    }
    consumer_order = call_order.get(consumer_call_id, len(call_order))
    produced_candidates = [
        value
        for value in produced.values()
        if value.source_call_id in call_order
        and call_order[value.source_call_id] < consumer_order
        and any(
            runtime_type_compatible(accepted, value.runtime_type)
            for accepted in accepted_types
        )
        and visible_from_valid_scope(
            value.valid_scope,
            scope_id=scope_id,
            registry=semantic_index.handle_registry,
        )
        and (
            (
                view.math_object_id is not None
                and value.math_object_id == view.math_object_id
            )
            or (
                view.state_version_id is not None
                and value.state_version_id == view.state_version_id
            )
        )
    ]
    if produced_candidates:
        latest_order = max(
            call_order[value.source_call_id]
            for value in produced_candidates
            if value.source_call_id is not None
        )
        latest = {
            (
                value.source_call_id,
                value.return_name,
                value.state_version_id,
            ): value
            for value in produced_candidates
            if call_order[value.source_call_id] == latest_order
        }
        if len(latest) == 1:
            return next(iter(latest.values()))
    return ResolvedFunctionalValue(
        handle=view.handle,
        runtime_type=view.runtime_type,
        valid_scope=view.valid_scope,
        state_slot_id=view.state_slot_id,
        object_ref=view.object_ref,
        condition_id=view.condition_id,
        object_roles=view.object_roles,
        dependency_object_refs=view.dependency_object_refs,
        free_symbol_refs=view.free_symbol_refs,
        source_state_slot_ids=view.source_state_slot_ids,
        provides_semantic_roles=view.provides_semantic_roles,
        lineage=view.lineage,
        math_object_id=view.math_object_id,
        logical_state_key=view.logical_state_key,
        typed_slot_id=view.typed_slot_id,
        state_version_id=view.state_version_id,
        source_version_ids=view.source_version_ids,
    )


def _resolved_value_matches_wire_ref(
    value: ResolvedFunctionalValue,
    ref: FunctionalRef,
    *,
    spec: FunctionalCapabilityArg,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
) -> bool:
    if isinstance(ref, CallResultRef):
        if (
            value.source_call_id != ref.from_call
            or value.return_name != ref.return_name
        ):
            return False
        expected = produced.get((ref.from_call, ref.return_name))
        if expected is None:
            return False
        if (
            expected.state_version_id is not None
            or value.state_version_id is not None
        ):
            return expected.state_version_id == value.state_version_id
        if expected.condition_id is not None or value.condition_id is not None:
            return expected.condition_id == value.condition_id
        if (
            expected.math_object_id is not None
            or value.math_object_id is not None
        ):
            return expected.math_object_id == value.math_object_id
        return (
            expected.source_call_id == value.source_call_id
            and expected.return_name == value.return_name
            and expected.runtime_type == value.runtime_type
        )
    accepted_types = spec.accepted_item_types or (spec.runtime_type,)
    view, _ = semantic_index.resolve(
        ref,
        scope_id=scope_id,
        accepted_types=accepted_types,
        accepted_condition_kinds=spec.accepted_condition_kinds,
    )
    if view is None:
        object_refs = semantic_index.object_refs_for(
            ref,
            scope_id=scope_id,
        )
        return (
            len(object_refs) == 1
            and value.object_ref == object_refs[0]
        )
    if (
        view.state_version_id is not None
        or value.state_version_id is not None
    ):
        return view.state_version_id == value.state_version_id
    if view.condition_id is not None or value.condition_id is not None:
        return view.condition_id == value.condition_id
    if view.math_object_id is not None or value.math_object_id is not None:
        return view.math_object_id == value.math_object_id
    return (
        view.object_ref is not None
        and view.object_ref == value.object_ref
    )


def _projected_read_handles(
    value: ResolvedFunctionalValue,
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    if value.materialized_runtime_type is not None:
        return tuple(
            unique_ordered((value.handle, *value.supporting_handles))
        )
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


def _functional_dependency_kinds(
    plan: FunctionalPlan,
    calls: Sequence[FunctionalCallReconciliation],
    *,
    dependency_graph: Mapping[str, tuple[str, ...]],
    projected_state_dependencies: Sequence[Any],
) -> dict[str, dict[str, str]]:
    """Preserve the typed origin of every authoritative dependency edge."""

    result: dict[str, dict[str, str]] = {
        call_id: {} for call_id in dependency_graph
    }
    for call in plan.calls:
        for refs in call.args.values():
            for ref in refs:
                if isinstance(ref, CallResultRef):
                    result.setdefault(call.call_id, {})[
                        ref.from_call
                    ] = "call_result"
    producer_by_version = {
        returned.selected_version_id: call.call_id
        for call in calls
        for returned in call.returns
        if returned.selected_version_id is not None
    }
    for call in calls:
        for values in call.resolved_args.values():
            for value in values:
                if value.source_call_id is None:
                    continue
                if value.condition_id is not None:
                    kind = "condition"
                elif (
                    value.state_version_id is not None
                    or value.source_version_ids
                ):
                    kind = "state_version"
                else:
                    kind = "semantic_object"
                result.setdefault(call.call_id, {})[
                    value.source_call_id
                ] = kind
        for returned in call.returns:
            for version_id in (
                *(
                    (returned.previous_version_id,)
                    if returned.previous_version_id is not None
                    else ()
                ),
                *returned.source_version_ids,
            ):
                producer = producer_by_version.get(version_id)
                if producer is not None and producer != call.call_id:
                    result.setdefault(call.call_id, {})[
                        producer
                    ] = "state_version"
    for dependency in projected_state_dependencies:
        consumer = dependency.step_id
        producer = (
            dependency.source_step_id
            if dependency.source_step_id is not None
            else None
        )
        if producer is None and dependency.state_version_id is not None:
            producer = producer_by_version.get(
                dependency.state_version_id
            )
        if producer is not None and producer != consumer:
            result.setdefault(consumer, {})[
                producer
            ] = "state_version"
    for consumer, producers in dependency_graph.items():
        for producer in producers:
            result.setdefault(consumer, {}).setdefault(
                producer,
                "semantic_object",
            )
    return {
        consumer: {
            producer: kind
            for producer, kind in producers.items()
            if producer in dependency_graph.get(consumer, ())
        }
        for consumer, producers in result.items()
    }


def _with_hidden_condition_object_dependencies(
    plan: FunctionalPlan,
    *,
    dependency_graph: Mapping[str, tuple[str, ...]],
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
    future_return_object_hints: Mapping[
        tuple[str, str], tuple[str, ...]
    ],
) -> dict[str, tuple[str, ...]]:
    """Add producer edges implied by semantic object state requirements.

    Explicit object refs can denote identity before their computed state exists;
    materialized-state args must therefore depend on the prior call that writes
    that object. Some capabilities also expose one structured Condition while their runtime
    adapter deterministically expands the Condition's object roles into hidden
    Point inputs. Those objects may be materialized by earlier calls even
    though the wire plan has no explicit CallResultRef. Recording the edge here
    prevents the consumer from being reported as an independent missing-state
    failure when its producer is already invalid.
    """

    result = {
        call_id: tuple(dependencies)
        for call_id, dependencies in dependency_graph.items()
    }
    ordered = tuple(
        (scope.scope_id, call)
        for scope in plan.scopes
        for call in scope.calls
    )
    order_by_id = {
        call.call_id: index for index, (_scope_id, call) in enumerate(ordered)
    }
    call_scopes = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    calls_by_id = {call.call_id: call for call in plan.calls}
    producers_by_object: dict[str, list[tuple[str, str, str]]] = {}
    for (call_id, return_name), object_refs in future_return_object_hints.items():
        for object_ref in object_refs:
            producers_by_object.setdefault(object_ref, []).append(
                (call_id, return_name, call_scopes[call_id])
            )

    for scope_id, call in ordered:
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        produced_object_refs = frozenset(
            object_ref
            for (producer_call_id, _return_name), object_refs in (
                future_return_object_hints.items()
            )
            if producer_call_id == call.call_id
            for object_ref in object_refs
        )
        hidden_dependencies: list[str] = []
        args_by_name = {item.name: item for item in capability.args}
        for arg_name, refs in call.args.items():
            arg = args_by_name.get(arg_name)
            accepted_item_types = (
                arg.accepted_item_types or (arg.runtime_type,)
                if arg is not None
                else ()
            )
            consumes_point_state = any(
                runtime_type_compatible(expected, actual)
                for expected in accepted_item_types
                for actual in ("Point", "PointList")
            )
            if arg is None or not (
                arg.requires_materialized_state or consumes_point_state
            ):
                continue
            for ref in refs:
                if not isinstance(ref, SemanticRef) or not is_object_semantic_kind(
                    ref.kind
                ):
                    continue
                resolved, _matches = semantic_index.resolve(
                    ref,
                    scope_id=scope_id,
                    accepted_types=accepted_item_types,
                    accepted_condition_kinds=arg.accepted_condition_kinds,
                )
                if (
                    resolved is not None
                    and _resolved_value_satisfies_closure_policy(
                        resolved,
                        policy=arg.input_closure_policy,
                    )
                ):
                    continue
                for object_ref in semantic_index.object_refs_for(
                    ref,
                    scope_id=scope_id,
                ):
                    if _context_has_materialized_object_state(
                        semantic_index,
                        object_ref=object_ref,
                        scope_id=scope_id,
                    ):
                        continue
                    producer = _select_planned_state_producer(
                        object_ref,
                        consumer_call=call,
                        consumer_scope_id=scope_id,
                        producers_by_object=producers_by_object,
                        calls_by_id=calls_by_id,
                        dependency_graph=result,
                        order_by_id=order_by_id,
                        handle_registry=semantic_index.handle_registry,
                        allow_future=object_ref not in produced_object_refs,
                    )
                    if producer is not None:
                        hidden_dependencies.append(producer)
        if not (capability.auto_args or capability.context_resolvers):
            result[call.call_id] = unique_ordered(
                (*result.get(call.call_id, ()), *hidden_dependencies)
            )
            continue
        for object_ref, requires_closed_state in (
            _hidden_auto_arg_object_requirements(
                call,
                scope_id=scope_id,
                capability=capability,
                semantic_index=semantic_index,
            )
        ):
            if _call_explicitly_supplies_object(
                call,
                object_ref=object_ref,
                scope_id=scope_id,
                requires_closed_state=requires_closed_state,
                semantic_index=semantic_index,
            ):
                continue
            if _context_has_materialized_object_state(
                semantic_index,
                object_ref=object_ref,
                scope_id=scope_id,
                requires_closed_state=requires_closed_state,
            ):
                continue
            producer = _select_planned_state_producer(
                object_ref,
                consumer_call=call,
                consumer_scope_id=scope_id,
                producers_by_object=producers_by_object,
                calls_by_id=calls_by_id,
                dependency_graph=result,
                order_by_id=order_by_id,
                handle_registry=semantic_index.handle_registry,
                requires_closed_state=requires_closed_state,
            )
            if producer is not None:
                hidden_dependencies.append(producer)
        for refs in call.args.values():
            for ref in refs:
                if not isinstance(ref, SemanticRef):
                    continue
                condition, _matches = semantic_index.resolve(
                    ref,
                    scope_id=scope_id,
                    accepted_types=("Condition",),
                )
                if condition is None or not condition.object_roles:
                    continue
                for _role, object_refs in condition.object_roles:
                    for object_ref in object_refs:
                        if _call_explicitly_supplies_object(
                            call,
                            object_ref=object_ref,
                            scope_id=scope_id,
                            requires_closed_state=False,
                            semantic_index=semantic_index,
                        ):
                            continue
                        if object_ref in produced_object_refs:
                            continue
                        if _context_has_materialized_object_state(
                            semantic_index,
                            object_ref=object_ref,
                            scope_id=scope_id,
                        ):
                            continue
                        producer = _select_planned_state_producer(
                            object_ref,
                            consumer_call=call,
                            consumer_scope_id=scope_id,
                            producers_by_object=producers_by_object,
                            calls_by_id=calls_by_id,
                            dependency_graph=result,
                            order_by_id=order_by_id,
                            handle_registry=semantic_index.handle_registry,
                        )
                        if producer is not None:
                            hidden_dependencies.append(producer)
        result[call.call_id] = unique_ordered(
            (*result.get(call.call_id, ()), *hidden_dependencies)
        )
    return result


def _resolved_value_satisfies_closure_policy(
    value: FunctionalSemanticView,
    *,
    policy: CapabilityStateClosurePolicy,
) -> bool:
    if policy == "closed_only":
        return not value.free_symbol_refs
    if policy == "closed_or_single_free":
        return len(value.free_symbol_refs) <= 1
    return True


def _call_explicitly_supplies_object(
    call: FunctionalCall,
    *,
    object_ref: str,
    scope_id: str,
    requires_closed_state: bool,
    semantic_index: FunctionalSemanticIndex,
) -> bool:
    """Whether a wire value already satisfies one hidden object requirement."""

    return any(
        view.object_ref == object_ref
        and (not requires_closed_state or not view.free_symbol_refs)
        for refs in call.args.values()
        for ref in refs
        if isinstance(ref, SemanticRef)
        for view in semantic_index.views
        if view.ref == ref.ref
        and view.kind == ref.kind
        and view.object_ref is not None
        and (
            view.state_version_id is not None
            or view.state_slot_id is not None
            or view.condition_id is not None
        )
        and visible_from_valid_scope(
            view.valid_scope,
            scope_id=scope_id,
            registry=semantic_index.handle_registry,
        )
    )


def _hidden_auto_arg_object_refs(
    call: FunctionalCall,
    *,
    scope_id: str,
    capability: FunctionalCapability,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[str, ...]:
    """Project structured auto-role selectors to their MathObject inputs.

    This pre-resolution projection is intentionally limited to selectors whose
    object role is fully determined by structured ProblemIR fields. It lets
    placement see the same hidden object dependency that the later resolver
    will consume, without parsing descriptions or guessing from visible
    objects.
    """

    result: list[str] = []
    for auto in capability.auto_args:
        if not auto.selector.startswith("angle_sum:"):
            continue
        role = auto.selector.split(":", 1)[1]
        if role in {"condition", "target"}:
            continue
        object_ref = _angle_sum_role_object_ref(
            call,
            role=role,
            scope_id=scope_id,
            semantic_index=semantic_index,
        )
        if object_ref is not None:
            result.append(object_ref)
    return unique_ordered(result)


def _hidden_auto_arg_object_requirements(
    call: FunctionalCall,
    *,
    scope_id: str,
    capability: FunctionalCapability,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[tuple[str, bool], ...]:
    result: list[tuple[str, bool]] = []
    for auto in capability.auto_args:
        if not auto.selector.startswith("angle_sum:"):
            continue
        role = auto.selector.split(":", 1)[1]
        if role in {"condition", "target"}:
            continue
        object_ref = _angle_sum_role_object_ref(
            call,
            role=role,
            scope_id=scope_id,
            semantic_index=semantic_index,
        )
        if object_ref is None:
            continue
        result.append(
            (
                object_ref,
                selector_semantics(auto.selector).requires_closed_state,
            )
        )
    return unique_ordered(result)


def _select_planned_state_producer(
    object_ref: str,
    *,
    consumer_call: FunctionalCall,
    consumer_scope_id: str,
    producers_by_object: Mapping[
        str,
        Sequence[tuple[str, str, str]],
    ],
    calls_by_id: Mapping[str, FunctionalCall],
    dependency_graph: Mapping[str, tuple[str, ...]],
    order_by_id: Mapping[str, int],
    handle_registry: CanonicalHandleRegistry,
    requires_closed_state: bool = False,
    allow_future: bool = True,
) -> str | None:
    """Choose a unique planned producer without relying on wire order."""

    candidates = tuple(
        item
        for item in producers_by_object.get(object_ref, ())
        if item[0] != consumer_call.call_id
        and not _dependency_reaches(
            item[0],
            consumer_call.call_id,
            dependency_graph=dependency_graph,
        )
    )
    if not allow_future:
        candidates = tuple(
            item
            for item in candidates
            if order_by_id.get(item[0], -1)
            < order_by_id.get(consumer_call.call_id, -1)
        )
    if requires_closed_state:
        closed = tuple(
            item
            for item in candidates
            if calls_by_id[item[0]].return_expectations.get(item[1])
            in {"closed_state", "closed_value"}
        )
        if closed:
            candidates = closed
    same_scope = tuple(
        item for item in candidates if item[2] == consumer_scope_id
    )
    if len(same_scope) == 1:
        return same_scope[0][0]
    if same_scope:
        candidates = same_scope
    visible = tuple(
        item
        for item in candidates
        if visible_from_valid_scope(
            item[2],
            scope_id=consumer_scope_id,
            registry=handle_registry,
        )
    )
    if len(visible) == 1:
        return visible[0][0]
    if visible:
        candidates = visible
    prior = tuple(
        item
        for item in candidates
        if order_by_id.get(item[0], -1)
        < order_by_id.get(consumer_call.call_id, -1)
    )
    if len(prior) == 1:
        return prior[0][0]
    if prior:
        return max(prior, key=lambda item: order_by_id[item[0]])[0]
    return candidates[0][0] if len(candidates) == 1 else None


def _dependency_reaches(
    start_call_id: str,
    target_call_id: str,
    *,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> bool:
    pending = list(dependency_graph.get(start_call_id, ()))
    visited: set[str] = set()
    while pending:
        call_id = pending.pop()
        if call_id == target_call_id:
            return True
        if call_id in visited:
            continue
        visited.add(call_id)
        pending.extend(dependency_graph.get(call_id, ()))
    return False


def _angle_sum_role_object_ref(
    call: FunctionalCall,
    *,
    role: str,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> str | None:
    conditions: list[FunctionalSemanticView] = []
    for refs in call.args.values():
        for ref in refs:
            if not isinstance(ref, SemanticRef):
                continue
            condition, _matches = semantic_index.resolve(
                ref,
                scope_id=scope_id,
                accepted_types=("Condition",),
            )
            if (
                condition is not None
                and semantic_index.handle_registry.fact_types.get(
                    condition.handle
                )
                == "angle_sum"
            ):
                conditions.append(condition)
    if len(conditions) != 1:
        return None
    payload = semantic_index.handle_registry.fact_payloads.get(
        conditions[0].handle,
        {},
    )
    terms = payload.get("angle_terms")
    if (
        not isinstance(terms, list | tuple)
        or len(terms) != 2
        or any(
            not isinstance(term, str) or len(term) != 3
            for term in terms
        )
    ):
        return None
    point_name = _angle_sum_role_point_name(terms, role)
    if point_name is None:
        return None
    matches = tuple(
        handle
        for handle in semantic_index.handle_registry.entity_handles
        if handle.startswith("point:")
        and handle.rsplit(":", 1)[-1] == point_name
        and visible_from_valid_scope(
            semantic_index.handle_registry.handle_valid_scopes.get(
                handle,
                scope_id,
            ),
            scope_id=scope_id,
            registry=semantic_index.handle_registry,
        )
    )
    return matches[0] if len(matches) == 1 else None


def _angle_sum_role_point_name(
    terms: Sequence[str],
    role: str,
) -> str | None:
    """Map one structured angle-sum role to its declared point name."""

    left, right = terms
    return {
        "x_axis_point": left[1],
        "y_axis_point": left[0],
        "reference_x_axis_point": right[0],
        "origin": right[2],
    }.get(role)


def _context_has_materialized_object_state(
    semantic_index: FunctionalSemanticIndex,
    *,
    object_ref: str,
    scope_id: str,
    requires_closed_state: bool = False,
) -> bool:
    return any(
        view.object_ref == object_ref
        and view.state_slot_id is not None
        and (not requires_closed_state or not view.free_symbol_refs)
        and visible_from_valid_scope(
            view.valid_scope,
            scope_id=scope_id,
            registry=semantic_index.handle_registry,
        )
        for view in semantic_index.views
    )


def _planned_target_objects(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    handle_registry: CanonicalHandleRegistry,
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
    referenced_returns = {
        (ref.from_call, ref.return_name)
        for call in plan.calls
        for refs in call.args.values()
        for ref in refs
        if isinstance(ref, CallResultRef)
    }
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
        ]
        if len(point_returns) != 1:
            continue
        point_return = point_returns[0]
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
        bound_object_ref = _bound_point_return_object_ref(
            call.return_bindings.get(point_return.name),
            scope_id=scopes[call.call_id],
            handle_registry=handle_registry,
        )
        if bound_object_ref is not None:
            object_ref = bound_object_ref
            allocate_current_target = False
        elif (
            point_return.return_binding == "call_local_allowed"
            and (call.call_id, point_return.name) in referenced_returns
        ):
            object_ref = derived_role_object_ref(
                call_id=call.call_id,
                semantic_role=point_return.semantic_role,
                scope_id=scopes[call.call_id],
                runtime_type="Point",
            )
            allocate_current_target = True
        elif source_target_args:
            object_ref = derived_role_object_ref(
                call_id=call.call_id,
                semantic_role=point_return.semantic_role,
                scope_id=scopes[call.call_id],
                runtime_type="Point",
            )
            allocate_current_target = True
        else:
            continue
        if allocate_current_target:
            result[(call.call_id, target_arg)] = object_ref
        for source_id, source_target in source_target_args:
            result[(source_id, source_target)] = object_ref
    return result


def _bound_point_return_object_ref(
    binding: SemanticRef | None,
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """Resolve one explicit Point destination to its canonical MathObject."""

    if binding is None:
        return None
    if binding.kind == "answer":
        return handle_registry.answer_target_handles.get(
            f"answer:{binding.ref}"
        )
    if binding.kind != "point":
        return None
    if binding.ref in handle_registry.entity_handles:
        return binding.ref
    candidates = tuple(
        handle
        for handle in handle_registry.entity_handles
        if handle.startswith("point:")
        and handle.rsplit(":", 1)[-1] == binding.ref
        and visible_from_valid_scope(
            handle_registry.handle_valid_scopes.get(handle, scope_id),
            scope_id=scope_id,
            registry=handle_registry,
        )
    )
    return candidates[0] if len(candidates) == 1 else None


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


def _required_identity_auto_arg_issues(
    capability: Any,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
    has_downstream_consumer: bool,
) -> tuple[FunctionalPlanIssue, ...]:
    """Reject unresolved compiler targets before direct compilation."""

    return tuple(
        _issue(
            "functional_reconciliation",
            "functional.auto_arg_identity_unresolved",
            (
                f"capability {capability.capability_id} requires a uniquely "
                f"resolved target object for hidden argument {auto.name}"
            ),
            call_id=call_id,
            scope_id=scope_id,
            details={
                "arg": auto.name,
                "selector": auto.selector,
                "expected_identity": "Point MathObject",
            },
        )
        for auto in capability.auto_args
        if auto.required
        and selector_semantics(auto.selector).owns_identity_binding
        and not any(
            returned.runtime_type == "Point"
            and returned.identity_policy == "target_object"
            for returned in capability.returns
        )
        and not has_downstream_consumer
        and not resolved_args.get(auto.name)
    )


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
            functional_answer_output_type_compatible(goal.value_type, output_type)
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


def _unbound_goal_producer_call_ids(
    plan: FunctionalPlan,
    reconciled: Sequence[FunctionalCallReconciliation],
    *,
    goal: QuestionGoal,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """Locate terminal calls that could own one missing required answer."""
    consumers = _call_result_consumer_calls(plan)
    target_object = handle_registry.answer_target_handles.get(
        f"answer:{goal.id}"
    )
    result: list[str] = []
    for resolved in reconciled:
        for allocation in resolved.returns:
            if (
                allocation.identity_policy == "derived_role"
                or _has_downstream_object_write(
                    allocation,
                    consumers=consumers,
                    reconciled=reconciled,
                )
                or not functional_answer_output_type_compatible(
                    goal.value_type,
                    allocation.runtime_type,
                )
                or not visible_from_valid_scope(
                    allocation.valid_scope,
                    scope_id=goal.question_id,
                    registry=handle_registry,
                )
            ):
                continue
            if (
                target_object is not None
                and allocation.object_ref != target_object
            ):
                continue
            result.append(allocation.call_id)
    return unique_ordered(result)


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
    return infer_future_return_object_hints(
        plan,
        catalog=catalog,
        semantic_index=semantic_index,
    )


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
    closure = (
        capability.source.symbolic_closure
        if isinstance(capability.source, FunctionSpec)
        else None
    )
    closure_target_refs = (
        {
            value.object_ref
            for value in resolved_args.get(closure.target_arg, ())
            if value.object_ref is not None
        }
        if closure is not None
        else set()
    )
    unresolved_symbol_refs = {
        symbol_ref
        for values in resolved_args.values()
        for value in values
        if value.runtime_type != "ParameterValue"
        for symbol_ref in value.free_symbol_refs
        if symbol_ref not in closure_target_refs
    }
    preserved_symbol_refs = {
        value.object_ref
        for arg in capability.args
        if arg.semantic_role == "free_parameters"
        for value in resolved_args.get(arg.name, ())
        if value.object_ref is not None
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
                provides_semantic_roles=view.provides_semantic_roles,
                lineage=view.lineage,
                math_object_id=view.math_object_id,
                logical_state_key=view.logical_state_key,
                typed_slot_id=view.typed_slot_id,
                state_version_id=view.state_version_id,
                source_version_ids=view.source_version_ids,
            )
            for view in semantic_index.compatible_views(
                scope_id=scope_id,
                accepted_types=accepted_types,
                accepted_condition_kinds=arg.accepted_condition_kinds,
            )
            if view.handle not in existing_handles
        )
        if arg.semantic_role == "parameter_value" and preserved_symbol_refs:
            suppressed = tuple(
                value
                for value in candidates
                if value.object_ref in preserved_symbol_refs
            )
            candidates = [
                value
                for value in candidates
                if value.object_ref not in preserved_symbol_refs
            ]
            for value in suppressed:
                repairs.append(
                    FunctionalDeterministicRepair(
                        call_id,
                        "suppress_value_for_preserved_symbol",
                        f"{arg.name}={value.object_ref or value.handle}",
                        f"{arg.name}=omitted",
                    )
                )
        if arg.semantic_role == "parameter_value":
            candidates = [
                value
                for value in candidates
                if value.object_ref in unresolved_symbol_refs
            ]
        elif related_objects:
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


def _has_context_auto_resolver(selector: str) -> bool:
    return (
        selector.startswith("function:")
        or selector.startswith("angle_sum:")
        or midpoint_endpoint_position(selector) is not None
    )


def _reconcile_supplied_context_auto_args(
    capability: Any,
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolved_auto_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolver_repairs: tuple[FunctionalDeterministicRepair, ...],
    resolver_issues: tuple[FunctionalPlanIssue, ...],
    supplied_names: set[str],
    call_id: str,
    scope_id: str,
) -> tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
]:
    """Accept a hidden override only when it equals the resolver's choice."""

    additions = {
        name: values
        for name, values in resolved_auto_args.items()
        if name not in supplied_names
    }
    repairs = [
        repair
        for repair in resolver_repairs
        if not any(
            repair.from_value.startswith(f"{name}=")
            for name in supplied_names
        )
    ]
    issues = [
        issue
        for issue in resolver_issues
        if not (
            issue.details is not None
            and issue.details.get("arg") in supplied_names
            and issue.details.get("arg") in resolved_auto_args
        )
    ]
    auto_by_name = {item.name: item for item in capability.auto_args}
    for name in sorted(supplied_names):
        supplied = resolved_args.get(name, ())
        expected = resolved_auto_args.get(name, ())
        if len(supplied) != 1 or len(expected) != 1:
            continue
        if _same_resolved_auto_value(supplied[0], expected[0]):
            repairs.append(
                FunctionalDeterministicRepair(
                    call_id,
                    "absorb_equivalent_auto_arg_override",
                    f"{name}={supplied[0].handle}",
                    f"{name}=auto",
                )
            )
            continue
        auto = auto_by_name[name]
        issues.append(
            _issue(
                "functional_reconciliation",
                "functional.auto_arg_override_mismatch",
                (
                    f"hidden argument {capability.capability_id}.{name} "
                    "does not match its deterministic Context resolution"
                ),
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg": name,
                    "selector": auto.selector,
                    "supplied_handle": supplied[0].handle,
                    "resolved_handle": expected[0].handle,
                    "supplied_state_slot_id": supplied[0].state_slot_id,
                    "resolved_state_slot_id": expected[0].state_slot_id,
                },
            )
        )
    return additions, tuple(repairs), tuple(issues)


def _same_resolved_auto_value(
    supplied: ResolvedFunctionalValue,
    expected: ResolvedFunctionalValue,
) -> bool:
    if supplied.state_slot_id is not None or expected.state_slot_id is not None:
        return (
            supplied.state_slot_id is not None
            and supplied.state_slot_id == expected.state_slot_id
        )
    if supplied.source_call_id is not None or expected.source_call_id is not None:
        return (
            supplied.source_call_id == expected.source_call_id
            and supplied.return_name == expected.return_name
        )
    return (
        supplied.handle == expected.handle
        and supplied.object_ref == expected.object_ref
        and runtime_type_compatible(
            supplied.runtime_type,
            expected.runtime_type,
        )
    )


def _resolve_context_auto_args(
    capability: Any,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
    planned_return_expectations: Mapping[tuple[str, str], str],
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
        if auto.selector.startswith("angle_sum:"):
            value, repair, issue = _resolve_angle_sum_auto_arg(
                auto,
                resolved_args=resolved_args,
                produced=produced,
                semantic_index=semantic_index,
                handle_registry=handle_registry,
                call_id=call_id,
                scope_id=scope_id,
                planned_return_expectations=planned_return_expectations,
            )
            if value is not None:
                additions[auto.name] = (value,)
            if repair is not None:
                repairs.append(repair)
            if issue is not None:
                issues.append(issue)
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
                    provides_semantic_roles=view.provides_semantic_roles,
                    lineage=view.lineage,
                    math_object_id=view.math_object_id,
                    logical_state_key=view.logical_state_key,
                    typed_slot_id=view.typed_slot_id,
                    state_version_id=view.state_version_id,
                    source_version_ids=view.source_version_ids,
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
            if selector_semantics(auto.selector).requires_materialized_state:
                additions[auto.name] = (selected,)
            else:
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


def _resolve_angle_sum_auto_arg(
    auto: Any,
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
    call_id: str,
    scope_id: str,
    planned_return_expectations: Mapping[tuple[str, str], str] | None = None,
) -> tuple[
    ResolvedFunctionalValue | None,
    FunctionalDeterministicRepair | None,
    FunctionalPlanIssue | None,
]:
    """Resolve an angle-sum selector to the latest exact Point state."""

    role = auto.selector.split(":", 1)[1]
    if role in {"condition", "target"}:
        return None, None, None
    conditions = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if value.runtime_type == "Condition"
        and handle_registry.fact_types.get(value.handle) == "angle_sum"
    )
    if len(conditions) != 1:
        return (
            None,
            None,
            _issue(
                "functional_reconciliation",
                (
                    "functional.auto_arg_unresolved"
                    if not conditions
                    else "functional.auto_arg_ambiguous"
                ),
                f"angle-sum role {role} requires one structured angle condition",
                call_id=call_id,
                scope_id=scope_id,
                details={"arg": auto.name, "selector": auto.selector},
            ),
        )
    condition = conditions[0]
    payload = handle_registry.fact_payloads.get(condition.handle, {})
    terms = payload.get("angle_terms")
    if (
        not isinstance(terms, list | tuple)
        or len(terms) != 2
        or any(not isinstance(term, str) or len(term) != 3 for term in terms)
    ):
        return (
            None,
            None,
            _issue(
                "functional_reconciliation",
                "functional.auto_arg_unresolved",
                "angle-sum condition has no structured three-point angle terms",
                call_id=call_id,
                scope_id=scope_id,
                details={"arg": auto.name, "selector": auto.selector},
            ),
        )
    point_name = _angle_sum_role_point_name(terms, role)
    if point_name is None:
        return None, None, None
    object_refs = tuple(
        handle
        for handle in handle_registry.entity_handles
        if handle.startswith("point:") and handle.rsplit(":", 1)[-1] == point_name
    )
    visible_object_refs = tuple(
        handle
        for handle in object_refs
        if visible_from_valid_scope(
            handle_registry.handle_valid_scopes.get(handle, scope_id),
            scope_id=scope_id,
            registry=handle_registry,
        )
    )
    if len(visible_object_refs) != 1:
        return (
            None,
            None,
            _issue(
                "functional_reconciliation",
                (
                    "functional.auto_arg_unresolved"
                    if not visible_object_refs
                    else "functional.auto_arg_ambiguous"
                ),
                f"angle-sum role {role} does not identify one visible Point object",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg": auto.name,
                    "selector": auto.selector,
                    "object_candidates": list(visible_object_refs),
                },
            ),
        )
    object_ref = visible_object_refs[0]
    value = _latest_point_state_for_object(
        object_ref,
        scope_id=scope_id,
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
        allow_unique_planned_producer=True,
    )
    if value is None:
        immutable_views = tuple(
            view
            for view in semantic_index.views
            if view.object_ref == object_ref
            and view.runtime_type == "Point"
            and view.state_slot_id is None
            and _problem_point_has_coordinates(
                object_ref,
                handle_registry=handle_registry,
            )
            and visible_from_valid_scope(
                view.valid_scope,
                scope_id=scope_id,
                registry=handle_registry,
            )
        )
        if len(immutable_views) == 1:
            view = immutable_views[0]
            value = ResolvedFunctionalValue(
                handle=view.handle,
                runtime_type=view.runtime_type,
                valid_scope=view.valid_scope,
                object_ref=view.object_ref,
                dependency_object_refs=view.dependency_object_refs,
                free_symbol_refs=view.free_symbol_refs,
                source_state_slot_ids=view.source_state_slot_ids,
                provides_semantic_roles=view.provides_semantic_roles,
                lineage=view.lineage,
                math_object_id=view.math_object_id,
                logical_state_key=view.logical_state_key,
                typed_slot_id=view.typed_slot_id,
                state_version_id=view.state_version_id,
                source_version_ids=view.source_version_ids,
            )
    if value is None:
        return (
            None,
            None,
            _issue(
                "functional_reconciliation",
                "functional.arg_state_unavailable",
                f"angle-sum role {role} requires a materialized Point state",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg": auto.name,
                    "selector": auto.selector,
                    "object_ref": object_ref,
                },
            ),
        )
    if (
        selector_semantics(auto.selector).requires_closed_state
        and value.free_symbol_refs
    ):
        expectation = (
            planned_return_expectations.get(
                (value.source_call_id, value.return_name)
            )
            if planned_return_expectations is not None
            and value.source_call_id is not None
            and value.return_name is not None
            else None
        )
        if expectation in {"closed_state", "closed_value"}:
            return (
                value,
                FunctionalDeterministicRepair(
                    call_id,
                    "defer_closed_state_check_to_runtime",
                    f"{auto.name}={value.handle}",
                    (
                        f"{auto.name}={value.handle}; "
                        f"producer_expectation={expectation}"
                    ),
                ),
                None,
            )
        repair_call_ids = unique_ordered(
            (
                *(
                    (value.source_call_id,)
                    if value.source_call_id is not None
                    else ()
                ),
                call_id,
            )
        )
        return (
            None,
            None,
            _issue(
                "functional_reconciliation",
                "functional.arg_state_open",
                f"angle-sum role {role} requires a closed Point state",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg": auto.name,
                    "selector": auto.selector,
                    "object_ref": object_ref,
                    "free_symbol_refs": list(value.free_symbol_refs),
                    "producer_call_id": value.source_call_id,
                    "producer_return_name": value.return_name,
                    "expected_form": "closed_state",
                    "actual_form": "open_state",
                    "repair_call_ids": list(repair_call_ids),
                },
            ),
        )
    return (
        value,
        FunctionalDeterministicRepair(
            call_id,
            "resolve_angle_sum_role_state",
            f"{auto.name}=omitted",
            f"{auto.name}={value.handle}",
        ),
        None,
    )


def _problem_point_has_coordinates(
    object_ref: str,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    payload = handle_registry.entity_payloads.get(object_ref, {})
    if payload.get("definition") == "coordinate_origin":
        return True
    coordinate = payload.get("coordinate")
    return (
        isinstance(coordinate, list | tuple)
        and len(coordinate) == 2
        and all(item is not None for item in coordinate)
    )


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
                provides_semantic_roles=(
                    selected_view.provides_semantic_roles
                ),
                lineage=selected_view.lineage,
                math_object_id=selected_view.math_object_id,
                logical_state_key=selected_view.logical_state_key,
                typed_slot_id=selected_view.typed_slot_id,
                state_version_id=selected_view.state_version_id,
                source_version_ids=selected_view.source_version_ids,
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
) -> tuple[
    tuple[FunctionalPlanIssue, ...],
    tuple[FunctionalDeterministicRepair, ...],
]:
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
    mechanical_parameter_args = {
        item.name
        for item in capability.auto_args
        if item.required
        and item.selector
        in {
            "parameter_symbol",
            "parameter_symbol_from_reads",
            "parameter_symbol_from_reads_or_expression",
            "known_parameter_symbol_from_reads",
        }
    }
    issues: list[FunctionalPlanIssue] = []
    repairs: list[FunctionalDeterministicRepair] = []
    for arg_name in unique_ordered(
        (
            *identity_args,
            *mechanical_parameter_args,
            *semantic_auto_by_name,
        )
    ):
        if arg_name in resolved_args:
            continue
        auto = auto_by_name.get(arg_name)
        semantic_auto = semantic_auto_by_name.get(arg_name)
        if (
            semantic_auto is None
            and (auto is None or "parameter" not in auto.selector)
        ):
            continue
        if (
            semantic_auto is not None
            and not semantic_auto.required
            and arg_name not in identity_args
        ):
            continue
        hinted_symbols = tuple(
            dependency
            for dependency in unique_ordered(identity_hints)
            if dependency.startswith("symbol:")
        )
        parameter_value_symbols = tuple(
            object_ref
            for object_ref in unique_ordered(
                value.object_ref
                for values in resolved_args.values()
                for value in values
                if value.runtime_type == "ParameterValue"
                and value.object_ref is not None
            )
            if object_ref.startswith("symbol:")
        )
        role_symbols = tuple(
            object_ref
            for object_ref in unique_ordered(
                object_ref
                for values in resolved_args.values()
                for value in values
                for object_ref in (
                    *(
                        ref
                        for _role, object_refs in value.object_roles
                        for ref in object_refs
                    ),
                    *(
                        ref
                        for binding in value.lineage.object_roles
                        for ref in binding.object_refs
                    ),
                )
            )
            if object_ref.startswith("symbol:")
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
                        object_ref
                        for _role, object_refs in value.object_roles
                        for object_ref in object_refs
                    ),
                    *(
                        object_ref
                        for binding in value.lineage.object_roles
                        for object_ref in binding.object_refs
                    ),
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
        # producer's unresolved-symbol estimate. An explicitly selected
        # ParameterValue is likewise authoritative for a mechanical
        # substitution arg: its object_ref names the Symbol being replaced,
        # while its own free symbols describe dependencies of the value.
        candidates = (
            hinted_symbols
            if hinted_symbols
            else (
                parameter_value_symbols
                if len(parameter_value_symbols) == 1
                else (
                    role_symbols
                    if len(role_symbols) == 1
                    else input_symbols
                )
            )
        )
        if (
            not hinted_symbols
            and len(parameter_value_symbols) == 1
            and arg_name in mechanical_parameter_args
        ):
            repairs.append(
                FunctionalDeterministicRepair(
                    call_id,
                    "infer_parameter_from_value_identity",
                    f"{arg_name}=omitted",
                    f"{arg_name}={parameter_value_symbols[0]}",
                )
            )
        inferred = (
            infer_unique_target_symbol_ref(resolved_args, candidates)
            if len(candidates) > 1
            else None
        )
        if inferred is not None:
            candidates = (inferred,)
            repairs.append(
                FunctionalDeterministicRepair(
                    call_id,
                    "infer_target_symbol_from_state_dependencies",
                    "available_symbols=ambiguous",
                    f"{arg_name}={inferred}",
                )
            )
        if len(candidates) != 1:
            resolver_is_required = bool(
                semantic_auto.required
                if semantic_auto is not None
                else (auto.required if auto is not None else False)
            )
            if not resolver_is_required:
                continue
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
    return tuple(issues), tuple(repairs)


def _functional_ref_role(ref: FunctionalRef) -> str:
    if isinstance(ref, CallResultRef):
        return ref.return_name
    return ref.ref.rsplit(".", 1)[-1]


def _resolved_value_semantic_roles(
    value: ResolvedFunctionalValue,
    ref: FunctionalRef,
) -> tuple[str, ...]:
    """Prefer stable StateSlot lineage over the current wire return label."""
    return unique_ordered(
        (
            *value.lineage.semantic_roles,
            *((value.return_name,) if value.return_name else ()),
            _functional_ref_role(ref),
        )
    )


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
            *((value.object_ref,) if value.object_ref else ()),
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
            *(
                (
                    legacy_state_slot_aliases(
                        value.state_version_id.slot_id
                    )[0],
                )
                if value.state_version_id is not None
                else (
                    ()
                    if (
                        value.source_call_id is not None
                        and value.return_name is not None
                    )
                    else (
                        (value.state_slot_id,)
                        if value.state_slot_id
                        else ()
                    )
                )
            ),
        )
    )


def _argument_source_versions(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[StateVersionId, ...]:
    return unique_ordered(
        version_id
        for values in args.values()
        for value in values
        for version_id in (
            *((value.state_version_id,) if value.state_version_id else ()),
            *value.source_version_ids,
        )
    )


def _argument_source_calls(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[str, ...]:
    return unique_ordered(
        source_call_id
        for values in args.values()
        for value in values
        for source_call_id in (
            *value.lineage.source_call_ids,
            *((value.source_call_id,) if value.source_call_id else ()),
        )
    )


def _argument_source_call_results(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[str, ...]:
    return unique_ordered(
        call_result_id
        for values in args.values()
        for value in values
        for call_result_id in (
            *value.lineage.source_call_result_ids,
            *(
                (
                    f"{value.source_call_id}.{value.return_name}",
                )
                if value.state_version_id is None
                and value.source_call_id is not None
                and value.return_name is not None
                else ()
            ),
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
    problem_entity_payloads = {
        item.get("handle"): item
        for item in problem_ir.get("entities", ())
        if isinstance(item, dict)
        and isinstance(item.get("handle"), str)
        and item.get("entity_type") == entity_kind
    }
    entity_payloads: dict[str, Mapping[str, Any]] = {}
    for item in planner_state_context.state.math_objects:
        if item.kind != entity_kind or item.canonical_handle is None:
            continue
        payload = dict(problem_entity_payloads.get(item.canonical_handle, {}))
        payload.setdefault("handle", item.canonical_handle)
        payload.setdefault("entity_type", item.kind)
        payload.setdefault("scope_id", item.scope_id)
        entity_payloads[item.canonical_handle] = payload
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
        and _semantic_view_materializes_return_type(
            item.runtime_type,
            return_spec.runtime_type,
        )
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
        object_ref
        for values in resolved_args.values()
        for value in values
        for _role, object_refs in value.object_roles
        for object_ref in object_refs
        if object_ref in visible_entities
    }
    structural_dependencies.update({
        handle
        for values in resolved_args.values()
        for value in values
        for handle in _structured_object_handles(
            fact_payloads.get(value.handle, {})
        )
        if handle in visible_entities
    })
    unresolved_dependencies = structural_dependencies - available_objects
    if len(unresolved_dependencies) == 1:
        return catalog_items.get(next(iter(unresolved_dependencies)))
    if len(unresolved_dependencies) > 1:
        # A structured relation may mention several not-yet-materialized
        # objects, such as the two remaining vertices of a square. Their
        # identities are real Context objects, but the relation alone does not
        # choose which one this call returns. Require an explicit binding
        # instead of letting a descriptive entity role win by score.
        return None

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


def _semantic_view_materializes_return_type(
    actual_runtime_type: str,
    expected_runtime_type: str,
) -> bool:
    """Distinguish an object's identity view from a computed state value.

    ``PointRef`` and similar reference views prove that a MathObject exists,
    but they do not prove that its coordinate/state has already been produced.
    Treating a reference as a materialized value hides the one remaining
    target in structured relationships and prevents deterministic binding.
    """

    actual = normalize_runtime_type(actual_runtime_type)
    expected_types = {
        normalize_runtime_type(item)
        for item in split_runtime_types(expected_runtime_type)
    }
    if actual.endswith("Ref") and actual not in expected_types:
        return False
    return runtime_type_compatible(expected_runtime_type, actual)


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
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    semantic_items: Sequence[SemanticReadCatalogItem],
    planner_state_context: PlannerStateContext,
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
    fact_payloads = {
        item.get("handle"): item
        for item in planner_state_context.state.problem_ir.get("facts", ())
        if isinstance(item, Mapping)
        and isinstance(item.get("handle"), str)
    }
    argument_objects = {
        value.object_ref
        for values in resolved_args.values()
        for value in values
        if value.object_ref is not None
    }
    structured_candidates = {
        handle
        for values in resolved_args.values()
        for value in values
        for handle in _structured_object_handles(
            fact_payloads.get(value.handle, {})
        )
        if handle not in argument_objects
    }
    relationship_refs = unique_ordered(
        item.ref
        for item in semantic_items
        if item.prompt_visible
        and item.kind == entity_kind
        and item.handle in structured_candidates
        and visible_from_valid_scope(
            item.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    )
    if relationship_refs:
        return relationship_refs
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
        and functional_answer_output_type_compatible(goal.value_type, return_type)
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
