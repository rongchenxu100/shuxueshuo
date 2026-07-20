"""Declarative post-resolution validators for Functional capabilities."""

from __future__ import annotations

from typing import Callable, Mapping

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCapability,
    FunctionalPlanIssue,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)

FunctionalReconciliationValidator = Callable[
    [
        FunctionalCapability,
        Mapping[str, tuple[ResolvedFunctionalValue, ...]],
        Mapping[tuple[str, str], ResolvedFunctionalValue],
        str,
        str,
    ],
    tuple[FunctionalPlanIssue, ...],
]


def functional_reconciliation_issues(
    capability: FunctionalCapability,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    call_id: str,
    scope_id: str,
) -> tuple[FunctionalPlanIssue, ...]:
    """Run every validator declared by the capability's source spec."""
    issues: list[FunctionalPlanIssue] = list(
        _distinct_argument_identity_issues(
            capability,
            resolved_args,
            call_id=call_id,
            scope_id=scope_id,
        )
    )
    for validator_id in capability.reconciliation_validators:
        validator = _RECONCILIATION_VALIDATORS.get(validator_id)
        if validator is None:
            raise ValueError(
                "planner_configuration_error: functional reconciliation "
                f"validator missing: {validator_id}"
            )
        issues.extend(
            validator(
                capability,
                resolved_args,
                produced,
                call_id,
                scope_id,
            )
        )
    return tuple(issues)


def _distinct_argument_identity_issues(
    capability: FunctionalCapability,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
) -> tuple[FunctionalPlanIssue, ...]:
    """Reject declared argument groups that resolve to the same state identity."""
    issues: list[FunctionalPlanIssue] = []
    for group in capability.distinct_arg_groups:
        identities: dict[str, list[str]] = {}
        bindings: list[dict[str, str | None]] = []
        for arg_name in group:
            values = resolved_args.get(arg_name, ())
            if len(values) != 1:
                continue
            value = values[0]
            identity = value.object_ref or value.state_slot_id or value.handle
            identities.setdefault(identity, []).append(arg_name)
            bindings.append(
                {
                    "arg": arg_name,
                    "object_ref": value.object_ref,
                    "state_slot_id": value.state_slot_id,
                    "source_call_id": value.source_call_id,
                    "return": value.return_name,
                }
            )
        duplicates = tuple(
            names for names in identities.values() if len(names) > 1
        )
        if not duplicates:
            continue
        issues.append(
            FunctionalPlanIssue(
                layer="functional_reconciliation",
                code="functional.arg_distinctness_violation",
                message=(
                    f"call {call_id} requires distinct semantic states for "
                    + ", ".join(group)
                ),
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg_group": list(group),
                    "duplicate_args": [list(item) for item in duplicates],
                    "current_bindings": bindings,
                    "unchanged_binding_rejected": True,
                },
            )
        )
    return tuple(issues)


def validate_reconciliation_validator_ids(
    validator_ids: tuple[str, ...],
) -> None:
    """Reject unknown declarations before an LLM request is made."""
    unknown = tuple(
        validator_id
        for validator_id in validator_ids
        if validator_id not in _RECONCILIATION_VALIDATORS
    )
    if unknown:
        raise ValueError(
            "planner_configuration_error: functional reconciliation validator "
            f"missing: {', '.join(unknown)}"
        )


def _companion_symbol_coverage(
    capability: FunctionalCapability,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    call_id: str,
    scope_id: str,
) -> tuple[FunctionalPlanIssue, ...]:
    """Require values for every Symbol companion of a parameterized Point."""
    parameter_args = [
        item
        for item in capability.args
        if any(
            runtime_type_compatible(expected, "ParameterValue")
            for expected in (item.accepted_item_types or (item.runtime_type,))
        )
    ]
    if not parameter_args:
        return ()
    parameter_object_refs = {
        value.object_ref
        for arg in parameter_args
        for value in resolved_args.get(arg.name, ())
        if value.object_ref is not None
    }
    required_sources: dict[str, dict[str, str]] = {}
    required_object_refs: set[str] = set()
    for input_name, values in resolved_args.items():
        for value in values:
            if value.runtime_type != "Point":
                continue
            companion_refs: set[str] = set()
            for (source_call_id, return_name), sibling in produced.items():
                if (
                    source_call_id != value.source_call_id
                    or sibling.runtime_type != "Symbol"
                    or sibling.object_ref is None
                ):
                    continue
                companion_refs.add(sibling.object_ref)
                required_object_refs.add(sibling.object_ref)
                required_sources.setdefault(
                    sibling.object_ref,
                    {
                        "from_call": source_call_id,
                        "return": return_name,
                        "value_type": "Symbol",
                    },
                )
            for symbol_ref in value.free_symbol_refs:
                if not symbol_ref.startswith("symbol:") or symbol_ref in companion_refs:
                    continue
                required_object_refs.add(symbol_ref)
                required_sources.setdefault(
                    symbol_ref,
                    {
                        "source": "point_free_symbol_state",
                        "input_arg": input_name,
                        "semantic_ref": symbol_ref.rsplit(":", 1)[-1],
                        "value_type": "Symbol",
                    },
                )
    if required_object_refs <= parameter_object_refs:
        return ()
    argument = parameter_args[0]
    current_bindings = [
        {
            "source_call_id": value.source_call_id,
            "return": value.return_name,
            "value_type": value.runtime_type,
            "identity_matches_required": value.object_ref in required_object_refs,
        }
        for item in parameter_args
        for value in resolved_args.get(item.name, ())
    ]
    return (
        FunctionalPlanIssue(
            layer="functional_reconciliation",
            code="functional.arg_identity_mismatch",
            message=(
                f"call {call_id} cannot run with its current bindings: "
                f"argument {argument.name} does not provide a value for every "
                "Symbol identity required by its parameterized Point input"
            ),
            call_id=call_id,
            scope_id=scope_id,
            details={
                "arg": argument.name,
                "semantic_role": argument.semantic_role or argument.name,
                "accepted_item_types": list(
                    argument.accepted_item_types or (argument.runtime_type,)
                ),
                "required_symbol_sources": list(required_sources.values()),
                "current_bindings": current_bindings,
                "unchanged_binding_rejected": True,
                "repair_options": [
                    {
                        "action": "add_missing_state_producer",
                        "requirement": (
                            "produce a ParameterValue for each missing Symbol "
                            "identity before this call"
                        ),
                    },
                    {
                        "action": "replace_capability",
                        "requirement": (
                            "produce the same external destination from already "
                            "resolved semantic states"
                        ),
                    },
                ],
            },
        ),
    )


_RECONCILIATION_VALIDATORS: dict[
    str,
    FunctionalReconciliationValidator,
] = {
    "companion_symbol_coverage": _companion_symbol_coverage,
}


__all__ = [
    "functional_reconciliation_issues",
    "validate_reconciliation_validator_ids",
]
