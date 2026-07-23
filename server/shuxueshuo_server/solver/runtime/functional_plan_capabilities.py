"""Functional capability catalog projected from FunctionSpec and MacroSpec."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.contracts import MethodSpec
from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CapabilityInputClosureRequirement,
    SolverFamilySpec,
    StepRecipeSpec,
)
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionArgSpec,
    FunctionReturnSpec,
    FunctionSpec,
    FunctionSpecRegistry,
    function_adapter_from_binding_rule,
)
from shuxueshuo_server.solver.runtime.capability_contracts import (
    contract_is_prompt_executable,
    effective_contract_by_id,
)
from shuxueshuo_server.solver.runtime.binding_selector_semantics import (
    expansion_selector_semantics,
    selector_context_binding,
    selector_semantics,
)
from shuxueshuo_server.solver.runtime.context_closure import (
    validate_context_closure_resolvers,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalAggregation,
    FunctionalAutoArg,
    FunctionalCapability,
    FunctionalCapabilityArg,
    FunctionalCapabilityReturn,
    FunctionalContextArgBinding,
    FunctionalInputClosureRequirement,
)
from shuxueshuo_server.solver.runtime.functional_reconciliation_validators import (
    validate_reconciliation_validator_ids,
)
from shuxueshuo_server.solver.runtime.state_identity_constraints import (
    validate_state_identity_constraint_specs,
)
from shuxueshuo_server.solver.runtime.macro_specs import (
    MacroArgSpec,
    MacroReturnSpec,
    MacroSpec,
    MacroSpecRegistry,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)
from shuxueshuo_server.solver.state_semantics import (
    state_kind_for_runtime_type,
)


class FunctionalSemanticCatalog(Protocol):
    """Context query required by catalog satisfiability preflight."""

    def has_compatible_view(
        self,
        *,
        accepted_types: Sequence[str],
        accepted_condition_kinds: Sequence[str] = (),
        accepted_semantic_roles: Sequence[str] = (),
        requires_materialized_state: bool = False,
    ) -> bool: ...

    def auto_selector_is_satisfiable(self, selector: str) -> bool: ...


class FunctionalCapabilityCatalog:
    """The one opt-in call catalog projected from FunctionSpec/MacroSpec."""

    def __init__(self, items: Mapping[str, FunctionalCapability]) -> None:
        self.items = dict(items)

    @classmethod
    def from_family_spec(
        cls,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
    ) -> "FunctionalCapabilityCatalog":
        result: dict[str, FunctionalCapability] = {}
        macros = MacroSpecRegistry.from_family_spec(family_spec, method_specs)
        macro_ids = set(macros.specs)
        recipes_by_id = {
            recipe.recipe_id: recipe for recipe in family_spec.step_recipes
        }
        functions = FunctionSpecRegistry.from_family_spec(family_spec, method_specs)
        contracts = effective_contract_by_id(family_spec, method_specs)
        family_binding_rules = {
            rule.method_id: rule
            for rule in family_spec.method_binding_rules
        }
        function_arg_aliases = _function_arg_aliases(family_spec.step_recipes)
        for spec in functions.specs.values():
            # A recipe with the same public id owns the call boundary. Its
            # underlying method remains an internal macro call, so the catalog
            # still has one unambiguous capability kind.
            if spec.function_id in macro_ids:
                continue
            if not contract_is_prompt_executable(contracts.get(spec.method_id)):
                continue
            if spec.adapter is None and spec.method_id in family_binding_rules:
                spec = replace(
                    spec,
                    adapter=function_adapter_from_binding_rule(
                        family_binding_rules[spec.method_id]
                    ),
                )
            if spec.adapter is None:
                continue
            if any(note.startswith("contract_slot_write_missing:required:") for note in spec.notes):
                raise ValueError(
                    "planner_configuration_error: incomplete functional contract: "
                    f"{spec.function_id}"
                )
            _register_capability(
                result,
                _function_capability(
                    spec,
                    method_spec=method_specs.require(spec.method_id),
                    contract=contracts.get(spec.method_id),
                    arg_aliases=function_arg_aliases.get(spec.method_id, {}),
                ),
            )
        for spec in macros.specs.values():
            if not contract_is_prompt_executable(contracts.get(spec.recipe_id)):
                continue
            if any(note.startswith("macro_contract_mismatch:required:") for note in spec.notes):
                raise ValueError(
                    "planner_configuration_error: incomplete macro contract: "
                    f"{spec.macro_id}"
                )
            if not spec.returns:
                continue
            _register_capability(
                result,
                _macro_capability(
                    spec,
                    recipe=recipes_by_id[spec.recipe_id],
                    functions=functions,
                    family_binding_rules=family_binding_rules,
                    method_specs=method_specs,
                ),
            )
        if not result:
            raise ValueError("planner_configuration_error: functional catalog is empty")
        catalog = cls(result)
        catalog.require_satisfiable_configuration()
        return catalog

    def get(self, capability_id: str) -> FunctionalCapability | None:
        return self.items.get(capability_id)

    def to_prompt_payload(self) -> dict[str, Any]:
        items = [item.to_prompt_payload() for item in self.items.values()]
        return {"capabilities": items}

    def contextualized(
        self,
        semantic_catalog: FunctionalSemanticCatalog,
    ) -> "FunctionalCapabilityCatalog":
        """Keep capabilities constructible from Context or prior returns.

        Required explicit arguments may come from an initial Context view or
        from another capability that is itself constructible. Cyclic-only
        producer groups never enter the fixed point.
        """

        ready: dict[str, FunctionalCapability] = {}
        pending = dict(self.items)
        while pending:
            available_returns = tuple(
                result
                for capability in ready.values()
                for result in capability.returns
            )
            added = [
                capability_id
                for capability_id, capability in pending.items()
                if all(
                    not arg.required
                    or semantic_catalog.has_compatible_view(
                        accepted_types=(
                            arg.accepted_item_types or (arg.runtime_type,)
                        ),
                        accepted_condition_kinds=arg.accepted_condition_kinds,
                        accepted_semantic_roles=arg.accepted_semantic_roles,
                        requires_materialized_state=(
                            arg.requires_materialized_state
                        ),
                    )
                    or any(
                        _return_satisfies_arg(result, arg)
                        for result in available_returns
                    )
                    for arg in capability.args
                )
                and all(
                    semantic_catalog.auto_selector_is_satisfiable(auto.selector)
                    for auto in capability.auto_args
                )
                and all(
                    semantic_catalog.auto_selector_is_satisfiable(selector)
                    for selector in capability.context_preflight_selectors
                )
                and all(
                    _input_requirement_is_satisfiable(
                        capability,
                        requirement,
                        semantic_catalog=semantic_catalog,
                        available_returns=available_returns,
                    )
                    for requirement in capability.input_closure_requirements
                )
            ]
            if not added:
                break
            for capability_id in added:
                ready[capability_id] = pending.pop(capability_id)
        if not ready:
            raise ValueError(
                "planner_configuration_error: no functional capability is "
                "constructible from the current Context"
            )
        return FunctionalCapabilityCatalog(ready)

    def require_satisfiable_configuration(self) -> None:
        for capability in self.items.values():
            _ = capability.goal_type
            validate_reconciliation_validator_ids(
                capability.reconciliation_validators
            )
            arg_names = [item.name for item in capability.args]
            if len(arg_names) != len(set(arg_names)):
                raise ValueError(
                    "planner_configuration_error: duplicate functional semantic "
                    f"arg role: {capability.capability_id}"
                )
            public_args = {item.name for item in capability.args}
            auto_args = {item.name for item in capability.auto_args}
            semantic_args: dict[str, list[FunctionalCapabilityArg]] = {}
            for item in capability.args:
                semantic_args.setdefault(
                    item.semantic_role or item.name, []
                ).append(item)
            for arg in capability.args:
                if arg.aggregation not in _SUPPORTED_AGGREGATIONS:
                    raise ValueError(
                        "planner_configuration_error: functional aggregator "
                        f"missing: {capability.capability_id}.{arg.name}="
                        f"{arg.aggregation}"
                    )
            for result in capability.returns:
                if (
                    result.identity_policy == "preserve_input_object"
                    and result.identity_arg
                    and result.identity_arg not in public_args | auto_args
                ):
                    raise ValueError(
                        "planner_configuration_error: functional return identity "
                        f"source missing: {capability.capability_id}."
                        f"{result.name}->{result.identity_arg}"
                    )
            for requirement in capability.input_closure_requirements:
                targets = semantic_args.get(requirement.semantic_role, ())
                if len(targets) != 1:
                    raise ValueError(
                        "planner_configuration_error: input closure target "
                        f"must identify one arg: {capability.capability_id}."
                        f"{requirement.semantic_role}"
                    )
                if requirement.cardinality != "one":
                    raise ValueError(
                        "planner_configuration_error: unsupported input closure "
                        f"cardinality: {capability.capability_id}."
                        f"{requirement.semantic_role}={requirement.cardinality}"
                    )
                if not requirement.description.strip():
                    raise ValueError(
                        "planner_configuration_error: input closure requirement "
                        f"needs LLM guidance: {capability.capability_id}."
                        f"{requirement.semantic_role}"
                    )
                for provider_role in requirement.provider_arg_roles:
                    providers = semantic_args.get(provider_role, ())
                    if len(providers) != 1 or requirement.semantic_role not in (
                        providers[0].provides_semantic_roles
                    ):
                        raise ValueError(
                            "planner_configuration_error: input closure provider "
                            f"role is not declared: {capability.capability_id}."
                            f"{provider_role}->{requirement.semantic_role}"
                        )
            for resolver_id in capability.context_resolvers:
                if not any(
                    item.resolver_id == resolver_id
                    for item in capability.context_arg_bindings
                ):
                    raise ValueError(
                        "planner_configuration_error: context resolver has no "
                        "selector-projected arguments: "
                        f"{capability.capability_id}.{resolver_id}"
                    )


def functional_capability_catalog_payload(
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry,
    *,
    semantic_catalog: FunctionalSemanticCatalog | None = None,
) -> dict[str, Any]:
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        family_spec,
        method_specs,
    )
    if semantic_catalog is not None:
        catalog = catalog.contextualized(semantic_catalog)
    return catalog.to_prompt_payload()



def _function_capability(
    spec: FunctionSpec,
    *,
    method_spec: MethodSpec,
    contract: Any | None,
    arg_aliases: Mapping[str, tuple[str, ...]],
) -> FunctionalCapability:
    context_resolvers = tuple(
        getattr(contract, "context_resolvers", ())
        if contract is not None
        else ()
    )
    validate_context_closure_resolvers(context_resolvers)
    binding_by_input = {
        item.input_name: item
        for item in (spec.adapter.input_bindings if spec.adapter is not None else ())
    }
    public_source_args = tuple(
        item
        for item in spec.args
        if method_spec.inputs[item.name].functional_exposed
        if (
            item.kind in {"slot_read", "condition_read"}
            and (
                _contract_declares_named_slot(contract, item.name)
                or not _selector_is_mechanical(
                    binding_by_input.get(item.name).selector
                    if binding_by_input.get(item.name) is not None
                    else None
                )
            )
        )
        or (
            item.kind == "point_ref"
            and (binding := binding_by_input.get(item.name)) is not None
            and binding.selector == "right_angle:target"
        )
        or _semantic_evidence_resolver(
            binding_by_input.get(item.name).selector
            if binding_by_input.get(item.name) is not None
            else None
        )
        is not None
    )
    condition_patterns = tuple(
        getattr(contract, "condition_reads", ()) if contract is not None else ()
    )
    remaining_condition_patterns = list(condition_patterns)
    deterministic_resolvers = _deterministic_arg_resolvers(
        spec.adapter.expansion_selectors if spec.adapter is not None else ()
    )
    public_args_list: list[FunctionalCapabilityArg] = []
    for item in public_source_args:
        condition_pattern = None
        if item.kind == "condition_read":
            condition_pattern = next(
                (
                    pattern
                    for pattern in remaining_condition_patterns
                    if pattern.condition_kind == item.name
                ),
                remaining_condition_patterns[0]
                if remaining_condition_patterns
                else None,
            )
        if condition_pattern is not None:
            remaining_condition_patterns.remove(condition_pattern)
        binding = binding_by_input.get(item.name)
        evidence_resolver = _semantic_evidence_resolver(
            binding.selector if binding is not None else None
        )
        public_args_list.append(
            _function_arg(
                item,
                condition_pattern=condition_pattern,
                deterministic_resolver=(
                    evidence_resolver
                    or deterministic_resolvers.get(item.name)
                ),
                required_override=(
                    False
                    if evidence_resolver
                    else None
                ),
                accepted_semantic_roles=_selector_semantic_roles(
                    binding.selector if binding is not None else None
                ),
                accepted_condition_kinds=_selector_condition_kinds(
                    binding.selector if binding is not None else None
                ),
                requires_materialized_state=_arg_requires_materialized_state(
                    item,
                    binding.selector if binding is not None else None,
                ),
                aliases=arg_aliases.get(item.name, ()),
            )
        )
    represented_condition_kinds = {
        kind
        for item in public_args_list
        for kind in item.accepted_condition_kinds
    }
    # Contracts may declare structural evidence consumed only by selector
    # primitives. Expose that evidence as one semantic Condition arg while the
    # selector-derived runtime inputs remain hidden from the LLM.
    selector_prerequisite_kinds = {
        primitive.prerequisite_condition_kind
        for binding in binding_by_input.values()
        if (primitive := _selector_primitive(binding.selector)) is not None
    }
    for pattern in remaining_condition_patterns:
        if pattern.condition_kind not in selector_prerequisite_kinds:
            continue
        if pattern.condition_kind in represented_condition_kinds:
            continue
        public_args_list.append(_contract_condition_arg(pattern))
        represented_condition_kinds.add(pattern.condition_kind)
    public_args = tuple(public_args_list)
    public_names = {item.name for item in public_args}
    public_runtime_inputs = {
        item.runtime_input for item in public_args if item.runtime_input is not None
    }
    auto_args = tuple(
        FunctionalAutoArg(
            name=item.name,
            selector=binding.selector,
            required=binding.required,
        )
        for item in spec.args
        if item.name not in public_names
        and item.name not in public_runtime_inputs
        if (binding := binding_by_input.get(item.name)) is not None
    )
    returns = tuple(_function_return(item) for item in spec.returns)
    returns = _normalize_object_role_projection_args(
        returns,
        public_args,
    )
    returns = _optionalize_polymorphic_returns(public_args, returns)
    use_when, do_not_use_when = _usage_guidance(
        method_spec.summary or method_spec.title,
        method_spec.do_not_use_when,
        capability_id=spec.function_id,
    )
    capability = FunctionalCapability(
        capability_id=spec.function_id,
        kind="function",
        goal_types=spec.goal_types,
        title=method_spec.title,
        use_when=use_when,
        do_not_use_when=do_not_use_when,
        args=public_args,
        returns=returns,
        source=spec,
        is_pure=spec.is_pure,
        dependency_policy=spec.dependency_policy,
        reconciliation_validators=spec.reconciliation_validators,
        distinct_arg_groups=spec.distinct_arg_groups,
        context_resolvers=context_resolvers,
        context_arg_bindings=_context_arg_bindings(
            spec.adapter.input_bindings if spec.adapter is not None else (),
            context_resolvers=context_resolvers,
        ),
        auto_args=auto_args,
        context_preflight_selectors=_context_preflight_selectors(
            binding.selector for binding in binding_by_input.values()
        ),
        input_closure_requirements=_input_closure_requirements(
            spec.input_closure_requirements
        ),
        identity_constraints=spec.identity_constraints,
    )
    _validate_identity_contract(capability)
    return capability


def _contract_declares_named_slot(contract: Any | None, name: str) -> bool:
    if contract is None:
        return False
    return any(
        item.semantic_role == name
        for item in getattr(contract, "slot_reads", ())
    )


def _selector_is_mechanical(selector: str | None) -> bool:
    return selector_semantics(selector).mechanical


def _normalize_object_role_projection_args(
    returns: tuple[FunctionalCapabilityReturn, ...],
    args: Sequence[FunctionalCapabilityArg],
) -> tuple[FunctionalCapabilityReturn, ...]:
    names_by_runtime_input = {
        item.runtime_input: item.name
        for item in args
        if item.runtime_input is not None
    }
    return tuple(
        replace(
            returned,
            object_role_projections=tuple(
                replace(
                    projection,
                    source_arg=names_by_runtime_input.get(
                        projection.source_arg,
                        projection.source_arg,
                    ),
                )
                for projection in returned.object_role_projections
            ),
        )
        for returned in returns
    )


def _selector_semantic_roles(selector: str | None) -> tuple[str, ...]:
    return selector_semantics(selector).semantic_roles


def _selector_condition_kinds(selector: str | None) -> tuple[str, ...]:
    return selector_semantics(selector).condition_kinds


def _selector_requires_state(selector: str | None) -> bool:
    return selector_semantics(selector).requires_materialized_state


def _arg_requires_materialized_state(
    item: FunctionArgSpec,
    selector: str | None,
) -> bool:
    """Distinguish local Function projections from full-state consumers.

    A Function object already carries its expression template. An unrestricted
    ``Expression`` input can therefore evaluate a local projection such as
    ``f(0)`` without solving every coefficient first. Full ``Parabola``
    consumers retain the selector's materialized-state requirement.
    """
    if (
        selector is not None
        and selector.startswith("function:")
        and item.input_closure_policy == "any"
        and "Expression" in split_runtime_types(item.runtime_type)
    ):
        return False
    return _selector_requires_state(selector)


def _context_preflight_selectors(
    selectors: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            prerequisite
            for selector in selectors
            for prerequisite in selector_semantics(
                selector
            ).context_prerequisites
        )
    )


def _semantic_evidence_resolver(selector: str | None) -> str | None:
    return selector_semantics(selector).semantic_evidence_resolver


def _selector_primitive(selector: str) -> Any | None:
    semantics = selector_semantics(selector)
    return (
        semantics
        if semantics.prerequisite_condition_kind is not None
        else None
    )


def _contract_condition_arg(pattern: Any) -> FunctionalCapabilityArg:
    return FunctionalCapabilityArg(
        name=pattern.condition_kind,
        runtime_type=pattern.runtime_type,
        required=pattern.required,
        cardinality=pattern.cardinality,
        kind="condition_read",
        semantic_role=pattern.condition_kind,
        llm_mode=("explicit" if pattern.required else "optional"),
        accepted_item_types=(pattern.runtime_type,),
        accepted_condition_kinds=(pattern.condition_kind,),
        aggregation="none",
        runtime_input=None,
        description=pattern.description,
    )


def _deterministic_arg_resolvers(
    expansion_selectors: Sequence[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for selector in expansion_selectors:
        for arg_name, resolver in expansion_selector_semantics(
            selector
        ).arg_resolvers:
            previous = result.setdefault(arg_name, resolver)
            if previous != resolver:
                raise ValueError(
                    "planner_configuration_error: conflicting functional arg "
                    f"resolvers for {arg_name}: {previous}, {resolver}"
                )
    return result


def _macro_capability(
    spec: MacroSpec,
    *,
    recipe: StepRecipeSpec,
    functions: FunctionSpecRegistry,
    family_binding_rules: Mapping[str, Any],
    method_specs: MethodSpecRegistry,
) -> FunctionalCapability:
    validate_context_closure_resolvers(spec.context_resolvers)
    use_when, do_not_use_when = _usage_guidance(
        recipe.description,
        recipe.do_not_use_when,
        capability_id=spec.macro_id,
    )
    capability = FunctionalCapability(
        capability_id=spec.macro_id,
        kind="macro",
        goal_types=spec.goal_types,
        title=recipe.title,
        use_when=use_when,
        do_not_use_when=do_not_use_when,
        args=tuple(_macro_arg(item) for item in spec.args if item.kind != "auto"),
        returns=tuple(_macro_return(item) for item in spec.returns),
        source=spec,
        is_pure=spec.is_pure,
        dependency_policy=spec.dependency_policy,
        context_resolvers=spec.context_resolvers,
        context_arg_bindings=_macro_context_arg_bindings(
            spec,
            functions=functions,
            family_binding_rules=family_binding_rules,
            method_specs=method_specs,
        ),
        input_closure_requirements=_input_closure_requirements(
            spec.input_closure_requirements
        ),
        identity_constraints=spec.identity_constraints,
    )
    _validate_identity_contract(capability)
    return capability


def _validate_identity_contract(capability: FunctionalCapability) -> None:
    arg_names = tuple(
        dict.fromkeys(
            (
                *(item.name for item in capability.args),
                *(item.arg_name for item in capability.context_arg_bindings),
                *(item.name for item in capability.auto_args),
            )
        )
    )
    known_args = set(arg_names)
    for returned in capability.returns:
        for projection in returned.object_role_projections:
            if projection.source_arg not in known_args:
                raise ValueError(
                    "planner_configuration_error: object-role projection "
                    "references unknown arg: "
                    f"{capability.capability_id}.{projection.source_arg}"
                )
        for closure in returned.lineage_closures:
            missing = set(closure.source_args) - known_args
            if not closure.source_args or missing:
                raise ValueError(
                    "planner_configuration_error: lineage closure references "
                    "unknown args: "
                    f"{capability.capability_id}.{returned.name}="
                    f"{','.join(sorted(missing)) or 'none'}"
                )
    validate_state_identity_constraint_specs(
        capability.identity_constraints,
        arg_names=arg_names,
        return_names=tuple(item.name for item in capability.returns),
    )


def _input_closure_requirements(
    items: Sequence[CapabilityInputClosureRequirement],
) -> tuple[FunctionalInputClosureRequirement, ...]:
    return tuple(
        FunctionalInputClosureRequirement(
            semantic_role=item.semantic_role,
            provider_arg_roles=item.provider_arg_roles,
            cardinality=item.cardinality,
            description=item.description,
        )
        for item in items
    )


def _input_requirement_is_satisfiable(
    capability: FunctionalCapability,
    requirement: FunctionalInputClosureRequirement,
    *,
    semantic_catalog: FunctionalSemanticCatalog,
    available_returns: Sequence[FunctionalCapabilityReturn],
) -> bool:
    args_by_role = {
        item.semantic_role or item.name: item for item in capability.args
    }
    target = args_by_role[requirement.semantic_role]
    if semantic_catalog.has_compatible_view(
        accepted_types=target.accepted_item_types or (target.runtime_type,),
        accepted_condition_kinds=target.accepted_condition_kinds,
        accepted_semantic_roles=target.accepted_semantic_roles,
        requires_materialized_state=target.requires_materialized_state,
    ) or any(
        _return_satisfies_arg(result, target)
        for result in available_returns
    ):
        return True
    return any(
        requirement.semantic_role in result.provides_semantic_roles
        and any(
            _return_satisfies_arg(result, args_by_role[provider_role])
            for provider_role in requirement.provider_arg_roles
        )
        for result in available_returns
    )


def _macro_context_arg_bindings(
    spec: MacroSpec,
    *,
    functions: FunctionSpecRegistry,
    family_binding_rules: Mapping[str, Any],
    method_specs: MethodSpecRegistry,
) -> tuple[FunctionalContextArgBinding, ...]:
    input_bindings = []
    declared_bindings: list[FunctionalContextArgBinding] = []
    wired_inputs = {
        tuple(target.rsplit(".", 1))
        for _source, target in spec.adapter.intermediate_wiring
        if "." in target
    }
    for internal_call in spec.internal_calls:
        function = functions.get(internal_call.capability_id)
        adapter = function.adapter if function is not None else None
        if adapter is None:
            rule = family_binding_rules.get(internal_call.capability_id)
            if rule is not None:
                adapter = function_adapter_from_binding_rule(rule)
        if adapter is not None:
            input_bindings.extend(adapter.input_bindings)
        method_spec = method_specs.require(internal_call.capability_id)
        for input_spec in method_spec.inputs.values():
            if (
                not input_spec.role
                or (internal_call.capability_id, input_spec.name) in wired_inputs
            ):
                continue
            declared_bindings.extend(
                FunctionalContextArgBinding(
                    resolver_id=resolver_id,
                    semantic_role=input_spec.role,
                    arg_name=input_spec.name,
                )
                for resolver_id in spec.context_resolvers
            )
    selector_bindings = _context_arg_bindings(
        tuple(input_bindings),
        context_resolvers=spec.context_resolvers,
    )
    return _merge_context_arg_bindings(
        (*selector_bindings, *declared_bindings)
    )


def _context_arg_bindings(
    input_bindings: Sequence[Any],
    *,
    context_resolvers: Sequence[CapabilityContextResolver],
) -> tuple[FunctionalContextArgBinding, ...]:
    result: dict[tuple[str, str], FunctionalContextArgBinding] = {}
    enabled = set(context_resolvers)
    for input_binding in input_bindings:
        context_binding = selector_context_binding(input_binding.selector)
        if context_binding is None:
            continue
        resolver_id, semantic_role = context_binding
        if resolver_id not in enabled:
            continue
        key = (resolver_id, semantic_role)
        projected = FunctionalContextArgBinding(
            resolver_id=resolver_id,
            semantic_role=semantic_role,
            arg_name=input_binding.input_name,
        )
        previous = result.setdefault(key, projected)
        if previous != projected:
            raise ValueError(
                "planner_configuration_error: conflicting context resolver "
                f"argument binding: {resolver_id}.{semantic_role}"
            )
    return tuple(result.values())


def _merge_context_arg_bindings(
    bindings: Sequence[FunctionalContextArgBinding],
) -> tuple[FunctionalContextArgBinding, ...]:
    result: dict[tuple[str, str], FunctionalContextArgBinding] = {}
    for binding in bindings:
        key = (binding.resolver_id, binding.semantic_role)
        previous = result.setdefault(key, binding)
        if previous != binding:
            raise ValueError(
                "planner_configuration_error: conflicting context resolver "
                f"argument binding: {binding.resolver_id}."
                f"{binding.semantic_role}"
            )
    return tuple(result.values())


def _function_arg(
    item: FunctionArgSpec,
    *,
    condition_pattern: Any | None,
    deterministic_resolver: str | None = None,
    required_override: bool | None = None,
    accepted_semantic_roles: tuple[str, ...] = (),
    accepted_condition_kinds: tuple[str, ...] = (),
    requires_materialized_state: bool = False,
    aliases: tuple[str, ...] = (),
) -> FunctionalCapabilityArg:
    accepted_item_types, cardinality, aggregation = _lower_runtime_container(
        item.runtime_type,
        item.cardinality,
    )
    if condition_pattern is not None:
        accepted_item_types = tuple(
            dict.fromkeys((*accepted_item_types, "Condition"))
        )
    semantic_role = (
        condition_pattern.condition_kind
        if condition_pattern is not None
        else item.name
    )
    return FunctionalCapabilityArg(
        semantic_role,
        item.runtime_type,
        item.required if required_override is None else required_override,
        cardinality,
        item.kind,
        semantic_role=semantic_role,
        llm_mode=(
            "explicit"
            if (item.required if required_override is None else required_override)
            else "optional"
        ),
        accepted_item_types=accepted_item_types,
        accepted_condition_kinds=(
            accepted_condition_kinds
            or (
                (condition_pattern.condition_kind,)
                if condition_pattern is not None
                else ()
            )
        ),
        accepted_semantic_roles=accepted_semantic_roles,
        requires_materialized_state=requires_materialized_state,
        aggregation=aggregation,
        runtime_input=item.method_input or item.name,
        aliases=aliases,
        deterministic_resolver=deterministic_resolver,
        description=item.description,
        provides_semantic_roles=item.provides_semantic_roles,
        input_closure_policy=item.input_closure_policy,
    )


def _function_arg_aliases(
    recipes: Sequence[StepRecipeSpec],
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Project recipe input aliases onto their underlying public functions."""
    collected: dict[tuple[str, str], list[str]] = {}
    alias_targets: dict[tuple[str, str], str] = {}
    for recipe in recipes:
        execution = recipe.execution
        if execution is None:
            continue
        for alias, target in execution.input_aliases:
            method_id, separator, input_name = target.partition(".")
            if not separator or not method_id or not input_name:
                raise ValueError(
                    "planner_configuration_error: invalid recipe input alias: "
                    f"{recipe.recipe_id}.{alias}->{target}"
                )
            previous_target = alias_targets.setdefault(
                (method_id, alias),
                input_name,
            )
            if previous_target != input_name:
                raise ValueError(
                    "planner_configuration_error: conflicting functional arg "
                    f"alias: {method_id}.{alias} -> "
                    f"{previous_target}/{input_name}"
                )
            values = collected.setdefault((method_id, input_name), [])
            if alias != input_name and alias not in values:
                values.append(alias)
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    for (method_id, input_name), aliases in collected.items():
        result.setdefault(method_id, {})[input_name] = tuple(aliases)
    return result


