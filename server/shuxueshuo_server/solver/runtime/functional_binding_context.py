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
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.binding_selector_semantics import (
    selector_semantics,
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


FunctionalArgSelectionPolicy = Literal[
    "exact",
    "latest",
    "identity_only",
    "compiler",
]
FunctionalArgConsumptionMode = Literal[
    "runtime_input",
    "resolver_evidence",
    "compiler_selector",
]
FunctionalArgSourceKind = Literal[
    "state_version",
    "condition",
    "math_object",
    "call_result",
    "compiler_selector",
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


@dataclass(frozen=True)
class FunctionalArgSourceIdentity:
    kind: FunctionalArgSourceKind
    state_version_id: StateVersionId | None = None
    condition_id: str | None = None
    math_object_id: MathObjectId | None = None
    source_call_id: str | None = None
    source_return_name: str | None = None
    compiler_selector_id: str | None = None
    selected_source: FunctionalArgSourceIdentity | None = None

    def __post_init__(self) -> None:
        populated = {
            "state_version": self.state_version_id is not None,
            "condition": self.condition_id is not None,
            "math_object": self.math_object_id is not None,
            "call_result": (
                self.source_call_id is not None
                and self.source_return_name is not None
            ),
            "compiler_selector": self.compiler_selector_id is not None,
        }
        if not populated[self.kind] or sum(populated.values()) != 1:
            raise FunctionalBindingContextError(
                "planner.functional_binding_context_incomplete",
                f"source kind {self.kind} is not uniquely identified",
            )
        if self.selected_source is not None and self.kind != "compiler_selector":
            raise FunctionalBindingContextError(
                "planner.functional_binding_context_incomplete",
                "only compiler selectors may carry a selected typed source",
            )
        if (
            self.selected_source is not None
            and self.selected_source.kind == "compiler_selector"
        ):
            raise FunctionalBindingContextError(
                "planner.functional_binding_context_incomplete",
                "compiler selected source cannot contain another selector",
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
        if self.compiler_selector_id is not None:
            payload["compiler_selector_id"] = self.compiler_selector_id
        if self.selected_source is not None:
            payload["selected_source"] = self.selected_source.to_payload()
        return payload

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalArgSourceIdentity":
        kind = str(payload.get("kind", ""))
        state_version = payload.get("state_version_id")
        math_object = payload.get("math_object_id")
        selected = payload.get("selected_source")
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
            compiler_selector_id=(
                str(payload["compiler_selector_id"])
                if payload.get("compiler_selector_id") is not None
                else None
            ),
            selected_source=(
                cls.from_payload(selected)
                if isinstance(selected, Mapping)
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

    def to_payload(self) -> dict[str, Any]:
        return {
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


@dataclass(frozen=True)
class FunctionalBindingContext:
    bindings: tuple[FunctionalArgBinding, ...]
    binding_signature: str
    relation_bindings: tuple[FunctionalMethodRelationBinding, ...] = ()

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
    ) -> FunctionalBindingContext:
        wire_calls = {item.call_id: item for item in plan.calls}
        calls_by_id = {item.call_id: item for item in calls}
        bindings: list[FunctionalArgBinding] = []
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
            for arg_name, values in call.resolved_args.items():
                spec = arg_specs.get(arg_name)
                if spec is None:
                    auto_spec = auto_specs.get(arg_name)
                    if auto_spec is not None:
                        selected_source = _compiler_auto_selected_source(
                            arg_name=auto_spec.name,
                            selector=auto_spec.selector,
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
                                    else "compiler_owned"
                                ),
                                source=FunctionalArgSourceIdentity(
                                    kind="compiler_selector",
                                    compiler_selector_id=auto_spec.selector,
                                    selected_source=selected_source,
                                ),
                                selection_policy="compiler",
                                consumption_mode="compiler_selector",
                                runtime_input_targets=(
                                    auto_spec.runtime_input or arg_name,
                                ),
                                runtime_input_required=auto_spec.required,
                            )
                        )
                        continue
                    context_spec = context_specs.get(arg_name)
                    if context_spec is None:
                        raise FunctionalBindingContextError(
                            "planner.functional_arg_role_drift",
                            f"{call.call_id}.{arg_name} has no arg contract",
                        )
                    for item_index, value in enumerate(values):
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
                                source=_source_identity(
                                    value,
                                    object_registry=object_registry,
                                    prefer_call_result=(
                                        force_exact_source_versions
                                    ),
                                ),
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
                                    context_spec.consumption_mode
                                ),
                                runtime_input_targets=(
                                    (arg_name,)
                                    if context_spec.consumption_mode
                                    == "runtime_input"
                                    else ()
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
                                _selection_policy_for_view(spec)
                                if item_index < len(wire_values)
                                and isinstance(
                                    wire_values[item_index],
                                    SemanticRef,
                                )
                                else None
                            ),
                            value=value,
                            source=_source_identity(
                                value,
                                object_registry=object_registry,
                                prefer_call_result=(
                                    force_exact_source_versions
                                ),
                            ),
                            runtime_targets=runtime_targets,
                            consumption_mode=consumption_mode,
                            force_exact_source_versions=(
                                force_exact_source_versions
                            ),
                        )
                    )
            for auto_arg in capability.auto_args:
                if auto_arg.name in call.resolved_args:
                    continue
                selected_source = _compiler_auto_selected_source(
                    arg_name=auto_arg.name,
                    selector=auto_arg.selector,
                    runtime_input=auto_arg.runtime_input,
                    required=auto_arg.required,
                    capability=capability,
                    call=call,
                    calls_by_id=calls_by_id,
                    object_registry=object_registry,
                    handle_registry=handle_registry,
                    method_specs=method_specs,
                    allow_missing_typed_source=(
                        allow_missing_typed_sources
                    ),
                )
                if selected_source is None:
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
                        runtime_type="compiler_owned",
                        source=FunctionalArgSourceIdentity(
                            kind="compiler_selector",
                            compiler_selector_id=auto_arg.selector,
                            selected_source=selected_source,
                        ),
                        selection_policy="compiler",
                        consumption_mode="compiler_selector",
                        runtime_input_targets=(
                            auto_arg.runtime_input or auto_arg.name,
                        ),
                        runtime_input_required=auto_arg.required,
                    )
                )
            source_adapter = getattr(capability.source, "adapter", None)
            adapter_bindings = {
                item.input_name: item
                for item in getattr(source_adapter, "input_bindings", ())
            }
            for public_arg in capability.args:
                if public_arg.name in call.resolved_args:
                    continue
                runtime_input = public_arg.runtime_input or public_arg.name
                adapter_binding = adapter_bindings.get(runtime_input)
                if adapter_binding is None:
                    continue
                semantics = selector_semantics(adapter_binding.selector)
                if semantics.projection_source_arg is None:
                    continue
                selected_source = _compiler_auto_selected_source(
                    arg_name=public_arg.name,
                    selector=adapter_binding.selector,
                    runtime_input=runtime_input,
                    required=public_arg.required,
                    capability=capability,
                    call=call,
                    calls_by_id=calls_by_id,
                    object_registry=object_registry,
                    handle_registry=handle_registry,
                    method_specs=method_specs,
                    allow_missing_typed_source=(
                        allow_missing_typed_sources
                    ),
                )
                if selected_source is None:
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
                        runtime_type="compiler_owned",
                        source=FunctionalArgSourceIdentity(
                            kind="compiler_selector",
                            compiler_selector_id=adapter_binding.selector,
                            selected_source=selected_source,
                        ),
                        selection_policy="compiler",
                        consumption_mode="compiler_selector",
                        runtime_input_targets=(runtime_input,),
                        runtime_input_required=public_arg.required,
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
    ) -> FunctionalArgBinding:
        if not runtime_targets and consumption_mode == "runtime_input":
            raise FunctionalBindingContextError(
                "planner.functional_runtime_input_mapping_drift",
                f"{call_id}.{arg_name} has no runtime input target",
            )
        if spec.requires_materialized_state and source.kind not in {
            "state_version",
            "call_result",
        }:
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
        )


