"""Project Functional PlannerStateContext retry memory into PlannerRetryState."""

from __future__ import annotations

from typing import Any, cast, get_args

from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryGraphCheckpoint,
)
from shuxueshuo_server.solver.runtime.functional_plan_retry import (
    functional_repair_instruction,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    PlannerRetryLayer,
    PlannerRetryPreservePolicy,
    PlannerRetryState,
)
from shuxueshuo_server.solver.runtime.strategy_retry_common import (
    repair_suffix_start_from_issues,
    with_preserve_policy,
)


_RETRY_LAYERS = frozenset(get_args(PlannerRetryLayer))
_PRESERVE_POLICIES = frozenset(get_args(PlannerRetryPreservePolicy))


class PlannerRetryStateProjector:
    """Build the LLM-facing retry state from a PlannerStateContext snapshot."""

    @classmethod
    def from_context(
        cls,
        context: PlannerStateContext,
    ) -> PlannerRetryState | None:
        memory = context.state.retry_memory
        issue_payloads = memory.issues or context.state.issues
        raw_issues = tuple(
            issue
            for payload in issue_payloads
            if (issue := _issue_from_payload(payload)) is not None
        )
        raw_recovered_issues = tuple(
            issue
            for payload in memory.recovered_issues
            if (issue := _issue_from_payload(payload)) is not None
        )
        if not raw_issues:
            return None

        primary_blocker = _primary_blocker(memory.replay_reports)
        repair_suffix_start = (
            memory.repair_suffix_start
            or _blocker_repair_suffix_start(primary_blocker)
            or repair_suffix_start_from_issues(raw_issues)
        )
        issues, recovered_issues = _active_and_recovered_issues(
            raw_issues,
            raw_recovered_issues,
            repair_suffix_start=repair_suffix_start,
            primary_blocker=primary_blocker,
        )
        if not issues:
            return None
        has_goal_verification = any(
            issue.layer == "goal_verification" for issue in issues
        )
        has_answer_check = (
            any(issue.layer == "answer_check" for issue in issues)
            and not has_goal_verification
        )
        committed_calls = _typed_committed_candidate_calls(
            memory.functional_retry_graph_checkpoint,
            memory.committed_candidate_calls or memory.stable_candidate_calls,
        )
        preserve_policy: PlannerRetryPreservePolicy = (
            "preserve_graph"
            if committed_calls and not has_answer_check
            else "none"
        )
        issues = tuple(with_preserve_policy(issue, preserve_policy) for issue in issues)
        recovered_issues = tuple(
            with_preserve_policy(issue, preserve_policy)
            for issue in recovered_issues
        )
        return PlannerRetryState(
            attempt=memory.attempt,
            repair_suffix_start=repair_suffix_start,
            issues=issues,
            recovered_issues=recovered_issues,
            preserve_policy=preserve_policy,
            repair_instruction=functional_repair_instruction(
                stable_candidate_calls=committed_calls,
                repair_call_ids=memory.repair_call_ids,
                issue_count=len(issues),
            ),
            replay_depth=memory.replay_depth,
            selected_repair_layer=issues[0].layer,
            replay_timeline=memory.replay_timeline,
            replay_reports=memory.replay_reports or {},
            source_context_id=context.manifest.context_id,
            baseline_candidate=memory.baseline_candidate,
            stable_candidate_calls=committed_calls,
            committed_candidate_calls=committed_calls,
            runtime_verified_calls=memory.runtime_verified_calls,
            validated_call_ids=memory.validated_call_ids,
            call_memory=memory.call_memory,
            repair_call_ids=memory.repair_call_ids,
            functional_retry_graph_checkpoint=(
                memory.functional_retry_graph_checkpoint
            ),
        )