def _macro_arg(item: MacroArgSpec) -> FunctionalCapabilityArg:
    accepted_item_types, cardinality, aggregation = _lower_runtime_container(
        item.runtime_type,
        item.cardinality,
    )
    semantic_role = _macro_semantic_role(item)
    return FunctionalCapabilityArg(
        semantic_role,
        item.runtime_type,
        item.required,
        cardinality,
        item.kind,
        semantic_role=semantic_role,
        llm_mode=("explicit" if item.required else "optional"),
        accepted_item_types=accepted_item_types,
        accepted_condition_kinds=(
            (item.condition_kind,) if item.condition_kind else ()
        ),
        aggregation=aggregation,
        runtime_input=item.name,
        description=item.description,
        provides_semantic_roles=item.provides_semantic_roles,
    )


_SUPPORTED_AGGREGATIONS: frozenset[FunctionalAggregation] = frozenset(
    {"none", "coefficients_by_symbol", "point_list", "symbol_list"}
)


def _lower_runtime_container(
    runtime_type: str,
    cardinality: str,
) -> tuple[tuple[str, ...], str, FunctionalAggregation]:
    container = {
        "Coefficients": (("ParameterValue",), "coefficients_by_symbol"),
        "PointList": (("Point",), "point_list"),
        "SymbolList": (("Symbol",), "symbol_list"),
    }.get(runtime_type)
    if container is not None:
        item_types, aggregation = container
        return item_types, "many", aggregation
    return (
        split_runtime_types(runtime_type),
        cardinality,
        "none",
    )


