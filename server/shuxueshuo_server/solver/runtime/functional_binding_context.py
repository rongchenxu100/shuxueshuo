"""Typed argument-role authority for Functional calls.

The binding context is deliberately independent from flat wire reads and
runtime paths.  It records why a value occupies a public capability argument
and how that argument is projected to Function/Macro runtime inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal, Mapping, cast

from shuxueshuo_server.solver.family.models import (
    FunctionalArgBindingAuthority,
)
from shuxueshuo_server.solver.contracts import (
    CanonicalSymbolDerivationSpec,
    CoefficientExtractionDerivationSpec,
    ConditionSourceSpec,
    EntityIdentitySourceSpec,
    ExactCallResultSourceSpec,
    ExactParameterSubstitutionSourceSpec,
    FreeSymbolBasisDerivationSpec,
    LatestStateSourceSpec,
    MacroPreparedRoleSourceSpec,
    MethodInputBindingSpec,
    OrdinalZeroTemplateDerivationSpec,
    PreviousOutputIdentityDerivationSpec,
    ProducerLinkedSourceSpec,
    PublicArgSourceSpec,
    SourceObjectIdentityDerivationSpec,
)
from shuxueshuo_server.solver.runtime.condition_binding_authority import (
    ConditionBindingAuthorityError,
    ConditionBindingAuthorityIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCallReconciliation,
    FunctionalMethodRelationBinding,
    FunctionalPlan,
    ResolvedFunctionalValue,
    SemanticRef,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedFunctionArgBinding,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectRegistry,
    MathObjectId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.method_input_contracts import (
    method_input_requires_typed_entity_authority,
)
from shuxueshuo_server.solver.utils import unique_ordered


FunctionalArgSelectionPolicy = Literal[
    "exact",
    "latest",
    "identity_only",
]
FunctionalArgConsumptionMode = Literal[
    "runtime_input",
    "resolver_evidence",
    "typed_binding",
]
FunctionalArgSourceKind = Literal[
    "state_version",
    "condition",
    "math_object",
    "call_result",
]


class FunctionalBindingContextError(ValueError):
    """A Functional binding ledger cannot be built without guessing."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"planner_configuration_error: {code}: {detail}")


@dataclass(frozen=True, order=True)
class FunctionalArgBindingKey:
    call_id: str
    arg_name: str
    item_index: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "arg_name": self.arg_name,
            "item_index": self.item_index,
        }