def _compiler_auto_selected_source(
    *,
    arg_name: str,
    selector: str,
    runtime_input: str | None,
    required: bool,
    capability: Any,
    call: FunctionalCallReconciliation,
    calls_by_id: Mapping[str, FunctionalCallReconciliation],
    object_registry: MathObjectRegistry | None,
    handle_registry: CanonicalHandleRegistry | None,
    method_specs: MethodSpecRegistry | None,
    allow_missing_typed_source: bool = False,
) -> FunctionalArgSourceIdentity | None:
    """Project a hidden entity slot from canonical call authority.

    Selector execution is intentionally absent here.  Declared same-call
    links, scoped entity roles, and free-symbol basis evidence are all typed
    authority channels. For a required or already consumed input, every
    non-empty channel must identify exactly one source and all channels must
    agree. An unconsumed optional input may decline projection instead of
    creating an empty ledger row. No channel wins by declaration order,
    candidate frequency, or legacy selector precedence.
    """

    input_spec = None
    method_id = getattr(capability.source, "method_id", None)
    if method_specs is not None and isinstance(method_id, str):
        try:
            input_spec = method_specs.require(method_id).inputs.get(
                runtime_input or arg_name
            )
        except KeyError:
            input_spec = None
    expected_kind = getattr(
        getattr(input_spec, "view", None),
        "object_kind",
        None,
    )
    exact_evidence: list[
        tuple[str, dict[str, FunctionalArgSourceIdentity]]
    ] = []
    semantics = selector_semantics(selector)

    def add_exact_evidence(
        label: str,
        values: list[FunctionalArgSourceIdentity],
    ) -> None:
        by_payload = {
            json.dumps(item.to_payload(), sort_keys=True): item
            for item in values
        }
        if by_payload:
            exact_evidence.append((label, by_payload))

    source_arg = semantics.projection_source_arg
    if source_arg is not None and source_arg != arg_name:
        sources: list[FunctionalArgSourceIdentity] = []
        for value in call.resolved_args.get(source_arg, ()):
            source = _source_for_input_view(
                value,
                input_spec=input_spec,
                object_registry=object_registry,
            )
            if source is not None:
                sources.append(source)
        add_exact_evidence(f"arg:{source_arg}", sources)

    source_return = semantics.projection_source_return
    if source_return is not None:
        add_exact_evidence(
            f"return:{source_return}",
            list(
                _allocation_sources_for_input_view(
                    call,
                    return_names=(source_return,),
                    expected_kind=expected_kind,
                    input_spec=input_spec,
                )
            ),
        )

    producer_arg = semantics.projection_source_producer_arg
    if producer_arg is not None:
        producer_source_values = (
            call.resolved_args.get(source_arg, ())
            if source_arg is not None
            else tuple(
                value
                for values in call.resolved_args.values()
                for value in values
            )
        )
        producer_ids = tuple(
            dict.fromkeys(
                value.source_call_id
                for value in producer_source_values
                if value.source_call_id is not None
            )
        )
        sources = []
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
                    sources.append(source)
        add_exact_evidence(f"producer_arg:{producer_arg}", sources)

    identity_returns = tuple(
        item.name
        for item in capability.returns
        if item.identity_arg == arg_name
    )
    add_exact_evidence(
        "return_identity",
        list(
            _allocation_sources_for_input_view(
                call,
                return_names=identity_returns,
                expected_kind=expected_kind,
                input_spec=input_spec,
            )
        ),
    )

    if selector.startswith("symbol:") and object_registry is not None:
        object_id = object_registry.resolve(
            selector.split(":", 1)[1]
        )
        if object_id is not None:
            add_exact_evidence(
                "literal_symbol",
                [
                    FunctionalArgSourceIdentity(
                        kind="math_object",
                        math_object_id=object_id,
                    )
                ],
            )

    direct_sources: list[FunctionalArgSourceIdentity] = []
    for value in call.resolved_args.get(arg_name, ()):
        source = _source_for_input_view(
            value,
            input_spec=input_spec,
            object_registry=object_registry,
        )
        if source is not None:
            direct_sources.append(source)
    add_exact_evidence(f"resolved_arg:{arg_name}", direct_sources)

    if (
        semantics.projection_entity_roles
        and handle_registry is not None
        and object_registry is not None
    ):
        role_sources: list[FunctionalArgSourceIdentity] = []
        for handle, payload in handle_registry.entity_payloads.items():
            if payload.get("role") not in semantics.projection_entity_roles:
                continue
            if (
                expected_kind is not None
                and payload.get("entity_type") != expected_kind
            ):
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
                role_sources.append(
                    FunctionalArgSourceIdentity(
                        kind="math_object",
                        math_object_id=object_id,
                    )
                )
        add_exact_evidence(
            "entity_roles:" + ",".join(semantics.projection_entity_roles),
            role_sources,
        )

    basis_candidates: list[FunctionalArgSourceIdentity] = []
    basis_refs_by_input: dict[str, tuple[str, ...]] = {}
    if (
        semantics.projection_free_symbol_basis
        and object_registry is not None
    ):
        claimed_roles = {
            role
            for auto_arg in capability.auto_args
            if auto_arg.name != arg_name
            for role in selector_semantics(
                auto_arg.selector
            ).projection_entity_roles
        }
        raw_refs_by_input = {
            input_name: tuple(
                dict.fromkeys(
                    ref
                    for value in values
                    for ref in (
                        *value.free_symbol_refs,
                        *(
                            (value.object_ref,)
                            if value.runtime_type == "Symbol"
                            else ()
                        ),
                    )
                    if ref is not None and ref.startswith("symbol:")
                )
            )
            for input_name, values in call.resolved_args.items()
            if input_name != arg_name
        }
        basis_refs_by_input = {
            input_name: tuple(
                ref
                for ref in refs
                if not (
                    handle_registry is not None
                    and handle_registry.entity_payloads.get(ref, {}).get(
                        "role"
                    )
                    in claimed_roles
                )
            )
            for input_name, refs in raw_refs_by_input.items()
        }
        symbol_refs = tuple(
            sorted(
                {
                    ref
                    for refs in basis_refs_by_input.values()
                    for ref in refs
                }
            )
        )
        for ref in symbol_refs:
            if handle_registry is not None:
                valid_scope = handle_registry.handle_valid_scopes.get(ref, "")
                if not visible_from_valid_scope(
                    valid_scope,
                    scope_id=call.scope_id,
                    registry=handle_registry,
                ):
                    continue
            object_id = object_registry.resolve(ref)
            if object_id is None:
                continue
            if expected_kind is not None and object_id.kind != expected_kind:
                continue
            basis_candidates.append(
                FunctionalArgSourceIdentity(
                    kind="math_object",
                    math_object_id=object_id,
                )
            )
    add_exact_evidence("free_symbol_basis", basis_candidates)

    evidence_payload = {
        label: [
            item.to_payload()
            for _, item in sorted(bucket.items())
        ]
        for label, bucket in exact_evidence
    }
    ambiguous_channels = tuple(
        label for label, bucket in exact_evidence if len(bucket) != 1
    )
    candidates = {
        payload_key: source
        for _, bucket in exact_evidence
        for payload_key, source in bucket.items()
    }
    if ambiguous_channels or len(candidates) > 1:
        if not required:
            return None
        raise FunctionalBindingContextError(
            "planner.method_input_view_authority_drift",
            (
                f"{call.call_id}.{arg_name} has inconsistent typed compiler "
                f"source evidence; ambiguous_channels={ambiguous_channels}, "
                f"evidence={evidence_payload}, "
                f"basis_by_input={basis_refs_by_input}"
            ),
        )
    if (
        not candidates
        and required
        and not allow_missing_typed_source
        and method_input_requires_typed_entity_authority(input_spec)
    ):
        raise FunctionalBindingContextError(
            "planner.method_input_view_authority_missing",
            (
                f"{call.call_id}.{arg_name} requires a typed compiler source; "
                f"selector={selector}, runtime_input={runtime_input or arg_name}"
            ),
        )
    return next(iter(candidates.values()), None)


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