def _macro_semantic_role(item: MacroArgSpec) -> str:
    if item.semantic_role:
        return item.semantic_role
    if item.condition_kind:
        return item.condition_kind
    if item.state_kind:
        return item.state_kind
    return item.name


def _function_return(item: FunctionReturnSpec) -> FunctionalCapabilityReturn:
    write_mode = (
        "transition"
        if item.runtime_type == "Point"
        and item.identity_policy == "preserve_input_object"
        else item.write_mode
    )
    return FunctionalCapabilityReturn(
        item.name,
        item.runtime_type,
        item.required,
        "one",
        item.state_kind,
        item.semantic_role or item.name,
        item.identity_policy,
        item.identity_arg,
        write_mode,
        item.description,
        (
            item.scalar_result_form.possible_forms
            if item.scalar_result_form is not None
            else ()
        ),
        (
            item.scalar_result_form.description
            if item.scalar_result_form is not None
            else ""
        ),
        None,
        item.provides_semantic_roles,
        (),
        item.object_role_projections,
        item.lineage_closures,
        (
            item.scalar_result_form.max_independent_free_parameters
            if item.scalar_result_form is not None
            else None
        ),
    )


def _usage_guidance(
    use_when: str,
    do_not_use_when: Sequence[str],
    *,
    capability_id: str,
) -> tuple[str, tuple[str, ...]]:
    normalized_use_when = use_when.strip()
    if not normalized_use_when:
        raise ValueError(
            "planner_configuration_error: functional capability has empty "
            f"use_when: {capability_id}"
        )
    normalized_do_not: list[str] = []
    for item in do_not_use_when:
        value = item.strip()
        if not value:
            raise ValueError(
                "planner_configuration_error: functional capability has empty "
                f"do_not_use_when item: {capability_id}"
            )
        if value not in normalized_do_not:
            normalized_do_not.append(value)
    return normalized_use_when, tuple(normalized_do_not)


