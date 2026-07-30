"""Typed MathObject, state-slot, version, and allocation identity.

This module is deliberately independent from FunctionalPlan and StepIntent.
Those protocols project into these types; neither wire format is an identity
source.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from typing import Any, Iterable, Literal, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.runtime.handle_alias_index import (
    parse_scoped_non_answer_handle,
)
from shuxueshuo_server.solver.state_semantics import (
    object_kind_for_runtime_type,
    object_semantic_kind_for_handle,
)

StateIdentityMode = Literal["shadow", "authoritative"]
StatePlacementMode = Literal["shadow", "authoritative"]
StateAllocationAction = Literal[
    "reuse",
    "create",
    "transition",
    "isolated",
    "conflict",
    "call_local_value",
]


class AmbiguousMathObjectReferenceError(ValueError):
    """A semantic ref names more than one registered MathObject."""

    def __init__(
        self,
        ref: str,
        candidates: Sequence["MathObjectId"],
    ) -> None:
        self.ref = ref
        self.candidates = tuple(sorted(candidates))
        super().__init__(
            "planner.math_object_identity_ambiguous: "
            f"ref={ref}, candidates="
            f"{[item.value for item in self.candidates]}"
        )


@dataclass(frozen=True, order=True)
class MathObjectId:
    value: str
    kind: str
    origin_scope_id: str

    def to_payload(self) -> dict[str, str]:
        return {
            "value": self.value,
            "kind": self.kind,
            "origin_scope_id": self.origin_scope_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MathObjectId":
        return cls(
            value=str(payload["value"]),
            kind=str(payload["kind"]),
            origin_scope_id=str(payload["origin_scope_id"]),
        )


@dataclass(frozen=True, order=True)
class LogicalStateKey:
    object_id: MathObjectId
    state_kind: str
    runtime_type: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id.to_payload(),
            "state_kind": self.state_kind,
            "runtime_type": self.runtime_type,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "LogicalStateKey":
        return cls(
            object_id=MathObjectId.from_payload(
                _mapping(payload["object_id"])
            ),
            state_kind=str(payload["state_kind"]),
            runtime_type=str(payload["runtime_type"]),
        )


@dataclass(frozen=True, order=True)
class StateSlotId:
    logical_key: LogicalStateKey
    storage_scope_id: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "logical_key": self.logical_key.to_payload(),
            "storage_scope_id": self.storage_scope_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StateSlotId":
        return cls(
            logical_key=LogicalStateKey.from_payload(
                _mapping(payload["logical_key"])
            ),
            storage_scope_id=str(payload["storage_scope_id"]),
        )


@dataclass(frozen=True, order=True)
class StateVersionId:
    slot_id: StateSlotId
    ordinal: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id.to_payload(),
            "ordinal": self.ordinal,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StateVersionId":
        return cls(
            slot_id=StateSlotId.from_payload(_mapping(payload["slot_id"])),
            ordinal=int(payload["ordinal"]),
        )


@dataclass(frozen=True, order=True)
class RuntimeDestinationKey:
    object_id: MathObjectId
    state_kind: str
    runtime_type: str
    runtime_path: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id.to_payload(),
            "state_kind": self.state_kind,
            "runtime_type": self.runtime_type,
            "runtime_path": self.runtime_path,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "RuntimeDestinationKey":
        return cls(
            object_id=MathObjectId.from_payload(
                _mapping(payload["object_id"])
            ),
            state_kind=str(payload["state_kind"]),
            runtime_type=str(payload["runtime_type"]),
            runtime_path=(
                str(payload["runtime_path"])
                if payload.get("runtime_path") is not None
                else None
            ),
        )


@dataclass(frozen=True, order=True)
class ArgVersionBinding:
    arg_name: str
    item_index: int
    version_id: StateVersionId | None = None
    condition_id: str | None = None
    object_id: MathObjectId | None = None
    call_result_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "arg_name": self.arg_name,
            "item_index": self.item_index,
            "version_id": (
                self.version_id.to_payload()
                if self.version_id is not None
                else None
            ),
            "condition_id": self.condition_id,
            "object_id": (
                self.object_id.to_payload()
                if self.object_id is not None
                else None
            ),
            "call_result_id": self.call_result_id,
        }


@dataclass(frozen=True, order=True)
class ComputationKey:
    capability_id: str
    arg_bindings: tuple[ArgVersionBinding, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "arg_bindings": [
                item.to_payload() for item in self.arg_bindings
            ],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ComputationKey":
        return cls(
            capability_id=str(payload["capability_id"]),
            arg_bindings=tuple(
                ArgVersionBinding(
                    arg_name=str(item["arg_name"]),
                    item_index=int(item["item_index"]),
                    version_id=(
                        StateVersionId.from_payload(
                            _mapping(item["version_id"])
                        )
                        if item.get("version_id") is not None
                        else None
                    ),
                    condition_id=(
                        str(item["condition_id"])
                        if item.get("condition_id") is not None
                        else None
                    ),
                    object_id=(
                        MathObjectId.from_payload(
                            _mapping(item["object_id"])
                        )
                        if item.get("object_id") is not None
                        else None
                    ),
                    call_result_id=(
                        str(item["call_result_id"])
                        if item.get("call_result_id") is not None
                        else None
                    ),
                )
                for item in _mapping_items(payload.get("arg_bindings"))
            ),
        )


@dataclass(frozen=True, order=True)
class LogicalReturnEffect:
    return_name: str
    logical_key: LogicalStateKey | None
    identity_policy: str
    write_mode: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "return_name": self.return_name,
            "logical_key": (
                self.logical_key.to_payload()
                if self.logical_key is not None
                else None
            ),
            "identity_policy": self.identity_policy,
            "write_mode": self.write_mode,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "LogicalReturnEffect":
        return cls(
            return_name=str(payload["return_name"]),
            logical_key=(
                LogicalStateKey.from_payload(
                    _mapping(payload["logical_key"])
                )
                if payload.get("logical_key") is not None
                else None
            ),
            identity_policy=str(payload["identity_policy"]),
            write_mode=str(payload["write_mode"]),
        )


@dataclass(frozen=True, order=True)
class StateEffectKey:
    returns: tuple[LogicalReturnEffect, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "returns": [item.to_payload() for item in self.returns],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "StateEffectKey":
        return cls(
            tuple(
                LogicalReturnEffect.from_payload(item)
                for item in _mapping_items(payload.get("returns"))
            )
        )


@dataclass(frozen=True, order=True)
class FunctionalCallIdentityKey:
    computation_key: ComputationKey
    state_effect_key: StateEffectKey

    def to_payload(self) -> dict[str, Any]:
        return {
            "computation_key": self.computation_key.to_payload(),
            "state_effect_key": self.state_effect_key.to_payload(),
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalCallIdentityKey":
        return cls(
            computation_key=ComputationKey.from_payload(
                _mapping(payload["computation_key"])
            ),
            state_effect_key=StateEffectKey.from_payload(
                _mapping(payload["state_effect_key"])
            ),
        )


@dataclass(frozen=True, order=True)
class StateVersionPlacementRewrite:
    source_version_id: StateVersionId
    target_version_id: StateVersionId

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_version_id": self.source_version_id.to_payload(),
            "target_version_id": self.target_version_id.to_payload(),
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "StateVersionPlacementRewrite":
        return cls(
            source_version_id=StateVersionId.from_payload(
                _mapping(payload["source_version_id"])
            ),
            target_version_id=StateVersionId.from_payload(
                _mapping(payload["target_version_id"])
            ),
        )


@dataclass(frozen=True)
class TypedCallPlacementDecision:
    canonical_call_id: str
    alias_call_ids: tuple[str, ...]
    identity_key: FunctionalCallIdentityKey
    declared_scope_ids: tuple[str, ...]
    execution_scope_id: str
    return_scope_ids: Mapping[str, str]
    version_rewrites: tuple[StateVersionPlacementRewrite, ...] = ()
    reason_code: str = "typed_identity_placement"

    def to_payload(self) -> dict[str, Any]:
        return {
            "canonical_call_id": self.canonical_call_id,
            "alias_call_ids": list(self.alias_call_ids),
            "identity_key": self.identity_key.to_payload(),
            "declared_scope_ids": list(self.declared_scope_ids),
            "execution_scope_id": self.execution_scope_id,
            "return_scope_ids": dict(self.return_scope_ids),
            "version_rewrites": [
                item.to_payload() for item in self.version_rewrites
            ],
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "TypedCallPlacementDecision":
        return cls(
            canonical_call_id=str(payload["canonical_call_id"]),
            alias_call_ids=tuple(
                str(item) for item in payload.get("alias_call_ids", ())
            ),
            identity_key=FunctionalCallIdentityKey.from_payload(
                _mapping(payload["identity_key"])
            ),
            declared_scope_ids=tuple(
                str(item) for item in payload.get("declared_scope_ids", ())
            ),
            execution_scope_id=str(payload["execution_scope_id"]),
            return_scope_ids={
                str(key): str(value)
                for key, value in _mapping(
                    payload.get("return_scope_ids")
                ).items()
            },
            version_rewrites=tuple(
                StateVersionPlacementRewrite.from_payload(item)
                for item in _mapping_items(
                    payload.get("version_rewrites")
                )
            ),
            reason_code=str(
                payload.get("reason_code") or "typed_identity_placement"
            ),
        )


@dataclass(frozen=True)
class IndexedStateVersion:
    version_id: StateVersionId
    valid_scope_id: str
    producer_call_id: str | None
    produced_handle: str | None
    computation_key: ComputationKey | None = None
    state_effect_key: StateEffectKey | None = None
    free_symbol_refs: tuple[str, ...] = ()
    previous_version_id: StateVersionId | None = None
    source_version_ids: tuple[StateVersionId, ...] = ()
    runtime_destination: RuntimeDestinationKey | None = None
    result_form: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id.to_payload(),
            "valid_scope_id": self.valid_scope_id,
            "producer_call_id": self.producer_call_id,
            "produced_handle": self.produced_handle,
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
            "free_symbol_refs": list(self.free_symbol_refs),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "source_version_ids": [
                item.to_payload() for item in self.source_version_ids
            ],
            "runtime_destination": (
                self.runtime_destination.to_payload()
                if self.runtime_destination is not None
                else None
            ),
            "result_form": self.result_form,
        }


@dataclass(frozen=True)
class StateAllocationRequest:
    call_id: str
    capability_id: str
    return_name: str
    object_id: MathObjectId | None
    state_kind: str
    runtime_type: str
    storage_scope_id: str
    valid_scope_id: str
    requested_write_mode: str
    identity_policy: str
    is_shareable: bool
    computation_key: ComputationKey
    state_effect_key: StateEffectKey
    source_version_ids: tuple[StateVersionId, ...] = ()
    free_symbol_refs: tuple[str, ...] = ()
    runtime_destination: RuntimeDestinationKey | None = None
    result_form: str | None = None


@dataclass(frozen=True)
class StateAllocationDecision:
    action: StateAllocationAction
    call_id: str
    return_name: str
    logical_state_key: LogicalStateKey | None
    selected_slot_id: StateSlotId | None
    selected_version_id: StateVersionId | None
    previous_version_id: StateVersionId | None
    canonical_producer_call_id: str | None
    runtime_destination: RuntimeDestinationKey | None
    reason_code: str
    conflict_code: str | None = None
    previous_producer_call_id: str | None = None
    transition_kind: Literal["direct", "dependency_refinement"] | None = None
    previous_free_symbol_refs: tuple[str, ...] = ()
    current_free_symbol_refs: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "call_id": self.call_id,
            "return_name": self.return_name,
            "logical_state_key": (
                self.logical_state_key.to_payload()
                if self.logical_state_key is not None
                else None
            ),
            "selected_slot_id": (
                self.selected_slot_id.to_payload()
                if self.selected_slot_id is not None
                else None
            ),
            "selected_version_id": (
                self.selected_version_id.to_payload()
                if self.selected_version_id is not None
                else None
            ),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "canonical_producer_call_id": self.canonical_producer_call_id,
            "runtime_destination": (
                self.runtime_destination.to_payload()
                if self.runtime_destination is not None
                else None
            ),
            "reason_code": self.reason_code,
            "conflict_code": self.conflict_code,
            "previous_producer_call_id": self.previous_producer_call_id,
            "transition_kind": self.transition_kind,
            "previous_free_symbol_refs": list(
                self.previous_free_symbol_refs
            ),
            "current_free_symbol_refs": list(
                self.current_free_symbol_refs
            ),
        }


@dataclass(frozen=True)
class IdentityShadowComparison:
    call_id: str
    return_name: str
    legacy_object_ref: str | None
    typed_object_ref: str | None
    legacy_slot_id: str | None
    typed_slot_id: str | None
    legacy_write_mode: str
    typed_action: StateAllocationAction
    matches: bool
    details: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "return_name": self.return_name,
            "legacy_object_ref": self.legacy_object_ref,
            "typed_object_ref": self.typed_object_ref,
            "legacy_slot_id": self.legacy_slot_id,
            "typed_slot_id": self.typed_slot_id,
            "legacy_write_mode": self.legacy_write_mode,
            "typed_action": self.typed_action,
            "matches": self.matches,
            "details": list(self.details),
        }


class _MathObjectLike(Protocol):
    object_id: str
    kind: str
    scope_id: str
    canonical_handle: str | None
    semantic_refs: tuple[str, ...]


class _StateSlotLike(Protocol):
    slot_id: str
    object_ref: str | None
    state_kind: str
    scope_id: str
    runtime_type: str
    canonical_handle: str | None
    valid_scope: str | None
    runtime_path: str | None
    write_history: Sequence[Any]
    free_symbol_refs: tuple[str, ...]


class _HandleRegistryLike(Protocol):
    entity_handles: set[str]
    answer_target_handles: Mapping[str, str]

    def ancestor_scopes(self, scope_id: str) -> tuple[str, ...]: ...


class MathObjectRegistry:
    """Canonical object-identity projection for planner/runtime state."""

    def __init__(self) -> None:
        self._by_ref: dict[str, MathObjectId] = {}
        self._by_semantic_ref: dict[str, set[MathObjectId]] = {}

    @classmethod
    def from_sources(
        cls,
        handle_registry: _HandleRegistryLike,
        *,
        math_objects: Iterable[_MathObjectLike] = (),
    ) -> "MathObjectRegistry":
        result = cls()
        for handle in sorted(handle_registry.entity_handles):
            result.register_handle(handle)
        for answer, target in handle_registry.answer_target_handles.items():
            object_id = result.register_handle(target)
            if object_id is not None:
                result._by_ref[answer] = object_id
        for item in math_objects:
            typed_object_id = getattr(item, "math_object_id", None)
            if isinstance(typed_object_id, MathObjectId):
                result._by_ref[item.object_id] = typed_object_id
                if item.canonical_handle:
                    result._by_ref[item.canonical_handle] = typed_object_id
                for ref in item.semantic_refs:
                    result._by_semantic_ref.setdefault(ref, set()).add(
                        typed_object_id
                    )
                continue
            primary_ref = item.canonical_handle or item.object_id
            object_id = result.register_handle(
                primary_ref,
                kind=item.kind,
                origin_scope_id=item.scope_id,
            )
            if object_id is None:
                continue
            result._by_ref[item.object_id] = object_id
            if item.canonical_handle:
                result._by_ref[item.canonical_handle] = object_id
            for ref in item.semantic_refs:
                result._by_semantic_ref.setdefault(ref, set()).add(object_id)
        return result

    def register_handle(
        self,
        handle: str,
        *,
        kind: str | None = None,
        origin_scope_id: str | None = None,
    ) -> MathObjectId | None:
        existing = self._by_ref.get(handle)
        if existing is not None:
            return existing
        parsed = parse_scoped_non_answer_handle(handle)
        resolved_kind = kind or object_semantic_kind_for_handle(handle)
        if resolved_kind is None:
            return None
        scope_id = origin_scope_id or (
            parsed[1] if parsed is not None else "problem"
        )
        object_id = MathObjectId(handle, resolved_kind, scope_id)
        self._by_ref[handle] = object_id
        if parsed is not None:
            self._by_semantic_ref.setdefault(parsed[2], set()).add(object_id)
        return object_id

    def resolve(self, ref: str) -> MathObjectId | None:
        direct = self._by_ref.get(ref)
        if direct is not None:
            return direct
        candidates = tuple(self._by_semantic_ref.get(ref, ()))
        if len(candidates) > 1:
            raise AmbiguousMathObjectReferenceError(ref, candidates)
        return candidates[0] if candidates else None


class ScopeVisibilityResolver:
    """One scope-visibility implementation shared by typed identity services."""

    def __init__(self, registry: _HandleRegistryLike) -> None:
        self.registry = registry

    def is_visible(
        self,
        valid_scope_id: str,
        *,
        consumer_scope_id: str,
    ) -> bool:
        return valid_scope_id in self.registry.ancestor_scopes(
            consumer_scope_id
        )

    def least_common_scope(self, scope_ids: Sequence[str]) -> str:
        if not scope_ids:
            return "problem"
        chains = [
            self.registry.ancestor_scopes(scope_id)
            for scope_id in scope_ids
        ]
        return next(
            (
                scope_id
                for scope_id in chains[0]
                if all(scope_id in chain for chain in chains[1:])
            ),
            "problem",
        )


class StateIdentityFactory:
    """Create typed identities and their legacy-compatible projections."""

    def __init__(self, objects: MathObjectRegistry) -> None:
        self.objects = objects

    def object_id(self, object_ref: str | None) -> MathObjectId | None:
        if object_ref is None:
            return None
        return self.objects.resolve(object_ref) or self.objects.register_handle(
            object_ref
        )

    def derived_computation_object_ref(
        self,
        *,
        computation_key: ComputationKey,
        semantic_role: str,
        runtime_type: str,
    ) -> str | None:
        """Create one scope-independent identity for a derived pure result."""
        object_kind = object_kind_for_runtime_type(runtime_type)
        if object_kind is None:
            return None
        payload = {
            "computation_key": computation_key.to_payload(),
            "semantic_role": semantic_role,
            "runtime_type": runtime_type,
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:24]
        # Object identity is scope-independent; StateSlot.valid_scope remains
        # the authority for visibility of the derived state.
        object_ref = f"{object_kind}:problem:derived_{digest}"
        self.objects.register_handle(
            object_ref,
            kind=object_kind,
            origin_scope_id="problem",
        )
        return object_ref

    def logical_key(
        self,
        *,
        object_ref: str | None,
        state_kind: str,
        runtime_type: str,
    ) -> LogicalStateKey | None:
        object_id = self.object_id(object_ref)
        if object_id is None:
            return None
        return LogicalStateKey(object_id, state_kind, runtime_type)

    def slot_id(
        self,
        logical_key: LogicalStateKey,
        *,
        storage_scope_id: str,
    ) -> StateSlotId:
        return StateSlotId(logical_key, storage_scope_id)

    @staticmethod
    def legacy_slot_alias(slot_id: StateSlotId) -> str:
        """Return the pre-B1 untyped key accepted for old Context payloads."""

        return (
            f"{slot_id.logical_key.object_id.value}."
            f"{slot_id.logical_key.state_kind}@{slot_id.storage_scope_id}"
        )


class StateIdentityIndex:
    """Attempt-local index of Context and in-flight typed StateVersions."""

    def __init__(self, visibility: ScopeVisibilityResolver) -> None:
        self.visibility = visibility
        self._versions_by_logical: dict[
            LogicalStateKey,
            list[IndexedStateVersion],
        ] = {}

    @classmethod
    def from_context(
        cls,
        *,
        state_slots: Iterable[_StateSlotLike],
        factory: StateIdentityFactory,
        visibility: ScopeVisibilityResolver,
    ) -> "StateIdentityIndex":
        result = cls(visibility)
        for slot in state_slots:
            # QuestionGoal slots are destinations, not materialized state.
            # Their answer handle may alias a ProblemIR MathObject, but ordinal
            # zero only exists once the object itself has a given state.
            if (
                slot.object_ref is not None
                and slot.object_ref.startswith("answer:")
            ):
                continue
            try:
                logical_key = getattr(slot, "logical_state_key", None) or (
                    factory.logical_key(
                        object_ref=slot.object_ref,
                        state_kind=slot.state_kind,
                        runtime_type=slot.runtime_type,
                    )
                )
            except AmbiguousMathObjectReferenceError as exc:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.context_identity_migration_failed: "
                    f"slot={slot.slot_id}, ref={exc.ref}"
                ) from exc
            if logical_key is None:
                if slot.object_ref is not None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.context_identity_migration_failed: "
                        f"slot={slot.slot_id} has no LogicalStateKey"
                    )
                continue
            typed_slot = getattr(slot, "typed_slot_id", None) or (
                factory.slot_id(
                    logical_key,
                    storage_scope_id=slot.scope_id,
                )
            )
            if typed_slot.logical_key != logical_key:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.context_identity_migration_failed: "
                    f"slot={slot.slot_id} typed key disagrees with object state"
                )
            history = tuple(slot.write_history)
            if not history:
                result.register(
                    IndexedStateVersion(
                        version_id=StateVersionId(typed_slot, 0),
                        valid_scope_id=slot.valid_scope or slot.scope_id,
                        producer_call_id=None,
                        produced_handle=slot.canonical_handle,
                        free_symbol_refs=slot.free_symbol_refs,
                        runtime_destination=RuntimeDestinationKey(
                            logical_key.object_id,
                            logical_key.state_kind,
                            logical_key.runtime_type,
                            slot.runtime_path,
                        ),
                    ),
                    legacy_slot_id=slot.slot_id,
                )
                continue
            for ordinal, write in enumerate(history, start=1):
                version_id = getattr(write, "version_id", None) or (
                    StateVersionId(typed_slot, ordinal)
                )
                write_free_symbol_refs = getattr(
                    write,
                    "free_symbol_refs",
                    None,
                )
                result.register(
                    IndexedStateVersion(
                        version_id=version_id,
                        valid_scope_id=(
                            getattr(write, "valid_scope_id", None)
                            or slot.valid_scope
                            or slot.scope_id
                        ),
                        producer_call_id=(
                            getattr(
                                write,
                                "canonical_producer_call_id",
                                None,
                            )
                            or getattr(write, "step_id", None)
                        ),
                        produced_handle=getattr(
                            write,
                            "produced_handle",
                            slot.canonical_handle,
                        ),
                        computation_key=getattr(
                            write,
                            "computation_key",
                            None,
                        ),
                        state_effect_key=getattr(
                            write,
                            "state_effect_key",
                            None,
                        ),
                        source_version_ids=getattr(
                            write,
                            "source_version_ids",
                            (),
                        ),
                        free_symbol_refs=(
                            tuple(write_free_symbol_refs)
                            if write_free_symbol_refs is not None
                            else slot.free_symbol_refs
                        ),
                        previous_version_id=getattr(
                            write,
                            "previous_version_id",
                            None,
                        ),
                        runtime_destination=(
                            getattr(write, "runtime_destination", None)
                            or RuntimeDestinationKey(
                                logical_key.object_id,
                                logical_key.state_kind,
                                logical_key.runtime_type,
                                slot.runtime_path,
                            )
                        ),
                        result_form=getattr(write, "result_form", None),
                    ),
                    legacy_slot_id=slot.slot_id,
                )
        return result

    def clone(self) -> "StateIdentityIndex":
        result = StateIdentityIndex(self.visibility)
        result._versions_by_logical = {
            key: list(items)
            for key, items in self._versions_by_logical.items()
        }
        return result

    def register(
        self,
        version: IndexedStateVersion,
        *,
        legacy_slot_id: str | None = None,
    ) -> None:
        del legacy_slot_id
        items = self._versions_by_logical.setdefault(
            version.version_id.slot_id.logical_key,
            [],
        )
        if version not in items:
            items.append(version)

    def update_version(
        self,
        version_id: StateVersionId,
        *,
        free_symbol_refs: tuple[str, ...],
        source_version_ids: tuple[StateVersionId, ...],
    ) -> None:
        """Refine metadata after cross-return dependencies are available."""

        def updated(
            items: list[IndexedStateVersion],
        ) -> list[IndexedStateVersion]:
            return [
                replace(
                    item,
                    free_symbol_refs=free_symbol_refs,
                    source_version_ids=source_version_ids,
                )
                if item.version_id == version_id
                else item
                for item in items
            ]

        logical_key = version_id.slot_id.logical_key
        if logical_key in self._versions_by_logical:
            self._versions_by_logical[logical_key] = updated(
                self._versions_by_logical[logical_key]
            )

    def versions_for(
        self,
        logical_key: LogicalStateKey,
    ) -> tuple[IndexedStateVersion, ...]:
        return tuple(self._versions_by_logical.get(logical_key, ()))

    def all_versions(self) -> tuple[IndexedStateVersion, ...]:
        """Return the authoritative Context/in-flight version snapshot."""

        return tuple(
            version
            for versions in self._versions_by_logical.values()
            for version in versions
        )

    def version(
        self,
        version_id: StateVersionId,
    ) -> IndexedStateVersion | None:
        return next(
            (
                item
                for item in self._versions_by_logical.get(
                    version_id.slot_id.logical_key,
                    (),
                )
                if item.version_id == version_id
            ),
            None,
        )

    def is_same_or_descendant(
        self,
        candidate_id: StateVersionId,
        ancestor_id: StateVersionId,
    ) -> bool:
        """Return whether a state version transitively consumes an ancestor."""

        pending = [candidate_id]
        visited: set[StateVersionId] = set()
        while pending:
            current = pending.pop()
            if current == ancestor_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            version = self.version(current)
            if version is not None:
                pending.extend(version.source_version_ids)
        return False

    def latest_visible(
        self,
        logical_key: LogicalStateKey,
        *,
        consumer_scope_id: str,
    ) -> IndexedStateVersion | None:
        return self._latest_visible(
            self._versions_by_logical.get(logical_key, ()),
            consumer_scope_id=consumer_scope_id,
        )

    def next_ordinal(self, slot_id: StateSlotId) -> int:
        return (
            max(
                (
                    item.version_id.ordinal
                    for item in self._versions_by_logical.get(
                        slot_id.logical_key,
                        (),
                    )
                    if item.version_id.slot_id == slot_id
                ),
                default=0,
            )
            + 1
        )

    def _latest_visible(
        self,
        versions: Iterable[IndexedStateVersion],
        *,
        consumer_scope_id: str,
    ) -> IndexedStateVersion | None:
        visible = [
            item
            for item in versions
            if self.visibility.is_visible(
                item.valid_scope_id,
                consumer_scope_id=consumer_scope_id,
            )
        ]
        if not visible:
            return None
        ancestors = self.visibility.registry.ancestor_scopes(
            consumer_scope_id
        )
        scope_rank = {
            scope_id: rank for rank, scope_id in enumerate(ancestors)
        }
        closest_rank = min(
            scope_rank.get(item.valid_scope_id, len(ancestors))
            for item in visible
        )
        closest = tuple(
            item
            for item in visible
            if scope_rank.get(item.valid_scope_id, len(ancestors))
            == closest_rank
        )
        latest_by_slot: dict[StateSlotId, IndexedStateVersion] = {}
        for item in closest:
            previous = latest_by_slot.get(item.version_id.slot_id)
            if (
                previous is None
                or item.version_id.ordinal > previous.version_id.ordinal
            ):
                latest_by_slot[item.version_id.slot_id] = item
        maximal = tuple(
            candidate
            for candidate in latest_by_slot.values()
            if not any(
                other.version_id != candidate.version_id
                and self.is_same_or_descendant(
                    other.version_id,
                    candidate.version_id,
                )
                for other in latest_by_slot.values()
            )
        )
        if len(maximal) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.state_identity_incomplete: "
                f"logical_key={visible[0].logical_state_key.to_payload()}, "
                f"consumer_scope={consumer_scope_id}, "
                "reason=ambiguous_latest_visible"
            )
        return maximal[0]


class StateAllocationService:
    """Classify one Functional return against typed Context/in-flight state."""

    def allocate(
        self,
        request: StateAllocationRequest,
        index: StateIdentityIndex,
    ) -> StateAllocationDecision:
        if request.object_id is None:
            return StateAllocationDecision(
                action="call_local_value",
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=None,
                selected_slot_id=None,
                selected_version_id=None,
                previous_version_id=None,
                canonical_producer_call_id=None,
                runtime_destination=None,
                reason_code="return_has_no_math_object",
            )

        logical_key = LogicalStateKey(
            request.object_id,
            request.state_kind,
            request.runtime_type,
        )
        requested_slot = StateSlotId(
            logical_key,
            request.storage_scope_id,
        )
        visible = index.latest_visible(
            logical_key,
            consumer_scope_id=request.storage_scope_id,
        )
        all_versions = index.versions_for(logical_key)
        reusable = next(
            (
                item
                for item in reversed(all_versions)
                if (
                    request.is_shareable
                    or item.producer_call_id == request.call_id
                )
                and item.computation_key == request.computation_key
                and item.state_effect_key == request.state_effect_key
                and index.visibility.is_visible(
                    item.valid_scope_id,
                    consumer_scope_id=request.storage_scope_id,
                )
                and (
                    request.result_form is None
                    or item.result_form is None
                    or request.result_form == item.result_form
                )
            ),
            None,
        )
        if reusable is not None:
            return StateAllocationDecision(
                action="reuse",
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=logical_key,
                selected_slot_id=reusable.version_id.slot_id,
                selected_version_id=reusable.version_id,
                previous_version_id=None,
                canonical_producer_call_id=reusable.producer_call_id,
                runtime_destination=(
                    reusable.runtime_destination
                    or request.runtime_destination
                ),
                reason_code="same_computation_and_state_effect",
            )

        same_state_source_ids = tuple(
            version_id
            for version_id in request.source_version_ids
            if version_id.slot_id.logical_key == logical_key
        )
        explicit_sources = tuple(
            item
            for item in all_versions
            if item.version_id in same_state_source_ids
        )
        maximal_explicit_sources = tuple(
            candidate
            for candidate in explicit_sources
            if not any(
                other.version_id != candidate.version_id
                and index.is_same_or_descendant(
                    other.version_id,
                    candidate.version_id,
                )
                for other in explicit_sources
            )
        )
        if len(maximal_explicit_sources) > 1:
            return self._conflict(
                request,
                logical_key,
                requested_slot,
                "state.transition_source_mismatch",
                "multiple_incomparable_explicit_state_sources",
            )
        explicit_previous = (
            maximal_explicit_sources[0]
            if maximal_explicit_sources
            else None
        )

        if request.requested_write_mode == "transition":
            previous = explicit_previous or visible
            if previous is None:
                version_id = StateVersionId(
                    requested_slot,
                    index.next_ordinal(requested_slot),
                )
                return StateAllocationDecision(
                    action="create",
                    call_id=request.call_id,
                    return_name=request.return_name,
                    logical_state_key=logical_key,
                    selected_slot_id=requested_slot,
                    selected_version_id=version_id,
                    previous_version_id=None,
                    canonical_producer_call_id=request.call_id,
                    runtime_destination=request.runtime_destination,
                    reason_code="first_materialized_state_from_object_identity",
                )
            if (
                same_state_source_ids
                and not explicit_sources
                and previous.version_id not in same_state_source_ids
            ):
                return self._conflict(
                    request,
                    logical_key,
                    requested_slot,
                    "state.transition_source_mismatch",
                    "transition_does_not_depend_on_latest_visible_version",
                )
            version_id = StateVersionId(
                requested_slot,
                index.next_ordinal(requested_slot),
            )
            return StateAllocationDecision(
                action="transition",
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=logical_key,
                selected_slot_id=requested_slot,
                selected_version_id=version_id,
                previous_version_id=previous.version_id,
                canonical_producer_call_id=request.call_id,
                runtime_destination=request.runtime_destination,
                reason_code="declared_visible_state_transition",
                previous_producer_call_id=previous.producer_call_id,
                transition_kind="direct",
                previous_free_symbol_refs=previous.free_symbol_refs,
                current_free_symbol_refs=request.free_symbol_refs,
            )

        if (
            explicit_previous is not None
            and set(request.free_symbol_refs).issubset(
                explicit_previous.free_symbol_refs
            )
        ):
            version_id = StateVersionId(
                requested_slot,
                index.next_ordinal(requested_slot),
            )
            return StateAllocationDecision(
                action="transition",
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=logical_key,
                selected_slot_id=requested_slot,
                selected_version_id=version_id,
                previous_version_id=explicit_previous.version_id,
                canonical_producer_call_id=request.call_id,
                runtime_destination=request.runtime_destination,
                reason_code=(
                    "dependency_refines_visible_state"
                    if visible is not None
                    and visible.version_id == explicit_previous.version_id
                    else "explicit_dependency_refines_state"
                ),
                previous_producer_call_id=explicit_previous.producer_call_id,
                transition_kind="dependency_refinement",
                previous_free_symbol_refs=explicit_previous.free_symbol_refs,
                current_free_symbol_refs=request.free_symbol_refs,
            )

        if visible is None:
            action: StateAllocationAction = (
                "isolated" if all_versions else "create"
            )
            version_id = StateVersionId(
                requested_slot,
                index.next_ordinal(requested_slot),
            )
            return StateAllocationDecision(
                action=action,
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=logical_key,
                selected_slot_id=requested_slot,
                selected_version_id=version_id,
                previous_version_id=None,
                canonical_producer_call_id=request.call_id,
                runtime_destination=request.runtime_destination,
                reason_code=(
                    "same_logical_state_not_visible"
                    if action == "isolated"
                    else "no_existing_logical_state"
                ),
            )

        if (
            visible.version_id in request.source_version_ids
            and set(request.free_symbol_refs).issubset(
                visible.free_symbol_refs
            )
        ):
            version_id = StateVersionId(
                requested_slot,
                index.next_ordinal(requested_slot),
            )
            return StateAllocationDecision(
                action="transition",
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=logical_key,
                selected_slot_id=requested_slot,
                selected_version_id=version_id,
                previous_version_id=visible.version_id,
                canonical_producer_call_id=request.call_id,
                runtime_destination=request.runtime_destination,
                reason_code="dependency_refines_visible_state",
                previous_producer_call_id=visible.producer_call_id,
                transition_kind="dependency_refinement",
                previous_free_symbol_refs=visible.free_symbol_refs,
                current_free_symbol_refs=request.free_symbol_refs,
            )

        if (
            request.identity_policy == "target_object"
            and set(request.free_symbol_refs).issubset(
                visible.free_symbol_refs
            )
            and visible.state_effect_key == request.state_effect_key
            and _computation_refines(
                visible.computation_key,
                request.computation_key,
                index=index,
            )
        ):
            version_id = StateVersionId(
                requested_slot,
                index.next_ordinal(requested_slot),
            )
            return StateAllocationDecision(
                action="transition",
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=logical_key,
                selected_slot_id=requested_slot,
                selected_version_id=version_id,
                previous_version_id=visible.version_id,
                canonical_producer_call_id=request.call_id,
                runtime_destination=request.runtime_destination,
                reason_code="recomputed_from_descendant_inputs",
                previous_producer_call_id=visible.producer_call_id,
                transition_kind="dependency_refinement",
                previous_free_symbol_refs=visible.free_symbol_refs,
                current_free_symbol_refs=request.free_symbol_refs,
            )

        if (
            requested_slot != visible.version_id.slot_id
            and not set(request.free_symbol_refs).issubset(
                visible.free_symbol_refs
            )
        ):
            version_id = StateVersionId(
                requested_slot,
                index.next_ordinal(requested_slot),
            )
            return StateAllocationDecision(
                action="isolated",
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=logical_key,
                selected_slot_id=requested_slot,
                selected_version_id=version_id,
                previous_version_id=None,
                canonical_producer_call_id=request.call_id,
                runtime_destination=request.runtime_destination,
                reason_code="child_scope_state_specialization",
            )

        if (
            requested_slot != visible.version_id.slot_id
            and set(request.free_symbol_refs) == set(visible.free_symbol_refs)
        ):
            version_id = StateVersionId(
                requested_slot,
                index.next_ordinal(requested_slot),
            )
            return StateAllocationDecision(
                action="isolated",
                call_id=request.call_id,
                return_name=request.return_name,
                logical_state_key=logical_key,
                selected_slot_id=requested_slot,
                selected_version_id=version_id,
                previous_version_id=None,
                canonical_producer_call_id=request.call_id,
                runtime_destination=request.runtime_destination,
                reason_code="independent_same_form_state_in_child_scope",
            )

        return self._conflict(
            request,
            logical_key,
            requested_slot,
            (
                "state.transition_dependency_unproven"
                if request.identity_policy == "target_object"
                and set(request.free_symbol_refs).issubset(
                    visible.free_symbol_refs
                )
                else "state.logical_duplicate_writer"
            ),
            (
                "target_object_update_has_no_version_ancestry"
                if request.identity_policy == "target_object"
                and set(request.free_symbol_refs).issubset(
                    visible.free_symbol_refs
                )
                else "visible_logical_state_has_different_computation"
            ),
            previous=visible,
        )

    @staticmethod
    def indexed_version(
        request: StateAllocationRequest,
        decision: StateAllocationDecision,
        *,
        produced_handle: str | None,
    ) -> IndexedStateVersion | None:
        if (
            decision.action in {"reuse", "conflict", "call_local_value"}
            or decision.selected_version_id is None
        ):
            return None
        return IndexedStateVersion(
            version_id=decision.selected_version_id,
            valid_scope_id=request.valid_scope_id,
            producer_call_id=request.call_id,
            produced_handle=produced_handle,
            computation_key=request.computation_key,
            state_effect_key=request.state_effect_key,
            free_symbol_refs=request.free_symbol_refs,
            source_version_ids=request.source_version_ids,
            runtime_destination=request.runtime_destination,
            result_form=request.result_form,
        )

    @staticmethod
    def _conflict(
        request: StateAllocationRequest,
        logical_key: LogicalStateKey,
        slot_id: StateSlotId,
        conflict_code: str,
        reason_code: str,
        *,
        previous: IndexedStateVersion | None = None,
    ) -> StateAllocationDecision:
        return StateAllocationDecision(
            action="conflict",
            call_id=request.call_id,
            return_name=request.return_name,
            logical_state_key=logical_key,
            selected_slot_id=slot_id,
            selected_version_id=None,
            previous_version_id=(
                previous.version_id if previous is not None else None
            ),
            canonical_producer_call_id=None,
            runtime_destination=request.runtime_destination,
            reason_code=reason_code,
            conflict_code=conflict_code,
            previous_producer_call_id=(
                previous.producer_call_id if previous is not None else None
            ),
            previous_free_symbol_refs=(
                previous.free_symbol_refs if previous is not None else ()
            ),
            current_free_symbol_refs=request.free_symbol_refs,
        )


def _computation_refines(
    previous: ComputationKey | None,
    current: ComputationKey,
    *,
    index: StateIdentityIndex,
) -> bool:
    """Prove that a repeated pure computation consumes descendant inputs."""

    if previous is None or previous.capability_id != current.capability_id:
        return False
    previous_bindings = {
        (item.arg_name, item.item_index): item
        for item in previous.arg_bindings
    }
    current_bindings = {
        (item.arg_name, item.item_index): item
        for item in current.arg_bindings
    }
    if previous_bindings.keys() != current_bindings.keys():
        return False
    for key, previous_binding in previous_bindings.items():
        current_binding = current_bindings[key]
        if previous_binding.version_id is not None:
            if (
                current_binding.version_id is None
                or (
                    current_binding.version_id.slot_id.logical_key
                    != previous_binding.version_id.slot_id.logical_key
                )
                or not (
                index.is_same_or_descendant(
                    current_binding.version_id,
                    previous_binding.version_id,
                )
                )
            ):
                return False
            continue
        if current_binding.version_id is not None:
            return False
        if (
            previous_binding.condition_id != current_binding.condition_id
            or previous_binding.object_id != current_binding.object_id
            or previous_binding.call_result_id
            != current_binding.call_result_id
        ):
            return False
    return True


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("typed identity payload must be an object")
    return value


def _mapping_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


__all__ = [
    "ArgVersionBinding",
    "ComputationKey",
    "FunctionalCallIdentityKey",
    "IdentityShadowComparison",
    "IndexedStateVersion",
    "LogicalReturnEffect",
    "LogicalStateKey",
    "MathObjectId",
    "MathObjectRegistry",
    "RuntimeDestinationKey",
    "ScopeVisibilityResolver",
    "StateAllocationAction",
    "StateAllocationDecision",
    "StateAllocationRequest",
    "StateAllocationService",
    "StateEffectKey",
    "StateIdentityFactory",
    "StateIdentityIndex",
    "StateIdentityMode",
    "StatePlacementMode",
    "StateSlotId",
    "StateVersionPlacementRewrite",
    "StateVersionId",
    "TypedCallPlacementDecision",
]
