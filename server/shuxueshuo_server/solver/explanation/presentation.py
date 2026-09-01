"""Legacy transactional-call projection used only by compiler diagnostics.

Student ownership is no longer projected here.  F5-F5A uses the recursive
Canonical Plan owner tree through :mod:`explanation.snapshot`.
"""

from __future__ import annotations

from typing import Any


def transactional_functional_steps(
    replay: Any | None,
    planner_output: Any,
) -> tuple[dict[str, Any], ...]:
    """Project goal-reachable transactional calls for non-teaching diagnostics."""

    reconciliation = getattr(replay, "functional_reconciliation", None)
    attempt = getattr(replay, "transactional_attempt_result", None)
    if reconciliation is None or attempt is None or planner_output is None:
        return ()
    goal_calls = set(getattr(attempt, "goal_reachable_call_ids", ()))
    calls = {item.call_id: item for item in reconciliation.calls}
    result: list[dict[str, Any]] = []
    for compiled_plan in planner_output.step_plans:
        call_id = compiled_plan.step_id
        if call_id not in goal_calls:
            continue
        call = calls.get(call_id)
        if call is None:
            continue
        produced = [
            {
                "handle": handle,
                "valid_scope": allocation.valid_scope,
                "description": (
                    f"{call.capability_id} return {allocation.return_name}"
                ),
                "output_type": allocation.runtime_type,
            }
            for allocation in call.returns
            for handle in dict.fromkeys(
                (allocation.state_handle, allocation.handle)
            )
            if isinstance(handle, str) and handle
        ]
        target = next(
            (
                allocation.handle
                for allocation in call.returns
                if allocation.bound_ref is not None
                and allocation.bound_ref.kind == "answer"
            ),
            None,
        )
        if target is None:
            target = next(
                (
                    allocation.math_object_id.value
                    for allocation in call.returns
                    if allocation.math_object_id is not None
                ),
                call.capability_id,
            )
        result.append(
            {
                "scope_id": compiled_plan.scope,
                "step_id": call_id,
                "recipe_hint": call.capability_id,
                "goal_type": call.capability_id,
                "target": target,
                "strategy": "",
                "reads": _transactional_call_reads(call),
                "creates": _transactional_call_creates(call),
                "produces": produced,
                "reason": "",
            }
        )
    return tuple(result)


def _transactional_call_reads(call: Any) -> list[str]:
    return list(
        dict.fromkeys(
            handle
            for values in call.resolved_args.values()
            for value in values
            for handle in (
                value.handle,
                value.object_ref,
                *value.supporting_handles,
            )
            if isinstance(handle, str) and handle
        )
    )


def _transactional_call_creates(call: Any) -> list[dict[str, Any]]:
    return [
        {
            "handle": allocation.math_object_id.value,
            "entity_type": allocation.math_object_id.kind,
            "valid_scope": allocation.valid_scope,
            "description": "Functional generated object",
        }
        for allocation in call.returns
        if allocation.math_object_id is not None
        and allocation.write_mode == "create"
    ]


__all__ = ["transactional_functional_steps"]
