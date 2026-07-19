"""Runtime verification for optional FunctionalPlan scalar result expectations."""

from __future__ import annotations

from collections.abc import Sequence

from shuxueshuo_server.solver.contracts import FunctionalResultForm
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
    FunctionalResultFormEvent,
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
        if call is None or not call.return_expectations:
            continue
        for allocation in reconciled.returns:
            expected = call.return_expectations.get(allocation.return_name)
            if expected is None:
                continue
            write = by_handle.get(allocation.handle)
            if write is None:
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
            free_symbols = tuple(sorted(set(write.free_symbol_names)))
            actual: FunctionalResultForm = (
                "open_expression" if free_symbols else "closed_value"
            )
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
                        "to be closed_value but still contains free symbols"
                    ),
                    hints=(
                        "Keep this result open for a later parameter-solving call, or "
                        "supply the missing ParameterValue states before requesting a "
                        "closed value.",
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


def _event_status(
    expected: FunctionalResultForm,
    actual: FunctionalResultForm,
) -> str:
    if expected == actual:
        return "matched"
    if expected == "open_expression" and actual == "closed_value":
        return "result_form_closed"
    return "mismatch"


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
