"""Final canonical validation boundary for StepIntent drafts.

The normalizer is allowed to rewrite aliases and promote state across scopes.
Those transformations can make two previously distinct handles converge only
after normalization.  This module owns the final, idempotent validation pass
shared by replay and runtime compilation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    HandleResolver,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateDependency,
    ProjectedStateWrite,
    StepIntentDraft,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    StateFinalizationResult,
    StateFinalizationService,
    StateFinalizerMode,
)
from shuxueshuo_server.solver.runtime.state_identity import IndexedStateVersion
from shuxueshuo_server.solver.runtime.models import StepPlan
from shuxueshuo_server.solver.utils import unique_ordered
from shuxueshuo_server.solver.runtime.strategy_validator import validate_canonical_draft


@dataclass(frozen=True)
class CanonicalDraftFinalizationReport:
    """Debug-safe summary of the final canonicalization boundary."""

    changed: bool
    handle_resolution: dict[str, Any] | None = None
    step_count: int = 0
    issues: tuple[str, ...] = ()
    state_finalization_decisions: tuple[dict[str, Any], ...] = ()
    state_finalization_mismatches: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "handle_resolution": self.handle_resolution,
            "step_count": self.step_count,
            "issues": list(self.issues),
            "state_finalization_decisions": [
                dict(item) for item in self.state_finalization_decisions
            ],
            "state_finalization_mismatches": [
                dict(item) for item in self.state_finalization_mismatches
            ],
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
        projected_state_dependencies: tuple[ProjectedStateDependency, ...] = (),
        known_state_versions: tuple[IndexedStateVersion, ...] = (),
        state_finalizer_mode: StateFinalizerMode = "authoritative",
    ) -> tuple[StepIntentDraft, CanonicalDraftFinalizationReport]:
        before = draft.to_payload()
        logical_finalization = StateFinalizationResult()
        if _uses_typed_finalization(projected_state_writes):
            logical_finalization = (
                StateFinalizationService().finalize_logical_graph(
                    projected_state_writes,
                    dependencies=projected_state_dependencies,
                    known_versions=known_state_versions,
                    step_scopes={
                        step.step_id: step.scope_id for step in draft.steps
                    },
                    handle_registry=handle_registry,
                    mode=state_finalizer_mode,
                )
            )
        draft = _close_projected_state_reads(
            draft,
            projected_state_writes=projected_state_writes,
            projected_state_dependencies=projected_state_dependencies,
            handle_registry=handle_registry,
        )
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
                authoritative_produced_handles={
                    item.produced_handle
                    for item in projected_state_writes
                },
            )
            issues = (str(exc),)
        return finalized, CanonicalDraftFinalizationReport(
            changed=finalized.to_payload() != before,
            handle_resolution=(
                resolution.to_payload() if resolution is not None else None
            ),
            step_count=len(finalized.steps),
            issues=issues,
            state_finalization_decisions=tuple(
                item.to_payload()
                for item in logical_finalization.decisions
            ),
            state_finalization_mismatches=tuple(
                item.to_payload()
                for item in logical_finalization.mismatches
            ),
        )

    def finalize_compiled_state_writes(
        self,
        *,
        projected_state_writes: tuple[ProjectedStateWrite, ...],
        provenance: tuple[Any, ...],
        plans: tuple[StepPlan, ...],
        question_goals: tuple[QuestionGoal, ...],
        handle_registry: CanonicalHandleRegistry,
        state_finalizer_mode: StateFinalizerMode = "authoritative",
    ) -> StateFinalizationResult:
        """Validate compiler outputs against B2 versions and destinations."""

        return StateFinalizationService().finalize_compiled_graph(
            projected_state_writes,
            provenance,
            plans,
            question_goals=question_goals,
            handle_registry=handle_registry,
            mode=state_finalizer_mode,
        )

    def validate_state_write_provenance(
        self,
        provenance: tuple[Any, ...],
    ) -> None:
        """Enforce single-writer semantics on the finalized StateSlot ledger."""
        latest_by_slot: dict[str, Any] = {}
        writes_by_version: dict[Any, Any] = {}
        for item in provenance:
            slot_id = getattr(item, "state_slot_id", None)
            if not isinstance(slot_id, str) or not slot_id:
                continue
            previous = latest_by_slot.get(slot_id)
            mode = getattr(item, "write_mode", "value")
            previous_version_id = getattr(item, "previous_version_id", None)
            allocation_action = getattr(item, "allocation_action", None)
            if (
                mode == "transition"
                and allocation_action == "transition"
                and previous_version_id is None
            ):
                raise StrategyDraftValidationError(
                    "planner.state_projection_drift: authoritative transition "
                    "is missing previous_version_id: "
                    f"slot={slot_id}, step={item.step_id}"
                )
            typed_previous = (
                writes_by_version.get(previous_version_id)
                if previous_version_id is not None
                else None
            )
            if mode == "transition" and previous_version_id is not None:
                if typed_previous is None:
                    raise StrategyDraftValidationError(
                        "state_transition_typed_previous_missing: "
                        f"slot={slot_id}, step={item.step_id}"
                    )
                previous = typed_previous
            if previous is None:
                if mode == "transition":
                    raise StrategyDraftValidationError(
                        "state_transition_without_previous_write: "
                        f"slot={slot_id}, step={item.step_id}"
                    )
                latest_by_slot[slot_id] = item
                selected_version_id = getattr(
                    item,
                    "selected_version_id",
                    None,
                )
                if selected_version_id is not None:
                    writes_by_version[selected_version_id] = item
                continue
            if previous.step_id == item.step_id:
                # One runtime output may be registered as both a reusable fact
                # and an answer alias inside the same step.
                latest_by_slot[slot_id] = item
                selected_version_id = getattr(
                    item,
                    "selected_version_id",
                    None,
                )
                if selected_version_id is not None:
                    writes_by_version[selected_version_id] = item
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
                if not current_symbols <= previous_symbols:
                    raise StrategyDraftValidationError(
                        "state_transition_not_dependency_refinement: "
                        f"slot={slot_id}, previous_symbols="
                        f"{sorted(previous_symbols)}, current_symbols="
                        f"{sorted(current_symbols)}"
                    )
            latest_by_slot[slot_id] = item
            selected_version_id = getattr(item, "selected_version_id", None)
            if selected_version_id is not None:
                writes_by_version[selected_version_id] = item


def _close_projected_state_reads(
    draft: StepIntentDraft,
    *,
    projected_state_writes: tuple[ProjectedStateWrite, ...],
    projected_state_dependencies: tuple[ProjectedStateDependency, ...] = (),
    handle_registry: CanonicalHandleRegistry,
) -> StepIntentDraft:
    """Restore exact reconciled StateSlot dependencies before legacy binding."""
    if not projected_state_dependencies:
        return draft

    step_index = {
        step.step_id: index for index, step in enumerate(draft.steps)
    }
    writes_by_handle = {
        write.produced_handle: write
        for write in projected_state_writes
        if write.step_id in step_index
    }
    writes_by_slot: dict[str, list[ProjectedStateWrite]] = {}
    for write in projected_state_writes:
        if write.step_id in step_index:
            writes_by_slot.setdefault(write.state_slot_id, []).append(write)
    for writes in writes_by_slot.values():
        writes.sort(key=lambda item: step_index[item.step_id])
    dependencies_by_step: dict[str, list[ProjectedStateDependency]] = {}
    for dependency in projected_state_dependencies:
        if dependency.step_id in step_index:
            dependencies_by_step.setdefault(
                dependency.step_id,
                [],
            ).append(dependency)
    valid_scope_by_handle = {
        produced.handle: produced.valid_scope
        for step in draft.steps
        for produced in step.produces
    }
    rewritten_steps = []

    def is_visible(handle: str, scope_id: str) -> bool:
        valid_scope = (
            valid_scope_by_handle.get(handle)
            or handle_registry.handle_valid_scopes.get(handle)
        )
        return (
            isinstance(valid_scope, str)
            and visible_from_valid_scope(
                valid_scope,
                scope_id=scope_id,
                registry=handle_registry,
            )
        )

    def latest_source_write(
        state_slot_id: str,
        *,
        before_index: int,
    ) -> ProjectedStateWrite | None:
        candidates = writes_by_slot.get(state_slot_id, ())
        return next(
            (
                item
                for item in reversed(candidates)
                if step_index[item.step_id] < before_index
            ),
            None,
        )

    def dependency_handles(
        dependency: ProjectedStateDependency,
        *,
        consumer_index: int,
    ) -> tuple[str, ...]:
        result: list[str] = []
        pending: list[tuple[ProjectedStateWrite, int]] = []
        direct_write = writes_by_handle.get(dependency.produced_handle)
        if direct_write is not None:
            pending.append((direct_write, step_index[direct_write.step_id]))
            result.append(direct_write.produced_handle)
        else:
            exact_source = next(
                (
                    item
                    for item in projected_state_writes
                    if dependency.source_step_id is not None
                    and item.step_id == dependency.source_step_id
                    and item.step_id in step_index
                    and (
                        dependency.source_return_name is None
                        or item.return_name == dependency.source_return_name
                    )
                    and step_index[item.step_id] < consumer_index
                ),
                None,
            )
            slot_write = exact_source or latest_source_write(
                dependency.state_slot_id,
                before_index=consumer_index,
            )
            if slot_write is not None:
                pending.append((slot_write, step_index[slot_write.step_id]))
                result.append(slot_write.produced_handle)
            else:
                result.append(dependency.produced_handle)
        visited: set[tuple[str, str]] = set()
        while pending:
            write, write_index = pending.pop()
            write_key = (write.step_id, write.produced_handle)
            if write_key in visited:
                continue
            visited.add(write_key)
            for source_slot_id in write.source_state_slot_ids:
                source = latest_source_write(
                    source_slot_id,
                    before_index=write_index,
                )
                if source is None:
                    continue
                result.append(source.produced_handle)
                pending.append((source, step_index[source.step_id]))
        return unique_ordered(result)

    for step in draft.steps:
        reads = list(step.reads)
        for dependency in dependencies_by_step.get(step.step_id, ()):
            for handle in dependency_handles(
                dependency,
                consumer_index=step_index[step.step_id],
            ):
                if handle in reads:
                    continue
                if not is_visible(handle, step.scope_id):
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: projected StateSlot "
                        "dependency is not visible: "
                        f"step={step.step_id}, slot={dependency.state_slot_id}, "
                        f"handle={handle}, scope={step.scope_id}"
                    )
                reads.append(handle)

        rewritten = (
            step
            if tuple(reads) == step.reads
            else replace(step, reads=tuple(reads))
        )
        rewritten_steps.append(rewritten)

    rewritten_by_id = {step.step_id: step for step in rewritten_steps}
    rewritten = StepIntentDraft(
        scopes=tuple(
            replace(
                scope,
                steps=tuple(
                    rewritten_by_id[step.step_id]
                    for step in scope.steps
                ),
            )
            for scope in draft.scopes
        )
    )
    return rewritten


def _uses_typed_finalization(
    writes: tuple[ProjectedStateWrite, ...],
) -> bool:
    return any(
        item.selected_version_id is not None
        or item.allocation_action is not None
        for item in writes
    )


__all__ = [
    "CanonicalDraftFinalizationReport",
    "CanonicalDraftFinalizer",
]
