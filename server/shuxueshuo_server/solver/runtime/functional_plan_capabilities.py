"""Functional capability catalog projected from FunctionSpec and MacroSpec."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.contracts import (
    ConditionSourceSpec,
    EntityIdentitySourceSpec,
    ExactCallResultSourceSpec,
    FreeSymbolBasisDerivationSpec,
    MethodInputBindingSpec,
    MethodInputViewMode,
    MethodSpec,
    PublicArgSourceSpec,
    SourceObjectIdentityDerivationSpec,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CapabilityInputClosureRequirement,
    FunctionalArgBindingAuthority,
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
from shuxueshuo_server.solver.runtime.context_closure import (
    validate_context_closure_resolvers,
)
from shuxueshuo_server.solver.runtime.condition_kinds import (
    expand_condition_kinds,
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
from shuxueshuo_server.solver.runtime.functional_repair_feedback import (
    validate_capability_repair_feedback_provider_ids,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    validate_symbolic_closure_spec,
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
from shuxueshuo_server.solver.runtime.macro_blueprints import (
    MacroSemanticBlueprint,
    default_macro_blueprints,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner_public_types import (
    join_prompt_descriptions,
    planner_input_domain_type,
)
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

@dataclass(frozen=True)
class FunctionalIdentityArgOmission:
    """One optional identity input proven redundant and unconsumed."""

    arg_name: str
    removed_value: object
    duplicate_arg_names: tuple[str, ...]
    return_names: tuple[str, ...]


def referenced_functional_step_returns(
    payload: object,
) -> frozenset[tuple[str, str]]:
    """Collect every public StepResultRef-shaped consumer in a Plan wire."""

    result: set[tuple[str, str]] = set()

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            step_id = value.get("step_id")
            return_name = value.get("return")
            if isinstance(step_id, str) and isinstance(return_name, str):
                result.add((step_id, return_name))
            for item in value.values():
                visit(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(payload)
    return frozenset(result)


def unconsumed_duplicate_identity_arg_omissions(
    *,
    step_id: str,
    capability: FunctionalCapability,
    args: Mapping[str, object],
    return_bindings: Mapping[str, object],
    consumed_returns: frozenset[tuple[str, str]],
) -> tuple[FunctionalIdentityArgOmission, ...]:
    """Find optional identity inputs that duplicate another distinct role.

    This is the sole executable contract used by both content/v3 and scoped
    Plan normalization. Return expectations do not count as consumption;
    StepResultRef and answer consumers do. Merely declaring a derived return
    name does not keep an otherwise dead step alive.
    """

    remaining = dict(args)
    omissions: list[FunctionalIdentityArgOmission] = []
    returns_by_identity_arg: dict[str, tuple[str, ...]] = {
        arg.name: tuple(
            returned.name
            for returned in capability.returns
            if returned.identity_arg == arg.name
        )
        for arg in capability.args
    }
    for arg in capability.args:
        if arg.required or arg.name not in remaining:
            continue
        return_names = returns_by_identity_arg.get(arg.name, ())
        values = _functional_argument_values(remaining.get(arg.name))
        if not return_names or len(values) != 1:
            continue
        duplicate_arg_names = tuple(
            dict.fromkeys(
                peer_name
                for group in capability.distinct_arg_groups
                if arg.name in group
                for peer_name in group
                if peer_name != arg.name
                and values[0]
                in _functional_argument_values(remaining.get(peer_name))
            )
        )
        if not duplicate_arg_names:
            continue
        if any(
            (step_id, return_name) in consumed_returns
            or return_name in return_bindings
            for return_name in return_names
        ):
            continue
        omissions.append(
            FunctionalIdentityArgOmission(
                arg_name=arg.name,
                removed_value=values[0],
                duplicate_arg_names=duplicate_arg_names,
                return_names=return_names,
            )
        )
        remaining.pop(arg.name, None)
    return tuple(omissions)


def _functional_argument_values(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


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
        return FunctionalCapabilityCatalog(
            {
                capability_id: _contextualize_dynamic_macro_roles(
                    capability,
                    semantic_catalog=semantic_catalog,
                )
                for capability_id, capability in ready.items()
            }
        )

    def require_satisfiable_configuration(self) -> None:
        validate_capability_repair_feedback_provider_ids(
            getattr(capability.source, "repair_feedback_provider_id", None)
            for capability in self.items.values()
        )
        for capability in self.items.values():
            _ = capability.goal_type
            symbolic_closure = getattr(
                capability.source,
                "symbolic_closure",
                None,
            )
            if symbolic_closure is not None:
                validate_symbolic_closure_spec(
                    symbolic_closure,
                    input_types={
                        item.name: item.runtime_type
                        for item in capability.source.args
                    },
                    output_types={
                        item.name: item.runtime_type
                        for item in capability.source.returns
                    },
                )
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
                        "typed projected arguments: "
                        f"{capability.capability_id}.{resolver_id}"
                    )


@dataclass(frozen=True)
class FamilyCapabilityBundle:
    """One family-selected capability universe shared by Plan and retry."""

    family_id: str
    catalog: FunctionalCapabilityCatalog
    function_ids: tuple[str, ...]
    macro_ids: tuple[str, ...]
    macro_blueprints: Mapping[str, MacroSemanticBlueprint]
    bundle_signature: str
    schema_version: str = "family-capability-bundle/v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "function_ids", tuple(sorted(self.function_ids)))
        object.__setattr__(self, "macro_ids", tuple(sorted(self.macro_ids)))
        object.__setattr__(
            self,
            "macro_blueprints",
            MappingProxyType(dict(sorted(self.macro_blueprints.items()))),
        )
        known = set(self.catalog.items)
        if set(self.function_ids) | set(self.macro_ids) != known:
            raise ValueError(
                "planner_configuration_error: capability bundle partitions "
                "do not cover the catalog"
            )
        if set(self.function_ids).intersection(self.macro_ids):
            raise ValueError(
                "planner_configuration_error: Function and Macro ids overlap"
            )
        if not set(self.macro_blueprints).issubset(self.macro_ids):
            raise ValueError(
                "planner_configuration_error: blueprint references a non-Macro"
            )
        for macro_id, blueprint in self.macro_blueprints.items():
            if blueprint.macro_id != macro_id:
                raise ValueError(
                    "planner_configuration_error: blueprint Macro id drift"
                )
            unknown_functions = set(blueprint.function_capability_ids) - set(
                self.function_ids
            )
            if unknown_functions:
                raise ValueError(
                    "planner_configuration_error: blueprint exposes unknown "
                    f"Functions {sorted(unknown_functions)}"
                )
        expected_signature = stable_hash(self.authority_payload(include_signature=False))
        if self.bundle_signature != expected_signature:
            raise ValueError("planner.capability_bundle_signature_drift")

    @classmethod
    def from_family_spec(
        cls,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        *,
        macro_blueprints: Mapping[str, MacroSemanticBlueprint] | None = None,
    ) -> "FamilyCapabilityBundle":
        catalog = FunctionalCapabilityCatalog.from_family_spec(
            family_spec,
            method_specs,
        )
        function_ids = tuple(
            capability_id
            for capability_id, item in catalog.items.items()
            if item.kind == "function"
        )
        macro_ids = tuple(
            capability_id
            for capability_id, item in catalog.items.items()
            if item.kind == "macro"
        )
        available_blueprints = (
            dict(macro_blueprints)
            if macro_blueprints is not None
            else default_macro_blueprints()
        )
        selected_blueprints = {
            macro_id: blueprint
            for macro_id, blueprint in available_blueprints.items()
            if macro_id in macro_ids
        }
        payload = {
            "schema_version": "family-capability-bundle/v1",
            "family_id": family_spec.family_id,
            "capabilities": catalog.to_prompt_payload()["capabilities"],
            "function_ids": sorted(function_ids),
            "macro_ids": sorted(macro_ids),
            "macro_blueprints": {
                key: value.authority_payload()
                for key, value in sorted(selected_blueprints.items())
            },
        }
        return cls(
            family_id=family_spec.family_id,
            catalog=catalog,
            function_ids=function_ids,
            macro_ids=macro_ids,
            macro_blueprints=selected_blueprints,
            bundle_signature=stable_hash(payload),
        )

    def authority_payload(self, *, include_signature: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "family_id": self.family_id,
            "capabilities": self.catalog.to_prompt_payload()["capabilities"],
            "function_ids": list(self.function_ids),
            "macro_ids": list(self.macro_ids),
            "macro_blueprints": {
                key: value.authority_payload()
                for key, value in self.macro_blueprints.items()
            },
        }
        if include_signature:
            payload["bundle_signature"] = self.bundle_signature
        return payload

    def to_prompt_payload(
        self,
        *,
        semantic_catalog: FunctionalSemanticCatalog | None = None,
    ) -> dict[str, Any]:
        catalog = (
            self.catalog.contextualized(semantic_catalog)
            if semantic_catalog is not None
            else self.catalog
        )
        capabilities = []
        for item in catalog.items.values():
            payload = item.to_prompt_payload()
            blueprint = self.macro_blueprints.get(item.capability_id)
            if blueprint is not None:
                payload["semantic_blueprint"] = blueprint.to_prompt_payload()
            capabilities.append(payload)
        return {
            "schema_version": self.schema_version,
            "bundle_signature": self.bundle_signature,
            "capabilities": capabilities,
        }


def family_capability_bundle_for_inputs(inputs: Any) -> FamilyCapabilityBundle:
    """Return and validate the family-selected capability authority."""

    existing = getattr(inputs, "capability_bundle", None)
    if existing is None:
        return FamilyCapabilityBundle.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )
    if not isinstance(existing, FamilyCapabilityBundle):
        raise ValueError("planner.capability_bundle_contract_invalid")
    if existing.family_id != inputs.family_spec.family_id:
        raise ValueError("planner.capability_bundle_family_drift")
    expected = FamilyCapabilityBundle.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    if existing.bundle_signature != expected.bundle_signature:
        raise ValueError("planner.capability_bundle_signature_drift")
    return existing


def _contextualize_dynamic_macro_roles(
    capability: FunctionalCapability,
    *,
    semantic_catalog: FunctionalSemanticCatalog,
) -> FunctionalCapability:
    """Hide roles already proved by source structure; constrain ambiguities."""

    projector = getattr(semantic_catalog, "macro_role_ref_candidates", None)
    if not callable(projector):
        return capability
    candidates = projector(capability.capability_id)
    if candidates is None or not candidates:
        return capability
    dynamic_roles = frozenset(candidates)
    projected_args: list[FunctionalCapabilityArg] = []
    for arg in capability.args:
        if arg.name not in dynamic_roles:
            projected_args.append(arg)
            continue
        refs = tuple(candidates.get(arg.name, ()))
        if len(refs) <= 1:
            continue
        projected_args.append(replace(arg, allowed_refs=refs))
    return replace(capability, args=tuple(projected_args))


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
    authority_by_input = {
        (item.method_input or item.name): _functional_binding_authority(
            binding_by_input.get(item.method_input or item.name),
            contract_declares_input=_contract_declares_named_slot(
                contract,
                item.method_input or item.name,
            ),
            functional_exposed=method_spec.inputs[
                item.method_input or item.name
            ].functional_exposed,
            arg_kind=item.kind,
        )
        for item in spec.args
    }
    context_role_arg_names = {
        item.arg_name for item in spec.context_role_bindings
    }
    explicit_context_arg_names = {
        item.name
        for item in spec.args
        if item.name in context_role_arg_names
        or (item.method_input or item.name) in context_role_arg_names
        if (
            binding := binding_by_input.get(item.method_input or item.name)
        )
        is not None
        and isinstance(binding, MethodInputBindingSpec)
        and isinstance(binding.source, PublicArgSourceSpec)
    }
    context_owned_arg_names = (
        context_role_arg_names - explicit_context_arg_names
    )
    public_source_args = tuple(
        item
        for item in spec.args
        if method_spec.inputs[item.method_input or item.name].functional_exposed
        and authority_by_input[item.method_input or item.name] == "wire"
        and item.name not in context_owned_arg_names
        and (item.method_input or item.name) not in context_owned_arg_names
    )
    condition_patterns = tuple(
        getattr(contract, "condition_reads", ()) if contract is not None else ()
    )
    remaining_condition_patterns = list(condition_patterns)
    public_args_list: list[FunctionalCapabilityArg] = []
    for item in public_source_args:
        runtime_input = item.method_input or item.name
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
        binding = binding_by_input.get(runtime_input)
        evidence_resolver = _binding_evidence_resolver(binding)
        functional_arg = _function_arg(
            item,
            condition_pattern=condition_pattern,
            deterministic_resolver=(
                evidence_resolver
            ),
            required_override=(False if evidence_resolver else None),
            accepted_semantic_roles=_binding_semantic_roles(binding),
            accepted_condition_kinds=_binding_condition_kinds(binding),
            requires_materialized_state=_arg_requires_materialized_state(
                item,
            ),
            aliases=arg_aliases.get(runtime_input, ()),
            binding_authority=(
                "resolver"
                if item.name in context_owned_arg_names
                or runtime_input in context_owned_arg_names
                else "wire"
            ),
        )
        if (
            isinstance(binding, MethodInputBindingSpec)
            and isinstance(binding.source, ConditionSourceSpec)
            and binding.source.arg_name is not None
        ):
            functional_arg = replace(
                functional_arg,
                name=binding.source.arg_name,
            )
        contract_slot = _contract_named_slot(contract, item.name)
        if contract_slot is not None:
            functional_arg = replace(
                functional_arg,
                description=join_prompt_descriptions(
                    (
                        contract_slot.description.strip(),
                        functional_arg.description.strip(),
                    )
                ),
                semantic_ref_role=contract_slot.semantic_ref_role,
            )
        public_args_list.append(functional_arg)
    represented_condition_kinds = {
        kind
        for item in public_args_list
        for kind in item.accepted_condition_kinds
    }
    # Structural evidence remains public when a declared Condition relation or
    # resolver consumes it. Typed output allocation must not make the Fact
    # disappear merely because it is not a Method's public scalar argument.
    prerequisite_condition_kinds = {
        kind
        for binding in binding_by_input.values()
        if isinstance(binding.source, ConditionSourceSpec)
        for kind in binding.source.condition_kinds
    }
    if "condition_object_roles" in context_resolvers:
        prerequisite_condition_kinds.update(
            pattern.condition_kind for pattern in remaining_condition_patterns
        )
    for pattern in remaining_condition_patterns:
        if pattern.condition_kind not in prerequisite_condition_kinds:
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
            name=item.method_input or item.name,
            required=binding.required,
            input_binding=binding,
            binding_authority=authority_by_input[item.method_input or item.name],
            semantic_role=getattr(item, "semantic_role", None) or item.name,
            runtime_input=item.method_input or item.name,
        )
        for item in spec.args
        if (item.method_input or item.name) not in public_names
        and (item.method_input or item.name) not in public_runtime_inputs
        if (
            binding := binding_by_input.get(item.method_input or item.name)
        )
        is not None
    )
    public_output_names = dict(
        spec.adapter.functional_output_names
        if spec.adapter is not None
        else ()
    )
    returns = tuple(
        replace(
            _function_return(item),
            name=public_output_names.get(
                item.output_key or item.name,
                item.name,
            ),
        )
        for item in spec.returns
    )
    returns = _normalize_object_role_projection_args(
        returns,
        public_args,
    )
    returns = _optionalize_polymorphic_returns(public_args, returns)
    _validate_function_facade_coverage(
        spec,
        method_spec=method_spec,
        public_args=public_args,
        auto_args=auto_args,
        returns=returns,
    )
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
        interchangeable_arg_groups=spec.interchangeable_arg_groups,
        context_resolvers=context_resolvers,
        context_arg_bindings=_merge_context_arg_bindings(
            (
                *(
                    FunctionalContextArgBinding(
                        resolver_id=item.resolver_id,
                        semantic_role=item.semantic_role,
                        arg_name=item.arg_name,
                        consumption_mode="resolver_evidence",
                        input_binding=(
                            binding_by_input.get(item.arg_name)
                        ),
                    )
                    for item in spec.context_role_bindings
                ),
            )
        ),
        input_bindings=(
            spec.adapter.input_bindings
            if spec.adapter is not None
            else ()
        ),
        auto_args=auto_args,
        input_closure_requirements=_input_closure_requirements(
            spec.input_closure_requirements
        ),
        identity_constraints=spec.identity_constraints,
    )
    _validate_identity_contract(capability)
    return capability


def _validate_function_facade_coverage(
    spec: FunctionSpec,
    *,
    method_spec: MethodSpec,
    public_args: Sequence[FunctionalCapabilityArg],
    auto_args: Sequence[FunctionalAutoArg],
    returns: Sequence[FunctionalCapabilityReturn],
) -> None:
    input_names = [
        item.runtime_input or item.name for item in (*public_args, *auto_args)
    ]
    lowered_inputs = {
        input_name
        for binding in (
            spec.adapter.aggregate_input_bindings
            if spec.adapter is not None
            else ()
        )
        for input_name in (
            *binding.item_inputs,
            *((binding.singleton_input,) if binding.singleton_input else ()),
        )
    }
    lowered_inputs.update(
        input_name
        for lowering in (
            spec.adapter.scalar_aggregate_lowerings
            if spec.adapter is not None
            else ()
        )
        for input_name in (lowering.identity_input, lowering.value_input)
    )
    required_inputs = {
        name
        for name, item in method_spec.inputs.items()
        if bool(getattr(item, "required", True))
    }
    missing_inputs = sorted(
        required_inputs - set(input_names) - lowered_inputs
    )
    duplicate_inputs = sorted(
        name for name in set(input_names) if input_names.count(name) > 1
    )
    output_keys = [item.output_key or item.name for item in spec.returns]
    required_outputs = set(method_spec.outputs) - set(
        method_spec.internal_outputs
    )
    missing_outputs = sorted(required_outputs - set(output_keys))
    unknown_outputs = sorted(set(output_keys) - set(method_spec.outputs))
    return_names = [item.name for item in returns]
    duplicate_returns = sorted(
        name for name in set(return_names) if return_names.count(name) > 1
    )
    roles_by_type: dict[str, list[str]] = {}
    for item in returns:
        roles_by_type.setdefault(item.runtime_type, []).append(
            item.semantic_role
        )
    ambiguous_roles = sorted(
        runtime_type
        for runtime_type, roles in roles_by_type.items()
        if len(roles) > 1 and len(set(roles)) != len(roles)
    )
    public_arg_names = {item.name for item in public_args}
    selector_errors = sorted(
        item.name
        for item in returns
        if item.output_target_selector is not None
        and (
            item.output_target_selector.output_name != item.name
            or (
                item.output_target_selector.related_arg is not None
                and item.output_target_selector.related_arg
                not in public_arg_names
            )
            or item.binding_mode == "internal_only"
        )
    )
    if (
        missing_inputs
        or duplicate_inputs
        or missing_outputs
        or unknown_outputs
        or duplicate_returns
        or ambiguous_roles
        or selector_errors
    ):
        raise ValueError(
            "functional.capability_contract_invalid: "
            f"{spec.function_id}: missing_inputs={missing_inputs}, "
            f"duplicate_inputs={duplicate_inputs}, "
            f"missing_outputs={missing_outputs}, "
            f"unknown_outputs={unknown_outputs}, "
            f"duplicate_returns={duplicate_returns}, "
            f"ambiguous_return_roles={ambiguous_roles}, "
            f"invalid_output_target_selectors={selector_errors}"
        )


def _contract_declares_named_slot(contract: Any | None, name: str) -> bool:
    return _contract_named_slot(contract, name) is not None


def _contract_named_slot(contract: Any | None, name: str) -> Any | None:
    if contract is None:
        return None
    return next(
        (
            item
            for item in getattr(contract, "slot_reads", ())
            if item.semantic_role == name
        ),
        None,
    )


def _functional_binding_authority(
    binding: Any | None,
    *,
    contract_declares_input: bool,
    functional_exposed: bool,
    arg_kind: str,
) -> str:
    if contract_declares_input:
        return "wire"
    if binding is None:
        return (
            "wire"
            if arg_kind in {"slot_read", "condition_read"}
            else "compiler"
        )
    if isinstance(
        binding.source,
        (
            PublicArgSourceSpec,
            ExactCallResultSourceSpec,
            ConditionSourceSpec,
        ),
    ):
        if not isinstance(binding.source, ConditionSourceSpec) or (
            binding.source.arg_name is not None
        ):
            return "wire"
        return "resolver"
    if (
        functional_exposed
        and isinstance(binding.derivation, FreeSymbolBasisDerivationSpec)
    ):
        return "wire"
    return "compiler"


def _binding_evidence_resolver(binding: Any | None) -> str | None:
    if isinstance(binding, MethodInputBindingSpec) and isinstance(
        binding.derivation,
        (FreeSymbolBasisDerivationSpec, SourceObjectIdentityDerivationSpec),
    ):
        return "unique_parameter_symbol"
    return None


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
                    source_arg=(
                        names_by_runtime_input.get(
                            projection.source_arg,
                            projection.source_arg,
                        )
                        if projection.source_arg is not None
                        else None
                    ),
                )
                for projection in returned.object_role_projections
            ),
        )
        for returned in returns
    )


def _binding_semantic_roles(binding: Any | None) -> tuple[str, ...]:
    if isinstance(binding, ExactCallResultSourceSpec):
        return binding.semantic_roles
    if isinstance(binding, MethodInputBindingSpec):
        source = binding.source
        if isinstance(source, ExactCallResultSourceSpec):
            return source.semantic_roles
        if isinstance(source, EntityIdentitySourceSpec):
            return source.semantic_roles
        return ()
    return ()


def _binding_condition_kinds(binding: Any | None) -> tuple[str, ...]:
    if not isinstance(binding, MethodInputBindingSpec):
        return ()
    if isinstance(binding.source, ConditionSourceSpec):
        return binding.source.condition_kinds
    return ()


def _arg_requires_materialized_state(
    item: FunctionArgSpec,
) -> bool:
    """Distinguish local Function projections from full-state consumers.

    A Function object already carries its expression template. An unrestricted
    ``Expression`` input can therefore evaluate a local projection such as
    ``f(0)`` without solving every coefficient first. Full ``Parabola``
    consumers retain the declared latest-state requirement.
    """
    if (
        item.view_mode == "latest_state"
        and item.input_closure_policy == "any"
        and "Expression" in split_runtime_types(item.runtime_type)
    ):
        return False
    return item.view_mode == "latest_state"


def _contract_condition_arg(pattern: Any) -> FunctionalCapabilityArg:
    return FunctionalCapabilityArg(
        name=pattern.condition_kind,
        runtime_type=pattern.runtime_type,
        required=pattern.required,
        cardinality=pattern.cardinality,
        kind="condition_read",
        domain_type="Fact",
        input_view_mode="immutable_value",
        semantic_role=pattern.condition_kind,
        llm_mode=("explicit" if pattern.required else "optional"),
        accepted_item_types=(pattern.runtime_type,),
        accepted_condition_kinds=(pattern.condition_kind,),
        aggregation="none",
        runtime_input=None,
        description=pattern.description,
        consumption_mode="resolver_evidence",
    )


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
    input_bindings = _macro_method_input_bindings(
        spec,
        functions=functions,
        family_binding_rules=family_binding_rules,
    )
    capability = FunctionalCapability(
        capability_id=spec.macro_id,
        kind="macro",
        goal_types=spec.goal_types,
        title=recipe.title,
        use_when=use_when,
        do_not_use_when=do_not_use_when,
        args=tuple(
            replace(
                _macro_arg(item),
                consumption_mode=(
                    "runtime_input"
                    if item.name
                    in {source for source, _target in spec.adapter.input_aliases}
                    else "resolver_evidence"
                ),
            )
            for item in spec.args
            if item.kind != "auto"
        ),
        returns=tuple(_macro_return(item) for item in spec.returns),
        source=spec,
        is_pure=spec.is_pure,
        dependency_policy=spec.dependency_policy,
        context_resolvers=spec.context_resolvers,
        context_arg_bindings=_macro_context_arg_bindings(
            spec,
            input_bindings=input_bindings,
            method_specs=method_specs,
        ),
        input_bindings=tuple(input_bindings),
        input_closure_requirements=_input_closure_requirements(
            spec.input_closure_requirements
        ),
        identity_constraints=spec.identity_constraints,
    )
    _validate_identity_contract(capability)
    return capability


def _validate_identity_contract(capability: FunctionalCapability) -> None:
    public_args = {item.name: item for item in capability.args}
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
    known_returns = {item.name for item in capability.returns}
    for returned in capability.returns:
        for projection in returned.object_role_projections:
            if (
                projection.source_arg is not None
                and projection.source_arg not in known_args
            ):
                raise ValueError(
                    "planner_configuration_error: object-role projection "
                    "references unknown arg: "
                    f"{capability.capability_id}.{projection.source_arg}"
                )
            if (
                projection.source_return is not None
                and projection.source_return not in known_returns
            ):
                raise ValueError(
                    "planner_configuration_error: object-role projection "
                    "references unknown return: "
                    f"{capability.capability_id}."
                    f"{projection.source_return}"
                )
        if returned.runtime_type == "PathTransformation":
            moving_roles = tuple(
                projection
                for projection in returned.object_role_projections
                if projection.role == "moving_object"
            )
            if len(moving_roles) != 1:
                raise ValueError(
                    "planner_configuration_error: PathTransformation must "
                    "declare exactly one planner-selected moving object: "
                    f"{capability.capability_id}.{returned.name}"
                )
            moving_role = moving_roles[0]
            moving_arg = (
                public_args.get(moving_role.source_arg)
                if moving_role.source_arg is not None
                else None
            )
            if (
                moving_arg is None
                or moving_arg.binding_authority != "wire"
                or moving_role.source_object_role is not None
            ):
                raise ValueError(
                    "planner_configuration_error: PathTransformation moving "
                    "object must come directly from an explicit wire argument; "
                    "condition roles, vertex positions, resolver args, and "
                    "sibling returns cannot choose it: "
                    f"{capability.capability_id}.{returned.name}"
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
    input_bindings: Sequence[MethodInputBindingSpec],
    method_specs: MethodSpecRegistry,
) -> tuple[FunctionalContextArgBinding, ...]:
    declared_bindings: list[FunctionalContextArgBinding] = []
    wired_inputs = {
        tuple(target.rsplit(".", 1))
        for _source, target in spec.adapter.intermediate_wiring
        if "." in target
    }
    for internal_call in spec.internal_calls:
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
    strict_bindings_by_input = {
        item.input_name: item
        for item in input_bindings
        if isinstance(item, MethodInputBindingSpec)
    }
    return _merge_context_arg_bindings(
        (
            *declared_bindings,
            *(
                FunctionalContextArgBinding(
                    resolver_id=item.resolver_id,
                    semantic_role=item.semantic_role,
                    arg_name=item.arg_name,
                    consumption_mode="resolver_evidence",
                    input_binding=strict_bindings_by_input.get(item.arg_name),
                )
                for item in spec.context_role_bindings
            ),
        )
    )


def _macro_method_input_bindings(
    spec: MacroSpec,
    *,
    functions: FunctionSpecRegistry,
    family_binding_rules: Mapping[str, Any],
) -> tuple[MethodInputBindingSpec, ...]:
    """Collect one unambiguous binding declaration per Macro Method input."""

    result: dict[str, MethodInputBindingSpec] = {}
    for internal_call in spec.internal_calls:
        function = functions.get(internal_call.capability_id)
        adapter = function.adapter if function is not None else None
        if adapter is None:
            rule = family_binding_rules.get(internal_call.capability_id)
            if rule is not None:
                adapter = function_adapter_from_binding_rule(rule)
        if adapter is None:
            continue
        for binding in adapter.input_bindings:
            previous = result.setdefault(binding.input_name, binding)
            if previous != binding:
                raise ValueError(
                    "planner_configuration_error: Macro internal inputs "
                    f"disagree for {spec.macro_id}.{binding.input_name}"
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
    binding_authority: FunctionalArgBindingAuthority = "wire",
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
    runtime_condition_kinds = expand_condition_kinds(
        accepted_condition_kinds
        or (
            (condition_pattern.condition_kind,)
            if condition_pattern is not None
            else ()
        )
    )
    return FunctionalCapabilityArg(
        semantic_role,
        item.runtime_type,
        item.required if required_override is None else required_override,
        cardinality,
        item.kind,
        domain_type=_planner_arg_domain_type(
            item.domain_type,
            aggregation=aggregation,
        ),
        input_view_mode=_public_function_arg_view_mode(
            item.view_mode,
            accepted_item_types=accepted_item_types,
        ),
        allows_anonymous_result=(
            item.view_mode == "exact_result"
            or item.allows_anonymous_result
        ),
        allows_empty_collection=item.allows_empty_collection,
        semantic_role=semantic_role,
        llm_mode=(
            "explicit"
            if (item.required if required_override is None else required_override)
            else "optional"
        ),
        accepted_item_types=accepted_item_types,
        accepted_condition_kinds=runtime_condition_kinds,
        prompt_fact_types=(
            ("symbol_value",)
            if aggregation == "coefficients_by_symbol"
            else ()
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
        binding_authority=binding_authority,
        semantic_ref_role=(
            "object_identity"
            if item.kind == "point_ref"
            else item.semantic_ref_role
        ),
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
        domain_type=_planner_arg_domain_type(
            item.runtime_type,
            aggregation=aggregation,
        ),
        input_view_mode=_macro_arg_view_mode(item),
        allows_anonymous_result=(
            _macro_arg_view_mode(item) == "exact_result"
            or item.allows_anonymous_result
        ),
        semantic_role=semantic_role,
        llm_mode=("explicit" if item.required else "optional"),
        accepted_item_types=accepted_item_types,
        accepted_condition_kinds=(
            (item.condition_kind,) if item.condition_kind else ()
        ),
        aggregation=aggregation,
        runtime_input=item.name,
        deterministic_resolver=item.deterministic_resolver,
        description=item.description,
        provides_semantic_roles=item.provides_semantic_roles,
        semantic_ref_role=item.semantic_ref_role,
    )


def _macro_arg_view_mode(item: MacroArgSpec) -> MethodInputViewMode:
    """Project one public Macro entity into its deterministic internal view."""

    if item.kind in {"point_ref", "object_ref"}:
        return "identity"
    if item.kind == "condition_read":
        return "immutable_value"
    if item.runtime_type in {
        "PathTransformation",
        "StraighteningCandidate",
        "StraighteningCandidates",
        "PointCandidates",
        "PointList",
    }:
        return "exact_result"
    return "latest_state"


def _public_function_arg_view_mode(
    method_view_mode: MethodInputViewMode,
    *,
    accepted_item_types: Sequence[str],
) -> MethodInputViewMode:
    """Let a Function facade materialize named entities for exact Methods."""

    if method_view_mode != "exact_result":
        return method_view_mode
    state_bearing_entity_types = {
        "Expression",
        "Line",
        "Parabola",
        "ParameterValue",
        "Point",
    }
    if any(
        member in state_bearing_entity_types
        for runtime_type in accepted_item_types
        for member in split_runtime_types(runtime_type)
    ):
        return "latest_state"
    return method_view_mode


def _planner_arg_domain_type(
    runtime_type: str,
    *,
    aggregation: FunctionalAggregation,
) -> str:
    """Expose the domain item type for homogeneous collection arguments."""

    return planner_input_domain_type(
        runtime_type,
        aggregation=aggregation,
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
        name=item.name,
        runtime_type=item.runtime_type,
        required=item.required,
        cardinality="one",
        state_kind=item.state_kind,
        semantic_role=item.semantic_role or item.name,
        identity_policy=item.identity_policy,
        identity_arg=item.identity_arg,
        write_mode=write_mode,
        description=item.description,
        possible_forms=(
            item.scalar_result_form.possible_forms
            if item.scalar_result_form is not None
            else ()
        ),
        result_form_description=(
            item.scalar_result_form.description
            if item.scalar_result_form is not None
            else ""
        ),
        equivalent_to=None,
        provides_semantic_roles=item.provides_semantic_roles,
        evidence_tags=(),
        object_role_projections=item.object_role_projections,
        lineage_closures=item.lineage_closures,
        max_independent_free_parameters=(
            item.scalar_result_form.max_independent_free_parameters
            if item.scalar_result_form is not None
            else None
        ),
        return_binding=item.return_binding,
        result_form_ignored_input_args=(
            item.scalar_result_form.ignored_symbol_input_args
            if item.scalar_result_form is not None
            else ()
        ),
        free_symbol_return_names=(
            item.scalar_result_form.free_symbol_output_names
            if item.scalar_result_form is not None
            else ()
        ),
        output_target_selector=item.output_target_selector,
        materialization_policy=item.materialization_policy,
        naming=item.naming,
        predicate_publication=item.predicate_publication,
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
        name=item.name,
        runtime_type=item.runtime_type,
        required=item.required,
        cardinality=item.cardinality,
        state_kind=item.state_kind or state_kind_for_runtime_type(item.runtime_type),
        semantic_role=item.semantic_role or item.name,
        identity_policy=item.identity_policy,
        identity_arg=item.identity_arg,
        write_mode=item.write_mode,
        description=item.description,
        possible_forms=(
            item.scalar_result_form.possible_forms
            if item.scalar_result_form is not None
            else ()
        ),
        result_form_description=(
            item.scalar_result_form.description
            if item.scalar_result_form is not None
            else ""
        ),
        equivalent_to=item.equivalent_to,
        provides_semantic_roles=item.provides_semantic_roles,
        evidence_tags=tuple(item.goal_evidence_tags),
        object_role_projections=item.object_role_projections,
        lineage_closures=(),
        max_independent_free_parameters=(
            item.scalar_result_form.max_independent_free_parameters
            if item.scalar_result_form is not None
            else None
        ),
        return_binding=item.return_binding,
        result_form_ignored_input_args=(
            item.scalar_result_form.ignored_symbol_input_args
            if item.scalar_result_form is not None
            else ()
        ),
        free_symbol_return_names=(
            item.scalar_result_form.free_symbol_output_names
            if item.scalar_result_form is not None
            else ()
        ),
        naming=item.naming,
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