def _typed_committed_candidate_calls(
    checkpoint_payload: dict[str, Any] | None,
    candidate_calls: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    del candidate_calls
    if checkpoint_payload is None:
        return ()
    checkpoint = FunctionalRetryGraphCheckpoint.from_payload(
        checkpoint_payload
    )
    return tuple(
        {
            "scope_id": committed.declared_scope_id,
            "call": dict(committed.call_payload),
        }
        for committed in checkpoint.committed_calls
    )


def _issue_from_payload(payload: dict[str, Any]) -> PlannerRetryIssue | None:
    layer = _retry_layer(payload.get("layer"))
    code = payload.get("code")
    if layer is None or not isinstance(code, str) or not code:
        return None
    preserve_policy = _preserve_policy(
        payload.get("preserve_policy"),
        default="preserve_prefix",
    )
    return PlannerRetryIssue(
        layer=layer,
        code=code,
        step_id=_optional_string(payload.get("step_id")),
        scope_id=_optional_string(payload.get("scope_id")),
        repair_target=str(payload.get("repair_target") or "suffix"),
        preserve_policy=preserve_policy,
        message=str(payload.get("message") or ""),
        hints=_string_tuple(payload.get("hints")),
        related_handles=_string_tuple(payload.get("related_handles")),
        details=(
            dict(payload["details"])
            if isinstance(payload.get("details"), dict)
            else None
        ),
    )


def _retry_layer(value: object) -> PlannerRetryLayer | None:
    if isinstance(value, str) and value in _RETRY_LAYERS:
        return cast(PlannerRetryLayer, value)
    return None


def _preserve_policy(
    value: object,
    *,
    default: PlannerRetryPreservePolicy,
) -> PlannerRetryPreservePolicy:
    if isinstance(value, str) and value in _PRESERVE_POLICIES:
        return cast(PlannerRetryPreservePolicy, value)
    return default


def _active_and_recovered_issues(
    issues: tuple[PlannerRetryIssue, ...],
    recovered_issues: tuple[PlannerRetryIssue, ...],
    *,
    repair_suffix_start: dict[str, Any] | None,
    primary_blocker: dict[str, Any] | None,
) -> tuple[tuple[PlannerRetryIssue, ...], tuple[PlannerRetryIssue, ...]]:
    repair_key = _step_key_from_payload(repair_suffix_start)
    active = list(issues)
    recovered = list(recovered_issues)
    active.sort(
        key=lambda issue: _issue_sort_key(
            issue,
            repair_key=repair_key,
            primary_blocker=primary_blocker,
        )
    )
    return tuple(active), tuple(_unique_issues(recovered))


def _issue_sort_key(
    issue: PlannerRetryIssue,
    *,
    repair_key: tuple[str | None, str | None] | None,
    primary_blocker: dict[str, Any] | None,
) -> tuple[int, int, int]:
    blocker_key = _step_key_from_payload(primary_blocker)
    issue_key = _step_key(issue.step_id, issue.scope_id)
    if blocker_key is not None and issue_key == blocker_key:
        blocker_rank = 0
    elif repair_key is not None and issue_key == repair_key:
        blocker_rank = 1
    else:
        blocker_rank = 2
    return (
        blocker_rank,
        _LAYER_PRIORITY.get(issue.layer, 99),
        _BLOCKER_CODE_PRIORITY.get(issue.code, 50),
    )


def _unique_issues(
    issues: list[PlannerRetryIssue],
) -> tuple[PlannerRetryIssue, ...]:
    result: list[PlannerRetryIssue] = []
    seen: set[tuple[Any, ...]] = set()
    for issue in issues:
        key = (
            issue.layer,
            issue.code,
            issue.step_id,
            issue.scope_id,
            issue.message,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return tuple(result)


def _primary_blocker(
    replay_reports: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(replay_reports, dict):
        return None
    trial = replay_reports.get("trial_execution")
    if not isinstance(trial, dict):
        return None
    blockers = trial.get("blockers")
    if isinstance(blockers, list):
        for item in blockers:
            if isinstance(item, dict):
                return item
    return None


def _blocker_repair_suffix_start(
    blocker: dict[str, Any] | None,
) -> dict[str, str | None] | None:
    if not isinstance(blocker, dict):
        return None
    step_id = _optional_string(blocker.get("step_id"))
    scope_id = _optional_string(blocker.get("scope_id"))
    if step_id or scope_id:
        return {"step_id": step_id, "scope_id": scope_id}
    return None


def _step_key_from_payload(
    payload: dict[str, Any] | None,
) -> tuple[str | None, str | None] | None:
    if not isinstance(payload, dict):
        return None
    return _step_key(
        _optional_string(payload.get("step_id")),
        _optional_string(payload.get("scope_id")),
    )


def _step_key(
    step_id: str | None,
    scope_id: str | None,
) -> tuple[str | None, str | None] | None:
    if step_id is None and scope_id is None:
        return None
    return (step_id, scope_id)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


_LAYER_PRIORITY = {
    "semantic_reads": 0,
    "handle_resolution": 1,
    "validation": 2,
    "normalization": 3,
    "candidate_resolution": 4,
    "trial_execution": 5,
    "goal_verification": 6,
    "answer_check": 7,
}
_BLOCKER_CODE_PRIORITY = {
    "recipe_trial_step_failed": 0,
    "no_executable_candidate": 1,
}


__all__ = ["PlannerRetryStateProjector"]
