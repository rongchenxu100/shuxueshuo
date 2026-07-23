"""Runtime verification for optional FunctionalPlan scalar result expectations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from shuxueshuo_server.solver.contracts import FunctionalResultForm
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCapability,
    FunctionalCall,
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
    FunctionalResultFormEvent,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    StateWriteProvenance,
    StepIntentExecutionDiagnostic,
)


def verify_functional_result_forms(
    plan: FunctionalPlan,
    reconciliation: FunctionalPlanReconciliationResult,
    diagnostic: StepIntentExecutionDiagnostic | None,
    *,
    catalog: FunctionalCapabilityCatalog | None = None,
) -> tuple[tuple[FunctionalResultFormEvent, ...], tuple[PlannerRetryIssue, ...]]:
    """Compare LLM expectations with runtime free-symbol provenance."""
    if diagnostic is None:
        return (), ()
    provenance = diagnostic.state_write_provenance
    by_handle = {item.produced_handle: item for item in provenance}
    available_parameters = _available_parameter_states(provenance)
    calls = {call.call_id: call for call in plan.calls}
    events: list[FunctionalResultFormEvent] = []
    issues: list[PlannerRetryIssue] = []
    for reconciled in reconciliation.calls:
        call = calls.get(reconciled.call_id)
        if call is None:
            continue
        capability = catalog.get(call.capability_id) if catalog else None
        return_specs = (
            {item.name: item for item in capability.returns}
            if capability is not None
            else {}
        )
        for allocation in reconciled.returns:
            expected = call.return_expectations.get(allocation.return_name)
            max_free = (
                return_specs[allocation.return_name].max_independent_free_parameters
                if allocation.return_name in return_specs
                else None
            )
            if expected is None and max_free is None:
                continue
            write = by_handle.get(allocation.handle)
            if write is None:
                if expected is not None:
                    events.append(
                        FunctionalResultFormEvent(
                            call_id=call.call_id,
                            scope_id=reconciled.scope_id,
                            return_name=allocation.return_name,
                            expected_form=expected,
                            actual_form=None,
                            status="provenance_missing",
                            available_parameter_states=available_parameters,
                        )
                    )
                continue
            free_symbols = tuple(
                sorted(
                    set(write.free_symbol_names)
                    - set(write.closure_ignored_symbol_names)
                )
            )
            if max_free is not None and len(free_symbols) > max_free:
                issues.append(
                    _return_complexity_issue(
                        call_id=call.call_id,
                        scope_id=reconciled.scope_id,
                        capability_id=call.capability_id,
                        return_name=allocation.return_name,
                        handle=allocation.handle,
                        free_symbols=free_symbols,
                        max_free=max_free,
                    )
                )
                continue
            if expected is None:
                continue
            actual = _actual_result_form(expected, free_symbols)
            status = _event_status(expected, actual)
            events.append(
                FunctionalResultFormEvent(
                    call_id=call.call_id,
                    scope_id=reconciled.scope_id,
                    return_name=allocation.return_name,
                    expected_form=expected,
                    actual_form=actual,
                    status=status,
                    free_symbol_names=free_symbols,
                    available_parameter_states=available_parameters,
                )
            )
            if status != "mismatch":
                continue
            issues.append(
                PlannerRetryIssue(
                    layer="goal_verification",
                    code="functional.return_form_mismatch",
                    step_id=call.call_id,
                    scope_id=reconciled.scope_id,
                    repair_target="functional_call",
                    preserve_policy="none",
                    message=(
                        f"return {call.call_id}.{allocation.return_name} was expected "
                        f"to be {expected} but its runtime state is {actual}"
                    ),
                    hints=(
                        "Keep this result open for a later parameter-solving call, or "
                        "supply the missing ParameterValue states before requesting a "
                        "closed result.",
                    ),
                    related_handles=(allocation.handle,),
                    details={
                        "return": allocation.return_name,
                        "expected_form": expected,
                        "actual_form": actual,
                        "free_symbol_names": list(free_symbols),
                        "available_parameter_states": list(available_parameters),
                    },
                )
            )
    return tuple(events), tuple(issues)


def _return_complexity_issue(
    *,
    call_id: str,
    scope_id: str,
    capability_id: str,
    return_name: str,
    handle: str,
    free_symbols: tuple[str, ...],
    max_free: int,
) -> PlannerRetryIssue:
    return PlannerRetryIssue(
        layer="goal_verification",
        code="functional.return_state_underdetermined",
        step_id=call_id,
        scope_id=scope_id,
        repair_target="functional_call",
        preserve_policy="none",
        message=(
            f"return {call_id}.{return_name} retains {len(free_symbols)} "
            f"independent parameters; {capability_id} allows at most {max_free}"
        ),
        hints=(
            "Reduce the relevant symbolic state before exposing this result; "
            "return_expectations describes open versus closed form but does "
            "not override the capability's parameter budget.",
        ),
        related_handles=(handle,),
        details={
            "return": return_name,
            "free_symbol_names": list(free_symbols),
            "max_independent_free_parameters": max_free,
        },
    )


def canonicalize_verified_result_forms(
    plan: FunctionalPlan,
    events: Sequence[FunctionalResultFormEvent],
) -> FunctionalPlan:
    """Write non-blocking runtime closure proofs back to the canonical plan."""
    actual_by_return = {
        (event.call_id, event.return_name): event.actual_form
        for event in events
        if event.status == "result_form_closed"
        and event.actual_form is not None
    }
    if not actual_by_return:
        return plan
    scopes = tuple(
        replace(
            scope,
            calls=tuple(
                _call_with_verified_result_forms(call, actual_by_return)
                for call in scope.calls
            ),
        )
        for scope in plan.scopes
    )
    return replace(plan, scopes=scopes)


def verify_functional_input_closures(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    catalog: FunctionalCapabilityCatalog,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> tuple[PlannerRetryIssue, ...]:
    """Validate declared input closure against actual producer provenance.

    Reconciliation can validate Context states and deterministically
    materialized Function templates immediately. Prior-call returns are only
    estimates until their constraint analyzer and runtime method execute, so
    this pass owns the authoritative check for those values.
    """
    if diagnostic is None:
        return ()
    by_handle = {
        item.produced_handle: item
        for item in diagnostic.state_write_provenance
    }
    issues: list[PlannerRetryIssue] = []
    for call in reconciliation.calls:
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        args = {item.name: item for item in capability.args}
        for arg_name, values in call.resolved_args.items():
            spec = args.get(arg_name)
            if spec is None or spec.input_closure_policy == "any":
                continue
            max_free = (
                0 if spec.input_closure_policy == "closed_only" else 1
            )
            for value in values:
                if value.source_call_id is None:
                    continue
                write = by_handle.get(value.handle)
                if write is None:
                    continue
                free_symbols = tuple(
                    sorted(
                        set(write.free_symbol_names)
                        - set(write.closure_ignored_symbol_names)
                    )
                )
                if len(free_symbols) <= max_free:
                    continue
                issues.append(
                    _input_closure_issue(
                        capability,
                        call_id=call.call_id,
                        scope_id=call.scope_id,
                        arg_name=arg_name,
                        source_call_id=value.source_call_id,
                        source_handle=value.handle,
                        free_symbols=free_symbols,
                        max_free=max_free,
                    )
                )
    return tuple(issues)


def _call_with_verified_result_forms(
    call: FunctionalCall,
    actual_by_return: dict[tuple[str, str], FunctionalResultForm],
) -> FunctionalCall:
    call_id = call.call_id
    expectations = dict(call.return_expectations)
    for (event_call_id, return_name), actual_form in actual_by_return.items():
        if event_call_id == call_id:
            expectations[return_name] = actual_form
    return replace(call, return_expectations=expectations)


def _input_closure_issue(
    capability: FunctionalCapability,
    *,
    call_id: str,
    scope_id: str,
    arg_name: str,
    source_call_id: str,
    source_handle: str,
    free_symbols: tuple[str, ...],
    max_free: int,
) -> PlannerRetryIssue:
    return PlannerRetryIssue(
        layer="goal_verification",
        code="functional.arg_state_underdetermined",
        step_id=call_id,
        scope_id=scope_id,
        repair_target="functional_call",
        preserve_policy="none",
        message=(
            f"argument {call_id}.{arg_name} receives a state with "
            f"{len(free_symbols)} independent free parameters, but "
            f"{capability.capability_id} accepts at most {max_free}"
        ),
        hints=(
            "Add enough constraints to reduce the input state, or choose a "
            "capability whose declared input closure accepts this state.",
        ),
        related_handles=(source_handle,),
        details={
            "arg": arg_name,
            "source_call_id": source_call_id,
            "free_symbol_names": list(free_symbols),
            "max_independent_free_parameters": max_free,
        },
    )


def _event_status(
    expected: FunctionalResultForm,
    actual: FunctionalResultForm,
) -> str:
    if expected == actual:
        return "matched"
    if (expected, actual) in {
        ("open_expression", "closed_value"),
        ("open_state", "closed_state"),
    }:
        return "result_form_closed"
    return "mismatch"


def _actual_result_form(
    expected: FunctionalResultForm,
    free_symbols: tuple[str, ...],
) -> FunctionalResultForm:
    if expected in {"open_state", "closed_state"}:
        return "open_state" if free_symbols else "closed_state"
    return "open_expression" if free_symbols else "closed_value"


def _available_parameter_states(
    provenance: Sequence[StateWriteProvenance],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.produced_handle
            for item in provenance
            if item.runtime_type == "ParameterValue"
        )
    )


__all__ = ["verify_functional_result_forms"]
