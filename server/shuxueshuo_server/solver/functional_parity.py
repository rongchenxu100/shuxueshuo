"""Offline parity checks for recorded StepIntent and authored FunctionalPlan."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from shuxueshuo_server.solver.deepseek_functional_batch import FunctionalBatchCase
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_plan_validation import (
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_models import (
    StateWriteProvenance,
    StepIntentExecutionDiagnostic,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayService,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import StrategyPlanner
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    is_object_handle,
    state_kind_for_runtime_type,
)


@dataclass(frozen=True)
class ProvenanceAnswerSignature:
    answer_handle: str
    runtime_type: str
    object_ref: str | None
    state_kind: str
    closed: bool
    write_mode: str
    identity_policy: str
    semantic_roles: tuple[str, ...]
    evidence_tags: tuple[str, ...]
    object_roles: tuple[tuple[str, tuple[str, ...]], ...]
    dependency_object_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "answer_handle": self.answer_handle,
            "runtime_type": self.runtime_type,
            "object_ref": self.object_ref,
            "state_kind": self.state_kind,
            "closed": self.closed,
            "write_mode": self.write_mode,
            "identity_policy": self.identity_policy,
            "semantic_roles": list(self.semantic_roles),
            "evidence_tags": list(self.evidence_tags),
            "object_roles": {
                role: list(object_refs)
                for role, object_refs in self.object_roles
            },
            "dependency_object_refs": list(self.dependency_object_refs),
        }


@dataclass(frozen=True)
class ProvenanceLogicalStateSignature:
    object_ref: str
    state_kind: str
    runtime_type: str
    writer_count: int
    scopes: tuple[str, ...]
    write_modes: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "object_ref": self.object_ref,
            "state_kind": self.state_kind,
            "runtime_type": self.runtime_type,
            "writer_count": self.writer_count,
            "scopes": list(self.scopes),
            "write_modes": list(self.write_modes),
        }


@dataclass(frozen=True)
class ProvenanceParitySignature:
    answers: tuple[ProvenanceAnswerSignature, ...]
    logical_states: tuple[ProvenanceLogicalStateSignature, ...]
    integrity_issues: tuple[str, ...] = ()
    scope_parents: tuple[tuple[str, str | None], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "answers": [item.to_payload() for item in self.answers],
            "logical_states": [
                item.to_payload() for item in self.logical_states
            ],
            "integrity_issues": list(self.integrity_issues),
            "scope_parents": dict(self.scope_parents),
        }


@dataclass(frozen=True)
class ProvenanceParityMismatch:
    path: str
    recorded: Any
    functional: Any
    message: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "recorded": self.recorded,
            "functional": self.functional,
            "message": self.message,
        }


@dataclass(frozen=True)
class ProvenanceParityReport:
    ok: bool
    recorded: ProvenanceParitySignature
    functional: ProvenanceParitySignature
    mismatches: tuple[ProvenanceParityMismatch, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "recorded": self.recorded.to_payload(),
            "functional": self.functional.to_payload(),
            "mismatches": [item.to_payload() for item in self.mismatches],
        }


class FunctionalParityRunner:
    """Replay both authored protocols and compare semantic provenance."""

    def compare_fixture(
        self,
        case: FunctionalBatchCase,
    ) -> ProvenanceParityReport:
        problem = load_problem_ir(case.problem_fixture_path)
        inputs = build_strategy_probe_inputs(problem)
        problem_payload = problem_to_llm_payload(problem)
        handle_registry = CanonicalHandleRegistry.from_problem_payload(
            problem_payload
        )

        recorded_planner = StrategyPlanner(
            ContextBuilder().build(problem),
            mode="recorded",
            recorded_fixture_dir=case.recorded_step_intent_path.parent,
        )
        recorded_planner.plan(inputs)
        recorded_replay = recorded_planner.artifacts.retry_replay_result
        if recorded_replay is None or recorded_replay.diagnostic is None:
            raise AssertionError(
                f"recorded fixture produced no diagnostic: {case.case_id}"
            )

        functional_payload = json.loads(
            case.functional_fixture_path.read_text(encoding="utf-8")
        )
        functional_plan, validation = (
            FunctionalPlanValidator().validate_payload_with_report(
                functional_payload,
                handle_registry=handle_registry,
                question_goals=inputs.question_goals,
            )
        )
        if functional_plan is None or not validation.ok:
            raise AssertionError(
                f"invalid FunctionalPlan fixture {case.case_id}: "
                f"{validation.errors}"
            )
        functional_replay = PlannerRetryReplayService().replay_functional_plan(
            functional_plan,
            inputs=inputs,
            handle_registry=handle_registry,
            context=ContextBuilder().build(problem),
            attempt=1,
            problem_payload=problem_payload,
            validation_report=validation,
        )
        if functional_replay.output is None or functional_replay.diagnostic is None:
            raise AssertionError(
                f"FunctionalPlan fixture did not replay {case.case_id}: "
                f"{functional_replay.errors}"
            )

        recorded = provenance_parity_signature(
            recorded_replay.diagnostic,
            scope_parents=handle_registry.scope_parents,
        )
        functional = provenance_parity_signature(
            functional_replay.diagnostic,
            scope_parents=handle_registry.scope_parents,
        )
        mismatches = compare_provenance_signatures(recorded, functional)
        return ProvenanceParityReport(
            ok=not mismatches,
            recorded=recorded,
            functional=functional,
            mismatches=mismatches,
        )


def provenance_parity_signature(
    diagnostic: StepIntentExecutionDiagnostic,
    *,
    scope_parents: dict[str, str | None] | None = None,
) -> ProvenanceParitySignature:
    writes = tuple(diagnostic.state_write_provenance)
    answer_writes = tuple(
        write
        for write in writes
        if write.produced_handle.startswith("answer:")
    )
    reachable_by_answer = {
        id(write): _answer_reachable_writes(writes, (write,))
        for write in answer_writes
    }
    reachable_ids = {
        id(write)
        for items in reachable_by_answer.values()
        for write in items
    }
    reachable_writes = tuple(
        write for write in writes if id(write) in reachable_ids
    )
    answers = tuple(
        _answer_signature(
            item,
            aliases=_write_aliases(item, writes),
            terminal_dependencies=_terminal_dependency_object_refs(
                reachable_by_answer[id(item)]
            ),
        )
        for item in sorted(
            answer_writes,
            key=lambda item: item.produced_handle,
        )
    )
    logical_states, integrity_issues = _logical_state_signatures(
        reachable_writes
    )
    return ProvenanceParitySignature(
        answers=answers,
        logical_states=logical_states,
        integrity_issues=integrity_issues,
        scope_parents=tuple(sorted((scope_parents or {}).items())),
    )


def compare_provenance_signatures(
    recorded: ProvenanceParitySignature,
    functional: ProvenanceParitySignature,
) -> tuple[ProvenanceParityMismatch, ...]:
    mismatches: list[ProvenanceParityMismatch] = []
    if recorded.integrity_issues:
        mismatches.append(
            ProvenanceParityMismatch(
                "recorded.integrity",
                recorded.integrity_issues,
                (),
                "recorded provenance oracle is internally inconsistent",
            )
        )
    if functional.integrity_issues:
        mismatches.append(
            ProvenanceParityMismatch(
                "functional.integrity",
                (),
                functional.integrity_issues,
                "Functional provenance has duplicate or invalid writers",
            )
        )
    recorded_answers = {
        item.answer_handle: item for item in recorded.answers
    }
    functional_answers = {
        item.answer_handle: item for item in functional.answers
    }
    if set(recorded_answers) != set(functional_answers):
        mismatches.append(
            ProvenanceParityMismatch(
                "answers",
                sorted(recorded_answers),
                sorted(functional_answers),
                "answer producer sets differ",
            )
        )
    for handle in sorted(set(recorded_answers) & set(functional_answers)):
        _compare_answer(
            handle,
            recorded_answers[handle],
            functional_answers[handle],
            mismatches,
        )
    _compare_logical_states(recorded, functional, mismatches)
    return tuple(mismatches)


def _answer_signature(
    write: StateWriteProvenance,
    *,
    aliases: tuple[StateWriteProvenance, ...],
    terminal_dependencies: tuple[str, ...],
) -> ProvenanceAnswerSignature:
    combined = (write, *aliases)
    return ProvenanceAnswerSignature(
        answer_handle=write.produced_handle,
        runtime_type=write.runtime_type,
        object_ref=write.object_ref,
        state_kind=state_kind_for_runtime_type(write.runtime_type),
        closed=not write.free_symbol_names,
        write_mode=_answer_write_mode(combined),
        identity_policy=_answer_identity_policy(combined),
        semantic_roles=_answer_semantic_roles(combined),
        evidence_tags=tuple(
            sorted(
                {
                    tag
                    for item in combined
                    for tag in item.lineage.evidence_tags
                }
            )
        ),
        object_roles=_object_roles(
            tuple(
                role
                for item in combined
                for role in item.lineage.object_roles
            )
        ),
        dependency_object_refs=tuple(
            sorted(
                {
                    *terminal_dependencies,
                    *(
                        object_ref
                        for item in combined
                        for object_ref in item.dependency_object_refs
                        if is_object_handle(object_ref)
                    ),
                }
            )
        ),
    )


def _compare_answer(
    handle: str,
    recorded: ProvenanceAnswerSignature,
    functional: ProvenanceAnswerSignature,
    mismatches: list[ProvenanceParityMismatch],
) -> None:
    for field_name in (
        "runtime_type",
        "object_ref",
        "state_kind",
        "closed",
        "write_mode",
        "identity_policy",
    ):
        recorded_value = getattr(recorded, field_name)
        functional_value = getattr(functional, field_name)
        if recorded_value != functional_value:
            mismatches.append(
                ProvenanceParityMismatch(
                    f"answers.{handle}.{field_name}",
                    recorded_value,
                    functional_value,
                    "answer provenance differs",
                )
            )
    _compare_recorded_subset(
        path=f"answers.{handle}.semantic_roles",
        recorded=recorded.semantic_roles,
        functional=functional.semantic_roles,
        message="Functional answer is missing recorded semantic roles",
        mismatches=mismatches,
    )
    _compare_recorded_subset(
        path=f"answers.{handle}.evidence_tags",
        recorded=recorded.evidence_tags,
        functional=functional.evidence_tags,
        message="Functional answer is missing recorded evidence tags",
        mismatches=mismatches,
    )
    _compare_recorded_subset(
        path=f"answers.{handle}.dependency_object_refs",
        recorded=recorded.dependency_object_refs,
        functional=functional.dependency_object_refs,
        message="Functional answer is missing recorded terminal dependencies",
        mismatches=mismatches,
    )
    functional_roles = dict(functional.object_roles)
    for role, object_refs in recorded.object_roles:
        actual = functional_roles.get(role)
        if actual is None or not set(object_refs).issubset(actual):
            mismatches.append(
                ProvenanceParityMismatch(
                    f"answers.{handle}.object_roles.{role}",
                    object_refs,
                    actual,
                    "Functional answer is missing a recorded object-role binding",
                )
            )


def _compare_recorded_subset(
    *,
    path: str,
    recorded: tuple[str, ...],
    functional: tuple[str, ...],
    message: str,
    mismatches: list[ProvenanceParityMismatch],
) -> None:
    if recorded and not set(recorded).issubset(functional):
        mismatches.append(
            ProvenanceParityMismatch(
                path,
                recorded,
                functional,
                message,
            )
        )


def _compare_logical_states(
    recorded: ProvenanceParitySignature,
    functional: ProvenanceParitySignature,
    mismatches: list[ProvenanceParityMismatch],
) -> None:
    """Require every recorded answer-reachable logical state in Functional.

    Functional may contain additional answer-reachable object states because
    the authored protocol can expose richer intermediate provenance than the
    legacy recorded StepIntent. The shared states must preserve writer count,
    transition order, and recorded visibility.
    """
    functional_scope_parents = dict(functional.scope_parents)
    recorded_states = {
        _logical_state_key(item): item for item in recorded.logical_states
    }
    functional_states = {
        _logical_state_key(item): item for item in functional.logical_states
    }
    for key in sorted(recorded_states):
        expected = recorded_states[key]
        actual = functional_states.get(key)
        path = "logical_states." + "/".join(key)
        if actual is None:
            mismatches.append(
                ProvenanceParityMismatch(
                    path,
                    expected.to_payload(),
                    None,
                    "Functional answer graph is missing a recorded logical state",
                )
            )
            continue
        for field_name in ("writer_count", "write_modes"):
            expected_value = getattr(expected, field_name)
            actual_value = getattr(actual, field_name)
            if expected_value != actual_value:
                mismatches.append(
                    ProvenanceParityMismatch(
                        f"{path}.{field_name}",
                        expected_value,
                        actual_value,
                        "answer-reachable logical-state provenance differs",
                    )
                )
        if not _scopes_cover(
            expected.scopes,
            actual.scopes,
            scope_parents=functional_scope_parents,
        ):
            mismatches.append(
                ProvenanceParityMismatch(
                    f"{path}.scopes",
                    expected.scopes,
                    actual.scopes,
                    "Functional state is not visible wherever the recorded state was visible",
                )
            )


def _logical_state_key(
    item: ProvenanceLogicalStateSignature,
) -> tuple[str, str, str]:
    return (item.object_ref, item.state_kind, item.runtime_type)


def _logical_state_signatures(
    writes: Iterable[StateWriteProvenance],
) -> tuple[
    tuple[ProvenanceLogicalStateSignature, ...],
    tuple[str, ...],
]:
    grouped: dict[tuple[str, str, str], list[StateWriteProvenance]] = {}
    for write in writes:
        if write.object_ref is None:
            continue
        key = (
            write.object_ref,
            state_kind_for_runtime_type(write.runtime_type),
            write.runtime_type,
        )
        grouped.setdefault(key, []).append(write)
    signatures: list[ProvenanceLogicalStateSignature] = []
    issues: list[str] = []
    for key, items in sorted(grouped.items()):
        unique: list[StateWriteProvenance] = []
        seen_writes: set[tuple[str, str | None]] = set()
        for item in items:
            write_key = (item.step_id, item.state_slot_id)
            if write_key in seen_writes:
                continue
            seen_writes.add(write_key)
            unique.append(item)
        writers_by_slot: dict[
            str,
            list[StateWriteProvenance],
        ] = {}
        for item in unique:
            slot_id = item.state_slot_id or (
                f"{item.object_ref}.{state_kind_for_runtime_type(item.runtime_type)}"
                f"@{item.scope_id}:{item.runtime_type}"
            )
            writers_by_slot.setdefault(slot_id, []).append(item)
        for slot_id, slot_writes in writers_by_slot.items():
            if len(slot_writes) > 1:
                for item in slot_writes[1:]:
                    if item.write_mode == "transition":
                        continue
                    issues.append(
                        "duplicate logical-state writer: "
                        f"{key[0]}/{key[1]}/{key[2]}@{item.scope_id} "
                        f"at {item.step_id}"
                    )
        signatures.append(
            ProvenanceLogicalStateSignature(
                object_ref=key[0],
                state_kind=key[1],
                runtime_type=key[2],
                writer_count=max(
                    (
                        len(slot_writes)
                        for slot_writes in writers_by_slot.values()
                    ),
                    default=0,
                ),
                scopes=tuple(
                    dict.fromkeys(item.scope_id for item in unique)
                ),
                write_modes=tuple(
                    dict.fromkeys(
                        _semantic_write_mode(item) for item in unique
                    )
                ),
            )
        )
    return tuple(signatures), tuple(issues)


def _answer_reachable_writes(
    writes: tuple[StateWriteProvenance, ...],
    answer_writes: tuple[StateWriteProvenance, ...],
) -> tuple[StateWriteProvenance, ...]:
    """Follow typed state provenance from every answer to its producers."""
    positions = {id(write): index for index, write in enumerate(writes)}
    by_state_slot: dict[str, list[StateWriteProvenance]] = {}
    by_object_ref: dict[str, list[StateWriteProvenance]] = {}
    for write in writes:
        if write.state_slot_id:
            by_state_slot.setdefault(write.state_slot_id, []).append(write)
        if write.object_ref:
            by_object_ref.setdefault(write.object_ref, []).append(write)

    pending = list(answer_writes)
    reachable_ids: set[int] = set()
    while pending:
        write = pending.pop()
        write_id = id(write)
        if write_id in reachable_ids:
            continue
        reachable_ids.add(write_id)
        current_position = positions[write_id]
        pending.extend(_write_aliases(write, writes))
        source_slot_ids = {
            *((write.state_slot_id,) if write.state_slot_id else ()),
            *write.source_state_slot_ids,
            *write.lineage.source_state_slot_ids,
            *(
                slot_id
                for role in write.lineage.object_roles
                for slot_id in role.source_state_slot_ids
            ),
        }
        for state_slot_id in source_slot_ids:
            pending.extend(
                item
                for item in by_state_slot.get(state_slot_id, ())
                if positions[id(item)] < current_position
            )
        for object_ref in write.dependency_object_refs:
            candidates = tuple(
                item
                for item in by_object_ref.get(object_ref, ())
                if positions[id(item)] < current_position
            )
            if candidates:
                pending.append(candidates[-1])
    return tuple(
        write for write in writes if id(write) in reachable_ids
    )


def _write_aliases(
    write: StateWriteProvenance,
    writes: tuple[StateWriteProvenance, ...],
) -> tuple[StateWriteProvenance, ...]:
    """Return answer/object handles emitted by the same logical write."""
    return tuple(
        item
        for item in writes
        if item is not write
        and item.step_id == write.step_id
        and item.runtime_type == write.runtime_type
        and item.object_ref == write.object_ref
        and (
            (
                write.state_slot_id is not None
                and item.state_slot_id == write.state_slot_id
            )
            or item.output_key == write.output_key
        )
    )


def _terminal_dependency_object_refs(
    writes: tuple[StateWriteProvenance, ...],
) -> tuple[str, ...]:
    produced_object_refs = {
        write.object_ref for write in writes if write.object_ref is not None
    }
    return tuple(
        sorted(
            {
                object_ref
                for write in writes
                for object_ref in write.dependency_object_refs
                if is_object_handle(object_ref)
                and object_ref not in produced_object_refs
            }
        )
    )


def _answer_write_mode(
    writes: tuple[StateWriteProvenance, ...],
) -> str:
    for write in writes:
        mode = _semantic_write_mode(write)
        if mode != "value":
            return mode
    return _semantic_write_mode(writes[0])


def _answer_identity_policy(
    writes: tuple[StateWriteProvenance, ...],
) -> str:
    for write in writes:
        if write.identity_policy != "value_only":
            return write.identity_policy
    return writes[0].identity_policy


def _answer_semantic_roles(
    writes: tuple[StateWriteProvenance, ...],
) -> tuple[str, ...]:
    """Drop scalar output-key labels that only encode method orchestration."""
    return tuple(
        sorted(
            {
                role
                for write in writes
                for role in write.lineage.semantic_roles
                if not (
                    _semantic_write_mode(write) == "value"
                    and role == write.output_key
                )
            }
        )
    )


def _scopes_cover(
    recorded_scopes: tuple[str, ...],
    functional_scopes: tuple[str, ...],
    *,
    scope_parents: dict[str, str | None],
) -> bool:
    functional_scope_set = set(functional_scopes)
    for scope_id in recorded_scopes:
        current: str | None = scope_id
        visible = False
        seen: set[str] = set()
        while current is not None and current not in seen:
            seen.add(current)
            if current in functional_scope_set:
                visible = True
                break
            current = scope_parents.get(current)
        if not visible:
            return False
    return True


def _semantic_write_mode(write: StateWriteProvenance) -> str:
    if write.runtime_type in {
        "Point",
        "Line",
        "Segment",
        "Ray",
        "Circle",
        "Polygon",
    }:
        return write.write_mode
    return "value"


def _object_roles(
    roles: tuple[StateObjectRoleBinding, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        sorted(
            (
                item.role,
                tuple(sorted(set(item.object_refs))),
            )
            for item in roles
        )
    )
