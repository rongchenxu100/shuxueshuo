"""Production adapters for the scope-native Goal replacement gate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    FunctionalGoalRepairService,
    FunctionalGoalRetryError,
    ScopedFunctionalGoalRetryRunResult,
    ScopedFunctionalGoalRetryService,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlan,
    ScopedFunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime import (
    functional_transaction_execution as transaction_module,
)
from support.scope_native_c0_c5_oracle import (
    ScopeNativeC5RetryScenario,
    ScopeNativeRetryScenario,
)

from _functional_goal_retry_support import (
    GoalRetryFixture,
    goal,
    goal_retry_fixture,
    published_goal_retry_fixture,
)
from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


@dataclass(frozen=True)
class ScopeNativeRetryProductionOutcome:
    accepted: bool
    error_code: str | None
    no_progress: bool
    solved_goal_reexecution_count: int
    failed_transaction_ghost_write_count: int
    restored_call_count: int


@dataclass(frozen=True)
class ScopeNativeC5ProductionOutcome:
    initial_failure_code: str
    diagnostic_in_retry_prompt: bool
    accepted: bool
    repair_error_code: str | None
    remaining_free: tuple[str, ...]
    equation_sources: tuple[str, ...]
    solved_goal_reexecution_count: int
    failed_transaction_ghost_write_count: int


@dataclass(frozen=True)
class _C5Fixture:
    authority_fixture: tuple[Any, ...]
    correct_payload: dict[str, Any]
    plan: ScopedFunctionalPlan

    @property
    def planning_context(self):
        return self.authority_fixture[1]

    @property
    def problem(self):
        return self.authority_fixture[2]

    @property
    def inputs(self):
        return self.authority_fixture[3]

    @property
    def problem_payload(self):
        return self.authority_fixture[4]

    @property
    def handle_registry(self):
        return self.authority_fixture[5]

    @property
    def planner_state_context(self):
        return self.authority_fixture[6]

    @property
    def binding_catalog(self):
        return self.authority_fixture[7]


_FIXTURE_ROOTS: list[TemporaryDirectory[str]] = []


@lru_cache(maxsize=None)
def _cached_fixture(profile: str) -> GoalRetryFixture:
    root = TemporaryDirectory(prefix=f"scope-native-retry-{profile}-")
    _FIXTURE_ROOTS.append(root)
    factory = (
        goal_retry_fixture
        if profile == "failed_goal"
        else published_goal_retry_fixture
    )
    return factory(Path(root.name))


@lru_cache(maxsize=1)
def _cached_c5_fixture() -> _C5Fixture:
    case = "tj-2026-heping-ermo-25"
    root = TemporaryDirectory(prefix="scope-native-c5-")
    _FIXTURE_ROOTS.append(root)
    authority_fixture = planning_binding_fixture(Path(root.name), case=case)
    payload = load_v2_fixture_payload(case)
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    if plan is None or not report.ok:
        raise AssertionError(report.to_payload())
    return _C5Fixture(authority_fixture, payload, plan)


def run_scope_native_goal_retry_adapter(
    scenario: ScopeNativeRetryScenario,
) -> ScopeNativeRetryProductionOutcome:
    """Exercise repair/v4 against a real authenticated Goal authority."""

    fixture = _cached_fixture(scenario.fixture_profile)
    payload = _repair_payload(fixture, scenario=scenario)
    if scenario.repair_mode in {"valid", "no_progress"}:
        return _run_lifecycle(fixture, scenario=scenario, repair_payload=payload)

    original = fixture.failed_plan.to_payload()
    error_code: str | None = None
    try:
        FunctionalGoalRepairService().apply_json(
            json.dumps(payload, ensure_ascii=False),
            base_plan=fixture.failed_plan,
            authority=fixture.retry_authority,
            capability_catalog=fixture.capability_catalog,
        )
    except FunctionalGoalRetryError as exc:
        error_code = exc.code
    return ScopeNativeRetryProductionOutcome(
        accepted=False,
        error_code=error_code,
        no_progress=False,
        solved_goal_reexecution_count=0,
        failed_transaction_ghost_write_count=(
            0 if fixture.failed_plan.to_payload() == original else 1
        ),
        restored_call_count=0,
    )


def run_scope_native_c5_retry_adapter(
    scenario: ScopeNativeC5RetryScenario,
) -> ScopeNativeC5ProductionOutcome:
    """Inject one typed closure failure, then run real Goal replacement."""

    fixture = _cached_c5_fixture()
    runtime_context = ContextBuilder().build(fixture.problem)
    initial_scopes = deepcopy(runtime_context.scopes)
    original_execute = transaction_module.execute_symbolic_closure
    injected = False

    def injected_execute(*args: Any, **kwargs: Any):
        nonlocal injected
        result = original_execute(*args, **kwargs)
        target_id = result.target_object_id
        if (
            injected
            or result.status != "unique"
            or target_id is None
            or not target_id.value.endswith(":c")
        ):
            return result
        injected = True
        build = result.validation_build
        if build is not None:
            build = replace(
                build,
                equation_sources=(
                    ("expression", "condition")
                    if scenario.expose_equation_sources
                    else ()
                ),
            )
        residual_symbols = (
            (result.target,)
            if scenario.expose_residual_symbol and result.target is not None
            else ()
        )
        residual_ids = (
            (target_id,) if scenario.expose_residual_symbol else ()
        )
        return replace(
            result,
            status=scenario.closure_failure,
            target_value=None,
            substitutions=(),
            residual_symbols=residual_symbols,
            residual_symbol_ids=residual_ids,
            branch_count=(2 if scenario.closure_failure == "ambiguous" else 0),
            provenance=None,
            validation_context_attached=False,
            validation_build=build,
        )

    transaction_module.execute_symbolic_closure = injected_execute
    try:
        client = _ScriptedC5RetryClient(fixture, scenario=scenario)
        result = ScopedFunctionalGoalRetryService(client).run(
            inputs=fixture.inputs,
            planning_context=fixture.planning_context,
            problem_binding_catalog=fixture.binding_catalog,
            handle_registry=fixture.handle_registry,
            runtime_context=runtime_context,
            planner_state_context=fixture.planner_state_context,
            problem_payload=fixture.problem_payload,
            max_attempts=2,
        )
    finally:
        transaction_module.execute_symbolic_closure = original_execute

    diagnostic = _initial_closure_diagnostic(result)
    observed = dict(diagnostic.get("observed") or {})
    repair_error_code = next(
        (
            attempt.error.code
            for attempt in reversed(result.attempts)
            if attempt.error is not None
        ),
        None,
    )
    return ScopeNativeC5ProductionOutcome(
        initial_failure_code=str(diagnostic.get("code") or ""),
        diagnostic_in_retry_prompt=(
            len(result.attempts) >= 2
            and _payload_contains(
                result.attempts[1].payload,
                key="code",
                expected=str(diagnostic.get("code") or ""),
            )
        ),
        accepted=result.status == "accepted",
        repair_error_code=repair_error_code,
        remaining_free=tuple(observed.get("remaining_free", ())),
        equation_sources=tuple(observed.get("equation_sources", ())),
        solved_goal_reexecution_count=_solved_goal_reexecution_count(result),
        failed_transaction_ghost_write_count=(
            0 if runtime_context.scopes == initial_scopes else 1
        ),
    )


class _ScriptedC5RetryClient:
    def __init__(
        self,
        fixture: _C5Fixture,
        *,
        scenario: ScopeNativeC5RetryScenario,
    ) -> None:
        self.fixture = fixture
        self.scenario = scenario

    def complete(self, request: Mapping[str, Any]) -> str:
        if request["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
            frame = FunctionalPlanAuthorityFrame.from_planning_context(
                self.fixture.planning_context
            )
            content = functional_plan_content_from_plan(
                self.fixture.plan,
                frame=frame,
            )
            return json.dumps(content.to_payload(), ensure_ascii=False)
        retry = request["planner_payload"]["goal_retry_context"]
        goal_ref = "ii.E"
        goal_payload = goal(self.fixture.correct_payload, goal_ref)
        payload = {
            "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
            "base_plan_id": (
                "plan:stale"
                if self.scenario.repair_mode == "stale_plan"
                else retry["base_plan_id"]
            ),
            "base_retry_context_id": retry["base_retry_context_id"],
            "goal_replacements": {
                goal_ref: {
                    "steps": deepcopy(goal_payload["steps"]),
                    "answer_from": deepcopy(goal_payload["answer_from"]),
                }
            },
            "scope_step_replacements": {},
        }
        payload = _reorder_payload(
            payload,
            reverse=self.scenario.reverse_mapping_order,
            rotation=self.scenario.variant,
        )
        return json.dumps(payload, ensure_ascii=False)


def _initial_closure_diagnostic(
    result: ScopedFunctionalGoalRetryRunResult,
) -> Mapping[str, Any]:
    if not result.attempts or result.attempts[0].execution is None:
        return {}
    checkpoint = result.attempts[0].execution.checkpoint
    if checkpoint is None:
        return {}

    def visit(scope: Any):
        yield from scope.scope_steps
        for goal_item in scope.goals:
            yield from goal_item.steps
        for child in scope.children:
            yield from visit(child)

    return next(
        (
            dict(item.typed_issue)
            for item in visit(checkpoint.root_scope)
            if item.step_id == "solve_parameter_c_ii"
            and item.typed_issue is not None
        ),
        {},
    )


def _payload_contains(value: Any, *, key: str, expected: str) -> bool:
    if isinstance(value, Mapping):
        if str(value.get(key, "")) == expected:
            return True
        return any(
            _payload_contains(item, key=key, expected=expected)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(
            _payload_contains(item, key=key, expected=expected)
            for item in value
        )
    return False


def _repair_payload(
    fixture: GoalRetryFixture,
    *,
    scenario: ScopeNativeRetryScenario,
) -> dict[str, Any]:
    authority = fixture.retry_authority
    replacements: dict[str, Any] = {}
    source_payload = (
        fixture.failed_payload
        if scenario.repair_mode == "no_progress"
        else fixture.correct_payload
    )
    for goal_ref in authority.editable_goal_refs:
        goal_payload = goal(source_payload, goal_ref)
        replacements[goal_ref] = {
            "steps": deepcopy(goal_payload.get("steps", [])),
            "answer_from": deepcopy(goal_payload["answer_from"]),
        }

    scope_replacements: dict[str, Any] = {
        scope_ref: {"steps": []}
        for scope_ref in authority.editable_scope_refs
    }
    payload: dict[str, Any] = {
        "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
        "base_plan_id": authority.base_plan_id,
        "base_retry_context_id": authority.retry_context_id,
        "goal_replacements": replacements,
        "scope_step_replacements": scope_replacements,
    }
    mode = scenario.repair_mode
    if mode == "stale_plan":
        payload["base_plan_id"] = "plan:stale"
    elif mode == "stale_context":
        payload["base_retry_context_id"] = "retry-context:stale"
    elif mode == "missing_editable_goal":
        foreign = authority.solved_goal_refs[0]
        foreign_payload = goal(fixture.correct_payload, foreign)
        payload["goal_replacements"] = {
            foreign: {
                "steps": deepcopy(foreign_payload.get("steps", [])),
                "answer_from": deepcopy(foreign_payload["answer_from"]),
            }
        }
    elif mode == "foreign_goal":
        foreign = authority.solved_goal_refs[0]
        foreign_payload = goal(fixture.correct_payload, foreign)
        payload["goal_replacements"][foreign] = {
            "steps": deepcopy(foreign_payload.get("steps", [])),
            "answer_from": deepcopy(foreign_payload["answer_from"]),
        }
    elif mode == "foreign_scope":
        replacement = deepcopy(next(iter(replacements.values()))["steps"][0])
        payload["scope_step_replacements"]["problem"] = {
            "steps": [replacement],
        }
    elif mode == "invalid_answer":
        editable = authority.editable_goal_refs[0]
        replacement = payload["goal_replacements"][editable]
        answer = replacement["answer_from"]
        producer = next(
            item
            for item in replacement["steps"]
            if item["step_id"] == answer["step_id"]
        )
        duplicate = deepcopy(producer)
        duplicate["step_id"] = (
            f"{producer['step_id']}_gate_alternative_{scenario.variant}"
        )
        replacement["steps"].append(duplicate)
        replacement["answer_from"] = {
            "step_id": "missing_answer_producer",
            "return": answer["return"],
        }

    return _reorder_payload(
        payload,
        reverse=scenario.reverse_mapping_order,
        rotation=(scenario.variant + scenario.retry_round) % 7,
    )


def _reorder_payload(
    value: Any,
    *,
    reverse: bool,
    rotation: int,
) -> Any:
    """Vary wire order without changing repair semantics."""

    if isinstance(value, dict):
        items = [
            (
                key,
                _reorder_payload(
                    item,
                    reverse=reverse,
                    rotation=rotation,
                ),
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
            _reorder_payload(
                item,
                reverse=reverse,
                rotation=rotation,
            )
            for item in value
        ]
    return value


class _ScriptedGoalRetryClient:
    def __init__(
        self,
        fixture: GoalRetryFixture,
        repair_payload: Mapping[str, Any],
    ) -> None:
        self.fixture = fixture
        self.repair_payload = deepcopy(dict(repair_payload))

    def complete(self, request: Mapping[str, Any]) -> str:
        protocol = request["planner_protocol"]
        if protocol == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
            frame = FunctionalPlanAuthorityFrame.from_planning_context(
                self.fixture.planning_context
            )
            content = functional_plan_content_from_plan(
                self.fixture.failed_plan,
                frame=frame,
            )
            return json.dumps(content.to_payload(), ensure_ascii=False)
        if protocol != FUNCTIONAL_GOAL_REPAIR_CONTRACT:
            raise AssertionError(f"unexpected Planner protocol {protocol!r}")
        retry = request["planner_payload"]["goal_retry_context"]
        payload = deepcopy(self.repair_payload)
        payload["base_plan_id"] = retry["base_plan_id"]
        payload["base_retry_context_id"] = retry["base_retry_context_id"]
        return json.dumps(payload, ensure_ascii=False)


def _run_lifecycle(
    fixture: GoalRetryFixture,
    *,
    scenario: ScopeNativeRetryScenario,
    repair_payload: Mapping[str, Any],
) -> ScopeNativeRetryProductionOutcome:
    runtime_context = ContextBuilder().build(fixture.problem)
    initial_scopes = deepcopy(runtime_context.scopes)
    result = ScopedFunctionalGoalRetryService(
        _ScriptedGoalRetryClient(fixture, repair_payload)
    ).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=runtime_context,
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=max(2, scenario.retry_round + 1),
    )
    error_code = next(
        (
            attempt.error.code
            for attempt in reversed(result.attempts)
            if attempt.error is not None
        ),
        None,
    )
    return ScopeNativeRetryProductionOutcome(
        accepted=result.status == "accepted",
        error_code=error_code,
        no_progress=result.no_progress,
        solved_goal_reexecution_count=_solved_goal_reexecution_count(result),
        failed_transaction_ghost_write_count=(
            0 if runtime_context.scopes == initial_scopes else 1
        ),
        restored_call_count=result.solved_goal_restore_count,
    )


def _solved_goal_reexecution_count(
    result: ScopedFunctionalGoalRetryRunResult,
) -> int:
    count = 0
    for attempt in result.attempts:
        if attempt.retry_authority is None or attempt.execution is None:
            continue
        solved_calls = {
            call_id
            for goal_authority in attempt.retry_authority.goal_authorities.values()
            if goal_authority.status == "solved"
            for call_id in goal_authority.closure_step_ids
        }
        transaction = (
            attempt.execution.replay.transactional_attempt_result
            if attempt.execution.replay is not None
            else None
        )
        if transaction is None:
            continue
        running = {
            event.call_id
            for event in transaction.execution_report.events
            if event.event == "running"
        }
        count += len(solved_calls.intersection(running))
    return count
