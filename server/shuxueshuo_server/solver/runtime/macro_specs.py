"""MacroSpec facade for recipe-level state transformers.

MacroSpec is the recipe-level companion to FunctionSpec.  It projects existing
StepRecipeSpec, RecipeExecutionSpec, and CapabilityContract metadata into a
typed state-transformer view while keeping the existing RecipeTrialExecutor as
the runtime execution boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from shuxueshuo_server.solver.contracts import ScalarResultFormSpec
from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CapabilityDependencyPolicy,
    CapabilityContractSpec,
    ConditionPattern,
    GoalEvidenceTag,
    RecipeExecutionSpec,
    RecipeOutputAliasSpec,
    StateIdentityPolicy,
    StateWriteMode,
    SolverFamilySpec,
    StateSlotPattern,
    StepRecipeSpec,
)
from shuxueshuo_server.solver.runtime.capability_contracts import (
    effective_contract_by_id,
)
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.output_type_inference import (
    produced_semantic_role,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProducedFact,
    StepIntent,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import (
    object_kind_for_runtime_type,
    split_runtime_types,
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
    intermediate_wiring: tuple[tuple[str, str], ...] = ()
    output_aliases: tuple[RecipeOutputAliasSpec, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "execution_strategy": self.execution_strategy,
            "creates": list(self.creates),
            "input_aliases": [list(item) for item in self.input_aliases],
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
    source: MacroSpecSource = "recipe_execution"
    is_pure: bool = False
    dependency_policy: CapabilityDependencyPolicy = "explicit_args"
    context_resolvers: tuple[CapabilityContextResolver, ...] = ()
    notes: tuple[str, ...] = ()

    def to_payload(self, *, include_adapter: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "macro_id": self.macro_id,
            "recipe_id": self.recipe_id,
            "goal_types": list(self.goal_types),
            "args": [item.to_payload() for item in self.args],
            "returns": [item.to_payload() for item in self.returns],
            "internal_calls": [item.to_payload() for item in self.internal_calls],
            "source": self.source,
            "is_pure": self.is_pure,
            "dependency_policy": self.dependency_policy,
            "context_resolvers": list(self.context_resolvers),
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
            "args": [item.to_payload() for item in self.args],
            "returns": [item.to_payload() for item in self.returns],
            "notes": list(self.notes),
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
        specs: dict[str, MacroSpec] = {}
        for recipe in family_spec.step_recipes:
            execution = _execution_for_recipe(recipe)
            if execution is None:
                continue
            contract = contracts.get(recipe.recipe_id)
            if contract is not None and contract.execution_status != "executable":
                continue
            specs[recipe.recipe_id] = macro_spec_from_recipe(
                recipe,
                execution=execution,
                contract=contract,
                function_specs=functions,
            )
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
    """Validate recipe StepIntent against MacroSpec state-transformer metadata."""

    def __init__(
        self,
        specs: MacroSpecRegistry,
        *,
        handle_registry: CanonicalHandleRegistry | None = None,
    ) -> None:
        self.specs = specs
        self.handle_registry = handle_registry

    def validate(self, recipe_id: str, step: StepIntent) -> MacroSpec:
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
        step: StepIntent,
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
) -> MacroSpec:
    """Project a StepRecipeSpec and RecipeExecutionSpec into a MacroSpec."""
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
            intermediate_wiring=execution.intermediate_wiring,
            output_aliases=execution.output_aliases,
        ),
        source=source,
        is_pure=_macro_is_pure(execution, function_specs),
        dependency_policy=(
            contract.dependency_policy
            if contract is not None
            else "explicit_args"
        ),
        context_resolvers=(
            contract.context_resolvers if contract is not None else ()
        ),
        notes=tuple(unique_ordered(notes)),
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
    if recipe.execution is not None:
        return recipe.execution
    if len(recipe.method_ids) == 1:
        return RecipeExecutionSpec(
            recipe_id=recipe.recipe_id,
            method_sequence=recipe.method_ids,
            execution_strategy="single_method",
        )
    return None


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
    )


def _condition_arg(condition: ConditionPattern, index: int) -> MacroArgSpec:
    return MacroArgSpec(
        name=_pattern_name(condition.condition_kind, condition.runtime_type, index),
        kind="condition_read",
        runtime_type=condition.runtime_type,
        required=condition.required,
        cardinality=condition.cardinality,
        condition_kind=condition.condition_kind,
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


def _arg_errors(spec: MacroSpec, step: StepIntent) -> tuple[str, ...]:
    required_reads = [
        arg for arg in spec.args
        if arg.required and arg.kind in {"slot_read", "condition_read"}
    ]
    if required_reads and not step.reads:
        return (
            "macro.arg_missing: "
            f"recipe={spec.recipe_id}, required_args="
            f"{[arg.name for arg in required_reads]}",
        )
    return ()


def _return_errors(
    spec: MacroSpec,
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry | None = None,
) -> tuple[str, ...]:
    _bindings, errors = _match_macro_returns(spec, step, handle_registry)
    return errors


def _match_macro_returns(
    spec: MacroSpec,
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry | None = None,
) -> tuple[
    tuple[tuple[ProducedFact, MacroReturnSpec], ...],
    tuple[str, ...],
]:
    errors: list[str] = []
    bindings: list[tuple[ProducedFact, MacroReturnSpec]] = []
    matched: dict[str, int] = {}
    for produced in step.produces:
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
        if matched[selected.name] > 1 and selected.cardinality != "many":
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


def _identity_compatible_returns(
    candidates: list[MacroReturnSpec],
    *,
    produced_handle: str,
    step: StepIntent,
) -> list[MacroReturnSpec]:
    if not candidates:
        return []
    if all(item.runtime_type != "Point" for item in candidates):
        return candidates
    result: list[MacroReturnSpec] = []
    for item in candidates:
        if item.identity_policy == "target_object" and produced_handle == step.target:
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
    if " return " in produced.description:
        return name == role
    return name == role or name.endswith(f"_{role}") or role.endswith(f"_{name}")


def _contract_errors(spec: MacroSpec) -> tuple[str, ...]:
    return tuple(
        f"macro.contract_mismatch: recipe={spec.recipe_id}, note={note}"
        for note in spec.notes
        if note.startswith("macro_contract_mismatch:required:")
    )


def _macro_is_prompt_executable(spec: MacroSpec) -> bool:
    return bool(spec.returns) and not any(
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
