"""FunctionSpec facade for generic method binding.

FunctionSpec is a planner/compiler-facing facade over existing MethodSpec and
CapabilityContract metadata.  Phase 5 keeps StepIntent as the LLM wire format
and MethodInvocation as the runtime format; the facade only provides a typed
adapter layer in between.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from shuxueshuo_server.solver.contracts import MethodSpec
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
    CapabilityContractSpec,
    MethodBindingRuleSpec,
    SolverFamilySpec,
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
from shuxueshuo_server.solver.utils import unique_ordered

FunctionArgKind = Literal["slot_read", "condition_read", "point_ref", "symbol", "auto"]
FunctionSpecSource = Literal["explicit_contract", "projected_contract", "method_spec"]
FunctionBindingStatus = Literal["success", "failure", "fallback"]

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

    def to_payload(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "input_bindings": [item.to_payload() for item in self.input_bindings],
            "expansion_selectors": list(self.expansion_selectors),
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

    def to_payload(self, *, include_adapter: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "function_id": self.function_id,
            "method_id": self.method_id,
            "goal_types": list(self.goal_types),
            "args": [item.to_payload() for item in self.args],
            "returns": [item.to_payload() for item in self.returns],
            "source": self.source,
            "notes": list(self.notes),
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
            if method_id not in GENERIC_FUNCTION_METHOD_IDS:
                continue
            try:
                method_spec = method_specs.require(method_id)
            except KeyError:
                continue
            contract = contracts.get(method_id)
            specs[method_id] = function_spec_from_method(
                method_spec,
                contract=contract,
                adapter=GENERIC_FUNCTION_ADAPTERS.get(method_id),
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
        items = [spec.to_prompt_payload() for spec in self.specs.values()]
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
            inputs[binding.input_name] = value
        if expansion_selectors_override is not None:
            expansions = expansion_selectors_override
        elif include_expansion_selectors:
            expansions = adapter.expansion_selectors
        else:
            expansions = ()
        for selector in expansions:
            inputs.update(self._expand(selector, step, index, local_outputs))
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
        _arg_spec_from_method_input(name, input_spec)
        for name, input_spec in method_spec.inputs.items()
    )
    returns = tuple(
        FunctionReturnSpec(
            name=output_name,
            output_key=output_name,
            runtime_type=output_type,
            state_kind=_state_kind_for_runtime_type(output_type),
            object_kind=_object_kind_for_runtime_type(output_type),
        )
        for output_name, output_type in method_spec.outputs.items()
    )
    return FunctionSpec(
        function_id=method_spec.method_id,
        method_id=method_spec.method_id,
        goal_types=method_spec.solves,
        args=args,
        returns=returns,
        adapter=adapter,
        source=source,
        notes=tuple(unique_ordered(notes)),
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
    return tuple(
        event for event in events
        if event.status in {"failure", "fallback"}
    )


def adapter_fallback_events(
    events: tuple[StepIntentFunctionBindingEvent, ...],
) -> tuple[StepIntentFunctionBindingEvent, ...]:
    return tuple(event for event in events if event.status == "fallback")


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


def assert_no_function_adapter_fallbacks(
    events: tuple[StepIntentFunctionBindingEvent, ...],
) -> None:
    """Compatibility alias; Phase 5b treats fallback as adapter failure."""
    assert_no_function_adapter_failures(events)


def _arg_spec_from_method_input(name: str, input_spec: Any) -> FunctionArgSpec:
    runtime_type = str(input_spec.type)
    runtime_types = _split_runtime_types(runtime_type)
    primary_type = runtime_types[0] if runtime_types else runtime_type
    kind = _arg_kind(runtime_types)
    return FunctionArgSpec(
        name=name,
        method_input=name,
        kind=kind,
        runtime_type=runtime_type,
        required=bool(getattr(input_spec, "required", True)),
        state_kind=(
            _state_kind_for_runtime_type(primary_type)
            if kind in {"slot_read", "condition_read"}
            else None
        ),
        object_kind=_object_kind_for_runtime_type(primary_type),
    )


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


def _split_runtime_types(runtime_type: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in runtime_type.split("|") if part.strip())


def _state_kind_for_runtime_type(runtime_type: str) -> str:
    if runtime_type in {"Parabola", "Expression", "MinimumExpression", "Equation"}:
        return "expression"
    if runtime_type in {"Point", "PointList"}:
        return "coordinate"
    if runtime_type == "Line":
        return "locus"
    if runtime_type == "Coefficients":
        return "coefficients"
    if runtime_type == "PathTransformation":
        return "transformation"
    if runtime_type == "StraighteningCandidate":
        return "candidate"
    if runtime_type == "ParameterValue":
        return "value"
    return runtime_type[:1].lower() + runtime_type[1:]


def _object_kind_for_runtime_type(runtime_type: str) -> str | None:
    if runtime_type in {"Parabola", "Function"}:
        return "function"
    if runtime_type in {"Point", "PointList"}:
        return "point"
    if runtime_type == "Line":
        return "line"
    if runtime_type == "ParameterValue":
        return "symbol"
    return None


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
