"""Typed semantic context for FunctionalPlan replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from typing import Any, Literal, Mapping, Protocol, Sequence, cast, get_args

from shuxueshuo_server.solver.runtime.capability_contracts import contract_payloads
from shuxueshuo_server.solver.runtime.condition_roles import (
    ConditionObjectRoles,
    ConditionRoleResolutionError,
    ConditionRoleResolver,
)
from shuxueshuo_server.solver.runtime.function_specs import function_spec_payloads
from shuxueshuo_server.solver.runtime.legacy_context_migration import (
    LegacyContextIdentityMigrator,
    legacy_state_slot_aliases,
)
from shuxueshuo_server.solver.runtime.macro_specs import macro_spec_payloads
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.output_type_inference import (
    FACT_TYPE_TO_OUTPUT_TYPE,
    produced_output_type,
    semantic_name_from_handle,
    semantic_name_to_runtime_type,
)
from shuxueshuo_server.solver.runtime.object_dependencies import (
    expand_object_dependencies as _expand_object_dependencies,
    structured_object_refs as _structured_object_refs,
)
from shuxueshuo_server.solver.runtime.semantic_reads import SemanticReadCatalogItem
from shuxueshuo_server.solver.runtime.symbol_dependencies import (
    structured_free_symbol_refs,
    symbol_handles_by_name,
    symbol_refs_from_names,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    ComputationKey,
    LogicalStateKey,
    MathObjectId,
    MathObjectRegistry,
    RuntimeDestinationKey,
    StateIdentityFactory,
    StateEffectKey,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerReplayDepth,
    PlannerRetryLayer,
    PlannerRetryPreservePolicy,
    SymbolicClosureProvenance,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_audit import (
    SymbolicClosureWriteAuditRecord,
    audit_symbolic_closure_writes,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    StateSemanticLineage,
    is_object_handle,
    is_object_semantic_kind,
    merge_state_semantic_lineages,
    state_semantic_lineage,
    state_semantic_lineage_from_payload,
    state_kind_for_runtime_type,
)
from shuxueshuo_server.solver.utils import unique_ordered as _unique_ordered

ContextSource = Literal["problem", "derived", "answer", "temporary"]
StateStatus = Literal["given", "planned", "validated", "runtime_verified", "invalid"]
StepStatus = Literal[
    "raw",
    "semantic_resolved",
    "validated",
    "normalized",
    "runtime_verified",
    "failed",
]
ContextEventName = Literal[
    "llm_attempt_received",
    "raw_output_normalized",
    "semantic_resolved",
    "validated",
    "normalized",
    "candidate_resolved",
    "trial_diagnosed",
    "answer_checked",
    "retry_projected",
    "functional_plan_received",
    "functional_call_reconciled",
    "functional_plan_projected",
    "state_observation_authority_selected",
]


@dataclass(frozen=True)
class ContextManifest:
    """Version metadata for a planner context snapshot."""

    context_id: str
    context_type: str
    schema_version: str
    parent_context_id: str | None
    dependency_context_ids: tuple[str, ...]
    problem_id: str
    family_id: str
    family_spec_hash: str
    capability_pack_hash: str
    prompt_template_version: str | None = None
    model: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "context_type": self.context_type,
            "schema_version": self.schema_version,
            "parent_context_id": self.parent_context_id,
            "dependency_context_ids": list(self.dependency_context_ids),
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "family_spec_hash": self.family_spec_hash,
            "capability_pack_hash": self.capability_pack_hash,
            "prompt_template_version": self.prompt_template_version,
            "model": self.model,
        }


@dataclass(frozen=True)
class ScopeGraph:
    """Scope ids and parent chain copied from CanonicalHandleRegistry."""

    scope_ids: tuple[str, ...]
    scope_parents: dict[str, str | None]

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_ids": list(self.scope_ids),
            "scope_parents": dict(self.scope_parents),
        }


@dataclass(frozen=True)
class MathObject:
    """A semantic math object such as a point, line, function, or answer."""

    object_id: str
    kind: str
    scope_id: str
    canonical_handle: str | None
    semantic_refs: tuple[str, ...]
    source: ContextSource
    valid_scope: str | None = None
    source_step_id: str | None = None
    math_object_id: MathObjectId | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "object_id": self.object_id,
            "kind": self.kind,
            "scope_id": self.scope_id,
            "canonical_handle": self.canonical_handle,
            "semantic_refs": list(self.semantic_refs),
            "source": self.source,
        }
        if self.valid_scope is not None:
            payload["valid_scope"] = self.valid_scope
        if self.source_step_id is not None:
            payload["source_step_id"] = self.source_step_id
        if self.math_object_id is not None:
            payload["math_object_id"] = self.math_object_id.to_payload()
        return payload


@dataclass(frozen=True)
class Condition:
    """A known relation/fact whose value is its existence."""

    condition_id: str
    kind: str
    scope_id: str
    canonical_handle: str | None
    subject_ids: tuple[str, ...] = ()
    object_roles: ConditionObjectRoles = ()
    value_type: str | None = None
    source_step_id: str | None = None
    valid_scope: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "kind": self.kind,
            "scope_id": self.scope_id,
            "canonical_handle": self.canonical_handle,
            "subject_ids": list(self.subject_ids),
            "object_roles": {
                role: list(object_refs)
                for role, object_refs in self.object_roles
            },
            "value_type": self.value_type,
            "source_step_id": self.source_step_id,
            "valid_scope": self.valid_scope,
        }


@dataclass(frozen=True)
class StateWriteVersion:
    """One ordered write to a semantic StateSlot."""

    step_id: str
    produced_handle: str
    capability_id: str
    write_mode: str
    previous_write_step_id: str | None = None
    lineage: StateSemanticLineage = StateSemanticLineage()
    version_id: StateVersionId | None = None
    computation_key: ComputationKey | None = None
    state_effect_key: StateEffectKey | None = None
    previous_version_id: StateVersionId | None = None
    source_version_ids: tuple[StateVersionId, ...] = ()
    canonical_producer_call_id: str | None = None
    valid_scope_id: str | None = None
    free_symbol_refs: tuple[str, ...] = ()
    free_symbol_ids: tuple[MathObjectId, ...] = ()
    result_form: str | None = None
    runtime_destination: RuntimeDestinationKey | None = None
    symbolic_closure_provenance: SymbolicClosureProvenance | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "produced_handle": self.produced_handle,
            "capability_id": self.capability_id,
            "write_mode": self.write_mode,
            "previous_write_step_id": self.previous_write_step_id,
            "lineage": self.lineage.to_payload(),
            "version_id": (
                self.version_id.to_payload()
                if self.version_id is not None
                else None
            ),
            "computation_key": (
                self.computation_key.to_payload()
                if self.computation_key is not None
                else None
            ),
            "state_effect_key": (
                self.state_effect_key.to_payload()
                if self.state_effect_key is not None
                else None
            ),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "source_version_ids": [
                item.to_payload() for item in self.source_version_ids
            ],
            "canonical_producer_call_id": self.canonical_producer_call_id,
            "valid_scope_id": self.valid_scope_id,
            "free_symbol_refs": list(self.free_symbol_refs),
            "free_symbol_ids": [
                item.to_payload() for item in self.free_symbol_ids
            ],
            "result_form": self.result_form,
            "runtime_destination": (
                self.runtime_destination.to_payload()
                if self.runtime_destination is not None
                else None
            ),
            "symbolic_closure_provenance": (
                self.symbolic_closure_provenance.to_payload()
                if self.symbolic_closure_provenance is not None
                else None
            ),
        }


@dataclass(frozen=True)
class StateSlot:
    """A typed semantic state attached to a math object or produced fact."""

    slot_id: str
    object_ref: str | None
    state_kind: str
    scope_id: str
    runtime_type: str
    canonical_handle: str | None = None
    aliases: tuple[str, ...] = ()
    produced_by: str | None = None
    valid_scope: str | None = None
    runtime_path: str | None = None
    status: StateStatus = "planned"
    write_history: tuple[StateWriteVersion, ...] = ()
    dependency_object_refs: tuple[str, ...] = ()
    free_symbol_refs: tuple[str, ...] = ()
    free_symbol_ids: tuple[MathObjectId, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()
    lineage: StateSemanticLineage = StateSemanticLineage()
    logical_state_key: LogicalStateKey | None = None
    typed_slot_id: StateSlotId | None = None
    latest_version_id: StateVersionId | None = None
    runtime_destination_key: RuntimeDestinationKey | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "object_ref": self.object_ref,
            "state_kind": self.state_kind,
            "scope_id": self.scope_id,
            "runtime_type": self.runtime_type,
            "canonical_handle": self.canonical_handle,
            "aliases": list(self.aliases),
            "produced_by": self.produced_by,
            "valid_scope": self.valid_scope,
            "runtime_path": self.runtime_path,
            "status": self.status,
            "write_history": [item.to_payload() for item in self.write_history],
            "dependency_object_refs": list(self.dependency_object_refs),
            "free_symbol_refs": list(self.free_symbol_refs),
            "free_symbol_ids": [
                item.to_payload() for item in self.free_symbol_ids
            ],
            "source_state_slot_ids": list(self.source_state_slot_ids),
            "lineage": self.lineage.to_payload(),
            "logical_state_key": (
                self.logical_state_key.to_payload()
                if self.logical_state_key is not None
                else None
            ),
            "typed_slot_id": (
                self.typed_slot_id.to_payload()
                if self.typed_slot_id is not None
                else None
            ),
            "latest_version_id": (
                self.latest_version_id.to_payload()
                if self.latest_version_id is not None
                else None
            ),
            "runtime_destination_key": (
                self.runtime_destination_key.to_payload()
                if self.runtime_destination_key is not None
                else None
            ),
        }


@dataclass(frozen=True)
class StepState:
    """A semantic view of one compiled Functional call in the timeline."""

    step_id: str
    scope_id: str
    raw_payload: dict[str, Any]
    normalized_payload: dict[str, Any] | None
    slot_reads: tuple[str, ...] = ()
    condition_reads: tuple[str, ...] = ()
    slot_writes: tuple[str, ...] = ()
    condition_writes: tuple[str, ...] = ()
    capability_id: str | None = None
    status: StepStatus = "raw"

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "raw_payload": dict(self.raw_payload),
            "normalized_payload": dict(self.normalized_payload)
            if self.normalized_payload is not None
            else None,
            "slot_reads": list(self.slot_reads),
            "condition_reads": list(self.condition_reads),
            "slot_writes": list(self.slot_writes),
            "condition_writes": list(self.condition_writes),
            "capability_id": self.capability_id,
            "status": self.status,
        }


@dataclass(frozen=True)
class RetryMemory:
    """Context-owned retry projection facts."""

    attempt: int = 0
    repair_suffix_start: dict[str, Any] | None = None
    preserve_policy: PlannerRetryPreservePolicy = "none"
    repair_instruction: str = ""
    replay_depth: PlannerReplayDepth | None = None
    selected_repair_layer: PlannerRetryLayer | None = None
    replay_timeline: tuple[dict[str, Any], ...] = ()
    replay_reports: dict[str, Any] | None = None
    issues: tuple[dict[str, Any], ...] = ()
    recovered_issues: tuple[dict[str, Any], ...] = ()
    baseline_candidate: dict[str, Any] | None = None
    stable_candidate_calls: tuple[dict[str, Any], ...] = ()
    committed_candidate_calls: tuple[dict[str, Any], ...] = ()
    runtime_verified_calls: tuple[dict[str, Any], ...] = ()
    validated_call_ids: tuple[str, ...] = ()
    call_memory: tuple[dict[str, Any], ...] = ()
    repair_call_ids: tuple[str, ...] = ()
    functional_retry_graph_checkpoint: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "repair_suffix_start": self.repair_suffix_start,
            "preserve_policy": self.preserve_policy,
            "repair_instruction": self.repair_instruction,
            "replay_depth": self.replay_depth,
            "selected_repair_layer": self.selected_repair_layer,
            "replay_timeline": [dict(item) for item in self.replay_timeline],
            "replay_reports": self.replay_reports or {},
            "issues": [dict(item) for item in self.issues],
            "recovered_issues": [dict(item) for item in self.recovered_issues],
            "baseline_candidate": self.baseline_candidate,
            "stable_candidate_calls": [
                dict(item) for item in self.stable_candidate_calls
            ],
            "committed_candidate_calls": [
                dict(item) for item in self.committed_candidate_calls
            ],
            "runtime_verified_calls": [
                dict(item) for item in self.runtime_verified_calls
            ],
            "validated_call_ids": list(self.validated_call_ids),
            "call_memory": [dict(item) for item in self.call_memory],
            "repair_call_ids": list(self.repair_call_ids),
            "functional_retry_graph_checkpoint": (
                dict(self.functional_retry_graph_checkpoint)
                if self.functional_retry_graph_checkpoint is not None
                else None
            ),
        }


@dataclass(frozen=True)
class AliasIndex:
    """Lookup from handles/semantic refs to semantic state ids."""

    by_handle: dict[str, str] = field(default_factory=dict)
    by_semantic_ref: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "by_handle": dict(sorted(self.by_handle.items())),
            "by_semantic_ref": {
                key: list(value)
                for key, value in sorted(self.by_semantic_ref.items())
            },
        }


@dataclass
class _MutableAliasIndex:
    """Builder-only mutable alias store."""

    by_handle: dict[str, str] = field(default_factory=dict)
    by_semantic_ref: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def freeze(self) -> AliasIndex:
        return AliasIndex(
            by_handle=dict(self.by_handle),
            by_semantic_ref={
                key: tuple(value)
                for key, value in self.by_semantic_ref.items()
            },
        )


@dataclass(frozen=True)
class StateRewriteEvent:
    """A deterministic alias/promotion rewrite observed in replay."""

    old_ref: str
    new_ref: str
    state_slot_id: str
    step_id: str
    source_layer: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        return {
            "old_ref": self.old_ref,
            "new_ref": self.new_ref,
            "state_slot_id": self.state_slot_id,
            "step_id": self.step_id,
            "source_layer": self.source_layer,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ContextEvent:
    """A typed replay event emitted while building planner state context."""

    event: ContextEventName
    ok: bool
    detail_count: int = 0
    attempt: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": self.event,
            "ok": self.ok,
            "detail_count": self.detail_count,
        }
        if self.attempt is not None:
            payload["attempt"] = self.attempt
        return payload


@dataclass(frozen=True)
class PlannerState:
    """Planner semantic state snapshot."""

    problem_ir: dict[str, Any]
    expanded_family_spec: dict[str, Any]
    scope_graph: ScopeGraph
    math_objects: tuple[MathObject, ...] = ()
    conditions: tuple[Condition, ...] = ()
    state_slots: tuple[StateSlot, ...] = ()
    alias_index: AliasIndex = field(default_factory=AliasIndex)
    step_timeline: tuple[StepState, ...] = ()
    retry_memory: RetryMemory = field(default_factory=RetryMemory)
    issues: tuple[dict[str, Any], ...] = ()
    rewrite_events: tuple[StateRewriteEvent, ...] = ()
    context_events: tuple[ContextEvent, ...] = ()
    capability_contracts: tuple[dict[str, Any], ...] = ()
    function_specs: tuple[dict[str, Any], ...] = ()
    macro_specs: tuple[dict[str, Any], ...] = ()
    state_write_provenance: tuple[dict[str, Any], ...] = ()
    # Audit input and canonical candidate are deliberately stored separately.
    raw_functional_plan_snapshot: dict[str, Any] | None = None
    functional_plan_snapshot: dict[str, Any] | None = None
    functional_call_timeline: tuple[dict[str, Any], ...] = ()
    student_step_placements: tuple[dict[str, Any], ...] = ()
    student_scope_references: tuple[dict[str, Any], ...] = ()
    state_identity_decisions: tuple[dict[str, Any], ...] = ()
    identity_mismatches: tuple[dict[str, Any], ...] = ()
    state_placement_decisions: tuple[dict[str, Any], ...] = ()
    placement_mismatches: tuple[dict[str, Any], ...] = ()
    state_finalization_decisions: tuple[dict[str, Any], ...] = ()
    state_finalization_mismatches: tuple[dict[str, Any], ...] = ()
    runtime_destination_decisions: tuple[dict[str, Any], ...] = ()
    typed_identity_completeness: dict[str, Any] = field(default_factory=dict)
    legacy_identity_fallback_count: int = 0
    runtime_consumer_decisions: tuple[dict[str, Any], ...] = ()
    runtime_consumer_mismatches: tuple[dict[str, Any], ...] = ()
    legacy_runtime_identity_fallback_count: int = 0
    functional_binding_decisions: tuple[dict[str, Any], ...] = ()
    functional_binding_mismatches: tuple[dict[str, Any], ...] = ()
    legacy_binding_role_fallback_count: int = 0
    functional_transaction_shadow: dict[str, Any] | None = None
    functional_transaction_execution: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_ir": self.problem_ir,
            "expanded_family_spec": self.expanded_family_spec,
            "scope_graph": self.scope_graph.to_payload(),
            "math_objects": [item.to_payload() for item in self.math_objects],
            "conditions": [item.to_payload() for item in self.conditions],
            "state_slots": [item.to_payload() for item in self.state_slots],
            "alias_index": self.alias_index.to_payload(),
            "step_timeline": [item.to_payload() for item in self.step_timeline],
            "retry_memory": self.retry_memory.to_payload(),
            "issues": [dict(item) for item in self.issues],
            "rewrite_events": [item.to_payload() for item in self.rewrite_events],
            "context_events": [item.to_payload() for item in self.context_events],
            "capability_contracts": [dict(item) for item in self.capability_contracts],
            "function_specs": [dict(item) for item in self.function_specs],
            "macro_specs": [dict(item) for item in self.macro_specs],
            "state_write_provenance": [
                dict(item) for item in self.state_write_provenance
            ],
            "raw_functional_plan_snapshot": self.raw_functional_plan_snapshot,
            "functional_plan_snapshot": self.functional_plan_snapshot,
            "functional_call_timeline": [
                dict(item) for item in self.functional_call_timeline
            ],
            "student_step_placements": [
                dict(item) for item in self.student_step_placements
            ],
            "student_scope_references": [
                dict(item) for item in self.student_scope_references
            ],
            "state_identity_decisions": [
                dict(item) for item in self.state_identity_decisions
            ],
            "identity_mismatches": [
                dict(item) for item in self.identity_mismatches
            ],
            "state_placement_decisions": [
                dict(item) for item in self.state_placement_decisions
            ],
            "placement_mismatches": [
                dict(item) for item in self.placement_mismatches
            ],
            "state_finalization_decisions": [
                dict(item) for item in self.state_finalization_decisions
            ],
            "state_finalization_mismatches": [
                dict(item) for item in self.state_finalization_mismatches
            ],
            "runtime_destination_decisions": [
                dict(item) for item in self.runtime_destination_decisions
            ],
            "typed_identity_completeness": dict(
                self.typed_identity_completeness
            ),
            "legacy_identity_fallback_count": (
                self.legacy_identity_fallback_count
            ),
            "runtime_consumer_decisions": [
                dict(item) for item in self.runtime_consumer_decisions
            ],
            "runtime_consumer_mismatches": [
                dict(item) for item in self.runtime_consumer_mismatches
            ],
            "legacy_runtime_identity_fallback_count": (
                self.legacy_runtime_identity_fallback_count
            ),
            "functional_binding_decisions": [
                dict(item) for item in self.functional_binding_decisions
            ],
            "functional_binding_mismatches": [
                dict(item) for item in self.functional_binding_mismatches
            ],
            "legacy_binding_role_fallback_count": (
                self.legacy_binding_role_fallback_count
            ),
            "functional_transaction_shadow": (
                dict(self.functional_transaction_shadow)
                if self.functional_transaction_shadow is not None
                else None
            ),
            "functional_transaction_execution": (
                dict(self.functional_transaction_execution)
                if self.functional_transaction_execution is not None
                else None
            ),
        }


@dataclass(frozen=True)
class PlannerStateContext:
    """Versioned shadow context produced alongside planner replay."""

    manifest: ContextManifest
    state: PlannerState

    def to_payload(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_payload(),
            "state": self.state.to_payload(),
        }

    @property
    def rewrite_ledger_payload(self) -> list[dict[str, str]]:
        return [event.to_payload() for event in self.state.rewrite_events]

    @property
    def events_payload(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = [
            item.to_payload() for item in self.state.context_events
        ]
        for event in self.state.rewrite_events:
            events.append({"event": "state_rewrite", **event.to_payload()})
        for issue in self.state.issues:
            events.append({"event": "issue", **dict(issue)})
        return events

    def semantic_read_catalog(
        self,
        scope_id: str | None = None,
    ) -> tuple[SemanticReadCatalogItem, ...]:
        """Project context state into internal semantic read catalog items."""
        del scope_id
        return _semantic_read_catalog_from_context(self)

    def semantic_read_catalog_payload(self) -> dict[str, Any]:
        """Return the prompt-facing semantic read catalog projection."""
        items = self.semantic_read_catalog()
        prompt_items = [item.to_prompt_payload() for item in items if item.prompt_visible]
        return {
            "source": "planner_state_context",
            "source_context_id": self.manifest.context_id,
            "items": prompt_items,
            "item_count": len(prompt_items),
        }

    def state_read_index(
        self,
        handle_registry: CanonicalHandleRegistry,
        *,
        mode: str = "authoritative",
    ) -> Any:
        from shuxueshuo_server.solver.runtime.functional_state_reads import (
            FunctionalStateReadIndex,
        )

        return FunctionalStateReadIndex.from_sources(
            handle_registry=handle_registry,
            mode=mode,
            planner_state_context=self,
        )

    def version(
        self,
        version_id: StateVersionId,
        *,
        handle_registry: CanonicalHandleRegistry,
    ) -> Any | None:
        return self.state_read_index(handle_registry).version(version_id)

    def latest_visible_state(
        self,
        logical_key: LogicalStateKey,
        *,
        scope_id: str,
        handle_registry: CanonicalHandleRegistry,
    ) -> Any | None:
        return self.state_read_index(handle_registry).latest_visible(
            logical_key,
            consumer_scope_id=scope_id,
        )

    @property
    def closure_by_version(
        self,
    ) -> dict[StateVersionId, SymbolicClosureProvenance]:
        """Build the closure index from canonical version history on demand."""
        result: dict[StateVersionId, SymbolicClosureProvenance] = {}
        for slot in self.state.state_slots:
            for write in slot.write_history:
                if (
                    write.version_id is None
                    or write.symbolic_closure_provenance is None
                ):
                    continue
                if write.version_id in result:
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: "
                        "planner.symbolic_closure_provenance_drift: "
                        "duplicate closure provenance for StateVersion "
                        f"{write.version_id!r}"
                    )
                result[write.version_id] = (
                    write.symbolic_closure_provenance
                )
        return result


@dataclass
class _MutableState:
    manifest: ContextManifest
    problem_ir: dict[str, Any]
    expanded_family_spec: dict[str, Any]
    scope_graph: ScopeGraph
    math_objects: list[MathObject]
    conditions: list[Condition]
    state_slots: dict[str, StateSlot]
    alias_index: _MutableAliasIndex
    step_timeline: list[StepState] = field(default_factory=list)
    retry_memory: RetryMemory = field(default_factory=RetryMemory)
    issues: list[dict[str, Any]] = field(default_factory=list)
    rewrite_events: list[StateRewriteEvent] = field(default_factory=list)
    context_events: list[ContextEvent] = field(default_factory=list)
    capability_contracts: list[dict[str, Any]] = field(default_factory=list)
    function_specs: list[dict[str, Any]] = field(default_factory=list)
    macro_specs: list[dict[str, Any]] = field(default_factory=list)
    state_write_provenance: list[dict[str, Any]] = field(default_factory=list)
    raw_functional_plan_snapshot: dict[str, Any] | None = None
    functional_plan_snapshot: dict[str, Any] | None = None
    functional_call_timeline: list[dict[str, Any]] = field(default_factory=list)
    student_step_placements: list[dict[str, Any]] = field(default_factory=list)
    student_scope_references: list[dict[str, Any]] = field(default_factory=list)
    state_identity_decisions: list[dict[str, Any]] = field(default_factory=list)
    identity_mismatches: list[dict[str, Any]] = field(default_factory=list)
    state_placement_decisions: list[dict[str, Any]] = field(default_factory=list)
    placement_mismatches: list[dict[str, Any]] = field(default_factory=list)
    state_finalization_decisions: list[dict[str, Any]] = field(
        default_factory=list
    )
    state_finalization_mismatches: list[dict[str, Any]] = field(
        default_factory=list
    )
    runtime_destination_decisions: list[dict[str, Any]] = field(
        default_factory=list
    )
    typed_identity_completeness: dict[str, Any] = field(default_factory=dict)
    legacy_identity_fallback_count: int = 0
    runtime_consumer_decisions: list[dict[str, Any]] = field(
        default_factory=list
    )
    runtime_consumer_mismatches: list[dict[str, Any]] = field(
        default_factory=list
    )
    legacy_runtime_identity_fallback_count: int = 0
    functional_binding_decisions: list[dict[str, Any]] = field(
        default_factory=list
    )
    functional_binding_mismatches: list[dict[str, Any]] = field(
        default_factory=list
    )
    legacy_binding_role_fallback_count: int = 0
    functional_transaction_shadow: dict[str, Any] | None = None
    functional_transaction_execution: dict[str, Any] | None = None

    def freeze(self) -> PlannerStateContext:
        return PlannerStateContext(
            manifest=self.manifest,
            state=PlannerState(
                problem_ir=self.problem_ir,
                expanded_family_spec=self.expanded_family_spec,
                scope_graph=self.scope_graph,
                math_objects=tuple(self.math_objects),
                conditions=tuple(self.conditions),
                state_slots=tuple(
                    sorted(self.state_slots.values(), key=lambda item: item.slot_id)
                ),
                alias_index=self.alias_index.freeze(),
                step_timeline=tuple(self.step_timeline),
                retry_memory=self.retry_memory,
                issues=tuple(self.issues),
                rewrite_events=tuple(self.rewrite_events),
                context_events=tuple(self.context_events),
                capability_contracts=tuple(self.capability_contracts),
                function_specs=tuple(self.function_specs),
                macro_specs=tuple(self.macro_specs),
                state_write_provenance=tuple(self.state_write_provenance),
                raw_functional_plan_snapshot=self.raw_functional_plan_snapshot,
                functional_plan_snapshot=self.functional_plan_snapshot,
                functional_call_timeline=tuple(self.functional_call_timeline),
                student_step_placements=tuple(self.student_step_placements),
                student_scope_references=tuple(self.student_scope_references),
                state_identity_decisions=tuple(self.state_identity_decisions),
                identity_mismatches=tuple(self.identity_mismatches),
                state_placement_decisions=tuple(
                    self.state_placement_decisions
                ),
                placement_mismatches=tuple(self.placement_mismatches),
                state_finalization_decisions=tuple(
                    self.state_finalization_decisions
                ),
                state_finalization_mismatches=tuple(
                    self.state_finalization_mismatches
                ),
                runtime_destination_decisions=tuple(
                    self.runtime_destination_decisions
                ),
                typed_identity_completeness=dict(
                    self.typed_identity_completeness
                ),
                legacy_identity_fallback_count=(
                    self.legacy_identity_fallback_count
                ),
                runtime_consumer_decisions=tuple(
                    self.runtime_consumer_decisions
                ),
                runtime_consumer_mismatches=tuple(
                    self.runtime_consumer_mismatches
                ),
                legacy_runtime_identity_fallback_count=(
                    self.legacy_runtime_identity_fallback_count
                ),
                functional_binding_decisions=tuple(
                    self.functional_binding_decisions
                ),
                functional_binding_mismatches=tuple(
                    self.functional_binding_mismatches
                ),
                legacy_binding_role_fallback_count=(
                    self.legacy_binding_role_fallback_count
                ),
                functional_transaction_shadow=(
                    dict(self.functional_transaction_shadow)
                    if self.functional_transaction_shadow is not None
                    else None
                ),
                functional_transaction_execution=(
                    dict(self.functional_transaction_execution)
                    if self.functional_transaction_execution is not None
                    else None
                ),
            ),
        )


class PlannerRetryReplaySnapshot(Protocol):
    """Typed subset of PlannerRetryReplayResult consumed by context builder."""

    attempt: int
    errors: tuple[str, ...]
    diagnostic: object | None
    retry_state: object | None
    functional_plan: object | None
    functional_reconciliation: object | None
    transactional_shadow_report: object | None
    transactional_execution_report: object | None
    transactional_attempt_result: object | None
    state_observation_authority: str


def _extend_unique_payloads(
    target: list[dict[str, Any]],
    values: object,
) -> None:
    for item in values or ():
        payload = (
            item.to_payload()
            if hasattr(item, "to_payload")
            else dict(item)
        )
        if payload not in target:
            target.append(payload)


class PlannerStateContextBuilder:
    """Builds shadow PlannerStateContext snapshots from existing artifacts."""

    @classmethod
    def initial_from_inputs(
        cls,
        inputs: PlannerInputs,
        *,
        problem_payload: dict[str, Any],
        handle_registry: CanonicalHandleRegistry,
        attempt: int = 0,
        parent_context_id: str | None = None,
    ) -> PlannerStateContext:
        state = cls._initial_mutable_state(
            inputs,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
            attempt=attempt,
            parent_context_id=parent_context_id,
        )
        return state.freeze()

    @classmethod
    def from_replay_result(
        cls,
        replay: PlannerRetryReplaySnapshot,
        *,
        inputs: PlannerInputs,
        problem_payload: dict[str, Any],
        handle_registry: CanonicalHandleRegistry,
        context_warnings: tuple[dict[str, Any], ...] = (),
        parent_context_id: str | None = None,
    ) -> PlannerStateContext:
        state = cls._initial_mutable_state(
            inputs,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
            attempt=replay.attempt,
            parent_context_id=parent_context_id,
        )
        state.issues.extend(dict(item) for item in context_warnings)
        observation_authority = getattr(
            replay,
            "state_observation_authority",
            "pending",
        )
        if observation_authority not in {"pending", "transactional"}:
            raise StrategyDraftValidationError(
                "planner_configuration_error: invalid state observation "
                f"authority: {observation_authority}"
            )
        if (
            observation_authority == "transactional"
            and getattr(replay, "transactional_attempt_result", None)
            is None
        ):
            raise StrategyDraftValidationError(
                "planner_configuration_error: transactional Context "
                "authority has no attempt result"
            )
        state.context_events.append(
            _context_event(
                "state_observation_authority_selected",
                attempt=replay.attempt,
                ok=True,
                detail_count=(
                    1 if observation_authority == "transactional" else 0
                ),
            )
        )
        cls._observe_functional_candidate(state, replay)
        shadow_report = getattr(
            replay,
            "transactional_shadow_report",
            None,
        )
        if shadow_report is not None:
            state.functional_transaction_shadow = (
                shadow_report.to_payload()
                if hasattr(shadow_report, "to_payload")
                else dict(shadow_report)
            )
        execution_report = getattr(
            replay,
            "transactional_execution_report",
            None,
        )
        if execution_report is not None:
            state.functional_transaction_execution = (
                execution_report.to_payload()
                if hasattr(execution_report, "to_payload")
                else dict(execution_report)
            )
        cls._observe_state_finalization(state, replay)
        state.context_events.append(
            _context_event(
                "llm_attempt_received",
                attempt=replay.attempt,
                ok=True,
            )
        )
        cls._observe_state_write_provenance(
            state,
            replay.diagnostic,
            retry_state=replay.retry_state,
            reconciliation=replay.functional_reconciliation,
        )
        cls._observe_replay_layer_events(state, replay)
        cls._observe_retry_issues(state, replay.retry_state)
        state.retry_memory = _retry_memory_from_retry_state(
            replay.retry_state,
            attempt=replay.attempt,
        )
        if replay.retry_state is not None:
            state.context_events.append(
                _context_event(
                    "retry_projected",
                    attempt=replay.attempt,
                    ok=False,
                )
            )
        for error in replay.errors or ():
            state.issues.append({"layer": "replay", "code": "error", "message": str(error)})
        return state.freeze()

    @staticmethod
    def _observe_functional_candidate(
        state: _MutableState,
        replay: PlannerRetryReplaySnapshot,
    ) -> None:
        plan = getattr(replay, "functional_plan", None)
        reconciliation = getattr(replay, "functional_reconciliation", None)
        if plan is None:
            return
        state.raw_functional_plan_snapshot = plan.to_payload()
        effective_plan = (
            getattr(reconciliation, "effective_plan", None)
            if reconciliation is not None
            else None
        )
        state.functional_plan_snapshot = (
            effective_plan.to_payload()
            if effective_plan is not None
            else state.raw_functional_plan_snapshot
        )
        state.context_events.append(
            _context_event(
                "functional_plan_received",
                attempt=replay.attempt,
                ok=True,
            )
        )
        if reconciliation is None:
            return
        placements = {
            item.canonical_call_id: item
            for item in getattr(reconciliation, "call_placements", ())
        }
        state.functional_call_timeline.extend(
            {
                **item.to_payload(),
                "placement": (
                    placements[item.call_id].to_payload()
                    if item.call_id in placements
                    else None
                ),
            }
            for item in getattr(reconciliation, "calls", ())
        )
        state.state_identity_decisions.extend(
            dict(item)
            for item in getattr(
                reconciliation,
                "state_identity_decisions",
                (),
            )
        )
        state.identity_mismatches.extend(
            dict(item)
            for item in getattr(reconciliation, "identity_mismatches", ())
        )
        state.state_placement_decisions.extend(
            dict(item)
            for item in getattr(
                reconciliation,
                "state_placement_decisions",
                (),
            )
        )
        state.placement_mismatches.extend(
            dict(item)
            for item in getattr(reconciliation, "placement_mismatches", ())
        )
        _extend_unique_payloads(
            state.state_finalization_decisions,
            getattr(reconciliation, "state_finalization_decisions", ()),
        )
        _extend_unique_payloads(
            state.state_finalization_mismatches,
            getattr(reconciliation, "state_finalization_mismatches", ()),
        )
        _extend_unique_payloads(
            state.runtime_destination_decisions,
            getattr(reconciliation, "runtime_destination_decisions", ()),
        )
        state.typed_identity_completeness = dict(
            getattr(
                reconciliation,
                "typed_identity_completeness",
                {},
            )
        )
        state.legacy_identity_fallback_count += int(
            getattr(
                reconciliation,
                "legacy_identity_fallback_count",
                0,
            )
        )
        _extend_unique_payloads(
            state.functional_binding_decisions,
            getattr(reconciliation, "functional_binding_decisions", ()),
        )
        _extend_unique_payloads(
            state.functional_binding_mismatches,
            getattr(reconciliation, "functional_binding_mismatches", ()),
        )
        state.legacy_binding_role_fallback_count += int(
            getattr(
                reconciliation,
                "legacy_binding_role_fallback_count",
                0,
            )
        )
        observation_authority = getattr(
            replay,
            "state_observation_authority",
            "transactional",
        )
        effective_step_payloads: tuple[dict[str, Any], ...] = ()
        if observation_authority == "transactional":
            from shuxueshuo_server.solver.explanation.presentation import (
                transactional_functional_steps,
            )

            effective_step_payloads = transactional_functional_steps(
                replay,
                getattr(replay, "output", None),
            )
        if effective_step_payloads:
            # Local import keeps the runtime state model independent from the
            # explanation package at module-import time.
            from shuxueshuo_server.solver.explanation.presentation import (
                StudentNarrativePlacementProjector,
            )

            narrative = StudentNarrativePlacementProjector().project(
                effective_steps=effective_step_payloads,
                problem=state.problem_ir,
                functional_reconciliation=reconciliation,
                raw_functional_plan=plan,
            )
            state.student_step_placements.extend(
                item.to_payload() for item in narrative.placements
            )
            state.student_scope_references.extend(
                item.to_payload() for item in narrative.references
            )
        for issue in getattr(reconciliation, "issues", ()):
            state.issues.append(issue.to_payload())
        state.context_events.append(
            _context_event(
                "functional_call_reconciled",
                attempt=replay.attempt,
                ok=not bool(getattr(reconciliation, "issues", ())),
            )
        )

    @staticmethod
    def _initial_mutable_state(
        inputs: PlannerInputs,
        *,
        problem_payload: dict[str, Any],
        handle_registry: CanonicalHandleRegistry,
        attempt: int,
        parent_context_id: str | None,
    ) -> _MutableState:
        manifest = ContextManifest(
            context_id=f"ctx_planner_{inputs.problem_id}_attempt_{attempt}",
            context_type="planner",
            schema_version="planner-state-context/v2",
            parent_context_id=parent_context_id,
            dependency_context_ids=(),
            problem_id=inputs.problem_id,
            family_id=inputs.family_spec.family_id,
            family_spec_hash=_stable_hash(asdict(inputs.family_spec)),
            capability_pack_hash=_stable_hash(
                {
                    "base_packs": list(inputs.family_spec.base_packs),
                    "mechanism_packs": list(inputs.family_spec.mechanism_packs),
                    "method_ids": list(inputs.family_spec.method_ids),
                    "step_recipes": [recipe.recipe_id for recipe in inputs.family_spec.step_recipes],
                }
            ),
        )
        scope_graph = ScopeGraph(
            scope_ids=tuple(sorted(handle_registry.scope_ids)),
            scope_parents=dict(handle_registry.scope_parents),
        )
        math_objects = _math_objects_from_registry(
            handle_registry,
            problem_payload=problem_payload,
        )
        conditions = _conditions_from_registry(handle_registry)
        state_slots = {
            slot.slot_id: slot
            for slot in _initial_state_slots_from_registry(handle_registry)
        }
        state_slots = _enrich_initial_state_slots(
            state_slots,
            problem_payload=problem_payload,
        )
        (
            math_objects,
            state_slots,
            legacy_identity_fallback_count,
        ) = _attach_typed_initial_identity(
            math_objects,
            state_slots,
            handle_registry=handle_registry,
        )
        alias_index = _build_alias_index(math_objects, conditions, state_slots.values())
        return _MutableState(
            manifest=manifest,
            problem_ir=dict(problem_payload),
            expanded_family_spec=asdict(inputs.family_spec),
            scope_graph=scope_graph,
            math_objects=math_objects,
            conditions=conditions,
            state_slots=state_slots,
            alias_index=alias_index,
            legacy_identity_fallback_count=(
                legacy_identity_fallback_count
            ),
            capability_contracts=list(
                contract_payloads(inputs.family_spec, inputs.method_specs)
            ),
            function_specs=list(
                function_spec_payloads(inputs.family_spec, inputs.method_specs)
            ),
            macro_specs=list(
                macro_spec_payloads(inputs.family_spec, inputs.method_specs)
            ),
        )

    @staticmethod
    def _observe_state_write_provenance(
        state: _MutableState,
        diagnostic: Any | None,
        *,
        retry_state: Any | None = None,
        reconciliation: Any | None = None,
    ) -> None:
        if diagnostic is None:
            return
        checkpoint = (
            retry_state.functional_retry_graph_checkpoint
            if retry_state is not None
            else None
        )
        checkpoint_by_version = {
            json.dumps(
                item["version_id"],
                ensure_ascii=False,
                sort_keys=True,
            ): item
            for item in (
                checkpoint.get("verified_versions", ())
                if isinstance(checkpoint, dict)
                else ()
            )
            if isinstance(item, dict)
            and isinstance(item.get("version_id"), dict)
        }
        call_by_step = {
            item.call_id: item.canonical_call_id
            for item in (
                getattr(reconciliation, "execution_entries", ()) or ()
            )
        }
        allocation_by_return = {
            (call.call_id, allocation.return_name): allocation
            for call in (
                getattr(reconciliation, "calls", ()) or ()
            )
            for allocation in call.returns
        }
        effect_by_call = {
            item["canonical_call_id"]: item["identity_key"][
                "state_effect_key"
            ]
            for item in (
                getattr(
                    reconciliation,
                    "state_placement_decisions",
                    (),
                )
                or ()
            )
            if isinstance(item, dict)
            and isinstance(item.get("canonical_call_id"), str)
            and isinstance(item.get("identity_key"), dict)
            and isinstance(
                item["identity_key"].get("state_effect_key"),
                dict,
            )
        }
        result_form_by_return = {
            (item.call_id, item.return_name): item.actual_form
            for item in (
                getattr(reconciliation, "result_form_events", ()) or ()
            )
            if item.actual_form is not None
        }
        for item in getattr(diagnostic, "state_write_provenance", ()) or ():
            if hasattr(item, "to_payload"):
                payload = item.to_payload()
                call_id = call_by_step.get(
                    str(payload.get("step_id") or "")
                )
                return_name = payload.get("return_name")
                allocation = (
                    allocation_by_return.get((call_id, return_name))
                    if isinstance(call_id, str)
                    and isinstance(return_name, str)
                    else None
                )
                version_payload = payload.get("selected_version_id")
                checkpoint_record = (
                    checkpoint_by_version.get(
                        json.dumps(
                            version_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                    if isinstance(version_payload, dict)
                    else None
                )
                if checkpoint_record is not None:
                    payload["state_effect_key"] = checkpoint_record.get(
                        "state_effect_key"
                    )
                    payload["canonical_producer_call_id"] = (
                        checkpoint_record.get(
                            "canonical_producer_call_id"
                        )
                    )
                    payload["valid_scope_id"] = checkpoint_record.get(
                        "valid_scope_id"
                    )
                    payload["result_form"] = checkpoint_record.get(
                        "result_form"
                    )
                    payload["runtime_destination_key"] = (
                        checkpoint_record.get("runtime_destination")
                    )
                elif allocation is not None and call_id is not None:
                    payload["state_effect_key"] = effect_by_call.get(
                        call_id
                    )
                    payload["canonical_producer_call_id"] = (
                        allocation.canonical_producer_call_id or call_id
                    )
                    payload["valid_scope_id"] = allocation.valid_scope
                    payload["result_form"] = result_form_by_return.get(
                        (call_id, return_name)
                    )
                state.state_write_provenance.append(payload)
                _apply_state_write_provenance(
                    state,
                    payload,
                    require_typed_authority=reconciliation is not None,
                )

    @staticmethod
    def _observe_state_finalization(
        state: _MutableState,
        replay: PlannerRetryReplaySnapshot,
    ) -> None:
        report = getattr(replay, "finalization_report", None)
        if isinstance(report, dict):
            _extend_unique_payloads(
                state.state_finalization_decisions,
                report.get("state_finalization_decisions", ()),
            )
            _extend_unique_payloads(
                state.state_finalization_mismatches,
                report.get("state_finalization_mismatches", ()),
            )
        diagnostic = getattr(replay, "diagnostic", None)
        if diagnostic is None:
            return
        _extend_unique_payloads(
            state.state_finalization_decisions,
            getattr(diagnostic, "state_finalization_decisions", ()),
        )
        _extend_unique_payloads(
            state.state_finalization_mismatches,
            getattr(diagnostic, "state_finalization_mismatches", ()),
        )
        _extend_unique_payloads(
            state.runtime_destination_decisions,
            getattr(diagnostic, "runtime_destination_decisions", ()),
        )
        _extend_unique_payloads(
            state.runtime_consumer_decisions,
            getattr(diagnostic, "runtime_consumer_decisions", ()),
        )
        _extend_unique_payloads(
            state.runtime_consumer_mismatches,
            getattr(diagnostic, "runtime_consumer_mismatches", ()),
        )
        state.legacy_runtime_identity_fallback_count += int(
            getattr(
                diagnostic,
                "legacy_runtime_identity_fallback_count",
                0,
            )
        )

    @staticmethod
    def _observe_retry_issues(
        state: _MutableState,
        retry_state: Any | None,
    ) -> None:
        if retry_state is None:
            return
        issues = getattr(retry_state, "issues", ()) or ()
        for issue in issues:
            if hasattr(issue, "to_payload"):
                state.issues.append(issue.to_payload())
            elif isinstance(issue, dict):
                state.issues.append(dict(issue))

    @staticmethod
    def _observe_replay_layer_events(
        state: _MutableState,
        replay: PlannerRetryReplaySnapshot,
    ) -> None:
        resolution = getattr(replay, "resolution_report", None)
        if resolution is not None:
            state.context_events.append(
                _context_event(
                    "candidate_resolved",
                    ok=bool(getattr(resolution, "ok", False)),
                    detail_count=len(getattr(resolution, "errors", ()) or ()),
                )
            )
        diagnostic = getattr(replay, "diagnostic", None)
        if diagnostic is not None:
            state.context_events.append(
                _context_event(
                    "trial_diagnosed",
                    ok=bool(getattr(diagnostic, "ok", False)),
                    detail_count=len(getattr(diagnostic, "blockers", ()) or ()),
                )
            )
        goal_issues = getattr(replay, "goal_verification_issues", ()) or ()
        if goal_issues:
            state.context_events.append(
                _context_event(
                    "answer_checked",
                    ok=False,
                    detail_count=len(goal_issues),
                )
            )


def _retry_memory_from_retry_state(
    retry_state: Any | None,
    *,
    attempt: int,
) -> RetryMemory:
    if retry_state is None:
        return RetryMemory(attempt=attempt)
    payload = retry_state.to_payload() if hasattr(retry_state, "to_payload") else retry_state
    if not isinstance(payload, dict):
        return RetryMemory(attempt=attempt)
    return RetryMemory(
        attempt=_int_or_default(payload.get("attempt"), attempt),
        repair_suffix_start=_dict_or_none(payload.get("repair_suffix_start")),
        preserve_policy=_planner_preserve_policy(payload.get("preserve_policy")),
        repair_instruction=str(payload.get("repair_instruction") or ""),
        replay_depth=_planner_replay_depth(payload.get("replay_depth")),
        selected_repair_layer=_planner_retry_layer(
            payload.get("selected_repair_layer")
        ),
        replay_timeline=tuple(
            dict(item)
            for item in payload.get("replay_timeline", ())
            if isinstance(item, dict)
        ),
        replay_reports=(
            dict(payload["replay_reports"])
            if isinstance(payload.get("replay_reports"), dict)
            else None
        ),
        issues=tuple(
            dict(item)
            for item in payload.get("issues", ())
            if isinstance(item, dict)
        ),
        recovered_issues=tuple(
            dict(item)
            for item in payload.get("recovered_issues", ())
            if isinstance(item, dict)
        ),
        baseline_candidate=_dict_or_none(payload.get("baseline_candidate")),
        stable_candidate_calls=tuple(
            dict(item)
            for item in payload.get("stable_candidate_calls", ())
            if isinstance(item, dict)
        ),
        committed_candidate_calls=tuple(
            dict(item)
            for item in payload.get("committed_candidate_calls", ())
            if isinstance(item, dict)
        ),
        runtime_verified_calls=tuple(
            dict(item)
            for item in payload.get("runtime_verified_calls", ())
            if isinstance(item, dict)
        ),
        validated_call_ids=tuple(
            item
            for item in payload.get("validated_call_ids", ())
            if isinstance(item, str)
        ),
        call_memory=tuple(
            dict(item)
            for item in payload.get("call_memory", ())
            if isinstance(item, dict)
        ),
        repair_call_ids=tuple(
            item
            for item in payload.get("repair_call_ids", ())
            if isinstance(item, str)
        ),
        functional_retry_graph_checkpoint=_dict_or_none(
            payload.get("functional_retry_graph_checkpoint")
        ),
    )


_PLANNER_REPLAY_DEPTHS = frozenset(get_args(PlannerReplayDepth))
_PLANNER_RETRY_LAYERS = frozenset(get_args(PlannerRetryLayer))
_PLANNER_PRESERVE_POLICIES = frozenset(get_args(PlannerRetryPreservePolicy))


def _planner_replay_depth(value: object) -> PlannerReplayDepth | None:
    if isinstance(value, str) and value in _PLANNER_REPLAY_DEPTHS:
        return cast(PlannerReplayDepth, value)
    return None


def _planner_retry_layer(value: object) -> PlannerRetryLayer | None:
    if isinstance(value, str) and value in _PLANNER_RETRY_LAYERS:
        return cast(PlannerRetryLayer, value)
    return None


def _planner_preserve_policy(value: object) -> PlannerRetryPreservePolicy:
    if isinstance(value, str) and value in _PLANNER_PRESERVE_POLICIES:
        return cast(PlannerRetryPreservePolicy, value)
    return "none"


def _dict_or_none(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _int_or_default(value: object, default: int) -> int:
    return value if isinstance(value, int) else default


def _context_event(
    event: ContextEventName,
    *,
    ok: bool,
    attempt: int | None = None,
    detail_count: int = 0,
) -> ContextEvent:
    return ContextEvent(
        event=event,
        ok=ok,
        attempt=attempt,
        detail_count=detail_count,
    )


def initial_planner_state_context(
    inputs: PlannerInputs,
    *,
    problem_payload: dict[str, Any],
    handle_registry: CanonicalHandleRegistry,
    attempt: int = 0,
    parent_context_id: str | None = None,
) -> PlannerStateContext:
    """Build the initial planner context through one shared entry point."""
    return PlannerStateContextBuilder.initial_from_inputs(
        inputs,
        problem_payload=problem_payload,
        handle_registry=handle_registry,
        attempt=attempt,
        parent_context_id=parent_context_id,
    )


def _math_objects_from_registry(
    registry: CanonicalHandleRegistry,
    *,
    problem_payload: Mapping[str, Any] | None = None,
) -> list[MathObject]:
    result: list[MathObject] = []
    known_handles: set[str] = set()
    for handle in sorted(registry.entity_handles):
        kind, scope_id, name = _split_entity_handle(handle)
        result.append(
            MathObject(
                object_id=f"{kind}:{name}@{scope_id}",
                kind=kind,
                scope_id=scope_id,
                canonical_handle=handle,
                semantic_refs=(name,),
                source="problem",
                valid_scope=registry.handle_valid_scopes.get(handle, scope_id),
            )
        )
        known_handles.add(handle)
    if problem_payload is not None:
        relationship_handles = {
            handle
            for collection_name in ("entities", "facts")
            for payload in problem_payload.get(collection_name, ())
            if isinstance(payload, Mapping)
            for handle in _structured_object_refs(payload)
            if is_object_handle(handle)
        }
        for handle in sorted(relationship_handles - known_handles):
            kind, scope_id, name = _split_entity_handle(handle)
            if scope_id not in registry.scope_ids:
                continue
            result.append(
                MathObject(
                    object_id=f"{kind}:{name}@{scope_id}",
                    kind=kind,
                    scope_id=scope_id,
                    canonical_handle=handle,
                    semantic_refs=(name,),
                    source="problem",
                    valid_scope=registry.handle_valid_scopes.get(
                        handle,
                        scope_id,
                    ),
                )
            )
            known_handles.add(handle)
    for handle in sorted(registry.answer_handles):
        answer_id = handle.split(":", 1)[1]
        scope_id = registry.handle_valid_scopes.get(handle, "problem")
        result.append(
            MathObject(
                object_id=f"answer:{answer_id}",
                kind="answer",
                scope_id=scope_id,
                canonical_handle=handle,
                semantic_refs=(answer_id,),
                source="answer",
                valid_scope=scope_id,
            )
        )
    return result


def _conditions_from_registry(
    registry: CanonicalHandleRegistry,
) -> list[Condition]:
    result: list[Condition] = []
    for handle in sorted(registry.fact_handles):
        fact_type = registry.fact_types.get(handle, "fact")
        if _fact_type_is_state_slot(fact_type):
            continue
        scope_id = _scope_from_handle(handle) or registry.handle_valid_scopes.get(handle, "problem")
        object_roles = _condition_object_roles(
            fact_type,
            registry.fact_payloads.get(handle, {}),
            entity_payloads=registry.entity_payloads,
        )
        subject_ids = dict(object_roles).get("subject", ())
        result.append(
            Condition(
                condition_id=f"condition:{_semantic_ref(handle)}@{scope_id}",
                kind=fact_type,
                scope_id=scope_id,
                canonical_handle=handle,
                subject_ids=subject_ids,
                object_roles=object_roles,
                value_type=fact_type,
                valid_scope=registry.handle_valid_scopes.get(handle),
            )
        )
    return result


def _initial_state_slots_from_registry(
    registry: CanonicalHandleRegistry,
) -> list[StateSlot]:
    result: list[StateSlot] = []
    point_state_objects = {
        payload.get("subject")
        for handle, payload in registry.fact_payloads.items()
        if registry.fact_types.get(handle) == "point_coordinate"
        and isinstance(payload.get("subject"), str)
    }
    for handle in sorted(registry.fact_handles):
        fact_type = registry.fact_types.get(handle)
        if not _fact_type_is_state_slot(fact_type):
            continue
        runtime_type = _runtime_type_for_handle(handle, registry)
        scope_id = _scope_from_handle(handle) or registry.handle_valid_scopes.get(handle, "problem")
        result.append(
            StateSlot(
                slot_id=_slot_id_for_produced_handle(
                    handle,
                    scope_id=scope_id,
                    runtime_type=runtime_type,
                ),
                object_ref=_object_ref_for_handle(handle, runtime_type, scope_id),
                state_kind=_state_kind_from_handle(handle, runtime_type),
                scope_id=scope_id,
                runtime_type=runtime_type,
                canonical_handle=handle,
                aliases=tuple(_aliases_for_handle(handle, registry)),
                valid_scope=registry.handle_valid_scopes.get(handle),
                status="given",
                lineage=state_semantic_lineage(
                    semantic_roles=(_semantic_ref(handle),),
                ),
            )
        )
    for handle in sorted(registry.entity_handles):
        if not handle.startswith("point:") or handle in point_state_objects:
            continue
        payload = registry.entity_payloads.get(handle, {})
        coordinate = payload.get("coordinate")
        if payload.get("definition") != "coordinate_origin" and not (
            isinstance(coordinate, list | tuple)
            and len(coordinate) == 2
            and all(item is not None for item in coordinate)
        ):
            continue
        scope_id = registry.handle_valid_scopes.get(
            handle,
            _scope_from_handle(handle) or "problem",
        )
        result.append(
            StateSlot(
                slot_id=f"{handle}.coordinate@{scope_id}:Point",
                object_ref=handle,
                state_kind="coordinate",
                scope_id=scope_id,
                runtime_type="Point",
                canonical_handle=handle,
                aliases=tuple(_aliases_for_handle(handle, registry)),
                valid_scope=scope_id,
                status="given",
                lineage=state_semantic_lineage(
                    semantic_roles=(_semantic_ref(handle),),
                ),
            )
        )
    for handle in sorted(registry.answer_handles):
        runtime_type = registry.answer_value_types.get(handle, "Answer")
        scope_id = registry.handle_valid_scopes.get(handle, "problem")
        result.append(
            StateSlot(
                slot_id=_slot_id_for_produced_handle(
                    handle,
                    scope_id=scope_id,
                    runtime_type=runtime_type,
                ),
                object_ref=f"answer:{handle.split(':', 1)[1]}",
                state_kind=_state_kind_from_handle(handle, runtime_type),
                scope_id=scope_id,
                runtime_type=runtime_type,
                canonical_handle=handle,
                aliases=tuple(_aliases_for_handle(handle, registry)),
                valid_scope=scope_id,
                status="given",
                lineage=state_semantic_lineage(
                    semantic_roles=(_semantic_ref(handle),),
                ),
            )
        )
    return result


def _enrich_initial_state_slots(
    slots: dict[str, StateSlot],
    *,
    problem_payload: dict[str, Any],
) -> dict[str, StateSlot]:
    facts = {
        item.get("handle"): item
        for item in problem_payload.get("facts", ())
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    entity_dependencies = {
        item["handle"]: tuple(dict.fromkeys(_structured_object_refs(item)))
        for item in problem_payload.get("entities", ())
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    entity_payloads = {
        item["handle"]: item
        for item in problem_payload.get("entities", ())
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    symbol_handles = symbol_handles_by_name(entity_payloads)
    result: dict[str, StateSlot] = {}
    for slot_id, slot in slots.items():
        payload = facts.get(slot.canonical_handle)
        if payload is None:
            result[slot_id] = slot
            continue
        dependencies = tuple(
            dict.fromkeys(
                _expand_object_dependencies(
                    _structured_object_refs(payload),
                    entity_dependencies,
                )
            )
        )
        subject = payload.get("subject")
        object_ref = (
            subject
            if isinstance(subject, str) and is_object_handle(subject)
            else slot.object_ref
        )
        result[slot_id] = replace(
            slot,
            object_ref=object_ref,
            dependency_object_refs=dependencies,
            free_symbol_refs=structured_free_symbol_refs(
                payload,
                symbol_handles=symbol_handles,
            ),
            lineage=merge_state_semantic_lineages(
                slot.lineage,
                object_roles=(
                    StateObjectRoleBinding(
                        role="subject",
                        object_refs=(object_ref,),
                        source_state_slot_ids=(slot.slot_id,),
                    ),
                )
                if isinstance(object_ref, str) and is_object_handle(object_ref)
                else (),
                source_state_slot_ids=(slot.slot_id,),
            ),
        )
    return result


def _build_alias_index(
    math_objects: list[MathObject],
    conditions: list[Condition],
    state_slots: Any,
) -> _MutableAliasIndex:
    by_handle: dict[str, str] = {}
    by_semantic_ref: dict[str, list[str]] = {}
    for item in math_objects:
        if item.canonical_handle:
            by_handle[item.canonical_handle] = item.object_id
        for ref in item.semantic_refs:
            by_semantic_ref.setdefault(ref, []).append(item.object_id)
    for item in conditions:
        if item.canonical_handle:
            by_handle[item.canonical_handle] = item.condition_id
            by_semantic_ref.setdefault(
                _semantic_ref(item.canonical_handle),
                [],
            ).append(item.condition_id)
    for item in state_slots:
        if item.canonical_handle:
            by_handle[item.canonical_handle] = item.slot_id
        for alias in item.aliases:
            by_handle[alias] = item.slot_id
        by_semantic_ref.setdefault(
            _semantic_ref(item.canonical_handle or item.slot_id),
            [],
        ).append(item.slot_id)
    return _MutableAliasIndex(
        by_handle=by_handle,
        by_semantic_ref={
            key: tuple(_unique_ordered(value))
            for key, value in by_semantic_ref.items()
        },
    )


def _condition_object_roles(
    condition_kind: str,
    payload: Mapping[str, Any],
    *,
    entity_payloads: Mapping[str, Mapping[str, Any]] | None = None,
) -> ConditionObjectRoles:
    try:
        return ConditionRoleResolver.object_roles(
            condition_kind,
            payload,
            entity_payloads=entity_payloads,
        )
    except ConditionRoleResolutionError:
        # Keep malformed facts visible in the Context. A consumer that requires
        # structured roles will emit the typed role-resolution error.
        return ()


def _attach_typed_initial_identity(
    math_objects: list[MathObject],
    state_slots: dict[str, StateSlot],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[list[MathObject], dict[str, StateSlot], int]:
    object_registry = MathObjectRegistry.from_sources(
        handle_registry,
        math_objects=math_objects,
    )
    factory = StateIdentityFactory(object_registry)
    typed_objects = [
        replace(
            item,
            math_object_id=factory.object_id(
                item.canonical_handle or item.object_id
            ),
        )
        for item in math_objects
    ]
    typed_slots: dict[str, StateSlot] = {}
    for slot_id, slot in state_slots.items():
        if (
            slot.object_ref is None
            or slot.object_ref.startswith("answer:")
        ):
            typed_slots[slot_id] = slot
            continue
        logical_key = factory.logical_key(
            object_ref=slot.object_ref,
            state_kind=slot.state_kind,
            runtime_type=slot.runtime_type,
        )
        if logical_key is None:
            typed_slots[slot_id] = slot
            continue
        typed_slot_id = factory.slot_id(
            logical_key,
            storage_scope_id=slot.scope_id,
        )
        latest_version_id = StateVersionId(
            typed_slot_id,
            len(slot.write_history) if slot.write_history else 0,
        )
        typed_slots[slot_id] = replace(
            slot,
            logical_state_key=logical_key,
            typed_slot_id=typed_slot_id,
            latest_version_id=latest_version_id,
            runtime_destination_key=RuntimeDestinationKey(
                logical_key.object_id,
                logical_key.state_kind,
                logical_key.runtime_type,
                slot.runtime_path,
            ),
            free_symbol_ids=_symbol_ids_for_refs(
                slot.free_symbol_refs,
                registry=object_registry,
            ),
        )
    versions_by_legacy_slot: dict[str, StateVersionId] = {}
    for slot in typed_slots.values():
        if (
            slot.latest_version_id is None
            or slot.typed_slot_id is None
        ):
            continue
        for legacy_slot_id in (
            slot.slot_id,
            *legacy_state_slot_aliases(slot.typed_slot_id),
        ):
            existing = versions_by_legacy_slot.get(legacy_slot_id)
            if (
                existing is not None
                and existing != slot.latest_version_id
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.context_identity_migration_failed: "
                    f"legacy state slot {legacy_slot_id} maps to "
                    "multiple StateVersionIds"
                )
            versions_by_legacy_slot[legacy_slot_id] = (
                slot.latest_version_id
            )
    object_candidates: dict[str, set[MathObjectId]] = {}
    for item in typed_objects:
        if item.math_object_id is None:
            continue
        for semantic_ref in (
            item.object_id,
            item.canonical_handle,
            *item.semantic_refs,
        ):
            if semantic_ref is None:
                continue
            object_candidates.setdefault(semantic_ref, set()).add(
                item.math_object_id
            )
    object_ids_by_ref = {
        semantic_ref: next(iter(object_ids))
        for semantic_ref, object_ids in object_candidates.items()
        if len(object_ids) == 1
    }
    legacy_identity_migrator = LegacyContextIdentityMigrator()
    for slot_id, slot in tuple(typed_slots.items()):
        lineage = merge_state_semantic_lineages(
            slot.lineage,
            source_state_slot_ids=slot.source_state_slot_ids,
        )
        typed_slots[slot_id] = replace(
            slot,
            source_state_slot_ids=(
                legacy_identity_migrator.normalize_source_slot_ids(
                    slot.source_state_slot_ids,
                    versions_by_legacy_slot=versions_by_legacy_slot,
                )
            ),
            lineage=legacy_identity_migrator.migrate_lineage(
                lineage,
                object_ids_by_ref=object_ids_by_ref,
                versions_by_legacy_slot=versions_by_legacy_slot,
            ),
        )
    return (
        typed_objects,
        typed_slots,
        legacy_identity_migrator.identity_fallback_count,
    )


def _logical_state_key_from_payload(value: Any) -> LogicalStateKey | None:
    if not isinstance(value, Mapping):
        return None
    return LogicalStateKey.from_payload(value)


def _state_slot_id_from_payload(value: Any) -> StateSlotId | None:
    if not isinstance(value, Mapping):
        return None
    return StateSlotId.from_payload(value)


def _state_version_id_from_payload(value: Any) -> StateVersionId | None:
    if not isinstance(value, Mapping):
        return None
    return StateVersionId.from_payload(value)


def _math_object_ids_from_payload(value: Any) -> tuple[MathObjectId, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        MathObjectId.from_payload(item)
        for item in value
        if isinstance(item, Mapping)
    )


def _symbol_ids_for_refs(
    refs: Sequence[str],
    *,
    registry: MathObjectRegistry,
) -> tuple[MathObjectId, ...]:
    result: list[MathObjectId] = []
    for ref in refs:
        object_id = registry.resolve(ref)
        if object_id is None or object_id.kind != "symbol":
            raise ValueError(
                "planner_configuration_error: "
                "planner.context_identity_migration_failed: "
                f"free_symbol_ref={ref}"
            )
        if object_id not in result:
            result.append(object_id)
    return tuple(result)


def _computation_key_from_payload(value: Any) -> ComputationKey | None:
    if not isinstance(value, Mapping):
        return None
    return ComputationKey.from_payload(value)


def _state_effect_key_from_payload(value: Any) -> StateEffectKey | None:
    if not isinstance(value, Mapping):
        return None
    return StateEffectKey.from_payload(value)


def _runtime_destination_key_from_payload(
    value: Any,
) -> RuntimeDestinationKey | None:
    if not isinstance(value, Mapping):
        return None
    return RuntimeDestinationKey.from_payload(value)


def _source_versions_from_computation(
    computation_key: ComputationKey | None,
) -> tuple[StateVersionId, ...]:
    if computation_key is None:
        return ()
    return tuple(
        _unique_ordered(
            binding.version_id
            for binding in computation_key.arg_bindings
            if binding.version_id is not None
        )
    )


def _merge_alias(
    state: _MutableState,
    slot_id: str,
    alias: str,
) -> None:
    slot = state.state_slots.get(slot_id)
    if slot is None:
        return
    aliases = tuple(_unique_ordered([*slot.aliases, alias]))
    state.state_slots[slot_id] = StateSlot(
        slot_id=slot.slot_id,
        object_ref=slot.object_ref,
        state_kind=slot.state_kind,
        scope_id=slot.scope_id,
        runtime_type=slot.runtime_type,
        canonical_handle=slot.canonical_handle,
        aliases=aliases,
        produced_by=slot.produced_by,
        valid_scope=slot.valid_scope,
        runtime_path=slot.runtime_path,
        status=slot.status,
        write_history=slot.write_history,
        dependency_object_refs=slot.dependency_object_refs,
        free_symbol_refs=slot.free_symbol_refs,
        source_state_slot_ids=slot.source_state_slot_ids,
        lineage=slot.lineage,
        logical_state_key=slot.logical_state_key,
        typed_slot_id=slot.typed_slot_id,
        latest_version_id=slot.latest_version_id,
        runtime_destination_key=slot.runtime_destination_key,
    )
    state.alias_index.by_handle[alias] = slot_id


def _state_id_for_handle(
    state: _MutableState,
    handle: str,
    produced_by: str,
) -> str:
    state_id = state.alias_index.by_handle.get(handle)
    if state_id is not None:
        return state_id
    runtime_type = _runtime_type_for_handle(handle, handle_registry=None)
    slot_id = _slot_id_for_produced_handle(
        handle,
        scope_id=_scope_from_handle(handle) or "problem",
        runtime_type=runtime_type,
    )
    state.state_slots.setdefault(
        slot_id,
        StateSlot(
            slot_id=slot_id,
            object_ref=_object_ref_for_handle(handle, runtime_type, _scope_from_handle(handle) or "problem"),
            state_kind=_state_kind_from_handle(handle, runtime_type),
            scope_id=_scope_from_handle(handle) or "problem",
            runtime_type=runtime_type,
            canonical_handle=handle,
            aliases=(handle,),
            produced_by=produced_by or None,
            valid_scope=_scope_from_handle(handle),
            lineage=state_semantic_lineage(
                semantic_roles=(_semantic_ref(handle),),
            ),
        ),
    )
    state.alias_index.by_handle[handle] = slot_id
    return slot_id


def _apply_state_write_provenance(
    state: _MutableState,
    payload: dict[str, Any],
    *,
    require_typed_authority: bool = True,
) -> None:
    """Reconcile Function/Macro identity writes into the semantic slot ledger."""
    slot_id = payload.get("state_slot_id")
    object_ref = payload.get("object_ref")
    produced_handle = payload.get("produced_handle")
    runtime_type = payload.get("runtime_type")
    if not all(
        isinstance(item, str) and item
        for item in (slot_id, object_ref, produced_handle, runtime_type)
    ):
        return
    selected_version_id = _state_version_id_from_payload(
        payload.get("selected_version_id")
    )
    canonical_producer_call_id = payload.get(
        "canonical_producer_call_id"
    )
    valid_scope_id = payload.get("valid_scope_id")
    if selected_version_id is not None:
        missing_typed_identity = tuple(
            name
            for name, value in (
                ("canonical_producer_call_id", canonical_producer_call_id),
                ("valid_scope_id", valid_scope_id),
            )
            if not isinstance(value, str) or not value
        )
        if missing_typed_identity:
            if not require_typed_authority:
                return
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.retry_version_checkpoint_invalid: "
                f"typed provenance for {produced_handle} is missing "
                f"{', '.join(missing_typed_identity)}"
            )
    old_slot_id = state.alias_index.by_handle.get(produced_handle)
    old_slot = state.state_slots.get(old_slot_id) if old_slot_id is not None else None
    current = state.state_slots.get(slot_id)
    observed_lineage = state_semantic_lineage_from_payload(
        payload.get("lineage")
    )
    histories = [
        *((old_slot.write_history if old_slot is not None else ())),
        *((current.write_history if current is not None else ())),
    ]
    computation_key = _computation_key_from_payload(
        payload.get("computation_key")
    )
    payload_source_versions = tuple(
        parsed
        for item in payload.get("source_version_ids", ())
        if (parsed := _state_version_id_from_payload(item)) is not None
    )
    runtime_free_symbol_refs = tuple(
        str(item) for item in payload.get("free_symbol_names", ())
    )
    runtime_free_symbol_ids = _math_object_ids_from_payload(
        payload.get("free_symbol_ids")
    )
    closure_payload = payload.get("symbolic_closure_provenance")
    symbolic_closure = (
        SymbolicClosureProvenance.from_payload(dict(closure_payload))
        if isinstance(closure_payload, Mapping)
        else None
    )
    if (
        require_typed_authority
        and selected_version_id is not None
        and runtime_free_symbol_refs
        and not runtime_free_symbol_ids
    ):
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            "planner.runtime_symbol_identity_unresolved: "
            f"state={produced_handle}"
        )
    if require_typed_authority and symbolic_closure is not None:
        object_payload = payload.get("math_object_id")
        write_object_id = (
            MathObjectId.from_payload(object_payload)
            if isinstance(object_payload, Mapping)
            else None
        )
        closure_issues = audit_symbolic_closure_writes(
            (
                SymbolicClosureWriteAuditRecord(
                    return_name=(
                        str(payload["return_name"])
                        if payload.get("return_name") is not None
                        else None
                    ),
                    runtime_type=runtime_type,
                    math_object_id=write_object_id,
                    free_symbol_ids=runtime_free_symbol_ids,
                    provenance=symbolic_closure,
                ),
            ),
            expected_provenance=symbolic_closure,
        )
        if closure_issues:
            issue = closure_issues[0]
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                f"{issue.code}: state={produced_handle}, "
                f"{issue.message}"
            )
    version = StateWriteVersion(
        step_id=str(payload.get("step_id") or ""),
        produced_handle=produced_handle,
        capability_id=str(payload.get("capability_id") or ""),
        write_mode=str(payload.get("write_mode") or "value"),
        previous_write_step_id=(
            str(payload["previous_write_step_id"])
            if payload.get("previous_write_step_id") is not None
            else None
        ),
        lineage=observed_lineage,
        version_id=selected_version_id,
        computation_key=computation_key,
        state_effect_key=_state_effect_key_from_payload(
            payload.get("state_effect_key")
        ),
        previous_version_id=_state_version_id_from_payload(
            payload.get("previous_version_id")
        ),
        source_version_ids=(
            payload_source_versions
            or _source_versions_from_computation(computation_key)
        ),
        canonical_producer_call_id=(
            str(canonical_producer_call_id)
            if isinstance(canonical_producer_call_id, str)
            and canonical_producer_call_id
            else None
        ),
        valid_scope_id=(
            str(valid_scope_id)
            if isinstance(valid_scope_id, str) and valid_scope_id
            else None
        ),
        free_symbol_refs=runtime_free_symbol_refs,
        free_symbol_ids=runtime_free_symbol_ids,
        result_form=(
            str(payload["result_form"])
            if payload.get("result_form") is not None
            else None
        ),
        runtime_destination=_runtime_destination_key_from_payload(
            payload.get("runtime_destination_key")
        ),
        symbolic_closure_provenance=symbolic_closure,
    )
    if version not in histories:
        histories.append(version)
    aliases = tuple(
        _unique_ordered(
            [
                *((old_slot.aliases if old_slot is not None else ())),
                *((current.aliases if current is not None else ())),
                produced_handle,
            ]
        )
    )
    scope_id = str(payload.get("scope_id") or _scope_from_handle(produced_handle) or "problem")
    lineage = merge_state_semantic_lineages(
        *((old_slot.lineage,) if old_slot is not None else ()),
        *((current.lineage,) if current is not None else ()),
        observed_lineage,
    )
    slot = StateSlot(
        slot_id=slot_id,
        object_ref=object_ref,
        state_kind=_state_kind_from_handle(produced_handle, runtime_type),
        scope_id=scope_id,
        runtime_type=runtime_type,
        canonical_handle=produced_handle,
        aliases=aliases,
        produced_by=version.step_id,
        valid_scope=version.valid_scope_id,
        runtime_path=(
            version.runtime_destination.runtime_path
            if version.runtime_destination is not None
            else (
                old_slot.runtime_path
                if old_slot is not None
                else (current.runtime_path if current is not None else None)
            )
        ),
        status="verified",
        write_history=tuple(histories),
        dependency_object_refs=(
            tuple(
                _unique_ordered(
                    (
                        *((
                            old_slot.dependency_object_refs
                            if old_slot is not None
                            else ()
                        )),
                        *((
                            current.dependency_object_refs
                            if current is not None
                            else ()
                        )),
                        *(
                            str(item)
                            for item in payload.get(
                                "dependency_object_refs",
                                (),
                            )
                            if isinstance(item, str)
                        ),
                    )
                )
            )
        ),
        free_symbol_refs=runtime_free_symbol_refs,
        free_symbol_ids=runtime_free_symbol_ids,
        source_state_slot_ids=(
            tuple(
                _unique_ordered(
                    (
                        *((
                            old_slot.source_state_slot_ids
                            if old_slot is not None
                            else ()
                        )),
                        *((
                            current.source_state_slot_ids
                            if current is not None
                            else ()
                        )),
                        *(
                            str(item)
                            for item in payload.get(
                                "source_state_slot_ids",
                                (),
                            )
                            if isinstance(item, str)
                        ),
                        *lineage.source_state_slot_ids,
                    )
                )
            )
        ),
        lineage=lineage,
        logical_state_key=_logical_state_key_from_payload(
            payload.get("logical_state_key")
        ),
        typed_slot_id=_state_slot_id_from_payload(
            payload.get("typed_slot_id")
        ),
        latest_version_id=version.version_id,
        runtime_destination_key=(
            version.runtime_destination
            if version.runtime_destination is not None
            else (
                RuntimeDestinationKey(
                    version.version_id.slot_id.logical_key.object_id,
                    version.version_id.slot_id.logical_key.state_kind,
                    version.version_id.slot_id.logical_key.runtime_type,
                    (
                        old_slot.runtime_path
                        if old_slot is not None
                        else (
                            current.runtime_path
                            if current is not None
                            else None
                        )
                    ),
                )
                if version.version_id is not None
                else None
            )
        ),
    )
    if old_slot_id is not None and old_slot_id != slot_id:
        state.state_slots.pop(old_slot_id, None)
    state.state_slots[slot_id] = slot
    for alias in aliases:
        state.alias_index.by_handle[alias] = slot_id
    ref = _semantic_ref(produced_handle)
    refs = [
        item
        for item in state.alias_index.by_semantic_ref.get(ref, ())
        if item != old_slot_id
    ]
    refs.append(slot_id)
    state.alias_index.by_semantic_ref[ref] = tuple(_unique_ordered(refs))


def _fact_type_is_state_slot(fact_type: str | None) -> bool:
    if fact_type is None:
        return False
    return FACT_TYPE_TO_OUTPUT_TYPE.get(fact_type, fact_type) in {
        "Point",
        "Parabola",
        "ParameterValue",
    }


def _runtime_type_for_handle(
    handle: str,
    handle_registry: CanonicalHandleRegistry | None,
) -> str:
    if handle.startswith("answer:"):
        if handle_registry is not None:
            return handle_registry.answer_value_types.get(handle, "Answer")
        return "Answer"
    if handle_registry is not None and handle in handle_registry.fact_types:
        fact_type = handle_registry.fact_types[handle]
        return FACT_TYPE_TO_OUTPUT_TYPE.get(fact_type, fact_type)
    return semantic_name_to_runtime_type(
        _semantic_ref(handle),
        default="Expression",
    ) or "Expression"


def _slot_id_for_produced_handle(
    handle: str,
    *,
    scope_id: str,
    runtime_type: str,
) -> str:
    state_kind = _state_kind_from_handle(handle, runtime_type)
    object_ref = _object_ref_for_handle(handle, runtime_type, scope_id)
    return f"{object_ref}.{state_kind}@{scope_id}:{runtime_type}"


def _object_ref_for_handle(handle: str, runtime_type: str, scope_id: str) -> str:
    if handle.startswith("answer:"):
        return f"answer:{handle.split(':', 1)[1]}"
    name = _semantic_ref(handle)
    if runtime_type == "Parabola":
        return "function:parabola"
    if runtime_type == "Point":
        point_name = name.split("_", 1)[0] if "_" in name else name
        return f"point:{point_name}"
    if runtime_type == "ParameterValue":
        param_name = name.split("_", 1)[0] if "_" in name else name
        return f"symbol:{param_name}"
    if runtime_type == "Symbol":
        return handle if handle.startswith("symbol:") else f"symbol:{scope_id}:{name}"
    return f"fact:{name}@{scope_id}"


def _state_kind_from_handle(handle: str, runtime_type: str) -> str:
    """Project handle state through the canonical runtime-type semantics."""
    return state_kind_for_runtime_type(runtime_type)


def _split_entity_handle(handle: str) -> tuple[str, str, str]:
    parts = handle.split(":", 2)
    if len(parts) != 3:
        return ("entity", "problem", handle)
    return (parts[0], parts[1], parts[2])


def _scope_from_handle(handle: str) -> str | None:
    parts = handle.split(":", 2)
    if len(parts) == 3 and (
        is_object_semantic_kind(parts[0]) or parts[0] == "fact"
    ):
        return parts[1]
    return None


def _semantic_ref(handle: str) -> str:
    return semantic_name_from_handle(handle)


def _semantic_read_catalog_from_context(
    context: PlannerStateContext,
) -> tuple[SemanticReadCatalogItem, ...]:
    source_context_id = context.manifest.context_id
    items: list[SemanticReadCatalogItem] = []
    entity_items: list[SemanticReadCatalogItem] = []
    for item in context.state.math_objects:
        if item.kind == "answer":
            continue
        handle = item.canonical_handle
        if handle is None:
            continue
        valid_scope = item.valid_scope or item.scope_id
        for ref in item.semantic_refs:
            entity_items.append(
                SemanticReadCatalogItem(
                    handle=handle,
                    kind=item.kind,
                    ref=ref,
                    scope=item.scope_id,
                    valid_scope=valid_scope,
                    source_step_id=item.source_step_id,
                    source_context_id=source_context_id,
                    math_object_id=item.math_object_id,
                )
            )
        entity_items.append(
            SemanticReadCatalogItem(
                handle=handle,
                kind=item.kind,
                ref=handle,
                scope=item.scope_id,
                valid_scope=valid_scope,
                source_step_id=item.source_step_id,
                source_context_id=source_context_id,
                math_object_id=item.math_object_id,
                prompt_visible=False,
            )
        )
    items.extend(_disambiguate_context_entity_refs(entity_items))
    for condition in context.state.conditions:
        handle = condition.canonical_handle
        if handle is None:
            continue
        items.append(
            SemanticReadCatalogItem(
                handle=handle,
                kind="fact",
                ref=_semantic_ref(handle),
                scope=condition.scope_id,
                valid_scope=condition.valid_scope or condition.scope_id,
                value_type=condition.value_type,
                source_step_id=condition.source_step_id,
                condition_id=condition.condition_id,
                source_context_id=source_context_id,
            )
        )
    for slot in context.state.state_slots:
        handle = slot.canonical_handle
        if handle is None:
            continue
        kind = (
            "answer"
            if handle.startswith("answer:")
            else ("symbol" if slot.runtime_type == "Symbol" else "fact")
        )
        ref = handle.removeprefix("answer:") if kind == "answer" else _semantic_ref(handle)
        items.append(
            SemanticReadCatalogItem(
                handle=handle,
                kind=kind,
                ref=ref,
                scope=slot.scope_id,
                valid_scope=slot.valid_scope or slot.scope_id,
                value_type=_llm_value_type_for_slot(slot),
                source_step_id=slot.produced_by,
                state_slot_id=slot.slot_id,
                source_context_id=source_context_id,
                math_object_id=(
                    slot.logical_state_key.object_id
                    if slot.logical_state_key is not None
                    else None
                ),
                state_version_id=slot.latest_version_id,
            )
        )
        for alias in slot.aliases:
            if alias == handle or alias == ref:
                continue
            items.append(
                SemanticReadCatalogItem(
                    handle=handle,
                    kind=kind,
                    ref=alias,
                    scope=slot.scope_id,
                    valid_scope=slot.valid_scope or slot.scope_id,
                    value_type=_llm_value_type_for_slot(slot),
                    source_step_id=slot.produced_by,
                    state_slot_id=slot.slot_id,
                    source_context_id=source_context_id,
                    math_object_id=(
                        slot.logical_state_key.object_id
                        if slot.logical_state_key is not None
                        else None
                    ),
                    state_version_id=slot.latest_version_id,
                    prompt_visible=False,
                )
            )
    return tuple(items)


def _disambiguate_context_entity_refs(
    items: list[SemanticReadCatalogItem],
) -> tuple[SemanticReadCatalogItem, ...]:
    counts: dict[tuple[str, str], int] = {}
    for item in items:
        if not item.prompt_visible:
            continue
        key = (item.kind, item.ref)
        counts[key] = counts.get(key, 0) + 1
    result: list[SemanticReadCatalogItem] = []
    for item in items:
        if item.prompt_visible and counts.get((item.kind, item.ref), 0) > 1:
            result.append(replace(item, ref=item.ref, prompt_visible=False))
            result.append(replace(item, ref=f"{item.scope}.{item.ref}"))
        else:
            result.append(item)
    return tuple(result)


def _llm_value_type_for_slot(slot: StateSlot) -> str:
    """Project runtime slot type to the current LLM-facing value_type vocabulary."""
    if slot.runtime_type == "Point" and slot.state_kind == "coordinate":
        return "point_coordinate"
    return slot.runtime_type


def _aliases_for_handle(
    handle: str,
    registry: CanonicalHandleRegistry,
) -> list[str]:
    aliases = [handle]
    aliases.extend(alias for alias, target in registry.handle_aliases.items() if target == handle)
    aliases.extend(alias for alias, target in registry.answer_aliases.items() if target == handle)
    return list(_unique_ordered(aliases))


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "AliasIndex",
    "Condition",
    "ContextManifest",
    "MathObject",
    "PlannerState",
    "PlannerStateContext",
    "PlannerStateContextBuilder",
    "RetryMemory",
    "initial_planner_state_context",
    "ScopeGraph",
    "StateRewriteEvent",
    "StateSlot",
    "StateWriteVersion",
    "StepState",
]
