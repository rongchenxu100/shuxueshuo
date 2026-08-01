"""Typed state-version reads shared by Functional runtime consumers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, Sequence

from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    MathObjectRegistry,
    ScopeVisibilityResolver,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateDependency,
    ProjectedStateWrite,
    StateWriteProvenance,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import (
    StateSemanticLineage,
    state_kind_for_runtime_type,
)

FunctionalConsumerIdentityMode = Literal["shadow", "authoritative"]


@dataclass(frozen=True)
class RuntimeStateVersionBinding:
    """One semantic StateVersion and its optional physical runtime binding."""

    version_id: StateVersionId
    logical_state_key: LogicalStateKey
    math_object_id: MathObjectId
    runtime_type: str
    valid_scope_id: str
    canonical_producer_call_id: str | None
    runtime_path: str | None
    produced_handle: str | None
    lineage: StateSemanticLineage = StateSemanticLineage()
    previous_version_id: StateVersionId | None = None
    source_version_ids: tuple[StateVersionId, ...] = ()
    free_symbol_refs: tuple[str, ...] = ()
    free_symbol_ids: tuple[MathObjectId, ...] = ()
    result_form: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id.to_payload(),
            "logical_state_key": self.logical_state_key.to_payload(),
            "math_object_id": self.math_object_id.to_payload(),
            "runtime_type": self.runtime_type,
            "valid_scope_id": self.valid_scope_id,
            "canonical_producer_call_id": (
                self.canonical_producer_call_id
            ),
            "runtime_path": self.runtime_path,
            "produced_handle": self.produced_handle,
            "lineage": self.lineage.to_payload(),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "source_version_ids": [
                item.to_payload() for item in self.source_version_ids
            ],
            "free_symbol_refs": list(self.free_symbol_refs),
            "free_symbol_ids": [
                item.to_payload() for item in self.free_symbol_ids
            ],
            "result_form": self.result_form,
        }


@dataclass(frozen=True)
class FunctionalRuntimeConsumerDecision:
    consumer: str
    action: str
    version_id: StateVersionId | None
    math_object_id: MathObjectId | None
    runtime_path: str | None
    reason_code: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "action": self.action,
            "version_id": (
                self.version_id.to_payload()
                if self.version_id is not None
                else None
            ),
            "math_object_id": (
                self.math_object_id.to_payload()
                if self.math_object_id is not None
                else None
            ),
            "runtime_path": self.runtime_path,
            "reason_code": self.reason_code,
        }


class FunctionalStateReadIndex:
    """Authoritative typed lookup for Context and in-flight runtime states."""

    def __init__(
        self,
        *,
        handle_registry: CanonicalHandleRegistry,
        mode: FunctionalConsumerIdentityMode = "authoritative",
    ) -> None:
        self.handle_registry = handle_registry
        self.mode = mode
        self.visibility = ScopeVisibilityResolver(handle_registry)
        self._by_version: dict[
            StateVersionId,
            RuntimeStateVersionBinding,
        ] = {}
        self._logical_key_by_runtime_path: dict[str, LogicalStateKey] = {}
        self.decisions: list[FunctionalRuntimeConsumerDecision] = []
        self.mismatches: list[dict[str, Any]] = []
        self.legacy_identity_fallback_count = 0

    @classmethod
    def from_sources(
        cls,
        *,
        handle_registry: CanonicalHandleRegistry,
        mode: FunctionalConsumerIdentityMode = "authoritative",
        planner_state_context: Any | None = None,
        projected_state_writes: Sequence[ProjectedStateWrite] = (),
        projected_state_dependencies: Sequence[
            ProjectedStateDependency
        ] = (),
        state_write_provenance: Sequence[StateWriteProvenance] = (),
        runtime_bindings: Mapping[str, Any] | None = None,
        known_state_versions: Sequence[Any] = (),
    ) -> "FunctionalStateReadIndex":
        result = cls(handle_registry=handle_registry, mode=mode)
        if planner_state_context is not None:
            result._register_context(planner_state_context)
        for version in known_state_versions:
            result._register_indexed_version(version)
        result._register_initial_runtime_states(runtime_bindings or {})
        for dependency in projected_state_dependencies:
            result._register_dependency(
                dependency,
                runtime_bindings=runtime_bindings or {},
            )
        for write in projected_state_writes:
            result._register_projected_write(
                write,
                runtime_bindings=runtime_bindings or {},
            )
        for write in state_write_provenance:
            result._register_runtime_write(
                write,
                runtime_bindings=runtime_bindings or {},
                authoritative_handles=frozenset(
                    item.produced_handle
                    for item in projected_state_writes
                    if item.write_mode != "value"
                ),
            )
        return result

    def _register_initial_runtime_states(
        self,
        runtime_bindings: Mapping[str, Any],
    ) -> None:
        """Materialize typed ordinal-0 states at the runtime load boundary."""

        object_registry = MathObjectRegistry.from_sources(
            self.handle_registry
        )
        identity_only_types = frozenset(
            {"PointRef", "Symbol", "Function"}
        )
        for handle, binding in runtime_bindings.items():
            if getattr(binding, "source", None) != "entity":
                continue
            runtime_type = getattr(binding, "value_type", None)
            runtime_path = getattr(binding, "path", None)
            if (
                not isinstance(runtime_type, str)
                or runtime_type in identity_only_types
                or not isinstance(runtime_path, str)
            ):
                continue
            object_id = object_registry.resolve(handle)
            if object_id is None:
                self._incomplete(
                    "planner.context_identity_migration_failed",
                    f"initial_handle={handle}",
                )
                continue
            logical_key = LogicalStateKey(
                object_id,
                state_kind_for_runtime_type(runtime_type),
                runtime_type,
            )
            try:
                path_scope = ContextPath.parse(runtime_path).scope_id
            except ValueError:
                path_scope = object_id.origin_scope_id
            valid_scope = (
                object_id.origin_scope_id
                if self.visibility.is_visible(
                    object_id.origin_scope_id,
                    consumer_scope_id=path_scope,
                )
                else path_scope
            )
            self.register(
                RuntimeStateVersionBinding(
                    version_id=StateVersionId(
                        StateSlotId(
                            logical_key,
                            object_id.origin_scope_id,
                        ),
                        0,
                    ),
                    logical_state_key=logical_key,
                    math_object_id=object_id,
                    runtime_type=runtime_type,
                    valid_scope_id=valid_scope,
                    canonical_producer_call_id=None,
                    runtime_path=runtime_path,
                    produced_handle=handle,
                )
            )

    def register(self, binding: RuntimeStateVersionBinding) -> None:
        if binding.runtime_path is not None:
            existing_key = self._logical_key_by_runtime_path.get(
                binding.runtime_path
            )
            if (
                existing_key is not None
                and existing_key != binding.logical_state_key
            ):
                self._fail(
                    "planner.runtime_state_binding_drift",
                    (
                        f"runtime_path={binding.runtime_path}, "
                        "reason=logical_state_collision, "
                        f"existing={existing_key.to_payload()}, "
                        f"incoming={binding.logical_state_key.to_payload()}"
                    ),
                )
            self._logical_key_by_runtime_path[
                binding.runtime_path
            ] = binding.logical_state_key
        existing = self._by_version.get(binding.version_id)
        if existing is None:
            self._by_version[binding.version_id] = binding
            return
        self._by_version[binding.version_id] = self._merge(
            existing,
            binding,
        )

    def version(
        self,
        version_id: StateVersionId,
    ) -> RuntimeStateVersionBinding | None:
        return self._by_version.get(version_id)

    def all_versions(self) -> tuple[RuntimeStateVersionBinding, ...]:
        return tuple(
            sorted(
                self._by_version.values(),
                key=lambda item: (
                    item.logical_state_key.object_id.value,
                    item.logical_state_key.state_kind,
                    item.logical_state_key.runtime_type,
                    item.version_id.ordinal,
                    item.valid_scope_id,
                ),
            )
        )

    def latest_visible(
        self,
        logical_key: LogicalStateKey,
        *,
        consumer_scope_id: str,
    ) -> RuntimeStateVersionBinding | None:
        candidates = tuple(
            item
            for item in self._by_version.values()
            if item.logical_state_key == logical_key
            and self.visibility.is_visible(
                item.valid_scope_id,
                consumer_scope_id=consumer_scope_id,
            )
        )
        selected = self._select_latest_visible(
            candidates,
            consumer_scope_id=consumer_scope_id,
        )
        self._record(
            consumer=consumer_scope_id,
            action="latest_visible",
            binding=selected,
            reason_code=(
                "typed_latest_visible"
                if selected is not None
                else "typed_state_not_visible"
            ),
        )
        return selected

    def _select_latest_visible(
        self,
        candidates: Sequence[RuntimeStateVersionBinding],
        *,
        consumer_scope_id: str,
    ) -> RuntimeStateVersionBinding | None:
        if not candidates:
            return None
        ancestors = self.handle_registry.ancestor_scopes(
            consumer_scope_id
        )
        scope_rank = {
            scope_id: rank for rank, scope_id in enumerate(ancestors)
        }
        closest_rank = min(
            scope_rank.get(item.valid_scope_id, len(ancestors))
            for item in candidates
        )
        closest = tuple(
            item
            for item in candidates
            if scope_rank.get(item.valid_scope_id, len(ancestors))
            == closest_rank
        )
        latest_by_slot: dict[
            StateSlotId,
            RuntimeStateVersionBinding,
        ] = {}
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
                and self._is_same_state_descendant(
                    other.version_id,
                    candidate.version_id,
                )
                for other in latest_by_slot.values()
            )
        )
        if len(maximal) != 1:
            self._fail(
                "planner.runtime_state_binding_drift",
                (
                    f"logical_key={candidates[0].logical_state_key.to_payload()}, "
                    f"consumer_scope={consumer_scope_id}, "
                    "reason=ambiguous_latest_visible, "
                    f"versions={[item.version_id.to_payload() for item in maximal]}"
                ),
            )
        return maximal[0]

    def _is_same_state_descendant(
        self,
        candidate_id: StateVersionId,
        ancestor_id: StateVersionId,
    ) -> bool:
        pending = [candidate_id]
        seen: set[StateVersionId] = set()
        while pending:
            current = pending.pop()
            if current == ancestor_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            binding = self._by_version.get(current)
            if binding is None:
                continue
            if binding.previous_version_id is not None:
                pending.append(binding.previous_version_id)
            pending.extend(
                source
                for source in binding.source_version_ids
                if source.slot_id.logical_key
                == ancestor_id.slot_id.logical_key
            )
        return False

    def visible_versions_for_object(
        self,
        object_id: MathObjectId,
        *,
        consumer_scope_id: str,
        runtime_type: str | None = None,
        state_kind: str | None = None,
    ) -> tuple[RuntimeStateVersionBinding, ...]:
        return tuple(
            item
            for item in self.all_versions()
            if item.math_object_id == object_id
            and (runtime_type is None or item.runtime_type == runtime_type)
            and (
                state_kind is None
                or item.logical_state_key.state_kind == state_kind
            )
            and self.visibility.is_visible(
                item.valid_scope_id,
                consumer_scope_id=consumer_scope_id,
            )
        )

    def runtime_path_for_version(
        self,
        version_id: StateVersionId,
        *,
        consumer_scope_id: str,
        consumer: str = "functional_runtime",
    ) -> str:
        binding = self.version(version_id)
        if binding is None:
            self._fail(
                "planner.runtime_state_version_unresolved",
                f"version={version_id.to_payload()}",
            )
        assert binding is not None
        if not self.visibility.is_visible(
            binding.valid_scope_id,
            consumer_scope_id=consumer_scope_id,
        ):
            self._fail(
                "planner.runtime_state_visibility_drift",
                (
                    f"version={version_id.to_payload()}, "
                    f"valid_scope={binding.valid_scope_id}, "
                    f"consumer_scope={consumer_scope_id}"
                ),
            )
        if binding.runtime_path is None:
            self._fail(
                "planner.runtime_state_binding_drift",
                f"version={version_id.to_payload()} has no runtime path",
            )
        self._record(
            consumer=consumer,
            action="runtime_path_for_version",
            binding=binding,
            reason_code="typed_exact_version",
        )
        assert binding.runtime_path is not None
        return binding.runtime_path

    def require_version(
        self,
        version_id: StateVersionId,
        *,
        consumer_scope_id: str,
        consumer: str = "functional_runtime",
        require_runtime_path: bool = False,
    ) -> RuntimeStateVersionBinding:
        binding = self.version(version_id)
        if binding is None:
            self._fail(
                "planner.runtime_state_version_unresolved",
                f"version={version_id.to_payload()}",
            )
        assert binding is not None
        if not self.visibility.is_visible(
            binding.valid_scope_id,
            consumer_scope_id=consumer_scope_id,
        ):
            self._fail(
                "planner.runtime_state_visibility_drift",
                (
                    f"version={version_id.to_payload()}, "
                    f"valid_scope={binding.valid_scope_id}, "
                    f"consumer_scope={consumer_scope_id}"
                ),
            )
        if require_runtime_path and binding.runtime_path is None:
            self._fail(
                "planner.runtime_state_binding_drift",
                f"version={version_id.to_payload()} has no runtime path",
            )
        self._record(
            consumer=consumer,
            action="exact_version",
            binding=binding,
            reason_code="typed_exact_version",
        )
        return binding

    def _register_context(self, context: Any) -> None:
        for slot in context.state.state_slots:
            logical_key = getattr(slot, "logical_state_key", None)
            typed_slot_id = getattr(slot, "typed_slot_id", None)
            if logical_key is None or typed_slot_id is None:
                if slot.object_ref is None:
                    continue
                self._incomplete(
                    "planner.context_identity_migration_failed",
                    f"slot={slot.slot_id}",
                )
                continue
            if (
                logical_key.object_id.kind == "answer"
                or (
                    isinstance(slot.object_ref, str)
                    and slot.object_ref.startswith("answer:")
                )
                or slot.canonical_handle.startswith("answer:")
            ):
                continue
            history = tuple(slot.write_history)
            if not history:
                version_id = (
                    getattr(slot, "latest_version_id", None)
                    or StateVersionId(typed_slot_id, 0)
                )
                self.register(
                    RuntimeStateVersionBinding(
                        version_id=version_id,
                        logical_state_key=logical_key,
                        math_object_id=logical_key.object_id,
                        runtime_type=logical_key.runtime_type,
                        valid_scope_id=slot.valid_scope or slot.scope_id,
                        canonical_producer_call_id=None,
                        runtime_path=(
                            getattr(
                                slot,
                                "runtime_destination_key",
                                None,
                            ).runtime_path
                            if getattr(
                                slot,
                                "runtime_destination_key",
                                None,
                            )
                            is not None
                            else slot.runtime_path
                        ),
                        produced_handle=slot.canonical_handle,
                        lineage=slot.lineage,
                        free_symbol_refs=slot.free_symbol_refs,
                        free_symbol_ids=slot.free_symbol_ids,
                    )
                )
                continue
            for ordinal, write in enumerate(history, start=1):
                version_id = getattr(write, "version_id", None)
                if version_id is None:
                    self._incomplete(
                        "planner.context_identity_migration_failed",
                        f"slot={slot.slot_id}, write={write.step_id}",
                    )
                    version_id = StateVersionId(typed_slot_id, ordinal)
                destination = getattr(write, "runtime_destination", None)
                self.register(
                    RuntimeStateVersionBinding(
                        version_id=version_id,
                        logical_state_key=logical_key,
                        math_object_id=logical_key.object_id,
                        runtime_type=logical_key.runtime_type,
                        valid_scope_id=(
                            getattr(write, "valid_scope_id", None)
                            or slot.valid_scope
                            or slot.scope_id
                        ),
                        canonical_producer_call_id=getattr(
                            write,
                            "canonical_producer_call_id",
                            None,
                        ),
                        runtime_path=(
                            destination.runtime_path
                            if destination is not None
                            else slot.runtime_path
                        ),
                        produced_handle=write.produced_handle,
                        lineage=write.lineage,
                        previous_version_id=getattr(
                            write,
                            "previous_version_id",
                            None,
                        ),
                        source_version_ids=getattr(
                            write,
                            "source_version_ids",
                            (),
                        ),
                        free_symbol_refs=getattr(
                            write,
                            "free_symbol_refs",
                            (),
                        ),
                        free_symbol_ids=getattr(
                            write,
                            "free_symbol_ids",
                            (),
                        ),
                        result_form=getattr(write, "result_form", None),
                    )
                )

    def _register_indexed_version(self, version: Any) -> None:
        version_id = getattr(version, "version_id", None)
        logical_key = (
            version_id.slot_id.logical_key
            if version_id is not None
            else None
        )
        valid_scope_id = getattr(version, "valid_scope_id", None)
        if version_id is None or logical_key is None or valid_scope_id is None:
            self._incomplete(
                "planner.context_identity_migration_failed",
                "known StateVersion lacks typed identity or valid scope",
            )
            return
        destination = getattr(version, "runtime_destination", None)
        self.register(
            RuntimeStateVersionBinding(
                version_id=version_id,
                logical_state_key=logical_key,
                math_object_id=logical_key.object_id,
                runtime_type=logical_key.runtime_type,
                valid_scope_id=valid_scope_id,
                canonical_producer_call_id=getattr(
                    version,
                    "producer_call_id",
                    None,
                ),
                runtime_path=(
                    destination.runtime_path
                    if destination is not None
                    else None
                ),
                produced_handle=getattr(version, "produced_handle", None),
                lineage=getattr(
                    version,
                    "lineage",
                    StateSemanticLineage(),
                ),
                previous_version_id=getattr(
                    version,
                    "previous_version_id",
                    None,
                ),
                source_version_ids=tuple(
                    getattr(version, "source_version_ids", ()) or ()
                ),
                free_symbol_refs=tuple(
                    getattr(version, "free_symbol_refs", ()) or ()
                ),
                free_symbol_ids=tuple(
                    getattr(version, "free_symbol_ids", ()) or ()
                ),
                result_form=getattr(version, "result_form", None),
            )
        )

    def _register_dependency(
        self,
        dependency: ProjectedStateDependency,
        *,
        runtime_bindings: Mapping[str, Any],
    ) -> None:
        version_id = dependency.state_version_id
        if version_id is None:
            if dependency.runtime_type is not None:
                self._incomplete(
                    "planner.state_dependency_version_unresolved",
                    (
                        f"step={dependency.step_id}, "
                        f"arg={dependency.arg_name or 'unknown'}"
                    ),
                )
            return
        logical_key = version_id.slot_id.logical_key
        self.register(
            RuntimeStateVersionBinding(
                version_id=version_id,
                logical_state_key=logical_key,
                math_object_id=logical_key.object_id,
                runtime_type=logical_key.runtime_type,
                valid_scope_id=version_id.slot_id.storage_scope_id,
                canonical_producer_call_id=dependency.source_step_id,
                runtime_path=_runtime_path(
                    dependency.produced_handle,
                    runtime_bindings,
                ),
                produced_handle=dependency.produced_handle,
            )
        )

    def _register_projected_write(
        self,
        write: ProjectedStateWrite,
        *,
        runtime_bindings: Mapping[str, Any],
    ) -> None:
        version_id = write.selected_version_id
        logical_key = write.logical_state_key
        if write.write_mode == "value":
            return
        if version_id is None or logical_key is None:
            self._incomplete(
                "planner.state_identity_incomplete",
                f"step={write.step_id}, return={write.return_name}",
            )
            return
        if write.math_object_id != logical_key.object_id:
            self._fail(
                "planner.runtime_state_binding_drift",
                f"step={write.step_id}, reason=object_identity_mismatch",
            )
        if not write.valid_scope_id:
            self._incomplete(
                "planner.state_identity_incomplete",
                f"step={write.step_id}, return={write.return_name}, missing=valid_scope",
            )
            return
        self.register(
            RuntimeStateVersionBinding(
                version_id=version_id,
                logical_state_key=logical_key,
                math_object_id=logical_key.object_id,
                runtime_type=logical_key.runtime_type,
                valid_scope_id=write.valid_scope_id,
                canonical_producer_call_id=(
                    write.canonical_producer_call_id or write.step_id
                ),
                runtime_path=_runtime_path(
                    write.produced_handle,
                    runtime_bindings,
                ),
                produced_handle=write.produced_handle,
                lineage=write.lineage,
                previous_version_id=write.previous_version_id,
                source_version_ids=write.source_version_ids,
                free_symbol_refs=write.free_symbol_refs,
                free_symbol_ids=write.free_symbol_ids,
                result_form=write.expected_result_form,
            )
        )
        self._register_projected_role_versions(
            write,
            runtime_bindings=runtime_bindings,
        )

    def _register_projected_role_versions(
        self,
        write: ProjectedStateWrite,
        *,
        runtime_bindings: Mapping[str, Any],
    ) -> None:
        for role in write.lineage.object_roles:
            if role.state_requirement != "materialized":
                continue
            if len(role.object_ids) != 1:
                self._incomplete(
                    "planner.state_identity_incomplete",
                    (
                        f"step={write.step_id}, role={role.role}, "
                        f"object_count={len(role.object_ids)}"
                    ),
                )
                continue
            if len(role.source_version_ids) != 1:
                self._incomplete(
                    "planner.state_dependency_version_unresolved",
                    (
                        f"step={write.step_id}, role={role.role}, "
                        f"version_count={len(role.source_version_ids)}"
                    ),
                )
                continue
            version_id = role.source_version_ids[0]
            logical_key = version_id.slot_id.logical_key
            if logical_key.object_id != role.object_ids[0]:
                self._fail(
                    "planner.runtime_state_binding_drift",
                    f"step={write.step_id}, role={role.role}",
                )
            candidate_handles = tuple(
                handle
                for handle in role.source_handles
                if _runtime_path(handle, runtime_bindings) is not None
            )
            paths = {
                _runtime_path(handle, runtime_bindings)
                for handle in candidate_handles
            }
            paths.discard(None)
            if len(paths) > 1:
                self._incomplete(
                    "planner.runtime_state_binding_drift",
                    (
                        f"step={write.step_id}, role={role.role}, "
                        f"runtime_path_count={len(paths)}"
                    ),
                )
                continue
            self.register(
                RuntimeStateVersionBinding(
                    version_id=version_id,
                    logical_state_key=logical_key,
                    math_object_id=role.object_ids[0],
                    runtime_type=logical_key.runtime_type,
                    valid_scope_id=version_id.slot_id.storage_scope_id,
                    canonical_producer_call_id=write.step_id,
                    runtime_path=next(iter(paths)) if paths else None,
                    produced_handle=(
                        candidate_handles[0]
                        if candidate_handles
                        else None
                    ),
                )
            )

    def _register_runtime_write(
        self,
        write: StateWriteProvenance,
        *,
        runtime_bindings: Mapping[str, Any],
        authoritative_handles: frozenset[str],
    ) -> None:
        if write.write_mode == "value":
            return
        version_id = write.selected_version_id
        logical_key = write.logical_state_key
        if version_id is None or logical_key is None:
            if write.produced_handle not in authoritative_handles:
                return
            self._incomplete(
                "planner.state_identity_incomplete",
                f"step={write.step_id}, return={write.return_name}",
            )
            return
        if write.math_object_id != logical_key.object_id:
            self._fail(
                "planner.runtime_state_binding_drift",
                f"step={write.step_id}, reason=runtime_object_identity_mismatch",
            )
        if not (write.valid_scope_id or write.scope_id):
            self._incomplete(
                "planner.state_identity_incomplete",
                f"step={write.step_id}, return={write.return_name}, missing=valid_scope",
            )
            return
        if write.free_symbol_names and not write.free_symbol_ids:
            self._incomplete(
                "planner.runtime_symbol_identity_unresolved",
                f"step={write.step_id}, return={write.return_name}",
            )
        destination = write.runtime_destination_key
        self.register(
            RuntimeStateVersionBinding(
                version_id=version_id,
                logical_state_key=logical_key,
                math_object_id=logical_key.object_id,
                runtime_type=logical_key.runtime_type,
                valid_scope_id=write.valid_scope_id or write.scope_id,
                canonical_producer_call_id=(
                    write.canonical_producer_call_id or write.step_id
                ),
                runtime_path=(
                    destination.runtime_path
                    if destination is not None
                    else _runtime_path(
                        write.produced_handle,
                        runtime_bindings,
                    )
                ),
                produced_handle=write.produced_handle,
                lineage=write.lineage,
                previous_version_id=write.previous_version_id,
                source_version_ids=write.source_version_ids,
                free_symbol_refs=write.free_symbol_names,
                free_symbol_ids=write.free_symbol_ids,
                result_form=write.result_form,
            )
        )

    def _merge(
        self,
        existing: RuntimeStateVersionBinding,
        incoming: RuntimeStateVersionBinding,
    ) -> RuntimeStateVersionBinding:
        if (
            existing.logical_state_key != incoming.logical_state_key
            or existing.math_object_id != incoming.math_object_id
            or existing.runtime_type != incoming.runtime_type
        ):
            self._fail(
                "planner.runtime_state_binding_drift",
                (
                    f"version={existing.version_id.to_payload()}, "
                    "reason=logical_identity_mismatch"
                ),
            )
        if (
            existing.runtime_path is not None
            and incoming.runtime_path is not None
            and existing.runtime_path != incoming.runtime_path
        ):
            self._fail(
                "planner.runtime_state_binding_drift",
                (
                    f"version={existing.version_id.to_payload()}, "
                    f"existing_path={existing.runtime_path}, "
                    f"incoming_path={incoming.runtime_path}"
                ),
            )
        if (
            existing.valid_scope_id != incoming.valid_scope_id
            and not (
                self.visibility.is_visible(
                    existing.valid_scope_id,
                    consumer_scope_id=incoming.valid_scope_id,
                )
                or self.visibility.is_visible(
                    incoming.valid_scope_id,
                    consumer_scope_id=existing.valid_scope_id,
                )
            )
        ):
            self._fail(
                "planner.runtime_state_visibility_drift",
                (
                    f"version={existing.version_id.to_payload()}, "
                    f"scopes={existing.valid_scope_id},{incoming.valid_scope_id}"
                ),
            )
        return replace(
            existing,
            valid_scope_id=_broader_scope(
                existing.valid_scope_id,
                incoming.valid_scope_id,
                registry=self.handle_registry,
            ),
            canonical_producer_call_id=(
                incoming.canonical_producer_call_id
                or existing.canonical_producer_call_id
            ),
            runtime_path=incoming.runtime_path or existing.runtime_path,
            produced_handle=(
                incoming.produced_handle or existing.produced_handle
            ),
            lineage=(
                incoming.lineage
                if incoming.lineage != StateSemanticLineage()
                else existing.lineage
            ),
            previous_version_id=(
                incoming.previous_version_id
                or existing.previous_version_id
            ),
            source_version_ids=tuple(
                dict.fromkeys(
                    (
                        *existing.source_version_ids,
                        *incoming.source_version_ids,
                    )
                )
            ),
            free_symbol_refs=(
                ()
                if incoming.result_form in {"closed", "closed_state"}
                else (
                    incoming.free_symbol_refs
                    if incoming.free_symbol_refs
                    else existing.free_symbol_refs
                )
            ),
            free_symbol_ids=(
                ()
                if incoming.result_form in {"closed", "closed_state"}
                else (
                    incoming.free_symbol_ids
                    if incoming.free_symbol_ids
                    else existing.free_symbol_ids
                )
            ),
            result_form=incoming.result_form or existing.result_form,
        )

    def _incomplete(self, code: str, message: str) -> None:
        if self.mode == "authoritative":
            self._fail(code, message)
        mismatch = {
            "code": "legacy_runtime_identity_fallback",
            "typed_issue_code": code,
            "message": message,
        }
        if mismatch not in self.mismatches:
            self.mismatches.append(mismatch)
            self.legacy_identity_fallback_count += 1

    @staticmethod
    def _fail(code: str, message: str) -> None:
        raise StrategyDraftValidationError(
            f"planner_configuration_error: {code}: {message}"
        )

    def _record(
        self,
        *,
        consumer: str,
        action: str,
        binding: RuntimeStateVersionBinding | None,
        reason_code: str,
    ) -> None:
        self.decisions.append(
            FunctionalRuntimeConsumerDecision(
                consumer=consumer,
                action=action,
                version_id=(
                    binding.version_id if binding is not None else None
                ),
                math_object_id=(
                    binding.math_object_id if binding is not None else None
                ),
                runtime_path=(
                    binding.runtime_path if binding is not None else None
                ),
                reason_code=reason_code,
            )
        )


def _runtime_path(
    handle: str | None,
    bindings: Mapping[str, Any],
) -> str | None:
    if handle is None:
        return None
    binding = bindings.get(handle)
    path = getattr(binding, "path", None)
    return str(path) if path is not None else None


def _broader_scope(
    left: str,
    right: str,
    *,
    registry: CanonicalHandleRegistry,
) -> str:
    if left == right:
        return left
    if left in registry.ancestor_scopes(right):
        return left
    if right in registry.ancestor_scopes(left):
        return right
    return left


__all__ = [
    "FunctionalConsumerIdentityMode",
    "FunctionalRuntimeConsumerDecision",
    "FunctionalStateReadIndex",
    "RuntimeStateVersionBinding",
]