def _optionalize_polymorphic_returns(
    args: Sequence[FunctionalCapabilityArg],
    returns: tuple[FunctionalCapabilityReturn, ...],
) -> tuple[FunctionalCapabilityReturn, ...]:
    variant_types: set[str] = set()
    return_types = {item.runtime_type for item in returns}
    for arg in args:
        accepted = set(arg.accepted_item_types or (arg.runtime_type,))
        matching = accepted & return_types
        if len(matching) > 1:
            variant_types.update(matching)
    if not variant_types:
        return returns
    return tuple(
        replace(item, required=False)
        if item.runtime_type in variant_types
        else item
        for item in returns
    )


def _macro_return(item: MacroReturnSpec) -> FunctionalCapabilityReturn:
    return FunctionalCapabilityReturn(
        item.name,
        item.runtime_type,
        item.required,
        item.cardinality,
        item.state_kind or state_kind_for_runtime_type(item.runtime_type),
        item.semantic_role or item.name,
        item.identity_policy,
        item.identity_arg,
        item.write_mode,
        item.description,
        (
            item.scalar_result_form.possible_forms
            if item.scalar_result_form is not None
            else ()
        ),
        (
            item.scalar_result_form.description
            if item.scalar_result_form is not None
            else ""
        ),
        item.equivalent_to,
        item.provides_semantic_roles,
        tuple(item.goal_evidence_tags),
        item.object_role_projections,
        (),
        (
            item.scalar_result_form.max_independent_free_parameters
            if item.scalar_result_form is not None
            else None
        ),
    )


def _register_capability(
    result: dict[str, FunctionalCapability],
    item: FunctionalCapability,
) -> None:
    if item.capability_id in result:
        raise ValueError(
            "planner_configuration_error: duplicate functional capability id: "
            f"{item.capability_id}"
        )
    if not item.returns:
        raise ValueError(
            "planner_configuration_error: functional capability has no returns: "
            f"{item.capability_id}"
        )
    result[item.capability_id] = item


def _return_satisfies_arg(
    result: FunctionalCapabilityReturn,
    arg: FunctionalCapabilityArg,
) -> bool:
    accepted_types = arg.accepted_item_types or (arg.runtime_type,)
    if not any(
        runtime_type_compatible(expected, result.runtime_type)
        for expected in accepted_types
    ):
        return False
    if not arg.accepted_condition_kinds:
        condition_matches = True
    else:
        condition_matches = (
            result.runtime_type == "Condition"
            and result.semantic_role in arg.accepted_condition_kinds
        )
    return condition_matches and (
        not arg.accepted_semantic_roles
        or result.semantic_role in arg.accepted_semantic_roles
    )
