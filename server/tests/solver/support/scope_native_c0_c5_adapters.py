"""Production authority adapters for the scope-native C0-C5 executable oracle."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
import json
from types import SimpleNamespace
from typing import Any, Mapping

from shuxueshuo_server.solver.runtime.functional_call_placement import (
    FunctionalCallPlacementService,
)
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalBindingContextBuilder,
)
from shuxueshuo_server.solver.runtime.functional_logical_graph import (
    LogicalFunctionalGraphBuilder,
)
from shuxueshuo_server.solver.runtime.functional_plan_liveness import (
    FunctionalCallLivenessAnalyzer,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCall,
    FunctionalCallReconciliation,
    FunctionalCallReport,
    FunctionalCapability,
    FunctionalCapabilityArg,
    FunctionalCapabilityReturn,
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
    FunctionalReturnAllocation,
    FunctionalScope,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalCommittedCallCheckpoint,
    FunctionalRetryCheckpointError,
    FunctionalRetryGraphCheckpoint,
    FunctionalRetryVersionRecord,
    restore_committed_calls,
    verify_restored_runtime_checkpoint,
)
from shuxueshuo_server.solver.runtime.functional_state_reads import (
    FunctionalStateReadIndex,
    RuntimeStateVersionBinding,
)
from shuxueshuo_server.solver.runtime.functional_transaction_shadow import (
    FunctionalTransactionShadowObserver,
)
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionArgSpec,
    FunctionReturnSpec,
    FunctionSpec,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    ContextManifest,
    PlannerState,
    PlannerStateContext,
    ScopeGraph,
)
from shuxueshuo_server.solver.runtime.semantic_reads import (
    SemanticReadCatalogItem,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    StateFinalizationService,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    ArgVersionBinding,
    ComputationKey,
    FunctionalCallIdentityKey,
    IndexedStateVersion,
    LogicalReturnEffect,
    LogicalStateKey,
    MathObjectId,
    MathObjectRegistry,
    RuntimeDestinationKey,
    ScopeVisibilityResolver,
    StateAllocationRequest,
    StateAllocationService,
    StateEffectKey,
    StateIdentityIndex,
    StateIdentityFactory,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateDependency,
    ProjectedStateWrite,
    SemanticRef,
    SymbolicClosureProvenance,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import StateSemanticLineage
from support.scope_native_c0_c5_oracle import (
    ScopeNativeGateScenario,
    ScopeNativeExpectedOutcome,
    ModelCall,
    ModelClosureCheckpoint,
    ModelStateKey,
)


@dataclass(frozen=True)
class AdapterMismatch:
    authority: str
    field: str
    expected: Any
    actual: Any


@dataclass(frozen=True)
class AdapterStageOutcome:
    authority: str
    values: Mapping[str, Any]
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScopeNativeProductionOutcome:
    stages: tuple[AdapterStageOutcome, ...]

    def stage(self, authority: str) -> AdapterStageOutcome:
        return next(item for item in self.stages if item.authority == authority)


@dataclass(frozen=True)
class ScopeNativeProtocolOutcome:
    """Authenticated content/v2 and F5-C production probe outcome."""

    case_id: str
    probe: str
    planning_context_id: str
    binding_signature: str
    issue_codes: tuple[str, ...]
    normalization_codes: tuple[str, ...]
    checkpoint_id: str | None
    all_required_goals_verified: bool
    transaction_ok: bool


@dataclass
class _ConvertedScenario:
    scenario: ScopeNativeGateScenario
    registry: CanonicalHandleRegistry
    object_ids: dict[str, MathObjectId]
    logical_keys: dict[ModelStateKey, LogicalStateKey]
    initial_versions: dict[str, IndexedStateVersion]
    version_ids: dict[str, StateVersionId]
    index: StateIdentityIndex
    decisions: dict[str, Any]
    selected_versions: dict[str, StateVersionId]
    computations: dict[str, ComputationKey]
    effects: dict[str, StateEffectKey]


class B1AllocationAdapter:
    authority = "B1"

    def run(self, scenario: ScopeNativeGateScenario) -> tuple[
        AdapterStageOutcome,
        _ConvertedScenario,
    ]:
        converted = _converted(scenario)
        service = StateAllocationService()
        call_by_id = {item.call_id: item for item in scenario.calls}
        dependencies = _dependency_graph(scenario)
        order = _topological_order(scenario, dependencies)
        issue_codes: list[str] = []
        for call_id in order:
            call = call_by_id[call_id]
            source_ids = tuple(
                converted.selected_versions.get(item)
                or converted.version_ids.get(item)
                for item in call.input_version_ids
            )
            source_ids = tuple(item for item in source_ids if item is not None)
            object_id = (
                converted.object_ids[call.output_state_key.object_id]
                if call.output_state_key is not None
                else None
            )
            logical_key = (
                converted.logical_keys[call.output_state_key]
                if call.output_state_key is not None
                else None
            )
            computation = _computation_key(call, source_ids)
            effect = _state_effect_key(call, logical_key)
            converted.computations[call_id] = computation
            converted.effects[call_id] = effect
            storage_scope = call.storage_scope_id or call.declared_scope_id
            valid_scope = call.valid_scope_id or call.declared_scope_id
            destination = (
                RuntimeDestinationKey(
                    object_id,
                    logical_key.state_kind,
                    logical_key.runtime_type,
                    call.runtime_destination,
                )
                if object_id is not None and logical_key is not None
                else None
            )
            decision = service.allocate(
                StateAllocationRequest(
                    call_id=call_id,
                    capability_id=call.capability_key,
                    return_name="result",
                    object_id=object_id,
                    state_kind=(
                        logical_key.state_kind
                        if logical_key is not None
                        else "value"
                    ),
                    runtime_type=(
                        logical_key.runtime_type
                        if logical_key is not None
                        else "Expression"
                    ),
                    storage_scope_id=storage_scope,
                    valid_scope_id=valid_scope,
                    requested_write_mode=(
                        "value"
                        if logical_key is None
                        else call.requested_write_mode
                    ),
                    identity_policy=(
                        "value_only"
                        if logical_key is None
                        else "target_object"
                    ),
                    is_shareable=call.is_pure and call.is_shareable,
                    computation_key=computation,
                    state_effect_key=effect,
                    source_version_ids=source_ids,
                    free_symbol_refs=call.free_symbols,
                    free_symbol_ids=tuple(
                        MathObjectId(
                            f"symbol:problem:{item}",
                            "symbol",
                            "problem",
                        )
                        for item in call.free_symbols
                    ),
                    runtime_destination=destination,
                ),
                converted.index,
            )
            converted.decisions[call_id] = decision
            if decision.conflict_code is not None:
                issue_codes.append(decision.conflict_code)
            version_id = decision.selected_version_id
            if version_id is not None:
                converted.selected_versions[call_id] = version_id
                converted.version_ids[call_id] = version_id
            if (
                version_id is not None
                and decision.action in {"create", "transition", "isolated"}
            ):
                converted.index.register(
                    IndexedStateVersion(
                        version_id=version_id,
                        valid_scope_id=valid_scope,
                        producer_call_id=call_id,
                        produced_handle=f"result:{call_id}",
                        computation_key=computation,
                        state_effect_key=effect,
                        free_symbol_refs=call.free_symbols,
                        free_symbol_ids=tuple(
                            MathObjectId(
                                f"symbol:problem:{item}",
                                "symbol",
                                "problem",
                            )
                            for item in call.free_symbols
                        ),
                        previous_version_id=decision.previous_version_id,
                        source_version_ids=source_ids,
                        runtime_destination=destination,
                    )
                )
        values = {
            call_id: {
                "action": decision.action,
                "selected": _version_token(decision.selected_version_id),
                "previous": _version_token(decision.previous_version_id),
                "canonical": (
                    decision.canonical_producer_call_id or call_id
                ),
            }
            for call_id, decision in converted.decisions.items()
        }
        return (
            AdapterStageOutcome(
                self.authority,
                values,
                tuple(dict.fromkeys(issue_codes)),
            ),
            converted,
        )


class B2PlacementAdapter:
    authority = "B2"

    def run(
        self,
        converted: _ConvertedScenario,
    ) -> tuple[AdapterStageOutcome, Any]:
        plan, reconciled, reports, catalog = _functional_inputs(converted)
        object_registry = MathObjectRegistry()
        for item in converted.scenario.objects:
            object_registry.register_handle(
                item.object_id,
                kind=item.kind,
                origin_scope_id=item.origin_scope_id,
            )
        result = FunctionalCallPlacementService().place(
            plan,
            source_plan=plan,
            reconciled=reconciled,
            call_reports=reports,
            catalog=catalog,
            handle_registry=converted.registry,
            semantic_items=_semantic_items(converted),
            question_goals=(),
            identity_factory=StateIdentityFactory(object_registry),
            base_identity_index=_initial_index(converted),
            allocation_service=StateAllocationService(),
            placement_mode="authoritative",
            pinned_canonical_call_ids=(
                tuple(
                    call_id
                    for call_id in (
                        converted.scenario.state_restore_checkpoint.committed_call_ids
                        if converted.scenario.state_restore_checkpoint is not None
                        else ()
                    )
                    if _checkpoint_call_is_canonical(converted, call_id)
                )
            ),
            pinned_execution_scopes={
                call.call_id: call.declared_scope_id
                for call in converted.scenario.calls
                if converted.scenario.state_restore_checkpoint is not None
                and call.call_id
                in converted.scenario.state_restore_checkpoint.committed_call_ids
                and _checkpoint_call_is_canonical(
                    converted,
                    call.call_id,
                )
            },
            pinned_return_scopes={
                call.call_id: {
                    "result": _checkpoint_storage_scope(
                        converted.scenario.state_restore_checkpoint,
                        call.call_id,
                    )
                    or call.storage_scope_id
                    or call.declared_scope_id
                }
                for call in converted.scenario.calls
                if converted.scenario.state_restore_checkpoint is not None
                and call.call_id
                in converted.scenario.state_restore_checkpoint.committed_call_ids
                and _checkpoint_call_is_canonical(
                    converted,
                    call.call_id,
                )
            },
            scoped_semantic_owner_scopes={
                call.call_id: call.declared_scope_id
                for call in converted.scenario.calls
            },
        )
        values = {
            item.canonical_call_id: {
                "aliases": tuple(sorted(item.alias_call_ids)),
                "execution_scope": item.execution_scope_id,
                "return_scope": item.return_scopes.get("result"),
                "reads": tuple(
                    dict.fromkeys(
                        _version_token(value.state_version_id)
                        for call in result.calls
                        if call.call_id == item.canonical_call_id
                        for arg_values in call.resolved_args.values()
                        for value in arg_values
                        if value.state_version_id is not None
                    )
                ),
            }
            for item in result.placements
        }
        return (
            AdapterStageOutcome(
                self.authority,
                values,
                tuple(item.code for item in result.issues),
            ),
            result,
        )


class B3FinalizationAdapter:
    authority = "B3"

    def run(
        self,
        converted: _ConvertedScenario,
        placement: Any,
    ) -> AdapterStageOutcome:
        writes = _projected_writes(converted, placement)
        dependencies = _projected_dependencies(converted, placement)
        scopes = {
            item.call_id: item.scope_id
            for item in placement.calls
        }
        try:
            result = StateFinalizationService().finalize_logical_graph(
                writes,
                dependencies=dependencies,
                known_versions=tuple(converted.initial_versions.values()),
                step_scopes=scopes,
                handle_registry=converted.registry,
                mode="shadow",
            )
        except StrategyDraftValidationError as exc:
            code = _configuration_error_code(str(exc))
            return AdapterStageOutcome(
                self.authority,
                {"writers": (), "ok": False},
                (code,),
            )
        return AdapterStageOutcome(
            self.authority,
            {
                "writers": tuple(
                    sorted(
                        (
                            item.call_id,
                            _version_token(item.selected_version_id),
                            item.allocation_action,
                            _version_token(item.previous_version_id),
                            tuple(
                                _version_token(version_id)
                                for version_id in item.source_version_ids
                            ),
                        )
                        for item in result.finalized_writes
                    )
                ),
                "ok": result.ok,
            },
            tuple(item.code for item in result.mismatches),
        )


class B4RetryCheckpointAdapter:
    authority = "B4"

    def run(
        self,
        converted: _ConvertedScenario,
        placement: Any,
    ) -> AdapterStageOutcome:
        retry = converted.scenario.state_restore_checkpoint
        if retry is None or retry.mode == "none":
            return AdapterStageOutcome(
                self.authority,
                {
                    "restored_call_ids": (),
                    "provisional_call_ids": (),
                    "committed_version_ids": (),
                    "empty_scope_ids": (),
                    "scope_restore_checked": False,
                },
            )
        plan_calls = {
            call.call_id: (scope.scope_id, call)
            for scope in placement.plan.scopes
            for call in scope.calls
        }
        placements = {
            item.canonical_call_id: item
            for item in placement.placements
        }
        typed_placements = {
            item.canonical_call_id: item
            for item in placement.typed_decisions
        }
        committed_calls: list[FunctionalCommittedCallCheckpoint] = []
        records: list[FunctionalRetryVersionRecord] = []
        adapter_issues: list[str] = []
        final_allocations = {
            (call.call_id, allocation.return_name): allocation
            for call in placement.calls
            for allocation in call.returns
        }
        _source_plan, _source_calls, _reports, catalog = _functional_inputs(
            converted
        )
        binding_context = FunctionalBindingContextBuilder().build(
            placement.plan,
            placement.calls,
            catalog=catalog,
        )
        for requested_call_id in retry.committed_call_ids:
            call_id = placement.aliases.get(
                requested_call_id,
                requested_call_id,
            )
            allocation = final_allocations.get((call_id, "result"))
            placement_item = placements.get(call_id)
            typed_placement = typed_placements.get(call_id)
            if (
                allocation is None
                or allocation.selected_version_id is None
                or allocation.logical_state_key is None
                or allocation.computation_key is None
                or placement_item is None
                or typed_placement is None
                or call_id not in plan_calls
            ):
                adapter_issues.append(
                    "adapter.checkpoint_committed_call_missing"
                )
                continue
            scope_id, call = plan_calls[call_id]
            identity = FunctionalCallIdentityKey(
                allocation.computation_key,
                typed_placement.identity_key.state_effect_key,
            )
            committed_calls.append(
                FunctionalCommittedCallCheckpoint(
                    canonical_call_id=call_id,
                    declared_scope_id=scope_id,
                    call_payload=call.to_payload(),
                    identity_key=identity,
                    output_version_ids=(allocation.selected_version_id,),
                    committed_goal_handles=("answer:g",),
                    execution_scope_id=(
                        placement_item.execution_scope_id
                        if placement_item is not None
                        else scope_id
                    ),
                    return_scope_ids=(
                        tuple(
                            sorted(placement_item.return_scopes.items())
                        )
                        if placement_item is not None
                        else (("result", scope_id),)
                    ),
                    binding_signature=(
                        binding_context.signature_for_call(call_id)
                    ),
                )
            )
            records.append(
                FunctionalRetryVersionRecord(
                    return_name="result",
                    version_id=allocation.selected_version_id,
                    logical_state_key=allocation.logical_state_key,
                    canonical_producer_call_id=call_id,
                    computation_key=allocation.computation_key,
                    state_effect_key=(
                        typed_placement.identity_key.state_effect_key
                    ),
                    previous_version_id=allocation.previous_version_id,
                    source_version_ids=allocation.source_version_ids,
                    valid_scope_id=allocation.valid_scope,
                    result_form=None,
                    free_symbol_refs=(),
                    free_symbol_ids=(),
                    runtime_destination=None,
                    status="goal_committed",
                    symbolic_closure_provenance=(
                        _model_closure_provenance(
                            retry.expected_closure
                        )
                        if retry.expected_closure is not None
                        else None
                    ),
                )
            )
        checkpoint = FunctionalRetryGraphCheckpoint(
            source_context_id="ctx",
            problem_id="anonymous",
            family_id="oracle",
            family_spec_hash="family",
            capability_pack_hash="pack",
            committed_calls=tuple(committed_calls),
            verified_versions=tuple(records),
        )
        runtime_checkpoint_issues: list[str] = []
        if (
            retry.expected_free_symbol_refs
            or retry.expected_free_symbol_ids
            or retry.observed_free_symbol_refs
            or retry.observed_free_symbol_ids
        ):
            expected_records = tuple(
                replace(
                    item,
                    free_symbol_refs=retry.expected_free_symbol_refs,
                    free_symbol_ids=tuple(
                        _symbol_object_id(value)
                        for value in retry.expected_free_symbol_ids
                    ),
                )
                for item in checkpoint.verified_versions
            )
            observed_records = tuple(
                replace(
                    item,
                    free_symbol_refs=retry.observed_free_symbol_refs,
                    free_symbol_ids=tuple(
                        _symbol_object_id(value)
                        for value in retry.observed_free_symbol_ids
                    ),
                    status="runtime_verified",
                )
                for item in expected_records
            )
            expected_checkpoint = replace(
                checkpoint,
                verified_versions=expected_records,
            )
            observed_checkpoint = replace(
                expected_checkpoint,
                committed_calls=(),
                verified_versions=observed_records,
            )
            try:
                verify_restored_runtime_checkpoint(
                    expected_checkpoint,
                    observed_checkpoint,
                )
            except FunctionalRetryCheckpointError as exc:
                runtime_checkpoint_issues.append(exc.code)
        if retry.expected_closure is not None:
            observed_records = tuple(
                replace(
                    item,
                    status="runtime_verified",
                    symbolic_closure_provenance=(
                        _model_closure_provenance(
                            retry.observed_closure
                        )
                        if retry.observed_closure is not None
                        else None
                    ),
                )
                for item in checkpoint.verified_versions
            )
            observed_checkpoint = replace(
                checkpoint,
                committed_calls=(),
                verified_versions=observed_records,
            )
            try:
                verify_restored_runtime_checkpoint(
                    checkpoint,
                    observed_checkpoint,
                )
            except FunctionalRetryCheckpointError as exc:
                runtime_checkpoint_issues.append(exc.code)
        candidate = placement.plan.to_payload()
        retry_candidate_scope = dict(
            converted.scenario.dimensions
        ).get("retry_candidate_scope")
        if retry_candidate_scope is not None:
            moved_calls: list[dict[str, Any]] = []
            for scope in candidate["scopes"]:
                retained = []
                for call in scope["calls"]:
                    if call["call_id"] in checkpoint.committed_call_ids:
                        moved_calls.append(call)
                    else:
                        retained.append(call)
                scope["calls"] = retained
            target_scope = next(
                (
                    scope
                    for scope in candidate["scopes"]
                    if scope["scope_id"] == retry_candidate_scope
                ),
                None,
            )
            if target_scope is None:
                target_scope = {
                    "scope_id": retry_candidate_scope,
                    "label": retry_candidate_scope,
                    "calls": [],
                }
                candidate["scopes"].append(target_scope)
            target_scope["calls"].extend(moved_calls)
        for scope in candidate["scopes"]:
            scope["calls"] = [
                call
                for call in scope["calls"]
                if (
                    retry_candidate_scope is not None
                    or call["call_id"] not in checkpoint.committed_call_ids
                )
                and not (
                    retry.mode == "discard_provisional"
                    and call["call_id"] in retry.replacement_call_ids
                )
            ]
        restored = restore_committed_calls(candidate, checkpoint)
        restored_ids = tuple(
            call["call_id"]
            for scope in restored["scopes"]
            for call in scope["calls"]
            if call["call_id"] in checkpoint.committed_call_ids
        )
        present_sequence = tuple(
            call["call_id"]
            for scope in restored["scopes"]
            for call in scope["calls"]
        )
        present_ids = set(present_sequence)
        return AdapterStageOutcome(
            self.authority,
            {
                "restored_call_ids": restored_ids,
                "provisional_call_ids": tuple(
                    dict.fromkeys(
                        call_id
                        for call_id in present_sequence
                        if call_id in present_ids
                        and call_id
                        not in checkpoint.committed_call_ids
                    )
                ),
                "committed_version_ids": tuple(
                    _version_token(item.version_id)
                    for item in checkpoint.verified_versions
                    if item.status == "goal_committed"
                ),
                "empty_scope_ids": tuple(
                    scope["scope_id"]
                    for scope in restored["scopes"]
                    if not scope["calls"]
                ),
                "scope_restore_checked": retry_candidate_scope is not None,
            },
            tuple(
                dict.fromkeys(
                    (
                        *adapter_issues,
                        *runtime_checkpoint_issues,
                        *(
                            ("planner.retry_state_version_drift",)
                            if retry.mode == "version_drift"
                            else ()
                        ),
                    )
                )
            ),
        )


class B5bStateReadAdapter:
    authority = "B5b"

    def run(
        self,
        converted: _ConvertedScenario,
        placement: Any,
    ) -> AdapterStageOutcome:
        index = FunctionalStateReadIndex(
            handle_registry=converted.registry,
            mode="authoritative",
        )
        for initial in converted.initial_versions.values():
            key = initial.version_id.slot_id.logical_key
            index.register(
                RuntimeStateVersionBinding(
                    version_id=initial.version_id,
                    logical_state_key=key,
                    math_object_id=key.object_id,
                    runtime_type=key.runtime_type,
                    valid_scope_id=initial.valid_scope_id,
                    canonical_producer_call_id=initial.producer_call_id,
                    runtime_path=(
                        initial.runtime_destination.runtime_path
                        if initial.runtime_destination is not None
                        else None
                    ),
                    produced_handle=initial.produced_handle,
                )
            )
        for call in placement.calls:
            for allocation in call.returns:
                if (
                    allocation.selected_version_id is None
                    or allocation.logical_state_key is None
                    or allocation.math_object_id is None
                    or allocation.allocation_action == "conflict"
                ):
                    continue
                index.register(
                    RuntimeStateVersionBinding(
                        version_id=allocation.selected_version_id,
                        logical_state_key=allocation.logical_state_key,
                        math_object_id=allocation.math_object_id,
                        runtime_type=allocation.runtime_type,
                        valid_scope_id=allocation.valid_scope,
                        canonical_producer_call_id=(
                            allocation.canonical_producer_call_id
                        ),
                        runtime_path=None,
                        produced_handle=(
                            allocation.state_handle or allocation.handle
                        ),
                    )
                )
        latest: dict[tuple[str, str], str | None] = {}
        for scope in converted.scenario.scopes:
            for model_key, key in converted.logical_keys.items():
                try:
                    selected = index.latest_visible(
                        key,
                        consumer_scope_id=scope.scope_id,
                    )
                    latest[(scope.scope_id, model_key.token)] = (
                        _version_token(selected.version_id)
                        if selected is not None
                        else None
                    )
                except ValueError:
                    latest[(scope.scope_id, model_key.token)] = "<ambiguous>"
        return AdapterStageOutcome(
            self.authority,
            {
                "latest": latest,
                "fallback_count": index.legacy_identity_fallback_count,
            },
            tuple(
                str(item.get("code"))
                for item in index.mismatches
                if item.get("code")
            ),
        )


class C0LogicalGraphAdapter:
    authority = "C0"

    def run(
        self,
        converted: _ConvertedScenario,
        placement: Any,
    ) -> AdapterStageOutcome:
        forced_failure_call_ids = {
            placement.aliases.get(call.call_id, call.call_id)
            for call in converted.scenario.calls
            if call.forced_failure
        }
        shadow_reports = tuple(
            replace(
                report,
                status=(
                    "invalid"
                    if report.call_id in forced_failure_call_ids
                    else report.status
                ),
            )
            for report in placement.call_reports
        )
        reconciliation = FunctionalPlanReconciliationResult(
            plan=placement.plan,
            calls=placement.calls,
            call_reports=shadow_reports,
            dependency_graph=placement.dependency_graph,
            call_placements=placement.placements,
            call_aliases=placement.aliases,
            state_placement_decisions=tuple(
                item.to_payload() for item in placement.typed_decisions
            ),
            state_dependencies=_projected_dependencies(
                converted,
                placement,
            ),
        )
        result = LogicalFunctionalGraphBuilder().build(
            _raw_plan(converted),
            reconciliation,
            handle_registry=converted.registry,
        )
        context = PlannerStateContext(
            ContextManifest(
                context_id=f"oracle:{converted.scenario.scenario_id}",
                context_type="planner",
                schema_version="planner-state-context/v2",
                parent_context_id=None,
                dependency_context_ids=(),
                problem_id="anonymous",
                family_id="oracle",
                family_spec_hash="oracle",
                capability_pack_hash="oracle",
            ),
            PlannerState(
                problem_ir={},
                expanded_family_spec={},
                scope_graph=ScopeGraph(
                    tuple(
                        item.scope_id
                        for item in converted.scenario.scopes
                    ),
                    {
                        item.scope_id: item.parent_scope_id
                        for item in converted.scenario.scopes
                    },
                ),
            ),
        )
        lifecycle = FunctionalTransactionShadowObserver().observe(
            raw_plan=_raw_plan(converted),
            reconciliation=reconciliation,
            diagnostic=None,
            retry_state=None,
            goal_verification_report=None,
            parent_context=context,
            handle_registry=converted.registry,
        )
        statuses = {
            item.call_id: item.status
            for item in lifecycle.call_states
        }
        return AdapterStageOutcome(
            self.authority,
            {
                "canonical_order": result.graph.canonical_order,
                "aliases": result.graph.alias_call_ids,
                "edges": tuple(
                    (
                        item.producer_call_id,
                        item.consumer_call_id,
                        item.kind,
                    )
                    for item in result.graph.dependencies
                ),
                "failed_call_ids": tuple(
                    sorted(
                        call_id
                        for call_id, status in statuses.items()
                        if status == "failed"
                    )
                ),
                "blocked_call_ids": tuple(
                    sorted(
                        call_id
                        for call_id, status in statuses.items()
                        if status == "blocked_by_dependency"
                    )
                ),
                "eliminated_call_ids": tuple(
                    sorted(
                        call_id
                        for call_id, status in statuses.items()
                        if status == "eliminated"
                    )
                ),
            },
            tuple(item.code for item in result.issues),
        )


def run_production_adapters(
    scenario: ScopeNativeGateScenario,
) -> ScopeNativeProductionOutcome:
    b1, converted = B1AllocationAdapter().run(scenario)
    b2, placement = B2PlacementAdapter().run(converted)
    stages = [
            b1,
            b2,
            B3FinalizationAdapter().run(converted, placement),
            B4RetryCheckpointAdapter().run(converted, placement),
            B5bStateReadAdapter().run(converted, placement),
            C0LogicalGraphAdapter().run(converted, placement),
    ]
    if any(call.dead for call in scenario.calls):
        stages.append(run_dead_writer_liveness_adapter(scenario))
    return ScopeNativeProductionOutcome(tuple(stages))


def run_dead_writer_liveness_adapter(
    scenario: ScopeNativeGateScenario,
) -> AdapterStageOutcome:
    """Probe liveness after B1 has provisionally chained same-object writes."""

    _b1, converted = B1AllocationAdapter().run(scenario)
    plan, reconciled, reports, catalog = _functional_inputs(converted)
    version_producers = {
        decision.selected_version_id: call_id
        for call_id, decision in converted.decisions.items()
        if decision.selected_version_id is not None
    }
    dependency_graph: dict[str, tuple[str, ...]] = {}
    for call_id, decision in converted.decisions.items():
        producer_ids: list[str] = []
        computation = converted.computations.get(call_id)
        source_version_ids = tuple(
            binding.version_id
            for binding in (
                computation.arg_bindings
                if computation is not None
                else ()
            )
            if binding.version_id is not None
        )
        for version_id in (
            decision.previous_version_id,
            *source_version_ids,
        ):
            if version_id is None:
                continue
            producer_id = version_producers.get(version_id)
            if producer_id is not None and producer_id != call_id:
                producer_ids.append(producer_id)
        dependency_graph[call_id] = tuple(
            dict.fromkeys(producer_ids)
        )
    result = FunctionalCallLivenessAnalyzer().analyze(
        plan,
        reconciled=reconciled,
        call_reports=reports,
        dependency_graph=dependency_graph,
        catalog=catalog,
        protected_call_ids=("answer",),
    )
    return AdapterStageOutcome(
        "Liveness",
        {
            "kept": tuple(item.call_id for item in result.plan.calls),
            "dropped": result.dropped_call_ids,
        },
    )


def compare_adapter_suite(
    expected: ScopeNativeExpectedOutcome,
    actual: ScopeNativeProductionOutcome,
) -> tuple[AdapterMismatch, ...]:
    if expected.eliminated_call_ids:
        try:
            liveness = actual.stage("Liveness")
        except StopIteration:
            return (
                AdapterMismatch(
                    "Liveness",
                    "stage",
                    "present",
                    "missing",
                ),
            )
        actual_eliminated = tuple(sorted(liveness.values["dropped"]))
        if actual_eliminated != expected.eliminated_call_ids:
            return (
                AdapterMismatch(
                    "Liveness",
                    "eliminated_call_ids",
                    expected.eliminated_call_ids,
                    actual_eliminated,
                ),
            )
        return ()
    expected_by_call = {
        item.call_id: item for item in expected.call_decisions
    }
    b1 = actual.stage("B1")
    for call_id, decision in expected_by_call.items():
        observed = b1.values.get(call_id)
        if decision.allocation_action == "eliminated":
            # Elimination happens after provisional allocation. Its final
            # lifecycle outcome is checked against the production liveness
            # analyzer below.
            continue
        if observed is None:
            return (
                AdapterMismatch(
                    "B1",
                    f"{call_id}.missing",
                    "allocation decision",
                    None,
                ),
            )
        fields = [
            (
                "action",
                decision.provisional_allocation_action
                or decision.allocation_action,
            ),
            (
                "selected",
                decision.provisional_version_id
                if decision.provisional_allocation_action is not None
                else decision.selected_version_id,
            ),
            (
                "previous",
                decision.provisional_previous_version_id
                if decision.provisional_allocation_action is not None
                else decision.previous_version_id,
            ),
        ]
        if decision.allocation_action != "call_local_value":
            fields.append(
                (
                    "canonical",
                    decision.provisional_canonical_call_id
                    or decision.call_id,
                )
            )
        for field, value in fields:
            if observed.get(field) != value:
                return (
                    AdapterMismatch(
                        "B1",
                        f"{call_id}.{field}",
                        value,
                        observed.get(field),
                    ),
                )

    b2 = actual.stage("B2")
    expected_owners = {
        decision.canonical_call_id
        for decision in expected_by_call.values()
        if decision.allocation_action != "eliminated"
    }
    if set(b2.values) != expected_owners:
        return (
            AdapterMismatch(
                "B2",
                "canonical_owners",
                tuple(sorted(expected_owners)),
                tuple(sorted(b2.values)),
            ),
        )
    expected_aliases: dict[str, set[str]] = {
        owner: set() for owner in expected_owners
    }
    for call_id, decision in expected_by_call.items():
        if decision.canonical_call_id != call_id:
            expected_aliases[decision.canonical_call_id].add(call_id)
            continue
        observed = b2.values[call_id]
        if (
            observed.get("execution_scope")
            != decision.execution_scope_id
        ):
            return (
                AdapterMismatch(
                    "B2",
                    f"{call_id}.execution_scope",
                    decision.execution_scope_id,
                    observed.get("execution_scope"),
                ),
            )
        selected_version_id = (
            decision.provisional_version_id
            if decision.allocation_action == "blocked"
            else decision.selected_version_id
        )
        expected_return_scope = decision.return_scope_id
        if (
            decision.allocation_action == "blocked"
            and decision.provisional_allocation_action
            == "call_local_value"
        ):
            expected_return_scope = decision.execution_scope_id
        if (
            selected_version_id is not None
            or (
                decision.allocation_action == "blocked"
                and decision.provisional_allocation_action
                == "call_local_value"
            )
        ):
            if observed.get("return_scope") != expected_return_scope:
                return (
                    AdapterMismatch(
                        "B2",
                        f"{call_id}.return_scope",
                        expected_return_scope,
                        observed.get("return_scope"),
                    ),
                )
        expected_reads = tuple(sorted(decision.source_version_ids))
        actual_reads = tuple(sorted(observed.get("reads", ())))
        if actual_reads != expected_reads:
            return (
                AdapterMismatch(
                    "B2",
                    f"{call_id}.materialized_reads",
                    expected_reads,
                    actual_reads,
                ),
            )
    for owner, aliases in expected_aliases.items():
        observed_aliases = set(b2.values[owner].get("aliases", ()))
        if observed_aliases != aliases:
            return (
                AdapterMismatch(
                    "B2",
                    f"{owner}.aliases",
                    tuple(sorted(aliases)),
                    tuple(sorted(observed_aliases)),
                ),
            )

    b3 = actual.stage("B3")
    actual_b3_categories = _b3_issue_categories(b3.issue_codes)
    if actual_b3_categories != expected.b3_issue_categories:
        return (
            AdapterMismatch(
                "B3",
                "issue_categories",
                expected.b3_issue_categories,
                actual_b3_categories,
            ),
        )
    c0 = actual.stage("C0")
    actual_blocked = tuple(sorted(c0.values["blocked_call_ids"]))
    if actual_blocked != expected.blocked_call_ids:
        return (
            AdapterMismatch(
                "C0",
                "blocked_call_ids",
                expected.blocked_call_ids,
                actual_blocked,
            ),
        )
    if expected.b3_issue_categories:
        # Authoritative B3 stops value/state interpretation, but the C0
        # lifecycle probe remains independently auditable above.
        return ()
    if not expected.b3_issue_categories:
        expected_writers = tuple(
            sorted(
                (
                    decision.call_id,
                    decision.selected_version_id,
                    decision.allocation_action,
                    decision.previous_version_id,
                    decision.source_version_ids,
                )
                for decision in expected_by_call.values()
                if decision.canonical_call_id == decision.call_id
                and decision.allocation_action
                in {"create", "transition", "isolated", "reuse"}
                and decision.selected_version_id is not None
            )
        )
        if b3.values["writers"] != expected_writers:
            return (
                AdapterMismatch(
                    "B3",
                    "writers",
                    expected_writers,
                    b3.values["writers"],
                ),
            )

    b4 = actual.stage("B4")
    for field, value in (
        ("restored_call_ids", expected.restored_call_ids),
        ("provisional_call_ids", expected.provisional_call_ids),
        ("committed_version_ids", expected.committed_version_ids),
    ):
        observed_values = tuple(sorted(b4.values[field]))
        expected_values = tuple(sorted(value))
        if observed_values != expected_values:
            return (
                AdapterMismatch(
                    "B4",
                    field,
                    expected_values,
                    observed_values,
                ),
            )
    if (
        b4.values.get("scope_restore_checked")
        and b4.values.get("empty_scope_ids")
    ):
        return (
            AdapterMismatch(
                "B4",
                "empty_scope_ids",
                (),
                b4.values["empty_scope_ids"],
            ),
        )
    expected_retry_issues = tuple(
        item
        for item in expected.issue_codes
        if item.startswith("planner.retry_")
    )
    if b4.issue_codes != expected_retry_issues:
        return (
            AdapterMismatch(
                "B4",
                "issues",
                expected_retry_issues,
                b4.issue_codes,
            ),
        )

    b5 = actual.stage("B5b")
    expected_latest = {
        (scope, key): version
        for scope, key, version in expected.final_visible_versions
    }
    if b5.values["latest"] != expected_latest:
        return (
            AdapterMismatch(
                "B5b",
                "latest",
                expected_latest,
                b5.values["latest"],
            ),
        )
    if b5.values["fallback_count"] != 0:
        return (
            AdapterMismatch(
                "B5b",
                "fallback_count",
                0,
                b5.values["fallback_count"],
            ),
        )

    actual_order = tuple(c0.values["canonical_order"])
    if actual_order != expected.canonical_order:
        return (
            AdapterMismatch(
                "C0",
                "canonical_order",
                expected.canonical_order,
                actual_order,
            ),
        )
    rank = {call_id: index for index, call_id in enumerate(actual_order)}
    actual_edge_kinds = {
        (producer, consumer, kind)
        for producer, consumer, kind in c0.values["edges"]
    }
    if set(expected.dependency_edge_kinds) != actual_edge_kinds:
        return (
            AdapterMismatch(
                "C0",
                "dependency_edges",
                expected.dependency_edge_kinds,
                tuple(sorted(actual_edge_kinds)),
            ),
        )
    for producer, consumer, _kind in actual_edge_kinds:
        if producer in rank and consumer in rank and rank[producer] >= rank[consumer]:
            return (
                AdapterMismatch(
                    "C0",
                    f"dependency:{producer}->{consumer}",
                    "producer_before_consumer",
                    actual_order,
                ),
            )
    if tuple(c0.issue_codes) != tuple(expected.c0_issue_codes):
        return (
            AdapterMismatch(
                "C0",
                "issues",
                expected.c0_issue_codes,
                c0.issue_codes,
            ),
        )
    if tuple(sorted(c0.values["aliases"])) != tuple(
        sorted(expected.alias_call_ids)
    ):
        return (
            AdapterMismatch(
                "C0",
                "aliases",
                expected.alias_call_ids,
                c0.values["aliases"],
            ),
        )
    return ()


def _b3_issue_categories(
    issue_codes: tuple[str, ...],
) -> tuple[str, ...]:
    categories: list[str] = []
    for code in issue_codes:
        category = (
            "state.version_visibility_or_resolution"
            if code
            in {
                "state.read_version_unresolved",
                "state.transition_source_invisible",
            }
            else code
        )
        if category not in categories:
            categories.append(category)
    return tuple(categories)


def _converted(scenario: ScopeNativeGateScenario) -> _ConvertedScenario:
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(item.scope_id for item in scenario.scopes),
        entity_handles=frozenset(
            f"{item.kind}:{item.origin_scope_id}:{item.object_id}"
            for item in scenario.objects
        ),
        fact_handles=frozenset(),
        answer_handles=frozenset({"answer:g"}),
        scope_parents={
            item.scope_id: item.parent_scope_id for item in scenario.scopes
        },
        answer_value_types={"answer:g": "Point"},
        answer_target_handles={
            "answer:g": (
                f"{scenario.objects[0].kind}:"
                f"{scenario.objects[0].origin_scope_id}:"
                f"{scenario.objects[0].object_id}"
            )
        },
        handle_valid_scopes={
            f"{item.kind}:{item.origin_scope_id}:{item.object_id}": (
                item.origin_scope_id
            )
            for item in scenario.objects
        },
    )
    object_ids = {
        item.object_id: MathObjectId(
            item.object_id,
            item.kind,
            item.origin_scope_id,
        )
        for item in scenario.objects
    }
    logical_keys = {
        key: LogicalStateKey(
            object_ids[key.object_id],
            key.state_kind,
            key.runtime_type,
        )
        for key in {
            *(item.state_key for item in scenario.initial_versions),
            *(
                item.output_state_key
                for item in scenario.calls
                if item.output_state_key is not None
            ),
            *(
                read.state_key
                for item in scenario.calls
                for read in item.state_reads
            ),
        }
    }
    visibility = ScopeVisibilityResolver(registry)
    index = StateIdentityIndex(visibility)
    initial_versions: dict[str, IndexedStateVersion] = {}
    version_ids: dict[str, StateVersionId] = {}
    for item in scenario.initial_versions:
        logical = logical_keys[item.state_key]
        version_id = StateVersionId(
            StateSlotId(logical, item.storage_scope_id),
            item.ordinal,
        )
        version_ids[item.version_id] = version_id
    for item in scenario.initial_versions:
        version_id = version_ids[item.version_id]
        runtime_destination = RuntimeDestinationKey(
            version_id.slot_id.logical_key.object_id,
            version_id.slot_id.logical_key.state_kind,
            version_id.slot_id.logical_key.runtime_type,
            item.runtime_destination,
        )
        indexed = IndexedStateVersion(
            version_id=version_id,
            valid_scope_id=item.valid_scope_id,
            producer_call_id=item.producer_call_id,
            produced_handle=f"initial:{item.version_id}",
            free_symbol_refs=item.free_symbols,
            previous_version_id=version_ids.get(item.previous_version_id),
            source_version_ids=tuple(
                version_ids[value]
                for value in item.source_version_ids
                if value in version_ids
            ),
            runtime_destination=runtime_destination,
        )
        initial_versions[item.version_id] = indexed
        index.register(indexed)
    return _ConvertedScenario(
        scenario=scenario,
        registry=registry,
        object_ids=object_ids,
        logical_keys=logical_keys,
        initial_versions=initial_versions,
        version_ids=version_ids,
        index=index,
        decisions={},
        selected_versions={},
        computations={},
        effects={},
    )


def _initial_index(converted: _ConvertedScenario) -> StateIdentityIndex:
    index = StateIdentityIndex(ScopeVisibilityResolver(converted.registry))
    for item in converted.initial_versions.values():
        index.register(item)
    return index


def _semantic_items(
    converted: _ConvertedScenario,
) -> tuple[SemanticReadCatalogItem, ...]:
    return tuple(
        SemanticReadCatalogItem(
            handle=(
                f"{item.kind}:{item.origin_scope_id}:{item.object_id}"
            ),
            kind=item.kind,
            ref=item.object_id,
            scope=item.origin_scope_id,
            valid_scope=item.origin_scope_id,
            math_object_id=converted.object_ids[item.object_id],
        )
        for item in converted.scenario.objects
    )


def _computation_key(
    call: ModelCall,
    source_ids: tuple[StateVersionId, ...],
) -> ComputationKey:
    bindings = [
        ArgVersionBinding("input", index, version_id=item)
        for index, item in enumerate(source_ids)
    ]
    bindings.extend(
        ArgVersionBinding("condition", index, condition_id=item)
        for index, item in enumerate(call.input_condition_ids)
    )
    return ComputationKey(call.capability_key, tuple(bindings))


def _state_effect_key(
    call: ModelCall,
    logical_key: LogicalStateKey | None,
) -> StateEffectKey:
    return StateEffectKey(
        (
            LogicalReturnEffect(
                "result",
                logical_key,
                "value_only" if logical_key is None else "target_object",
                "value" if logical_key is None else call.requested_write_mode,
            ),
        )
    )


def _version_token(version_id: StateVersionId | None) -> str | None:
    if version_id is None:
        return None
    key = version_id.slot_id.logical_key
    model_key = (
        f"{key.object_id.value}.{key.state_kind}:{key.runtime_type}"
    )
    return (
        f"{model_key}@{version_id.slot_id.storage_scope_id}"
        f"#{version_id.ordinal}"
    )


def _symbol_object_id(value: str) -> MathObjectId:
    parts = value.split(":", 2)
    if len(parts) != 3 or parts[0] != "symbol":
        raise ValueError(f"invalid oracle Symbol identity: {value}")
    return MathObjectId(value, "symbol", parts[1])


def _model_closure_provenance(
    closure: ModelClosureCheckpoint,
) -> SymbolicClosureProvenance:
    target = MathObjectId("symbol:problem:p", "symbol", "problem")
    return SymbolicClosureProvenance(
        status=closure.status,
        target_object_id=target,
        target_value=closure.target_value,
        substitutions=((target, closure.target_value),),
        residual_symbol_ids=tuple(
            MathObjectId(
                f"symbol:problem:{value}",
                "symbol",
                "problem",
            )
            for value in closure.residual_symbols
        ),
        branch_count=closure.branch_count,
        equation_builder="oracle_equation",
        target_binding="parameter",
        equation_sources=closure.equation_sources,
        affected_returns=("result",),
    )


def _checkpoint_storage_scope(checkpoint: Any, call_id: str) -> str | None:
    if checkpoint is None:
        return None
    try:
        index = checkpoint.committed_call_ids.index(call_id)
        version_id = checkpoint.committed_version_ids[index]
    except (ValueError, IndexError):
        return None
    scope_and_ordinal = version_id.rsplit("@", 1)[-1]
    return scope_and_ordinal.rsplit("#", 1)[0]


def _checkpoint_call_is_canonical(
    converted: _ConvertedScenario,
    call_id: str,
) -> bool:
    decision = converted.decisions.get(call_id)
    return decision is not None and decision.canonical_producer_call_id in {
        None,
        call_id,
    }


def _configuration_error_code(message: str) -> str:
    marker = "planner_configuration_error: "
    if marker not in message:
        return "adapter.configuration_error_unclassified"
    return message.split(marker, 1)[1].split(":", 1)[0].strip()


def _dependency_graph(
    scenario: ScopeNativeGateScenario,
) -> dict[str, tuple[str, ...]]:
    graph: dict[str, list[str]] = {
        item.call_id: [] for item in scenario.calls
    }
    for item in scenario.dependency_edges:
        graph[item.consumer_call_id].append(item.producer_call_id)
    for call in scenario.calls:
        for token in call.input_version_ids:
            if any(item.call_id == token for item in scenario.calls):
                graph[call.call_id].append(token)
    return {
        key: tuple(dict.fromkeys(values))
        for key, values in graph.items()
    }


def _topological_order(
    scenario: ScopeNativeGateScenario,
    graph: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    serialized_order = _serialized_scenario_order(scenario)
    rank = {
        call_id: index for index, call_id in enumerate(serialized_order)
    }
    pending = set(rank)
    result: list[str] = []
    while pending:
        ready = sorted(
            (
                item
                for item in pending
                if set(graph.get(item, ())) <= set(result)
            ),
            key=rank.__getitem__,
        )
        if not ready:
            return tuple(result)
        for item in ready:
            pending.remove(item)
            result.append(item)
    return tuple(result)


def _serialized_scenario_order(
    scenario: ScopeNativeGateScenario,
) -> tuple[str, ...]:
    """Project the abstract wire order through FunctionalPlan scope groups."""

    calls_by_scope: dict[str, list[str]] = {
        item.scope_id: [] for item in scenario.scopes
    }
    calls = {item.call_id: item for item in scenario.calls}
    for call_id in scenario.wire_order:
        calls_by_scope[calls[call_id].declared_scope_id].append(call_id)
    scopes = sorted(
        scenario.scopes,
        key=lambda item: min(
            (
                scenario.wire_order.index(call_id)
                for call_id in calls_by_scope[item.scope_id]
            ),
            default=len(scenario.wire_order),
        ),
    )
    return tuple(
        call_id
        for scope in scopes
        for call_id in calls_by_scope[scope.scope_id]
    )


def _functional_inputs(
    converted: _ConvertedScenario,
) -> tuple[
    FunctionalPlan,
    tuple[FunctionalCallReconciliation, ...],
    tuple[FunctionalCallReport, ...],
    FunctionalCapabilityCatalog,
]:
    plan = _raw_plan(converted)
    calls_by_id = {item.call_id: item for item in converted.scenario.calls}
    reconciled: list[FunctionalCallReconciliation] = []
    reports: list[FunctionalCallReport] = []
    for call in converted.scenario.calls:
        decision = converted.decisions[call.call_id]
        values: list[ResolvedFunctionalValue] = []
        for token in call.input_version_ids:
            version_id = (
                converted.selected_versions.get(token)
                or converted.version_ids.get(token)
            )
            if version_id is None:
                continue
            indexed = converted.index.version(version_id)
            key = version_id.slot_id.logical_key
            values.append(
                ResolvedFunctionalValue(
                    handle=f"state:{token}",
                    runtime_type=key.runtime_type,
                    valid_scope=(
                        indexed.valid_scope_id
                        if indexed is not None
                        else call.declared_scope_id
                    ),
                    state_slot_id=f"compat:{token}",
                    source_call_id=(
                        token
                        if token in calls_by_id
                        else None
                    ),
                    return_name=(
                        "result" if token in calls_by_id else None
                    ),
                    object_ref=key.object_id.value,
                    math_object_id=key.object_id,
                    logical_state_key=key,
                    typed_slot_id=version_id.slot_id,
                    state_version_id=version_id,
                )
            )
        for read in call.state_reads:
            object_id = converted.object_ids[read.state_key.object_id]
            logical_key = converted.logical_keys[read.state_key]
            if read.mode == "identity_only":
                values.append(
                    ResolvedFunctionalValue(
                        handle=(
                            f"{object_id.kind}:{object_id.origin_scope_id}:"
                            f"{read.state_key.object_id}"
                        ),
                        runtime_type="PointRef",
                        valid_scope=object_id.origin_scope_id,
                        object_ref=object_id.value,
                        math_object_id=object_id,
                    )
                )
                continue
            if read.mode == "latest":
                values.append(
                    ResolvedFunctionalValue(
                        handle=(
                            f"{object_id.kind}:{object_id.origin_scope_id}:"
                            f"{read.state_key.object_id}"
                        ),
                        runtime_type=logical_key.runtime_type,
                        valid_scope=object_id.origin_scope_id,
                        object_ref=object_id.value,
                        math_object_id=object_id,
                        logical_state_key=logical_key,
                    )
                )
                continue
            token = read.source_call_id or read.version_id
            version_id = (
                converted.selected_versions.get(token or "")
                or converted.version_ids.get(token or "")
            )
            if version_id is None:
                continue
            indexed = converted.index.version(version_id)
            values.append(
                ResolvedFunctionalValue(
                    handle=f"state:{token}",
                    runtime_type=logical_key.runtime_type,
                    valid_scope=(
                        indexed.valid_scope_id
                        if indexed is not None
                        else call.declared_scope_id
                    ),
                    state_slot_id=f"compat:{token}",
                    source_call_id=(
                        token if token in calls_by_id else None
                    ),
                    return_name=(
                        "result" if token in calls_by_id else None
                    ),
                    object_ref=object_id.value,
                    math_object_id=object_id,
                    logical_state_key=logical_key,
                    typed_slot_id=version_id.slot_id,
                    state_version_id=version_id,
                )
            )
        returns: tuple[FunctionalReturnAllocation, ...]
        if (
            decision.selected_version_id is None
            and decision.action == "call_local_value"
        ):
            returns = (
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    return_name="result",
                    handle=f"result:{call.call_id}",
                    runtime_type="Expression",
                    valid_scope=call.declared_scope_id,
                    state_slot_id=f"call-local:{call.call_id}",
                    object_ref=None,
                    identity_policy="value_only",
                    write_mode="value",
                    computation_key=converted.computations[call.call_id],
                    allocation_action="call_local_value",
                    canonical_producer_call_id=call.call_id,
                    allocation_reason_code=decision.reason_code,
                ),
            )
        elif decision.selected_version_id is None:
            returns = ()
        else:
            version_id = decision.selected_version_id
            key = decision.logical_state_key
            returns = (
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    return_name="result",
                    handle=f"result:{call.call_id}",
                    runtime_type=key.runtime_type,
                    valid_scope=call.valid_scope_id
                    or call.declared_scope_id,
                    state_slot_id=f"compat:{call.call_id}",
                    object_ref=key.object_id.value,
                    identity_policy="target_object",
                    write_mode=(
                        "transition"
                        if decision.action == "transition"
                        else "create"
                    ),
                    state_handle=f"result:{call.call_id}",
                    free_symbol_refs=call.free_symbols,
                    math_object_id=key.object_id,
                    logical_state_key=key,
                    typed_slot_id=version_id.slot_id,
                    selected_version_id=version_id,
                    previous_version_id=decision.previous_version_id,
                    computation_key=converted.computations[call.call_id],
                    source_version_ids=tuple(
                        item.state_version_id
                        for item in values
                        if item.state_version_id is not None
                    ),
                    allocation_action=decision.action,
                    canonical_producer_call_id=(
                        decision.canonical_producer_call_id
                        or call.call_id
                    ),
                    allocation_reason_code=decision.reason_code,
                ),
            )
        reconciled.append(
            FunctionalCallReconciliation(
                call_id=call.call_id,
                scope_id=call.declared_scope_id,
                capability_id=call.capability_key,
                resolved_args={"input": tuple(values)} if values else {},
                returns=returns,
            )
        )
        reports.append(
            FunctionalCallReport(
                call_id=call.call_id,
                scope_id=call.declared_scope_id,
                capability_id=call.capability_key,
                status="valid",
            )
        )
    capabilities = {
        call.capability_key: _capability(call)
        for call in converted.scenario.calls
    }
    return (
        plan,
        tuple(reconciled),
        tuple(reports),
        FunctionalCapabilityCatalog(capabilities),
    )


def _capability(call: ModelCall) -> FunctionalCapability:
    is_value = call.output_state_key is None
    runtime_type = (
        call.output_state_key.runtime_type
        if call.output_state_key is not None
        else "Expression"
    )
    state_kind = (
        call.output_state_key.state_kind
        if call.output_state_key is not None
        else "value"
    )
    source = FunctionSpec(
        function_id=call.capability_key,
        method_id=call.capability_key,
        goal_types=("oracle",),
        args=(
            FunctionArgSpec(
                "input",
                "slot_read",
                runtime_type,
                runtime_type,
                "latest_state",
                required=False,
                cardinality="many",
            ),
        ),
        returns=(
            FunctionReturnSpec(
                "result",
                runtime_type,
                state_kind,
                identity_policy=(
                    "value_only" if is_value else "target_object"
                ),
                write_mode=(
                    "value" if is_value else call.requested_write_mode
                ),
            ),
        ),
        is_pure=call.is_pure,
    )
    return FunctionalCapability(
        capability_id=call.capability_key,
        kind="function",
        goal_types=("oracle",),
        title=call.capability_key,
        use_when="oracle",
        do_not_use_when=(),
        args=(
            FunctionalCapabilityArg(
                "input",
                runtime_type,
                False,
                "many",
                "slot_read",
                domain_type=runtime_type,
                input_view_mode="latest_state",
            ),
        ),
        returns=(
            FunctionalCapabilityReturn(
                "result",
                runtime_type,
                True,
                "one",
                state_kind,
                "result",
                "value_only" if is_value else "target_object",
                None,
                "value" if is_value else call.requested_write_mode,
            ),
        ),
        source=source,
        is_pure=call.is_pure,
        dependency_policy="explicit_args",
    )


def _raw_plan(converted: _ConvertedScenario) -> FunctionalPlan:
    by_scope: dict[str, list[FunctionalCall]] = {
        item.scope_id: [] for item in converted.scenario.scopes
    }
    calls = {item.call_id: item for item in converted.scenario.calls}
    for call_id in converted.scenario.wire_order:
        call = calls[call_id]
        refs = []
        for token in call.input_version_ids:
            if token in calls:
                refs.append(CallResultRef(token, "result"))
            else:
                refs.append(
                    SemanticRef(
                        ref=f"state:{token}",
                        kind="point",
                    )
                )
        for read in call.state_reads:
            if read.mode == "call_result" and read.source_call_id is not None:
                refs.append(CallResultRef(read.source_call_id, "result"))
            elif read.mode in {"latest", "identity_only"}:
                object_kind = next(
                    item.kind
                    for item in converted.scenario.objects
                    if item.object_id == read.state_key.object_id
                )
                refs.append(
                    SemanticRef(
                        ref=read.state_key.object_id,
                        kind=object_kind,
                    )
                )
            elif read.mode == "exact" and read.version_id is not None:
                refs.append(
                    SemanticRef(
                        ref=f"state:{read.version_id}",
                        kind="point",
                    )
                )
        by_scope[call.declared_scope_id].append(
            FunctionalCall(
                call_id=call.call_id,
                capability_id=call.capability_key,
                args={"input": tuple(refs)} if refs else {},
                return_bindings={},
                strategy="",
                reason="",
            )
        )
    return FunctionalPlan(
        tuple(
            FunctionalScope(
                scope_id=item.scope_id,
                label=item.scope_id,
                calls=tuple(by_scope[item.scope_id]),
            )
            for item in sorted(
                converted.scenario.scopes,
                key=lambda scope: min(
                    (
                        converted.scenario.wire_order.index(call.call_id)
                        for call in by_scope[scope.scope_id]
                    ),
                    default=len(converted.scenario.wire_order),
                ),
            )
            if by_scope[item.scope_id]
        )
    )


def _projected_writes(
    converted: _ConvertedScenario,
    placement: Any,
) -> tuple[ProjectedStateWrite, ...]:
    result: list[ProjectedStateWrite] = []
    for call in placement.calls:
        for allocation in call.returns:
            if (
                allocation.selected_version_id is None
                or allocation.logical_state_key is None
                or allocation.math_object_id is None
            ):
                continue
            result.append(
                ProjectedStateWrite(
                    step_id=call.call_id,
                    produced_handle=(
                        allocation.state_handle or allocation.handle
                    ),
                    state_slot_id=allocation.state_slot_id,
                    write_mode=allocation.write_mode,
                    runtime_type=allocation.runtime_type,
                    object_ref=allocation.object_ref,
                    return_name=allocation.return_name,
                    math_object_id=allocation.math_object_id,
                    logical_state_key=allocation.logical_state_key,
                    typed_slot_id=allocation.typed_slot_id,
                    selected_version_id=allocation.selected_version_id,
                    previous_version_id=allocation.previous_version_id,
                    computation_key=allocation.computation_key,
                    source_version_ids=allocation.source_version_ids,
                    allocation_action=allocation.allocation_action,
                    free_symbol_refs=allocation.free_symbol_refs,
                    canonical_producer_call_id=(
                        allocation.canonical_producer_call_id
                        or call.call_id
                    ),
                    valid_scope_id=allocation.valid_scope,
                )
            )
    return tuple(result)


def _projected_dependencies(
    converted: _ConvertedScenario,
    placement: Any,
) -> tuple[ProjectedStateDependency, ...]:
    aliases = placement.aliases
    final_version_by_call = {
        call.call_id: allocation.selected_version_id
        for call in placement.calls
        for allocation in call.returns
        if allocation.return_name == "result"
        and allocation.selected_version_id is not None
    }
    result: list[ProjectedStateDependency] = []
    for call in converted.scenario.calls:
        consumer = aliases.get(call.call_id, call.call_id)
        for token in call.input_version_ids:
            version_id = (
                final_version_by_call.get(
                    aliases.get(token, token)
                )
                or converted.selected_versions.get(token)
                or converted.version_ids.get(token)
            )
            if version_id is None:
                continue
            source_call = token if token in converted.decisions else None
            result.append(
                ProjectedStateDependency(
                    step_id=consumer,
                    state_slot_id=f"compat:{token}",
                    produced_handle=f"state:{token}",
                    runtime_type=version_id.slot_id.logical_key.runtime_type,
                    object_ref=version_id.slot_id.logical_key.object_id.value,
                    arg_name="input",
                    source="wire",
                    source_step_id=(
                        aliases.get(source_call, source_call)
                        if source_call is not None
                        else None
                    ),
                    source_return_name=(
                        "result" if source_call is not None else None
                    ),
                    state_version_id=version_id,
                )
            )
    existing = {
        (
            item.step_id,
            item.arg_name,
            item.state_version_id,
        )
        for item in result
    }
    for call in placement.calls:
        for arg_name, values in call.resolved_args.items():
            for value in values:
                if value.state_version_id is None:
                    continue
                key = (call.call_id, arg_name, value.state_version_id)
                if key in existing:
                    continue
                result.append(
                    ProjectedStateDependency(
                        step_id=call.call_id,
                        state_slot_id=value.state_slot_id or "typed",
                        produced_handle=value.handle,
                        runtime_type=value.runtime_type,
                        object_ref=value.object_ref,
                        arg_name=arg_name,
                        source="resolver",
                        source_step_id=value.source_call_id,
                        source_return_name=value.return_name,
                        state_version_id=value.state_version_id,
                    )
                )
                existing.add(key)
    return tuple(result)


SCOPE_NATIVE_PROTOCOL_PROBES = (
    "baseline",
    "empty_optional_maps",
    "missing_goal",
    "unknown_scope",
    "duplicate_step_owner",
    "invalid_answer_source",
    "revision_drift",
    "source_binding_drift",
)


@lru_cache(maxsize=None)
def run_scope_native_protocol_adapter(
    case_id: str,
    probe: str,
) -> ScopeNativeProtocolOutcome:
    """Run one current-wire probe from authenticated Bundle authority.

    The expensive Bundle/PlanningContext/F5-C construction is cached by the
    shared test fixture. Each probe still recompiles the current LLM content
    wire, and successful probes execute through the Goal checkpoint service.
    """

    if probe not in SCOPE_NATIVE_PROTOCOL_PROBES:
        raise ValueError(f"unknown scope-native protocol probe {probe!r}")

    from _problem_planning_support import cached_planning_binding_fixture
    from _scoped_functional_plan_support import load_v2_fixture_payload
    from shuxueshuo_server.solver.runtime.context import ContextBuilder
    from shuxueshuo_server.solver.runtime.functional_goal_execution import (
        ScopedFunctionalGoalExecutionService,
    )
    from shuxueshuo_server.solver.runtime.functional_plan_content import (
        FunctionalPlanAuthorityFrame,
        FunctionalPlanContentCompiler,
        functional_plan_content_from_plan,
    )
    from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
        ScopedFunctionalPlanError,
        ScopedFunctionalPlanValidator,
    )
    from shuxueshuo_server.solver.extraction.problem_planning_binding import (
        ProblemPlanningBindingError,
    )

    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        handle_registry,
        planner_state_context,
        binding_catalog,
    ) = cached_planning_binding_fixture(case_id)
    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        load_v2_fixture_payload(case_id)
    )
    if plan is None or not validation.ok:
        raise AssertionError(validation.to_payload())
    frame = FunctionalPlanAuthorityFrame.from_planning_context(planning_context)
    content_payload = functional_plan_content_from_plan(
        plan,
        frame=frame,
    ).to_payload()
    _mutate_protocol_probe(
        content_payload,
        probe=probe,
        frame=frame,
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    compilation = FunctionalPlanContentCompiler().compile_payload(
        content_payload,
        frame=frame,
        capability_catalog=catalog,
    )
    normalization_codes = tuple(
        item.code for item in compilation.normalizations
    )
    if compilation.plan is None:
        return ScopeNativeProtocolOutcome(
            case_id=case_id,
            probe=probe,
            planning_context_id=planning_context.planning_context_id,
            binding_signature=binding_catalog.binding_signature,
            issue_codes=tuple(
                item.code for item in compilation.report.issues
            ),
            normalization_codes=normalization_codes,
            checkpoint_id=None,
            all_required_goals_verified=False,
            transaction_ok=False,
        )

    execution_catalog = binding_catalog
    if probe == "revision_drift":
        execution_catalog = replace(
            binding_catalog,
            bundle_authority_token=replace(
                binding_catalog.bundle_authority_token,
                problem_revision_id="problem-revision:foreign",
            ),
        )
    elif probe == "source_binding_drift":
        key, binding = next(iter(binding_catalog.bindings.items()))
        execution_catalog = replace(
            binding_catalog,
            bindings={
                **binding_catalog.bindings,
                key: replace(
                    binding,
                    source_unit_ids=(
                        *binding.source_unit_ids,
                        "source-unit:foreign",
                    ),
                ),
            },
        )
    try:
        execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
            json.dumps(compilation.plan.to_payload(), ensure_ascii=False),
            inputs=inputs,
            planning_context=planning_context,
            problem_binding_catalog=execution_catalog,
            handle_registry=handle_registry,
            context=ContextBuilder().build(problem),
            planner_state_context=planner_state_context,
            problem_payload=problem_payload,
        )
    except (ScopedFunctionalPlanError, ProblemPlanningBindingError) as exc:
        return ScopeNativeProtocolOutcome(
            case_id=case_id,
            probe=probe,
            planning_context_id=planning_context.planning_context_id,
            binding_signature=binding_catalog.binding_signature,
            issue_codes=(exc.code,),
            normalization_codes=normalization_codes,
            checkpoint_id=None,
            all_required_goals_verified=False,
            transaction_ok=False,
        )
    checkpoint = execution.checkpoint
    issue_code_values = [
        *(item.code for item in compilation.report.issues),
        *(item.code for item in execution.authority_report.issues),
    ]
    if checkpoint is not None:
        issue_code_values.extend(
            str(item.get("code", ""))
            for item in checkpoint.root_issues
            if item.get("code")
        )
    issue_codes = tuple(dict.fromkeys(issue_code_values))
    return ScopeNativeProtocolOutcome(
        case_id=case_id,
        probe=probe,
        planning_context_id=planning_context.planning_context_id,
        binding_signature=binding_catalog.binding_signature,
        issue_codes=issue_codes,
        normalization_codes=normalization_codes,
        checkpoint_id=(checkpoint.checkpoint_id if checkpoint is not None else None),
        all_required_goals_verified=(
            checkpoint.all_required_goals_verified
            if checkpoint is not None
            else False
        ),
        transaction_ok=(
            checkpoint.transaction_ok if checkpoint is not None else False
        ),
    )


def _mutate_protocol_probe(
    payload: dict[str, Any],
    *,
    probe: str,
    frame: Any,
) -> None:
    if probe == "baseline":
        return
    if probe == "missing_goal":
        payload["goal_plans"].pop(sorted(payload["goal_plans"])[0])
        return
    if probe == "unknown_scope":
        payload.setdefault("scope_steps", {})["unknown_scope"] = [
            deepcopy(_first_protocol_step(payload))
        ]
        return
    if probe == "duplicate_step_owner":
        step = deepcopy(_first_protocol_step(payload))
        owner = _first_protocol_step_owner(payload)
        if owner[0] == "scope":
            payload["scope_steps"][owner[1]].append(step)
        else:
            payload["goal_plans"][owner[1]].setdefault("steps", []).append(step)
        return
    if probe == "invalid_answer_source":
        first_goal = sorted(payload["goal_plans"])[0]
        payload["goal_plans"][first_goal]["answer_from"] = {
            "step_id": "missing_answer_producer",
            "return": "missing_return",
        }
        return
    if probe == "empty_optional_maps":
        step = _first_protocol_step(payload)
        step["output_targets"] = {}
        step["return_expectations"] = {}
        return
    if probe in {"revision_drift", "source_binding_drift"}:
        return
    raise ValueError(probe)


def _first_protocol_step(payload: Mapping[str, Any]) -> dict[str, Any]:
    owner = _first_protocol_step_owner(payload)
    if owner[0] == "scope":
        return payload["scope_steps"][owner[1]][0]
    return payload["goal_plans"][owner[1]]["steps"][0]


def _first_protocol_step_owner(
    payload: Mapping[str, Any],
) -> tuple[str, str]:
    for scope_ref, steps in payload.get("scope_steps", {}).items():
        if steps:
            return "scope", str(scope_ref)
    for goal_ref, goal in payload["goal_plans"].items():
        if goal.get("steps"):
            return "goal", str(goal_ref)
    raise ValueError("protocol fixture contains no steps")
