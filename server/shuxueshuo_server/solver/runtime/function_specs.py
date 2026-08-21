"""FunctionSpec facade for generic method binding.

FunctionSpec is a planner/compiler-facing facade over existing MethodSpec and
CapabilityContract metadata. FunctionalPlan is the LLM wire format and
MethodInvocation is the runtime format; the facade provides the typed adapter
layer in between.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Literal, Mapping

from shuxueshuo_server.solver.contracts import (
    MethodInputViewMode,
    MethodSpec,
    PlanTransformerScope,
    ScalarResultFormSpec,
    SymbolicClosureSpec,
    default_result_form_spec,
)
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
from shuxueshuo_server.solver.runtime.functional_compile_contract import (
    compile_input_handles as _compile_input_handles,
)
from shuxueshuo_server.solver.family.models import (
    CapabilityInputClosureRequirement,
    CapabilityDependencyPolicy,
    CapabilityContractSpec,
    CapabilityContextRoleBindingSpec,
    CapabilityStateClosurePolicy,
    FunctionalArgBindingAuthority,
    FunctionalSemanticRefRole,
    FunctionalOutputTargetSelectorSpec,
    FunctionalReturnBindingPolicy,
    MethodBindingRuleSpec,
    PathTransformationConsumerSpec,
    SolverFamilySpec,
    StateIdentityConstraintSpec,
    StateIdentityPolicy,
    StateLineageClosureSpec,
    StateObjectRoleProjectionSpec,
    StateWriteMode,
)
from shuxueshuo_server.solver.runtime.capability_contracts import (
    effective_contract_by_id,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.method_input_contracts import (
    method_input_requires_typed_entity_authority,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    FunctionalDiagnosticSubject,
    StatelessMethodError,
)
from shuxueshuo_server.solver.runtime.planner_public_types import (
    planner_output_value_type,
)
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    FunctionArgBindingRepair,
    FunctionalCompileStepView,
    FunctionalFunctionBindingEvent,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import (
    object_kind_for_runtime_type,
    state_kind_for_runtime_type,
)
from shuxueshuo_server.solver.utils import unique_ordered

FunctionArgKind = Literal["slot_read", "condition_read", "point_ref", "symbol", "auto"]
FunctionSpecSource = Literal["explicit_contract", "projected_contract", "method_spec"]
FunctionBindingStatus = Literal["success", "failure"]

BindingSelectorFn = Callable[[FunctionalCompileStepView, Any, Mapping[str, str]], str | None]
ExpansionSelectorFn = Callable[[FunctionalCompileStepView, Any, Mapping[str, str]], dict[str, str]]


@dataclass(frozen=True)
class FunctionArgSpec:
    """Typed function argument visible to planner/debug layers."""

    name: str
    kind: FunctionArgKind
    runtime_type: str
    domain_type: str
    view_mode: MethodInputViewMode
    required: bool = True
    cardinality: str = "one"
    state_kind: str | None = None
    object_kind: str | None = None
    method_input: str | None = None
    description: str = ""
    provides_semantic_roles: tuple[str, ...] = ()
    input_closure_policy: CapabilityStateClosurePolicy = "any"
    semantic_ref_role: FunctionalSemanticRefRole = "value"
    allows_anonymous_result: bool = False
    allows_empty_collection: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "domain_type": self.domain_type,
            "runtime_type": self.runtime_type,
            "view_mode": self.view_mode,
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
        if self.input_closure_policy != "any":
            payload["input_closure_policy"] = self.input_closure_policy
        if self.semantic_ref_role != "value":
            payload["semantic_ref_role"] = self.semantic_ref_role
        if self.allows_anonymous_result:
            payload["allows_anonymous_result"] = True
        if self.allows_empty_collection:
            payload["allows_empty_collection"] = True
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
    provides_semantic_roles: tuple[str, ...] = ()
    object_role_projections: tuple[StateObjectRoleProjectionSpec, ...] = ()
    lineage_closures: tuple[StateLineageClosureSpec, ...] = ()
    return_binding: FunctionalReturnBindingPolicy = "auto"
    output_target_selector: FunctionalOutputTargetSelectorSpec | None = None

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
        if self.provides_semantic_roles:
            payload["provides_semantic_roles"] = list(
                self.provides_semantic_roles
            )
        if self.object_role_projections:
            payload["object_role_projections"] = [
                item.to_payload() for item in self.object_role_projections
            ]
        if self.lineage_closures:
            payload["lineage_closures"] = [
                item.to_payload() for item in self.lineage_closures
            ]
        if self.return_binding != "auto":
            payload["return_binding"] = self.return_binding
        if self.output_target_selector is not None:
            payload["output_target_selector"] = (
                self.output_target_selector.to_payload()
            )
        return payload


@dataclass(frozen=True)
class FunctionInputBindingSpec:
    """Adapter binding from a function arg/method input to a selector primitive."""

    input_name: str
    selector: str
    required: bool = True
    functional_authority: FunctionalArgBindingAuthority | None = None
    functional_resolver: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "input_name": self.input_name,
            "selector": self.selector,
            "required": self.required,
        }
        if self.functional_authority is not None:
            payload["functional_authority"] = self.functional_authority
        if self.functional_resolver is not None:
            payload["functional_resolver"] = self.functional_resolver
        return payload


@dataclass(frozen=True)
class FunctionAggregateInputBindingSpec:
    """Compile one reconciled many-arg into fixed scalar method inputs."""

    source_input: str
    item_inputs: tuple[str, ...]
    singleton_input: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_input": self.source_input,
            "item_inputs": list(self.item_inputs),
            **(
                {"singleton_input": self.singleton_input}
                if self.singleton_input is not None
                else {}
            ),
        }


@dataclass(frozen=True)
class FunctionScalarAggregateLoweringSpec:
    source_input: str
    item_runtime_type: str
    identity_input: str
    value_input: str

    def to_payload(self) -> dict[str, object]:
        return {
            "source_input": self.source_input,
            "item_runtime_type": self.item_runtime_type,
            "identity_input": self.identity_input,
            "value_input": self.value_input,
        }


@dataclass(frozen=True)
class FunctionAdapterSpec:
    """Runtime adapter for compiling a FunctionSpec to MethodInvocation inputs."""

    adapter_id: str
    functional_input_names: tuple[tuple[str, str], ...] = ()
    functional_output_names: tuple[tuple[str, str], ...] = ()
    functional_output_target_selectors: tuple[
        FunctionalOutputTargetSelectorSpec, ...
    ] = ()
    input_bindings: tuple[FunctionInputBindingSpec, ...] = ()
    aggregate_input_bindings: tuple[FunctionAggregateInputBindingSpec, ...] = ()
    scalar_aggregate_lowerings: tuple[
        FunctionScalarAggregateLoweringSpec, ...
    ] = ()
    expansion_selectors: tuple[str, ...] = ()
    constraint_analyzer: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "functional_input_names": [
                list(item) for item in self.functional_input_names
            ],
            "functional_output_names": [
                list(item) for item in self.functional_output_names
            ],
            "functional_output_target_selectors": [
                item.to_payload()
                for item in self.functional_output_target_selectors
            ],
            "input_bindings": [item.to_payload() for item in self.input_bindings],
            "aggregate_input_bindings": [
                item.to_payload() for item in self.aggregate_input_bindings
            ],
            "scalar_aggregate_lowerings": [
                item.to_payload() for item in self.scalar_aggregate_lowerings
            ],
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
    plan_transformer_scope: PlanTransformerScope = "single_invocation"
    reconciliation_validators: tuple[str, ...] = ()
    repair_feedback_provider_id: str | None = None
    distinct_arg_groups: tuple[tuple[str, ...], ...] = ()
    interchangeable_arg_groups: tuple[tuple[str, ...], ...] = ()
    dependency_policy: CapabilityDependencyPolicy = "explicit_args"
    context_role_bindings: tuple[CapabilityContextRoleBindingSpec, ...] = ()
    path_transformation_consumer: PathTransformationConsumerSpec | None = None
    input_closure_requirements: tuple[
        CapabilityInputClosureRequirement, ...
    ] = ()
    identity_constraints: tuple[StateIdentityConstraintSpec, ...] = ()
    symbolic_closure: SymbolicClosureSpec | None = None

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
            "plan_transformer_scope": self.plan_transformer_scope,
            "reconciliation_validators": list(self.reconciliation_validators),
            "repair_feedback_provider_id": self.repair_feedback_provider_id,
            "distinct_arg_groups": [
                list(group) for group in self.distinct_arg_groups
            ],
            "interchangeable_arg_groups": [
                list(group) for group in self.interchangeable_arg_groups
            ],
            "dependency_policy": self.dependency_policy,
            "context_role_bindings": [
                item.to_payload() for item in self.context_role_bindings
            ],
            "path_transformation_consumer": (
                self.path_transformation_consumer.to_payload()
                if self.path_transformation_consumer is not None
                else None
            ),
            "input_closure_requirements": [
                item.to_payload() for item in self.input_closure_requirements
            ],
            "identity_constraints": [
                item.to_payload() for item in self.identity_constraints
            ],
            "symbolic_closure": (
                self.symbolic_closure.to_payload()
                if self.symbolic_closure is not None
                else None
            ),
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
        family_binding_rules = {
            rule.method_id: rule
            for rule in family_spec.method_binding_rules
        }
        specs: dict[str, FunctionSpec] = {}
        for method_id in family_spec.method_ids:
            try:
                method_spec = method_specs.require(method_id)
            except KeyError:
                continue
            contract = contracts.get(method_id)
            adapter = GENERIC_FUNCTION_ADAPTERS.get(method_id)
            projection_adapter = adapter
            if projection_adapter is None and method_id in family_binding_rules:
                projection_adapter = function_adapter_from_binding_rule(
                    family_binding_rules[method_id]
                )
            _validate_constraint_analyzer_consistency(
                method_spec,
                contract=contract,
                adapter=projection_adapter,
            )
            projected = function_spec_from_method(
                method_spec,
                contract=contract,
                adapter=projection_adapter,
            )
            # Family binding rules may rename the public Function facade while
            # the method remains on the legacy binding-rule execution path.
            # Preserve that execution classification after projecting names.
            specs[method_id] = (
                replace(projected, adapter=None)
                if adapter is None and projection_adapter is not None
                else projected
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
        self.last_arg_repairs: tuple[FunctionArgBindingRepair, ...] = ()

    def rule_for(self, method_id: str) -> FunctionAdapterSpec | None:
        return self.adapters.get(method_id)

    def bind(
        self,
        method_id: str,
        step: FunctionalCompileStepView,
        index: Any,
        *,
        local_outputs: Mapping[str, str] | None = None,
        include_expansion_selectors: bool = True,
        expansion_selectors_override: tuple[str, ...] | None = None,
        input_bindings_override: tuple[Any, ...] | None = None,
        exact_inputs: Mapping[str, str] | None = None,
        method_input_specs: Mapping[str, object] | None = None,
        distinct_arg_groups: tuple[tuple[str, ...], ...] = (),
        apply_constraint_analyzer: bool = True,
    ) -> dict[str, str]:
        local_outputs = local_outputs or {}
        self.last_arg_repairs = ()
        adapter = self.adapters.get(method_id)
        if adapter is None:
            raise StrategyDraftValidationError(
                f"function.adapter_missing: method={method_id}"
            )
        inputs: dict[str, str] = dict(exact_inputs or {})
        for binding in _effective_input_bindings(
            adapter,
            input_bindings_override=input_bindings_override,
        ):
            if binding.input_name in inputs:
                continue
            input_spec = (method_input_specs or {}).get(binding.input_name)
            if (
                getattr(index, "problem_binding_authority", False)
                and method_input_requires_typed_entity_authority(input_spec)
            ):
                if not binding.required:
                    continue
                raise StatelessMethodError(
                    "planner.method_input_view_authority_missing",
                    "production compiler entity input has no typed authority",
                    category="configuration",
                    retryability="configuration",
                    method_id=method_id,
                    step_id=step.step_id,
                    subjects=(
                        FunctionalDiagnosticSubject(
                            role=binding.input_name,
                            arg_name=binding.input_name,
                            expected_type=getattr(input_spec, "domain_type", None),
                            expected_state=getattr(
                                getattr(input_spec, "view", None),
                                "mode",
                                None,
                            ),
                        ),
                    ),
                    expected={
                        "missing_role": binding.input_name,
                        "authority_source": "method_input_read_authority",
                        "domain_type": getattr(input_spec, "domain_type", None),
                    },
                    observed={
                        "consumer_step": step.step_id,
                        "compiler_selector_id": binding.selector,
                        "typed_candidate_count": 0,
                    },
                    repair_action="fix_runtime_contract",
                    details={
                        "missing_role": binding.input_name,
                        "consumer_step": step.step_id,
                        "authority_source": "compiler_selector_typed_binding",
                    },
                )
            if (
                getattr(index, "problem_binding_authority", False)
                and binding.functional_authority == "wire"
                and binding.functional_resolver is None
            ):
                if binding.required:
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: wire-owned Functional "
                        "argument has no exact reconciled binding: "
                        f"method={method_id}, arg={binding.input_name}"
                    )
                continue
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
            if _expansion_conflicts_with_exact_arg(
                binding.input_name,
                value,
                exact_inputs=exact_inputs,
                distinct_arg_groups=distinct_arg_groups,
            ):
                if binding.required:
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: required selector conflicts "
                        "with explicit Functional argument identity: "
                        f"method={method_id}, arg={binding.input_name}"
                    )
                continue
            if _selector_requires_declared_read(binding.selector) and not _path_is_declared_read(
                value,
                step=step,
                index=index,
                local_outputs=local_outputs,
            ):
                if not binding.required:
                    continue
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
            expanded = identity_safe_parameter_value_expansion(
                expanded,
                existing_inputs=inputs,
            )
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
            for input_name, path in expanded.items():
                if _expansion_conflicts_with_exact_arg(
                    input_name,
                    path,
                    exact_inputs=exact_inputs,
                    distinct_arg_groups=distinct_arg_groups,
                ):
                    continue
                inputs.setdefault(input_name, path)
        if apply_constraint_analyzer and adapter.constraint_analyzer is not None:
            analyzed = _apply_constraint_analyzer(
                adapter.constraint_analyzer,
                inputs=inputs,
                step=step,
                index=index,
            )
            inputs = analyzed.inputs
            self.last_arg_repairs = analyzed.arg_repairs
        return inputs

    def _select(
        self,
        selector: str,
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
        index: Any,
        local_outputs: Mapping[str, str],
    ) -> dict[str, str]:
        fn = self.expansion_selectors.get(selector)
        if fn is None:
            raise StrategyDraftValidationError(
                f"function.adapter_expansion_missing: {selector}"
            )
        return fn(step, index, local_outputs)


def identity_safe_parameter_value_expansion(
    expanded: Mapping[str, str],
    *,
    existing_inputs: Mapping[str, str],
) -> dict[str, str]:
    """Keep an automatic ParameterValue only for the same Symbol input.

    ParameterValue expansion resolves its Symbol from write provenance and
    therefore emits the canonical runtime path for both members of the pair.
    If another selector has already bound a different ``parameter``, retaining
    only the value would create an invalid cross-Symbol substitution.  An
    explicit ParameterValue makes that mismatch a malformed call and must fail
    loud.  A legacy optional expansion may still be discarded when no explicit
    value was selected.
    """
    result = dict(expanded)
    parameter_value = result.get("parameter_value")
    expanded_parameter = result.get("parameter")
    existing_parameter = existing_inputs.get("parameter")
    if (
        parameter_value is not None
        and expanded_parameter is not None
        and existing_parameter is not None
        and existing_parameter != expanded_parameter
    ):
        if existing_inputs.get("parameter_value") is not None:
            raise StrategyDraftValidationError(
                "function.parameter_value_object_mismatch: "
                f"parameter={existing_parameter}, "
                f"parameter_value_owner={expanded_parameter}"
            )
        result.pop("parameter", None)
        result.pop("parameter_value", None)
    return result


def _expansion_conflicts_with_exact_arg(
    input_name: str,
    path: str,
    *,
    exact_inputs: Mapping[str, str] | None,
    distinct_arg_groups: tuple[tuple[str, ...], ...],
) -> bool:
    """Keep heuristic expansion from reassigning an explicit arg identity."""
    if not exact_inputs:
        return False
    for group in distinct_arg_groups:
        if input_name not in group:
            continue
        if any(
            peer != input_name and exact_inputs.get(peer) == path
            for peer in group
        ):
            return True
    return False


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
    step: FunctionalCompileStepView,
    index: Any,
    local_outputs: Mapping[str, str],
) -> bool:
    if path in local_outputs.values():
        return True
    return any(
        getattr(index.bindings.get(handle), "path", None) == path
        for handle in _compile_input_handles(step)
    )

def function_spec_from_method(
    method_spec: MethodSpec,
    *,
    contract: CapabilityContractSpec | None,
    adapter: FunctionAdapterSpec | None,
) -> FunctionSpec:
    """Derive a FunctionSpec from runtime method and contract metadata."""
    _validate_internal_output_contract(method_spec, contract=contract)
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
    functional_input_name_pairs = (
        adapter.functional_input_names if adapter is not None else ()
    )
    functional_output_name_pairs = (
        adapter.functional_output_names if adapter is not None else ()
    )
    _validate_functional_name_mapping(
        functional_input_name_pairs,
        runtime_names=tuple(method_spec.inputs),
        kind="input",
        method_id=method_spec.method_id,
    )
    _validate_functional_name_mapping(
        functional_output_name_pairs,
        runtime_names=tuple(method_spec.outputs),
        kind="output",
        method_id=method_spec.method_id,
    )
    functional_input_names = dict(functional_input_name_pairs)
    functional_output_names = dict(functional_output_name_pairs)
    output_target_selectors = {
        item.output_name: item
        for item in (
            adapter.functional_output_target_selectors
            if adapter is not None
            else ()
        )
    }
    if len(output_target_selectors) != len(
        adapter.functional_output_target_selectors if adapter is not None else ()
    ):
        raise ValueError(
            "functional.capability_contract_invalid: duplicate output target "
            f"selector: {method_spec.method_id}"
        )
    unknown_selector_outputs = sorted(
        set(output_target_selectors) - set(method_spec.outputs)
    )
    if unknown_selector_outputs:
        raise ValueError(
            "functional.capability_contract_invalid: output target selector "
            f"references unknown outputs: {method_spec.method_id}: "
            f"{unknown_selector_outputs}"
        )
    args = tuple(
        _arg_spec_from_method_input(
            name,
            input_spec,
            contract=contract,
            functional_name=functional_input_names.get(name),
        )
        for name, input_spec in method_spec.inputs.items()
    )
    returns: list[FunctionReturnSpec] = []
    for output_name, output_type in method_spec.outputs.items():
        if output_name in method_spec.internal_outputs:
            continue
        contract_write = _function_return_contract_write(
            contract,
            output_name=output_name,
            output_type=output_type,
        )
        identity_policy, identity_arg = _function_return_identity(
            method_spec,
            output_type=output_type,
            adapter=adapter,
            contract_write=contract_write,
        )
        write_mode = _function_return_write_mode(
            contract,
            method_spec=method_spec,
            output_type=output_type,
            identity_policy=identity_policy,
            identity_arg=identity_arg,
        )
        returns.append(
            FunctionReturnSpec(
                name=functional_output_names.get(output_name, output_name),
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
                scalar_result_form=(
                    method_spec.scalar_result_forms.get(output_name)
                    or (
                        contract_write.result_form
                        if contract_write is not None
                        else None
                    )
                    or default_result_form_spec(output_type)
                ),
                provides_semantic_roles=(
                    contract_write.provides_semantic_roles
                    if contract_write is not None
                    else ()
                ),
                object_role_projections=(
                    contract_write.object_role_projections
                    if contract_write is not None
                    else ()
                ),
                lineage_closures=(
                    contract_write.lineage_closures
                    if contract_write is not None
                    else ()
                ),
                return_binding=(
                    contract_write.return_binding
                    if contract_write is not None
                    else "auto"
                ),
                output_target_selector=(
                    replace(
                        output_target_selectors[output_name],
                        output_name=functional_output_names.get(
                            output_name,
                            output_name,
                        ),
                        related_arg=(
                            functional_input_names.get(
                                output_target_selectors[
                                    output_name
                                ].related_arg,
                                output_target_selectors[
                                    output_name
                                ].related_arg,
                            )
                            if output_target_selectors[
                                output_name
                            ].related_arg
                            is not None
                            else None
                        ),
                    )
                    if output_name in output_target_selectors
                    else None
                ),
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
        plan_transformer_scope=method_spec.plan_transformer_scope,
        reconciliation_validators=method_spec.reconciliation_validators,
        repair_feedback_provider_id=method_spec.repair_feedback_provider_id,
        distinct_arg_groups=method_spec.distinct_arg_groups,
        interchangeable_arg_groups=method_spec.interchangeable_arg_groups,
        dependency_policy=(
            contract.dependency_policy
            if contract is not None
            else "explicit_args"
        ),
        context_role_bindings=(
            contract.context_role_bindings if contract is not None else ()
        ),
        path_transformation_consumer=(
            contract.path_transformation_consumer
            if contract is not None
            else None
        ),
        input_closure_requirements=(
            contract.input_closure_requirements
            if contract is not None
            else ()
        ),
        identity_constraints=(
            contract.identity_constraints if contract is not None else ()
        ),
        symbolic_closure=method_spec.symbolic_closure,
        notes=tuple(unique_ordered(notes)),
    )


def _validate_functional_name_mapping(
    pairs: tuple[tuple[str, str], ...],
    *,
    runtime_names: tuple[str, ...],
    kind: str,
    method_id: str,
) -> None:
    runtime_keys = [item[0] for item in pairs]
    public_values = [item[1] for item in pairs]
    unknown = sorted(set(runtime_keys) - set(runtime_names))
    duplicate_runtime = sorted(
        name for name in set(runtime_keys) if runtime_keys.count(name) > 1
    )
    mapping = dict(pairs)
    projected_names = [mapping.get(name, name) for name in runtime_names]
    duplicate_public = sorted(
        name
        for name in set(projected_names)
        if projected_names.count(name) > 1
    )
    if (
        unknown
        or duplicate_runtime
        or duplicate_public
        or any(not name.strip() for name in public_values)
    ):
        raise ValueError(
            "function.functional_name_mapping_invalid: "
            f"{method_id}.{kind}: unknown={unknown}, "
            f"duplicate_runtime={duplicate_runtime}, "
            f"duplicate_public={duplicate_public}"
        )


def _validate_internal_output_contract(
    method_spec: MethodSpec,
    *,
    contract: CapabilityContractSpec | None,
) -> None:
    """Keep runtime-only outputs out of the Functional state contract."""

    if contract is None or not method_spec.internal_outputs:
        return
    exposed_internal_outputs = tuple(
        item.output_key
        for item in contract.slot_writes
        if item.output_key in method_spec.internal_outputs
    )
    if exposed_internal_outputs:
        raise ValueError(
            "internal method outputs cannot be Functional state writes: "
            f"method={method_spec.method_id}, outputs="
            + ", ".join(exposed_internal_outputs)
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
    contract_write: StateSlotPattern | None,
) -> tuple[StateIdentityPolicy, str | None]:
    if (
        contract_write is not None
        and contract_write.identity_policy is not None
    ):
        return (
            contract_write.identity_policy,
            contract_write.identity_arg,
        )
    if output_type == "ParameterValue":
        for input_name in ("target_parameter", "parameter"):
            if input_name in method_spec.inputs:
                return "preserve_input_object", input_name
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
    method_spec: MethodSpec,
    output_type: str,
    identity_policy: StateIdentityPolicy,
    identity_arg: str | None,
) -> StateWriteMode:
    """Project write semantics, including same-object state transitions."""
    if identity_policy == "preserve_input_object" and identity_arg is not None:
        identity_input = method_spec.inputs.get(identity_arg)
        if (
            identity_input is not None
            and output_type in split_runtime_types(str(identity_input.type))
        ):
            return "transition"
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
    events: tuple[FunctionalFunctionBindingEvent, ...],
) -> tuple[FunctionalFunctionBindingEvent, ...]:
    return tuple(event for event in events if event.status == "failure")


def assert_no_function_adapter_failures(
    events: tuple[FunctionalFunctionBindingEvent, ...],
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
    functional_name: str | None = None,
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
    if kind == "symbol" and contract_slot is not None:
        kind = "slot_read"
    return FunctionArgSpec(
        name=functional_name or name,
        method_input=name,
        kind=kind,
        runtime_type=runtime_type,
        domain_type=input_spec.domain_type,
        view_mode=input_spec.view.mode,
        required=bool(getattr(input_spec, "required", True)),
        state_kind=(
            state_kind_for_runtime_type(primary_type)
            if kind in {"slot_read", "condition_read"}
            else None
        ),
        object_kind=object_kind_for_runtime_type(primary_type),
        description=(
            _function_arg_contract_description(
                contract,
                name=name,
                runtime_type=runtime_type,
                kind=kind,
            )
            or str(getattr(input_spec, "role", "")).strip()
        ),
        provides_semantic_roles=(
            contract_slot.provides_semantic_roles
            if contract_slot is not None
            else ()
        ),
        input_closure_policy=(
            contract_slot.input_closure_policy
            if contract_slot is not None
            else "any"
        ),
        allows_anonymous_result=bool(
            getattr(input_spec, "allows_anonymous_result", False)
        ),
        allows_empty_collection=bool(
            getattr(input_spec, "allows_empty_collection", False)
        ),
    )


def _function_arg_contract_slot(
    contract: CapabilityContractSpec | None,
    *,
    name: str,
    runtime_type: str,
    kind: FunctionArgKind,
) -> Any | None:
    if contract is None or kind not in {"slot_read", "symbol"}:
        return None
    named = [item for item in contract.slot_reads if item.semantic_role == name]
    if len(named) == 1:
        return named[0]
    if kind == "symbol":
        return None
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
    if kind not in {"condition_read", "slot_read", "symbol"}:
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
        "domain_type": arg.domain_type,
        "required": arg.required,
        "cardinality": arg.cardinality,
    }
    return payload


def _return_prompt_payload(item: FunctionReturnSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": item.name,
        "type": planner_output_value_type(item.runtime_type),
        "required": item.required,
    }
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
            functional_authority=item.functional_authority,
            functional_resolver=item.functional_resolver,
        )
        for item in rule.input_bindings
    )
    aggregate_input_bindings = tuple(
        FunctionAggregateInputBindingSpec(
            source_input=item.source_input,
            item_inputs=item.item_inputs,
            singleton_input=item.singleton_input,
        )
        for item in rule.aggregate_input_bindings
    )
    scalar_aggregate_lowerings = tuple(
        FunctionScalarAggregateLoweringSpec(
            source_input=item.source_input,
            item_runtime_type=item.item_runtime_type,
            identity_input=item.identity_input,
            value_input=item.value_input,
        )
        for item in rule.scalar_aggregate_lowerings
    )
    return FunctionAdapterSpec(
        adapter_id=rule.method_id,
        functional_input_names=rule.functional_input_names,
        functional_output_names=rule.functional_output_names,
        functional_output_target_selectors=(
            rule.functional_output_target_selectors
        ),
        input_bindings=tuple(input_bindings),
        aggregate_input_bindings=aggregate_input_bindings,
        scalar_aggregate_lowerings=scalar_aggregate_lowerings,
        expansion_selectors=rule.expansion_selectors,
        constraint_analyzer=rule.constraint_analyzer,
    )


def _apply_constraint_analyzer(
    analyzer_id: str,
    *,
    inputs: dict[str, Any],
    step: FunctionalCompileStepView,
    index: Any,
) -> ConstraintAnalyzerResult:
    analyzer = _CONSTRAINT_ANALYZERS.get(analyzer_id)
    if analyzer is None:
        raise StrategyDraftValidationError(
            f"function.constraint_analyzer_missing: {analyzer_id}"
        )
    return analyzer(inputs, step, index)


@dataclass(frozen=True)
class ConstraintAnalyzerResult:
    inputs: dict[str, Any]
    arg_repairs: tuple[FunctionArgBindingRepair, ...] = ()


ConstraintAnalyzer = Callable[
    [dict[str, Any], FunctionalCompileStepView, Any],
    ConstraintAnalyzerResult,
]


def _analyze_quadratic_coefficient_inputs(
    inputs: dict[str, Any],
    step: FunctionalCompileStepView,
    index: Any,
) -> ConstraintAnalyzerResult:
    from shuxueshuo_server.solver.runtime.methods.quadratic_from_constraints import (
        analyze_quadratic_constraints,
        equivalent_quadratic_free_parameter_bases,
    )
    from shuxueshuo_server.solver.runtime.functional_diagnostics import (
        method_input_invalid,
        method_input_state_unavailable,
        method_result_ambiguous,
        method_result_inconsistent,
    )
    from shuxueshuo_server.solver.runtime.symbolic_state_representation import (
        SymbolicStateRepresentationError,
    )

    runtime_inputs: dict[str, Any] = {}
    for name, path in inputs.items():
        try:
            if isinstance(path, tuple):
                item_expected_type = (
                    "Point" if name == "curve_points" else None
                )
                runtime_inputs[name] = [
                    index.context.read_path(
                        item_path,
                        from_scope_id=step.scope_id,
                        expected_type=item_expected_type,
                    ).value
                    for item_path in path
                ]
                continue
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
            return ConstraintAnalyzerResult(inputs)
    declared_free_parameters = _declared_free_parameters(runtime_inputs)
    target_parameter = runtime_inputs.get("target_parameter")
    if target_parameter is not None:
        if target_parameter in declared_free_parameters:
            name = getattr(target_parameter, "name", str(target_parameter))
            raise method_input_invalid(
                "target parameter cannot also be preserved as a free parameter",
                method_id="quadratic_from_constraints",
                scope_id=step.scope_id,
                step_id=step.step_id,
                arg_name="target_parameter",
                role="quadratic_target_parameter",
                internal_ref=name,
                expected={"target_parameter_not_preserved": name},
                observed={"preserved_free_parameters": [name]},
                repair_action="separate_target_and_free_parameters",
            )
        # Targeted closure is authoritative in the shared runtime solver. Keep
        # the explicit free basis intact instead of letting the older
        # coefficient-shape analyzer discard contextual dependency Symbols.
        return ConstraintAnalyzerResult(inputs)
    try:
        analysis = analyze_quadratic_constraints(
            {
                name: value
                for name, value in runtime_inputs.items()
                if name not in {"free_parameter", "free_parameters"}
            },
        )
    except SymbolicStateRepresentationError as exc:
        expected = {
            "requested_symbols": [
                symbol.name for symbol in exc.requested_symbols
            ],
            "unique_representation": True,
        }
        observed = {
            "current_symbols": [
                symbol.name for symbol in exc.current_symbols
            ],
            "branch_count": exc.branch_count,
        }
        if exc.code == "function.state_representation_ambiguous":
            raise method_result_ambiguous(
                str(exc),
                method_id="quadratic_from_constraints",
                scope_id=step.scope_id,
                step_id=step.step_id,
                expected=expected,
                observed=observed,
                repair_action="align_symbolic_state_basis",
            ) from exc
        if exc.code == "function.state_representation_inconsistent":
            raise method_result_inconsistent(
                str(exc),
                method_id="quadratic_from_constraints",
                scope_id=step.scope_id,
                step_id=step.step_id,
                expected=expected,
                observed=observed,
                retryability="planner_repairable",
                repair_action="revise_quadratic_constraints",
            ) from exc
        raise method_input_state_unavailable(
            str(exc),
            method_id="quadratic_from_constraints",
            scope_id=step.scope_id,
            step_id=step.step_id,
            arg_name="free_parameters",
            role="symbolic_state_basis",
            expected=expected,
            observed=observed,
            repair_action="align_symbolic_state_basis",
        ) from exc
    if analysis.status == "determined" and not declared_free_parameters:
        return ConstraintAnalyzerResult(inputs)
    declared_basis = tuple(
        sorted(
            declared_free_parameters,
            key=lambda symbol: getattr(symbol, "name", str(symbol)),
        )
    )
    equivalent_bases = equivalent_quadratic_free_parameter_bases(
        {
            name: value
            for name, value in runtime_inputs.items()
            if name not in {"free_parameter", "free_parameters"}
        }
    )
    if equivalent_bases:
        if declared_basis in equivalent_bases:
            return ConstraintAnalyzerResult(inputs)
        declared = ",".join(
            symbol.name
            for symbol in sorted(declared_free_parameters, key=lambda item: item.name)
        )
        raise method_input_state_unavailable(
            (
                "open quadratic state requires an explicit non-empty "
                "free_parameters basis"
                if not declared_basis
                else (
                    "declared free parameters do not form a complete runtime "
                    "quadratic-state basis"
                )
            ),
            method_id="quadratic_from_constraints",
            scope_id=step.scope_id,
            step_id=step.step_id,
            arg_name="free_parameters",
            role="symbolic_state_basis",
            expected={
                "allowed_free_parameter_bases": [
                    [symbol.name for symbol in basis]
                    for basis in equivalent_bases
                ],
                "basis_cardinality": len(equivalent_bases[0]),
            },
            observed={
                "declared_free_parameters": declared.split(",") if declared else []
            },
            repair_action="provide_or_align_symbolic_state_basis",
        )
    if analysis.status == "determined":
        declared = ",".join(
            symbol.name
            for symbol in sorted(declared_free_parameters, key=lambda item: item.name)
        )
        raise method_input_invalid(
            "quadratic state is closed but the call declares free parameters",
            method_id="quadratic_from_constraints",
            scope_id=step.scope_id,
            step_id=step.step_id,
            arg_name="free_parameters",
            role="symbolic_state_basis",
            expected={"free_parameters": []},
            observed={
                "declared_free_parameters": declared.split(",") if declared else []
            },
            repair_action="remove_redundant_free_parameters",
        )
    if analysis.status == "inconsistent":
        raise method_result_inconsistent(
            "quadratic constraints have no consistent branch",
            method_id="quadratic_from_constraints",
            scope_id=step.scope_id,
            step_id=step.step_id,
            expected={"branch_count_at_least": 1},
            observed={"branch_count": 0},
            retryability="planner_repairable",
            repair_action="revise_quadratic_constraints",
        )
    raise method_result_ambiguous(
        "quadratic constraints retain multiple branches",
        method_id="quadratic_from_constraints",
        scope_id=step.scope_id,
        step_id=step.step_id,
        expected={"branch_count": 1},
        observed={"branch_count": analysis.branch_count},
        repair_action="provide_additional_quadratic_constraint",
    )


def _declared_free_parameters(runtime_inputs: Mapping[str, Any]) -> set[Any]:
    result: set[Any] = set()
    single = runtime_inputs.get("free_parameter")
    if single is not None:
        result.add(single)
    many = runtime_inputs.get("free_parameters")
    if isinstance(many, (list, tuple, set, frozenset)):
        result.update(many)
    elif many is not None:
        result.add(many)
    return result


_CONSTRAINT_ANALYZERS: dict[str, ConstraintAnalyzer] = {
    "quadratic_coefficients": _analyze_quadratic_coefficient_inputs,
}


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
            functional_authority=getattr(
                binding,
                "functional_authority",
                None,
            ),
            functional_resolver=getattr(
                binding,
                "functional_resolver",
                None,
            ),
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
