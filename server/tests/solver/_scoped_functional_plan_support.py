from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalPlan,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "functional-plan-v3-fixtures"
)


def load_v3_fixture_payload(case: str) -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )


def migrate_v1_fixture_payload_to_v3(
    plan: FunctionalPlan,
    planning_context: ProblemPlanningContext,
    call_goal_bindings: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    """One-time test migration used to author and audit checked-in v3 gold."""

    scopes = {scope.scope_id: scope for scope in planning_context.scopes}
    parents = {
        scope.scope_id: scope.parent_scope_id
        for scope in planning_context.scopes
    }
    goal_by_unit = {
        goal.goal_unit_id: goal for goal in planning_context.goal_views
    }
    goal_by_answer = {
        (goal.answer_ref.ref, goal.answer_ref.kind): goal
        for goal in planning_context.goal_views
    }
    calls = {call.call_id: call for call in plan.calls}
    original_scope = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    answer_source: dict[str, dict[str, str]] = {}
    for call in plan.calls:
        for return_name, binding in call.return_bindings.items():
            goal = goal_by_answer.get((binding.ref, binding.kind))
            if goal is not None:
                answer_source[goal.answer_ref.ref] = {
                    "step_id": call.call_id,
                    "return": _public_return_name(call, return_name),
                }

    scope_steps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    goal_steps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in plan.calls:
        goal_ids = tuple(call_goal_bindings[call.call_id])
        owners = [goal_by_unit[goal_id].owner_scope_id for goal_id in goal_ids]
        owner_scope = original_scope[call.call_id]
        authored_goal_ref: str | None = None
        if len(goal_ids) == 1 and owner_scope == owners[0]:
            authored_goal_ref = goal_by_unit[goal_ids[0]].answer_ref.ref
        elif not all(_is_ancestor(owner_scope, item, parents) for item in owners):
            owner_scope = _lca(owners, parents)
        payload = _step_payload(call, calls=calls)
        if authored_goal_ref is None:
            scope_steps[owner_scope].append(payload)
        else:
            goal_steps[authored_goal_ref].append(payload)

    children: dict[str, list[str]] = defaultdict(list)
    root: str | None = None
    for scope in planning_context.scopes:
        if scope.parent_scope_id is None:
            root = scope.scope_id
        else:
            children[scope.parent_scope_id].append(scope.scope_id)
    assert root is not None

    goals_by_scope: dict[str, list[Any]] = defaultdict(list)
    for goal in planning_context.goal_views:
        goals_by_scope[goal.owner_scope_id].append(goal)

    def build(scope_id: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_ref": scope_id}
        if scope_steps[scope_id]:
            payload["steps"] = scope_steps[scope_id]
        goal_payloads = []
        for goal in goals_by_scope[scope_id]:
            item: dict[str, Any] = {
                "goal_ref": goal.answer_ref.ref,
                "answer_from": answer_source[goal.answer_ref.ref],
            }
            if goal_steps[goal.answer_ref.ref]:
                item["steps"] = goal_steps[goal.answer_ref.ref]
            goal_payloads.append(item)
        if goal_payloads:
            payload["goals"] = goal_payloads
        if children[scope_id]:
            payload["children"] = [build(item) for item in children[scope_id]]
        return payload

    return {"format": "functional_plan/v3", "root_scope": build(root)}


def _step_payload(call: Any, *, calls: dict[str, Any]) -> dict[str, Any]:
    public_arg_names = {
        "quadratic_x_axis_intercept_point": {"quadratic": "parabola"},
    }.get(call.capability_id, {})
    public_return_names = {
        "square_adjacent_vertex_from_side": {"point": "adjacent_vertex"},
    }.get(call.capability_id, {})
    args: dict[str, Any] = {}
    for name, values in call.args.items():
        encoded = [
            (
                {"step_id": value.from_call, "return": value.return_name}
                if isinstance(value, CallResultRef)
                else value.ref
            )
            for value in values
        ]
        encoded = [
            {
                **value,
                "return": _public_return_name(
                    calls[value["step_id"]],
                    value["return"],
                ),
            }
            if isinstance(value, dict)
            else value
            for value in encoded
        ]
        public_name = public_arg_names.get(name, name)
        args[public_name] = encoded[0] if len(encoded) == 1 else encoded
    payload: dict[str, Any] = {
        "step_id": call.call_id,
        "capability_id": call.capability_id,
        "args": args,
    }
    outputs = {
        public_return_names.get(name, name): binding.ref
        for name, binding in call.return_bindings.items()
        if binding.kind != "answer"
    }
    if outputs:
        payload["return_bindings"] = {
            name: {"kind": "existing", "ref": ref}
            for name, ref in outputs.items()
        }
    if call.return_expectations:
        payload["return_expectations"] = dict(call.return_expectations)
    intent = call.strategy or call.reason
    if intent:
        payload["intent"] = intent
    return payload


def _public_return_name(call: Any, return_name: str) -> str:
    return {
        "square_adjacent_vertex_from_side": {"point": "adjacent_vertex"},
    }.get(call.capability_id, {}).get(return_name, return_name)


def _is_ancestor(
    ancestor: str,
    descendant: str,
    parents: dict[str, str | None],
) -> bool:
    cursor: str | None = descendant
    while cursor is not None:
        if cursor == ancestor:
            return True
        cursor = parents[cursor]
    return False


def _lca(scopes: list[str], parents: dict[str, str | None]) -> str:
    paths = [_path(scope, parents) for scope in scopes]
    shared = paths[0][0]
    for items in zip(*paths, strict=False):
        if len(set(items)) != 1:
            break
        shared = items[0]
    return shared


def _path(scope: str, parents: dict[str, str | None]) -> list[str]:
    result: list[str] = []
    cursor: str | None = scope
    while cursor is not None:
        result.append(cursor)
        cursor = parents[cursor]
    return list(reversed(result))
