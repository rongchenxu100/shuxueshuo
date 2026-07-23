"""Deterministic elaboration and Context semantic views for FunctionalPlan."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.family.models import (
    CapabilityStateClosurePolicy,
)

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_graph import (
    rewrite_call_result_aliases as _rewrite_call_result_aliases,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCapability,
    FunctionalCall,
    FunctionalPlan,
    FunctionalPlanIssue,
    FunctionalScope,
    SemanticRef,
    _issue,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    StateSemanticLineage,
    state_semantic_lineage,
)
from shuxueshuo_server.solver.runtime.object_dependencies import (
    expand_object_dependencies as _expand_object_dependencies,
    structured_object_refs as _structured_object_refs,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    normalize_runtime_type,
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.symbol_dependencies import (
    structured_free_symbol_refs as _structured_free_symbol_refs,
    symbol_handles_by_name as _symbol_handles_by_name,
)
from shuxueshuo_server.solver.state_semantics import is_object_handle


@dataclass(frozen=True)
class FunctionalDeterministicRepair:
    call_id: str
    action: str
    from_value: str
    to_value: str

    def to_payload(self) -> dict[str, str]:
        return {
            "call_id": self.call_id,
            "action": self.action,
            "from": self.from_value,
            "to": self.to_value,
        }


@dataclass(frozen=True)
class FunctionalSemanticView:
    ref: str
    kind: str
    handle: str
    runtime_type: str
    valid_scope: str
    object_ref: str | None = None
    state_slot_id: str | None = None
    condition_id: str | None = None
    condition_kind: str | None = None
    object_roles: tuple[tuple[str, tuple[str, ...]], ...] = ()
    dependency_object_refs: tuple[str, ...] = ()
    free_symbol_refs: tuple[str, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()
    provides_semantic_roles: tuple[str, ...] = ()
    lineage: StateSemanticLineage = StateSemanticLineage()

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "kind": self.kind,
            "value_type": self.runtime_type,
        }


@dataclass(frozen=True)
class FunctionalStateMaterialization:
    """Proof that an object template can become one typed runtime state."""

    status: str
    source: FunctionalSemanticView | None = None
    target_runtime_type: str | None = None
    supporting_handles: tuple[str, ...] = ()
    free_symbol_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class FunctionalPlanElaborationResult:
    raw_plan: FunctionalPlan
    plan: FunctionalPlan
    issues: tuple[FunctionalPlanIssue, ...] = ()
    deterministic_repairs: tuple[FunctionalDeterministicRepair, ...] = ()
    auto_args: dict[str, tuple[str, ...]] | None = None
    resolved_args: dict[str, dict[str, tuple[dict[str, Any], ...]]] | None = None
    aggregations: dict[str, dict[str, str]] | None = None
    call_aliases: dict[str, str] | None = None

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "plan": self.plan.to_payload(),
            "issues": [item.to_payload() for item in self.issues],
            "deterministic_repairs": [
                item.to_payload() for item in self.deterministic_repairs
            ],
            "auto_args": {
                call_id: list(names)
                for call_id, names in (self.auto_args or {}).items()
            },
            "resolved_args": {
                call_id: {
                    name: list(values) for name, values in args.items()
                }
                for call_id, args in (self.resolved_args or {}).items()
            },
            "aggregations": self.aggregations or {},
            "call_aliases": dict(self.call_aliases or {}),
        }


def _object_state_free_symbol_refs(
    object_refs: Sequence[str],
    *,
    slots_by_object: Mapping[str, Sequence[Any]],
) -> tuple[str, ...]:
    """Return unresolved symbols carried by referenced object states.

    Structural facts often name geometry objects rather than repeating their
    coordinates. Their symbol flow therefore comes from those objects' current
    StateSlots. Bare Symbol subjects are intentionally excluded: a constraint
    that mentions a coefficient is evidence about it, not proof that every
    result consuming the constraint remains parameterized by that coefficient.
    """
    return tuple(
        dict.fromkeys(
            symbol_ref
            for object_ref in object_refs
            if not object_ref.startswith("symbol:")
            for slot in slots_by_object.get(object_ref, ())
            for symbol_ref in slot.free_symbol_refs
        )
    )


class FunctionalPlanElaborator:
    """Canonicalize only contract-declared FunctionalPlan wire details."""

    def elaborate(
        self,
        plan: FunctionalPlan,
        *,
        catalog: FunctionalCapabilityCatalog,
        semantic_index: FunctionalSemanticIndex | None = None,
    ) -> FunctionalPlanElaborationResult:
        issues: list[FunctionalPlanIssue] = []
        repairs: list[FunctionalDeterministicRepair] = []
        auto_args: dict[str, tuple[str, ...]] = {}
        resolved_args: dict[
            str, dict[str, tuple[dict[str, Any], ...]]
        ] = {}
        aggregations: dict[str, dict[str, str]] = {}
        scopes: list[FunctionalScope] = []
        for scope in plan.scopes:
            calls: list[FunctionalCall] = []
            for call in scope.calls:
                capability = catalog.get(call.capability_id)
                if capability is None:
                    calls.append(call)
                    continue
                call = _drop_fixed_form_return_expectations(
                    call,
                    capability=capability,
                    repairs=repairs,
                )
                arg_specs = {item.name: item for item in capability.args}
                alias_to_name = {
                    alias: item.name
                    for item in capability.args
                    for alias in (
                        *item.aliases,
                        *(
                            (item.runtime_input,)
                            if item.runtime_input and item.runtime_input != item.name
                            else ()
                        ),
                    )
                }
                normalized_args: dict[str, tuple[Any, ...]] = {}
                for raw_name, values in call.args.items():
                    name = alias_to_name.get(raw_name, raw_name)
                    if name != raw_name:
                        repairs.append(
                            FunctionalDeterministicRepair(
                                call.call_id,
                                "normalize_arg_role",
                                raw_name,
                                name,
                            )
                        )
                    if name in normalized_args:
                        issues.append(
                            _issue(
                                "functional_elaboration",
                                "functional.arg_alias_collision",
                                f"multiple inputs map to semantic arg {name}",
                                call_id=call.call_id,
                                scope_id=scope.scope_id,
                            )
                        )
                        continue
                    normalized_args[name] = values
                if semantic_index is not None:
                    normalized_args = _reclassify_unique_semantic_args(
                        normalized_args,
                        arg_specs=arg_specs,
                        semantic_index=semantic_index,
                        scope_id=scope.scope_id,
                        call_id=call.call_id,
                        repairs=repairs,
                    )
                    normalized_args = _drop_redundant_incompatible_optional_args(
                        normalized_args,
                        arg_specs=arg_specs,
                        semantic_index=semantic_index,
                        scope_id=scope.scope_id,
                        call_id=call.call_id,
                        repairs=repairs,
                    )
                for name, values in normalized_args.items():
                    spec = arg_specs.get(name)
                    if spec is None:
                        continue
                    if spec.cardinality != "many" and len(values) > 1:
                        issues.append(
                            _issue(
                                "functional_elaboration",
                                "functional.arg_cardinality",
                                f"argument {name} accepts one semantic value",
                                call_id=call.call_id,
                                scope_id=scope.scope_id,
                                details={
                                    "arg": name,
                                    "accepted_item_types": list(
                                        spec.accepted_item_types
                                    ),
                                },
                            )
                        )
                auto_args[call.call_id] = tuple(
                    item.name for item in capability.auto_args
                )
                resolved_args[call.call_id] = {
                    name: tuple(value.to_payload() for value in values)
                    for name, values in normalized_args.items()
                }
                aggregations[call.call_id] = {
                    name: spec.aggregation
                    for name, spec in arg_specs.items()
                    if spec.aggregation != "none" and normalized_args.get(name)
                }
                calls.append(replace(call, args=normalized_args))
            scopes.append(replace(scope, calls=tuple(calls)))
        elaborated_plan = replace(plan, scopes=tuple(scopes))
        elaborated_plan, call_aliases = _merge_equivalent_object_calls(
            elaborated_plan,
            catalog=catalog,
            repairs=repairs,
            issues=issues,
            semantic_index=semantic_index,
        )
        final_call_ids = {call.call_id for call in elaborated_plan.calls}
        return FunctionalPlanElaborationResult(
            raw_plan=plan,
            plan=elaborated_plan,
            issues=tuple(issues),
            deterministic_repairs=tuple(repairs),
            auto_args={
                key: value for key, value in auto_args.items() if key in final_call_ids
            },
            resolved_args={
                key: value
                for key, value in resolved_args.items()
                if key in final_call_ids
            },
            aggregations={
                key: value
                for key, value in aggregations.items()
                if key in final_call_ids
            },
            call_aliases=call_aliases,
        )


def _drop_fixed_form_return_expectations(
    call: FunctionalCall,
    *,
    capability: Any,
    repairs: list[FunctionalDeterministicRepair],
) -> FunctionalCall:
    """Remove result-form hints unsupported by the declared return contract."""
    if not call.return_expectations:
        return call
    return_specs = {item.name: item for item in capability.returns}
    expectations = dict(call.return_expectations)
    for return_name, expectation in tuple(expectations.items()):
        return_spec = return_specs.get(return_name)
        if return_spec is None:
            continue
        if expectation in return_spec.possible_forms:
            continue
        expectations.pop(return_name)
        repairs.append(
            FunctionalDeterministicRepair(
                call.call_id,
                "drop_fixed_form_return_expectation",
                f"{return_name}:{expectation}",
                "fixed_result_form",
            )
        )
    if expectations == call.return_expectations:
        return call
    return replace(call, return_expectations=expectations)


def _merge_equivalent_object_calls(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    repairs: list[FunctionalDeterministicRepair],
    issues: list[FunctionalPlanIssue],
    semantic_index: FunctionalSemanticIndex | None,
) -> tuple[FunctionalPlan, dict[str, str]]:
    call_aliases: dict[str, str] = {}
    exact_calls_by_fingerprint: dict[str, str] = {}
    ancestor_calls_by_fingerprint: dict[str, tuple[str, str]] = {}
    scope_calls: list[list[FunctionalCall]] = []
    call_locations: dict[str, tuple[int, int]] = {}
    for scope_index, scope in enumerate(plan.scopes):
        execution_locations: dict[str, int] = {}
        calls: list[FunctionalCall] = []
        for raw_call in scope.calls:
            call = _rewrite_call_result_aliases(raw_call, call_aliases)
            capability = catalog.get(call.capability_id)
            wire_inputs_are_stable = (
                capability is not None
                and _wire_inputs_are_version_stable(call, capability)
            )
            execution_fingerprint = (
                _call_execution_fingerprint(call)
                if wire_inputs_are_stable
                else None
            )
            ancestor_call = (
                ancestor_calls_by_fingerprint.get(execution_fingerprint)
                if execution_fingerprint is not None
                else None
            )
            if (
                ancestor_call is not None
                and not call.return_bindings
                and semantic_index is not None
                and ancestor_call[0] != scope.scope_id
                and ancestor_call[0]
                in semantic_index.handle_registry.ancestor_scopes(
                    scope.scope_id
                )
            ):
                previous = _located_call(
                    ancestor_call[1],
                    scope_index=scope_index,
                    current_calls=calls,
                    prior_scope_calls=scope_calls,
                    locations=call_locations,
                )
                merged_expectations = (
                    _merged_return_expectations(previous, call)
                    if previous is not None
                    else None
                )
                if merged_expectations is None:
                    issues.append(
                        _return_expectation_conflict_issue(previous, call)
                    )
                    if previous is not None:
                        call_aliases[call.call_id] = previous.call_id
                        repairs.append(
                            FunctionalDeterministicRepair(
                                call.call_id,
                                "isolate_conflicting_equivalent_call",
                                call.call_id,
                                previous.call_id,
                            )
                        )
                        continue
                else:
                    _replace_located_call(
                        replace(
                            previous,
                            return_expectations=merged_expectations,
                        ),
                        scope_index=scope_index,
                        current_calls=calls,
                        prior_scope_calls=scope_calls,
                        locations=call_locations,
                    )
                    call_aliases[call.call_id] = ancestor_call[1]
                    repairs.append(
                        FunctionalDeterministicRepair(
                            call.call_id,
                            "merge_ancestor_equivalent_call",
                            call.call_id,
                            ancestor_call[1],
                        )
                    )
                    continue
            previous_index = (
                execution_locations.get(execution_fingerprint)
                if execution_fingerprint is not None
                else None
            )
            if previous_index is not None:
                previous = calls[previous_index]
                merged_bindings = _merged_return_bindings(
                    previous.return_bindings,
                    call.return_bindings,
                )
                if merged_bindings is not None:
                    merged_expectations = _merged_return_expectations(
                        previous,
                        call,
                    )
                    if merged_expectations is None:
                        issues.append(
                            _return_expectation_conflict_issue(previous, call)
                        )
                        call_aliases[call.call_id] = previous.call_id
                        repairs.append(
                            FunctionalDeterministicRepair(
                                call.call_id,
                                "isolate_conflicting_equivalent_call",
                                call.call_id,
                                previous.call_id,
                            )
                        )
                        continue
                    else:
                        calls[previous_index] = replace(
                            previous,
                            return_bindings=merged_bindings,
                            return_expectations=merged_expectations,
                        )
                        call_aliases[call.call_id] = previous.call_id
                        repairs.append(
                            FunctionalDeterministicRepair(
                                call.call_id,
                                "merge_equivalent_capability_call",
                                call.call_id,
                                previous.call_id,
                            )
                        )
                        continue

            fingerprint = (
                _object_bound_call_fingerprint(call)
                if wire_inputs_are_stable
                else None
            )
            previous_call_id = (
                exact_calls_by_fingerprint.get(fingerprint)
                if fingerprint is not None
                else None
            )
            if previous_call_id is not None:
                previous = _located_call(
                    previous_call_id,
                    scope_index=scope_index,
                    current_calls=calls,
                    prior_scope_calls=scope_calls,
                    locations=call_locations,
                )
                merged_expectations = (
                    _merged_return_expectations(previous, call)
                    if previous is not None
                    else None
                )
                if merged_expectations is None:
                    issues.append(
                        _return_expectation_conflict_issue(previous, call)
                    )
                    if previous is not None:
                        call_aliases[call.call_id] = previous.call_id
                        repairs.append(
                            FunctionalDeterministicRepair(
                                call.call_id,
                                "isolate_conflicting_equivalent_call",
                                call.call_id,
                                previous.call_id,
                            )
                        )
                        continue
                else:
                    _replace_located_call(
                        replace(
                            previous,
                            return_expectations=merged_expectations,
                        ),
                        scope_index=scope_index,
                        current_calls=calls,
                        prior_scope_calls=scope_calls,
                        locations=call_locations,
                    )
                    call_aliases[call.call_id] = previous_call_id
                    repairs.append(
                        FunctionalDeterministicRepair(
                            call.call_id,
                            "merge_equivalent_object_call",
                            call.call_id,
                            previous_call_id,
                        )
                    )
                    continue
            if fingerprint is not None:
                exact_calls_by_fingerprint[fingerprint] = call.call_id
            if execution_fingerprint is not None:
                execution_locations[execution_fingerprint] = len(calls)
            if execution_fingerprint is not None and not call.return_bindings:
                ancestor_calls_by_fingerprint.setdefault(
                    execution_fingerprint,
                    (scope.scope_id, call.call_id),
                )
            call_locations[call.call_id] = (scope_index, len(calls))
            calls.append(call)
        scope_calls.append(calls)
    return (
        replace(
            plan,
            scopes=tuple(
                replace(scope, calls=tuple(calls))
                for scope, calls in zip(plan.scopes, scope_calls, strict=True)
            ),
        ),
        call_aliases,
    )


def _call_execution_fingerprint(call: FunctionalCall) -> str:
    payload = {
        "capability_id": call.capability_id,
        "args": {
            name: [item.to_payload() for item in values]
            for name, values in call.args.items()
        },
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _wire_inputs_are_version_stable(
    call: FunctionalCall,
    capability: FunctionalCapability,
) -> bool:
    """Return whether raw refs identify immutable inputs without Context lookup.

    ``point``/``function``/``symbol`` refs select the latest visible state at the
    call's position. Two calls with identical wire JSON can therefore consume
    different StateSlot versions after an intervening transition. Exact prior
    call results and ProblemIR facts are stable enough for this early merge;
    every other ref is deferred to reconciliation's resolved-state signature.
    """
    if capability.dependency_policy == "context_closure":
        return False
    return all(
        isinstance(ref, CallResultRef)
        or (isinstance(ref, SemanticRef) and ref.kind == "fact")
        for values in call.args.values()
        for ref in values
    )


def _merged_return_bindings(
    previous: Mapping[str, SemanticRef],
    current: Mapping[str, SemanticRef],
) -> dict[str, SemanticRef] | None:
    # Return bindings are part of a call's intended state effect. An unbound
    # computation and a call that binds an internal return to an external
    # object are not interchangeable, even when their executable args match.
    # Resolved-state placement can still merge calls whose complete effects
    # are identical after reconciliation.
    if dict(previous) != dict(current):
        return None
    return dict(previous)


def _merged_return_expectations(
    previous: FunctionalCall,
    current: FunctionalCall,
) -> dict[str, Any] | None:
    merged = dict(previous.return_expectations)
    for name, expectation in current.return_expectations.items():
        existing = merged.get(name)
        if existing is not None and existing != expectation:
            return None
        merged[name] = expectation
    return merged


def _return_expectation_conflict_issue(
    previous: FunctionalCall | None,
    current: FunctionalCall,
) -> FunctionalPlanIssue:
    previous_id = previous.call_id if previous is not None else "unknown"
    return _issue(
        "functional_reconciliation",
        "functional.return_expectation_conflict",
        (
            f"equivalent calls {previous_id} and {current.call_id} declare "
            "conflicting result forms"
        ),
        call_id=current.call_id,
        details={"canonical_call_id": previous_id},
    )


def _located_call(
    call_id: str,
    *,
    scope_index: int,
    current_calls: list[FunctionalCall],
    prior_scope_calls: list[list[FunctionalCall]],
    locations: Mapping[str, tuple[int, int]],
) -> FunctionalCall | None:
    location = locations.get(call_id)
    if location is None:
        return None
    call_scope, call_index = location
    return (
        current_calls[call_index]
        if call_scope == scope_index
        else prior_scope_calls[call_scope][call_index]
    )


def _replace_located_call(
    call: FunctionalCall,
    *,
    scope_index: int,
    current_calls: list[FunctionalCall],
    prior_scope_calls: list[list[FunctionalCall]],
    locations: Mapping[str, tuple[int, int]],
) -> None:
    call_scope, call_index = locations[call.call_id]
    if call_scope == scope_index:
        current_calls[call_index] = call
    else:
        prior_scope_calls[call_scope][call_index] = call


def _object_bound_call_fingerprint(call: FunctionalCall) -> str | None:
    if not call.return_bindings:
        return None
    if any(binding.kind == "answer" for binding in call.return_bindings.values()):
        return None
    payload = {
        "capability_id": call.capability_id,
        "args": {
            name: [item.to_payload() for item in values]
            for name, values in call.args.items()
        },
        "return_bindings": {
            name: binding.to_payload()
            for name, binding in call.return_bindings.items()
        },
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _reclassify_unique_semantic_args(
    args: dict[str, tuple[Any, ...]],
    *,
    arg_specs: Mapping[str, Any],
    semantic_index: FunctionalSemanticIndex,
    scope_id: str,
    call_id: str,
    repairs: list[FunctionalDeterministicRepair],
) -> dict[str, tuple[Any, ...]]:
    result: dict[str, list[Any]] = {
        name: list(values) for name, values in args.items()
    }
    for source_name, values in tuple(result.items()):
        source_spec = arg_specs.get(source_name)
        if source_spec is None:
            continue
        retained: list[Any] = []
        for value in values:
            if isinstance(value, CallResultRef) or not isinstance(value, SemanticRef):
                retained.append(value)
                continue
            if _semantic_ref_satisfies_arg(
                value,
                source_spec,
                semantic_index=semantic_index,
                scope_id=scope_id,
            ):
                retained.append(value)
                continue
            target_names = [
                name
                for name, spec in arg_specs.items()
                if name != source_name
                and _semantic_ref_satisfies_arg(
                    value,
                    spec,
                    semantic_index=semantic_index,
                    scope_id=scope_id,
                )
                and (
                    spec.cardinality == "many"
                    or not result.get(name)
                )
            ]
            populated_targets = [
                name for name in target_names if result.get(name)
            ]
            if len(populated_targets) == 1:
                target_names = populated_targets
            if len(target_names) != 1:
                retained.append(value)
                continue
            target_name = target_names[0]
            result.setdefault(target_name, []).append(value)
            repairs.append(
                FunctionalDeterministicRepair(
                    call_id,
                    "reclassify_semantic_arg",
                    source_name,
                    target_name,
                )
            )
        result[source_name] = retained
    return {
        name: tuple(values)
        for name, values in result.items()
        if values
    }


def _semantic_ref_satisfies_arg(
    ref: SemanticRef,
    arg_spec: Any,
    *,
    semantic_index: FunctionalSemanticIndex,
    scope_id: str,
) -> bool:
    resolved, _candidates = semantic_index.resolve(
        ref,
        scope_id=scope_id,
        accepted_types=(
            arg_spec.accepted_item_types or (arg_spec.runtime_type,)
        ),
        accepted_condition_kinds=arg_spec.accepted_condition_kinds,
    )
    return resolved is not None


def _drop_redundant_incompatible_optional_args(
    args: Mapping[str, tuple[Any, ...]],
    *,
    arg_specs: Mapping[str, Any],
    semantic_index: FunctionalSemanticIndex,
    scope_id: str,
    call_id: str,
    repairs: list[FunctionalDeterministicRepair],
) -> dict[str, tuple[Any, ...]]:
    """Drop a bad optional view only when another arg owns that role.

    Provider relationships come from capability contracts. Unknown refs remain
    errors, and a compatible explicit value remains authoritative.
    """
    result = dict(args)
    for name, values in tuple(result.items()):
        spec = arg_specs.get(name)
        if spec is None or spec.required or not values:
            continue
        role = spec.semantic_role or spec.name
        providers = tuple(
            provider_name
            for provider_name, provider_spec in arg_specs.items()
            if provider_name != name
            and result.get(provider_name)
            and role in provider_spec.provides_semantic_roles
        )
        if not providers or not all(isinstance(value, SemanticRef) for value in values):
            continue
        semantic_values = tuple(value for value in values if isinstance(value, SemanticRef))
        if any(
            _semantic_ref_satisfies_arg(
                value,
                spec,
                semantic_index=semantic_index,
                scope_id=scope_id,
            )
            for value in semantic_values
        ):
            continue
        if not all(
            _semantic_ref_is_known(
                value,
                semantic_index=semantic_index,
                scope_id=scope_id,
            )
            for value in semantic_values
        ):
            continue
        result.pop(name)
        repairs.append(
            FunctionalDeterministicRepair(
                call_id,
                "drop_redundant_incompatible_optional_arg",
                f"{name}=" + ",".join(value.ref for value in semantic_values),
                "provided_by=" + ",".join(providers),
            )
        )
    return result


def _semantic_ref_is_known(
    ref: SemanticRef,
    *,
    semantic_index: FunctionalSemanticIndex,
    scope_id: str,
) -> bool:
    return any(
        item.ref == ref.ref
        and item.kind == ref.kind
        and visible_from_valid_scope(
            item.valid_scope,
            scope_id=scope_id,
            registry=semantic_index.handle_registry,
        )
        for item in semantic_index.views
    )


class FunctionalSemanticIndex:
    """Resolve one short semantic ref to object/state/condition Context views."""

    def __init__(
        self,
        views: Sequence[FunctionalSemanticView],
        *,
        handle_registry: CanonicalHandleRegistry,
        entity_payloads: Mapping[str, Mapping[str, Any]] | None = None,
        fact_payloads: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self.views = tuple(views)
        self.handle_registry = handle_registry
        self.entity_payloads = dict(entity_payloads or {})
        self.fact_payloads = dict(fact_payloads or {})

    @classmethod
    def from_context(
        cls,
        context: PlannerStateContext,
        *,
        handle_registry: CanonicalHandleRegistry,
    ) -> "FunctionalSemanticIndex":
        state_slots = {item.slot_id: item for item in context.state.state_slots}
        conditions = {
            item.condition_id: item for item in context.state.conditions
        }
        slots_by_object: dict[str, list[Any]] = {}
        for slot in context.state.state_slots:
            if slot.object_ref:
                slots_by_object.setdefault(slot.object_ref, []).append(slot)
        problem_ir = context.state.problem_ir
        entity_payloads = {
            item.get("handle"): item
            for item in problem_ir.get("entities", ())
            if isinstance(item, dict) and isinstance(item.get("handle"), str)
        }
        fact_payloads = {
            item.get("handle"): item
            for item in problem_ir.get("facts", ())
            if isinstance(item, dict) and isinstance(item.get("handle"), str)
        }
        entity_dependencies = _problem_object_dependencies(
            entity_payloads,
            fact_payloads,
        )
        symbol_handles = _symbol_handles_by_name(entity_payloads)
        views: list[FunctionalSemanticView] = []
        for item in context.semantic_read_catalog():
            if not item.prompt_visible:
                continue
            slot = state_slots.get(item.state_slot_id or "")
            if slot is not None:
                views.append(
                    FunctionalSemanticView(
                        item.ref,
                        item.kind,
                        item.handle,
                        slot.runtime_type,
                        item.valid_scope,
                        object_ref=slot.object_ref,
                        state_slot_id=slot.slot_id,
                        dependency_object_refs=slot.dependency_object_refs,
                        free_symbol_refs=slot.free_symbol_refs,
                        source_state_slot_ids=(slot.slot_id,),
                        lineage=slot.lineage,
                    )
                )
            if item.kind == "fact":
                fact_payload = fact_payloads.get(item.handle, {})
                condition = conditions.get(item.condition_id or "")
                direct_fact_refs = tuple(
                    dict.fromkeys(
                        (
                            *_structured_object_refs(fact_payload),
                            *_structured_free_symbol_refs(
                                fact_payload,
                                symbol_handles=symbol_handles,
                            ),
                        )
                    )
                )
                fact_free_symbol_refs = tuple(
                    dict.fromkeys(
                        (
                            *_structured_free_symbol_refs(
                                fact_payload,
                                symbol_handles=symbol_handles,
                            ),
                            *_object_state_free_symbol_refs(
                                direct_fact_refs,
                                slots_by_object=slots_by_object,
                            ),
                        )
                    )
                )
                fact_dependencies = tuple(
                    dict.fromkeys(
                        _expand_object_dependencies(
                            direct_fact_refs,
                            entity_dependencies,
                        )
                    )
                )
                fact_type = str(fact_payload.get("type") or item.value_type or "fact")
                views.append(
                    FunctionalSemanticView(
                        item.ref,
                        item.kind,
                        item.handle,
                        "Condition",
                        item.valid_scope,
                        condition_id=item.condition_id,
                        condition_kind=fact_type,
                        object_roles=(
                            condition.object_roles
                            if condition is not None
                            else ()
                        ),
                        dependency_object_refs=fact_dependencies,
                        free_symbol_refs=fact_free_symbol_refs,
                        lineage=state_semantic_lineage(
                            semantic_roles=(fact_type,),
                            object_roles=(
                                StateObjectRoleBinding(
                                    role=role,
                                    object_refs=object_refs,
                                )
                                for role, object_refs in (
                                    condition.object_roles
                                    if condition is not None
                                    else ()
                                )
                            ),
                        ),
                    )
                )
                value_runtime_type = normalize_runtime_type(fact_type)
                if value_runtime_type not in {"Condition", "fact"}:
                    views.append(
                        FunctionalSemanticView(
                            item.ref,
                            item.kind,
                            item.handle,
                            value_runtime_type,
                            item.valid_scope,
                            object_ref=_primary_value_object_ref(
                                fact_payload,
                                value_runtime_type=value_runtime_type,
                                direct_object_refs=direct_fact_refs,
                            ),
                            dependency_object_refs=fact_dependencies,
                            free_symbol_refs=fact_free_symbol_refs,
                            lineage=state_semantic_lineage(
                                semantic_roles=(item.ref,),
                            ),
                        )
                    )
            payload = entity_payloads.get(item.handle)
            if payload is not None:
                runtime_type = _entity_runtime_type(payload)
                dependencies = tuple(
                    dict.fromkeys(
                        _expand_object_dependencies(
                            _structured_object_refs(payload),
                            entity_dependencies,
                        )
                    )
                )
                free_symbol_refs = (
                    (item.handle,)
                    if runtime_type == "Symbol"
                    else _structured_free_symbol_refs(
                        payload,
                        symbol_handles=symbol_handles,
                    )
                )
                views.append(
                    FunctionalSemanticView(
                        item.ref,
                        item.kind,
                        item.handle,
                        runtime_type,
                        item.valid_scope,
                        object_ref=item.handle,
                        dependency_object_refs=dependencies,
                        free_symbol_refs=free_symbol_refs,
                        lineage=state_semantic_lineage(
                            semantic_roles=(item.ref,),
                        ),
                    )
                )
                for object_slot in slots_by_object.get(item.handle, ()):
                    views.append(
                        FunctionalSemanticView(
                            item.ref,
                            item.kind,
                            object_slot.canonical_handle or item.handle,
                            object_slot.runtime_type,
                            object_slot.valid_scope or object_slot.scope_id,
                            object_ref=item.handle,
                            state_slot_id=object_slot.slot_id,
                            dependency_object_refs=(
                                object_slot.dependency_object_refs
                            ),
                            free_symbol_refs=object_slot.free_symbol_refs,
                            source_state_slot_ids=(object_slot.slot_id,),
                            lineage=object_slot.lineage,
                        )
                    )
        entity_views = tuple(
            item
            for item in views
            if item.object_ref == item.handle
            and item.state_slot_id is None
            and item.condition_id is None
        )
        state_views_by_object: dict[str, list[FunctionalSemanticView]] = {}
        for item in views:
            if item.object_ref and item.handle != item.object_ref:
                state_views_by_object.setdefault(item.object_ref, []).append(item)
        for entity in entity_views:
            for state_view in state_views_by_object.get(entity.object_ref or "", ()):
                views.append(
                    replace(
                        state_view,
                        ref=entity.ref,
                        kind=entity.kind,
                        dependency_object_refs=tuple(
                            dict.fromkeys(
                                (
                                    *state_view.dependency_object_refs,
                                    *entity.dependency_object_refs,
                                )
                            )
                        ),
                    )
                )
        return cls(
            _unique_views(views),
            handle_registry=handle_registry,
            entity_payloads=entity_payloads,
            fact_payloads=fact_payloads,
        )

    def materialize_function_state(
        self,
        ref: SemanticRef,
        *,
        scope_id: str,
        target_runtime_type: str,
        closure_policy: CapabilityStateClosurePolicy,
    ) -> FunctionalStateMaterialization:
        """Prove a Function template can satisfy a typed symbolic state read."""
        if target_runtime_type != "Parabola" or closure_policy == "any":
            return FunctionalStateMaterialization("not_applicable")
        candidates = tuple(
            item
            for item in self.views
            if item.ref == ref.ref
            and item.kind == ref.kind
            and item.runtime_type == "Function"
            and visible_from_valid_scope(
                item.valid_scope,
                scope_id=scope_id,
                registry=self.handle_registry,
            )
        )
        identities = {item.handle for item in candidates}
        if len(identities) != 1:
            return FunctionalStateMaterialization(
                "ambiguous" if candidates else "not_applicable"
            )
        source = candidates[0]
        payload = self.entity_payloads.get(source.handle, {})
        expression_text = payload.get("expression")
        if not isinstance(expression_text, str) or not expression_text.strip():
            return FunctionalStateMaterialization("not_applicable")
        try:
            expression = sp.sympify(expression_text)
        except (TypeError, ValueError, sp.SympifyError):
            return FunctionalStateMaterialization("not_applicable")

        function_variables = {
            str(item.get("name") or item.get("semantic_ref"))
            for item in self.entity_payloads.values()
            if item.get("entity_type") == "symbol"
            and item.get("role") == "function_variable"
        }
        substitutions: dict[sp.Symbol, sp.Expr] = {}
        supporting_handles: list[str] = []
        for symbol in sorted(expression.free_symbols, key=lambda item: item.name):
            if symbol.name in function_variables:
                continue
            selected = self._visible_symbol_value(
                symbol.name,
                scope_id=scope_id,
            )
            if selected is None:
                continue
            handle, value = selected
            substitutions[symbol] = value
            supporting_handles.append(handle)
        materialized = expression
        for _ in range(len(substitutions) + 1):
            updated = sp.simplify(materialized.subs(substitutions))
            if updated == materialized:
                break
            materialized = updated
        residual = tuple(
            sorted(
                (
                    symbol
                    for symbol in materialized.free_symbols
                    if symbol.name not in function_variables
                ),
                key=lambda item: item.name,
            )
        )
        max_free = 0 if closure_policy == "closed_only" else 1
        if len(residual) > max_free:
            return FunctionalStateMaterialization(
                "underdetermined",
                source=source,
                target_runtime_type=target_runtime_type,
                supporting_handles=tuple(supporting_handles),
                free_symbol_refs=tuple(
                    _symbol_handle_for_name(
                        symbol.name,
                        entity_payloads=self.entity_payloads,
                    )
                    for symbol in residual
                ),
            )
        free_symbol_refs = tuple(
            _symbol_handle_for_name(
                symbol.name,
                entity_payloads=self.entity_payloads,
            )
            for symbol in residual
        )
        return FunctionalStateMaterialization(
            "determined" if not residual else "single_free",
            source=source,
            target_runtime_type=target_runtime_type,
            supporting_handles=tuple(
                dict.fromkeys((*supporting_handles, *free_symbol_refs))
            ),
            free_symbol_refs=free_symbol_refs,
        )

    def _visible_symbol_value(
        self,
        symbol_name: str,
        *,
        scope_id: str,
    ) -> tuple[str, sp.Expr] | None:
        ancestors = self.handle_registry.ancestor_scopes(scope_id)
        candidates: list[tuple[int, str, sp.Expr]] = []
        for handle, payload in self.fact_payloads.items():
            if payload.get("type") != "symbol_value":
                continue
            subject = str(payload.get("subject") or "").rsplit(":", 1)[-1]
            if subject != symbol_name:
                continue
            valid_scope = str(
                payload.get("valid_scope") or payload.get("scope_id") or "problem"
            )
            if not visible_from_valid_scope(
                valid_scope,
                scope_id=scope_id,
                registry=self.handle_registry,
            ):
                continue
            try:
                value = sp.sympify(payload.get("value"))
                rank = ancestors.index(valid_scope)
            except (TypeError, ValueError, sp.SympifyError):
                continue
            candidates.append((rank, handle, value))
        if not candidates:
            return None
        nearest_rank = min(item[0] for item in candidates)
        nearest = [item for item in candidates if item[0] == nearest_rank]
        values = {sp.srepr(item[2]) for item in nearest}
        if len(values) != 1:
            return None
        _, handle, value = nearest[0]
        return handle, value

    def resolve(
        self,
        ref: SemanticRef,
        *,
        scope_id: str,
        accepted_types: Sequence[str],
        accepted_condition_kinds: Sequence[str] = (),
    ) -> tuple[FunctionalSemanticView | None, tuple[FunctionalSemanticView, ...]]:
        all_matching = tuple(
            item
            for item in self.views
            if item.ref == ref.ref
            and item.kind == ref.kind
        )
        matching = tuple(
            item
            for item in all_matching
            if visible_from_valid_scope(
                item.valid_scope,
                scope_id=scope_id,
                registry=self.handle_registry,
            )
        )
        compatible = tuple(
            item
            for item in matching
            if any(
                runtime_type_compatible(expected, item.runtime_type)
                for expected in accepted_types
            )
            and (
                not accepted_condition_kinds
                or item.condition_kind in accepted_condition_kinds
            )
        )
        if not compatible:
            return None, all_matching
        ranked = sorted(
            compatible,
            key=lambda item: (
                item.state_slot_id is not None,
                item.valid_scope == scope_id,
                item.condition_id is not None,
            ),
            reverse=True,
        )
        best = ranked[0]
        best_rank = (
            best.state_slot_id is not None,
            best.valid_scope == scope_id,
            best.condition_id is not None,
        )
        tied = [
            item
            for item in ranked
            if (
                item.state_slot_id is not None,
                item.valid_scope == scope_id,
                item.condition_id is not None,
            ) == best_rank
        ]
        identities = {
            (item.handle, item.runtime_type, item.object_ref) for item in tied
        }
        return (best if len(identities) == 1 else None), tuple(tied)

    def object_refs_for(
        self,
        ref: SemanticRef,
        *,
        scope_id: str,
    ) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.object_ref
                for item in self.views
                if item.ref == ref.ref
                and item.kind == ref.kind
                and item.object_ref is not None
                and visible_from_valid_scope(
                    item.valid_scope,
                    scope_id=scope_id,
                    registry=self.handle_registry,
                )
            )
        )

    def dependencies_for_object(self, object_ref: str | None) -> tuple[str, ...]:
        if object_ref is None:
            return ()
        return tuple(
            dict.fromkeys(
                dependency
                for item in self.views
                if item.object_ref == object_ref
                for dependency in item.dependency_object_refs
            )
        )

    def dependency_read_handles(
        self,
        object_refs: Sequence[str],
        *,
        scope_id: str,
    ) -> tuple[str, ...]:
        dependencies = set(object_refs)
        return tuple(
            dict.fromkeys(
                item.handle
                for item in self.views
                if visible_from_valid_scope(
                    item.valid_scope,
                    scope_id=scope_id,
                    registry=self.handle_registry,
                )
                and (
                    item.object_ref in dependencies
                    or bool(dependencies & set(item.dependency_object_refs))
                )
                and (
                    item.condition_id is not None
                    or item.state_slot_id is not None
                    or item.handle in dependencies
                )
            )
        )

    def available_refs(
        self,
        *,
        scope_id: str,
        accepted_types: Sequence[str],
        accepted_condition_kinds: Sequence[str] = (),
        accepted_semantic_roles: Sequence[str] = (),
        requires_materialized_state: bool = False,
    ) -> tuple[dict[str, str], ...]:
        result: dict[tuple[str, str], dict[str, str]] = {}
        for item in self.views:
            if not visible_from_valid_scope(
                item.valid_scope,
                scope_id=scope_id,
                registry=self.handle_registry,
            ):
                continue
            if not any(
                runtime_type_compatible(expected, item.runtime_type)
                for expected in accepted_types
            ):
                continue
            if (
                accepted_condition_kinds
                and item.condition_kind not in accepted_condition_kinds
            ):
                continue
            if (
                accepted_semantic_roles
                and item.ref.rsplit(".", 1)[-1]
                not in accepted_semantic_roles
            ):
                continue
            if requires_materialized_state and item.state_slot_id is None:
                continue
            key = (item.ref, item.kind)
            result.setdefault(
                key,
                {
                    "ref": item.ref,
                    "kind": item.kind,
                    "value_type": item.runtime_type,
                },
            )
        return tuple(result.values())

    def has_compatible_view(
        self,
        *,
        accepted_types: Sequence[str],
        accepted_condition_kinds: Sequence[str] = (),
        accepted_semantic_roles: Sequence[str] = (),
        requires_materialized_state: bool = False,
    ) -> bool:
        return any(
            any(
                runtime_type_compatible(expected, item.runtime_type)
                for expected in accepted_types
            )
            and (
                not accepted_condition_kinds
                or item.condition_kind in accepted_condition_kinds
            )
            and (
                not accepted_semantic_roles
                or item.ref.rsplit(".", 1)[-1]
                in accepted_semantic_roles
            )
            and (
                not requires_materialized_state
                or item.state_slot_id is not None
            )
            for item in self.views
        )

    def auto_selector_is_satisfiable(self, selector: str) -> bool:
        """Check selector-level Context prerequisites before prompt exposure."""
        if selector.startswith("fact_type:"):
            fact_type = selector.split(":", 1)[1]
            return fact_type in self.handle_registry.fact_types.values()
        checker = _AUTO_SELECTOR_CONTEXT_CHECKS.get(selector)
        return True if checker is None else checker(self.handle_registry)

    def compatible_views(
        self,
        *,
        scope_id: str,
        accepted_types: Sequence[str],
        accepted_condition_kinds: Sequence[str] = (),
    ) -> tuple[FunctionalSemanticView, ...]:
        return tuple(
            item
            for item in self.views
            if visible_from_valid_scope(
                item.valid_scope,
                scope_id=scope_id,
                registry=self.handle_registry,
            )
            and any(
                runtime_type_compatible(expected, item.runtime_type)
                for expected in accepted_types
            )
            and (
                not accepted_condition_kinds
                or item.condition_kind in accepted_condition_kinds
            )
        )


def _entity_runtime_type(payload: Mapping[str, Any]) -> str:
    entity_type = str(payload.get("entity_type") or "entity")
    if entity_type == "function":
        # The ProblemIR entity is an object reference. A concrete Parabola
        # state must come from a StateSlot/call return for this object; treating
        # the entity itself as Parabola lets reconciliation accept a value that
        # the Runtime binding index only exposes as a generic expression.
        return "Function"
    return {
        "point": "Point",
        "symbol": "Symbol",
        "line": "Line",
        "segment": "Segment",
        "ray": "Ray",
        "angle": "Angle",
        "circle": "Circle",
        "polygon": "Polygon",
    }.get(entity_type, entity_type.title())


def _symbol_handle_for_name(
    name: str,
    *,
    entity_payloads: Mapping[str, Mapping[str, Any]],
) -> str:
    return _symbol_handles_by_name(entity_payloads).get(
        name,
        f"symbol:problem:{name}",
    )


def _primary_value_object_ref(
    payload: Mapping[str, Any],
    *,
    value_runtime_type: str,
    direct_object_refs: Sequence[str],
) -> str | None:
    preferred_keys = {
        "ParameterValue": ("subject", "parameter", "symbol"),
        "Point": ("subject", "point"),
        "Parabola": ("subject", "curve", "function"),
        "Expression": ("subject",),
        "MinimumExpression": ("subject",),
    }.get(value_runtime_type, ("subject",))
    for key in preferred_keys:
        candidate = payload.get(key)
        if isinstance(candidate, str) and is_object_handle(candidate):
            return candidate
    return direct_object_refs[0] if len(direct_object_refs) == 1 else None


def _problem_object_dependencies(
    entity_payloads: Mapping[str, Mapping[str, Any]],
    fact_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[str, ...]]:
    symbol_handles = _symbol_handles_by_name(entity_payloads)
    direct: dict[str, set[str]] = {
        handle: {
            *_structured_object_refs(payload),
            *_structured_free_symbol_refs(
                payload,
                symbol_handles=symbol_handles,
            ),
        }
        for handle, payload in entity_payloads.items()
    }
    for payload in fact_payloads.values():
        refs = {
            *_structured_object_refs(payload),
            *_structured_free_symbol_refs(
                payload,
                symbol_handles=symbol_handles,
            ),
        }
        expanded = set(_expand_object_dependencies(tuple(refs), direct))
        for object_ref in refs:
            if object_ref in direct:
                direct[object_ref].update(expanded)
    return {
        object_ref: tuple(_expand_object_dependencies(tuple(values), direct))
        for object_ref, values in direct.items()
    }


def _has_declared_translation_target(
    registry: CanonicalHandleRegistry,
) -> bool:
    for payload in registry.entity_payloads.values():
        if payload.get("entity_type") != "point":
            continue
        if payload.get("definition") != "translated_point":
            continue
        has_source = any(payload.get(key) for key in ("of", "source", "base"))
        vector = payload.get("vector")
        has_vector = (
            isinstance(vector, list)
            and len(vector) == 2
        ) or ("dx" in payload and "dy" in payload)
        if has_source and has_vector:
            return True
    return False


_AUTO_SELECTOR_CONTEXT_CHECKS = {
    "translated_point:target": _has_declared_translation_target,
}


def _unique_views(
    items: Sequence[FunctionalSemanticView],
) -> tuple[FunctionalSemanticView, ...]:
    result: dict[tuple[Any, ...], FunctionalSemanticView] = {}
    for item in items:
        key = (
            item.ref,
            item.kind,
            item.handle,
            item.runtime_type,
            item.object_ref,
            item.state_slot_id,
            item.condition_id,
            item.condition_kind,
        )
        result.setdefault(key, item)
    return tuple(result.values())


__all__ = [
    "FunctionalDeterministicRepair",
    "FunctionalPlanElaborationResult",
    "FunctionalPlanElaborator",
    "FunctionalSemanticIndex",
    "FunctionalSemanticView",
    "runtime_type_compatible",
]
