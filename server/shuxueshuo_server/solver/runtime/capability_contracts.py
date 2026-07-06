"""Helpers for capability contract lookup and projection.

Explicit contracts from Capability Packs are the authoritative declaration
layer. During migration, methods/recipes without an explicit contract get a
conservative projected contract from their existing specs so prompt gates and
debug context can remain useful without duplicating every method spec by hand.
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodSpec
from shuxueshuo_server.solver.family.models import (
    CapabilityContractSpec,
    SolverFamilySpec,
    StateSlotPattern,
    StepRecipeSpec,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.utils import unique_ordered


def explicit_contract_by_id(
    family_spec: SolverFamilySpec,
) -> dict[str, CapabilityContractSpec]:
    """Return explicit pack/family contracts keyed by capability_id."""
    return {
        contract.capability_id: contract
        for contract in family_spec.capability_contracts
    }


def effective_contract_by_id(
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry | None = None,
) -> dict[str, CapabilityContractSpec]:
    """Return explicit contracts plus migration projections for missing ids."""
    contracts = explicit_contract_by_id(family_spec)
    for recipe in family_spec.step_recipes:
        if recipe.recipe_id not in contracts:
            contracts[recipe.recipe_id] = project_recipe_contract(recipe)
    if method_specs is not None:
        for method_id in family_spec.method_ids:
            if method_id in contracts:
                continue
            try:
                method_spec = method_specs.require(method_id)
            except KeyError:
                continue
            contracts[method_id] = project_method_contract(method_spec)
    return contracts


def project_method_contract(method_spec: MethodSpec) -> CapabilityContractSpec:
    """Project a conservative executable contract from MethodSpec outputs."""
    slot_reads = tuple(
        pattern
        for pattern in (
            _input_slot_pattern(input_spec.type)
            for input_spec in method_spec.inputs.values()
        )
        if pattern is not None
    )
    if not method_spec.outputs:
        return CapabilityContractSpec(
            capability_id=method_spec.method_id,
            kind="method",
            execution_status="executable",
            source="projected",
            slot_reads=slot_reads,
            notes=("projected_no_outputs_declared",),
            complete=True,
        )
    return CapabilityContractSpec(
        capability_id=method_spec.method_id,
        kind="method",
        execution_status="executable",
        source="projected",
        slot_reads=slot_reads,
        slot_writes=tuple(
            _output_slot_pattern(output_type)
            for output_type in method_spec.outputs.values()
        ),
    )


def project_recipe_contract(recipe: StepRecipeSpec) -> CapabilityContractSpec:
    """Project a conservative executable contract from RecipeExecutionSpec."""
    output_types: list[str] = []
    execution = recipe.execution
    if execution is not None:
        for _output_key, output_type in execution.output_aliases:
            if output_type not in output_types:
                output_types.append(output_type)
    return CapabilityContractSpec(
        capability_id=recipe.recipe_id,
        kind="recipe",
        execution_status="executable",
        source="projected",
        slot_writes=tuple(_output_slot_pattern(output_type) for output_type in output_types),
    )


def contract_is_prompt_executable(contract: CapabilityContractSpec | None) -> bool:
    """Whether a direct capability can be exposed in the LLM method catalog."""
    if contract is None:
        return False
    return (
        contract.execution_status == "executable"
        and contract.exposes_to_llm
        and contract.is_complete
    )


def contract_write_runtime_types(
    contract: CapabilityContractSpec | None,
) -> tuple[str, ...]:
    """Return runtime types declared by contract writes."""
    if contract is None:
        return ()
    return unique_ordered(
        (
            *(slot.runtime_type for slot in contract.slot_writes),
            *(condition.runtime_type for condition in contract.condition_writes),
        )
    )


def contract_required_write_runtime_types(
    contract: CapabilityContractSpec | None,
) -> tuple[str, ...]:
    """Return runtime types required by contract writes."""
    if contract is None:
        return ()
    return unique_ordered(
        (
            *(slot.runtime_type for slot in contract.slot_writes if slot.required),
            *(
                condition.runtime_type
                for condition in contract.condition_writes
                if condition.required
            ),
        )
    )


def contract_payloads(
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry | None = None,
) -> tuple[dict[str, object], ...]:
    """Return JSON-serializable effective contract snapshots."""
    return tuple(
        contract.to_payload()
        for contract in effective_contract_by_id(family_spec, method_specs).values()
    )


def _input_slot_pattern(input_type: str) -> StateSlotPattern | None:
    """Project only semantic value reads, not invocation plumbing.

    ``Condition`` is represented by condition patterns, while ``Symbol`` and
    ``PointRef`` are binding/runtime references rather than StateSlot values.
    Keeping them out of projected slot reads prevents Context matching from
    treating invocation handles as semantic state dependencies.
    """
    runtime_types = _split_runtime_types(input_type)
    if "Condition" in runtime_types:
        return None
    if "Symbol" in runtime_types or "PointRef" in runtime_types:
        return None
    if not runtime_types:
        return None
    return StateSlotPattern(
        state_kind=_state_kind_for_runtime_type(runtime_types[0]),
        runtime_type="|".join(runtime_types),
        object_kind=_object_kind_for_runtime_type(runtime_types[0]),
        required=True,
    )


def _output_slot_pattern(output_type: str) -> StateSlotPattern:
    return StateSlotPattern(
        state_kind=_state_kind_for_runtime_type(output_type),
        runtime_type=output_type,
        object_kind=_object_kind_for_runtime_type(output_type),
    )


def _split_runtime_types(input_type: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in input_type.split("|") if part.strip())


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


__all__ = [
    "contract_is_prompt_executable",
    "contract_payloads",
    "contract_required_write_runtime_types",
    "contract_write_runtime_types",
    "effective_contract_by_id",
    "explicit_contract_by_id",
    "project_method_contract",
    "project_recipe_contract",
]
