"""Deterministic output type canonicalization for StepIntent produces."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.runtime.capability_contracts import (
    contract_required_write_runtime_types,
    effective_contract_by_id,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.output_type_inference import (
    produced_output_type_inference,
    semantic_name_from_handle,
    semantic_name_to_runtime_type,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProducedFact,
    StepIntentDraft,
    StepIntentNormalizationAction,
    StepIntentScope,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import build_executable_capabilities
from shuxueshuo_server.solver.output_type_policy import TRANSIENT_OUTPUT_TYPES


def canonicalize_produced_output_types(
    draft: StepIntentDraft,
    *,
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntentDraft, tuple[StepIntentNormalizationAction, ...]]:
    """Fill/overwrite produces.output_type when code can infer it uniquely.

    This is a raw-LLM unloading layer: output_type is accepted as a hint, but the
    canonical StepIntent used by resolver/runtime should prefer deterministic
    answer/fact/capability/semantic-name inference.
    """
    capabilities = {
        capability.capability_id: capability
        for capability in build_executable_capabilities(family_spec, method_specs)
    }
    contracts_by_id = effective_contract_by_id(family_spec, method_specs)
    actions: list[StepIntentNormalizationAction] = []
    scopes: list[StepIntentScope] = []
    for scope in draft.scopes:
        steps = []
        for step in scope.steps:
            produces: list[ProducedFact] = []
            for produced in step.produces:
                inferred = _authoritative_output_type(
                    produced,
                    recipe_hint=step.recipe_hint,
                    capabilities_by_id=capabilities,
                    handle_registry=handle_registry,
                )
                if (
                    inferred is None
                    or produced.output_type == inferred
                    or not _should_write_back_output_type(
                        produced,
                        inferred,
                        contract=contracts_by_id.get(step.recipe_hint or ""),
                    )
                ):
                    produces.append(produced)
                    continue
                produces.append(replace(produced, output_type=inferred))
                actions.append(
                    StepIntentNormalizationAction(
                        action="infer_output_type",
                        step_id=step.step_id,
                        handle=produced.handle,
                        reason=(
                            "authoritative_output_type:"
                            f"{produced.output_type or '<missing>'}->{inferred}"
                        ),
                    )
                )
            steps.append(replace(step, produces=tuple(produces)))
        scopes.append(replace(scope, steps=tuple(steps)))
    if not actions:
        return draft, ()
    return StepIntentDraft(scopes=tuple(scopes)), tuple(actions)


def _authoritative_output_type(
    produced: ProducedFact,
    *,
    recipe_hint: str | None,
    capabilities_by_id: dict[str, Any],
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """Infer output type using only deterministic/high-confidence sources."""
    registry_inference = produced_output_type_inference(produced, handle_registry)
    capability = capabilities_by_id.get(recipe_hint or "")
    capability_semantic_type = _capability_output_type_for_handle(
        produced,
        capability=capability,
    )
    if registry_inference.source in {"answer_value_type", "fact_type"}:
        if (
            registry_inference.output_type in {"Expression", "Equation"}
            and capability_semantic_type is not None
        ):
            return capability_semantic_type
        return registry_inference.output_type

    if capability is not None and len(capability.output_types) == 1:
        return capability.output_types[0]
    if capability_semantic_type is not None:
        return capability_semantic_type

    produced_without_hint = ProducedFact(
        handle=produced.handle,
        valid_scope=produced.valid_scope,
        description=produced.description,
        output_type=None,
    )
    semantic_inference = produced_output_type_inference(
        produced_without_hint,
        handle_registry,
    )
    if semantic_inference.source == "semantic_name":
        return semantic_inference.output_type

    if produced.output_type is not None:
        return produced.output_type
    return None


def _capability_output_type_for_handle(
    produced: ProducedFact,
    *,
    capability: Any | None,
) -> str | None:
    if capability is None:
        return None
    output_types = set(getattr(capability, "output_types", ()) or ())
    if not output_types:
        return None
    return semantic_name_to_runtime_type(
        semantic_name_from_handle(produced.handle),
        allowed_types=output_types,
    )


def _should_write_back_output_type(
    produced: ProducedFact,
    inferred: str,
    *,
    contract: Any | None,
) -> bool:
    if produced.output_type is not None:
        return True
    required_contract_write_types = set(contract_required_write_runtime_types(contract))
    if inferred in required_contract_write_types:
        return True
    # Migration fallback for methods without explicit contracts yet.
    return inferred not in TRANSIENT_OUTPUT_TYPES


__all__ = ["canonicalize_produced_output_types"]
