"""Final canonical validation boundary for StepIntent drafts.

The normalizer is allowed to rewrite aliases and promote state across scopes.
Those transformations can make two previously distinct handles converge only
after normalization.  This module owns the final, idempotent validation pass
shared by replay and runtime compilation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    HandleResolver,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateWrite,
    StepIntentDraft,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.strategy_validator import validate_canonical_draft


@dataclass(frozen=True)
class CanonicalDraftFinalizationReport:
    """Debug-safe summary of the final canonicalization boundary."""

    changed: bool
    handle_resolution: dict[str, Any] | None = None
    step_count: int = 0
    issues: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "handle_resolution": self.handle_resolution,
            "step_count": self.step_count,
            "issues": list(self.issues),
        }


class CanonicalDraftFinalizer:
    """Produce the one canonical draft consumed by candidate/runtime layers."""

    def finalize(
        self,
        draft: StepIntentDraft,
        *,
        family_spec: SolverFamilySpec,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
        handle_registry: CanonicalHandleRegistry,
        allow_shared_derivation_scopes: bool = False,
        projected_state_writes: tuple[ProjectedStateWrite, ...] = (),
    ) -> tuple[StepIntentDraft, CanonicalDraftFinalizationReport]:
        before = draft.to_payload()
        issues: tuple[str, ...] = ()
        try:
            finalized, validation_report = validate_canonical_draft(
                draft,
                question_goals=question_goals,
                handle_registry=handle_registry,
                family_spec=family_spec,
                allow_shared_derivation_scopes=allow_shared_derivation_scopes,
                projected_state_writes=projected_state_writes,
            )
            resolution = validation_report.handle_resolution
        except StrategyDraftValidationError as exc:
            # Partial drafts used by trial diagnostics may intentionally expose
            # a missing read so CandidateResolver can produce a typed blocker.
            # Canonicalize aliases, but keep that read error non-fatal here.
            if not str(exc).startswith("unknown_read_handle:"):
                raise
            finalized, resolution = HandleResolver().resolve_draft(
                draft,
                handle_registry,
            )
            issues = (str(exc),)
        return finalized, CanonicalDraftFinalizationReport(
            changed=finalized.to_payload() != before,
            handle_resolution=(
                resolution.to_payload() if resolution is not None else None
            ),
            step_count=len(finalized.steps),
            issues=issues,
        )

    def validate_state_write_provenance(
        self,
        provenance: tuple[Any, ...],
    ) -> None:
        """Enforce single-writer semantics on the finalized StateSlot ledger."""
        latest_by_slot: dict[str, Any] = {}
        for item in provenance:
            slot_id = getattr(item, "state_slot_id", None)
            if not isinstance(slot_id, str) or not slot_id:
                continue
            previous = latest_by_slot.get(slot_id)
            mode = getattr(item, "write_mode", "value")
            if previous is None:
                if mode == "transition":
                    raise StrategyDraftValidationError(
                        "state_transition_without_previous_write: "
                        f"slot={slot_id}, step={item.step_id}"
                    )
                latest_by_slot[slot_id] = item
                continue
            if previous.step_id == item.step_id:
                # One runtime output may be registered as both a reusable fact
                # and an answer alias inside the same step.
                latest_by_slot[slot_id] = item
                continue
            if mode != "transition":
                raise StrategyDraftValidationError(
                    "duplicate_state_slot_writer: "
                    f"slot={slot_id}, first={previous.step_id}, second={item.step_id}"
                )
            if getattr(item, "previous_write_step_id", None) != previous.step_id:
                raise StrategyDraftValidationError(
                    "state_transition_previous_write_mismatch: "
                    f"slot={slot_id}, expected={previous.step_id}, "
                    f"actual={getattr(item, 'previous_write_step_id', None)}"
                )
            if getattr(item, "transition_kind", None) == "dependency_refinement":
                previous_symbols = set(
                    getattr(previous, "free_symbol_names", ())
                )
                current_symbols = set(getattr(item, "free_symbol_names", ()))
                if not current_symbols < previous_symbols:
                    raise StrategyDraftValidationError(
                        "state_transition_not_dependency_refinement: "
                        f"slot={slot_id}, previous_symbols="
                        f"{sorted(previous_symbols)}, current_symbols="
                        f"{sorted(current_symbols)}"
                    )
            latest_by_slot[slot_id] = item


__all__ = [
    "CanonicalDraftFinalizationReport",
    "CanonicalDraftFinalizer",
]