def _selection_policy_for_view(spec: Any) -> FunctionalArgSelectionPolicy:
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
        selected_source = binding.source.selected_source
        if value is None and selected_source is None:
            continue
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
                value.runtime_type if value is not None else binding.runtime_type
            ),
            state_slot_id=(value.state_slot_id if value is not None else None),
            object_ref=(
                value.object_ref
                if value is not None
                else (
                    selected_source.math_object_id.value
                    if selected_source is not None
                    and selected_source.math_object_id is not None
                    else None
                )
            ),
            math_object_id=(
                binding.source.math_object_id
                or (
                    binding.source.selected_source.math_object_id
                    if binding.source.selected_source is not None
                    else None
                )
                or (value.math_object_id if value is not None else None)
            ),
            state_version_id=(
                binding.source.state_version_id
                or (
                    binding.source.selected_source.state_version_id
                    if binding.source.selected_source is not None
                    else None
                )
                or (value.state_version_id if value is not None else None)
            ),
            condition_id=(
                binding.source.condition_id
                or (
                    binding.source.selected_source.condition_id
                    if binding.source.selected_source is not None
                    else None
                )
                or (value.condition_id if value is not None else None)
            ),
            source_call_id=(
                binding.source.source_call_id
                or (
                    binding.source.selected_source.source_call_id
                    if binding.source.selected_source is not None
                    else None
                )
                or (value.source_call_id if value is not None else None)
            ),
            source_return_name=(
                binding.source.source_return_name
                or (
                    binding.source.selected_source.source_return_name
                    if binding.source.selected_source is not None
                    else None
                )
                or (value.return_name if value is not None else None)
            ),
            binding_authority=binding.binding_authority,
            semantic_role=binding.semantic_role,
            cardinality=binding.cardinality,
            item_index=binding.key.item_index,
            selection_policy=binding.selection_policy,
            consumption_mode=binding.consumption_mode,
            compiler_selector_id=binding.source.compiler_selector_id,
            compiler_selected_source_kind=(
                binding.source.selected_source.kind
                if binding.source.selected_source is not None
                else None
            ),
            runtime_input_targets=binding.runtime_input_targets,
            runtime_input_required=binding.runtime_input_required,
            )
        )
    return tuple(projected)


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
        # Mechanical compiler selectors need not be projected into the v1
        # compatibility IR. When a typed compiler binding is projected (for
        # example a hidden target identity), audit it like every other source.
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
            if _projected_source_payload(item) != binding.source.to_payload():
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
) -> dict[str, Any]:
    if (
        item.binding_authority == "compiler"
        and item.compiler_selector_id is not None
    ):
        payload: dict[str, Any] = {
            "kind": "compiler_selector",
            "compiler_selector_id": item.compiler_selector_id,
        }
        selected = _projected_compiler_selected_source_payload(item)
        if selected is not None:
            payload["selected_source"] = selected
        return payload
    if item.condition_id is not None:
        return {"kind": "condition", "condition_id": item.condition_id}
    if item.source_call_id is not None and item.source_return_name is not None:
        return {
            "kind": "call_result",
            "source_call_id": item.source_call_id,
            "source_return_name": item.source_return_name,
        }
    if item.state_version_id is not None:
        return {
            "kind": "state_version",
            "state_version_id": item.state_version_id.to_payload(),
        }
    if item.math_object_id is not None:
        return {
            "kind": "math_object",
            "math_object_id": item.math_object_id.to_payload(),
        }
    if item.compiler_selector_id is not None:
        return {
            "kind": "compiler_selector",
            "compiler_selector_id": item.compiler_selector_id,
        }
    return {"kind": "unresolved"}


def _projected_compiler_selected_source_payload(
    item: ProjectedFunctionArgBinding,
) -> dict[str, Any] | None:
    kind = item.compiler_selected_source_kind
    if kind == "condition" and item.condition_id is not None:
        return {"kind": "condition", "condition_id": item.condition_id}
    if kind == "state_version" and item.state_version_id is not None:
        return {
            "kind": "state_version",
            "state_version_id": item.state_version_id.to_payload(),
        }
    if (
        kind == "call_result"
        and item.source_call_id is not None
        and item.source_return_name is not None
    ):
        return {
            "kind": "call_result",
            "source_call_id": item.source_call_id,
            "source_return_name": item.source_return_name,
        }
    if kind == "math_object" and item.math_object_id is not None:
        return {
            "kind": "math_object",
            "math_object_id": item.math_object_id.to_payload(),
        }
    return None


def _binding_source_handle(binding: FunctionalArgBinding) -> str | None:
    source = binding.source.selected_source or binding.source
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
