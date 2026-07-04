"""Deterministic replay pipeline for planner retry state generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.recipe_compiler import RecipeTrialExecutor
from shuxueshuo_server.solver.runtime.strategy_draft_merge import (
    merge_previous_accepted_prefix,
    prepare_step_intent_raw_response,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ExecutablePlanResolutionReport,
    PlannerRetryState,
    StepIntentDraft,
    StepIntentExecutionDiagnostic,
    StepIntentNormalizationReport,
    StepIntentRepairAttempt,
    StepIntentValidationReport,
)
from shuxueshuo_server.solver.runtime.strategy_normalizer import StepIntentNormalizer
from shuxueshuo_server.solver.runtime.strategy_repair_feedback import RepairFeedbackBuilder
from shuxueshuo_server.solver.runtime.strategy_resolver import StepIntentCandidateResolver
from shuxueshuo_server.solver.runtime.strategy_retry_state import build_planner_retry_state
from shuxueshuo_server.solver.runtime.strategy_validator import StepIntentValidator
@dataclass(frozen=True)
class PlannerRetryReplayResult:
    """一次 deterministic replay 的完整产物。"""

    attempt: int
    errors: tuple[str, ...] = ()
    raw_draft: StepIntentDraft | None = None
    validation_report: StepIntentValidationReport | None = None
    normalized_draft: StepIntentDraft | None = None
    normalization_report: StepIntentNormalizationReport | None = None
    resolution_report: ExecutablePlanResolutionReport | None = None
    effective_draft: StepIntentDraft | None = None
    diagnostic: StepIntentExecutionDiagnostic | None = None
    retry_state: PlannerRetryState | None = None
    output: Any | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        return {
            "attempt": self.attempt,
            "errors": list(self.errors),
            "raw_draft": self.raw_draft.to_payload() if self.raw_draft else None,
            "validation_report": (
                self.validation_report.to_payload()
                if self.validation_report is not None
                else None
            ),
            "normalized_draft": (
                self.normalized_draft.to_payload()
                if self.normalized_draft is not None
                else None
            ),
            "normalization_report": (
                self.normalization_report.to_payload()
                if self.normalization_report is not None
                else None
            ),
            "resolution_report": (
                self.resolution_report.to_payload()
                if self.resolution_report is not None
                else None
            ),
            "effective_draft": (
                self.effective_draft.to_payload()
                if self.effective_draft is not None
                else None
            ),
            "diagnostic": (
                self.diagnostic.to_payload()
                if self.diagnostic is not None
                else None
            ),
            "retry_state": (
                self.retry_state.to_payload()
                if self.retry_state is not None
                else None
            ),
            "output_ok": self.output is not None,
        }

class PlannerRetryReplayService:
    """统一执行 StepIntent deterministic replay 并生成 retry state。"""

    def replay_raw_json(
        self,
        raw_response: str,
        *,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        attempt: int,
        errors: tuple[str, ...] = (),
        merge_previous_prefix: bool = True,
    ) -> PlannerRetryReplayResult:
        """从 LLM raw JSON 开始 replay。"""
        raw_response = prepare_step_intent_raw_response(
            raw_response,
            previous_attempts=inputs.previous_errors,
        )
        draft, validation_report = StepIntentValidator().validate_json_with_report(
            raw_response,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )
        if draft is None:
            replay_errors = errors or tuple(validation_report.errors)
            retry_state = build_planner_retry_state(
                attempt=attempt,
                errors=replay_errors,
                validation_report=validation_report,
            )
            return PlannerRetryReplayResult(
                attempt=attempt,
                errors=replay_errors,
                validation_report=validation_report,
                retry_state=retry_state,
            )
        return self.replay_draft(
            draft,
            inputs=inputs,
            handle_registry=handle_registry,
            context=context,
            attempt=attempt,
            errors=errors,
            validation_report=validation_report,
            merge_previous_prefix=merge_previous_prefix,
        )

    def replay_draft(
        self,
        draft: StepIntentDraft,
        *,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        attempt: int,
        errors: tuple[str, ...] = (),
        validation_report: StepIntentValidationReport | None = None,
        merge_previous_prefix: bool = True,
    ) -> PlannerRetryReplayResult:
        """从已通过 validation 的 draft 开始 replay。"""
        raw_draft = draft
        replay_draft = (
            merge_previous_accepted_prefix(
                draft,
                previous_attempts=inputs.previous_errors,
                handle_registry=handle_registry,
                inputs=inputs,
            )
            if merge_previous_prefix
            else draft
        )
        try:
            normalized, normalization_report = StepIntentNormalizer().normalize(
                replay_draft,
                family_spec=inputs.family_spec,
                question_goals=inputs.question_goals,
                handle_registry=handle_registry,
            )
        except Exception as exc:
            replay_errors = errors or (str(exc),)
            retry_state = build_planner_retry_state(
                attempt=attempt,
                errors=replay_errors,
                normalized_draft=replay_draft,
                validation_report=validation_report,
                normalization_errors=(str(exc),),
            )
            return PlannerRetryReplayResult(
                attempt=attempt,
                errors=replay_errors,
                raw_draft=raw_draft,
                validation_report=validation_report,
                normalized_draft=replay_draft,
                retry_state=retry_state,
            )

        resolution_report = StepIntentCandidateResolver().resolve(
            normalized,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
        )
        output, diagnostic, effective_draft = RecipeTrialExecutor().diagnose(
            normalized,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            context=context,
            question_goals=inputs.question_goals,
        )
        retry_state = build_planner_retry_state(
            attempt=attempt,
            errors=errors,
            effective_draft=effective_draft,
            normalized_draft=normalized,
            validation_report=validation_report,
            resolution_report=resolution_report,
            diagnostic=diagnostic,
        )
        return PlannerRetryReplayResult(
            attempt=attempt,
            errors=errors,
            raw_draft=raw_draft,
            validation_report=validation_report,
            normalized_draft=normalized,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            effective_draft=effective_draft,
            diagnostic=diagnostic,
            retry_state=retry_state,
            output=output,
        )

    def replay_from_artifacts(
        self,
        *,
        attempt: int,
        errors: tuple[str, ...],
        raw_draft: StepIntentDraft | None = None,
        validation_report: StepIntentValidationReport | None = None,
        normalized_draft: StepIntentDraft | None = None,
        normalization_report: StepIntentNormalizationReport | None = None,
        resolution_report: ExecutablePlanResolutionReport | None = None,
        effective_draft: StepIntentDraft | None = None,
        diagnostic: StepIntentExecutionDiagnostic | None = None,
        output: Any | None = None,
    ) -> PlannerRetryReplayResult:
        """从已存在 artifacts 生成同一形态 replay result。"""
        retry_state = build_planner_retry_state(
            attempt=attempt,
            errors=errors,
            effective_draft=effective_draft,
            normalized_draft=normalized_draft,
            validation_report=validation_report,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            diagnostic=diagnostic,
        )
        return PlannerRetryReplayResult(
            attempt=attempt,
            errors=errors,
            raw_draft=raw_draft,
            validation_report=validation_report,
            normalized_draft=normalized_draft,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            effective_draft=effective_draft,
            diagnostic=diagnostic,
            retry_state=retry_state,
            output=output,
        )

def repair_attempt_payload_from_replay(
    replay: PlannerRetryReplayResult,
) -> dict[str, Any] | None:
    """从 replay result 生成 previous_attempts 可携带的 repair context。"""
    diagnostic = replay.diagnostic
    if not replay.errors and (diagnostic is None or diagnostic.ok):
        return None
    effective = replay.effective_draft
    repair_summary = RepairFeedbackBuilder(
        diagnostic=diagnostic,
        errors=replay.errors,
        effective_draft=effective,
    ).build()
    retry_state = replay.retry_state
    repair_instruction = (
        retry_state.repair_instruction
        if retry_state is not None
        else "请根据 errors 修复并重新输出完整 StepIntent JSON。不要输出 patch。"
    )
    return StepIntentRepairAttempt(
        attempt=replay.attempt,
        effective_draft=effective.to_payload() if effective is not None else None,
        diagnostic=diagnostic,
        repair_summary=repair_summary,
        planner_retry_state=retry_state,
        repair_instruction=repair_instruction,
        errors=replay.errors,
    ).to_payload()

__all__ = [
    "PlannerRetryReplayResult",
    "PlannerRetryReplayService",
    "repair_attempt_payload_from_replay",
]
