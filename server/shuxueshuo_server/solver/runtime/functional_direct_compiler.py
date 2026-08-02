"""Direct Functional call compilation without a StepIntent projection.

The runtime plan remains ``StepPlan``/``MethodInvocation``.  This module only
removes the semantic round trip through ``StepIntent``: B1-B5b have already
selected capability, scope, typed inputs and return destinations before a
request reaches this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapability,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCallReconciliation,
    FunctionalReturnAllocation,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    ExactCompiledStep,
    RecipeTrialExecutor,
)
from shuxueshuo_server.solver.runtime.state_identity import IndexedStateVersion
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedFunctionArgBinding,
    ProjectedStateDependency,
    ProjectedStateWrite,
    StateWriteProvenance,
)
from shuxueshuo_server.solver.utils import unique_ordered


FunctionalCompileMode = Literal[
    "projected",
    "direct_shadow",
    "direct_authoritative",
]


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
    projected_arg_bindings: tuple[ProjectedFunctionArgBinding, ...] = ()
    state_writes: tuple[ProjectedStateWrite, ...] = ()
    known_state_writes: tuple[StateWriteProvenance, ...] = ()
    known_runtime_bindings: tuple[tuple[str, str, str, str], ...] = ()
    known_object_refs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _DirectCreatedEntity:
    handle: str
    entity_type: str
    valid_scope: str
    description: str = ""


@dataclass(frozen=True)
class _DirectProducedOutput:
    handle: str
    valid_scope: str
    description: str
    output_type: str | None


@dataclass(frozen=True)
class _DirectCompileView:
    scope_id: str
    step_id: str
    recipe_hint: str
    goal_type: str
    target: str
    reads: tuple[str, ...]
    creates: tuple[_DirectCreatedEntity, ...]
    produces: tuple[_DirectProducedOutput, ...]
    strategy: str = ""
    reason: str = ""


class FunctionalDirectCompiler:
    """Compile one typed Functional request through its exact capability."""

    def __init__(
        self,
        *,
        trial_executor: RecipeTrialExecutor | None = None,
    ) -> None:
        self._trial_executor = trial_executor or RecipeTrialExecutor()

    def compile(
        self,
        request: FunctionalCompileRequest,
        runtime_context: Any,
        *,
        inputs: Any,
        handle_registry: Any,
    ) -> ExactCompiledStep:
        step = _compile_view(request)
        return self._trial_executor.compile_functional_call(
            step,
            capability_id=request.capability.capability_id,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            context=runtime_context,
            question_goals=tuple(inputs.question_goals),
            state_writes=request.state_writes,
            state_dependencies=request.state_dependencies,
            arg_bindings=request.projected_arg_bindings,
            known_state_versions=request.known_versions,
            known_state_writes=request.known_state_writes,
            known_runtime_bindings=request.known_runtime_bindings,
        )


def _compile_view(request: FunctionalCompileRequest) -> _DirectCompileView:
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
        _DirectProducedOutput(
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
    return _DirectCompileView(
        scope_id=request.execution_scope_id,
        step_id=request.prepared_call.call_id,
        recipe_hint=request.capability.capability_id,
        goal_type=request.capability.goal_type,
        target=target or request.capability.goal_type,
        reads=reads,
        creates=creates,
        produces=produces,
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
) -> tuple[_DirectCreatedEntity, ...]:
    created: dict[str, _DirectCreatedEntity] = {}
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
                _DirectCreatedEntity(
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
            _DirectCreatedEntity(
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
    "FunctionalCompileMode",
    "FunctionalCompileRequest",
    "FunctionalDirectCompiler",
]
