"""Shadow semantic context for StepIntent planner replay.

Phase 1 keeps this module read-only relative to the existing planner/runtime
pipeline.  It snapshots semantic state from PlannerInputs, registry snapshots,
validation/normalization reports, and replay artifacts so we can prove alias
continuity without changing the executable StepIntent contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from typing import Any, Literal, Protocol

from shuxueshuo_server.solver.runtime.capability_contracts import contract_payloads
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.output_type_inference import (
    FACT_TYPE_TO_OUTPUT_TYPE,
    produced_output_type,
    semantic_name_from_handle,
    semantic_name_to_runtime_type,
)
from shuxueshuo_server.solver.runtime.semantic_reads import SemanticReadCatalogItem
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    StepIntent,
    StepIntentDraft,
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
        return payload


@dataclass(frozen=True)
class Condition:
    """A known relation/fact whose value is its existence."""

    condition_id: str
    kind: str
    scope_id: str
    canonical_handle: str | None
    subject_ids: tuple[str, ...] = ()
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
            "value_type": self.value_type,
            "source_step_id": self.source_step_id,
            "valid_scope": self.valid_scope,
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
        }


@dataclass(frozen=True)
class StepState:
    """A semantic view of one StepIntent in the timeline."""

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
class StableStep:
    """A runtime-verified step prefix entry."""

    step_id: str
    normalized_payload: dict[str, Any]
    verified_slot_writes: tuple[str, ...] = ()
    verified_condition_writes: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "normalized_payload": dict(self.normalized_payload),
            "verified_slot_writes": list(self.verified_slot_writes),
            "verified_condition_writes": list(self.verified_condition_writes),
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
    stable_prefix: tuple[StableStep, ...] = ()
    issues: tuple[dict[str, Any], ...] = ()
    rewrite_events: tuple[StateRewriteEvent, ...] = ()
    capability_contracts: tuple[dict[str, Any], ...] = ()

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
            "stable_prefix": [item.to_payload() for item in self.stable_prefix],
            "issues": [dict(item) for item in self.issues],
            "rewrite_events": [item.to_payload() for item in self.rewrite_events],
            "capability_contracts": [dict(item) for item in self.capability_contracts],
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
        events: list[dict[str, Any]] = []
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
    stable_prefix: list[StableStep] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    rewrite_events: list[StateRewriteEvent] = field(default_factory=list)
    capability_contracts: list[dict[str, Any]] = field(default_factory=list)

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
                stable_prefix=tuple(self.stable_prefix),
                issues=tuple(self.issues),
                rewrite_events=tuple(self.rewrite_events),
                capability_contracts=tuple(self.capability_contracts),
            ),
        )


class PlannerRetryReplaySnapshot(Protocol):
    """Typed subset of PlannerRetryReplayResult consumed by context builder."""

    attempt: int
    errors: tuple[str, ...]
    raw_draft: StepIntentDraft | None
    validation_report: object | None
    normalized_draft: StepIntentDraft | None
    normalization_report: object | None
    effective_draft: StepIntentDraft | None
    diagnostic: object | None
    retry_state: object | None


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
    ) -> PlannerStateContext:
        state = cls._initial_mutable_state(
            inputs,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
            attempt=attempt,
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
    ) -> PlannerStateContext:
        state = cls._initial_mutable_state(
            inputs,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
            attempt=replay.attempt,
        )
        state.issues.extend(dict(item) for item in context_warnings)
        cls._observe_validation_report(
            state,
            replay.validation_report,
        )
        raw_draft = replay.raw_draft
        normalized_draft = replay.normalized_draft
        if raw_draft is not None:
            cls._observe_draft(
                state,
                raw_draft,
                handle_registry=handle_registry,
                status="validated",
                normalized_lookup=_step_payload_lookup(normalized_draft),
            )
        elif normalized_draft is not None:
            cls._observe_draft(
                state,
                normalized_draft,
                handle_registry=handle_registry,
                status="normalized",
                normalized_lookup=_step_payload_lookup(normalized_draft),
            )
        if normalized_draft is not None:
            cls._observe_normalization(
                state,
                raw_draft=raw_draft,
                normalized_draft=normalized_draft,
                normalization_report=replay.normalization_report,
                handle_registry=handle_registry,
            )
        cls._observe_stable_prefix(
            state,
            replay.diagnostic,
            normalized_lookup=_step_payload_lookup(
                replay.effective_draft or normalized_draft
            ),
        )
        cls._observe_retry_issues(state, replay.retry_state)
        for error in replay.errors or ():
            state.issues.append({"layer": "replay", "code": "error", "message": str(error)})
        return state.freeze()

    @staticmethod
    def _initial_mutable_state(
        inputs: PlannerInputs,
        *,
        problem_payload: dict[str, Any],
        handle_registry: CanonicalHandleRegistry,
        attempt: int,
    ) -> _MutableState:
        manifest = ContextManifest(
            context_id=f"ctx_planner_{inputs.problem_id}_attempt_{attempt}",
            context_type="planner",
            schema_version="planner-state-context/v1",
            parent_context_id=None,
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
        math_objects = _math_objects_from_registry(handle_registry)
        conditions = _conditions_from_registry(handle_registry)
        state_slots = {
            slot.slot_id: slot
            for slot in _initial_state_slots_from_registry(handle_registry)
        }
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
            capability_contracts=list(
                contract_payloads(inputs.family_spec, inputs.method_specs)
            ),
        )

    @staticmethod
    def _observe_validation_report(
        state: _MutableState,
        validation_report: Any | None,
    ) -> None:
        if validation_report is None:
            return
        for error in getattr(validation_report, "errors", ()) or ():
            state.issues.append(
                {"layer": "validation", "code": "validation_error", "message": str(error)}
            )
        handle_resolution = getattr(validation_report, "handle_resolution", None)
        if handle_resolution is not None:
            for correction in getattr(handle_resolution, "corrections", ()) or ():
                slot_id = _state_id_for_handle(
                    state,
                    getattr(correction, "to_handle", ""),
                    getattr(correction, "step_id", ""),
                )
                _merge_alias(state, slot_id, getattr(correction, "from_handle", ""))
                state.rewrite_events.append(
                    StateRewriteEvent(
                        old_ref=getattr(correction, "from_handle", ""),
                        new_ref=getattr(correction, "to_handle", ""),
                        state_slot_id=slot_id,
                        step_id=getattr(correction, "step_id", ""),
                        source_layer="handle_resolution",
                        reason=getattr(correction, "reason", ""),
                    )
                )
        semantic_report = getattr(validation_report, "semantic_read_resolution", None)
        if semantic_report is not None:
            for error in getattr(semantic_report, "errors", ()) or ():
                payload = error.to_payload() if hasattr(error, "to_payload") else dict(error)
                payload.setdefault("layer", "semantic_reads")
                state.issues.append(payload)

    @classmethod
    def _observe_draft(
        cls,
        state: _MutableState,
        draft: StepIntentDraft,
        *,
        handle_registry: CanonicalHandleRegistry,
        status: StepStatus,
        normalized_lookup: dict[str, dict[str, Any]],
    ) -> None:
        for step in draft.steps:
            slot_reads, condition_reads = _classify_handles(
                step.reads,
                state=state,
                handle_registry=handle_registry,
            )
            slot_writes, condition_writes = _classify_produces(
                step.produces,
                state=state,
                handle_registry=handle_registry,
                produced_by=step.step_id,
                status="planned",
            )
            _classify_creates(
                step.creates,
                state=state,
                produced_by=step.step_id,
            )
            state.step_timeline.append(
                StepState(
                    step_id=step.step_id,
                    scope_id=step.scope_id,
                    raw_payload=step.to_payload(),
                    normalized_payload=normalized_lookup.get(step.step_id),
                    slot_reads=slot_reads,
                    condition_reads=condition_reads,
                    slot_writes=slot_writes,
                    condition_writes=condition_writes,
                    capability_id=step.recipe_hint,
                    status=status,
                )
            )

    @classmethod
    def _observe_normalization(
        cls,
        state: _MutableState,
        *,
        raw_draft: StepIntentDraft | None,
        normalized_draft: StepIntentDraft,
        normalization_report: Any | None,
        handle_registry: CanonicalHandleRegistry,
    ) -> None:
        raw_by_step = {step.step_id: step for step in raw_draft.steps} if raw_draft else {}
        for normalized_step in normalized_draft.steps:
            raw_step = raw_by_step.get(normalized_step.step_id)
            if raw_step is None:
                _classify_produces(
                    normalized_step.produces,
                    state=state,
                    handle_registry=handle_registry,
                    produced_by=normalized_step.step_id,
                    status="validated",
                )
                continue
            raw_handles = {item.handle for item in raw_step.produces}
            normalized_handles = {item.handle for item in normalized_step.produces}
            for old_ref in sorted(raw_handles - normalized_handles):
                new_ref = _best_rewrite_target(
                    old_ref,
                    normalized_step.produces,
                    handle_registry=handle_registry,
                )
                if new_ref is None:
                    continue
                slot_id = _slot_id_for_produced_handle(
                    new_ref,
                    scope_id=_scope_from_handle(new_ref) or normalized_step.scope_id,
                    runtime_type=_runtime_type_for_handle(
                        new_ref,
                        handle_registry=handle_registry,
                    ),
                )
                _ensure_produced_slot(
                    state,
                    ProducedFact(
                        handle=new_ref,
                        valid_scope=normalized_step.scope_id,
                        output_type=_runtime_type_for_handle(
                            new_ref,
                            handle_registry=handle_registry,
                        ),
                    ),
                    produced_by=normalized_step.step_id,
                    handle_registry=handle_registry,
                    status="validated",
                )
                _merge_alias(state, slot_id, old_ref)
                state.rewrite_events.append(
                    StateRewriteEvent(
                        old_ref=old_ref,
                        new_ref=new_ref,
                        state_slot_id=slot_id,
                        step_id=normalized_step.step_id,
                        source_layer="normalization",
                        reason=_normalization_reason(normalization_report, normalized_step.step_id, old_ref),
                    )
                )
        cls._observe_normalization_actions(state, normalization_report)

    @staticmethod
    def _observe_normalization_actions(
        state: _MutableState,
        normalization_report: Any | None,
    ) -> None:
        if normalization_report is None:
            return
        for action in getattr(normalization_report, "actions", ()) or ():
            action_name = getattr(action, "action", "")
            handle = getattr(action, "handle", None)
            reason = getattr(action, "reason", "")
            if action_name == "infer_output_type":
                state.issues.append(
                    {
                        "layer": "normalization",
                        "code": action_name,
                        "step_id": getattr(action, "step_id", ""),
                        "handle": handle,
                        "message": reason,
                    }
                )

    @staticmethod
    def _observe_stable_prefix(
        state: _MutableState,
        diagnostic: Any | None,
        *,
        normalized_lookup: dict[str, dict[str, Any]],
    ) -> None:
        if diagnostic is None:
            return
        for accepted in getattr(diagnostic, "accepted_prefix", ()) or ():
            step_id = getattr(accepted, "step_id", None)
            if not step_id:
                continue
            step_state = next(
                (item for item in state.step_timeline if item.step_id == step_id),
                None,
            )
            payload = normalized_lookup.get(step_id) or (
                step_state.normalized_payload if step_state is not None else {}
            )
            state.stable_prefix.append(
                StableStep(
                    step_id=step_id,
                    normalized_payload=payload,
                    verified_slot_writes=(
                        step_state.slot_writes if step_state is not None else ()
                    ),
                    verified_condition_writes=(
                        step_state.condition_writes if step_state is not None else ()
                    ),
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


def initial_planner_state_context(
    inputs: PlannerInputs,
    *,
    problem_payload: dict[str, Any],
    handle_registry: CanonicalHandleRegistry,
    attempt: int = 0,
) -> PlannerStateContext:
    """Build the initial planner context through one shared entry point."""
    return PlannerStateContextBuilder.initial_from_inputs(
        inputs,
        problem_payload=problem_payload,
        handle_registry=handle_registry,
        attempt=attempt,
    )


def _math_objects_from_registry(
    registry: CanonicalHandleRegistry,
) -> list[MathObject]:
    result: list[MathObject] = []
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
        result.append(
            Condition(
                condition_id=f"condition:{_semantic_ref(handle)}@{scope_id}",
                kind=fact_type,
                scope_id=scope_id,
                canonical_handle=handle,
                value_type=fact_type,
                valid_scope=registry.handle_valid_scopes.get(handle),
            )
        )
    return result


def _initial_state_slots_from_registry(
    registry: CanonicalHandleRegistry,
) -> list[StateSlot]:
    result: list[StateSlot] = []
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
            )
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


def _classify_handles(
    handles: tuple[str, ...],
    *,
    state: _MutableState,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    slot_reads: list[str] = []
    condition_reads: list[str] = []
    for handle in handles:
        state_id = state.alias_index.by_handle.get(handle)
        if state_id is None and handle.startswith("fact:"):
            if handle in handle_registry.fact_handles:
                state_id = f"condition:{_semantic_ref(handle)}@{_scope_from_handle(handle) or 'problem'}"
            else:
                state_id = _state_id_for_handle(state, handle, "")
        if state_id is None and handle.startswith("answer:"):
            state_id = _state_id_for_handle(state, handle, "")
        if state_id and state_id.startswith("condition:"):
            condition_reads.append(state_id)
        elif state_id:
            slot_reads.append(state_id)
    return tuple(_unique_ordered(slot_reads)), tuple(_unique_ordered(condition_reads))


def _classify_creates(
    creates: tuple[CreatedEntity, ...],
    *,
    state: _MutableState,
    produced_by: str,
) -> None:
    for item in creates:
        handle = item.handle
        kind = item.entity_type or _scope_kind_from_handle(handle)
        if not kind:
            continue
        scope_id = _scope_from_handle(handle) or item.valid_scope
        name = _semantic_ref(handle)
        object_id = f"{kind}:{name}@{scope_id}"
        if any(existing.object_id == object_id for existing in state.math_objects):
            continue
        state.math_objects.append(
            MathObject(
                object_id=object_id,
                kind=kind,
                scope_id=scope_id,
                canonical_handle=handle,
                semantic_refs=(name,),
                source="derived",
                valid_scope=item.valid_scope or scope_id,
                source_step_id=produced_by,
            )
        )
        state.alias_index.by_handle[handle] = object_id
        refs = list(state.alias_index.by_semantic_ref.get(name, ()))
        refs.append(object_id)
        state.alias_index.by_semantic_ref[name] = tuple(_unique_ordered(refs))


def _classify_produces(
    produces: tuple[ProducedFact, ...],
    *,
    state: _MutableState,
    handle_registry: CanonicalHandleRegistry,
    produced_by: str,
    status: StateStatus,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    slot_writes: list[str] = []
    condition_writes: list[str] = []
    for item in produces:
        runtime_type = _runtime_type_for_produced(item, handle_registry)
        if _produced_is_condition(item, handle_registry, runtime_type):
            condition = _ensure_produced_condition(
                state,
                item,
                produced_by=produced_by,
                handle_registry=handle_registry,
                runtime_type=runtime_type,
            )
            condition_id = condition.condition_id
            condition_writes.append(condition_id)
            continue
        slot = _ensure_produced_slot(
            state,
            item,
            produced_by=produced_by,
            handle_registry=handle_registry,
            status=status,
        )
        slot_writes.append(slot.slot_id)
    return tuple(_unique_ordered(slot_writes)), tuple(_unique_ordered(condition_writes))


def _ensure_produced_condition(
    state: _MutableState,
    item: ProducedFact,
    *,
    produced_by: str,
    handle_registry: CanonicalHandleRegistry,
    runtime_type: str,
) -> Condition:
    scope_id = _scope_from_handle(item.handle) or item.valid_scope
    ref = _semantic_ref(item.handle)
    condition_id = f"condition:{ref}@{scope_id}"
    existing = next(
        (condition for condition in state.conditions if condition.condition_id == condition_id),
        None,
    )
    if existing is not None:
        state.alias_index.by_handle[item.handle] = existing.condition_id
        return existing
    value_type = handle_registry.fact_types.get(item.handle) or item.output_type or runtime_type
    condition = Condition(
        condition_id=condition_id,
        kind=value_type,
        scope_id=scope_id,
        canonical_handle=item.handle,
        value_type=value_type,
        source_step_id=produced_by,
        valid_scope=item.valid_scope,
    )
    state.conditions.append(condition)
    state.alias_index.by_handle[item.handle] = condition_id
    refs = list(state.alias_index.by_semantic_ref.get(ref, ()))
    refs.append(condition_id)
    state.alias_index.by_semantic_ref[ref] = tuple(_unique_ordered(refs))
    return condition


def _ensure_produced_slot(
    state: _MutableState,
    item: ProducedFact,
    *,
    produced_by: str,
    handle_registry: CanonicalHandleRegistry,
    status: StateStatus,
) -> StateSlot:
    runtime_type = _runtime_type_for_produced(item, handle_registry)
    scope_id = _scope_from_handle(item.handle) or item.valid_scope
    slot_id = _slot_id_for_produced_handle(
        item.handle,
        scope_id=scope_id,
        runtime_type=runtime_type,
    )
    existing = state.state_slots.get(slot_id)
    aliases = tuple(
        _unique_ordered(
            [
                *((existing.aliases if existing else ())),
                item.handle,
                *_aliases_for_handle(item.handle, handle_registry),
            ]
        )
    )
    slot = StateSlot(
        slot_id=slot_id,
        object_ref=_object_ref_for_handle(item.handle, runtime_type, scope_id),
        state_kind=_state_kind_from_handle(item.handle, runtime_type),
        scope_id=scope_id,
        runtime_type=runtime_type,
        canonical_handle=item.handle,
        aliases=aliases,
        produced_by=produced_by,
        valid_scope=item.valid_scope,
        status=status,
    )
    state.state_slots[slot_id] = slot
    for alias in aliases:
        state.alias_index.by_handle[alias] = slot_id
    state.alias_index.by_handle[item.handle] = slot_id
    ref = _semantic_ref(item.handle)
    refs = list(state.alias_index.by_semantic_ref.get(ref, ()))
    refs.append(slot_id)
    state.alias_index.by_semantic_ref[ref] = tuple(_unique_ordered(refs))
    return slot


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
        ),
    )
    state.alias_index.by_handle[handle] = slot_id
    return slot_id


def _produced_is_condition(
    item: ProducedFact,
    registry: CanonicalHandleRegistry,
    runtime_type: str,
) -> bool:
    if item.handle.startswith("answer:"):
        return False
    if item.handle in registry.fact_types:
        return registry.fact_types[item.handle] not in {
            "point_coordinate",
            "function_expression",
            "parameter_value",
        }
    return runtime_type in {"Equation", "AngleEquality"}


def _fact_type_is_state_slot(fact_type: str | None) -> bool:
    return fact_type in {
        "point_coordinate",
        "function_expression",
        "parameter_value",
    }


def _runtime_type_for_produced(
    item: ProducedFact,
    registry: CanonicalHandleRegistry,
) -> str:
    return produced_output_type(item, registry) or item.output_type or _runtime_type_for_handle(
        item.handle,
        handle_registry=registry,
    )


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
    return f"fact:{name}@{scope_id}"


def _state_kind_from_handle(handle: str, runtime_type: str) -> str:
    if handle.startswith("answer:"):
        return "answer"
    name = _semantic_ref(handle).lower()
    if runtime_type == "Point":
        return "coordinate"
    if runtime_type == "Parabola":
        return "expression"
    if runtime_type == "Coefficients":
        return "coefficients"
    if runtime_type == "ParameterValue":
        return "value"
    if runtime_type == "MinimumExpression":
        return "minimum_expression"
    if runtime_type == "Line":
        return "line"
    if "value" in name:
        return "value"
    return "expression"


def _best_rewrite_target(
    old_ref: str,
    candidates: tuple[ProducedFact, ...],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    if not candidates:
        return None
    old_type = _runtime_type_for_handle(old_ref, handle_registry)
    same_type = [
        item.handle
        for item in candidates
        if _runtime_type_for_produced(item, handle_registry) == old_type
    ]
    if len(same_type) == 1:
        return same_type[0]
    old_name = _semantic_ref(old_ref).lower()
    for item in candidates:
        candidate_name = _semantic_ref(item.handle).lower()
        if candidate_name in old_name or old_name in candidate_name:
            return item.handle
    if len(candidates) == 1:
        return candidates[0].handle
    return None


def _normalization_reason(
    normalization_report: Any | None,
    step_id: str,
    handle: str,
) -> str:
    if normalization_report is None:
        return "produces handle changed during normalization"
    for action in getattr(normalization_report, "actions", ()) or ():
        if getattr(action, "step_id", None) != step_id:
            continue
        action_handle = getattr(action, "handle", None)
        if action_handle is None or action_handle == handle:
            reason = getattr(action, "reason", "")
            return f"{getattr(action, 'action', 'normalization')}: {reason}".strip()
    return "produces handle changed during normalization"


def _step_payload_lookup(draft: StepIntentDraft | None) -> dict[str, dict[str, Any]]:
    if draft is None:
        return {}
    return {step.step_id: step.to_payload() for step in draft.steps}


def _split_entity_handle(handle: str) -> tuple[str, str, str]:
    parts = handle.split(":", 2)
    if len(parts) != 3:
        return ("entity", "problem", handle)
    return (parts[0], parts[1], parts[2])


def _scope_from_handle(handle: str) -> str | None:
    parts = handle.split(":", 2)
    if len(parts) == 3 and parts[0] in {"point", "line", "segment", "ray", "function", "symbol", "angle", "circle", "polygon", "fact"}:
        return parts[1]
    return None


def _scope_kind_from_handle(handle: str) -> str | None:
    parts = handle.split(":", 2)
    if len(parts) == 3:
        return parts[0]
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
        kind = "answer" if handle.startswith("answer:") else "fact"
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
    "initial_planner_state_context",
    "ScopeGraph",
    "StableStep",
    "StateRewriteEvent",
    "StateSlot",
    "StepState",
]
