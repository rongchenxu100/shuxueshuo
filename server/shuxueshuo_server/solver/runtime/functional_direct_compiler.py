"""Direct Functional call compilation from typed prepared inputs.

The runtime plan remains ``StepPlan``/``MethodInvocation``. B1-B5b have already
selected capability, scope, typed inputs, and return destinations before a
request reaches this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapability,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCallReconciliation,
    FunctionalReturnAllocation,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    ExactCompiledStep,
    FunctionalCapabilityCompiler,
)
from shuxueshuo_server.solver.runtime.state_identity import IndexedStateVersion
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateDependency,
    ProjectedStateWrite,
    StateWriteProvenance,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class FunctionalCompileRequest:
    prepared_call: Any
    capability: FunctionalCapability
    execution_scope_id: str
    arg_bindings: tuple[Any, ...]
    state_reads: tuple[Any, ...]
    return_allocations: tuple[FunctionalReturnAllocation, ...]
    state_dependencies: tuple[ProjectedStateDependency, ...]
    known_versions: tuple[IndexedStateVersion, ...]
    required_return_names: tuple[str, ...]
    state_writes: tuple[ProjectedStateWrite, ...] = ()
    known_state_writes: tuple[StateWriteProvenance, ...] = ()
    known_runtime_bindings: tuple[tuple[str, str, str, str], ...] = ()
    known_object_refs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FunctionalCreatedEntity:
    handle: str
    entity_type: str
    valid_scope: str
    description: str = ""


@dataclass(frozen=True)
class FunctionalReturnOutput:
    handle: str
    valid_scope: str
    description: str
    output_type: str | None


@dataclass(frozen=True)
class FunctionalRuntimeArgBinding:
    """One C3 binding resolved to its exact physical runtime input."""

    call_id: str
    arg_name: str
    item_index: int
    runtime_type: str
    runtime_path: str | None
    runtime_input_targets: tuple[str, ...]
    binding_authority: str
    semantic_role: str
    cardinality: str
    selection_policy: str
    consumption_mode: str
    state_version_id: Any | None = None
    condition_id: str | None = None
    math_object_id: Any | None = None
    source_call_id: str | None = None
    source_return_name: str | None = None
    compiler_selector_id: str | None = None
    source_handle: str | None = None
    state_slot_id: str | None = None

    @property
    def step_id(self) -> str:
        return self.call_id


@dataclass(frozen=True)
class FunctionalCapabilityCompileCall:
    scope_id: str
    step_id: str
    capability_id: str
    goal_type: str
    target_handle: str
    input_handles: tuple[str, ...]
    created_entities: tuple[FunctionalCreatedEntity, ...]
    return_outputs: tuple[FunctionalReturnOutput, ...]


class FunctionalDirectCompiler:
    """Compile one typed Functional request through its exact capability."""

    def __init__(
        self,
        *,
        capability_compiler: FunctionalCapabilityCompiler | None = None,
    ) -> None:
        self._capability_compiler = (
            capability_compiler or FunctionalCapabilityCompiler()
        )

    def compile(
        self,
        request: FunctionalCompileRequest,
        runtime_context: Any,
        *,
        inputs: Any,
        handle_registry: Any,
    ) -> ExactCompiledStep:
        step = _compile_call(request)
        arg_bindings = _runtime_arg_bindings(request)
        compiled = self._capability_compiler.compile(
            step,
            capability_id=request.capability.capability_id,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            context=runtime_context,
            question_goals=tuple(inputs.question_goals),
            state_writes=request.state_writes,
            state_dependencies=request.state_dependencies,
            arg_bindings=arg_bindings,
            known_state_versions=request.known_versions,
            known_state_writes=request.known_state_writes,
            known_runtime_bindings=request.known_runtime_bindings,
        )
        return replace(
            compiled,
            plan=replace(
                compiled.plan,
                scope=request.execution_scope_id,
            ),
        )


def _runtime_arg_bindings(
    request: FunctionalCompileRequest,
) -> tuple[FunctionalRuntimeArgBinding, ...]:
    result: list[FunctionalRuntimeArgBinding] = []
    for prepared in request.arg_bindings:
        binding = prepared.logical_binding
        result.append(
            FunctionalRuntimeArgBinding(
                call_id=request.prepared_call.call_id,
                arg_name=binding.key.arg_name,
                item_index=binding.key.item_index,
                runtime_type=binding.runtime_type,
                runtime_path=(
                    prepared.runtime_path
                    if prepared.selected_state_version_id is None
                    else None
                ),
                runtime_input_targets=binding.runtime_input_targets,
                binding_authority=binding.binding_authority,
                semantic_role=binding.semantic_role,
                cardinality=binding.cardinality,
                selection_policy=binding.selection_policy,
                consumption_mode=binding.consumption_mode,
                state_version_id=prepared.selected_state_version_id,
                condition_id=binding.source.condition_id,
                math_object_id=(
                    binding.source.math_object_id
                    or prepared.source_math_object_id
                ),
                source_call_id=binding.source.source_call_id,
                source_return_name=binding.source.source_return_name,
                compiler_selector_id=binding.source.compiler_selector_id,
                source_handle=prepared.source_handle,
            )
        )
    return tuple(result)


def _compile_call(
    request: FunctionalCompileRequest,
) -> FunctionalCapabilityCompileCall:
    reconciliation: FunctionalCallReconciliation = (
        request.prepared_call.reconciliation
    )
    reads = tuple(
        unique_ordered(
            handle
            for values in reconciliation.resolved_args.values()
            for value in values
            for handle in _direct_read_handles(value)
            if isinstance(handle, str) and handle
        )
    )
    produces = tuple(
        FunctionalReturnOutput(
            handle=handle,
            valid_scope=allocation.valid_scope,
            description=(
                f"{request.capability.capability_id} return "
                f"{allocation.return_name}"
            ),
            output_type=allocation.runtime_type,
        )
        for allocation in request.return_allocations
        for handle in unique_ordered(
            (allocation.state_handle, allocation.handle)
        )
        if isinstance(handle, str) and handle
    )
    creates = _direct_creates(request)
    target = next(
        (
            allocation.handle
            for allocation in request.return_allocations
            if allocation.bound_ref is not None
            and allocation.bound_ref.kind == "answer"
        ),
        None,
    )
    if target is None:
        target = next(
            (
                allocation.math_object_id.value
                for allocation in request.return_allocations
                if allocation.math_object_id is not None
            ),
            None,
        )
    if target is None and produces:
        target = produces[0].handle
    return FunctionalCapabilityCompileCall(
        scope_id=request.execution_scope_id,
        step_id=request.prepared_call.call_id,
        capability_id=request.capability.capability_id,
        goal_type=request.capability.goal_type,
        target_handle=target or request.capability.goal_type,
        input_handles=reads,
        created_entities=creates,
        return_outputs=produces,
    )


def _direct_read_handles(value: Any) -> tuple[str, ...]:
    """Preserve identity/state views without selecting by handle syntax."""
    if value.materialized_runtime_type is not None:
        return tuple(
            unique_ordered((value.handle, *value.supporting_handles))
        )
    if value.runtime_type.endswith("Ref"):
        return (
            (value.object_ref,)
            if isinstance(value.object_ref, str) and value.object_ref
            else ()
        )
    if value.runtime_type == "Point" and value.object_ref is not None:
        return tuple(
            unique_ordered(
                (value.object_ref, value.handle, *value.supporting_handles)
            )
        )
    return tuple(
        unique_ordered((value.handle, *value.supporting_handles))
    )


def _direct_creates(
    request: FunctionalCompileRequest,
) -> tuple[FunctionalCreatedEntity, ...]:
    created: dict[str, FunctionalCreatedEntity] = {}
    for values in request.prepared_call.reconciliation.resolved_args.values():
        for value in values:
            object_id = value.math_object_id
            if (
                object_id is None
                or value.runtime_type not in {"PointRef", "LineRef"}
                or object_id.value in request.known_object_refs
            ):
                continue
            created.setdefault(
                object_id.value,
                FunctionalCreatedEntity(
                    handle=object_id.value,
                    entity_type=object_id.kind,
                    valid_scope=value.valid_scope,
                    description="Functional planned target object",
                ),
            )
    for allocation in request.return_allocations:
        object_id = allocation.math_object_id
        if (
            allocation.write_mode != "create"
            or object_id is None
            or object_id.kind not in {"point", "line"}
            or object_id.value in request.known_object_refs
        ):
            continue
        created.setdefault(
            object_id.value,
            FunctionalCreatedEntity(
                handle=object_id.value,
                entity_type=object_id.kind,
                valid_scope=allocation.valid_scope,
                description=(
                    "Functional generated object for "
                    f"{allocation.return_name}"
                ),
            ),
        )
    return tuple(created.values())


__all__ = [
    "FunctionalCompileRequest",
    "FunctionalDirectCompiler",
    "FunctionalRuntimeArgBinding",
]
