"""Deterministic production-backed role/authority scenarios for C3."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from types import SimpleNamespace
from typing import Literal

from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalBindingContextBuilder,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalAutoArg,
    FunctionalCall,
    FunctionalCallReconciliation,
    FunctionalCapability,
    FunctionalCapabilityArg,
    FunctionalPlan,
    FunctionalScope,
    ResolvedFunctionalValue,
    SemanticRef,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)


SourceProfile = Literal[
    "wire_state",
    "resolver_state",
    "resolver_identity",
    "compiler_selector",
]


@dataclass(frozen=True)
class FunctionalBindingRoleScenario:
    scenario_id: str
    roles: tuple[str, str]
    source_profile: SourceProfile
    cardinality: Literal["one", "many"]
    renamed_call: bool
    declared_scope: str
    reverse_wire_order: bool
    placement_scope: str
    retry_round: int


def generated_binding_role_scenarios() -> tuple[FunctionalBindingRoleScenario, ...]:
    role_pairs = (
        ("primary_parameter", "dynamic_parameter"),
        ("free_parameter", "target_parameter"),
        ("fixed_point", "reference_point"),
        ("reference_point", "anchor"),
        ("moving_object", "fixed_endpoint"),
        ("curve_point", "candidate_point"),
        ("straightened_endpoint_1", "straightened_endpoint_2"),
        ("identity_subject", "materialized_subject"),
    )
    dimensions = product(
        role_pairs,
        ("wire_state", "resolver_state", "resolver_identity", "compiler_selector"),
        ("one", "many"),
        (False, True),
        ("ii_1", "ii_2"),
        (False, True),
        ("ii", "problem"),
        (1, 2),
    )
    return tuple(
        FunctionalBindingRoleScenario(
            scenario_id=f"c3-role-{index:04d}",
            roles=roles,
            source_profile=profile,
            cardinality=cardinality,
            renamed_call=renamed,
            declared_scope=declared_scope,
            reverse_wire_order=reverse_order,
            placement_scope=placement_scope,
            retry_round=retry_round,
        )
        for index, (
            roles,
            profile,
            cardinality,
            renamed,
            declared_scope,
            reverse_order,
            placement_scope,
            retry_round,
        ) in enumerate(dimensions)
    )


def reference_binding_outcome(
    scenario: FunctionalBindingRoleScenario,
) -> tuple[tuple[object, ...], ...]:
    authority, source_kind, selection = _profile(scenario.source_profile)
    item_count = (
        1
        if source_kind == "compiler_selector"
        else 2 if scenario.cardinality == "many" else 1
    )
    outcome = []
    for arg_name, role in zip(("arg_1", "arg_2"), scenario.roles, strict=True):
        source_indexes = list(range(item_count))
        if scenario.reverse_wire_order and source_kind != "compiler_selector":
            source_indexes.reverse()
        for item_index, source_index in enumerate(source_indexes):
            outcome.append(
                (
                    arg_name,
                    item_index,
                    role,
                    authority,
                    source_kind,
                    selection,
                    (f"method.{role}",),
                    _reference_source_payload(
                        scenario,
                        role=role,
                        source_index=source_index,
                    ),
                )
            )
    return tuple(sorted(outcome))


def production_binding_outcome(
    scenario: FunctionalBindingRoleScenario,
) -> tuple[tuple[tuple[object, ...], ...], str]:
    plan, calls, catalog = _production_inputs(scenario)
    context = FunctionalBindingContextBuilder().build(
        plan,
        calls,
        catalog=catalog,
    )
    call_id = calls[0].call_id
    outcome = tuple(
        (
            item.key.arg_name,
            item.key.item_index,
            item.semantic_role,
            item.binding_authority,
            item.source.kind,
            item.selection_policy,
            item.runtime_input_targets,
            _source_payload(item.source.to_payload()),
        )
        for item in context.bindings
    )
    return outcome, context.signature_for_call(call_id)


def _production_inputs(
    scenario: FunctionalBindingRoleScenario,
) -> tuple[
    FunctionalPlan,
    tuple[FunctionalCallReconciliation, ...],
    FunctionalCapabilityCatalog,
]:
    call_id = "retry_alias" if scenario.renamed_call else "canonical_call"
    is_compiler = scenario.source_profile == "compiler_selector"
    capability_args = () if is_compiler else tuple(
        FunctionalCapabilityArg(
            name=arg_name,
            runtime_type=_runtime_type(role),
            required=True,
            cardinality=scenario.cardinality,
            kind="slot_read",
            semantic_role=role,
            requires_materialized_state=(
                scenario.source_profile in {"wire_state", "resolver_state"}
            ),
            runtime_input=f"method.{role}",
        )
        for arg_name, role in zip(("arg_1", "arg_2"), scenario.roles, strict=True)
    )
    auto_args = () if not is_compiler else tuple(
        FunctionalAutoArg(
            name=arg_name,
            selector=f"selector:{role}",
            required=True,
            semantic_role=role,
            runtime_input=f"method.{role}",
        )
        for arg_name, role in zip(("arg_1", "arg_2"), scenario.roles, strict=True)
    )
    source = SimpleNamespace(
        adapter=SimpleNamespace(
            input_aliases=(),
            aggregate_input_bindings=(),
            scalar_aggregate_lowerings=(),
        )
    )
    capability = FunctionalCapability(
        capability_id="synthetic_role_capability",
        kind="function",
        goal_types=("oracle",),
        title="synthetic",
        use_when="synthetic",
        do_not_use_when=(),
        args=capability_args,
        returns=(),
        source=source,
        is_pure=True,
        dependency_policy="explicit_args",
        auto_args=auto_args,
    )
    resolved_args: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    wire_args: dict[str, tuple[SemanticRef, ...]] = {}
    if not is_compiler:
        item_count = 2 if scenario.cardinality == "many" else 1
        for arg_name, role in zip(("arg_1", "arg_2"), scenario.roles, strict=True):
            values = [
                _resolved_value(scenario, role=role, source_index=index)
                for index in range(item_count)
            ]
            if scenario.reverse_wire_order:
                values.reverse()
            resolved_args[arg_name] = tuple(values)
            if scenario.source_profile == "wire_state":
                wire_args[arg_name] = tuple(
                    SemanticRef(
                        ref=value.handle,
                        kind="symbol" if "parameter" in role else "point",
                        value_type=value.runtime_type,
                    )
                    for value in values
                )
    wire_call = FunctionalCall(
        call_id=call_id,
        capability_id=capability.capability_id,
        args=wire_args,
        return_bindings={},
        strategy="",
        reason="",
    )
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope(
                scope_id=scenario.declared_scope,
                label="synthetic",
                calls=(wire_call,),
            ),
        )
    )
    calls = (
        FunctionalCallReconciliation(
            call_id=call_id,
            scope_id=scenario.placement_scope,
            capability_id=capability.capability_id,
            resolved_args=resolved_args,
            returns=(),
        ),
    )
    return plan, calls, FunctionalCapabilityCatalog(
        {capability.capability_id: capability}
    )


def _resolved_value(
    scenario: FunctionalBindingRoleScenario,
    *,
    role: str,
    source_index: int,
) -> ResolvedFunctionalValue:
    object_id = _object_id(scenario, role=role, source_index=source_index)
    runtime_type = _runtime_type(role)
    if scenario.source_profile == "resolver_identity":
        return ResolvedFunctionalValue(
            handle=object_id.value,
            runtime_type=runtime_type,
            valid_scope=scenario.placement_scope,
            math_object_id=object_id,
        )
    logical_key = LogicalStateKey(object_id, "value", runtime_type)
    version_id = StateVersionId(
        StateSlotId(logical_key, scenario.placement_scope),
        scenario.retry_round + source_index,
    )
    return ResolvedFunctionalValue(
        handle=object_id.value,
        runtime_type=runtime_type,
        valid_scope=scenario.placement_scope,
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=version_id.slot_id,
        state_version_id=version_id,
    )


def _profile(profile: SourceProfile) -> tuple[str, str, str]:
    return {
        "wire_state": ("wire", "state_version", "latest"),
        "resolver_state": ("resolver", "state_version", "latest"),
        "resolver_identity": ("resolver", "math_object", "identity_only"),
        "compiler_selector": ("compiler", "compiler_selector", "compiler"),
    }[profile]


def _runtime_type(role: str) -> str:
    return "ParameterValue" if "parameter" in role else "Point"


def _object_id(
    scenario: FunctionalBindingRoleScenario,
    *,
    role: str,
    source_index: int,
) -> MathObjectId:
    kind = "symbol" if "parameter" in role else "point"
    return MathObjectId(
        f"{kind}:{scenario.declared_scope}:{role}_{source_index}",
        kind,
        scenario.declared_scope,
    )


def _reference_source_payload(
    scenario: FunctionalBindingRoleScenario,
    *,
    role: str,
    source_index: int,
) -> tuple[object, ...]:
    if scenario.source_profile == "compiler_selector":
        return ("compiler_selector", f"selector:{role}")
    object_id = _object_id(scenario, role=role, source_index=source_index)
    if scenario.source_profile == "resolver_identity":
        return ("math_object", object_id.value, object_id.kind, object_id.origin_scope_id)
    return (
        "state_version",
        object_id.value,
        object_id.kind,
        object_id.origin_scope_id,
        scenario.placement_scope,
        scenario.retry_round + source_index,
    )


def _source_payload(payload: dict[str, object]) -> tuple[object, ...]:
    kind = payload["kind"]
    if kind == "compiler_selector":
        return (kind, payload["compiler_selector_id"])
    if kind == "math_object":
        object_id = payload["math_object_id"]
        assert isinstance(object_id, dict)
        return (
            kind,
            object_id["value"],
            object_id["kind"],
            object_id["origin_scope_id"],
        )
    version = payload["state_version_id"]
    assert isinstance(version, dict)
    slot = version["slot_id"]
    assert isinstance(slot, dict)
    logical = slot["logical_key"]
    assert isinstance(logical, dict)
    object_id = logical["object_id"]
    assert isinstance(object_id, dict)
    return (
        kind,
        object_id["value"],
        object_id["kind"],
        object_id["origin_scope_id"],
        slot["storage_scope_id"],
        version["ordinal"],
    )
