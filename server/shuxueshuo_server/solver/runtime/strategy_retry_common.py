"""Shared retry-state projection helpers.

Both the legacy replay builder and PlannerStateContext projector produce
``PlannerRetryState``. Keep policy-sensitive text and preserve semantics here so
the two paths cannot drift.
"""

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


def retry_instruction(
    *,
    issues: Sequence[PlannerRetryIssue],
    recovered_issues: Sequence[PlannerRetryIssue],
    preserve_policy: PlannerRetryPreservePolicy,
    has_stable_prefix: bool,
) -> str:
    """Build the LLM-facing retry instruction from canonical retry fields."""
    parts = [
        "请优先阅读 latest_retry_state；以 baseline_draft 为修复基线，仍输出完整 StepIntent JSON。",
    ]
    if has_stable_prefix and preserve_policy == "preserve_prefix":
        parts.append(
            "保留 stable_prefix 中已通过 deterministic replay 的步骤语义，只修复 "
            "repair_suffix_start 及其后续步骤。"
        )
    else:
        parts.append("本轮不冻结 stable prefix；可以调整 baseline_draft 中与 issues 相关的步骤。")
    first = issues[0] if issues else None
    if first is not None:
        location = f" step={first.step_id}" if first.step_id else ""
        parts.append(
            f"首要问题 layer={first.layer}, code={first.code}{location}。"
        )
    if recovered_issues:
        parts.append(
            "recovered_issues 记录的是代码已接管的问题，不要把它们作为主修复目标。"
        )
    return " ".join(parts)


__all__ = [
    "NON_PREFIX_PRESERVING_LAYERS",
    "repair_suffix_start_from_issues",
    "retry_instruction",
    "with_preserve_policy",
]
