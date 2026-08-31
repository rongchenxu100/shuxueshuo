"""Production adapter for the Functional Scope Retry generated gate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_scope_retry import (
    FunctionalScopeRepairCompiler,
    FunctionalScopeRetryAuthorityProjector,
    FunctionalScopeRetryError,
    build_scope_retry_restore_seed,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)

from _functional_scope_retry_support import (
    FAILED_STEP_ID,
    ScopeRetryFixture,
    iter_scopes,
    scope_retry_fixture,
)
from support.functional_scope_retry_generated import (
    FunctionalScopeRetryScenario,
)


@dataclass(frozen=True)
class FunctionalScopeRetryProductionOutcome:
    accepted: bool
    error_code: str | None
    no_progress: bool
    failed_candidate_ghost_write_count: int
    open_scope_restore_leak_count: int
    restored_call_count: int


_FIXTURE_ROOTS: list[TemporaryDirectory[str]] = []


@lru_cache(maxsize=None)
def _fixture(profile: str, normalized_failed_scope: bool) -> ScopeRetryFixture:
    root = TemporaryDirectory(prefix=f"functional-scope-retry-{profile}-")
    _FIXTURE_ROOTS.append(root)
    base = scope_retry_fixture(Path(root.name))
    if profile == "goal_local":
        fixture = base
    elif profile != "scope_owned":
        raise AssertionError(profile)
    else:
        fixture = _scope_owned_fixture(base)
    if not normalized_failed_scope:
        return fixture
    failed = _without_open_scope_return_expectations(fixture.failed_payload)
    failed_plan, validation = (
        ScopedFunctionalPlanValidator().validate_payload_with_report(failed)
    )
    assert validation.ok and failed_plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(failed, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )
    return ScopeRetryFixture(
        authority_fixture=fixture.authority_fixture,
        correct_payload=fixture.correct_payload,
        failed_payload=failed,
        failed_plan=failed_plan,
        execution=execution,
    )


def _scope_owned_fixture(base: ScopeRetryFixture) -> ScopeRetryFixture:
    correct = _move_failed_step_to_scope(base.correct_payload)
    failed = _move_failed_step_to_scope(base.failed_payload)
    failed_plan, validation = (
        ScopedFunctionalPlanValidator().validate_payload_with_report(failed)
    )
    assert validation.ok and failed_plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(failed, ensure_ascii=False),
        inputs=base.inputs,
        planning_context=base.planning_context,
        problem_binding_catalog=base.binding_catalog,
        handle_registry=base.handle_registry,
        context=ContextBuilder().build(base.problem),
        planner_state_context=base.planner_state_context,
        problem_payload=base.problem_payload,
    )
    return ScopeRetryFixture(
        authority_fixture=base.authority_fixture,
        correct_payload=correct,
        failed_payload=failed,
        failed_plan=failed_plan,
        execution=execution,
    )


def _move_failed_step_to_scope(payload: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(payload)
    scope = next(
        item for item in iter_scopes(value["root_scope"])
        if item["scope_ref"] == "ii"
    )
    goal = next(
        item for item in scope.get("goals", ())
        if item["goal_ref"] == "ii.a"
    )
    index = next(
        index
        for index, item in enumerate(goal["steps"])
        if item["step_id"] == FAILED_STEP_ID
    )
    scope.setdefault("steps", []).append(goal["steps"].pop(index))
    return value


def _without_open_scope_return_expectations(
    payload: dict[str, Any],
) -> dict[str, Any]:
    value = deepcopy(payload)
    scope = next(
        item for item in iter_scopes(value["root_scope"])
        if item["scope_ref"] == "ii"
    )
    for item in scope.get("steps", ()):
        item.pop("return_expectations", None)
    for goal in scope.get("goals", ()):
        for item in goal.get("steps", ()):
            item.pop("return_expectations", None)
    return value


def run_functional_scope_retry_adapter(
    scenario: FunctionalScopeRetryScenario,
) -> FunctionalScopeRetryProductionOutcome:
    fixture = _fixture(
        scenario.scope_profile,
        scenario.repair_mode == "no_progress",
    )
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    source = (
        fixture.failed_payload
        if scenario.repair_mode == "no_progress"
        else fixture.correct_payload
    )
    payload = _scope_repair_payload(source, authority.editable_scope_refs)
    base_plan = fixture.failed_plan
    mode = scenario.repair_mode
    if mode == "stale_plan":
        base_plan = replace(
            fixture.failed_plan,
            root_scope=replace(fixture.failed_plan.root_scope, children=()),
        )
    elif mode == "missing_scope":
        payload["scope_replacements"].clear()
    elif mode == "foreign_scope":
        payload["scope_replacements"]["problem"] = {
            "scope_steps": [],
            "goals": {},
        }
    elif mode == "missing_goal":
        _first_replacement(payload)["goals"].clear()
    elif mode == "foreign_goal":
        replacement = _first_replacement(payload)
        replacement["goals"]["ii.foreign"] = deepcopy(
            next(iter(replacement["goals"].values()))
        )
    elif mode == "invalid_answer":
        goal = next(iter(_first_replacement(payload)["goals"].values()))
        answer = goal["answer_from"]
        producer = next(
            item
            for item in goal["steps"]
            if item["step_id"] == answer["step_id"]
        )
        alternative = deepcopy(producer)
        alternative["step_id"] = (
            f"{producer['step_id']}_alternative_{scenario.variant}"
        )
        goal["steps"].append(alternative)
        answer["step_id"] = "missing_answer_producer"

    payload = _reorder_mappings(
        payload,
        reverse=scenario.reverse_mapping_order,
        rotation=scenario.variant + scenario.retry_round,
    )
    original = fixture.failed_plan.to_payload()
    error_code: str | None = None
    application = None
    try:
        application = FunctionalScopeRepairCompiler().apply_json(
            json.dumps(payload, ensure_ascii=False),
            base_plan=base_plan,
            authority=authority,
            capability_catalog=fixture.capability_catalog,
        )
    except FunctionalScopeRetryError as exc:
        error_code = exc.code

    no_progress = bool(
        application is not None
        and application.plan_hash == authority.base_plan_hash
    )
    restored_call_count = 0
    open_scope_restore_leak_count = 0
    if application is not None:
        seed = build_scope_retry_restore_seed(
            authority,
            fixture.execution,
            next_plan=application.plan,
        )
        restored_call_count = len(seed.call_ids)
        open_scope_call_ids = _scope_call_ids(
            fixture.failed_payload,
            authority.editable_scope_refs,
        )
        open_scope_restore_leak_count = len(
            set(seed.call_ids).intersection(open_scope_call_ids)
        )
    accepted = application is not None and not no_progress
    return FunctionalScopeRetryProductionOutcome(
        accepted=accepted,
        error_code=error_code,
        no_progress=no_progress,
        failed_candidate_ghost_write_count=(
            0 if fixture.failed_plan.to_payload() == original else 1
        ),
        open_scope_restore_leak_count=open_scope_restore_leak_count,
        restored_call_count=restored_call_count,
    )


def _scope_repair_payload(
    plan_payload: dict[str, Any],
    scope_refs: tuple[str, ...],
) -> dict[str, Any]:
    scopes = {
        scope["scope_ref"]: scope
        for scope in iter_scopes(plan_payload["root_scope"])
    }

    def authored_step(step: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(step)
        value.pop("execution", None)
        value.pop("return_expectations", None)
        return value

    return {
        "schema_version": "functional-scope-repair/v1",
        "scope_replacements": {
            scope_ref: {
                "scope_steps": [
                    authored_step(item)
                    for item in scopes[scope_ref].get("steps", ())
                ],
                "goals": {
                    goal["goal_ref"]: {
                        "steps": [
                            authored_step(item)
                            for item in goal.get("steps", ())
                        ],
                        "answer_from": deepcopy(goal["answer_from"]),
                    }
                    for goal in scopes[scope_ref].get("goals", ())
                },
            }
            for scope_ref in scope_refs
        },
    }


def _first_replacement(payload: dict[str, Any]) -> dict[str, Any]:
    return next(iter(payload["scope_replacements"].values()))


def _scope_call_ids(
    payload: dict[str, Any],
    scope_refs: tuple[str, ...],
) -> set[str]:
    result: set[str] = set()
    for scope in iter_scopes(payload["root_scope"]):
        if scope["scope_ref"] not in scope_refs:
            continue
        result.update(item["step_id"] for item in scope.get("steps", ()))
        for goal in scope.get("goals", ()):
            result.update(item["step_id"] for item in goal.get("steps", ()))
    return result


def _reorder_mappings(value: Any, *, reverse: bool, rotation: int) -> Any:
    if isinstance(value, dict):
        items = [
            (
                key,
                _reorder_mappings(item, reverse=reverse, rotation=rotation),
            )
            for key, item in value.items()
        ]
        if items:
            offset = rotation % len(items)
            items = items[offset:] + items[:offset]
        if reverse:
            items.reverse()
        return dict(items)
    if isinstance(value, list):
        return [
            _reorder_mappings(item, reverse=reverse, rotation=rotation)
            for item in value
        ]
    return value
