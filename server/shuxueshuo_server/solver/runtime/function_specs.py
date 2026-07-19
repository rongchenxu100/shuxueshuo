"""FunctionSpec facade for generic method binding.

FunctionSpec is a planner/compiler-facing facade over existing MethodSpec and
CapabilityContract metadata.  Phase 5 keeps StepIntent as the LLM wire format
and MethodInvocation as the runtime format; the facade only provides a typed
adapter layer in between.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from shuxueshuo_server.solver.contracts import MethodSpec, ScalarResultFormSpec
from shuxueshuo_server.solver.family.common_binding_rules import (
    distance_between_points_rule,
    evaluate_expression_at_parameter_rule,
    evaluate_point_at_parameter_rule,
    line_intersection_point_rule,
    line_parabola_second_intersection_point_rule,
    midpoint_point_rule,
    parameter_from_curve_point_on_quadratic_rule,
    parameter_from_expression_value_rule,
    quadratic_from_constraints_rule,
    quadratic_vertex_point_rule,
    quadratic_x_axis_intercept_point_rule,
    quadratic_y_axis_intercept_point_rule,
    translated_point_rule,
)
from shuxueshuo_server.solver.family.models import (
    CapabilityDependencyPolicy,
    CapabilityContractSpec,
    MethodBindingRuleSpec,
    SolverFamilySpec,
    StateIdentityPolicy,
    StateWriteMode,
)
from shuxueshuo_server.solver.runtime.capability_contracts import (
    effective_contract_by_id,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StepIntentFunctionBindingEvent,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import (
    object_kind_for_runtime_type,
    split_runtime_types,
    state_kind_for_runtime_type,
)
from shuxueshuo_server.solver.utils import unique_ordered

FunctionArgKind = Literal["slot_read", "condition_read", "point_ref", "symbol", "auto"]
FunctionSpecSource = Literal["explicit_contract", "projected_contract", "method_spec"]
FunctionBindingStatus = Literal["success", "failure"]

BindingSelectorFn = Callable[[StepIntent, Any, Mapping[str, str]], str | None]
ExpansionSelectorFn = Callable[[StepIntent, Any, Mapping[str, str]], dict[str, str]]


@dataclass(frozen=True)
class FunctionArgSpec:
    """Typed function argument visible to planner/debug layers."""

    name: str
    kind: FunctionArgKind
    runtime_type: str
    required: bool = True
    cardinality: str = "one"
    state_kind: str | None = None
    object_kind: str | None = None
    method_input: str | None = None
    description: str = ""
    provides_semantic_roles: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "runtime_type": self.runtime_type,
            "required": self.required,
            "cardinality": self.cardinality,
        }
        if self.state_kind is not None:
            payload["state_kind"] = self.state_kind
        if self.object_kind is not None:
            payload["object_kind"] = self.object_kind
        if self.method_input is not None:
            payload["method_input"] = self.method_input
        if self.description:
            payload["description"] = self.description
        if self.provides_semantic_roles:
            payload["provides_semantic_roles"] = list(
                self.provides_semantic_roles
            )
        return payload


@dataclass(frozen=True)
class FunctionReturnSpec:
    """Typed function return visible to planner/debug layers."""

    name: str
    runtime_type: str
    state_kind: str
    object_kind: str | None = None
    required: bool = True
    output_key: str | None = None
    semantic_role: str | None = None
    identity_policy: StateIdentityPolicy = "value_only"
    identity_arg: str | None = None
    write_mode: StateWriteMode = "value"
    description: str = ""
    scalar_result_form: ScalarResultFormSpec | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "runtime_type": self.runtime_type,
            "state_kind": self.state_kind,
            "required": self.required,
        }
        if self.object_kind is not None:
            payload["object_kind"] = self.object_kind
        if self.output_key is not None:
            payload["output_key"] = self.output_key
        if self.semantic_role is not None:
            payload["semantic_role"] = self.semantic_role
        payload["identity_policy"] = self.identity_policy
        if self.identity_arg is not None:
            payload["identity_arg"] = self.identity_arg
        payload["write_mode"] = self.write_mode
        if self.description:
            payload["description"] = self.description
        if self.scalar_result_form is not None:
            payload["scalar_result_form"] = self.scalar_result_form.to_payload()
        return payload


@dataclass(frozen=True)
class FunctionInputBindingSpec:
    """Adapter binding from a function arg/method input to a selector primitive."""

    input_name: str
    selector: str
    required: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "input_name": self.input_name,
            "selector": self.selector,
            "required": self.required,
        }


@dataclass(frozen=True)
class FunctionAdapterSpec:
    """Runtime adapter for compiling a FunctionSpec to MethodInvocation inputs."""

    adapter_id: str
    input_bindings: tuple[FunctionInputBindingSpec, ...] = ()
    expansion_selectors: tuple[str, ...] = ()
    constraint_analyzer: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "input_bindings": [item.to_payload() for item in self.input_bindings],
            "expansion_selectors": list(self.expansion_selectors),
            "constraint_analyzer": self.constraint_analyzer,
        }


@dataclass(frozen=True)
class FunctionSpec:
    """Typed function facade derived from MethodSpec and CapabilityContract."""

    function_id: str
    method_id: str
    goal_types: tuple[str, ...]
    args: tuple[FunctionArgSpec, ...]
    returns: tuple[FunctionReturnSpec, ...]
    adapter: FunctionAdapterSpec | None = None
    source: FunctionSpecSource = "method_spec"
    notes: tuple[str, ...] = ()
    is_pure: bool = False
    plan_transformer: str | None = None
    reconciliation_validators: tuple[str, ...] = ()
    dependency_policy: CapabilityDependencyPolicy = "explicit_args"

    def to_payload(self, *, include_adapter: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "function_id": self.function_id,
            "method_id": self.method_id,
            "goal_types": list(self.goal_types),
            "args": [item.to_payload() for item in self.args],
            "returns": [item.to_payload() for item in self.returns],
            "source": self.source,
            "notes": list(self.notes),
            "is_pure": self.is_pure,
            "plan_transformer": self.plan_transformer,
            "reconciliation_validators": list(self.reconciliation_validators),
            "dependency_policy": self.dependency_policy,
        }
        if include_adapter and self.adapter is not None:
            payload["adapter"] = self.adapter.to_payload()
        return payload

    def to_prompt_payload(self) -> dict[str, Any]:
        """Return LLM-facing catalog payload without runtime selectors/paths."""
        return {
            "function_id": self.function_id,
            "goal_types": list(self.goal_types),
            "args": [
                _arg_prompt_payload(item)
                for item in self.args
            ],
            "returns": [
                _return_prompt_payload(item)
                for item in self.returns
            ],
            "notes": list(self.notes),
        }


class FunctionSpecRegistry:
    """Effective FunctionSpec lookup for a solver family."""

    def __init__(self, specs: Mapping[str, FunctionSpec]) -> None:
        self.specs = dict(specs)

    @classmethod
    def from_family_spec(
        cls,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
    ) -> "FunctionSpecRegistry":
        contracts = effective_contract_by_id(family_spec, method_specs)
        specs: dict[str, FunctionSpec] = {}
        for method_id in family_spec.method_ids:
            try:
                method_spec = method_specs.require(method_id)
            except KeyError:
                continue
            contract = contracts.get(method_id)
            adapter = GENERIC_FUNCTION_ADAPTERS.get(method_id)
            _validate_constraint_analyzer_consistency(
                method_spec,
                contract=contract,
                adapter=adapter,
            )
            specs[method_id] = function_spec_from_method(
                method_spec,
                contract=contract,
                adapter=adapter,
            )
        return cls(specs)

    def get(self, function_id: str) -> FunctionSpec | None:
        return self.specs.get(function_id)

    def require(self, function_id: str) -> FunctionSpec:
        try:
            return self.specs[function_id]
        except KeyError as exc:
            raise KeyError(f"function spec not found: {function_id}") from exc

    def to_payload(self, *, include_adapter: bool = True) -> tuple[dict[str, Any], ...]:
        return tuple(
            spec.to_payload(include_adapter=include_adapter)
            for spec in self.specs.values()
        )

    def to_prompt_payload(self) -> dict[str, Any]:
        # FunctionSpec is also the typed identity/provenance facade for direct
        # family methods that have not migrated to FunctionAdapter yet. Keep
        # prompt exposure stable until those methods have an executable adapter.
        items = [
            spec.to_prompt_payload()
            for spec in self.specs.values()
            if spec.adapter is not None
        ]
        return {
            "source": "function_spec_facade",
            "items": items,
            "item_count": len(items),
        }


class FunctionAdapterRegistry:
    """Bind migrated generic methods through FunctionSpec adapter declarations."""

    def __init__(
        self,
        *,
        selectors: Mapping[str, BindingSelectorFn],
        expansion_selectors: Mapping[str, ExpansionSelectorFn],
        adapters: Mapping[str, FunctionAdapterSpec] | None = None,
    ) -> None:
        self.selectors = dict(selectors)
        self.expansion_selectors = dict(expansion_selectors)
        self.adapters = dict(adapters or GENERIC_FUNCTION_ADAPTERS)

    def rule_for(self, method_id: str) -> FunctionAdapterSpec | None:
        return self.adapters.get(method_id)

    def bind(
        self,
        method_id: str,
        step: StepIntent,
        index: Any,
        *,
        local_outputs: Mapping[str, str] | None = None,
        include_expansion_selectors: bool = True,
        expansion_selectors_override: tuple[str, ...] | None = None,
        input_bindings_override: tuple[Any, ...] | None = None,
    ) -> dict[str, str]:
        local_outputs = local_outputs or {}
        adapter = self.adapters.get(method_id)
        if adapter is None:
            raise StrategyDraftValidationError(
                f"function.adapter_missing: method={method_id}"
            )
        inputs: dict[str, str] = {}
        for binding in _effective_input_bindings(
            adapter,
            input_bindings_override=input_bindings_override,
        ):
            try:
                value = self._select(binding.selector, step, index, local_outputs)
            except StrategyDraftValidationError as exc:
                if binding.required:
                    raise StrategyDraftValidationError(
                        "function.arg_missing: "
                        f"method={method_id}, arg={binding.input_name}, "
                        f"selector={binding.selector}, reason={exc}"
                    ) from exc
                continue
            if value is None:
                if binding.required:
                    raise StrategyDraftValidationError(
                        "function.arg_missing: "
                        f"method={method_id}, arg={binding.input_name}, "
                        f"selector={binding.selector}"
                    )
                continue
            if _selector_requires_declared_read(binding.selector) and not _path_is_declared_read(
                value,
                step=step,
                index=index,
                local_outputs=local_outputs,
            ):
                raise StrategyDraftValidationError(
                    "function.arg_not_read: "
                    f"method={method_id}, arg={binding.input_name}, "
                    f"selector={binding.selector}"
                )
            inputs[binding.input_name] = value
        if expansion_selectors_override is not None:
            expansions = expansion_selectors_override
        elif include_expansion_selectors:
            expansions = adapter.expansion_selectors
        else:
            expansions = ()
        for selector in expansions:
            expanded = self._expand(selector, step, index, local_outputs)
            for input_name, path in expanded.items():
                if (
                    input_name in {"parameter", "x", "all_coefficients"}
                    or selector in _DECLARATIVE_EXPANSIONS
                ):
                    continue
                if not _path_is_declared_read(
                    path,
                    step=step,
                    index=index,
                    local_outputs=local_outputs,
                ):
                    raise StrategyDraftValidationError(
                        "function.arg_not_read: "
                        f"method={method_id}, arg={input_name}, expansion={selector}"
                    )
            inputs.update(expanded)
        if adapter.constraint_analyzer is not None:
            inputs = _apply_constraint_analyzer(
                adapter.constraint_analyzer,
                inputs=inputs,
                step=step,
                index=index,
            )
        return inputs

    def _select(
        self,
        selector: str,
        step: StepIntent,
        index: Any,
        local_outputs: Mapping[str, str],
    ) -> str | None:
        fn = self.selectors.get(selector)
        if fn is None:
            raise StrategyDraftValidationError(
                f"function.adapter_selector_missing: {selector}"
            )
        return fn(step, index, local_outputs)

    def _expand(
        self,
        selector: str,
        step: StepIntent,
        index: Any,
        local_outputs: Mapping[str, str],
    ) -> dict[str, str]:
        fn = self.expansion_selectors.get(selector)
        if fn is None:
            raise StrategyDraftValidationError(
                f"function.adapter_expansion_missing: {selector}"
            )
        return fn(step, index, local_outputs)


def _selector_requires_declared_read(selector: str) -> bool:
    return selector.startswith("read_type:") or selector.startswith("fact:")


_DECLARATIVE_EXPANSIONS = frozenset(
    {
        "known_coefficients_if_read",
        "free_quadratic_parameter_if_read",
        "curve_point_if_read",
        "curve_points_if_parameterized",
    }
)


def _path_is_declared_read(
    path: str,
    *,
    step: StepIntent,
    index: Any,
    local_outputs: Mapping[str, str],
) -> bool:
    if path in local_outputs.values():
        return True
    return any(
        getattr(index.bindings.get(handle), "path", None) == path
        for handle in step.reads
    )

def function_spec_from_method(
    method_spec: MethodSpec,
    *,
    contract: CapabilityContractSpec | None,
    adapter: FunctionAdapterSpec | None,
) -> FunctionSpec:
    """Derive a FunctionSpec from runtime method and contract metadata."""
    source: FunctionSpecSource = "method_spec"
    notes: list[str] = []
    if contract is not None:
        source = (
            "explicit_contract"
            if contract.source == "explicit"
            else "projected_contract"
        )
        notes.extend(contract.notes)
        notes.extend(_contract_return_notes(contract, method_spec.outputs))
    args = tuple(
        _arg_spec_from_method_input(name, input_spec, contract=contract)
        for name, input_spec in method_spec.inputs.items()
    )
    returns: list[FunctionReturnSpec] = []
    for output_name, output_type in method_spec.outputs.items():
        contract_write = _function_return_contract_write(
            contract,
            output_name=output_name,
            output_type=output_type,
        )
        identity_policy, identity_arg = _function_return_identity(
            method_spec,
            output_type=output_type,
            adapter=adapter,
        )
        write_mode = _function_return_write_mode(
            contract,
            output_type=output_type,
        )
        returns.append(
            FunctionReturnSpec(
                name=output_name,
                output_key=output_name,
                runtime_type=output_type,
                state_kind=(
                    contract_write.state_kind
                    if contract_write is not None
                    else state_kind_for_runtime_type(output_type)
                ),
                object_kind=(
                    contract_write.object_kind
                    if contract_write is not None
                    else object_kind_for_runtime_type(output_type)
                ),
                required=_function_return_required(
                    contract,
                    output_name=output_name,
                    output_type=output_type,
                    output_count=len(method_spec.outputs),
                ),
                semantic_role=_function_return_semantic_role(
                    contract,
                    output_name=output_name,
                    output_type=output_type,
                ),
                identity_policy=identity_policy,
                identity_arg=identity_arg,
                write_mode=write_mode,
                description=(
                    contract_write.description
                    if contract_write is not None
                    else ""
                ),
                scalar_result_form=method_spec.scalar_result_forms.get(output_name),
            )
        )
    return FunctionSpec(
        function_id=method_spec.method_id,
        method_id=method_spec.method_id,
        goal_types=method_spec.solves,
        args=args,
        returns=tuple(returns),
        adapter=adapter,
        source=source,
        is_pure=method_spec.is_pure,
        plan_transformer=method_spec.plan_transformer,
        reconciliation_validators=method_spec.reconciliation_validators,
        dependency_policy=(
            contract.dependency_policy
            if contract is not None
            else "explicit_args"
        ),
        notes=tuple(unique_ordered(notes)),
    )


def _function_return_contract_write(
    contract: CapabilityContractSpec | None,
    *,
    output_name: str,
    output_type: str,
) -> Any | None:
    if contract is None:
        return None
    keyed = [
        item
        for item in contract.slot_writes
        if item.output_key == output_name
    ]
    if len(keyed) == 1:
        return keyed[0]
    typed = [
        item
        for item in contract.slot_writes
        if item.output_key is None and item.runtime_type == output_type
    ]
    return typed[0] if len(typed) == 1 else None


def _function_return_required(
    contract: CapabilityContractSpec | None,
    *,
    output_name: str,
    output_type: str,
    output_count: int,
) -> bool:
    if output_count == 1:
        return True
    if contract is None:
        return True
    keyed = [
        item
        for item in contract.slot_writes
        if item.output_key == output_name
    ]
    if len(keyed) == 1:
        return keyed[0].required
    typed = [
        item
        for item in contract.slot_writes
        if item.output_key is None and item.runtime_type == output_type
    ]
    if len(typed) == 1:
        return typed[0].required
    return True


def _function_return_semantic_role(
    contract: CapabilityContractSpec | None,
    *,
    output_name: str,
    output_type: str,
) -> str:
    """Project an explicit contract role without inventing facade metadata."""
    if contract is None:
        return output_name
    keyed = [
        item.semantic_role
        for item in contract.slot_writes
        if item.output_key == output_name and item.semantic_role
    ]
    if len(keyed) == 1:
        return keyed[0]
    typed = [
        item.semantic_role
        for item in contract.slot_writes
        if item.output_key is None
        and item.runtime_type == output_type
        and item.semantic_role
    ]
    if len(typed) == 1:
        return typed[0]
    return output_name


def _function_return_identity(
    method_spec: MethodSpec,
    *,
    output_type: str,
    adapter: FunctionAdapterSpec | None,
) -> tuple[StateIdentityPolicy, str | None]:
    if output_type == "ParameterValue" and "parameter" in method_spec.inputs:
        return "preserve_input_object", "parameter"
    if output_type == "Symbol":
        target = method_spec.inputs.get("target")
        if target is not None and "PointRef" in split_runtime_types(str(target.type)):
            return "derived_role", "target"
    output_object_kind = object_kind_for_runtime_type(output_type)
    if output_object_kind == "function" and adapter is not None:
        function_inputs = [
            binding.input_name
            for binding in adapter.input_bindings
            if binding.selector.startswith("function:")
        ]
        if len(function_inputs) == 1:
            return "preserve_input_object", function_inputs[0]
    if output_object_kind is not None and output_object_kind != "point":
        identity_inputs = [
            input_name
            for input_name, input_spec in method_spec.inputs.items()
            if output_type in split_runtime_types(str(input_spec.type))
            or {
                object_kind_for_runtime_type(runtime_type)
                for runtime_type in split_runtime_types(str(input_spec.type))
            }
            == {output_object_kind}
        ]
        if len(identity_inputs) == 1:
            return "preserve_input_object", identity_inputs[0]
    if output_type not in {"Point", "PointList"}:
        return "value_only", None
    target = method_spec.inputs.get("target")
    if target is not None and "PointRef" in split_runtime_types(str(target.type)):
        return "target_object", "target"
    for input_name in ("target_point", "point"):
        point = method_spec.inputs.get(input_name)
        if point is not None and "Point" in split_runtime_types(str(point.type)):
            return "preserve_input_object", input_name
    return "derived_role", None


def _function_return_write_mode(
    contract: CapabilityContractSpec | None,
    *,
    output_type: str,
) -> StateWriteMode:
    """Project the authoritative write mode when one contract write is unique."""
    if contract is not None:
        matches = [
            item.write_mode
            for item in contract.slot_writes
            if item.runtime_type == output_type
        ]
        if len(matches) == 1:
            return matches[0]
    return "create" if output_type in {"Point", "PointList"} else "value"


def _validate_constraint_analyzer_consistency(
    method_spec: MethodSpec,
    *,
    contract: CapabilityContractSpec | None,
    adapter: FunctionAdapterSpec | None,
) -> None:
    """Keep applicability analysis declarative across the three facades."""
    if contract is not None and contract.execution_status != "executable":
        return
    declarations = (
        method_spec.constraint_analyzer,
        contract.constraint_analyzer if contract is not None else None,
        adapter.constraint_analyzer if adapter is not None else None,
    )
    active = tuple(item for item in declarations if item is not None)
    if not active:
        return
    if len(active) != len(declarations) or len(set(active)) != 1:
        raise ValueError(
            "constraint analyzer declaration mismatch: "
            f"method={method_spec.method_id}, declarations={declarations}"
        )


def _contract_return_notes(
    contract: CapabilityContractSpec,
    method_outputs: Mapping[str, str],
) -> tuple[str, ...]:
    """Return debug notes when contract writes are not covered by method outputs.

    MethodSpec remains the runtime execution source for output keys. Contract
    slot_writes describe semantic state writes.  During the facade migration we
    keep the two layers separate, but make inconsistencies visible in the
    FunctionSpec payload instead of silently hiding them.
    """
    output_types = set(method_outputs.values())
    notes: list[str] = []
    for slot in contract.slot_writes:
        if slot.runtime_type in output_types:
            continue
        marker = "required" if slot.required else "optional"
        notes.append(f"contract_slot_write_missing:{marker}:{slot.runtime_type}")
    return tuple(notes)


def function_catalog_payload(
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry,
) -> dict[str, Any]:
    """Build prompt-facing FunctionSpec catalog."""
    return FunctionSpecRegistry.from_family_spec(
        family_spec,
        method_specs,
    ).to_prompt_payload()


def function_spec_payloads(
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry,
) -> tuple[dict[str, Any], ...]:
    """Build debug-facing FunctionSpec snapshots including adapter metadata."""
    return FunctionSpecRegistry.from_family_spec(
        family_spec,
        method_specs,
    ).to_payload(include_adapter=True)


def function_adapter_failure_events(
    events: tuple[StepIntentFunctionBindingEvent, ...],
) -> tuple[StepIntentFunctionBindingEvent, ...]:
    return tuple(event for event in events if event.status == "failure")


def assert_no_function_adapter_failures(
    events: tuple[StepIntentFunctionBindingEvent, ...],
) -> None:
    failures = function_adapter_failure_events(events)
    if failures:
        details = [
            f"{event.step_id}:{event.method_id}:{'|'.join(event.errors)}"
            for event in failures
        ]
        raise AssertionError(
            "function adapter failure occurred: " + "; ".join(details)
        )


def _arg_spec_from_method_input(
    name: str,
    input_spec: Any,
    *,
    contract: CapabilityContractSpec | None,
) -> FunctionArgSpec:
    runtime_type = str(input_spec.type)
    runtime_types = split_runtime_types(runtime_type)
    primary_type = runtime_types[0] if runtime_types else runtime_type
    kind = _arg_kind(runtime_types)
    contract_slot = _function_arg_contract_slot(
        contract,
        name=name,
        runtime_type=runtime_type,
        kind=kind,
    )
    return FunctionArgSpec(
        name=name,
        method_input=name,
        kind=kind,
        runtime_type=runtime_type,
        required=bool(getattr(input_spec, "required", True)),
        state_kind=(
            state_kind_for_runtime_type(primary_type)
            if kind in {"slot_read", "condition_read"}
            else None
        ),
        object_kind=object_kind_for_runtime_type(primary_type),
        description=_function_arg_contract_description(
            contract,
            name=name,
            runtime_type=runtime_type,
            kind=kind,
        ),
        provides_semantic_roles=(
            contract_slot.provides_semantic_roles
            if contract_slot is not None
            else ()
        ),
    )


def _function_arg_contract_slot(
    contract: CapabilityContractSpec | None,
    *,
    name: str,
    runtime_type: str,
    kind: FunctionArgKind,
) -> Any | None:
    if contract is None or kind != "slot_read":
        return None
    named = [item for item in contract.slot_reads if item.semantic_role == name]
    if len(named) == 1:
        return named[0]
    accepted_types = set(split_runtime_types(runtime_type))
    typed = [
        item for item in contract.slot_reads if item.runtime_type in accepted_types
    ]
    return typed[0] if len(typed) == 1 else None


def _function_arg_contract_description(
    contract: CapabilityContractSpec | None,
    *,
    name: str,
    runtime_type: str,
    kind: FunctionArgKind,
) -> str:
    if contract is None:
        return ""
    if kind not in {"condition_read", "slot_read"}:
        return ""
    conditions = tuple(contract.condition_reads)
    slots = tuple(contract.slot_reads)
    named_conditions = [item for item in conditions if item.condition_kind == name]
    if len(named_conditions) == 1:
        return named_conditions[0].description
    named_slots = [item for item in slots if item.semantic_role == name]
    if len(named_slots) == 1:
        return named_slots[0].description
    accepted_types = set(split_runtime_types(runtime_type))
    typed_descriptions = [
        item.description
        for item in (*conditions, *slots)
        if item.runtime_type in accepted_types and item.description
    ]
    return typed_descriptions[0] if len(typed_descriptions) == 1 else ""


def _arg_prompt_payload(arg: FunctionArgSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": arg.name,
        "kind": arg.kind,
        "value_type": arg.runtime_type,
        "required": arg.required,
        "cardinality": arg.cardinality,
    }
    if arg.state_kind is not None:
        payload["state_kind"] = arg.state_kind
    if arg.object_kind is not None:
        payload["object_kind"] = arg.object_kind
    return payload


def _return_prompt_payload(item: FunctionReturnSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": item.name,
        "value_type": item.runtime_type,
        "state_kind": item.state_kind,
        "required": item.required,
    }
    if item.object_kind is not None:
        payload["object_kind"] = item.object_kind
    return payload


def _arg_kind(runtime_types: tuple[str, ...]) -> FunctionArgKind:
    if "Symbol" in runtime_types:
        return "symbol"
    if "PointRef" in runtime_types:
        return "point_ref"
    if "Condition" in runtime_types or "Constraint" in runtime_types:
        return "condition_read"
    return "slot_read"


def function_adapter_from_binding_rule(
    rule: MethodBindingRuleSpec,
) -> FunctionAdapterSpec:
    """Project a generic binding rule into a FunctionSpec compile adapter.

    Phase 5 deliberately keeps ``MethodBindingRuleSpec`` as the single source
    of selector truth.  Function adapters add typed function-call diagnostics
    and prompt/context projections, but they should not duplicate selector
    strings while the legacy binding rules are still the rollback oracle.
    """
    input_bindings = tuple(
        FunctionInputBindingSpec(
            input_name=item.input_name,
            selector=item.selector,
            required=item.required,
        )
        for item in rule.input_bindings
    )
    return FunctionAdapterSpec(
        adapter_id=rule.method_id,
        input_bindings=tuple(input_bindings),
        expansion_selectors=rule.expansion_selectors,
        constraint_analyzer=rule.constraint_analyzer,
    )


def _apply_constraint_analyzer(
    analyzer_id: str,
    *,
    inputs: dict[str, str],
    step: StepIntent,
    index: Any,
) -> dict[str, str]:
    analyzer = _CONSTRAINT_ANALYZERS.get(analyzer_id)
    if analyzer is None:
        raise StrategyDraftValidationError(
            f"function.constraint_analyzer_missing: {analyzer_id}"
        )
    return analyzer(inputs, step, index)


ConstraintAnalyzer = Callable[
    [dict[str, str], StepIntent, Any],
    dict[str, str],
]


def _analyze_quadratic_coefficient_inputs(
    inputs: dict[str, str],
    step: StepIntent,
    index: Any,
) -> dict[str, str]:
    if "free_parameter" in inputs or "free_parameters" in inputs:
        return inputs
    from shuxueshuo_server.solver.runtime.methods.quadratic_from_constraints import (
        analyze_quadratic_constraints,
    )

    runtime_inputs: dict[str, Any] = {}
    for name, path in inputs.items():
        try:
            # RuntimeContext can deterministically materialize a PointRef when
            # a numeric Point input is requested. The analyzer must use the
            # same typed-read semantics as InvocationExecutor; otherwise a
            # valid curve point reaches SymPy as an unsubscriptable PointRef.
            expected_type = (
                "Point" if name in {"curve_point", "p1", "p2"} else None
            )
            runtime_inputs[name] = index.context.read_path(
                path,
                from_scope_id=step.scope_id,
                expected_type=expected_type,
            ).value
        except KeyError:
            # A binding-only/preflight caller may register a future runtime
            # path without materializing its value. Inference is then unsafe;
            # leave the strict method invocation unchanged.
            return inputs
    analysis = analyze_quadratic_constraints(runtime_inputs)
    if analysis.status == "determined":
        return inputs
    if analysis.status == "single_free" and len(analysis.free_parameters) == 1:
        symbol = analysis.free_parameters[0]
        symbol_path = _visible_symbol_path(symbol.name, step=step, index=index)
        return {**inputs, "free_parameter": symbol_path}
    if analysis.status == "underdetermined":
        names = ",".join(symbol.name for symbol in analysis.free_parameters)
        raise StrategyDraftValidationError(
            "function.constraints_underdetermined: "
            f"step={step.step_id}, free_parameters={names or 'multiple'}"
        )
    raise StrategyDraftValidationError(
        "function.constraints_ambiguous: "
        f"step={step.step_id}, branch_count={analysis.branch_count}"
    )


_CONSTRAINT_ANALYZERS: dict[str, ConstraintAnalyzer] = {
    "quadratic_coefficients": _analyze_quadratic_coefficient_inputs,
}


def _visible_symbol_path(name: str, *, step: StepIntent, index: Any) -> str:
    for scope_id in reversed(index.handle_registry.ancestor_scopes(step.scope_id)):
        handle = f"symbol:{scope_id}:{name}"
        if handle in index.bindings:
            return index.path_for(handle, expected_type="Symbol")
    raise StrategyDraftValidationError(
        "function.arg_missing: "
        f"method=quadratic_from_constraints, arg=free_parameter, symbol={name}"
    )


def _effective_input_bindings(
    adapter: FunctionAdapterSpec,
    *,
    input_bindings_override: tuple[Any, ...] | None,
) -> tuple[FunctionInputBindingSpec, ...]:
    if input_bindings_override is None:
        return adapter.input_bindings
    by_name = {
        binding.input_name: binding
        for binding in adapter.input_bindings
    }
    order = [binding.input_name for binding in adapter.input_bindings]
    for binding in input_bindings_override:
        input_name = str(getattr(binding, "input_name"))
        if input_name not in by_name:
            order.append(input_name)
        by_name[input_name] = FunctionInputBindingSpec(
            input_name=input_name,
            selector=str(getattr(binding, "selector")),
            required=bool(getattr(binding, "required", True)),
        )
    return tuple(by_name[input_name] for input_name in order)


GENERIC_FUNCTION_BINDING_RULES: tuple[MethodBindingRuleSpec, ...] = (
    quadratic_from_constraints_rule(),
    quadratic_vertex_point_rule(),
    quadratic_x_axis_intercept_point_rule(),
    quadratic_y_axis_intercept_point_rule(),
    line_parabola_second_intersection_point_rule(),
    distance_between_points_rule(),
    midpoint_point_rule(),
    translated_point_rule(),
    line_intersection_point_rule(),
    parameter_from_curve_point_on_quadratic_rule(),
    parameter_from_expression_value_rule(),
    evaluate_expression_at_parameter_rule(),
    evaluate_point_at_parameter_rule(),
)

GENERIC_FUNCTION_METHOD_IDS: tuple[str, ...] = tuple(
    rule.method_id for rule in GENERIC_FUNCTION_BINDING_RULES
)

GENERIC_FUNCTION_ADAPTERS: dict[str, FunctionAdapterSpec] = {
    rule.method_id: function_adapter_from_binding_rule(rule)
    for rule in GENERIC_FUNCTION_BINDING_RULES
}
