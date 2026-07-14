"""Planner retry state and issue collection.

This module converts validation, candidate-resolution, trial-execution, and
answer-check reports into the LLM-facing ``PlannerRetryState``. Replay pipeline
and draft merge/raw payload repair live in sibling modules; compatibility exports
are resolved lazily to keep old import paths working without import cycles.
"""

from __future__ import annotations

import importlib
import re
from typing import Any

from shuxueshuo_server.solver.runtime.strategy_repair_feedback import (
    RepairHintRegistry,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.strategy_compressed_steps import (
    compressed_step_retry_issue,
    find_step,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ExecutablePlanResolutionReport,
    PlannerReplayDepth,
    PlannerRetryIssue,
    PlannerRetryState,
    RecipeAlignmentReport,
    StepIntentDraft,
    StepIntentExecutionDiagnostic,
    StepIntentNormalizationReport,
    StepIntentValidationReport,
)
from shuxueshuo_server.solver.runtime.strategy_retry_common import (
    repair_suffix_start_from_issues,
    retry_instruction,
    with_preserve_policy,
)
from shuxueshuo_server.solver.runtime.strategy_repair_guidance import (
    RepairGuidanceResolver,
)


def build_planner_retry_state(
    *,
    attempt: int,
    errors: tuple[str, ...],
    effective_draft: StepIntentDraft | None = None,
    normalized_draft: StepIntentDraft | None = None,
    validation_report: StepIntentValidationReport | None = None,
    normalization_report: StepIntentNormalizationReport | None = None,
    normalization_errors: tuple[str, ...] = (),
    resolution_report: ExecutablePlanResolutionReport | None = None,
    diagnostic: StepIntentExecutionDiagnostic | None = None,
    handle_registry: CanonicalHandleRegistry | None = None,
    goal_verification_issues: tuple[PlannerRetryIssue, ...] = (),
    guidance_resolver: RepairGuidanceResolver | None = None,
) -> PlannerRetryState | None:
    """根据现有 replay artifacts 构造正式 retry state。"""
    issues = _issues_from_reports(
        errors=errors,
        validation_report=validation_report,
        normalization_errors=normalization_errors,
        resolution_report=resolution_report,
        diagnostic=diagnostic,
        draft=effective_draft or normalized_draft,
        handle_registry=handle_registry,
        goal_verification_issues=goal_verification_issues,
        guidance_resolver=guidance_resolver,
    )
    recovered_issues = _recovered_issues_from_reports(
        validation_report=validation_report,
        normalization_report=normalization_report,
    )
    if not issues and (diagnostic is None or diagnostic.ok):
        return None

    has_goal_verification = any(
        issue.layer == "goal_verification" for issue in issues
    )
    has_answer_check = (
        any(issue.layer == "answer_check" for issue in issues)
        and not has_goal_verification
    )
    stable_prefix = (
        ()
        if has_answer_check
        else _stable_prefix_for_issues(diagnostic, issues)
    )
    preserve_policy = "none" if has_answer_check else (
        "preserve_prefix" if stable_prefix else "none"
    )
    baseline_draft = _baseline_payload(
        effective_draft=effective_draft,
        normalized_draft=normalized_draft,
        validation_report=validation_report,
    )
    state = PlannerRetryState(
        attempt=attempt,
        baseline_draft=baseline_draft,
        stable_prefix=stable_prefix,
        repair_suffix_start=_repair_suffix_start(issues, diagnostic),
        issues=tuple(
            with_preserve_policy(issue, preserve_policy)
            for issue in issues
        ),
        recovered_issues=tuple(recovered_issues),
        preserve_policy=preserve_policy,
        repair_instruction=retry_instruction(
            issues=issues,
            recovered_issues=recovered_issues,
            preserve_policy=preserve_policy,
            has_stable_prefix=bool(stable_prefix),
        ),
        replay_depth=_replay_depth(
            issues=issues,
            validation_report=validation_report,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            diagnostic=diagnostic,
        ),
        selected_repair_layer=issues[0].layer if issues else None,
        replay_timeline=_replay_timeline(
            validation_report=validation_report,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            diagnostic=diagnostic,
            issues=issues,
            recovered_issues=recovered_issues,
        ),
        replay_reports=_replay_reports(
            validation_report=validation_report,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            diagnostic=diagnostic,
        ),
    )
    return state

def retry_state_from_attempt(item: dict[str, Any]) -> dict[str, Any] | None:
    """从 previous attempt payload 中读取 retry state。"""
    context_state = item.get("context_derived_retry_state")
    if isinstance(context_state, dict):
        return context_state
    state = item.get("planner_retry_state")
    return state if isinstance(state, dict) else None

def _issues_from_reports(
    *,
    errors: tuple[str, ...],
    validation_report: StepIntentValidationReport | None,
    normalization_errors: tuple[str, ...],
    resolution_report: ExecutablePlanResolutionReport | None,
    diagnostic: StepIntentExecutionDiagnostic | None,
    draft: StepIntentDraft | None,
    handle_registry: CanonicalHandleRegistry | None,
    goal_verification_issues: tuple[PlannerRetryIssue, ...],
    guidance_resolver: RepairGuidanceResolver | None,
) -> list[PlannerRetryIssue]:
    issues: list[PlannerRetryIssue] = []
    issues.extend(_semantic_issues(validation_report))
    issues.extend(_validation_issues(validation_report))
    issues.extend(_normalization_issues(normalization_errors))
    if _has_blocking_failure(
        errors=errors,
        normalization_errors=normalization_errors,
        resolution_report=resolution_report,
        diagnostic=diagnostic,
    ):
        issues.extend(_capability_alignment_issues(validation_report))
        issues.extend(_strategy_route_issues(validation_report, resolution_report))
        issues.extend(
            _compressed_step_issues(
                draft=draft,
                resolution_report=resolution_report,
                diagnostic=diagnostic,
                handle_registry=handle_registry,
            )
        )
    issues.extend(_candidate_issues(resolution_report))
    issues.extend(
        _trial_issues(
            diagnostic,
            draft=draft,
            guidance_resolver=guidance_resolver,
        )
    )
    issues.extend(goal_verification_issues)
    issues.extend(_answer_check_issues(errors, diagnostic=diagnostic))
    if not issues:
        issues.extend(
            PlannerRetryIssue(
                layer="trial_execution",
                code=_code_from_message(error),
                repair_target="suffix",
                message=_safe_error_message(error),
            )
            for error in errors
        )
    return issues

def _capability_alignment_issues(
    validation_report: StepIntentValidationReport | None,
) -> list[PlannerRetryIssue]:
    """Turn method/recipe contract mismatches into explicit repair tickets."""
    alignment = (
        validation_report.recipe_alignment
        if validation_report is not None
        else None
    )
    if alignment is None or not alignment.capability_errors:
        return []
    issues: list[PlannerRetryIssue] = []
    for error in alignment.capability_errors:
        step_id = _optional_error_field(error, "step_id")
        recipe_hint = _optional_error_field(error, "recipe_hint")
        goal_type = _optional_error_field(error, "goal_type")
        original_code = _optional_error_field(error, "code") or "capability_error"
        message = _optional_error_field(error, "message") or original_code
        details = {
            key: value
            for key, value in {
                "original_code": original_code,
                "recipe_hint": recipe_hint,
                "goal_type": goal_type,
            }.items()
            if value is not None
        }
        issues.append(
            PlannerRetryIssue(
                layer="candidate_resolution",
                code="method_contract_mismatch",
                step_id=step_id,
                scope_id=None,
                repair_target="step",
                message=(
                    "selected method/recipe does not match this step's "
                    f"output contract: {message}"
                ),
                hints=(
                    "重新选择更合适的 catalog method/recipe，或把该 step 拆成可执行的中间 fact 与最终 answer 收集。",
                    "不要只改自然语言 strategy/reason；必须调整 recipe_hint、target、produces 或 dataflow。",
                    (
                        f"current_recipe_hint={recipe_hint}"
                        if recipe_hint is not None
                        else "current_recipe_hint=<missing>"
                    ),
                    (
                        f"current_goal_type={goal_type}"
                        if goal_type is not None
                        else "current_goal_type=<missing>"
                    ),
                ),
                details=details or None,
            )
        )
    return issues

def _compressed_step_issues(
    *,
    draft: StepIntentDraft | None,
    resolution_report: ExecutablePlanResolutionReport | None,
    diagnostic: StepIntentExecutionDiagnostic | None,
    handle_registry: CanonicalHandleRegistry | None,
) -> list[PlannerRetryIssue]:
    """把 over-compressed step 失败翻译成结构化 repair 工单。"""
    issues: list[PlannerRetryIssue] = []
    seen: set[tuple[str | None, str]] = set()
    if resolution_report is not None and not resolution_report.ok:
        for step_report in resolution_report.step_reports:
            if step_report.ok:
                continue
            step = find_step(draft, step_report.step_id)
            issue = compressed_step_retry_issue(
                step=step,
                layer="candidate_resolution",
                messages=step_report.errors,
                handle_registry=handle_registry,
            )
            if issue is not None:
                key = (issue.step_id, issue.layer)
                if key not in seen:
                    issues.append(issue)
                    seen.add(key)
    if diagnostic is not None and not diagnostic.ok:
        for blocker in diagnostic.blockers:
            step = find_step(draft, blocker.step_id)
            messages = (blocker.message, *blocker.capability_errors)
            issue = compressed_step_retry_issue(
                step=step,
                layer="candidate_resolution",
                messages=messages,
                handle_registry=handle_registry,
            )
            if issue is not None:
                key = (issue.step_id, issue.layer)
                if key not in seen:
                    issues.append(issue)
                    seen.add(key)
    return issues

def _has_blocking_failure(
    *,
    errors: tuple[str, ...],
    normalization_errors: tuple[str, ...],
    resolution_report: ExecutablePlanResolutionReport | None,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> bool:
    """只有本轮确实失败时，route warning 才能升级为 retry issue。"""
    return (
        bool(errors)
        or bool(normalization_errors)
        or (resolution_report is not None and not resolution_report.ok)
        or (diagnostic is not None and not diagnostic.ok)
    )

def _strategy_route_issues(
    validation_report: StepIntentValidationReport | None,
    resolution_report: ExecutablePlanResolutionReport | None,
) -> list[PlannerRetryIssue]:
    """把“已有 family preferred route 但 draft 绕路”提前成主修复目标。

    ``missing_preferred_recipe_ids`` 只说明 family 存在推荐路线，不能单独阻断
    open-world derivation。只有它和 null-hint utility、avoid pattern、capability
    error 或 candidate 失败同时出现时，才把问题归类为 route deviation。
    """
    if validation_report is None or not validation_report.ok:
        return []
    alignment = validation_report.recipe_alignment
    if alignment is None or not _has_family_route_coverage(alignment):
        return []
    signals = _route_deviation_signals(alignment, resolution_report)
    if not signals:
        return []
    step_id = _route_repair_step_id(alignment, resolution_report, signals)
    missing = tuple(alignment.missing_preferred_recipe_ids)
    return [
        PlannerRetryIssue(
            layer="candidate_resolution",
            code="strategy_route_deviation",
            step_id=step_id,
            scope_id=_scope_id_for_step(resolution_report, step_id),
            repair_target="suffix",
            message=(
                "Family preferred route is available, but the draft switches to "
                "unhinted utility/parameterized steps instead of the catalog route."
            ),
            hints=(
                "family_route_covered_by=" + ",".join(alignment.preferred_recipe_ids),
                "missing_preferred_recipes=" + ",".join(missing),
                (
                    "从该 step 开始改回 recipe_catalog 中的 preferred route；不要把 "
                    "family route 的内部代数参数化或中间 utility fact 展开成独立 step。"
                ),
                "route_deviation_signals=" + ",".join(signals),
            ),
        )
    ]

def _has_family_route_coverage(alignment: RecipeAlignmentReport) -> bool:
    """family route 覆盖的保守判据：family 显式声明 preferred recipes。"""
    return bool(alignment.preferred_recipe_ids and alignment.missing_preferred_recipe_ids)

def _route_deviation_signals(
    alignment: RecipeAlignmentReport,
    resolution_report: ExecutablePlanResolutionReport | None,
) -> tuple[str, ...]:
    signals: list[str] = []
    if alignment.avoid_pattern_hits:
        signals.append("avoid_pattern_hits")
    if alignment.capability_errors:
        signals.append("capability_errors")
    candidate_null_hint_failures = _null_hint_candidate_failures(
        alignment,
        resolution_report,
    )
    if candidate_null_hint_failures:
        signals.append("null_hint_candidate_failures")
    if alignment.null_hint_steps and (
        alignment.avoid_pattern_hits
        or alignment.capability_errors
        or candidate_null_hint_failures
    ):
        signals.append("null_hint_utility_steps")
    return tuple(dict.fromkeys(signals))

def _route_repair_step_id(
    alignment: RecipeAlignmentReport,
    resolution_report: ExecutablePlanResolutionReport | None,
    signals: tuple[str, ...],
) -> str | None:
    """优先定位到最早的 unhinted route drift，而不是后续局部无候选 step。"""
    del signals
    if alignment.null_hint_steps:
        return alignment.null_hint_steps[0]
    if alignment.avoid_pattern_hits:
        hit = alignment.avoid_pattern_hits[0]
        return hit.get("step_id")
    if alignment.capability_errors:
        error = alignment.capability_errors[0]
        return error.get("step_id")
    failures = _null_hint_candidate_failures(alignment, resolution_report)
    return failures[0] if failures else None

def _null_hint_candidate_failures(
    alignment: RecipeAlignmentReport,
    resolution_report: ExecutablePlanResolutionReport | None,
) -> tuple[str, ...]:
    if resolution_report is None:
        return ()
    null_hint_ids = set(alignment.null_hint_steps)
    return tuple(
        report.step_id
        for report in resolution_report.step_reports
        if report.step_id in null_hint_ids and report.errors
    )

def _scope_id_for_step(
    resolution_report: ExecutablePlanResolutionReport | None,
    step_id: str | None,
) -> str | None:
    if resolution_report is None or step_id is None:
        return None
    for report in resolution_report.step_reports:
        if report.step_id == step_id:
            return report.scope_id
    return None

def _optional_error_field(
    payload: dict[str, str],
    key: str,
) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None

def _semantic_issues(
    validation_report: StepIntentValidationReport | None,
) -> list[PlannerRetryIssue]:
    semantic = (
        validation_report.semantic_read_resolution
        if validation_report is not None
        else None
    )
    if semantic is None:
        return []
    return [
        PlannerRetryIssue(
            layer="semantic_reads",
            code=error.code,
            step_id=error.step_id,
            scope_id=error.scope_id,
            repair_target="semantic_reads",
            preserve_policy="none",
            message=error.message,
            hints=("保留 partially_resolved_payload 中已解析成功的 reads，只修复失败的 semantic_reads。",),
        )
        for error in semantic.errors
    ]

def _recovered_issues_from_reports(
    *,
    validation_report: StepIntentValidationReport | None,
    normalization_report: StepIntentNormalizationReport | None,
) -> list[PlannerRetryIssue]:
    """返回代码已确定性接管、不应作为主修复目标的问题。"""
    del normalization_report
    return _semantic_recovered_issues(validation_report)

def _semantic_recovered_issues(
    validation_report: StepIntentValidationReport | None,
) -> list[PlannerRetryIssue]:
    semantic = (
        validation_report.semantic_read_resolution
        if validation_report is not None
        else None
    )
    if semantic is None:
        return []
    return [
        PlannerRetryIssue(
            layer="semantic_reads",
            code=fallback.reason,
            step_id=fallback.step_id,
            scope_id=fallback.scope_id,
            repair_target="semantic_reads",
            preserve_policy="none",
            message=(
                "semantic_reads failed but legacy reads were visible and used "
                f"for step {fallback.step_id}."
            ),
            hints=tuple(
                error.message for error in fallback.semantic_errors
            ),
            related_handles=fallback.reads,
        )
        for fallback in semantic.fallbacks
    ]

def _validation_issues(
    validation_report: StepIntentValidationReport | None,
) -> list[PlannerRetryIssue]:
    if validation_report is None or validation_report.ok:
        return []
    if (
        validation_report.semantic_read_resolution is not None
        and validation_report.semantic_read_resolution.errors
    ):
        return []
    return [
        PlannerRetryIssue(
            layer="validation",
            code=_code_from_message(error),
            step_id=_step_id_from_text(error),
            scope_id=_scope_id_from_text(error),
            repair_target="step_intent_json",
            preserve_policy="none",
            message=_safe_error_message(error),
        )
        for error in validation_report.errors
    ]

def _candidate_issues(
    resolution_report: ExecutablePlanResolutionReport | None,
) -> list[PlannerRetryIssue]:
    if resolution_report is None or resolution_report.ok:
        return []
    issues: list[PlannerRetryIssue] = []
    for step_report in resolution_report.step_reports:
        if step_report.ok:
            continue
        messages = step_report.errors or ("no_executable_candidate",)
        issues.append(
            PlannerRetryIssue(
                layer="candidate_resolution",
                code=_code_from_messages(messages),
                step_id=step_report.step_id,
                scope_id=step_report.scope_id,
                repair_target="step",
                message="; ".join(_safe_error_message(item) for item in messages),
                hints=tuple(step_report.warnings),
            )
        )
    if not issues:
        issues.extend(
            PlannerRetryIssue(
                layer="candidate_resolution",
                code=_code_from_message(error),
                repair_target="step",
                message=_safe_error_message(error),
            )
            for error in resolution_report.errors
        )
    return issues

def _normalization_issues(errors: tuple[str, ...]) -> list[PlannerRetryIssue]:
    return [
        PlannerRetryIssue(
            layer="normalization",
            code=_code_from_message(error),
            step_id=_step_id_from_text(error),
            scope_id=_scope_id_from_text(error),
            repair_target="step_intent_json",
            preserve_policy="none",
            message=_safe_error_message(error),
        )
        for error in errors
    ]

def _trial_issues(
    diagnostic: StepIntentExecutionDiagnostic | None,
    *,
    draft: StepIntentDraft | None,
    guidance_resolver: RepairGuidanceResolver | None,
) -> list[PlannerRetryIssue]:
    if diagnostic is None or diagnostic.ok:
        return []
    issues: list[PlannerRetryIssue] = []
    for blocker in diagnostic.blockers:
        guidance = (
            guidance_resolver.resolve(
                missing_runtime_type=blocker.missing_runtime_type,
                step=find_step(draft, blocker.step_id),
                draft=draft,
            )
            if guidance_resolver is not None
            else None
        )
        hints = list(_retry_hints_for_blocker(blocker))
        if guidance is not None:
            hints.append(
                f"可用候选 `{guidance.capability_id}` 已通过当前 contract applicability 预检。"
            )
        issues.append(PlannerRetryIssue(
            layer="trial_execution",
            code=blocker.code,
            step_id=blocker.step_id,
            scope_id=blocker.scope_id,
            repair_target="step",
            message=blocker.message,
            hints=tuple(hints),
            related_handles=(
                (blocker.missing_runtime_type,)
                if blocker.missing_runtime_type is not None
                else ()
            ),
            details=(
                {"method_guidance": guidance.to_payload()}
                if guidance is not None
                else None
            ),
        ))
    if issues:
        return issues
    return [
        PlannerRetryIssue(
            layer="candidate_resolution",
            code=_code_from_message(error),
            repair_target="step",
            message=_safe_error_message(error),
        )
        for error in diagnostic.candidate_errors
    ]

def _retry_hints_for_blocker(blocker: Any) -> tuple[str, ...]:
    hints: list[str] = list(blocker.capability_errors)
    hint = RepairHintRegistry.default().find(blocker)
    if hint is not None:
        hints.extend(hint.next_actions)
        hints.extend(f"避免：{item}" for item in hint.do_not)
    return tuple(dict.fromkeys(hints))

def _answer_check_issues(
    errors: tuple[str, ...],
    *,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> list[PlannerRetryIssue]:
    issues: list[PlannerRetryIssue] = []
    for error in errors:
        if error.startswith("answer_mismatch:"):
            issues.append(
                PlannerRetryIssue(
                    layer="answer_check",
                    code="answer_mismatch",
                    repair_target="answer_goal",
                    preserve_policy="none",
                    message=_sanitize_answer_mismatch(error),
                )
            )
            continue
        if error.startswith("answer_unresolved:"):
            producer = _unresolved_symbol_producer(error, diagnostic)
            issues.append(
                PlannerRetryIssue(
                    layer="answer_check",
                    code="answer_unresolved",
                    step_id=(producer.step_id if producer is not None else None),
                    scope_id=(producer.scope_id if producer is not None else None),
                    repair_target="answer_goal",
                    preserve_policy="none",
                    message=_safe_error_message(error),
                    hints=_answer_unresolved_hints(error),
                    related_handles=_answer_related_handles(error),
                    details=(
                        {
                            "unresolved_symbols": list(_unresolved_symbol_names(error)),
                            "earliest_producer": producer.to_payload(),
                        }
                        if producer is not None
                        else {"unresolved_symbols": list(_unresolved_symbol_names(error))}
                    ),
                )
            )
    return issues

def _answer_unresolved_hints(
    error: str,
) -> tuple[str, ...]:
    del error
    return (
        "最终答案仍含 unresolved_symbols；从 earliest_producer 开始补齐对应 Symbol StateSlot 的 ParameterValue。",
        "ParameterValue 必须保持输入 Symbol identity；不要仅改 produced handle 的参数名。",
    )


def _unresolved_symbol_names(error: str) -> tuple[str, ...]:
    match = re.search(r"unresolved_symbols=([^;]+)", error)
    if match is None:
        return ()
    return tuple(
        item.strip()
        for item in match.group(1).split(",")
        if item.strip()
    )


def _unresolved_symbol_producer(
    error: str,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> Any | None:
    if diagnostic is None:
        return None
    names = set(_unresolved_symbol_names(error))
    if not names:
        return None
    for item in diagnostic.state_write_provenance:
        if item.runtime_type != "Symbol":
            continue
        if names.intersection(item.free_symbol_names):
            return item
    for item in diagnostic.state_write_provenance:
        if names.intersection(item.free_symbol_names):
            return item
    return None

def _answer_related_handles(error: str) -> tuple[str, ...]:
    match = re.search(r"goal=([^;]+)", error)
    if match is None:
        return ()
    return (match.group(1).strip(),)

def _stable_prefix(
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> tuple[dict[str, Any], ...]:
    if diagnostic is None:
        return ()
    return tuple(item.to_payload() for item in diagnostic.accepted_prefix)

def _stable_prefix_for_issues(
    diagnostic: StepIntentExecutionDiagnostic | None,
    issues: list[PlannerRetryIssue],
) -> tuple[dict[str, Any], ...]:
    prefix = _stable_prefix(diagnostic)
    goal_issue_step = next(
        (
            issue.step_id
            for issue in issues
            if issue.layer == "goal_verification" and issue.step_id
        ),
        None,
    )
    if goal_issue_step is None:
        return prefix
    result: list[dict[str, Any]] = []
    for item in prefix:
        if item.get("step_id") == goal_issue_step:
            break
        result.append(item)
    return tuple(result)

def _baseline_payload(
    *,
    effective_draft: StepIntentDraft | None,
    normalized_draft: StepIntentDraft | None,
    validation_report: StepIntentValidationReport | None,
) -> dict[str, Any] | None:
    if effective_draft is not None:
        return effective_draft.to_payload()
    if normalized_draft is not None:
        return normalized_draft.to_payload()
    semantic = (
        validation_report.semantic_read_resolution
        if validation_report is not None
        else None
    )
    if semantic is not None and semantic.partially_resolved_payload is not None:
        return semantic.partially_resolved_payload
    return None

def _repair_suffix_start(
    issues: list[PlannerRetryIssue],
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> dict[str, str | None] | None:
    if diagnostic is not None and diagnostic.first_blocker is not None:
        blocker = diagnostic.first_blocker
        return {"step_id": blocker.step_id, "scope_id": blocker.scope_id}
    return repair_suffix_start_from_issues(issues)

def _replay_reports(
    *,
    validation_report: StepIntentValidationReport | None,
    normalization_report: StepIntentNormalizationReport | None = None,
    resolution_report: ExecutablePlanResolutionReport | None,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    if validation_report is not None:
        reports["validation"] = validation_report.to_payload()
    if normalization_report is not None:
        reports["normalization"] = normalization_report.to_payload()
    if resolution_report is not None:
        reports["candidate_resolution"] = resolution_report.to_payload()
    if diagnostic is not None:
        reports["trial_execution"] = diagnostic.to_payload()
    return reports

def _replay_depth(
    *,
    issues: list[PlannerRetryIssue],
    validation_report: StepIntentValidationReport | None,
    normalization_report: StepIntentNormalizationReport | None,
    resolution_report: ExecutablePlanResolutionReport | None,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> PlannerReplayDepth | None:
    if any(issue.layer == "goal_verification" for issue in issues):
        return "goal_verification"
    if any(issue.layer == "answer_check" for issue in issues):
        return "answer_check"
    if diagnostic is not None:
        return "trial_execution"
    if resolution_report is not None:
        return "candidate_resolution"
    if any(issue.layer == "candidate_resolution" for issue in issues):
        return "candidate_resolution"
    if normalization_report is not None:
        return "normalization"
    if validation_report is not None:
        semantic = validation_report.semantic_read_resolution
        if semantic is not None and semantic.changed:
            return "semantic_reads"
        return "validation"
    return None

def _replay_timeline(
    *,
    validation_report: StepIntentValidationReport | None,
    normalization_report: StepIntentNormalizationReport | None,
    resolution_report: ExecutablePlanResolutionReport | None,
    diagnostic: StepIntentExecutionDiagnostic | None,
    issues: list[PlannerRetryIssue],
    recovered_issues: list[PlannerRetryIssue],
) -> tuple[dict[str, Any], ...]:
    blocking_by_layer = {issue.layer: issue for issue in issues}
    recovered_by_layer: dict[str, list[PlannerRetryIssue]] = {}
    for issue in recovered_issues:
        recovered_by_layer.setdefault(issue.layer, []).append(issue)

    timeline: list[dict[str, Any]] = []
    if (
        validation_report is not None
        and validation_report.semantic_read_resolution is not None
    ):
        semantic = validation_report.semantic_read_resolution
        timeline.append(
            _timeline_item(
                "semantic_reads",
                blocking=blocking_by_layer.get("semantic_reads"),
                recovered=recovered_by_layer.get("semantic_reads", []),
                ok=semantic.ok,
                detail_count=len(semantic.resolutions) + len(semantic.fallbacks),
            )
        )
    if validation_report is not None:
        timeline.append(
            _timeline_item(
                "validation",
                blocking=blocking_by_layer.get("validation"),
                recovered=recovered_by_layer.get("validation", []),
                ok=validation_report.ok,
                detail_count=len(validation_report.errors),
            )
        )
    if normalization_report is not None:
        timeline.append(
            {
                "layer": "normalization",
                "status": "recovered" if normalization_report.changed else "ok",
                "detail_count": len(normalization_report.actions),
            }
        )
    if resolution_report is not None:
        timeline.append(
            _timeline_item(
                "candidate_resolution",
                blocking=blocking_by_layer.get("candidate_resolution"),
                recovered=recovered_by_layer.get("candidate_resolution", []),
                ok=resolution_report.ok,
                detail_count=len(resolution_report.errors),
            )
        )
    elif blocking_by_layer.get("candidate_resolution") is not None:
        timeline.append(
            _timeline_item(
                "candidate_resolution",
                blocking=blocking_by_layer.get("candidate_resolution"),
                recovered=recovered_by_layer.get("candidate_resolution", []),
                ok=False,
                detail_count=sum(
                    1 for issue in issues
                    if issue.layer == "candidate_resolution"
                ),
            )
        )
    if diagnostic is not None:
        timeline.append(
            _timeline_item(
                "trial_execution",
                blocking=blocking_by_layer.get("trial_execution"),
                recovered=recovered_by_layer.get("trial_execution", []),
                ok=diagnostic.ok,
                detail_count=len(diagnostic.blockers),
            )
        )
    if any(issue.layer == "goal_verification" for issue in issues):
        timeline.append(
            _timeline_item(
                "goal_verification",
                blocking=blocking_by_layer.get("goal_verification"),
                recovered=recovered_by_layer.get("goal_verification", []),
                ok=False,
                detail_count=sum(
                    1 for issue in issues if issue.layer == "goal_verification"
                ),
            )
        )
    if any(issue.layer == "answer_check" for issue in issues):
        timeline.append(
            _timeline_item(
                "answer_check",
                blocking=blocking_by_layer.get("answer_check"),
                recovered=recovered_by_layer.get("answer_check", []),
                ok=False,
                detail_count=sum(
                    1 for issue in issues if issue.layer == "answer_check"
                ),
            )
        )
    return tuple(timeline)

def _timeline_item(
    layer: str,
    *,
    blocking: PlannerRetryIssue | None,
    recovered: list[PlannerRetryIssue],
    ok: bool,
    detail_count: int,
) -> dict[str, Any]:
    if blocking is not None:
        status = "blocked"
    elif recovered:
        status = "recovered"
    else:
        status = "ok" if ok else "failed"
    payload: dict[str, Any] = {
        "layer": layer,
        "status": status,
        "detail_count": detail_count,
    }
    issue = blocking or (recovered[0] if recovered else None)
    if issue is not None:
        payload["code"] = issue.code
        if issue.step_id is not None:
            payload["step_id"] = issue.step_id
        if issue.scope_id is not None:
            payload["scope_id"] = issue.scope_id
    return payload

def _code_from_messages(messages: tuple[str, ...]) -> str:
    for message in messages:
        if message:
            return _code_from_message(message)
    return "unknown"

def _code_from_message(message: str) -> str:
    text = str(message).strip()
    if not text:
        return "unknown"
    prefix = re.split(r"[:;\s]", text, maxsplit=1)[0]
    return re.sub(r"[^A-Za-z0-9_]+", "_", prefix).strip("_") or "unknown"

def _step_id_from_text(text: str) -> str | None:
    for pattern in (
        r"step(?:_id)?=([A-Za-z0-9_]+)",
        r"step `([A-Za-z0-9_]+)`",
        r"steps\[[0-9]+\]\.step_id.*?'([A-Za-z0-9_]+)'",
    ):
        match = re.search(pattern, text)
        if match is not None:
            return match.group(1)
    return None

def _scope_id_from_text(text: str) -> str | None:
    for pattern in (
        r"scope(?:_id)?=([A-Za-z0-9_]+)",
        r"scope_id ['\"]?([A-Za-z0-9_]+)['\"]?",
    ):
        match = re.search(pattern, text)
        if match is not None:
            return match.group(1)
    return None

def _safe_error_message(error: str) -> str:
    if error.startswith("answer_mismatch:"):
        return _sanitize_answer_mismatch(error)
    return str(error)

def _sanitize_answer_mismatch(error: str) -> str:
    text = str(error)
    if "; expected=" in text:
        text = text.split("; expected=", 1)[0]
    return text

_COMPAT_EXPORTS = {
    "merge_previous_accepted_prefix": (
        "shuxueshuo_server.solver.runtime.strategy_draft_merge",
        "merge_previous_accepted_prefix",
    ),
    "overlay_previous_retry_state_raw_payload": (
        "shuxueshuo_server.solver.runtime.strategy_draft_merge",
        "overlay_previous_retry_state_raw_payload",
    ),
    "prepare_step_intent_raw_response": (
        "shuxueshuo_server.solver.runtime.strategy_draft_merge",
        "prepare_step_intent_raw_response",
    ),
    "sanitize_step_intent_raw_payload": (
        "shuxueshuo_server.solver.runtime.strategy_draft_merge",
        "sanitize_step_intent_raw_payload",
    ),
    "PlannerRetryReplayResult": (
        "shuxueshuo_server.solver.runtime.strategy_replay",
        "PlannerRetryReplayResult",
    ),
    "PlannerRetryReplayService": (
        "shuxueshuo_server.solver.runtime.strategy_replay",
        "PlannerRetryReplayService",
    ),
    "repair_attempt_payload_from_replay": (
        "shuxueshuo_server.solver.runtime.strategy_replay",
        "repair_attempt_payload_from_replay",
    ),
}


def __getattr__(name: str) -> Any:
    target = _COMPAT_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    value = getattr(importlib.import_module(module_name), attr_name)
    globals()[name] = value
    return value


__all__ = [
    "build_planner_retry_state",
    "merge_previous_accepted_prefix",
    "overlay_previous_retry_state_raw_payload",
    "PlannerRetryReplayResult",
    "PlannerRetryReplayService",
    "prepare_step_intent_raw_response",
    "repair_attempt_payload_from_replay",
    "retry_state_from_attempt",
    "sanitize_step_intent_raw_payload",
]
