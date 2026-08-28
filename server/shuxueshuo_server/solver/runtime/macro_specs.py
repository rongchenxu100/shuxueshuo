"""MacroSpec facade for recipe-level state transformers.

MacroSpec is the recipe-level companion to FunctionSpec.  It projects existing
StepRecipeSpec, RecipeExecutionSpec, and CapabilityContract metadata into a
typed state-transformer view while keeping the shared capability compiler as
the runtime execution boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from shuxueshuo_server.solver.contracts import (
    MacroExecutionMode,
    MacroSearchSpec,
    ScalarResultFormSpec,
)
from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CapabilityDependencyPolicy,
    CapabilityContractSpec,
    CapabilityContextRoleBindingSpec,
    CapabilityInputClosureRequirement,
    ConditionPattern,
    GoalEvidenceTag,
    PathTransformationConsumerSpec,
    FunctionalReturnBindingPolicy,
    FunctionalSemanticRefRole,
    RecipeExecutionSpec,
    RecipeInputDerivationSpec,
    RecipeOutputAliasSpec,
    StateIdentityPolicy,
    StateIdentityConstraintSpec,
    StateObjectRoleProjectionSpec,
    StateWriteMode,
    SolverFamilySpec,
    StateSlotPattern,
    StepRecipeSpec,
)
from shuxueshuo_server.solver.runtime.capability_contracts import (
    effective_contract_by_id,
)
from shuxueshuo_server.solver.runtime.functional_compile_contract import (
    compile_input_handles as _compile_input_handles,
    compile_return_outputs as _compile_return_outputs,
    compile_target_handle as _compile_target_handle,
)
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner_public_types import (
    planner_input_domain_type,
    planner_output_value_type,
    planner_prompt_text,
)
from shuxueshuo_server.solver.runtime.recipes._spec import RecipeSpec
from shuxueshuo_server.solver.runtime.recipes.registry import RecipeSpecRegistry
from shuxueshuo_server.solver.runtime.output_type_inference import (
    produced_semantic_role,
)
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.straightening_metadata import (
    canonical_straightening_endpoint_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProducedFact,
    FunctionalCompileStepView,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import (
    object_kind_for_runtime_type,
)
from shuxueshuo_server.solver.utils import unique_ordered

MacroArgKind = Literal["slot_read", "condition_read", "point_ref", "object_ref", "auto"]
MacroReturnKind = Literal["slot_write", "condition_write"]
MacroInternalCallKind = Literal["function", "method", "macro"]
MacroSpecSource = Literal["explicit_contract", "projected_contract", "recipe_execution"]


@dataclass(frozen=True)
class MacroArgSpec:
    """Typed macro argument visible to planner/debug layers."""

    name: str
    kind: MacroArgKind
    runtime_type: str
    required: bool = True
    cardinality: str = "one"
    state_kind: str | None = None
    condition_kind: str | None = None
    object_kind: str | None = None
    semantic_role: str | None = None
    description: str = ""
    provides_semantic_roles: tuple[str, ...] = ()
    semantic_ref_role: FunctionalSemanticRefRole = "value"
    allows_anonymous_result: bool = False
    deterministic_resolver: str | None = None

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
        if self.condition_kind is not None:
            payload["condition_kind"] = self.condition_kind
        if self.object_kind is not None:
            payload["object_kind"] = self.object_kind
        if self.semantic_role is not None:
            payload["semantic_role"] = self.semantic_role
        if self.description:
            payload["description"] = self.description
        if self.provides_semantic_roles:
            payload["provides_semantic_roles"] = list(
                self.provides_semantic_roles
            )
        if self.semantic_ref_role != "value":
            payload["semantic_ref_role"] = self.semantic_ref_role
        if self.allows_anonymous_result:
            payload["allows_anonymous_result"] = True
        if self.deterministic_resolver is not None:
            payload["deterministic_resolver"] = self.deterministic_resolver
        return payload


@dataclass(frozen=True)
class MacroReturnSpec:
    """Typed macro return visible to planner/debug layers."""

    name: str
    kind: MacroReturnKind
    runtime_type: str
    required: bool = True
    cardinality: str = "one"
    state_kind: str | None = None
    condition_kind: str | None = None
    object_kind: str | None = None
    output_key: str | None = None
    semantic_role: str | None = None
    identity_policy: StateIdentityPolicy = "value_only"
    identity_arg: str | None = None
    write_mode: StateWriteMode = "value"
    goal_evidence_tags: tuple[GoalEvidenceTag, ...] = ()
    description: str = ""
    scalar_result_form: ScalarResultFormSpec | None = None
    equivalent_to: str | None = None
    provides_semantic_roles: tuple[str, ...] = ()
    object_role_projections: tuple[StateObjectRoleProjectionSpec, ...] = ()
    return_binding: FunctionalReturnBindingPolicy = "auto"

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
        if self.condition_kind is not None:
            payload["condition_kind"] = self.condition_kind
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
        payload["goal_evidence_tags"] = list(self.goal_evidence_tags)
        if self.description:
            payload["description"] = self.description
        if self.scalar_result_form is not None:
            payload["scalar_result_form"] = self.scalar_result_form.to_payload()
        if self.equivalent_to is not None:
            payload["equivalent_to"] = self.equivalent_to
        if self.provides_semantic_roles:
            payload["provides_semantic_roles"] = list(
                self.provides_semantic_roles
            )
        if self.object_role_projections:
            payload["object_role_projections"] = [
                item.to_payload() for item in self.object_role_projections
            ]
        if self.return_binding != "auto":
            payload["return_binding"] = self.return_binding
        return payload


@dataclass(frozen=True)
class MacroInternalCallSpec:
    """Internal recipe call projected from RecipeExecutionSpec.method_sequence."""

    call_id: str
    capability_id: str
    call_kind: MacroInternalCallKind
    order: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "capability_id": self.capability_id,
            "call_kind": self.call_kind,
            "order": self.order,
        }


@dataclass(frozen=True)
class MacroAdapterSpec:
    """Adapter metadata projected from RecipeExecutionSpec."""

    adapter_id: str
    execution_strategy: str
    creates: tuple[str, ...] = ()
    input_aliases: tuple[tuple[str, str], ...] = ()
    input_derivations: tuple[RecipeInputDerivationSpec, ...] = ()
    strategy_input_targets: tuple[str, ...] = ()
    intermediate_wiring: tuple[tuple[str, str], ...] = ()
    output_aliases: tuple[RecipeOutputAliasSpec, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "execution_strategy": self.execution_strategy,
            "creates": list(self.creates),
            "input_aliases": [list(item) for item in self.input_aliases],
            "input_derivations": [
                item.to_payload() for item in self.input_derivations
            ],
            "strategy_input_targets": list(self.strategy_input_targets),
            "intermediate_wiring": [list(item) for item in self.intermediate_wiring],
            "output_aliases": [item.to_payload() for item in self.output_aliases],
        }


@dataclass(frozen=True)
class MacroSpec:
    """Typed recipe facade derived from recipe execution and contracts."""

    macro_id: str
    recipe_id: str
    goal_types: tuple[str, ...]
    args: tuple[MacroArgSpec, ...]
    returns: tuple[MacroReturnSpec, ...]
    internal_calls: tuple[MacroInternalCallSpec, ...]
    adapter: MacroAdapterSpec
    execution_mode: MacroExecutionMode
    search: MacroSearchSpec | None = None
    source: MacroSpecSource = "recipe_execution"
    exposes_to_llm: bool = True
    is_pure: bool = False
    dependency_policy: CapabilityDependencyPolicy = "explicit_args"
    context_resolvers: tuple[CapabilityContextResolver, ...] = ()
    context_role_bindings: tuple[CapabilityContextRoleBindingSpec, ...] = ()
    path_transformation_consumer: PathTransformationConsumerSpec | None = None
    input_closure_requirements: tuple[
        CapabilityInputClosureRequirement, ...
    ] = ()
    identity_constraints: tuple[StateIdentityConstraintSpec, ...] = ()
    repair_feedback_provider_id: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def code_owned_search_roles(self) -> frozenset[str]:
        """Roles resolved by Context/preparation and never authored by the LLM."""

        if self.execution_mode != "runtime_search" or self.search is None:
            return frozenset()
        searchable = frozenset(self.search.searchable_roles)
        return frozenset(
            item.semantic_role
            for item in self.context_role_bindings
            if item.semantic_role in searchable
        )

    def to_payload(self, *, include_adapter: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "macro_id": self.macro_id,
            "recipe_id": self.recipe_id,
            "goal_types": list(self.goal_types),
            "args": [item.to_payload() for item in self.args],
            "returns": [item.to_payload() for item in self.returns],
            "internal_calls": [item.to_payload() for item in self.internal_calls],
            "execution_mode": self.execution_mode,
            "search": self.search.to_payload() if self.search is not None else None,
            "source": self.source,
            "exposes_to_llm": self.exposes_to_llm,
            "is_pure": self.is_pure,
            "dependency_policy": self.dependency_policy,
            "context_role_bindings": [
                item.to_payload() for item in self.context_role_bindings
            ],
            "path_transformation_consumer": (
                self.path_transformation_consumer.to_payload()
                if self.path_transformation_consumer is not None
                else None
            ),
            "context_resolvers": list(self.context_resolvers),
            "input_closure_requirements": [
                item.to_payload() for item in self.input_closure_requirements
            ],
            "identity_constraints": [
                item.to_payload() for item in self.identity_constraints
            ],
            "repair_feedback_provider_id": self.repair_feedback_provider_id,
            "notes": list(self.notes),
        }
        if include_adapter:
            payload["adapter"] = self.adapter.to_payload()
        return payload

    def to_prompt_payload(self) -> dict[str, Any]:
        """Return LLM-facing catalog payload without compiler wiring details."""
        return {
            "macro_id": self.macro_id,
            "recipe_id": self.recipe_id,
            "goal_types": list(self.goal_types),
            "args": [
                _macro_prompt_arg(item)
                for item in self.args
                if (item.semantic_role or item.name)
                not in self.code_owned_search_roles
            ],
            "returns": [_macro_prompt_return(item) for item in self.returns],
            "notes": [_macro_prompt_text(item) for item in self.notes],
        }


class MacroSpecRegistry:
    """Effective MacroSpec lookup for a solver family."""

    def __init__(self, specs: Mapping[str, MacroSpec]) -> None:
        self.specs = dict(specs)

    @classmethod
    def from_family_spec(
        cls,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
    ) -> "MacroSpecRegistry":
        contracts = effective_contract_by_id(family_spec, method_specs)
        functions = FunctionSpecRegistry.from_family_spec(family_spec, method_specs)
        recipe_specs = RecipeSpecRegistry.load_from_code()
        specs: dict[str, MacroSpec] = {}
        for recipe in family_spec.step_recipes:
            execution = _execution_for_recipe(recipe)
            if execution is None:
                continue
            contract = contracts.get(recipe.recipe_id)
            if contract is not None and contract.execution_status != "executable":
                continue
            spec = macro_spec_from_recipe(
                recipe,
                execution=execution,
                contract=contract,
                function_specs=functions,
                recipe_spec=recipe_specs.get(recipe.recipe_id),
            )
            _validate_macro_lowering_contract(spec, method_specs)
            specs[recipe.recipe_id] = spec
        from shuxueshuo_server.solver.runtime.macro_preparation import (
            default_macro_implementation_registry,
        )

        implementations = default_macro_implementation_registry()
        for spec in specs.values():
            if spec.execution_mode == "runtime_search":
                if spec.search is None:
                    raise ValueError(
                        "planner.macro_contract_invalid: runtime_search Macro "
                        f"has no search spec: {spec.macro_id}"
                    )
                implementations.require(spec.macro_id, spec.search)
        return cls(specs)

    def get(self, macro_id: str) -> MacroSpec | None:
        return self.specs.get(macro_id)

    def require(self, macro_id: str) -> MacroSpec:
        try:
            return self.specs[macro_id]
        except KeyError as exc:
            raise KeyError(f"macro spec not found: {macro_id}") from exc

    def to_payload(self, *, include_adapter: bool = True) -> tuple[dict[str, Any], ...]:
        return tuple(
            spec.to_payload(include_adapter=include_adapter)
            for spec in self.specs.values()
        )

    def to_prompt_payload(self) -> dict[str, Any]:
        items = [
            spec.to_prompt_payload()
            for spec in self.specs.values()
            if _macro_is_prompt_executable(spec)
        ]
        return {
            "source": "macro_spec_facade",
            "items": items,
            "item_count": len(items),
        }


class MacroAdapterRegistry:
    """Validate recipe FunctionalCompileStepView against MacroSpec state-transformer metadata."""

    def __init__(
        self,
        specs: MacroSpecRegistry,
        *,
        handle_registry: CanonicalHandleRegistry | None = None,
    ) -> None:
        self.specs = specs
        self.handle_registry = handle_registry

    def validate(self, recipe_id: str, step: FunctionalCompileStepView) -> MacroSpec:
        spec = self.specs.get(recipe_id)
        if spec is None:
            raise StrategyDraftValidationError(f"macro.spec_missing: {recipe_id}")
        errors = [
            *_arg_errors(spec, step),
            *_return_errors(spec, step, self.handle_registry),
            *_contract_errors(spec),
        ]
        if errors:
            raise StrategyDraftValidationError("; ".join(errors))
        return spec

    def return_bindings(
        self,
        recipe_id: str,
        step: FunctionalCompileStepView,
    ) -> tuple[tuple[ProducedFact, MacroReturnSpec], ...]:
        """Return the unique typed macro return selected for each produced state."""
        spec = self.specs.require(recipe_id)
        bindings, errors = _match_macro_returns(
            spec,
            step,
            self.handle_registry,
        )
        if errors:
            raise StrategyDraftValidationError("; ".join(errors))
        return bindings


def macro_spec_from_recipe(
    recipe: StepRecipeSpec,
    *,
    execution: RecipeExecutionSpec,
    contract: CapabilityContractSpec | None,
    function_specs: FunctionSpecRegistry,
    recipe_spec: RecipeSpec | None = None,
) -> MacroSpec:
    """Project a StepRecipeSpec and RecipeExecutionSpec into a MacroSpec."""
    _validate_macro_execution_contract(execution)
    source: MacroSpecSource = "recipe_execution"
    notes: list[str] = []
    if contract is not None:
        source = (
            "explicit_contract"
            if contract.source == "explicit"
            else "projected_contract"
        )
        notes.extend(contract.notes)
    args = _args_from_contract(contract)
    returns = _returns_from_contract(contract, execution, function_specs)
    notes.extend(_contract_mismatch_notes(contract, execution))
    provider_ids = {
        item
        for item in (
            recipe.repair_feedback_provider_id,
            (
                recipe_spec.repair_feedback_provider_id
                if recipe_spec is not None
                else None
            ),
        )
        if item is not None
    }
    if len(provider_ids) > 1:
        raise ValueError(
            "planner_configuration_error: conflicting macro repair feedback "
            f"providers for {recipe.recipe_id}"
        )
    return MacroSpec(
        macro_id=recipe.recipe_id,
        recipe_id=recipe.recipe_id,
        goal_types=(recipe.goal_type,),
        args=args,
        returns=returns,
        internal_calls=_internal_calls(execution, function_specs),
        adapter=MacroAdapterSpec(
            adapter_id=recipe.recipe_id,
            execution_strategy=execution.execution_strategy,
            creates=execution.creates,
            input_aliases=execution.input_aliases,
            input_derivations=execution.input_derivations,
            strategy_input_targets=execution.strategy_input_targets,
            intermediate_wiring=execution.intermediate_wiring,
            output_aliases=execution.output_aliases,
        ),
        execution_mode=execution.execution_mode,
        search=execution.search,
        source=source,
        exposes_to_llm=(
            contract.exposes_to_llm if contract is not None else True
        ),
        is_pure=_macro_is_pure(execution, function_specs),
        dependency_policy=(
            contract.dependency_policy
            if contract is not None
            else "explicit_args"
        ),
        context_resolvers=(
            contract.context_resolvers if contract is not None else ()
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
        repair_feedback_provider_id=next(iter(provider_ids), None),
        notes=tuple(unique_ordered(notes)),
    )


_MACRO_CANDIDATE_BUILDERS = frozenset(
    {
        "visible_point_role_assignments",
        "path_role_assignments",
        "straightening_role_assignments",
        "equal_length_ray_role_assignments",
        "curve_role_assignments",
    }
)
_MACRO_VALIDATION_POLICIES = frozenset(
    {
        "method_checks_and_macro_postconditions",
        "path_equivalence_and_provenance",
        "minimum_expression_and_provenance",
        "distance_equivalence_and_provenance",
        "curve_membership_and_provenance",
    }
)


def _validate_macro_execution_contract(execution: RecipeExecutionSpec) -> None:
    search = execution.search
    if execution.execution_mode == "direct":
        if search is not None:
            raise ValueError(
                "planner_configuration_error: direct Macro must not declare search: "
                f"{execution.recipe_id}"
            )
        return
    if execution.execution_mode != "runtime_search" or search is None:
        raise ValueError(
            "planner_configuration_error: Macro execution mode/search mismatch: "
            f"{execution.recipe_id}"
        )
    if not search.searchable_roles or len(set(search.searchable_roles)) != len(
        search.searchable_roles
    ):
        raise ValueError(
            "planner_configuration_error: Macro searchable roles must be unique: "
            f"{execution.recipe_id}"
        )
    if search.candidate_builder_id not in _MACRO_CANDIDATE_BUILDERS:
        raise ValueError(
            "planner_configuration_error: unknown Macro candidate builder: "
            f"{execution.recipe_id}:{search.candidate_builder_id}"
        )
    if search.validation_policy_id not in _MACRO_VALIDATION_POLICIES:
        raise ValueError(
            "planner_configuration_error: unknown Macro validation policy: "
            f"{execution.recipe_id}:{search.validation_policy_id}"
        )
    if not 1 <= search.max_candidates <= 32:
        raise ValueError(
            "planner_configuration_error: Macro search budget must be within 1..32: "
            f"{execution.recipe_id}:{search.max_candidates}"
        )


def _macro_is_pure(
    execution: RecipeExecutionSpec,
    function_specs: FunctionSpecRegistry,
) -> bool:
    """Derive macro purity from its executable graph and declared effects."""
    if execution.creates:
        return False
    functions = tuple(
        function_specs.get(method_id) for method_id in execution.method_sequence
    )
    if not functions or any(item is None or not item.is_pure for item in functions):
        return False
    return not any(
        output.runtime_type == "Condition"
        for output in execution.output_aliases
    )


def macro_catalog_payload(
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry,
) -> dict[str, Any]:
    """Build prompt-facing MacroSpec catalog."""
    return MacroSpecRegistry.from_family_spec(
        family_spec,
        method_specs,
    ).to_prompt_payload()


def macro_spec_payloads(
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry,
) -> tuple[dict[str, Any], ...]:
    """Build debug-facing MacroSpec snapshots including adapter metadata."""
    return MacroSpecRegistry.from_family_spec(
        family_spec,
        method_specs,
    ).to_payload(include_adapter=True)


def macro_adapter_failure_events(events: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(event for event in events if getattr(event, "status", None) == "failure")


def assert_no_macro_adapter_failures(events: tuple[Any, ...]) -> None:
    failures = macro_adapter_failure_events(events)
    if failures:
        details = [
            f"{event.step_id}:{event.recipe_id}:{'|'.join(event.errors)}"
            for event in failures
        ]
        raise AssertionError("macro adapter failure occurred: " + "; ".join(details))


def _execution_for_recipe(recipe: StepRecipeSpec) -> RecipeExecutionSpec | None:
    return recipe.execution


def _args_from_contract(contract: CapabilityContractSpec | None) -> tuple[MacroArgSpec, ...]:
    if contract is None:
        return ()
    args: list[MacroArgSpec] = []
    for index, slot in enumerate(contract.slot_reads, start=1):
        args.append(_slot_arg(slot, index))
    for index, condition in enumerate(contract.condition_reads, start=1):
        args.append(_condition_arg(condition, index))
    return tuple(args)


def _slot_arg(slot: StateSlotPattern, index: int) -> MacroArgSpec:
    return MacroArgSpec(
        name=_pattern_name(slot.state_kind, slot.runtime_type, index),
        kind="slot_read",
        runtime_type=slot.runtime_type,
        required=slot.required,
        cardinality=slot.cardinality,
        state_kind=slot.state_kind,
        object_kind=slot.object_kind,
        semantic_role=slot.semantic_role,
        description=slot.description,
        provides_semantic_roles=slot.provides_semantic_roles,
        semantic_ref_role=slot.semantic_ref_role,
        allows_anonymous_result=slot.allows_anonymous_result,
    )


def _macro_prompt_arg(item: MacroArgSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": _macro_arg_public_name(item),
        "domain_type": planner_input_domain_type(item.runtime_type),
        "required": item.required,
        "cardinality": item.cardinality,
    }
    if item.description:
        payload["role"] = planner_prompt_text(item.description)
    return payload


def _macro_prompt_return(item: MacroReturnSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": item.name,
        "type": planner_output_value_type(item.runtime_type),
    }
    if not item.required:
        payload["required"] = False
    if item.cardinality != "one":
        payload["cardinality"] = item.cardinality
    if item.description:
        payload["desc"] = planner_prompt_text(item.description)
    return payload


def _macro_prompt_text(value: str) -> str:
    return planner_prompt_text(value)


def _condition_arg(condition: ConditionPattern, index: int) -> MacroArgSpec:
    return MacroArgSpec(
        name=_pattern_name(condition.condition_kind, condition.runtime_type, index),
        kind="condition_read",
        runtime_type=condition.runtime_type,
        required=condition.required,
        cardinality=condition.cardinality,
        condition_kind=condition.condition_kind,
        deterministic_resolver=condition.deterministic_resolver,
        description=condition.description,
    )


def _returns_from_contract(
    contract: CapabilityContractSpec | None,
    execution: RecipeExecutionSpec,
    function_specs: FunctionSpecRegistry,
) -> tuple[MacroReturnSpec, ...]:
    # RecipeExecutionSpec is the sole return-role source. The contract is used
    # below for consistency diagnostics, never to collapse execution outputs.
    return tuple(_returns_from_output_aliases(execution, function_specs))


def _returns_from_output_aliases(
    execution: RecipeExecutionSpec,
    function_specs: FunctionSpecRegistry,
) -> tuple[MacroReturnSpec, ...]:
    returns: list[MacroReturnSpec] = []
    for output in execution.output_aliases:
        returns.append(
            MacroReturnSpec(
                name=output.semantic_role,
                kind="slot_write",
                runtime_type=output.runtime_type,
                required=output.required,
                cardinality=output.cardinality,
                state_kind=output.state_kind,
                object_kind=object_kind_for_runtime_type(output.runtime_type),
                output_key=output.output_key,
                semantic_role=output.semantic_role,
                identity_policy=output.identity_policy,
                identity_arg=output.identity_arg,
                write_mode=output.write_mode,
                goal_evidence_tags=output.goal_evidence_tags,
                description=output.description,
                scalar_result_form=_macro_scalar_result_form(
                    output,
                    execution=execution,
                    function_specs=function_specs,
                ),
                equivalent_to=output.equivalent_to,
                provides_semantic_roles=output.provides_semantic_roles,
                object_role_projections=output.object_role_projections,
                return_binding=output.return_binding,
            )
        )
    return tuple(returns)


def _macro_scalar_result_form(
    output: RecipeOutputAliasSpec,
    *,
    execution: RecipeExecutionSpec,
    function_specs: FunctionSpecRegistry,
) -> ScalarResultFormSpec | None:
    """Project result-form metadata from the unique internal Function return."""
    if output.result_form is not None:
        return output.result_form
    explicit_method: str | None = None
    output_name = output.output_key
    if "." in output.output_key:
        explicit_method, output_name = output.output_key.rsplit(".", 1)
    method_ids = (
        (explicit_method,)
        if explicit_method is not None
        else execution.method_sequence
    )
    candidates: list[ScalarResultFormSpec] = []
    for method_id in method_ids:
        function = function_specs.get(method_id)
        if function is None:
            continue
        for result in function.returns:
            if result.name != output_name and result.output_key != output_name:
                continue
            if result.scalar_result_form is not None:
                candidates.append(result.scalar_result_form)
    unique = tuple(dict.fromkeys(candidates))
    if len(unique) > 1:
        raise ValueError(
            "planner_configuration_error: ambiguous macro scalar result form: "
            f"{execution.recipe_id}.{output.semantic_role}"
        )
    return unique[0] if unique else None


def _internal_calls(
    execution: RecipeExecutionSpec,
    function_specs: FunctionSpecRegistry,
) -> tuple[MacroInternalCallSpec, ...]:
    calls: list[MacroInternalCallSpec] = []
    for index, method_id in enumerate(execution.method_sequence):
        call_kind: MacroInternalCallKind = (
            "function" if function_specs.get(method_id) is not None else "method"
        )
        calls.append(
            MacroInternalCallSpec(
                call_id=f"{execution.recipe_id}.{index + 1}.{method_id}",
                capability_id=method_id,
                call_kind=call_kind,
                order=index,
            )
        )
    return tuple(calls)


def _contract_mismatch_notes(
    contract: CapabilityContractSpec | None,
    execution: RecipeExecutionSpec,
) -> tuple[str, ...]:
    if contract is None:
        return ()
    output_types = {output.runtime_type for output in execution.output_aliases}
    notes: list[str] = []
    for slot in contract.slot_writes:
        if _runtime_type_covered(slot.runtime_type, output_types):
            continue
        marker = "required" if slot.required else "optional"
        notes.append(f"macro_contract_mismatch:{marker}:slot_write:{slot.runtime_type}")
    for condition in contract.condition_writes:
        if _runtime_type_covered(condition.runtime_type, output_types):
            continue
        marker = "required" if condition.required else "optional"
        notes.append(
            f"macro_contract_mismatch:{marker}:condition_write:{condition.runtime_type}"
        )
    return tuple(notes)


def _arg_errors(spec: MacroSpec, step: FunctionalCompileStepView) -> tuple[str, ...]:
    required_reads = [
        arg for arg in spec.args
        if arg.required and arg.kind in {"slot_read", "condition_read"}
    ]
    if required_reads and not _compile_input_handles(step):
        return (
            "macro.arg_missing: "
            f"recipe={spec.recipe_id}, required_args="
            f"{[arg.name for arg in required_reads]}",
        )
    return ()


def _return_errors(
    spec: MacroSpec,
    step: FunctionalCompileStepView,
    handle_registry: CanonicalHandleRegistry | None = None,
) -> tuple[str, ...]:
    _bindings, errors = _match_macro_returns(spec, step, handle_registry)
    return errors


def _match_macro_returns(
    spec: MacroSpec,
    step: FunctionalCompileStepView,
    handle_registry: CanonicalHandleRegistry | None = None,
) -> tuple[
    tuple[tuple[ProducedFact, MacroReturnSpec], ...],
    tuple[str, ...],
]:
    errors: list[str] = []
    bindings: list[tuple[ProducedFact, MacroReturnSpec]] = []
    matched: dict[str, int] = {}
    matched_outputs: dict[str, list[ProducedFact]] = {}
    for produced in _compile_return_outputs(step):
        produced_type = produced.output_type or (
            handle_registry.answer_value_types.get(produced.handle)
            if handle_registry is not None and produced.handle.startswith("answer:")
            else None
        )
        compatible = (
            list(spec.returns)
            if produced_type is None
            else [
                item
                for item in spec.returns
                if _runtime_type_covered(item.runtime_type, {produced_type})
            ]
        )
        role_matches = [
            item for item in compatible
            if _semantic_role_matches(produced, item.semantic_role)
        ]
        candidates = role_matches or _identity_compatible_returns(
            compatible,
            produced_handle=produced.handle,
            step=step,
        )
        if not candidates:
            same_role = [
                item for item in spec.returns
                if _semantic_role_matches(produced, item.semantic_role)
            ]
            code = "macro.return_type_mismatch" if same_role else "macro.return_unresolved"
            errors.append(
                f"{code}: recipe={spec.recipe_id}, "
                f"handle={produced.handle}, runtime_type={produced_type}"
            )
            continue
        if len(candidates) > 1:
            required = [item for item in candidates if item.required]
            if len(required) == 1:
                candidates = required
            else:
                errors.append(
                    "macro.return_ambiguous: "
                    f"recipe={spec.recipe_id}, handle={produced.handle}, "
                    f"returns={[item.name for item in candidates]}"
                )
                continue
        selected = candidates[0]
        bindings.append((produced, selected))
        matched[selected.name] = matched.get(selected.name, 0) + 1
        selected_outputs = matched_outputs.setdefault(selected.name, [])
        selected_outputs.append(produced)
        if (
            matched[selected.name] > 1
            and selected.cardinality != "many"
            and not _is_answer_state_alias_group(selected_outputs)
        ):
            errors.append(
                "macro.return_ambiguous: "
                f"recipe={spec.recipe_id}, return={selected.name}, "
                "multiple produced states mapped to a single return"
            )
    for item in spec.returns:
        if item.required and not matched.get(item.name):
            errors.append(
                "macro.return_unresolved: "
                f"recipe={spec.recipe_id}, return={item.name}, "
                f"runtime_type={item.runtime_type}"
            )
    return tuple(bindings), tuple(errors)


def _is_answer_state_alias_group(outputs: list[ProducedFact]) -> bool:
    """One answer plus one fact may name the same projected runtime return."""

    return (
        len(outputs) == 2
        and sum(item.handle.startswith("answer:") for item in outputs) == 1
        and sum(item.handle.startswith("fact:") for item in outputs) == 1
        and len({item.output_type for item in outputs}) == 1
    )


def _identity_compatible_returns(
    candidates: list[MacroReturnSpec],
    *,
    produced_handle: str,
    step: FunctionalCompileStepView,
) -> list[MacroReturnSpec]:
    if not candidates:
        return []
    if all(item.runtime_type != "Point" for item in candidates):
        return candidates
    result: list[MacroReturnSpec] = []
    for item in candidates:
        if item.identity_policy == "target_object" and produced_handle == _compile_target_handle(step):
            result.append(item)
        elif item.identity_policy == "preserve_input_object" and len(candidates) == 1:
            result.append(item)
        # derived_role Point outputs intentionally require an explicit role
        # match; type equality alone cannot turn an endpoint into a target point.
    return result


def _semantic_role_matches(
    produced: ProducedFact,
    semantic_role: str | None,
) -> bool:
    if not semantic_role:
        return False
    name = produced_semantic_role(produced).lower()
    role = semantic_role.lower()
    canonical_name = canonical_straightening_endpoint_name(name)
    canonical_role = canonical_straightening_endpoint_name(role)
    if canonical_name is not None or canonical_role is not None:
        return canonical_name == canonical_role
    if " return " in produced.description:
        return name == role
    return name == role or name.endswith(f"_{role}") or role.endswith(f"_{name}")


def _contract_errors(spec: MacroSpec) -> tuple[str, ...]:
    return tuple(
        f"macro.contract_mismatch: recipe={spec.recipe_id}, note={note}"
        for note in spec.notes
        if note.startswith("macro_contract_mismatch:required:")
    )


def _validate_macro_lowering_contract(
    spec: MacroSpec,
    method_specs: MethodSpecRegistry,
) -> None:
    """Audit every public-to-internal Macro edge before it reaches runtime."""

    public_args = {_macro_arg_public_name(item): item for item in spec.args}
    internal_methods = {
        item.capability_id
        for item in spec.internal_calls
    }
    errors: list[str] = []

    def target_input(target: str) -> tuple[str, str, Any] | None:
        method_id, separator, input_name = target.partition(".")
        if not separator or not method_id or not input_name:
            errors.append(f"invalid target {target!r}")
            return None
        if method_id not in internal_methods:
            errors.append(f"target method is outside sequence: {target}")
            return None
        method = method_specs.specs.get(method_id)
        if method is None:
            errors.append(f"target method is unknown: {method_id}")
            return None
        input_spec = method.inputs.get(input_name)
        if input_spec is None:
            errors.append(f"target input is unknown: {target}")
            return None
        return method_id, input_name, input_spec

    target_sources: dict[str, str] = {}
    for source_arg, target in spec.adapter.input_aliases:
        source = public_args.get(source_arg)
        if source is None:
            errors.append(f"input alias source is not public: {source_arg}")
            continue
        resolved = target_input(target)
        if resolved is None:
            continue
        _method_id, _input_name, input_spec = resolved
        if not runtime_type_compatible(input_spec.type, source.runtime_type):
            errors.append(
                "input alias type mismatch: "
                f"{source_arg}:{source.runtime_type}->{target}:{input_spec.type}"
            )
        previous = target_sources.setdefault(target, source_arg)
        if previous != source_arg:
            errors.append(
                f"input target has multiple public sources: {target}"
            )

    for derivation in spec.adapter.input_derivations:
        source = public_args.get(derivation.source_arg)
        if source is None:
            errors.append(
                "input derivation source is not public: "
                f"{derivation.source_arg}"
            )
            continue
        resolved = target_input(derivation.target)
        if resolved is None:
            continue
        _method_id, _input_name, input_spec = resolved
        if derivation.kind != "source_object_identity":
            errors.append(
                f"unsupported input derivation: {derivation.kind}"
            )
            continue
        source_kind = object_kind_for_runtime_type(source.runtime_type)
        target_kinds = {
            object_kind_for_runtime_type(runtime_type)
            for runtime_type in split_runtime_types(input_spec.type)
        }
        if source_kind is None or source_kind not in target_kinds:
            errors.append(
                "input derivation object identity mismatch: "
                f"{derivation.source_arg}:{source.runtime_type}->"
                f"{derivation.target}:{input_spec.type}"
            )
        previous = target_sources.setdefault(
            derivation.target,
            derivation.source_arg,
        )
        if previous != derivation.source_arg:
            errors.append(
                "derived input target has multiple public sources: "
                f"{derivation.target}"
            )

    for target in spec.adapter.strategy_input_targets:
        if target_input(target) is None:
            continue
        previous = target_sources.setdefault(target, "<strategy>")
        if previous != "<strategy>":
            errors.append(
                "strategy input duplicates another lowering edge: "
                f"{target}"
            )

    for source, target in spec.adapter.intermediate_wiring:
        source_method, separator, output_name = source.partition(".")
        if not separator or source_method not in internal_methods:
            errors.append(f"invalid intermediate source: {source}")
            continue
        source_spec = method_specs.specs.get(source_method)
        output_type = (
            source_spec.outputs.get(output_name)
            if source_spec is not None
            else None
        )
        resolved = target_input(target)
        if output_type is None:
            errors.append(f"intermediate output is unknown: {source}")
        elif resolved is not None and not runtime_type_compatible(
            resolved[2].type,
            output_type,
        ):
            errors.append(
                "intermediate type mismatch: "
                f"{source}:{output_type}->{target}:{resolved[2].type}"
            )
        elif resolved is not None:
            previous = target_sources.setdefault(target, source)
            if previous != source:
                errors.append(
                    "intermediate input duplicates another lowering edge: "
                    f"{target}"
                )

    for method_id in sorted(internal_methods):
        method = method_specs.specs.get(method_id)
        if method is None:
            errors.append(f"internal method is unknown: {method_id}")
            continue
        for input_name, input_spec in method.inputs.items():
            target = f"{method_id}.{input_name}"
            if input_spec.required and target not in target_sources:
                errors.append(
                    "required internal input has no lowering edge: "
                    f"{target}"
                )

    for output in spec.adapter.output_aliases:
        method_id, separator, output_name = output.output_key.partition(".")
        method = method_specs.specs.get(method_id)
        actual_type = method.outputs.get(output_name) if method is not None else None
        if not separator or method_id not in internal_methods or actual_type is None:
            errors.append(f"output alias target is unknown: {output.output_key}")
        elif not runtime_type_compatible(output.runtime_type, actual_type):
            errors.append(
                "output alias type mismatch: "
                f"{output.output_key}:{actual_type}->{output.runtime_type}"
            )
        elif method is not None:
            activation = method.output_activation.get(output_name)
            if activation is not None and activation.kind == "requires_inputs":
                missing_activation_inputs = tuple(
                    input_name
                    for input_name in activation.required_inputs
                    if f"{method_id}.{input_name}" not in target_sources
                )
                if missing_activation_inputs:
                    errors.append(
                        "optional output has no public activation lowering: "
                        f"{output.output_key} requires "
                        f"{missing_activation_inputs}"
                    )

    if errors:
        raise ValueError(
            "planner_configuration_error: macro lowering contract invalid: "
            f"macro={spec.macro_id}; " + "; ".join(errors)
        )


def _macro_arg_public_name(item: MacroArgSpec) -> str:
    if item.semantic_role:
        return item.semantic_role
    if item.condition_kind:
        return item.condition_kind
    if item.state_kind:
        return item.state_kind
    return item.name


def _macro_is_prompt_executable(spec: MacroSpec) -> bool:
    return spec.exposes_to_llm and bool(spec.returns) and not any(
        note.startswith("macro_contract_mismatch:required:")
        for note in spec.notes
    )


def _first_output_alias_for_type(
    runtime_type: str,
    output_aliases: list[RecipeOutputAliasSpec],
) -> str | None:
    for output in output_aliases:
        if output.runtime_type == runtime_type:
            return output.output_key
    return None


def _runtime_type_covered(runtime_type: str, candidates: set[str | None]) -> bool:
    parts = set(split_runtime_types(runtime_type))
    return bool(parts & {candidate for candidate in candidates if candidate})


def _pattern_name(kind: str, runtime_type: str, index: int) -> str:
    base = f"{kind}_{runtime_type}".replace("|", "_or_")
    return base if index == 1 else f"{base}_{index}"