@dataclass(frozen=True, order=True)
class FunctionalTypedInputOmission:
    """Audit-only record for an optional typed input with no evidence."""

    call_id: str
    input_name: str
    reason: Literal["optional_no_evidence"] = "optional_no_evidence"

    def to_payload(self) -> dict[str, str]:
        return {
            "call_id": self.call_id,
            "input_name": self.input_name,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FunctionalArgSourceIdentity:
    kind: FunctionalArgSourceKind
    state_version_id: StateVersionId | None = None
    condition_id: str | None = None
    math_object_id: MathObjectId | None = None
    source_call_id: str | None = None
    source_return_name: str | None = None

    def __post_init__(self) -> None:
        populated = {
            "state_version": self.state_version_id is not None,
            "condition": self.condition_id is not None,
            "math_object": self.math_object_id is not None,
            "call_result": (
                self.source_call_id is not None
                and self.source_return_name is not None
            ),
        }
        if not populated[self.kind] or sum(populated.values()) != 1:
            raise FunctionalBindingContextError(
                "planner.functional_binding_context_incomplete",
                f"source kind {self.kind} is not uniquely identified",
            )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.state_version_id is not None:
            payload["state_version_id"] = self.state_version_id.to_payload()
        if self.condition_id is not None:
            payload["condition_id"] = self.condition_id
        if self.math_object_id is not None:
            payload["math_object_id"] = self.math_object_id.to_payload()
        if self.source_call_id is not None:
            payload["source_call_id"] = self.source_call_id
            payload["source_return_name"] = self.source_return_name
        return payload

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalArgSourceIdentity":
        kind = str(payload.get("kind", ""))
        state_version = payload.get("state_version_id")
        math_object = payload.get("math_object_id")
        return cls(
            kind=cast(FunctionalArgSourceKind, kind),
            state_version_id=(
                StateVersionId.from_payload(state_version)
                if isinstance(state_version, Mapping)
                else None
            ),
            condition_id=(
                str(payload["condition_id"])
                if payload.get("condition_id") is not None
                else None
            ),
            math_object_id=(
                MathObjectId.from_payload(math_object)
                if isinstance(math_object, Mapping)
                else None
            ),
            source_call_id=(
                str(payload["source_call_id"])
                if payload.get("source_call_id") is not None
                else None
            ),
            source_return_name=(
                str(payload["source_return_name"])
                if payload.get("source_return_name") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class FunctionalArgBinding:
    key: FunctionalArgBindingKey
    capability_id: str
    semantic_role: str
    binding_authority: FunctionalArgBindingAuthority
    cardinality: str
    runtime_type: str
    source: FunctionalArgSourceIdentity
    selection_policy: FunctionalArgSelectionPolicy
    consumption_mode: FunctionalArgConsumptionMode
    runtime_input_targets: tuple[str, ...]
    runtime_input_required: bool = True
    input_binding: MethodInputBindingSpec | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "key": self.key.to_payload(),
            "capability_id": self.capability_id,
            "semantic_role": self.semantic_role,
            "binding_authority": self.binding_authority,
            "cardinality": self.cardinality,
            "runtime_type": self.runtime_type,
            "source": self.source.to_payload(),
            "selection_policy": self.selection_policy,
            "consumption_mode": self.consumption_mode,
            "runtime_input_targets": list(self.runtime_input_targets),
            "runtime_input_required": self.runtime_input_required,
        }
        if self.input_binding is not None:
            payload["input_binding"] = self.input_binding.to_payload()
        return payload


@dataclass(frozen=True)
class FunctionalBindingContext:
    bindings: tuple[FunctionalArgBinding, ...]
    binding_signature: str
    relation_bindings: tuple[FunctionalMethodRelationBinding, ...] = ()
    typed_input_omissions: tuple[FunctionalTypedInputOmission, ...] = ()

    def for_call(self, call_id: str) -> tuple[FunctionalArgBinding, ...]:
        return tuple(item for item in self.bindings if item.key.call_id == call_id)

    def binding_for(
        self,
        call_id: str,
        arg_name: str,
        item_index: int,
    ) -> FunctionalArgBinding | None:
        key = FunctionalArgBindingKey(call_id, arg_name, item_index)
        return next((item for item in self.bindings if item.key == key), None)

    def signature_for_call(self, call_id: str) -> str:
        return _binding_signature(
            self.for_call(call_id),
            relation_bindings=self.relations_for_call(call_id),
            include_call_id=False,
        )

    def relations_for_call(
        self,
        call_id: str,
    ) -> tuple[FunctionalMethodRelationBinding, ...]:
        return tuple(
            item for item in self.relation_bindings if item.call_id == call_id
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "bindings": [item.to_payload() for item in self.bindings],
            "relation_bindings": [
                item.to_payload() for item in self.relation_bindings
            ],
            "typed_input_omissions": [
                item.to_payload() for item in self.typed_input_omissions
            ],
            "binding_signature": self.binding_signature,
        }


class FunctionalBindingContextBuilder:
    """Build the final binding ledger from canonical reconciliation state."""

    def build(
        self,
        plan: FunctionalPlan,
        calls: tuple[FunctionalCallReconciliation, ...],
        *,
        catalog: FunctionalCapabilityCatalog,
        object_registry: MathObjectRegistry | None = None,
        handle_registry: CanonicalHandleRegistry | None = None,
        method_specs: MethodSpecRegistry | None = None,
        resolver_injected_arg_keys: frozenset[tuple[str, str]] = frozenset(),
        force_exact_source_versions: bool = False,
        allow_missing_typed_sources: bool = False,
        condition_authority_index: ConditionBindingAuthorityIndex | None = None,
    ) -> FunctionalBindingContext:
        wire_calls = {item.call_id: item for item in plan.calls}
        calls_by_id = {item.call_id: item for item in calls}
        bindings: list[FunctionalArgBinding] = []
        omissions: list[FunctionalTypedInputOmission] = []
        for call in calls:
            capability = catalog.get(call.capability_id)
            if capability is None:
                raise FunctionalBindingContextError(
                    "planner.functional_binding_context_incomplete",
                    f"unknown capability {call.capability_id}",
                )
            wire_call = wire_calls.get(call.call_id)
            arg_specs = {item.name: item for item in capability.args}
            auto_specs = {item.name: item for item in capability.auto_args}
            context_specs = {
                item.arg_name: item for item in capability.context_arg_bindings
            }
            adapter_bindings = {
                item.input_name: item
                for item in capability.input_bindings
            }

            def strict_binding_for_arg(
                resolved_arg_name: str,
                *,
                preferred_input: str | None = None,
            ) -> tuple[str, MethodInputBindingSpec] | None:
                """Map one public/resolved argument to one strict Method input."""

                context_binding = context_specs.get(resolved_arg_name)
                if (
                    context_binding is not None
                    and context_binding.input_binding is not None
                ):
                    return (
                        context_binding.input_binding.input_name,
                        context_binding.input_binding,
                    )
                direct = adapter_bindings.get(
                    preferred_input or resolved_arg_name
                )
                if isinstance(direct, MethodInputBindingSpec):
                    return direct.input_name, direct
                matches = tuple(
                    (input_name, declaration)
                    for input_name, declaration in adapter_bindings.items()
                    if isinstance(declaration, MethodInputBindingSpec)
                    and resolved_arg_name
                    in _binding_declared_source_args(declaration)
                )
                if len(matches) > 1:
                    raise FunctionalBindingContextError(
                        "planner.method_input_view_authority_drift",
                        f"{call.call_id}.{resolved_arg_name} maps to multiple "
                        f"strict Method inputs: "
                        f"{[item[0] for item in matches]!r}",
                    )
                return matches[0] if matches else None

            for arg_name, values in call.resolved_args.items():
                spec = arg_specs.get(arg_name)
                if spec is None:
                    context_spec = context_specs.get(arg_name)
                    auto_spec = (
                        auto_specs.get(arg_name)
                        if context_spec is None
                        else None
                    )
                    if auto_spec is not None:
                        selected_source = _typed_input_selected_source(
                            arg_name=auto_spec.name,
                            binding=auto_spec.input_binding,
                            runtime_input=auto_spec.runtime_input,
                            required=bool(values) or auto_spec.required,
                            capability=capability,
                            call=call,
                            calls_by_id=calls_by_id,
                            object_registry=object_registry,
                            handle_registry=handle_registry,
                            method_specs=method_specs,
                            allow_missing_typed_source=(
                                allow_missing_typed_sources
                            ),
                            condition_authority_index=(
                                condition_authority_index
                            ),
                        )
                        if selected_source is None:
                            continue
                        bindings.append(
                            FunctionalArgBinding(
                                key=FunctionalArgBindingKey(
                                    call.call_id,
                                    arg_name,
                                    0,
                                ),
                                capability_id=call.capability_id,
                                semantic_role=(
                                    auto_spec.semantic_role or arg_name
                                ),
                                binding_authority="compiler",
                                cardinality=(
                                    "many" if len(values) > 1 else "one"
                                ),
                                runtime_type=(
                                    values[0].runtime_type
                                    if values and values[0].runtime_type
                                    else _declared_typed_runtime_type(
                                        capability,
                                        runtime_input=(
                                            auto_spec.runtime_input
                                            or auto_spec.name
                                        ),
                                        method_specs=method_specs,
                                    )
                                ),
                                source=selected_source,
                                selection_policy=_typed_binding_selection_policy(
                                    auto_spec.input_binding,
                                    capability=capability,
                                    runtime_input=auto_spec.runtime_input,
                                    method_specs=method_specs,
                                ),
                                consumption_mode="typed_binding",
                                runtime_input_targets=(
                                    auto_spec.runtime_input or arg_name,
                                ),
                                runtime_input_required=auto_spec.required,
                                input_binding=auto_spec.input_binding,
                            )
                        )
                        continue
                    if context_spec is None:
                        raise FunctionalBindingContextError(
                            "planner.functional_arg_role_drift",
                            f"{call.call_id}.{arg_name} has no arg contract",
                        )
                    strict_context = strict_binding_for_arg(arg_name)
                    for item_index, value in enumerate(values):
                        source_identity = _source_identity(
                            value,
                            object_registry=object_registry,
                            prefer_call_result=force_exact_source_versions,
                        )
                        runtime_input = arg_name
                        strict_binding: MethodInputBindingSpec | None = None
                        macro_role_hint = False
                        if strict_context is not None:
                            runtime_input, strict_binding = strict_context
                            macro_role_hint = isinstance(
                                strict_binding.source,
                                MacroPreparedRoleSourceSpec,
                            )
                            if not macro_role_hint:
                                typed_source = _typed_input_selected_source(
                                    arg_name=arg_name,
                                    binding=strict_binding,
                                    runtime_input=runtime_input,
                                    required=True,
                                    capability=capability,
                                    call=call,
                                    calls_by_id=calls_by_id,
                                    object_registry=object_registry,
                                    handle_registry=handle_registry,
                                    method_specs=method_specs,
                                    allow_missing_typed_source=False,
                                    condition_authority_index=(
                                        condition_authority_index
                                    ),
                                )
                                if typed_source is None:
                                    raise FunctionalBindingContextError(
                                        "planner.method_input_view_authority_missing",
                                        f"{call.call_id}.{arg_name} has no typed "
                                        "Condition/role source",
                                    )
                                _require_resolved_value_matches_source_authority(
                                    value,
                                    source_identity,
                                    typed_source,
                                    call_id=call.call_id,
                                    arg_name=arg_name,
                                )
                                source_identity = typed_source
                        bindings.append(
                            FunctionalArgBinding(
                                key=FunctionalArgBindingKey(
                                    call.call_id,
                                    arg_name,
                                    item_index,
                                ),
                                capability_id=call.capability_id,
                                semantic_role=context_spec.semantic_role,
                                binding_authority="resolver",
                                cardinality=(
                                    "many" if len(values) > 1 else "one"
                                ),
                                runtime_type=value.runtime_type or "unknown",
                                source=source_identity,
                                selection_policy=(
                                    "exact"
                                    if force_exact_source_versions
                                    and value.source_call_id is not None
                                    and value.return_name is not None
                                    else (
                                        "identity_only"
                                        if value.state_version_id is None
                                        and value.math_object_id is not None
                                        else (
                                            "exact"
                                            if force_exact_source_versions
                                            else "latest"
                                        )
                                    )
                                ),
                                consumption_mode=(
                                    "resolver_evidence"
                                    if macro_role_hint
                                    else (
                                        "typed_binding"
                                        if strict_binding is not None
                                        else context_spec.consumption_mode
                                    )
                                ),
                                runtime_input_targets=(
                                    ()
                                    if macro_role_hint
                                    else (
                                        (runtime_input,)
                                        if strict_binding is not None
                                        or context_spec.consumption_mode
                                        == "runtime_input"
                                        else ()
                                    )
                                ),
                                runtime_input_required=(
                                    strict_binding.required
                                    if strict_binding is not None
                                    else True
                                ),
                                input_binding=(
                                    None if macro_role_hint else strict_binding
                                ),
                            )
                        )
                    continue
                authored_on_wire = (
                    wire_call is not None
                    and arg_name in wire_call.args
                    and (call.call_id, arg_name)
                    not in resolver_injected_arg_keys
                )
                if spec.binding_authority != "wire" and wire_call is not None and (
                    arg_name in wire_call.args
                ):
                    raise FunctionalBindingContextError(
                        "planner.functional_binding_authority_drift",
                        f"{spec.binding_authority} arg {call.call_id}.{arg_name} was supplied on wire",
                    )
                for item_index, value in enumerate(values):
                    wire_values = (
                        wire_call.args.get(arg_name, ())
                        if authored_on_wire and wire_call is not None
                        else ()
                    )
                    runtime_targets, consumption_mode = _runtime_mapping(
                        capability.source,
                        arg_name=arg_name,
                        runtime_input=spec.runtime_input,
                        item_index=item_index,
                        item_count=len(values),
                        consumption_mode=spec.consumption_mode,
                    )
                    runtime_input = spec.runtime_input or arg_name
                    strict_match = strict_binding_for_arg(
                        arg_name,
                        preferred_input=runtime_input,
                    )
                    strict_binding: MethodInputBindingSpec | None = None
                    macro_role_hint = False
                    if strict_match is not None:
                        runtime_input, strict_binding = strict_match
                        macro_role_hint = isinstance(
                            strict_binding.source,
                            MacroPreparedRoleSourceSpec,
                        )
                    source_identity = _source_identity(
                        value,
                        object_registry=object_registry,
                        prefer_call_result=force_exact_source_versions,
                    )
                    if strict_binding is not None and not macro_role_hint:
                        typed_source = _typed_input_selected_source(
                            arg_name=arg_name,
                            binding=strict_binding,
                            runtime_input=runtime_input,
                            required=True,
                            capability=capability,
                            call=call,
                            calls_by_id=calls_by_id,
                            object_registry=object_registry,
                            handle_registry=handle_registry,
                            method_specs=method_specs,
                            allow_missing_typed_source=False,
                            condition_authority_index=condition_authority_index,
                        )
                        if typed_source is None:
                            raise FunctionalBindingContextError(
                                "planner.method_input_view_authority_missing",
                                f"{call.call_id}.{arg_name} has no typed source",
                            )
                        _require_resolved_value_matches_source_authority(
                            value,
                            source_identity,
                            typed_source,
                            call_id=call.call_id,
                            arg_name=arg_name,
                        )
                        source_identity = typed_source
                    bindings.append(
                        self._value_binding(
                            call_id=call.call_id,
                            capability_id=call.capability_id,
                            arg_name=arg_name,
                            item_index=item_index,
                            spec=spec,
                            binding_authority=(
                                "wire" if authored_on_wire else "resolver"
                            ),
                            selection_policy=(
                                _wire_resolution_policy_for_view(spec)
                                if item_index < len(wire_values)
                                and isinstance(
                                    wire_values[item_index],
                                    SemanticRef,
                                )
                                else None
                            ),
                            value=value,
                            source=source_identity,
                            runtime_targets=(
                                ()
                                if macro_role_hint
                                else (
                                    runtime_targets
                                    if runtime_targets or strict_binding is None
                                    else (runtime_input,)
                                )
                            ),
                            consumption_mode=(
                                "resolver_evidence"
                                if macro_role_hint
                                else (
                                    "typed_binding"
                                    if strict_binding is not None
                                    else consumption_mode
                                )
                            ),
                            force_exact_source_versions=(
                                force_exact_source_versions
                            ),
                            input_binding=(
                                None if macro_role_hint else strict_binding
                            ),
                        )
                    )
            for auto_arg in capability.auto_args:
                if auto_arg.name in call.resolved_args:
                    continue
                selected_source = _typed_input_selected_source(
                    arg_name=auto_arg.name,
                    binding=auto_arg.input_binding,
                    runtime_input=auto_arg.runtime_input,
                    required=auto_arg.required,
                    capability=capability,
                    call=call,
                    calls_by_id=calls_by_id,
                    object_registry=object_registry,
                    handle_registry=handle_registry,
                    method_specs=method_specs,
                    allow_missing_typed_source=allow_missing_typed_sources,
                    condition_authority_index=condition_authority_index,
                )
                if selected_source is None:
                    if not auto_arg.required:
                        omissions.append(
                            FunctionalTypedInputOmission(
                                call.call_id,
                                auto_arg.name,
                            )
                        )
                    continue
                bindings.append(
                    FunctionalArgBinding(
                        key=FunctionalArgBindingKey(
                            call.call_id,
                            auto_arg.name,
                            0,
                        ),
                        capability_id=call.capability_id,
                        semantic_role=(
                            auto_arg.semantic_role or auto_arg.name
                        ),
                        binding_authority="compiler",
                        cardinality="one",
                        runtime_type=_declared_typed_runtime_type(
                            capability,
                            runtime_input=(
                                auto_arg.runtime_input or auto_arg.name
                            ),
                            method_specs=method_specs,
                        ),
                        source=selected_source,
                        selection_policy=_typed_binding_selection_policy(
                            auto_arg.input_binding,
                            capability=capability,
                            runtime_input=auto_arg.runtime_input,
                            method_specs=method_specs,
                        ),
                        consumption_mode="typed_binding",
                        runtime_input_targets=(
                            auto_arg.runtime_input or auto_arg.name,
                        ),
                        runtime_input_required=auto_arg.required,
                        input_binding=auto_arg.input_binding,
                    )
                )
            for public_arg in capability.args:
                if public_arg.name in call.resolved_args:
                    continue
                runtime_input = public_arg.runtime_input or public_arg.name
                adapter_binding = adapter_bindings.get(runtime_input)
                if adapter_binding is None:
                    continue
                binding_required = public_arg.required or adapter_binding.required
                selected_source = _typed_input_selected_source(
                    arg_name=public_arg.name,
                    binding=adapter_binding,
                    runtime_input=runtime_input,
                    required=binding_required,
                    capability=capability,
                    call=call,
                    calls_by_id=calls_by_id,
                    object_registry=object_registry,
                    handle_registry=handle_registry,
                    method_specs=method_specs,
                    allow_missing_typed_source=allow_missing_typed_sources,
                    condition_authority_index=condition_authority_index,
                )
                if selected_source is None:
                    if not binding_required:
                        omissions.append(
                            FunctionalTypedInputOmission(
                                call.call_id,
                                runtime_input,
                            )
                        )
                    continue
                bindings.append(
                    FunctionalArgBinding(
                        key=FunctionalArgBindingKey(
                            call.call_id,
                            public_arg.name,
                            0,
                        ),
                        capability_id=call.capability_id,
                        semantic_role=(
                            public_arg.semantic_role or public_arg.name
                        ),
                        binding_authority="compiler",
                        cardinality="one",
                        runtime_type=_declared_typed_runtime_type(
                            capability,
                            runtime_input=runtime_input,
                            method_specs=method_specs,
                        ),
                        source=selected_source,
                        selection_policy=_typed_binding_selection_policy(
                            adapter_binding,
                            capability=capability,
                            runtime_input=runtime_input,
                            method_specs=method_specs,
                        ),
                        consumption_mode="typed_binding",
                        runtime_input_targets=(runtime_input,),
                        runtime_input_required=(
                            public_arg.required
                            or adapter_binding.required
                        ),
                        input_binding=adapter_binding,
                    )
                )
        ordered = tuple(sorted(bindings, key=lambda item: item.key))
        relation_bindings = tuple(
            sorted(
                (
                    relation
                    for call in calls
                    for relation in call.relation_bindings
                ),
                key=lambda item: (
                    item.call_id,
                    item.point_arg_name,
                    item.point_item_index,
                    item.curve_arg_name,
                    item.condition_id,
                ),
            )
        )
        return FunctionalBindingContext(
            bindings=ordered,
            binding_signature=_binding_signature(
                ordered,
                relation_bindings=relation_bindings,
            ),
            relation_bindings=relation_bindings,
            typed_input_omissions=tuple(sorted(set(omissions))),
        )


    def _value_binding(
        self,
        *,
        call_id: str,
        capability_id: str,
        arg_name: str,
        item_index: int,
        spec: Any,
        binding_authority: FunctionalArgBindingAuthority,
        selection_policy: FunctionalArgSelectionPolicy | None,
        value: ResolvedFunctionalValue,
        source: FunctionalArgSourceIdentity,
        runtime_targets: tuple[str, ...],
        consumption_mode: FunctionalArgConsumptionMode,
        force_exact_source_versions: bool = False,
        input_binding: MethodInputBindingSpec | None = None,
    ) -> FunctionalArgBinding:
        if not runtime_targets and consumption_mode == "runtime_input":
            raise FunctionalBindingContextError(
                "planner.functional_runtime_input_mapping_drift",
                f"{call_id}.{arg_name} has no runtime input target",
            )
        debug_materialized_value = (
            not force_exact_source_versions
            and value.materialized_runtime_type is not None
        )
        if (
            spec.requires_materialized_state
            and source.kind not in {"state_version", "call_result"}
            and not debug_materialized_value
        ):
            raise FunctionalBindingContextError(
                "planner.functional_arg_version_drift",
                f"materialized arg {call_id}.{arg_name}[{item_index}] has no StateVersionId",
            )
        selection: FunctionalArgSelectionPolicy
        if force_exact_source_versions and source.kind == "state_version":
            selection = "exact"
        elif selection_policy is not None:
            selection = selection_policy
        elif source.kind == "math_object":
            selection = "identity_only"
        elif binding_authority == "resolver":
            selection = "latest"
        else:
            selection = "exact"
        return FunctionalArgBinding(
            key=FunctionalArgBindingKey(call_id, arg_name, item_index),
            capability_id=capability_id,
            semantic_role=spec.semantic_role or arg_name,
            binding_authority=binding_authority,
            cardinality=spec.cardinality,
            runtime_type=value.runtime_type or spec.runtime_type,
            source=source,
            selection_policy=selection,
            consumption_mode=consumption_mode,
            runtime_input_targets=runtime_targets,
            # Once a public/resolver value has been selected, the compiler
            # must consume it even when the public argument was optional.
            runtime_input_required=True,
            input_binding=input_binding,
        )


def _typed_input_selected_source(
    *,
    arg_name: str,
    binding: MethodInputBindingSpec,
    runtime_input: str | None,
    required: bool,
    capability: Any,
    call: FunctionalCallReconciliation,
    calls_by_id: Mapping[str, FunctionalCallReconciliation],
    object_registry: MathObjectRegistry | None,
    handle_registry: CanonicalHandleRegistry | None,
    method_specs: MethodSpecRegistry | None,
    allow_missing_typed_source: bool = False,
    condition_authority_index: ConditionBindingAuthorityIndex | None = None,
    _stack: tuple[str, ...] = (),
) -> FunctionalArgSourceIdentity | None:
    """Resolve one strict declaration without invoking a selector.

    Every declared evidence channel is authoritative.  Absence may omit an
    optional input; disagreement is always a contract drift, including for an
    optional slot.
    """

    input_name = runtime_input or binding.input_name
    if input_name in _stack:
        raise FunctionalBindingContextError(
            "planner.method_input_view_authority_drift",
            f"cyclic typed input derivation: {_stack + (input_name,)}",
        )
    input_spec = _method_input_spec(
        capability,
        input_name=input_name,
        method_specs=method_specs,
    )
    channels: list[tuple[str, tuple[FunctionalArgSourceIdentity, ...]]] = []

    def add(label: str, values: list[FunctionalArgSourceIdentity]) -> None:
        unique = {
            json.dumps(item.to_payload(), sort_keys=True): item
            for item in values
        }
        if unique:
            channels.append((label, tuple(unique.values())))

    def resolved_sources(
        source_arg: str,
        *,
        identity: bool = False,
    ) -> list[FunctionalArgSourceIdentity]:
        result: list[FunctionalArgSourceIdentity] = []
        for value in call.resolved_args.get(source_arg, ()):
            source = _source_for_input_view(
                value,
                input_spec=(
                    _identity_input_spec(input_spec) if identity else input_spec
                ),
                object_registry=object_registry,
            )
            if source is not None:
                result.append(source)
        return result

    def resolved_call_results(
        source_arg: str,
    ) -> list[FunctionalArgSourceIdentity]:
        return [
            FunctionalArgSourceIdentity(
                kind="call_result",
                source_call_id=value.source_call_id,
                source_return_name=value.return_name,
            )
            for value in call.resolved_args.get(source_arg, ())
            if value.source_call_id is not None and value.return_name is not None
        ]

    source = binding.source
    derivation = binding.derivation
    if isinstance(source, PublicArgSourceSpec):
        add(f"public_arg:{source.arg_name}", resolved_sources(source.arg_name))
    elif isinstance(source, LatestStateSourceSpec):
        latest_sources = resolved_sources(source.entity_arg)
        if not latest_sources and source.entity_arg != input_name:
            latest_sources = resolved_sources(input_name)
        add(
            f"latest_state:{source.entity_arg}",
            latest_sources,
        )
        return_names = tuple(
            item.name
            for item in capability.returns
            if item.identity_arg in {source.entity_arg, arg_name, input_name}
        )
        add(
            "previous_return_state",
            list(
                _allocation_sources_for_input_view(
                    call,
                    return_names=return_names,
                    expected_kind=getattr(
                        getattr(input_spec, "view", None),
                        "object_kind",
                        None,
                    ),
                    input_spec=input_spec,
                )
            ),
        )
    elif isinstance(source, EntityIdentitySourceSpec):
        if source.arg_name is not None:
            add(
                f"entity_arg:{source.arg_name}",
                resolved_sources(source.arg_name, identity=True),
            )
        else:
            add(
                "entity_roles:" + ",".join(source.semantic_roles),
                _visible_role_identity_sources(
                    source.semantic_roles,
                    call=call,
                    input_spec=input_spec,
                    object_registry=object_registry,
                    handle_registry=handle_registry,
                ),
            )
    elif isinstance(source, ExactCallResultSourceSpec):
        add(
            f"exact_call_result:{source.arg_name}",
            resolved_call_results(source.arg_name),
        )
    elif isinstance(source, ConditionSourceSpec):
        if source.arg_name is not None:
            add(
                f"condition_arg:{source.arg_name}",
                resolved_sources(source.arg_name),
            )
        else:
            add(
                f"resolved_condition:{arg_name}",
                resolved_sources(arg_name),
            )
            if condition_authority_index is None:
                if required and not allow_missing_typed_source:
                    raise FunctionalBindingContextError(
                        "planner.method_input_view_authority_missing",
                        (
                            f"{call.call_id}.{arg_name} requires a Condition "
                            "authority index"
                        ),
                    )
            else:
                related_ids: list[MathObjectId] = []
                related_refs: list[str] = []
                for related_arg in source.related_args:
                    values = call.resolved_args.get(related_arg, ())
                    if not values:
                        related_source = _typed_source_for_named_input(
                            related_arg,
                            capability=capability,
                            call=call,
                            calls_by_id=calls_by_id,
                            object_registry=object_registry,
                            handle_registry=handle_registry,
                            method_specs=method_specs,
                            allow_missing_typed_source=allow_missing_typed_source,
                            condition_authority_index=condition_authority_index,
                            stack=_stack + (input_name,),
                        )
                        related_identity = _source_object_identity(related_source)
                        if (
                            related_identity is not None
                            and related_identity.math_object_id is not None
                        ):
                            related_ids.append(related_identity.math_object_id)
                            continue
                        if not required or allow_missing_typed_source:
                            return None
                        raise FunctionalBindingContextError(
                            "planner.method_input_view_authority_missing",
                            (
                                f"{call.call_id}.{arg_name} requires related "
                                f"argument {related_arg!r}"
                            ),
                        )
                    identities = unique_ordered(
                        value.math_object_id
                        or (
                            object_registry.resolve(
                                value.object_ref or value.handle
                            )
                            if object_registry is not None
                            else None
                        )
                        for value in values
                    )
                    identities = tuple(
                        item for item in identities if item is not None
                    )
                    refs = unique_ordered(
                        value.object_ref or value.handle for value in values
                    )
                    if len(identities) > 1 or len(refs) > 1:
                        raise FunctionalBindingContextError(
                            "planner.method_input_view_authority_drift",
                            (
                                f"{call.call_id}.{arg_name} related arg "
                                f"{related_arg!r} is ambiguous"
                            ),
                        )
                    if identities:
                        related_ids.extend(identities)
                    else:
                        related_refs.extend(refs)
                try:
                    authority = condition_authority_index.resolve_relation(
                        condition_kinds=source.condition_kinds,
                        related_object_ids=tuple(related_ids),
                        related_object_refs=tuple(related_refs),
                        scope_id=call.scope_id,
                    )
                except ConditionBindingAuthorityError as exc:
                    if not required and exc.code.endswith("_missing"):
                        # Optional means that no evidence may be omitted. It
                        # never turns ambiguous or conflicting evidence into
                        # an omission.
                        return None
                    code = (
                        "planner.method_input_view_authority_missing"
                        if exc.code.endswith("_missing")
                        else "planner.method_input_view_authority_drift"
                    )
                    raise FunctionalBindingContextError(
                        code,
                        (
                            f"{call.call_id}.{arg_name} Condition authority "
                            f"cannot be finalized: {exc}; details={dict(exc.details)}"
                        ),
                    ) from exc
                add(
                    "condition_relation",
                    [
                        FunctionalArgSourceIdentity(
                            kind="condition",
                            condition_id=authority.condition_id,
                        )
                    ],
                )
    elif isinstance(source, ExactParameterSubstitutionSourceSpec):
        target_ids = _exact_parameter_target_ids(
            source.target_input,
            capability=capability,
            call=call,
            calls_by_id=calls_by_id,
            object_registry=object_registry,
            handle_registry=handle_registry,
            method_specs=method_specs,
            allow_missing_typed_source=allow_missing_typed_source,
            condition_authority_index=condition_authority_index,
            stack=_stack + (input_name,),
        )
        add(
            "exact_parameter_substitution",
            _exact_parameter_substitution_sources(
                source.source_inputs,
                target_ids=target_ids,
                call=call,
                scope_id=call.scope_id,
                handle_registry=handle_registry,
            ),
        )
    elif isinstance(source, ProducerLinkedSourceSpec):
        linked_sources = _producer_linked_sources(
            source.source_arg,
            source.producer_arg,
            call=call,
            calls_by_id=calls_by_id,
            input_spec=input_spec,
            object_registry=object_registry,
        )
        linked_kinds = {item.kind for item in linked_sources}
        # ``source_arg`` identifies which producer edge to follow. It is also
        # an independent identity witness only when its typed view has the
        # same authority shape as the producer role (for example a
        # ParameterValue and its Symbol). A Condition CallResult leading to a
        # Point role is routing evidence, not a competing Point source.
        add(
            f"arg:{source.source_arg}",
            [
                item
                for item in resolved_sources(source.source_arg)
                if item.kind in linked_kinds
            ],
        )
        add(
            f"producer_arg:{source.producer_arg}",
            linked_sources,
        )
    elif isinstance(source, MacroPreparedRoleSourceSpec):
        if getattr(capability.source, "execution_mode", None) != "runtime_search":
            raise FunctionalBindingContextError(
                "planner.method_input_binding_lowerer_missing",
                (
                    f"{call.call_id}.{arg_name} declares Macro role "
                    f"{source.role!r} outside a runtime-search Macro"
                ),
            )
        # Runtime-search roles stay pending until shadow execution chooses a
        # winner. Authored hints are deliberately not source authority.
        return None
    elif isinstance(derivation, CanonicalSymbolDerivationSpec):
        if object_registry is not None:
            object_id = object_registry.resolve(
                f"symbol:{derivation.symbol_name}"
            ) or object_registry.resolve(derivation.symbol_name)
            if object_id is not None:
                add(
                    f"canonical_symbol:{derivation.symbol_name}",
                    [
                        FunctionalArgSourceIdentity(
                            kind="math_object",
                            math_object_id=object_id,
                        )
                    ],
                )
    elif isinstance(
        derivation,
        (CoefficientExtractionDerivationSpec, OrdinalZeroTemplateDerivationSpec),
    ):
        upstream = _typed_source_for_named_input(
            derivation.source_input,
            capability=capability,
            call=call,
            calls_by_id=calls_by_id,
            object_registry=object_registry,
            handle_registry=handle_registry,
            method_specs=method_specs,
            allow_missing_typed_source=allow_missing_typed_source,
            condition_authority_index=condition_authority_index,
            stack=_stack + (input_name,),
        )
        if upstream is not None:
            add(f"derived_from:{derivation.source_input}", [upstream])
    elif isinstance(derivation, PreviousOutputIdentityDerivationSpec):
        add(
            f"previous_output:{derivation.output_name}",
            list(
                _allocation_sources_for_input_view(
                    call,
                    return_names=(derivation.output_name,),
                    expected_kind=getattr(
                        getattr(input_spec, "view", None),
                        "object_kind",
                        None,
                    ),
                    input_spec=input_spec,
                )
            ),
        )
    elif isinstance(derivation, SourceObjectIdentityDerivationSpec):
        add(
            f"source_object_arg:{derivation.source_input}",
            [
                item
                for value in call.resolved_args.get(
                    derivation.source_input,
                    (),
                )
                if (
                    item := _source_for_input_view(
                        value,
                        input_spec=_identity_input_spec(input_spec),
                        object_registry=object_registry,
                    )
                )
                is not None
            ],
        )
        upstream = _typed_source_for_named_input(
            derivation.source_input,
            capability=capability,
            call=call,
            calls_by_id=calls_by_id,
            object_registry=object_registry,
            handle_registry=handle_registry,
            method_specs=method_specs,
            allow_missing_typed_source=allow_missing_typed_source,
            condition_authority_index=condition_authority_index,
            stack=_stack + (input_name,),
        )
        identity = _source_object_identity(
            upstream,
            calls_by_id=calls_by_id,
        )
        if identity is not None:
            add(
                f"source_object_authority:{derivation.source_input}",
                [identity],
            )
    elif isinstance(derivation, FreeSymbolBasisDerivationSpec):
        declared = resolved_sources(arg_name, identity=True)
        basis = _free_symbol_basis_sources(
            derivation.source_inputs,
            arg_name=arg_name,
            capability=capability,
            call=call,
            calls_by_id=calls_by_id,
            object_registry=object_registry,
            handle_registry=handle_registry,
        )
        add(
            f"resolved_arg:{arg_name}",
            declared,
        )
        if declared and basis:
            declared_keys = {
                _source_authority_key(item, input_spec=input_spec)
                for item in declared
            }
            basis_keys = {
                _source_authority_key(item, input_spec=input_spec)
                for item in basis
            }
            if not declared_keys.issubset(basis_keys):
                raise FunctionalBindingContextError(
                    "planner.method_input_view_authority_drift",
                    (
                        f"{call.call_id}.{arg_name} explicit parameter is "
                        "outside the typed free-symbol basis; evidence="
                        f"{_typed_evidence_payload([('resolved_arg', tuple(declared)), ('free_symbol_basis', tuple(basis))])}"
                    ),
                )
        elif not declared:
            add("free_symbol_basis", basis)

    ambiguous = tuple(label for label, values in channels if len(values) != 1)
    by_authority: dict[tuple[Any, ...], FunctionalArgSourceIdentity] = {}
    for _label, values in channels:
        for value in values:
            by_authority[_source_authority_key(value, input_spec=input_spec)] = value
    if ambiguous or len(by_authority) > 1:
        raise FunctionalBindingContextError(
            "planner.method_input_view_authority_drift",
            (
                f"{call.call_id}.{arg_name} typed evidence disagrees; "
                f"ambiguous_channels={ambiguous}, evidence="
                f"{_typed_evidence_payload(channels)}"
            ),
        )
    if by_authority:
        return next(iter(by_authority.values()))
    if required and not allow_missing_typed_source:
        raise FunctionalBindingContextError(
            "planner.method_input_view_authority_missing",
            (
                f"{call.call_id}.{arg_name} requires "
                f"{binding.to_payload()}"
            ),
        )
    return None


def _exact_parameter_target_ids(
    target_input: str,
    *,
    capability: Any,
    call: FunctionalCallReconciliation,
    calls_by_id: Mapping[str, FunctionalCallReconciliation],
    object_registry: MathObjectRegistry | None,
    handle_registry: CanonicalHandleRegistry | None,
    method_specs: MethodSpecRegistry | None,
    allow_missing_typed_source: bool,
    condition_authority_index: ConditionBindingAuthorityIndex | None,
    stack: tuple[str, ...],
) -> frozenset[MathObjectId]:
    result = {
        value.math_object_id
        or (
            object_registry.resolve(value.object_ref or value.handle)
            if object_registry is not None
            else None
        )
        for value in call.resolved_args.get(target_input, ())
    }
    result.discard(None)
    if not result:
        target_source = _typed_source_for_named_input(
            target_input,
            capability=capability,
            call=call,
            calls_by_id=calls_by_id,
            object_registry=object_registry,
            handle_registry=handle_registry,
            method_specs=method_specs,
            allow_missing_typed_source=allow_missing_typed_source,
            condition_authority_index=condition_authority_index,
            stack=stack,
        )
        target_identity = _source_object_identity(
            target_source,
            calls_by_id=calls_by_id,
        )
        if target_identity is not None and target_identity.math_object_id is not None:
            result.add(target_identity.math_object_id)
    if len(result) > 1:
        raise FunctionalBindingContextError(
            "planner.method_input_view_authority_drift",
            f"{call.call_id}.{target_input} has multiple target identities",
        )
    return frozenset(result)


def _exact_parameter_substitution_sources(
    source_inputs: tuple[str, ...],
    *,
    target_ids: frozenset[MathObjectId],
    call: FunctionalCallReconciliation,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry | None,
) -> list[FunctionalArgSourceIdentity]:
    """Collect ParameterValue pins only from declared exact input lineage."""

    versions: dict[StateVersionId, FunctionalArgSourceIdentity] = {}
    results: dict[tuple[str, str], FunctionalArgSourceIdentity] = {}
    for source_input in source_inputs:
        for value in call.resolved_args.get(source_input, ()):
            pinned_parameter_version = False
            candidate_versions = tuple(
                dict.fromkeys(
                    (
                        *((value.state_version_id,) if value.state_version_id else ()),
                        *value.source_version_ids,
                    )
                )
            )
            for version_id in candidate_versions:
                logical_key = version_id.slot_id.logical_key
                if logical_key.runtime_type != "ParameterValue":
                    continue
                if logical_key.object_id in target_ids:
                    continue
                if (
                    handle_registry is not None
                    and not visible_from_valid_scope(
                        version_id.slot_id.storage_scope_id,
                        scope_id=scope_id,
                        registry=handle_registry,
                    )
                ):
                    continue
                versions[version_id] = FunctionalArgSourceIdentity(
                    kind="state_version",
                    state_version_id=version_id,
                )
                pinned_parameter_version = True
            if (
                not pinned_parameter_version
                and value.runtime_type == "ParameterValue"
                and value.source_call_id is not None
                and value.return_name is not None
                and value.math_object_id not in target_ids
            ):
                key = (value.source_call_id, value.return_name)
                results[key] = FunctionalArgSourceIdentity(
                    kind="call_result",
                    source_call_id=value.source_call_id,
                    source_return_name=value.return_name,
                )
    return [*versions.values(), *results.values()]


def _typed_binding_selection_policy(
    binding: MethodInputBindingSpec,
    *,
    capability: Any,
    runtime_input: str | None,
    method_specs: MethodSpecRegistry | None,
) -> FunctionalArgSelectionPolicy:
    input_spec = _method_input_spec(
        capability,
        input_name=runtime_input or binding.input_name,
        method_specs=method_specs,
    )
    mode = getattr(getattr(input_spec, "view", None), "mode", None)
    if mode == "identity":
        return "identity_only"
    if mode in {"latest_state", "immutable_value", "exact_result"}:
        # F5-C pins the concrete source before the derived v1 invocation.
        return "exact"
    raise FunctionalBindingContextError(
        "planner.method_input_view_authority_drift",
        (
            f"typed input {binding.input_name} has unsupported view mode "
            f"{mode!r}"
        ),
    )


def _method_input_spec(
    capability: Any,
    *,
    input_name: str,
    method_specs: MethodSpecRegistry | None,
) -> Any | None:
    method_id = getattr(capability.source, "method_id", None)
    if method_specs is None or not isinstance(method_id, str):
        return None
    try:
        return method_specs.require(method_id).inputs.get(input_name)
    except KeyError:
        return None


def _declared_typed_runtime_type(
    capability: Any,
    *,
    runtime_input: str,
    method_specs: MethodSpecRegistry | None,
) -> str:
    input_spec = _method_input_spec(
        capability,
        input_name=runtime_input,
        method_specs=method_specs,
    )
    return (
        input_spec.runtime_type
        if input_spec is not None
        else "compiler_owned"
    )


def _identity_input_spec(input_spec: Any | None) -> Any | None:
    if input_spec is None:
        return None
    view = getattr(input_spec, "view", None)
    if view is None:
        return input_spec
    return type("_IdentityInput", (), {
        "view": type("_IdentityView", (), {"mode": "identity"})()
    })()


def _typed_source_for_named_input(
    input_name: str,
    *,
    capability: Any,
    call: FunctionalCallReconciliation,
    calls_by_id: Mapping[str, FunctionalCallReconciliation],
    object_registry: MathObjectRegistry | None,
    handle_registry: CanonicalHandleRegistry | None,
    method_specs: MethodSpecRegistry | None,
    allow_missing_typed_source: bool,
    condition_authority_index: ConditionBindingAuthorityIndex | None,
    stack: tuple[str, ...],
) -> FunctionalArgSourceIdentity | None:
    input_spec = _method_input_spec(
        capability,
        input_name=input_name,
        method_specs=method_specs,
    )
    values = call.resolved_args.get(input_name, ())
    if values:
        sources = tuple(
            _source_for_input_view(
                value,
                input_spec=input_spec,
                object_registry=object_registry,
            )
            for value in values
        )
        sources = tuple(item for item in sources if item is not None)
        if len(sources) == 1:
            return sources[0]
        if len(sources) > 1:
            raise FunctionalBindingContextError(
                "planner.method_input_view_authority_drift",
                f"{call.call_id}.{input_name} has multiple typed sources",
            )
    candidates = tuple(
        item
        for item in capability.auto_args
        if item.name == input_name or item.runtime_input == input_name
    )
    if len(candidates) == 1:
        item = candidates[0]
        return _typed_input_selected_source(
            arg_name=item.name,
            binding=item.input_binding,
            runtime_input=item.runtime_input,
            required=item.required,
            capability=capability,
            call=call,
            calls_by_id=calls_by_id,
            object_registry=object_registry,
            handle_registry=handle_registry,
            method_specs=method_specs,
            allow_missing_typed_source=allow_missing_typed_source,
            condition_authority_index=condition_authority_index,
            _stack=stack,
        )
    declarations = tuple(
        item
        for item in capability.input_bindings
        if item.input_name == input_name
    )
    public_args = tuple(
        item
        for item in capability.args
        if (item.runtime_input or item.name) == input_name
    )
    if len(declarations) == 1 and len(public_args) == 1:
        declaration = declarations[0]
        public_arg = public_args[0]
        return _typed_input_selected_source(
            arg_name=public_arg.name,
            binding=declaration,
            runtime_input=input_name,
            required=public_arg.required or declaration.required,
            capability=capability,
            call=call,
            calls_by_id=calls_by_id,
            object_registry=object_registry,
            handle_registry=handle_registry,
            method_specs=method_specs,
            allow_missing_typed_source=allow_missing_typed_source,
            condition_authority_index=condition_authority_index,
            _stack=stack,
        )
    return None


def _source_object_identity(
    source: FunctionalArgSourceIdentity | None,
    *,
    calls_by_id: Mapping[str, FunctionalCallReconciliation] | None = None,
) -> FunctionalArgSourceIdentity | None:
    if source is None:
        return None
    object_id = source.math_object_id
    if object_id is None and source.state_version_id is not None:
        object_id = source.state_version_id.slot_id.logical_key.object_id
    if (
        object_id is None
        and calls_by_id is not None
        and source.source_call_id is not None
        and source.source_return_name is not None
    ):
        producer = calls_by_id.get(source.source_call_id)
        return_object_ids = {
            (
                item.math_object_id
                or (
                    item.logical_state_key.object_id
                    if item.logical_state_key is not None
                    else None
                )
                or (
                    item.typed_slot_id.logical_key.object_id
                    if item.typed_slot_id is not None
                    else None
                )
                or (
                    item.selected_version_id.slot_id.logical_key.object_id
                    if item.selected_version_id is not None
                    else None
                )
                or (
                    item.previous_version_id.slot_id.logical_key.object_id
                    if item.previous_version_id is not None
                    else None
                )
            )
            for item in (producer.returns if producer is not None else ())
            if item.return_name == source.source_return_name
        }
        return_object_ids.discard(None)
        if len(return_object_ids) > 1:
            raise FunctionalBindingContextError(
                "planner.method_input_view_authority_drift",
                "exact result maps to multiple return object identities: "
                f"call={source.source_call_id}, "
                f"return={source.source_return_name}",
            )
        if return_object_ids:
            object_id = next(iter(return_object_ids))
    if object_id is None:
        return None
    return FunctionalArgSourceIdentity(
        kind="math_object",
        math_object_id=object_id,
    )


def _visible_role_identity_sources(
    roles: tuple[str, ...],
    *,
    call: FunctionalCallReconciliation,
    input_spec: Any | None,
    object_registry: MathObjectRegistry | None,
    handle_registry: CanonicalHandleRegistry | None,
) -> list[FunctionalArgSourceIdentity]:
    if object_registry is None or handle_registry is None:
        return []
    expected_kind = getattr(getattr(input_spec, "view", None), "object_kind", None)
    result: list[FunctionalArgSourceIdentity] = []
    for handle, payload in handle_registry.entity_payloads.items():
        if payload.get("role") not in roles:
            continue
        if expected_kind is not None and payload.get("entity_type") != expected_kind:
            continue
        valid_scope = handle_registry.handle_valid_scopes.get(handle, "")
        if not visible_from_valid_scope(
            valid_scope,
            scope_id=call.scope_id,
            registry=handle_registry,
        ):
            continue
        object_id = object_registry.resolve(handle)
        if object_id is not None:
            result.append(
                FunctionalArgSourceIdentity(
                    kind="math_object",
                    math_object_id=object_id,
                )
            )
    return result


def _producer_linked_sources(
    source_arg: str,
    producer_arg: str,
    *,
    call: FunctionalCallReconciliation,
    calls_by_id: Mapping[str, FunctionalCallReconciliation],
    input_spec: Any | None,
    object_registry: MathObjectRegistry | None,
) -> list[FunctionalArgSourceIdentity]:
    result: list[FunctionalArgSourceIdentity] = []
    producer_ids = tuple(
        dict.fromkeys(
            value.source_call_id
            for value in call.resolved_args.get(source_arg, ())
            if value.source_call_id is not None
        )
    )
    for producer_id in producer_ids:
        producer = calls_by_id.get(producer_id)
        if producer is None:
            continue
        for value in producer.resolved_args.get(producer_arg, ()):
            source = _source_for_input_view(
                value,
                input_spec=input_spec,
                object_registry=object_registry,
            )
            if source is not None:
                result.append(source)
    return result


def _free_symbol_basis_sources(
    source_inputs: tuple[str, ...],
    *,
    arg_name: str,
    capability: Any,
    call: FunctionalCallReconciliation,
    calls_by_id: Mapping[str, FunctionalCallReconciliation],
    object_registry: MathObjectRegistry | None,
    handle_registry: CanonicalHandleRegistry | None,
) -> list[FunctionalArgSourceIdentity]:
    if object_registry is None:
        return []
    excluded_refs = {
        f"symbol:{item.input_binding.derivation.symbol_name}"
        for item in capability.auto_args
        if item.name != arg_name
        and item.input_binding is not None
        and isinstance(
            item.input_binding.derivation,
            CanonicalSymbolDerivationSpec,
        )
    }
    for other_name, values in call.resolved_args.items():
        if other_name == arg_name or other_name in source_inputs:
            continue
        for value in values:
            if value.runtime_type == "Symbol":
                excluded_refs.add(value.object_ref or value.handle)
    refs: set[str] = set()
    for source_input in source_inputs:
        values = call.resolved_args.get(source_input, ())
        for value in values:
            refs.update(value.free_symbol_refs)
            if value.runtime_type == "Symbol":
                refs.add(value.object_ref or value.handle)
            if value.state_version_id is not None:
                object_id = value.state_version_id.slot_id.logical_key.object_id
                if object_id.kind == "symbol":
                    refs.add(object_id.value)
            if value.source_call_id is not None:
                producer = calls_by_id.get(value.source_call_id)
                if producer is not None:
                    for producer_value in producer.resolved_args.get("parameter", ()):
                        refs.add(producer_value.object_ref or producer_value.handle)
    result: list[FunctionalArgSourceIdentity] = []
    for ref in sorted(refs - excluded_refs):
        if handle_registry is not None:
            valid_scope = handle_registry.handle_valid_scopes.get(ref, "")
            if valid_scope and not visible_from_valid_scope(
                valid_scope,
                scope_id=call.scope_id,
                registry=handle_registry,
            ):
                continue
        object_id = object_registry.resolve(ref)
        if object_id is not None and object_id.kind == "symbol":
            result.append(
                FunctionalArgSourceIdentity(
                    kind="math_object",
                    math_object_id=object_id,
                )
            )
    return result


def _source_authority_key(
    source: FunctionalArgSourceIdentity,
    *,
    input_spec: Any | None,
) -> tuple[Any, ...]:
    if getattr(getattr(input_spec, "view", None), "mode", None) == "identity":
        identity = _source_object_identity(source)
        if identity is not None:
            return ("math_object", identity.math_object_id)
    if source.state_version_id is not None:
        return ("state_version", source.state_version_id)
    if source.math_object_id is not None:
        return ("math_object", source.math_object_id)
    if source.condition_id is not None:
        return ("condition", source.condition_id)
    return ("call_result", source.source_call_id, source.source_return_name)


def _require_same_source_authority(
    observed: FunctionalArgSourceIdentity,
    expected: FunctionalArgSourceIdentity,
    *,
    call_id: str,
    arg_name: str,
) -> None:
    observed_identity = _source_object_identity(observed)
    expected_identity = _source_object_identity(expected)
    if (
        observed.to_payload() == expected.to_payload()
        or (
            observed_identity is not None
            and expected_identity is not None
            and observed_identity == expected_identity
        )
    ):
        return
    raise FunctionalBindingContextError(
        "planner.method_input_view_authority_drift",
        (
            f"{call_id}.{arg_name} resolved source disagrees with typed "
            f"binding: observed={observed.to_payload()}, "
            f"expected={expected.to_payload()}"
        ),
    )


def _require_resolved_value_matches_source_authority(
    value: ResolvedFunctionalValue,
    observed: FunctionalArgSourceIdentity,
    expected: FunctionalArgSourceIdentity,
    *,
    call_id: str,
    arg_name: str,
) -> None:
    if (
        expected.kind == "state_version"
        and expected.state_version_id is not None
        and value.state_version_id == expected.state_version_id
    ):
        return
    if (
        expected.kind == "call_result"
        and value.source_call_id == expected.source_call_id
        and value.return_name == expected.source_return_name
    ):
        return
    if (
        expected.kind == "math_object"
        and expected.math_object_id is not None
        and value.math_object_id == expected.math_object_id
    ):
        return
    _require_same_source_authority(
        observed,
        expected,
        call_id=call_id,
        arg_name=arg_name,
    )


def _typed_evidence_payload(
    channels: list[tuple[str, tuple[FunctionalArgSourceIdentity, ...]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        label: [item.to_payload() for item in values]
        for label, values in channels
    }


def _source_for_input_view(
    value: ResolvedFunctionalValue,
    *,
    input_spec: Any | None,
    object_registry: MathObjectRegistry | None,
) -> FunctionalArgSourceIdentity | None:
    if getattr(getattr(input_spec, "view", None), "mode", None) == "identity":
        object_id = value.math_object_id
        if object_id is None and object_registry is not None:
            object_id = object_registry.resolve(value.object_ref or value.handle)
        if object_id is None:
            return None
        return FunctionalArgSourceIdentity(
            kind="math_object",
            math_object_id=object_id,
        )
    return _source_identity(value, object_registry=object_registry)


def _allocation_sources_for_input_view(
    call: FunctionalCallReconciliation,
    *,
    return_names: tuple[str, ...],
    expected_kind: str | None,
    input_spec: Any | None,
) -> tuple[FunctionalArgSourceIdentity, ...]:
    view_mode = getattr(getattr(input_spec, "view", None), "mode", None)
    if view_mode == "latest_state":
        return tuple(
            FunctionalArgSourceIdentity(
                kind="state_version",
                state_version_id=allocation.previous_version_id,
            )
            for allocation in call.returns
            if allocation.return_name in return_names
            and allocation.previous_version_id is not None
            and (
                expected_kind is None
                or allocation.previous_version_id.slot_id.logical_key.object_id.kind
                == expected_kind
            )
        )
    return tuple(
        FunctionalArgSourceIdentity(
            kind="math_object",
            math_object_id=allocation.math_object_id,
        )
        for allocation in call.returns
        if allocation.return_name in return_names
        and allocation.math_object_id is not None
        and (
            expected_kind is None
            or allocation.math_object_id.kind == expected_kind
        )
    )


def _wire_resolution_policy_for_view(
    spec: Any,
) -> FunctionalArgSelectionPolicy:
    """Describe pre-finalization wire intent, not runtime read policy.

    ``latest`` means that a SourceRef requests the latest lexically visible
    state during F5-C finalization.  A catalog-backed build converts the
    selected state to an exact source in ``_value_binding``; compiler and
    runtime consumers must never interpret this value as permission to
    reselect latest state.
    """

    mode = getattr(spec, "input_view_mode", None)
    if mode == "identity":
        return "identity_only"
    if mode == "latest_state":
        return "latest"
    if mode in {"immutable_value", "exact_result"}:
        return "exact"
    raise FunctionalBindingContextError(
        "planner.functional_arg_role_drift",
        f"arg {getattr(spec, 'name', '<unknown>')} has no input view contract",
    )


def _source_identity(
    value: ResolvedFunctionalValue,
    *,
    object_registry: MathObjectRegistry | None,
    prefer_call_result: bool = False,
) -> FunctionalArgSourceIdentity:
    if (
        prefer_call_result
        and value.source_call_id is not None
        and value.return_name is not None
    ):
        return FunctionalArgSourceIdentity(
            kind="call_result",
            source_call_id=value.source_call_id,
            source_return_name=value.return_name,
        )
    if value.condition_id is not None:
        return FunctionalArgSourceIdentity(kind="condition", condition_id=value.condition_id)
    if value.state_version_id is not None:
        return FunctionalArgSourceIdentity(
            kind="state_version",
            state_version_id=value.state_version_id,
        )
    if value.source_call_id is not None and value.return_name is not None:
        return FunctionalArgSourceIdentity(
            kind="call_result",
            source_call_id=value.source_call_id,
            source_return_name=value.return_name,
        )
    if value.math_object_id is not None:
        return FunctionalArgSourceIdentity(
            kind="math_object",
            math_object_id=value.math_object_id,
        )
    if object_registry is not None:
        object_id = object_registry.resolve(value.handle)
        if object_id is not None:
            return FunctionalArgSourceIdentity(
                kind="math_object",
                math_object_id=object_id,
            )
    raise FunctionalBindingContextError(
        "planner.functional_binding_context_incomplete",
        f"resolved value {value.handle} has no typed source identity",
    )


def _runtime_mapping(
    source: Any,
    *,
    arg_name: str,
    runtime_input: str | None,
    item_index: int,
    item_count: int,
    consumption_mode: str,
) -> tuple[tuple[str, ...], FunctionalArgConsumptionMode]:
    if consumption_mode == "resolver_evidence":
        return (), "resolver_evidence"
    target = runtime_input or arg_name
    adapter = getattr(source, "adapter", None)
    if adapter is None:
        return (target,), "runtime_input"
    aliases = dict(getattr(adapter, "input_aliases", ()))
    if arg_name in aliases:
        return (aliases[arg_name],), "runtime_input"
    for aggregate in getattr(adapter, "aggregate_input_bindings", ()):
        if aggregate.source_input == arg_name:
            if item_count == 1 and aggregate.singleton_input is not None:
                return (aggregate.singleton_input,), "runtime_input"
            if item_index >= len(aggregate.item_inputs):
                if not aggregate.item_inputs:
                    return (target,), "runtime_input"
                raise FunctionalBindingContextError(
                    "planner.functional_runtime_input_mapping_drift",
                    f"aggregate {arg_name}[{item_index}] exceeds declared runtime targets",
                )
            return (aggregate.item_inputs[item_index],), "runtime_input"
    for aggregate in getattr(adapter, "scalar_aggregate_lowerings", ()):
        if aggregate.source_input == arg_name:
            if item_count == 1:
                return (
                    (aggregate.identity_input, aggregate.value_input),
                    "runtime_input",
                )
            return (target,), "runtime_input"
    return (target,), "runtime_input"


def _binding_declared_source_args(
    binding: MethodInputBindingSpec,
) -> tuple[str, ...]:
    """Return explicit call-argument links without inferring semantic roles."""

    source = binding.source
    if isinstance(source, PublicArgSourceSpec):
        return (source.arg_name,)
    if isinstance(source, EntityIdentitySourceSpec):
        return (source.arg_name,) if source.arg_name is not None else ()
    if isinstance(source, LatestStateSourceSpec):
        return (source.entity_arg,)
    if isinstance(source, ConditionSourceSpec):
        return (source.arg_name,) if source.arg_name is not None else ()
    if isinstance(source, ExactCallResultSourceSpec):
        return (source.arg_name,)
    if isinstance(source, ExactParameterSubstitutionSourceSpec):
        return source.source_inputs
    return ()


def _binding_signature(
    bindings: tuple[FunctionalArgBinding, ...],
    *,
    relation_bindings: tuple[FunctionalMethodRelationBinding, ...] = (),
    include_call_id: bool = True,
) -> str:
    binding_payload = [item.to_payload() for item in bindings]
    relation_payload = [item.to_payload() for item in relation_bindings]
    if not include_call_id:
        for item in binding_payload:
            item["key"].pop("call_id", None)
        for item in relation_payload:
            item.pop("call_id", None)
    payload: Any = (
        {
            "bindings": binding_payload,
            "relation_bindings": relation_payload,
        }
        if relation_payload
        else binding_payload
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def call_binding_signatures(
    context: FunctionalBindingContext,
) -> Mapping[str, str]:
    call_ids = tuple(dict.fromkeys(item.key.call_id for item in context.bindings))
    return {call_id: context.signature_for_call(call_id) for call_id in call_ids}


def build_functional_runtime_arg_bindings_from_context(
    calls: tuple[FunctionalCallReconciliation, ...],
    context: FunctionalBindingContext,
) -> tuple[ProjectedFunctionArgBinding, ...]:
    """Project the authoritative ledger into direct-compiler bindings."""

    values_by_key = {
        (call.call_id, arg_name, item_index): value
        for call in calls
        for arg_name, values in call.resolved_args.items()
        for item_index, value in enumerate(values)
    }
    projected: list[ProjectedFunctionArgBinding] = []
    for binding in context.bindings:
        value = values_by_key.get(
            (
                binding.key.call_id,
                binding.key.arg_name,
                binding.key.item_index,
            )
        )
        strict_source = binding.source
        strict_math_object_id = _source_math_object_id(strict_source)
        projected.append(
            ProjectedFunctionArgBinding(
                step_id=binding.key.call_id,
                arg_name=binding.key.arg_name,
                source_handle=(
                    value.handle
                    if value is not None
                    else (_binding_source_handle(binding) or "")
                ),
                runtime_type=(
                    value.runtime_type
                    if value is not None
                    else binding.runtime_type
                ),
                state_slot_id=(
                    value.state_slot_id if value is not None else None
                ),
                object_ref=(
                    value.object_ref
                    if value is not None
                    else (
                        strict_math_object_id.value
                        if strict_math_object_id is not None
                        else None
                    )
                ),
                math_object_id=(
                    strict_math_object_id
                    or (value.math_object_id if value is not None else None)
                ),
                state_version_id=(
                    strict_source.state_version_id
                    or (value.state_version_id if value is not None else None)
                ),
                condition_id=(
                    strict_source.condition_id
                    or (value.condition_id if value is not None else None)
                ),
                source_call_id=(
                    strict_source.source_call_id
                    or (value.source_call_id if value is not None else None)
                ),
                source_return_name=(
                    strict_source.source_return_name
                    or (value.return_name if value is not None else None)
                ),
                binding_authority=binding.binding_authority,
                semantic_role=binding.semantic_role,
                cardinality=binding.cardinality,
                item_index=binding.key.item_index,
                selection_policy=binding.selection_policy,
                consumption_mode=binding.consumption_mode,
                runtime_input_targets=binding.runtime_input_targets,
                runtime_input_required=binding.runtime_input_required,
                input_binding=binding.input_binding,
            )
        )
    return tuple(projected)


def _source_math_object_id(
    source: FunctionalArgSourceIdentity,
) -> MathObjectId | None:
    if source.math_object_id is not None:
        return source.math_object_id
    if source.state_version_id is not None:
        return source.state_version_id.slot_id.logical_key.object_id
    return None


@dataclass(frozen=True)
class FunctionalBindingProjectionAudit:
    decisions: tuple[dict[str, Any], ...]
    mismatches: tuple[dict[str, Any], ...]
    legacy_fallback_count: int


@dataclass(frozen=True)
class FunctionalBindingConsumptionAudit:
    decisions: tuple[dict[str, Any], ...]
    mismatches: tuple[dict[str, Any], ...]


def audit_functional_arg_binding_projection(
    context: FunctionalBindingContext,
    projected: tuple[ProjectedFunctionArgBinding, ...],
) -> FunctionalBindingProjectionAudit:
    """Compare the compatibility projection with the typed ledger fail-closed."""

    projected_by_key = {
        (item.step_id, item.arg_name, item.item_index): item
        for item in projected
    }
    decisions: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    fallback_count = 0
    expected_keys: set[tuple[str, str, int]] = set()
    for binding in context.bindings:
        key = (
            binding.key.call_id,
            binding.key.arg_name,
            binding.key.item_index,
        )
        # An omitted optional typed input has no ledger row. Every finalized
        # binding that reaches the derived v1 IR is audited like any other
        # exact source.
        if (
            binding.binding_authority == "compiler"
            and key not in projected_by_key
        ):
            continue
        expected_keys.add(key)
        item = projected_by_key.get(key)
        details: list[str] = []
        if item is None:
            details.append("projected_binding_missing")
        else:
            if item.semantic_role is None:
                fallback_count += 1
                details.append("legacy_role_fallback_required")
            if (item.semantic_role or item.arg_name) != binding.semantic_role:
                details.append("semantic_role")
            if item.binding_authority != binding.binding_authority:
                details.append("binding_authority")
            if item.cardinality != binding.cardinality:
                details.append("cardinality")
            if item.selection_policy != binding.selection_policy:
                details.append("selection_policy")
            if item.runtime_input_targets != binding.runtime_input_targets:
                details.append("runtime_input_targets")
            if _projected_source_payload(
                item,
                expected_kind=binding.source.kind,
            ) != binding.source.to_payload():
                details.append("source_identity")
        decision = {
            "call_id": binding.key.call_id,
            "arg_name": binding.key.arg_name,
            "item_index": binding.key.item_index,
            "matches": not details,
            "details": details,
        }
        decisions.append(decision)
        if details:
            mismatches.append(
                {
                    **decision,
                    "code": "planner.functional_runtime_input_mapping_drift",
                }
            )
    for key in sorted(set(projected_by_key) - expected_keys):
        mismatches.append(
            {
                "call_id": key[0],
                "arg_name": key[1],
                "item_index": key[2],
                "matches": False,
                "details": ["unexpected_projected_binding"],
                "code": "planner.functional_binding_authority_drift",
            }
        )
    return FunctionalBindingProjectionAudit(
        decisions=tuple(decisions),
        mismatches=tuple(mismatches),
        legacy_fallback_count=fallback_count,
    )


def audit_compiled_functional_arg_consumption(
    bindings: tuple[FunctionalArgBinding, ...],
    plans: tuple[Any, ...],
    *,
    expected_runtime_paths: Mapping[FunctionalArgBindingKey, str | None],
    arg_repairs: tuple[Any, ...] = (),
) -> FunctionalBindingConsumptionAudit:
    """Compare ledger targets with compiler-produced invocation inputs."""

    inputs_by_qualified_target: dict[
        str,
        list[tuple[str, tuple[str, ...]]],
    ] = {}
    inputs_by_name: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    source_paths_by_output: dict[str, tuple[str, ...]] = {}
    for plan in plans:
        for invocation in plan.invocations:
            invocation_sources = tuple(
                dict.fromkeys(
                    path
                    for value in invocation.inputs.values()
                    for path in _runtime_input_paths(value)
                )
            )
            for output_path in invocation.outputs.values():
                source_paths_by_output[output_path] = invocation_sources
            for input_name, value in invocation.inputs.items():
                item = (
                    invocation.invocation_id,
                    _runtime_input_paths(value),
                )
                inputs_by_qualified_target.setdefault(
                    f"{invocation.method_id}.{input_name}",
                    [],
                ).append(item)
                inputs_by_name.setdefault(input_name, []).append(item)

    all_runtime_paths = tuple(
        path
        for candidates in inputs_by_name.values()
        for _invocation_id, paths in candidates
        for path in paths
    )
    bindings_by_arg: dict[str, list[FunctionalArgBinding]] = {}
    for binding in bindings:
        bindings_by_arg.setdefault(binding.key.arg_name, []).append(binding)
    repairs_by_arg: dict[str, Any] = {}
    for repair in arg_repairs:
        arg_name = getattr(repair, "arg_name", None)
        if not isinstance(arg_name, str):
            continue
        selected_handles = tuple(
            item
            for item in getattr(repair, "source_handles", ())
            if isinstance(item, str)
        )
        declared = {
            handle: expected_runtime_paths.get(binding.key)
            for binding in bindings_by_arg.get(arg_name, ())
            for handle in (_binding_source_handle(binding),)
            if handle is not None
        }
        if any(handle not in declared for handle in selected_handles):
            continue
        if any(
            expected_path is None
            or not any(
                _runtime_path_descends_from(
                    path,
                    expected_path,
                    source_paths_by_output,
                )
                for path in all_runtime_paths
            )
            for handle in selected_handles
            for expected_path in (declared[handle],)
        ):
            continue
        repairs_by_arg[arg_name] = repair

    decisions: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    target_counts: dict[str, int] = {}
    for binding in bindings:
        for target in binding.runtime_input_targets:
            target_counts[target] = target_counts.get(target, 0) + 1
    for binding in bindings:
        arg_repair = repairs_by_arg.get(binding.key.arg_name)
        if binding.consumption_mode == "resolver_evidence":
            decisions.append(
                {
                    "call_id": binding.key.call_id,
                    "arg_name": binding.key.arg_name,
                    "item_index": binding.key.item_index,
                    "semantic_role": binding.semantic_role,
                    "binding_authority": binding.binding_authority,
                    "consumption_mode": binding.consumption_mode,
                    "runtime_target": None,
                    "expected_runtime_path": None,
                    "actual_runtime_paths": [],
                    "invocation_ids": [],
                    "matches": True,
                    "details": [],
                }
            )
            continue
        candidates_by_target: dict[
            str,
            tuple[tuple[str, tuple[str, ...]], ...],
        ] = {}
        for target in binding.runtime_input_targets:
            candidates = (
                inputs_by_qualified_target.get(target, ())
                if "." in target
                else inputs_by_name.get(target, ())
            )
            candidates_by_target[target] = tuple(candidates)
        expected_path = (
            expected_runtime_paths.get(binding.key)
            if all(
                target_counts.get(target, 0) == 1
                for target in binding.runtime_input_targets
            )
            else None
        )
        source_path_matched = (
            expected_path is None
            or any(
                any(
                    _runtime_path_descends_from(
                        path,
                        expected_path,
                        source_paths_by_output,
                    )
                    or (
                        binding.selection_policy == "identity_only"
                        and _runtime_identity_paths_equivalent(
                            path,
                            expected_path,
                        )
                    )
                    for path in paths
                )
                for candidates in candidates_by_target.values()
                for _invocation_id, paths in candidates
            )
        )
        for target_index, target in enumerate(binding.runtime_input_targets):
            candidates = candidates_by_target[target]
            details: list[str] = []
            if (
                not candidates
                and binding.runtime_input_required
                and arg_repair is None
            ):
                details.append("runtime_target_not_consumed")
            actual_paths = tuple(
                dict.fromkeys(
                    path
                    for _invocation_id, paths in candidates
                    for path in paths
                )
            )
            if (
                target_index == 0
                and not source_path_matched
                and arg_repair is None
            ):
                details.append("runtime_source_path_drift")
            decision = {
                "call_id": binding.key.call_id,
                "arg_name": binding.key.arg_name,
                "item_index": binding.key.item_index,
                "semantic_role": binding.semantic_role,
                "binding_authority": binding.binding_authority,
                "consumption_mode": binding.consumption_mode,
                "runtime_input_required": binding.runtime_input_required,
                "runtime_target": target,
                "expected_runtime_path": expected_path,
                "actual_runtime_paths": list(actual_paths),
                "invocation_ids": [item[0] for item in candidates],
                "deterministic_arg_repair": (
                    arg_repair.to_payload()
                    if arg_repair is not None
                    else None
                ),
                "matches": not details,
                "details": details,
            }
            decisions.append(decision)
            if details:
                mismatches.append(
                    {
                        **decision,
                        "code": (
                            "planner.functional_runtime_input_mapping_drift"
                        ),
                    }
                )
    return FunctionalBindingConsumptionAudit(
        decisions=tuple(decisions),
        mismatches=tuple(mismatches),
    )


def _projected_source_payload(
    item: ProjectedFunctionArgBinding,
    *,
    expected_kind: FunctionalArgSourceKind,
) -> dict[str, Any]:
    if expected_kind == "condition" and item.condition_id is not None:
        return {"kind": "condition", "condition_id": item.condition_id}
    if (
        expected_kind == "call_result"
        and item.source_call_id is not None
        and item.source_return_name is not None
    ):
        return {
            "kind": "call_result",
            "source_call_id": item.source_call_id,
            "source_return_name": item.source_return_name,
        }
    if expected_kind == "state_version" and item.state_version_id is not None:
        return {
            "kind": "state_version",
            "state_version_id": item.state_version_id.to_payload(),
        }
    if expected_kind == "math_object" and item.math_object_id is not None:
        return {
            "kind": "math_object",
            "math_object_id": item.math_object_id.to_payload(),
        }
    return {"kind": "unresolved"}


def _binding_source_handle(binding: FunctionalArgBinding) -> str | None:
    source = binding.source
    if source.math_object_id is not None:
        return source.math_object_id.value
    if source.state_version_id is not None:
        return source.state_version_id.slot_id.logical_key.object_id.value
    if source.condition_id is not None:
        return source.condition_id
    if source.source_call_id is not None and source.source_return_name is not None:
        return f"{source.source_call_id}.{source.source_return_name}"
    return None


def _runtime_input_paths(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, tuple):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _runtime_path_descends_from(
    path: str,
    expected_source: str,
    source_paths_by_output: Mapping[str, tuple[str, ...]],
) -> bool:
    """Trace a compiler-owned temporary back to the selected typed input."""

    pending = [path]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == expected_source:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(source_paths_by_output.get(current, ()))
    return False


def _runtime_identity_paths_equivalent(path: str, expected_source: str) -> bool:
    """Accept immutable identity and mutable state views of one MathObject.

    The exact container may change from ``points`` to ``object_refs`` when a
    Point acquires a coordinate state.  Scope and object key must remain exact;
    this therefore cannot authorize a sibling object or a different entity.
    """

    try:
        actual = ContextPath.parse(path)
        expected = ContextPath.parse(expected_source)
    except ValueError:
        return False
    if (actual.scope_id, actual.key) != (expected.scope_id, expected.key):
        return False
    compatible_containers = {actual.container, expected.container}
    return compatible_containers <= {"points", "object_refs"}
