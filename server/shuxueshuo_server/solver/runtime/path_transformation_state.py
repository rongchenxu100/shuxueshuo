"""Resolve PathTransformation roles from Functional state provenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    MathObjectRegistry,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateDependency,
    ProjectedStateWrite,
    StepIntent,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import StateObjectRoleBinding
from shuxueshuo_server.solver.utils import unique_ordered

PathTransformationRole = Literal[
    "moving_object",
    "fixed_endpoint_1",
    "fixed_endpoint_2",
    "moving_locus",
    "moving_locus_endpoint_1",
    "moving_locus_endpoint_2",
    "auxiliary_object",
]


@dataclass(frozen=True)
class ResolvedPathTransformationRole:
    role: PathTransformationRole
    object_ref: str
    state_handle: str | None
    source_state_slot_ids: tuple[str, ...]
    source_handles: tuple[str, ...]
    state_requirement: Literal["identity_only", "materialized"]
    object_id: MathObjectId | None = None
    state_version_id: StateVersionId | None = None
    runtime_path: str | None = None

    @property
    def compatibility_object_ref(self) -> str:
        return self.object_ref

    @property
    def compatibility_handle(self) -> str | None:
        return self.state_handle


@dataclass(frozen=True)
class ResolvedPathTransformationState:
    transformation_handle: str
    transformation_kind: str | None
    roles: tuple[ResolvedPathTransformationRole, ...]

    def require(self, role: PathTransformationRole) -> ResolvedPathTransformationRole:
        matches = tuple(item for item in self.roles if item.role == role)
        if len(matches) != 1:
            raise StrategyDraftValidationError(
                "functional.path_transformation_role_missing: "
                f"transformation={self.transformation_handle}, role={role}"
            )
        return matches[0]


class PathTransformationStateResolver:
    """Resolve consumer inputs from the producer's immutable role lineage."""

    def __init__(
        self,
        *,
        index: CanonicalRuntimeBindingIndex,
        projected_state_writes: Sequence[ProjectedStateWrite],
        projected_state_dependencies: Sequence[ProjectedStateDependency],
    ) -> None:
        self.index = index
        self.writes = tuple(projected_state_writes)
        self.dependencies = tuple(projected_state_dependencies)
        self.consumer_identity_mode = (
            index.functional_consumer_identity_mode
        )
        self.object_registry = MathObjectRegistry.from_sources(
            index.handle_registry
        )
        self.write_order = {
            (item.step_id, item.produced_handle): order
            for order, item in enumerate(self.writes)
        }

    def resolve(
        self,
        transformation_handle: str,
        *,
        step: StepIntent,
        required_roles: Sequence[PathTransformationRole],
    ) -> ResolvedPathTransformationState:
        write = self.index.projected_state_write_for_handle(
            transformation_handle
        )
        if write is None:
            if self.consumer_identity_mode is not None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.path_transformation_role_version_unresolved: "
                    f"transformation={transformation_handle}"
                )
            return self._resolve_legacy(
                transformation_handle,
                step=step,
                required_roles=required_roles,
            )
        roles = tuple(
            self._resolve_role(binding, producer=write, step=step)
            for binding in write.lineage.object_roles
            if binding.role in _PATH_TRANSFORMATION_ROLES
        )
        result = ResolvedPathTransformationState(
            transformation_handle=transformation_handle,
            transformation_kind=self._runtime_kind(
                transformation_handle,
                step=step,
            ),
            roles=roles,
        )
        for role in required_roles:
            result.require(role)
        self._validate_runtime_identity(result, step=step)
        return result

    def _resolve_role(
        self,
        binding: StateObjectRoleBinding,
        *,
        producer: ProjectedStateWrite,
        step: StepIntent,
    ) -> ResolvedPathTransformationRole:
        if self.consumer_identity_mode is not None:
            return self._resolve_typed_role(
                binding,
                producer=producer,
                step=step,
            )
        if len(binding.object_refs) != 1:
            raise StrategyDraftValidationError(
                "functional.path_transformation_role_missing: "
                f"transformation={producer.produced_handle}, "
                f"role={binding.role}, object_count={len(binding.object_refs)}"
            )
        state_handle = self._state_handle(
            binding,
            producer=producer,
            step=step,
        )
        if state_handle is None:
            # Legacy StepIntent has no Functional role sidecar, but may carry
            # an explicit materialized read for the exact MathObject.
            state_handle = self._legacy_explicit_state(
                binding.object_refs[0],
                step=step,
            )
        if binding.state_requirement == "materialized" and state_handle is None:
            raise StrategyDraftValidationError(
                "functional.path_transformation_state_unavailable: "
                f"transformation={producer.produced_handle}, "
                f"role={binding.role}, object_ref={binding.object_refs[0]}"
            )
        return ResolvedPathTransformationRole(
            role=binding.role,  # type: ignore[arg-type]
            object_ref=binding.object_refs[0],
            state_handle=state_handle,
            source_state_slot_ids=binding.source_state_slot_ids,
            source_handles=binding.source_handles,
            state_requirement=binding.state_requirement,
        )

    def _resolve_typed_role(
        self,
        binding: StateObjectRoleBinding,
        *,
        producer: ProjectedStateWrite,
        step: StepIntent,
    ) -> ResolvedPathTransformationRole:
        if len(binding.object_ids) != 1:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.path_transformation_role_version_unresolved: "
                f"transformation={producer.produced_handle}, "
                f"role={binding.role}, object_count={len(binding.object_ids)}"
            )
        object_id = binding.object_ids[0]
        object_ref = (
            binding.object_refs[0]
            if len(binding.object_refs) == 1
            else object_id.value
        )
        if binding.state_requirement == "identity_only":
            if binding.source_version_ids:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_binding_drift: "
                    f"role={binding.role} is identity-only but carries versions"
                )
            return ResolvedPathTransformationRole(
                role=binding.role,  # type: ignore[arg-type]
                object_ref=object_ref,
                state_handle=None,
                source_state_slot_ids=binding.source_state_slot_ids,
                source_handles=binding.source_handles,
                state_requirement=binding.state_requirement,
                object_id=object_id,
            )
        if len(binding.source_version_ids) != 1:
            raise StrategyDraftValidationError(
                "planner.path_transformation_role_version_unresolved: "
                f"transformation={producer.produced_handle}, "
                f"role={binding.role}, "
                f"version_count={len(binding.source_version_ids)}"
            )
        version_id = binding.source_version_ids[0]
        read_index = self.index.functional_state_read_index()
        state = read_index.require_version(
            version_id,
            consumer_scope_id=step.scope_id,
            consumer=f"{step.step_id}.{binding.role}",
            require_runtime_path=True,
        )
        self.index.capture_functional_read_audit(read_index)
        if state.math_object_id != object_id:
            raise StrategyDraftValidationError(
                "planner.contract_runtime_identity_drift: "
                f"transformation={producer.produced_handle}, "
                f"role={binding.role}"
            )
        return ResolvedPathTransformationRole(
            role=binding.role,  # type: ignore[arg-type]
            object_ref=object_ref,
            state_handle=state.produced_handle,
            source_state_slot_ids=binding.source_state_slot_ids,
            source_handles=binding.source_handles,
            state_requirement=binding.state_requirement,
            object_id=object_id,
            state_version_id=version_id,
            runtime_path=state.runtime_path,
        )

    def _state_handle(
        self,
        binding: StateObjectRoleBinding,
        *,
        producer: ProjectedStateWrite,
        step: StepIntent,
    ) -> str | None:
        candidates: list[str] = []
        for handle in binding.source_handles:
            runtime_binding = self.index.bindings.get(handle)
            if runtime_binding is not None:
                candidates.append(handle)
        for slot_id in binding.source_state_slot_ids:
            candidates.extend(
                item.produced_handle
                for item in self.dependencies
                if item.step_id == producer.step_id
                and item.state_slot_id == slot_id
            )
            producer_order = self.write_order.get(
                (producer.step_id, producer.produced_handle),
                len(self.writes),
            )
            prior = tuple(
                item
                for item in self.writes
                if item.state_slot_id == slot_id
                and self.write_order.get(
                    (item.step_id, item.produced_handle),
                    len(self.writes),
                )
                < producer_order
            )
            if prior:
                candidates.append(prior[-1].produced_handle)
        visible = tuple(
            handle
            for handle in unique_ordered(candidates)
            if self._visible(handle, step=step)
        )
        if len(visible) > 1:
            # Source handles and projected dependencies commonly identify the
            # same runtime binding through aliases. Collapse by path, not name.
            by_path: dict[str, str] = {}
            for handle in visible:
                runtime_binding = self.index.bindings.get(handle)
                if runtime_binding is not None:
                    by_path.setdefault(runtime_binding.path, handle)
            if len(by_path) == 1:
                return next(iter(by_path.values()))
            raise StrategyDraftValidationError(
                "functional.path_transformation_state_unavailable: "
                f"role={binding.role}, reason=ambiguous_state_version"
            )
        return visible[0] if visible else None

    def _visible(self, handle: str, *, step: StepIntent) -> bool:
        binding = self.index.bindings.get(handle)
        if binding is None:
            return False
        valid_scope = self.index.handle_registry.handle_valid_scopes.get(handle)
        return valid_scope is None or visible_from_valid_scope(
            valid_scope,
            scope_id=step.scope_id,
            registry=self.index.handle_registry,
        )

    def _runtime_kind(
        self,
        transformation_handle: str,
        *,
        step: StepIntent,
    ) -> str | None:
        binding = self.index.bindings.get(transformation_handle)
        if binding is None:
            return None
        try:
            payload = self.index.context.read_path(
                binding.path,
                from_scope_id=step.scope_id,
                expected_type="PathTransformation",
            ).value
        except Exception:
            return None
        if not isinstance(payload, Mapping):
            return None
        kind = payload.get("type")
        return str(kind) if isinstance(kind, str) else None

    def _validate_runtime_identity(
        self,
        state: ResolvedPathTransformationState,
        *,
        step: StepIntent,
    ) -> None:
        binding = self.index.bindings.get(state.transformation_handle)
        if binding is None:
            return
        try:
            payload = self.index.context.read_path(
                binding.path,
                from_scope_id=step.scope_id,
                expected_type="PathTransformation",
            ).value
        except Exception:
            return
        if not isinstance(payload, Mapping):
            return
        by_role = {item.role: item for item in state.roles}
        moving_ref = payload.get("moving_point_ref")
        moving = by_role.get("moving_object")
        moving_payload_id = (
            self._payload_object_id(moving_ref)
            if isinstance(moving_ref, str)
            else None
        )
        if (
            isinstance(moving_ref, str)
            and moving is not None
            and (
                moving.object_id is not None
                and moving_payload_id != moving.object_id
                or moving.object_id is None
                and moving_ref != moving.object_ref
            )
        ):
            self._identity_drift(
                state.transformation_handle,
                "moving_object",
                moving.object_ref,
                moving_ref,
            )
        fixed_refs = payload.get("fixed_endpoint_refs")
        if isinstance(fixed_refs, (list, tuple)) and len(fixed_refs) == 2:
            expected_roles = tuple(
                by_role[role]
                for role in ("fixed_endpoint_1", "fixed_endpoint_2")
                if role in by_role
            )
            actual = tuple(str(item) for item in fixed_refs)
            actual_ids = tuple(
                self._payload_object_id(item) for item in actual
            )
            expected_ids = tuple(
                item.object_id for item in expected_roles
            )
            matches = (
                actual_ids == expected_ids
                if all(item is not None for item in expected_ids)
                else actual
                == tuple(item.object_ref for item in expected_roles)
            )
            if len(expected_roles) == 2 and not matches:
                self._identity_drift(
                    state.transformation_handle,
                    "fixed_endpoints",
                    ",".join(
                        item.object_ref for item in expected_roles
                    ),
                    ",".join(actual),
                )
        for payload_key, role_name in (
            ("linked_fixed_endpoint_ref", "fixed_endpoint_1"),
            ("auxiliary_point_ref", "auxiliary_object"),
        ):
            payload_ref = payload.get(payload_key)
            expected = by_role.get(role_name)
            if not isinstance(payload_ref, str) or expected is None:
                continue
            payload_id = self._payload_object_id(payload_ref)
            if (
                expected.object_id is not None
                and payload_id != expected.object_id
            ):
                self._identity_drift(
                    state.transformation_handle,
                    role_name,
                    expected.object_ref,
                    payload_ref,
                )

    def _payload_object_id(self, object_ref: str) -> MathObjectId | None:
        """Parse a runtime payload ref once at the typed identity boundary."""

        return (
            self.object_registry.resolve(object_ref)
            or self.object_registry.register_handle(object_ref)
        )

    @staticmethod
    def _identity_drift(
        transformation_handle: str,
        role: str,
        expected: str,
        actual: str,
    ) -> None:
        raise StrategyDraftValidationError(
            "planner.contract_runtime_identity_drift: "
            f"transformation={transformation_handle}, role={role}, "
            f"expected={expected}, actual={actual}"
        )

    def _resolve_legacy(
        self,
        transformation_handle: str,
        *,
        step: StepIntent,
        required_roles: Sequence[PathTransformationRole],
    ) -> ResolvedPathTransformationState:
        """Align canonical payload refs with explicit legacy StepIntent reads."""
        binding = self.index.bindings.get(transformation_handle)
        if binding is None:
            raise StrategyDraftValidationError(
                "functional.path_transformation_state_unavailable: "
                f"transformation={transformation_handle}"
            )
        try:
            payload = self.index.context.read_path(
                binding.path,
                from_scope_id=step.scope_id,
                expected_type="PathTransformation",
            ).value
        except Exception as exc:
            raise StrategyDraftValidationError(
                "functional.path_transformation_state_unavailable: "
                f"transformation={transformation_handle}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise StrategyDraftValidationError(
                "functional.path_transformation_state_unavailable: "
                f"transformation={transformation_handle}"
            )
        roles: list[ResolvedPathTransformationRole] = []
        fixed_refs = payload.get("fixed_endpoint_refs")
        if isinstance(fixed_refs, (list, tuple)) and len(fixed_refs) == 2:
            for position, object_ref in enumerate(fixed_refs, start=1):
                matched = self._legacy_explicit_state(
                    str(object_ref),
                    step=step,
                )
                roles.append(
                    ResolvedPathTransformationRole(
                        role=f"fixed_endpoint_{position}",  # type: ignore[arg-type]
                        object_ref=str(object_ref),
                        state_handle=matched,
                        source_state_slot_ids=(),
                        source_handles=((matched,) if matched else ()),
                        state_requirement="materialized",
                    )
                )
        moving_ref = payload.get("moving_point_ref")
        if isinstance(moving_ref, str):
            roles.append(
                ResolvedPathTransformationRole(
                    "moving_object",
                    moving_ref,
                    None,
                    (),
                    (),
                    "identity_only",
                )
            )
        linked_fixed_ref = payload.get("linked_fixed_endpoint_ref")
        if isinstance(linked_fixed_ref, str):
            matched = self._legacy_explicit_state(
                linked_fixed_ref,
                step=step,
            )
            roles.append(
                ResolvedPathTransformationRole(
                    "fixed_endpoint_1",
                    linked_fixed_ref,
                    matched,
                    (),
                    ((matched,) if matched else ()),
                    "materialized",
                )
            )
        auxiliary_ref = payload.get("auxiliary_point_ref")
        if isinstance(auxiliary_ref, str):
            matched = self._legacy_explicit_state(
                auxiliary_ref,
                step=step,
            )
            roles.append(
                ResolvedPathTransformationRole(
                    "auxiliary_object",
                    auxiliary_ref,
                    matched,
                    (),
                    ((matched,) if matched else ()),
                    "materialized",
                )
            )
        locus_condition_ref = payload.get("moving_locus_condition_ref")
        locus_object_ref = payload.get("moving_locus_segment_ref")
        if isinstance(locus_condition_ref, str) and isinstance(
            locus_object_ref,
            str,
        ):
            roles.append(
                ResolvedPathTransformationRole(
                    "moving_locus",
                    locus_object_ref,
                    None,
                    (),
                    (locus_condition_ref,),
                    "identity_only",
                )
            )
        locus_endpoint_refs = payload.get("moving_locus_endpoint_refs")
        if (
            isinstance(locus_endpoint_refs, (list, tuple))
            and len(locus_endpoint_refs) == 2
        ):
            for position, object_ref in enumerate(
                locus_endpoint_refs,
                start=1,
            ):
                object_ref = str(object_ref)
                matched = self._legacy_explicit_state(
                    object_ref,
                    step=step,
                )
                roles.append(
                    ResolvedPathTransformationRole(
                        f"moving_locus_endpoint_{position}",  # type: ignore[arg-type]
                        object_ref,
                        matched,
                        (),
                        ((matched,) if matched else ()),
                        "materialized",
                    )
                )
        result = ResolvedPathTransformationState(
            transformation_handle,
            str(payload.get("type")) if payload.get("type") else None,
            tuple(roles),
        )
        for role in required_roles:
            result.require(role)
        return result

    def _legacy_explicit_state(
        self,
        object_ref: str,
        *,
        step: StepIntent,
    ) -> str | None:
        candidates = tuple(
            handle
            for handle in step.reads
            if (
                (runtime_binding := self.index.bindings.get(handle)) is not None
                and runtime_binding.value_type == "Point"
                and (
                    (
                        (
                            write := self.index.projected_state_write_for_handle(
                                handle
                            )
                        )
                        is not None
                        and write.object_ref == object_ref
                    )
                    or any(
                        item.produced_handle == handle
                        and item.object_ref == object_ref
                        for item in self.index.state_write_provenance
                    )
                    or handle == object_ref
                )
            )
        )
        by_path = {
            self.index.bindings[handle].path: handle
            for handle in candidates
            if handle in self.index.bindings
        }
        return next(iter(by_path.values())) if len(by_path) == 1 else None


_PATH_TRANSFORMATION_ROLES = frozenset(
    {
        "moving_object",
        "fixed_endpoint_1",
        "fixed_endpoint_2",
        "moving_locus",
        "moving_locus_endpoint_1",
        "moving_locus_endpoint_2",
        "auxiliary_object",
    }
)


__all__ = [
    "PathTransformationRole",
    "PathTransformationStateResolver",
    "ResolvedPathTransformationRole",
    "ResolvedPathTransformationState",
]
