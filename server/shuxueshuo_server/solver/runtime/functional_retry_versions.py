"""Typed StateVersion authority for FunctionalPlan retry memory."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, Sequence

from shuxueshuo_server.solver.runtime.state_identity import (
    ComputationKey,
    FunctionalCallIdentityKey,
    LogicalStateKey,
    RuntimeDestinationKey,
    StateEffectKey,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StrategyDraftValidationError,
)


FunctionalRetryVersionStatus = Literal[
    "runtime_verified",
    "goal_committed",
]
FunctionalRetryResultStatus = FunctionalRetryVersionStatus


class FunctionalRetryCheckpointError(StrategyDraftValidationError):
    """A persisted retry checkpoint is incompatible with the current graph."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"planner_configuration_error: {code}: {message}")


@dataclass(frozen=True)
class FunctionalRetryVersionRecord:
    return_name: str
    version_id: StateVersionId
    logical_state_key: LogicalStateKey
    canonical_producer_call_id: str
    computation_key: ComputationKey
    state_effect_key: StateEffectKey
    previous_version_id: StateVersionId | None
    source_version_ids: tuple[StateVersionId, ...]
    valid_scope_id: str
    result_form: str | None
    free_symbol_refs: tuple[str, ...]
    runtime_destination: RuntimeDestinationKey | None
    status: FunctionalRetryVersionStatus

    def to_payload(self) -> dict[str, Any]:
        return {
            "return_name": self.return_name,
            "version_id": self.version_id.to_payload(),
            "logical_state_key": self.logical_state_key.to_payload(),
            "canonical_producer_call_id": self.canonical_producer_call_id,
            "computation_key": self.computation_key.to_payload(),
            "state_effect_key": self.state_effect_key.to_payload(),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "source_version_ids": [
                item.to_payload() for item in self.source_version_ids
            ],
            "valid_scope_id": self.valid_scope_id,
            "result_form": self.result_form,
            "free_symbol_refs": list(self.free_symbol_refs),
            "runtime_destination": (
                self.runtime_destination.to_payload()
                if self.runtime_destination is not None
                else None
            ),
            "status": self.status,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalRetryVersionRecord":
        return cls(
            return_name=str(payload["return_name"]),
            version_id=StateVersionId.from_payload(
                _mapping(payload["version_id"])
            ),
            logical_state_key=LogicalStateKey.from_payload(
                _mapping(payload["logical_state_key"])
            ),
            canonical_producer_call_id=str(
                payload["canonical_producer_call_id"]
            ),
            computation_key=ComputationKey.from_payload(
                _mapping(payload["computation_key"])
            ),
            state_effect_key=StateEffectKey.from_payload(
                _mapping(payload["state_effect_key"])
            ),
            previous_version_id=(
                StateVersionId.from_payload(
                    _mapping(payload["previous_version_id"])
                )
                if payload.get("previous_version_id") is not None
                else None
            ),
            source_version_ids=tuple(
                StateVersionId.from_payload(item)
                for item in _mapping_items(
                    payload.get("source_version_ids")
                )
            ),
            valid_scope_id=str(payload["valid_scope_id"]),
            result_form=(
                str(payload["result_form"])
                if payload.get("result_form") is not None
                else None
            ),
            free_symbol_refs=tuple(
                str(item) for item in payload.get("free_symbol_refs", ())
            ),
            runtime_destination=(
                RuntimeDestinationKey.from_payload(
                    _mapping(payload["runtime_destination"])
                )
                if payload.get("runtime_destination") is not None
                else None
            ),
            status=_version_status(payload.get("status")),
        )


@dataclass(frozen=True)
class FunctionalRetryResultRecord:
    """Runtime-verified public return without a cross-call StateVersion."""

    return_name: str
    result_id: str
    canonical_producer_call_id: str
    computation_key: ComputationKey
    state_effect_key: StateEffectKey
    valid_scope_id: str
    value_type: str
    result_form: str | None
    free_symbol_refs: tuple[str, ...]
    status: FunctionalRetryResultStatus

    def to_payload(self) -> dict[str, Any]:
        return {
            "return_name": self.return_name,
            "result_id": self.result_id,
            "canonical_producer_call_id": self.canonical_producer_call_id,
            "computation_key": self.computation_key.to_payload(),
            "state_effect_key": self.state_effect_key.to_payload(),
            "valid_scope_id": self.valid_scope_id,
            "value_type": self.value_type,
            "result_form": self.result_form,
            "free_symbol_refs": list(self.free_symbol_refs),
            "status": self.status,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalRetryResultRecord":
        return cls(
            return_name=str(payload["return_name"]),
            result_id=str(payload["result_id"]),
            canonical_producer_call_id=str(
                payload["canonical_producer_call_id"]
            ),
            computation_key=ComputationKey.from_payload(
                _mapping(payload["computation_key"])
            ),
            state_effect_key=StateEffectKey.from_payload(
                _mapping(payload["state_effect_key"])
            ),
            valid_scope_id=str(payload["valid_scope_id"]),
            value_type=str(payload["value_type"]),
            result_form=(
                str(payload["result_form"])
                if payload.get("result_form") is not None
                else None
            ),
            free_symbol_refs=tuple(
                str(item) for item in payload.get("free_symbol_refs", ())
            ),
            status=_version_status(payload.get("status")),
        )


@dataclass(frozen=True)
class FunctionalCommittedCallCheckpoint:
    canonical_call_id: str
    declared_scope_id: str
    call_payload: dict[str, Any]
    identity_key: FunctionalCallIdentityKey
    output_version_ids: tuple[StateVersionId, ...]
    committed_goal_handles: tuple[str, ...]
    output_result_ids: tuple[str, ...] = ()
    execution_scope_id: str | None = None
    return_scope_ids: tuple[tuple[str, str], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "canonical_call_id": self.canonical_call_id,
            "declared_scope_id": self.declared_scope_id,
            "call_payload": dict(self.call_payload),
            "identity_key": self.identity_key.to_payload(),
            "output_version_ids": [
                item.to_payload() for item in self.output_version_ids
            ],
            "output_result_ids": list(self.output_result_ids),
            "committed_goal_handles": list(self.committed_goal_handles),
            "execution_scope_id": self.execution_scope_id,
            "return_scope_ids": dict(self.return_scope_ids),
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalCommittedCallCheckpoint":
        return cls(
            canonical_call_id=str(payload["canonical_call_id"]),
            declared_scope_id=str(payload["declared_scope_id"]),
            call_payload=dict(_mapping(payload["call_payload"])),
            identity_key=FunctionalCallIdentityKey.from_payload(
                _mapping(payload["identity_key"])
            ),
            output_version_ids=tuple(
                StateVersionId.from_payload(item)
                for item in _mapping_items(
                    payload.get("output_version_ids")
                )
            ),
            output_result_ids=tuple(
                str(item)
                for item in payload.get("output_result_ids", ())
            ),
            committed_goal_handles=tuple(
                str(item)
                for item in payload.get("committed_goal_handles", ())
            ),
            execution_scope_id=(
                str(payload["execution_scope_id"])
                if payload.get("execution_scope_id") is not None
                else None
            ),
            return_scope_ids=tuple(
                sorted(
                    (
                        str(name),
                        str(scope_id),
                    )
                    for name, scope_id in _mapping(
                        payload.get("return_scope_ids", {})
                    ).items()
                )
            ),
        )


@dataclass(frozen=True)
class FunctionalRetryGraphCheckpoint:
    source_context_id: str
    problem_id: str
    family_id: str
    family_spec_hash: str
    capability_pack_hash: str
    committed_calls: tuple[FunctionalCommittedCallCheckpoint, ...] = ()
    verified_versions: tuple[FunctionalRetryVersionRecord, ...] = ()
    verified_results: tuple[FunctionalRetryResultRecord, ...] = ()

    @property
    def committed_call_ids(self) -> tuple[str, ...]:
        return tuple(
            item.canonical_call_id for item in self.committed_calls
        )

    @property
    def pinned_execution_scopes(self) -> dict[str, str]:
        result: dict[str, str] = {}
        scopes_by_call: dict[str, set[str]] = {}
        for record in self.verified_versions:
            if record.status == "goal_committed":
                scopes_by_call.setdefault(
                    record.canonical_producer_call_id,
                    set(),
                ).add(record.valid_scope_id)
        for item in self.committed_calls:
            if item.execution_scope_id is not None:
                result[item.canonical_call_id] = item.execution_scope_id
                continue
            inferred = scopes_by_call.get(item.canonical_call_id, set())
            if len(inferred) == 1:
                result[item.canonical_call_id] = next(iter(inferred))
        return result

    @property
    def pinned_return_scopes(self) -> dict[str, dict[str, str]]:
        result = {
            item.canonical_call_id: dict(item.return_scope_ids)
            for item in self.committed_calls
            if item.return_scope_ids
        }
        committed_ids = set(self.committed_call_ids)
        for record in self.verified_versions:
            call_id = record.canonical_producer_call_id
            if (
                record.status == "goal_committed"
                and call_id in committed_ids
            ):
                result.setdefault(call_id, {})[
                    record.return_name
                ] = record.valid_scope_id
        return result

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_context_id": self.source_context_id,
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "family_spec_hash": self.family_spec_hash,
            "capability_pack_hash": self.capability_pack_hash,
            "committed_calls": [
                item.to_payload() for item in self.committed_calls
            ],
            "verified_versions": [
                item.to_payload() for item in self.verified_versions
            ],
            "verified_results": [
                item.to_payload() for item in self.verified_results
            ],
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalRetryGraphCheckpoint":
        try:
            return cls(
                source_context_id=str(payload["source_context_id"]),
                problem_id=str(payload["problem_id"]),
                family_id=str(payload["family_id"]),
                family_spec_hash=str(payload["family_spec_hash"]),
                capability_pack_hash=str(payload["capability_pack_hash"]),
                committed_calls=tuple(
                    FunctionalCommittedCallCheckpoint.from_payload(item)
                    for item in _mapping_items(
                        payload.get("committed_calls")
                    )
                ),
                verified_versions=tuple(
                    FunctionalRetryVersionRecord.from_payload(item)
                    for item in _mapping_items(
                        payload.get("verified_versions")
                    )
                ),
                verified_results=tuple(
                    FunctionalRetryResultRecord.from_payload(item)
                    for item in _mapping_items(
                        payload.get("verified_results")
                    )
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FunctionalRetryCheckpointError(
                "planner.retry_version_checkpoint_invalid",
                str(exc),
            ) from exc


def latest_functional_retry_graph_checkpoint(
    previous_attempts: Sequence[Any],
) -> FunctionalRetryGraphCheckpoint | None:
    """Read the latest internal typed checkpoint, never prompt projections."""

    for attempt in reversed(tuple(previous_attempts)):
        if not isinstance(attempt, Mapping):
            continue
        candidates = (
            attempt.get("functional_retry_graph_checkpoint"),
            _nested_checkpoint(attempt.get("context_derived_retry_state")),
            _nested_checkpoint(attempt.get("planner_retry_state")),
            _nested_checkpoint(attempt.get("context_retry_memory")),
        )
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                return FunctionalRetryGraphCheckpoint.from_payload(candidate)
    return None


def validate_checkpoint_manifest(
    checkpoint: FunctionalRetryGraphCheckpoint,
    *,
    context: Any,
) -> None:
    manifest = context.manifest
    mismatches = {
        name: (expected, actual)
        for name, expected, actual in (
            ("problem_id", checkpoint.problem_id, manifest.problem_id),
            ("family_id", checkpoint.family_id, manifest.family_id),
            (
                "family_spec_hash",
                checkpoint.family_spec_hash,
                manifest.family_spec_hash,
            ),
            (
                "capability_pack_hash",
                checkpoint.capability_pack_hash,
                manifest.capability_pack_hash,
            ),
        )
        if expected != actual
    }
    if mismatches:
        raise FunctionalRetryCheckpointError(
            "planner.retry_context_incompatible",
            json.dumps(mismatches, ensure_ascii=False, sort_keys=True),
        )


def restore_committed_calls(
    candidate: dict[str, Any],
    checkpoint: FunctionalRetryGraphCheckpoint,
) -> dict[str, Any]:
    """Restore exact committed wire calls without semantic/string guessing."""

    result = json.loads(json.dumps(candidate))
    raw_scopes = result.get("scopes")
    if not isinstance(raw_scopes, list):
        return candidate
    scope_by_id = {
        scope.get("scope_id"): scope
        for scope in raw_scopes
        if isinstance(scope, dict)
        and isinstance(scope.get("scope_id"), str)
        and isinstance(scope.get("calls"), list)
    }
    committed_ids = set(checkpoint.committed_call_ids)
    for scope in scope_by_id.values():
        calls = scope.get("calls")
        if not isinstance(calls, list):
            continue
        calls[:] = [
            call
            for call in calls
            if (
                call.get("call_id")
                if isinstance(call, dict)
                else None
            )
            not in committed_ids
        ]

    restored_by_scope: dict[str, list[dict[str, Any]]] = {}
    for committed in checkpoint.committed_calls:
        scope = scope_by_id.get(committed.declared_scope_id)
        if scope is None:
            scope = {
                "scope_id": committed.declared_scope_id,
                "label": committed.declared_scope_id,
                "calls": [],
            }
            raw_scopes.append(scope)
            scope_by_id[committed.declared_scope_id] = scope
        restored_by_scope.setdefault(
            committed.declared_scope_id,
            [],
        ).append(dict(committed.call_payload))
    for scope_id, restored_calls in restored_by_scope.items():
        scope = scope_by_id[scope_id]
        scope["calls"][:] = [*restored_calls, *scope["calls"]]
    return result


def build_functional_retry_graph_checkpoint(
    *,
    context: Any,
    reconciliation: Any,
    call_memory: Any,
    provenance: Sequence[Any],
) -> FunctionalRetryGraphCheckpoint:
    """Build a checkpoint only from runtime-verified canonical returns."""

    committed_ids = set(call_memory.committed_call_ids)
    verified_ids = committed_ids | set(
        call_memory.runtime_verified_call_ids
    )
    call_payloads = {
        call.call_id: (scope.scope_id, call.to_payload())
        for scope in reconciliation.plan.scopes
        for call in scope.calls
    }
    reconciled_by_id = {
        call.call_id: call for call in reconciliation.calls
    }
    call_by_step = {
        step_id: item.call_id
        for item in reconciliation.projection_map
        for step_id in item.step_ids
    }
    placement_keys = _placement_identity_keys(reconciliation)
    placements_by_call = {
        item.canonical_call_id: item
        for item in getattr(reconciliation, "call_placements", ())
    }
    memory_by_call = {
        item.call_id: item for item in call_memory.entries
    }
    form_by_return = {
        (item.call_id, result.return_name): result.actual_form
        for item in call_memory.entries
        for result in item.result_snapshots
    }
    snapshots_by_return = {
        (item.call_id, result.return_name): result
        for item in call_memory.entries
        for result in item.result_snapshots
    }
    provenance_by_return: dict[tuple[str, str], Any] = {}
    for write in provenance:
        call_id = call_by_step.get(write.step_id)
        return_name = getattr(write, "return_name", None)
        if (
            call_id in verified_ids
            and isinstance(return_name, str)
            and write.selected_version_id is not None
        ):
            provenance_by_return[(call_id, return_name)] = write

    records: list[FunctionalRetryVersionRecord] = []
    result_records: list[FunctionalRetryResultRecord] = []
    for call in reconciliation.plan.calls:
        call_id = call.call_id
        if call_id not in verified_ids:
            continue
        resolved = reconciled_by_id.get(call_id)
        identity_key = placement_keys.get(call_id)
        if resolved is None or identity_key is None:
            continue
        for allocation in resolved.returns:
            snapshot = snapshots_by_return.get(
                (call_id, allocation.return_name)
            )
            write = provenance_by_return.get(
                (call_id, allocation.return_name)
            )
            if allocation.selected_version_id is None:
                if (
                    snapshot is None
                    or snapshot.value_omitted_reason
                    == "runtime_value_unavailable"
                ):
                    continue
                producer_call_id = (
                    allocation.canonical_producer_call_id or call_id
                )
                result_records.append(
                    FunctionalRetryResultRecord(
                        return_name=allocation.return_name,
                        result_id=(
                            f"{producer_call_id}."
                            f"{allocation.return_name}"
                        ),
                        canonical_producer_call_id=producer_call_id,
                        computation_key=(
                            allocation.computation_key
                            or identity_key.computation_key
                        ),
                        state_effect_key=identity_key.state_effect_key,
                        valid_scope_id=allocation.valid_scope,
                        value_type=allocation.runtime_type,
                        result_form=snapshot.actual_form,
                        free_symbol_refs=tuple(
                            allocation.free_symbol_refs
                        ),
                        status=(
                            "goal_committed"
                            if call_id in committed_ids
                            else "runtime_verified"
                        ),
                    )
                )
                continue
            if (
                write is None
                or write.selected_version_id is None
                or write.logical_state_key is None
                or write.computation_key is None
            ):
                continue
            records.append(
                FunctionalRetryVersionRecord(
                    return_name=allocation.return_name,
                    version_id=write.selected_version_id,
                    logical_state_key=write.logical_state_key,
                    canonical_producer_call_id=(
                        allocation.canonical_producer_call_id or call_id
                    ),
                    computation_key=write.computation_key,
                    state_effect_key=identity_key.state_effect_key,
                    previous_version_id=write.previous_version_id,
                    source_version_ids=_direct_checkpoint_source_versions(
                        computation_key=write.computation_key,
                        previous_version_id=write.previous_version_id,
                    ),
                    valid_scope_id=allocation.valid_scope,
                    result_form=form_by_return.get(
                        (call_id, allocation.return_name)
                    ),
                    free_symbol_refs=tuple(allocation.free_symbol_refs),
                    runtime_destination=write.runtime_destination_key,
                    status=(
                        "goal_committed"
                        if call_id in committed_ids
                        else "runtime_verified"
                    ),
                )
            )

    records_by_call: dict[str, list[FunctionalRetryVersionRecord]] = {}
    for record in records:
        records_by_call.setdefault(
            record.canonical_producer_call_id,
            [],
        ).append(record)
    results_by_call: dict[str, list[FunctionalRetryResultRecord]] = {}
    for record in result_records:
        results_by_call.setdefault(
            record.canonical_producer_call_id,
            [],
        ).append(record)
    committed_calls: list[FunctionalCommittedCallCheckpoint] = []
    for call in reconciliation.plan.calls:
        call_id = call.call_id
        if call_id not in committed_ids:
            continue
        call_source = call_payloads.get(call_id)
        identity_key = placement_keys.get(call_id)
        memory = memory_by_call.get(call_id)
        placement = placements_by_call.get(call_id)
        missing_checkpoint_inputs = tuple(
            name
            for name, value in (
                ("call_payload", call_source),
                ("identity_key", identity_key),
                ("call_memory", memory),
            )
            if value is None
        )
        if missing_checkpoint_inputs:
            raise FunctionalRetryCheckpointError(
                "planner.retry_version_checkpoint_invalid",
                (
                    f"committed call {call_id} is missing "
                    f"{', '.join(missing_checkpoint_inputs)}"
                ),
            )
        resolved = reconciled_by_id.get(call_id)
        output_records: list[FunctionalRetryVersionRecord] = []
        output_result_records: list[FunctionalRetryResultRecord] = []
        if resolved is not None:
            for allocation in resolved.returns:
                producer_call_id = (
                    allocation.canonical_producer_call_id or call_id
                )
                output_records.extend(
                    record
                    for record in records_by_call.get(producer_call_id, ())
                    if record.return_name == allocation.return_name
                )
                output_result_records.extend(
                    record
                    for record in results_by_call.get(
                        producer_call_id,
                        (),
                    )
                    if record.return_name == allocation.return_name
                )
        versioned_return_names = {
            allocation.return_name
            for allocation in (resolved.returns if resolved is not None else ())
            if allocation.selected_version_id is not None
        }
        materialized_return_names = {
            snapshot.return_name
            for snapshot in memory.result_snapshots
            if snapshot.return_name in versioned_return_names
        }
        checkpointed_return_names = {
            record.return_name for record in output_records
        }
        missing_materialized_returns = tuple(
            sorted(materialized_return_names - checkpointed_return_names)
        )
        if missing_materialized_returns:
            raise FunctionalRetryCheckpointError(
                "planner.retry_version_checkpoint_invalid",
                (
                    f"committed call {call_id} has no typed version "
                    "checkpoint for "
                    f"{', '.join(missing_materialized_returns)}"
                ),
            )
        if not output_records and not output_result_records:
            raise FunctionalRetryCheckpointError(
                "planner.retry_version_checkpoint_invalid",
                (
                    f"committed call {call_id} for "
                    f"{', '.join(memory.committed_goal_handles) or 'a verified goal'} "
                    "has no typed output version anchor"
                ),
            )
        declared_scope_id, call_payload = call_source
        committed_calls.append(
            FunctionalCommittedCallCheckpoint(
                canonical_call_id=call_id,
                declared_scope_id=declared_scope_id,
                call_payload=call_payload,
                identity_key=identity_key,
                output_version_ids=tuple(
                    item.version_id for item in output_records
                ),
                output_result_ids=tuple(
                    item.result_id for item in output_result_records
                ),
                committed_goal_handles=tuple(
                    memory.committed_goal_handles
                ),
                execution_scope_id=(
                    placement.execution_scope_id
                    if placement is not None
                    else declared_scope_id
                ),
                return_scope_ids=tuple(
                    sorted(
                        placement.return_scopes.items()
                        if placement is not None
                        else ()
                    )
                ),
            )
        )

    committed_version_ids = {
        version_id
        for committed in committed_calls
        for version_id in committed.output_version_ids
    }
    records = [
        replace(
            record,
            status=(
                "goal_committed"
                if record.version_id in committed_version_ids
                else "runtime_verified"
            ),
        )
        for record in records
    ]
    committed_result_ids = {
        result_id
        for committed in committed_calls
        for result_id in committed.output_result_ids
    }
    result_records = [
        replace(
            record,
            status=(
                "goal_committed"
                if record.result_id in committed_result_ids
                else "runtime_verified"
            ),
        )
        for record in result_records
    ]

    manifest = context.manifest
    return FunctionalRetryGraphCheckpoint(
        source_context_id=manifest.context_id,
        problem_id=manifest.problem_id,
        family_id=manifest.family_id,
        family_spec_hash=manifest.family_spec_hash,
        capability_pack_hash=manifest.capability_pack_hash,
        committed_calls=tuple(committed_calls),
        verified_versions=tuple(records),
        verified_results=tuple(result_records),
    )


def verify_restored_checkpoint(
    checkpoint: FunctionalRetryGraphCheckpoint,
    *,
    reconciliation: Any,
    handle_registry: Any,
) -> None:
    """Verify that B2/B3 reproduced every committed typed version."""

    calls = {item.call_id: item for item in reconciliation.calls}
    placement_keys = _placement_identity_keys(reconciliation)
    expected_records = {
        (item.canonical_producer_call_id, item.return_name): item
        for item in checkpoint.verified_versions
        if item.status == "goal_committed"
    }
    expected_versions = {
        item.version_id: item for item in expected_records.values()
    }
    expected_result_records = {
        (item.canonical_producer_call_id, item.return_name): item
        for item in checkpoint.verified_results
        if item.status == "goal_committed"
    }
    expected_result_ids = {
        item.result_id: item
        for item in expected_result_records.values()
    }
    restored_call_ids: dict[str, str] = {}
    for committed in checkpoint.committed_calls:
        if (
            not committed.output_version_ids
            and not committed.output_result_ids
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_version_checkpoint_invalid",
                (
                    f"committed call {committed.canonical_call_id} "
                    "has no typed output anchor"
                ),
            )
        missing_versions = tuple(
            version_id
            for version_id in committed.output_version_ids
            if version_id not in expected_versions
        )
        if missing_versions:
            raise FunctionalRetryCheckpointError(
                "planner.retry_version_checkpoint_invalid",
                (
                    f"committed call {committed.canonical_call_id} "
                    "references an unverified output version"
                ),
            )
        missing_results = tuple(
            result_id
            for result_id in committed.output_result_ids
            if result_id not in expected_result_ids
        )
        if missing_results:
            raise FunctionalRetryCheckpointError(
                "planner.retry_version_checkpoint_invalid",
                (
                    f"committed call {committed.canonical_call_id} "
                    "references an unverified call result"
                ),
            )
        actual_call_id = _canonical_restored_call_id(
            committed.canonical_call_id,
            reconciliation=reconciliation,
        )
        restored_call_ids[committed.canonical_call_id] = actual_call_id
        actual = calls.get(actual_call_id)
        if actual is None:
            raise FunctionalRetryCheckpointError(
                "planner.retry_canonical_producer_drift",
                f"missing committed call {committed.canonical_call_id}",
            )
        actual_key = placement_keys.get(actual_call_id)
        if not _restored_identity_key_compatible(
            committed.identity_key,
            actual_key,
            wire_arg_names=frozenset(
                _mapping(committed.call_payload.get("args", {}))
            ),
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_canonical_producer_drift",
                f"identity changed for {committed.canonical_call_id}",
            )

    actual_allocations: dict[tuple[str, str], Any] = {}
    for call in reconciliation.calls:
        for allocation in call.returns:
            key = (
                getattr(
                    allocation,
                    "canonical_producer_call_id",
                    None,
                )
                or call.call_id,
                allocation.return_name,
            )
            actual_allocations[key] = allocation

    for key, expected in expected_records.items():
        actual_call_id = restored_call_ids.get(key[0], key[0])
        allocation = actual_allocations.get(
            (actual_call_id, key[1])
        )
        if allocation is None:
            raise FunctionalRetryCheckpointError(
                "planner.retry_state_version_drift",
                f"missing committed return {key[0]}.{key[1]}",
            )
        if (
            allocation.selected_version_id != expected.version_id
            or allocation.logical_state_key != expected.logical_state_key
            or not _computation_keys_retry_compatible(
                expected.computation_key,
                allocation.computation_key,
                wire_arg_names=_checkpoint_wire_arg_names(
                    checkpoint,
                    key[0],
                    version_id=expected.version_id,
                ),
            )
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_state_version_drift",
                f"call={key[0]}, return={key[1]}",
            )
        actual_direct_sources = _direct_checkpoint_source_versions(
            computation_key=allocation.computation_key,
            previous_version_id=allocation.previous_version_id,
        )
        expected_direct_sources = _direct_checkpoint_source_versions(
            computation_key=expected.computation_key,
            previous_version_id=expected.previous_version_id,
        )
        if (
            allocation.previous_version_id != expected.previous_version_id
            or actual_direct_sources != expected_direct_sources
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_transition_chain_drift",
                f"call={key[0]}, return={key[1]}",
            )
        if allocation.valid_scope == expected.valid_scope_id:
            continue
        if allocation.valid_scope not in handle_registry.ancestor_scopes(
            expected.valid_scope_id
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_locked_scope_drift",
                (
                    f"call={key[0]}, return={key[1]}, "
                    f"expected={expected.valid_scope_id}, "
                    f"actual={allocation.valid_scope}"
                ),
            )

    for key, expected in expected_result_records.items():
        actual_call_id = restored_call_ids.get(key[0], key[0])
        allocation = actual_allocations.get(
            (actual_call_id, key[1])
        )
        if allocation is None:
            raise FunctionalRetryCheckpointError(
                "planner.retry_state_version_drift",
                f"missing committed return {key[0]}.{key[1]}",
            )
        if (
            allocation.selected_version_id is not None
            or allocation.runtime_type != expected.value_type
            or not _computation_keys_retry_compatible(
                expected.computation_key,
                allocation.computation_key,
                wire_arg_names=_checkpoint_wire_arg_names(
                    checkpoint,
                    key[0],
                    result_id=expected.result_id,
                ),
            )
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_state_version_drift",
                f"call={key[0]}, return={key[1]}",
            )
        if allocation.valid_scope == expected.valid_scope_id:
            continue
        if allocation.valid_scope not in handle_registry.ancestor_scopes(
            expected.valid_scope_id
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_locked_scope_drift",
                (
                    f"call={key[0]}, return={key[1]}, "
                    f"expected={expected.valid_scope_id}, "
                    f"actual={allocation.valid_scope}"
                ),
            )


def _direct_checkpoint_source_versions(
    *,
    computation_key: ComputationKey,
    previous_version_id: StateVersionId | None,
) -> tuple[StateVersionId, ...]:
    """Project only versions that define the restored computation.

    State provenance may also carry transitive evidence and companion object
    versions. Those remain available in PlannerStateContext, but they do not
    define the retry identity of this call and may legitimately differ when an
    equivalent producer is referenced more explicitly in a later candidate.
    """

    return tuple(
        dict.fromkeys(
            (
                *(
                    (previous_version_id,)
                    if previous_version_id is not None
                    else ()
                ),
                *(
                    binding.version_id
                    for binding in computation_key.arg_bindings
                    if binding.version_id is not None
                ),
            )
        )
    )


def verify_restored_runtime_checkpoint(
    expected: FunctionalRetryGraphCheckpoint,
    actual: FunctionalRetryGraphCheckpoint,
) -> None:
    """Verify runtime-grounded form and destination for restored versions."""

    expected_records = {
        (item.canonical_producer_call_id, item.return_name): item
        for item in expected.verified_versions
        if item.status == "goal_committed"
    }
    actual_records = {
        (item.canonical_producer_call_id, item.return_name): item
        for item in actual.verified_versions
    }
    for key, expected_record in expected_records.items():
        actual_record = actual_records.get(key)
        if actual_record is None:
            raise FunctionalRetryCheckpointError(
                "planner.retry_state_version_drift",
                f"runtime did not verify committed return {key[0]}.{key[1]}",
            )
        if (
            actual_record.version_id != expected_record.version_id
            or actual_record.runtime_destination
            != expected_record.runtime_destination
            or actual_record.result_form != expected_record.result_form
            or actual_record.free_symbol_refs
            != expected_record.free_symbol_refs
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_state_version_drift",
                f"runtime state changed for {key[0]}.{key[1]}",
            )
    expected_results = {
        (item.canonical_producer_call_id, item.return_name): item
        for item in expected.verified_results
        if item.status == "goal_committed"
    }
    actual_results = {
        (item.canonical_producer_call_id, item.return_name): item
        for item in actual.verified_results
    }
    for key, expected_result in expected_results.items():
        actual_result = actual_results.get(key)
        if actual_result is None:
            raise FunctionalRetryCheckpointError(
                "planner.retry_state_version_drift",
                f"runtime did not verify committed return {key[0]}.{key[1]}",
            )
        if (
            actual_result.result_id != expected_result.result_id
            or actual_result.value_type != expected_result.value_type
            or actual_result.result_form != expected_result.result_form
            or actual_result.free_symbol_refs
            != expected_result.free_symbol_refs
        ):
            raise FunctionalRetryCheckpointError(
                "planner.retry_state_version_drift",
                f"runtime result changed for {key[0]}.{key[1]}",
            )


def expand_retry_dependency_graph_with_versions(
    reconciliation: Any,
    *,
    checkpoint: FunctionalRetryGraphCheckpoint | None = None,
) -> dict[str, tuple[str, ...]]:
    """Add exact StateVersion producer edges to the retry dependency graph."""

    graph = {
        call_id: list(dependencies)
        for call_id, dependencies in reconciliation.dependency_graph.items()
    }
    producer_by_version: dict[StateVersionId, str] = {}
    source_versions_by_call: dict[str, set[StateVersionId]] = {}
    for call in reconciliation.calls:
        graph.setdefault(call.call_id, [])
        for allocation in call.returns:
            if allocation.selected_version_id is not None:
                producer_by_version.setdefault(
                    allocation.selected_version_id,
                    allocation.canonical_producer_call_id or call.call_id,
                )
            sources = source_versions_by_call.setdefault(
                call.call_id,
                set(),
            )
            sources.update(allocation.source_version_ids)
            if allocation.previous_version_id is not None:
                sources.add(allocation.previous_version_id)
    if checkpoint is not None:
        for record in checkpoint.verified_versions:
            producer_by_version.setdefault(
                record.version_id,
                record.canonical_producer_call_id,
            )
    for call_id, source_versions in source_versions_by_call.items():
        for version_id in source_versions:
            producer = producer_by_version.get(version_id)
            if (
                producer is not None
                and producer != call_id
                and producer not in graph[call_id]
            ):
                graph[call_id].append(producer)
    return {
        call_id: tuple(dependencies)
        for call_id, dependencies in graph.items()
    }


def _placement_identity_keys(
    reconciliation: Any,
) -> dict[str, FunctionalCallIdentityKey]:
    result: dict[str, FunctionalCallIdentityKey] = {}
    for payload in getattr(
        reconciliation,
        "state_placement_decisions",
        (),
    ):
        if not isinstance(payload, Mapping):
            continue
        call_id = payload.get("canonical_call_id")
        identity = payload.get("identity_key")
        if isinstance(call_id, str) and isinstance(identity, Mapping):
            result[call_id] = FunctionalCallIdentityKey.from_payload(identity)
    return result


def _restored_identity_key_compatible(
    expected: FunctionalCallIdentityKey,
    actual: FunctionalCallIdentityKey | None,
    *,
    wire_arg_names: frozenset[str] = frozenset(),
) -> bool:
    """Allow new B3-validated projections without changing the calculation."""

    if (
        actual is None
        or not _computation_keys_retry_compatible(
            expected.computation_key,
            actual.computation_key,
            wire_arg_names=wire_arg_names,
        )
    ):
        return False
    actual_effects = {
        item.return_name: item
        for item in actual.state_effect_key.returns
    }
    return all(
        actual_effects.get(item.return_name) == item
        for item in expected.state_effect_key.returns
    )


def _computation_keys_retry_compatible(
    expected: ComputationKey,
    actual: ComputationKey | None,
    *,
    wire_arg_names: frozenset[str],
) -> bool:
    """Keep wire and state-bearing bindings exact across retry.

    Resolver-owned object-only bindings describe deterministic planning
    metadata such as a preserved free-symbol basis. They are recomputed from
    the new Context and may be represented more explicitly without changing
    the executable StateVersion chain. State, condition and call-result
    bindings remain exact regardless of wire ownership.
    """

    if actual is None or actual.capability_id != expected.capability_id:
        return False
    expected_by_arg = _bindings_by_arg(expected)
    actual_by_arg = _bindings_by_arg(actual)
    strict_arg_names = set(wire_arg_names)
    strict_arg_names.update(
        binding.arg_name
        for binding in (*expected.arg_bindings, *actual.arg_bindings)
        if (
            binding.version_id is not None
            or binding.condition_id is not None
            or binding.call_result_id is not None
        )
    )
    return all(
        expected_by_arg.get(arg_name, ()) == actual_by_arg.get(arg_name, ())
        for arg_name in strict_arg_names
    )


def _bindings_by_arg(
    key: ComputationKey,
) -> dict[str, tuple[Any, ...]]:
    grouped: dict[str, list[Any]] = {}
    for binding in key.arg_bindings:
        grouped.setdefault(binding.arg_name, []).append(binding)
    return {
        arg_name: tuple(bindings)
        for arg_name, bindings in grouped.items()
    }


def _checkpoint_wire_arg_names(
    checkpoint: FunctionalRetryGraphCheckpoint,
    call_id: str,
    *,
    version_id: StateVersionId | None = None,
    result_id: str | None = None,
) -> frozenset[str]:
    """Return wire-owned args for the committed call anchoring an output.

    A reused StateVersion keeps the existing producer as its canonical
    producer, while the checkpoint locks the later wire call that requested
    the reuse. Resolve through the output anchor before falling back to the
    producer id so object-only wire bindings remain strict across retry.
    """

    committed_calls = tuple(
        item
        for item in checkpoint.committed_calls
        if (
            item.canonical_call_id == call_id
            or (
                version_id is not None
                and version_id in item.output_version_ids
            )
            or (
                result_id is not None
                and result_id in item.output_result_ids
            )
        )
    )
    return frozenset(
        str(name)
        for committed in committed_calls
        for args in (committed.call_payload.get("args", {}),)
        if isinstance(args, Mapping)
        for name in args
    )


def _canonical_restored_call_id(
    call_id: str,
    *,
    reconciliation: Any,
) -> str:
    aliases = getattr(reconciliation, "call_aliases", {}) or {}
    current = call_id
    visited: set[str] = set()
    while (
        current in aliases
        and current not in visited
        and isinstance(aliases[current], str)
    ):
        visited.add(current)
        current = aliases[current]
    return current


def _nested_checkpoint(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("functional_retry_graph_checkpoint")
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"expected mapping, got {type(value).__name__}")
    return value


def _mapping_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise TypeError("expected a sequence of mappings")
    return tuple(_mapping(item) for item in value)


def _version_status(value: Any) -> FunctionalRetryVersionStatus:
    if value in {"runtime_verified", "goal_committed"}:
        return value
    raise ValueError(f"invalid retry version status: {value!r}")


__all__ = [
    "FunctionalCommittedCallCheckpoint",
    "FunctionalRetryCheckpointError",
    "FunctionalRetryGraphCheckpoint",
    "FunctionalRetryResultRecord",
    "FunctionalRetryResultStatus",
    "FunctionalRetryVersionRecord",
    "FunctionalRetryVersionStatus",
    "build_functional_retry_graph_checkpoint",
    "expand_retry_dependency_graph_with_versions",
    "latest_functional_retry_graph_checkpoint",
    "restore_committed_calls",
    "validate_checkpoint_manifest",
    "verify_restored_checkpoint",
    "verify_restored_runtime_checkpoint",
]
