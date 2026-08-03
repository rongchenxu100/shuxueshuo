"""Shared Functional retry-state projection helpers."""

from __future__ import annotations

from collections.abc import Sequence

from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    PlannerRetryPreservePolicy,
)


NON_PREFIX_PRESERVING_LAYERS = frozenset(
    {"semantic_reads", "validation", "normalization", "answer_check"}
)


def repair_suffix_start_from_issues(
    issues: Sequence[PlannerRetryIssue],
) -> dict[str, str | None] | None:
    """Return the first issue location that can anchor suffix repair."""
    for issue in issues:
        if issue.step_id or issue.scope_id:
            return {"step_id": issue.step_id, "scope_id": issue.scope_id}
    return None


def with_preserve_policy(
    issue: PlannerRetryIssue,
    preserve_policy: PlannerRetryPreservePolicy,
) -> PlannerRetryIssue:
    """Apply a global preserve policy unless the layer is schema-local."""
    if issue.layer in NON_PREFIX_PRESERVING_LAYERS:
        return issue
    return PlannerRetryIssue(
        layer=issue.layer,
        code=issue.code,
        step_id=issue.step_id,
        scope_id=issue.scope_id,
        repair_target=issue.repair_target,
        preserve_policy=preserve_policy,
        message=issue.message,
        hints=issue.hints,
        related_handles=issue.related_handles,
        details=issue.details,
    )


__all__ = [
    "NON_PREFIX_PRESERVING_LAYERS",
    "repair_suffix_start_from_issues",
    "with_preserve_policy",
]
