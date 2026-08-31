"""Typed write authority for code-owned Method companion outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, TypeAlias

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalReturnAllocation,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    RuntimeDestinationKey,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import ProjectedStateWrite
from shuxueshuo_server.solver.extraction.source_identity import stable_hash


@dataclass(frozen=True)
class StateOutputDestinationAuthority:
    logical_state_key: LogicalStateKey
    selected_version_id: StateVersionId
    previous_version_id: StateVersionId | None
    runtime_destination: RuntimeDestinationKey
    allocation_action: str
    kind: Literal["state"] = field(default="state", init=False)

    @property
    def runtime_path(self) -> str:
        return self.runtime_destination.runtime_path or ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "logical_state_key": self.logical_state_key.to_payload(),
            "selected_version_id": self.selected_version_id.to_payload(),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "runtime_destination": self.runtime_destination.to_payload(),
            "allocation_action": self.allocation_action,
        }


@dataclass(frozen=True)
class CallResultOutputDestinationAuthority:
    call_id: str
    return_name: str
    runtime_path: str
    kind: Literal["call_result"] = field(default="call_result", init=False)

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "call_id": self.call_id,
            "return_name": self.return_name,
            "runtime_path": self.runtime_path,
        }


MethodOutputDestinationAuthority: TypeAlias = (
    StateOutputDestinationAuthority | CallResultOutputDestinationAuthority
)


@dataclass(frozen=True, order=True)
class MethodOutputRegistrationAuthority:
    handle: str
    runtime_path: str
    runtime_type: str
    basis: Literal[
        "allocation_handle",
        "state_handle",
        "exact_call_result",
    ]

    def to_payload(self) -> dict[str, str]:
        return {
            "handle": self.handle,
            "runtime_path": self.runtime_path,
            "runtime_type": self.runtime_type,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class MethodOutputWriteAuthority:
    call_id: str
    invocation_id: str
    method_id: str
    output_name: str
    function_return_name: str
    runtime_type: str
    valid_scope: str
    allocation_signature: str
    destination: MethodOutputDestinationAuthority
    registration_aliases: tuple[MethodOutputRegistrationAuthority, ...]
    authority_signature: str = field(init=False)
    schema_version: str = "method-output-write-authority/v1"

    def __post_init__(self) -> None:
        required = (
            self.call_id,
            self.invocation_id,
            self.method_id,
            self.output_name,
            self.function_return_name,
            self.runtime_type,
            self.valid_scope,
            self.allocation_signature,
            self.destination.runtime_path,
        )
        if any(not item for item in required):
            raise ValueError(
                "planner.method_output_write_authority_missing: output "
                "authority fields must be non-empty"
            )
        handles = tuple(item.handle for item in self.registration_aliases)
        if len(handles) != len(set(handles)):
            raise ValueError(
                "planner.method_output_write_authority_drift: duplicate "
                "output registration alias"
            )
        if any(
            item.runtime_path != self.destination.runtime_path
            or item.runtime_type != self.runtime_type
            for item in self.registration_aliases
        ):
            raise ValueError(
                "planner.method_output_write_authority_drift: output aliases "
                "must use the authorized path and runtime type"
            )
        object.__setattr__(
            self,
            "authority_signature",
            stable_hash(self.authority_payload(include_signature=False)),
        )

    @property
    def runtime_path(self) -> str:
        return self.destination.runtime_path

    def authority_payload(self, *, include_signature: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "call_id": self.call_id,
            "invocation_id": self.invocation_id,
            "method_id": self.method_id,
            "output_name": self.output_name,
            "function_return_name": self.function_return_name,
            "runtime_type": self.runtime_type,
            "valid_scope": self.valid_scope,
            "allocation_signature": self.allocation_signature,
            "destination": self.destination.to_payload(),
            "registration_aliases": [
                item.to_payload() for item in self.registration_aliases
            ],
        }
        if include_signature:
            payload["authority_signature"] = self.authority_signature
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MethodOutputWriteAuthority":
        if payload.get("schema_version") != "method-output-write-authority/v1":
            raise ValueError("unsupported Method output write authority contract")
        destination_payload = _mapping(payload.get("destination"))
        destination = _destination_from_payload(destination_payload)
        aliases_raw = payload.get("registration_aliases", ())
        if not isinstance(aliases_raw, list | tuple):
            raise ValueError("Method output registration aliases must be a list")
        aliases = tuple(
            MethodOutputRegistrationAuthority(
                handle=_required_string(_mapping(item), "handle"),
                runtime_path=_required_string(_mapping(item), "runtime_path"),
                runtime_type=_required_string(_mapping(item), "runtime_type"),
                basis=_required_string(_mapping(item), "basis"),  # type: ignore[arg-type]
            )
            for item in aliases_raw
        )
        authority = cls(
            call_id=_required_string(payload, "call_id"),
            invocation_id=_required_string(payload, "invocation_id"),
            method_id=_required_string(payload, "method_id"),
            output_name=_required_string(payload, "output_name"),
            function_return_name=_required_string(
                payload, "function_return_name"
            ),
            runtime_type=_required_string(payload, "runtime_type"),
            valid_scope=_required_string(payload, "valid_scope"),
            allocation_signature=_required_string(
                payload, "allocation_signature"
            ),
            destination=destination,
            registration_aliases=aliases,
        )
        if payload.get("authority_signature") != authority.authority_signature:
            raise ValueError("Method output write authority signature drift")
        return authority

    def verify(
        self,
        *,
        allocation: FunctionalReturnAllocation,
        runtime_path: str,
    ) -> None:
        expected = (
            stable_hash(allocation.to_payload()),
            allocation.call_id,
            allocation.return_name,
            allocation.runtime_type,
            allocation.valid_scope,
            runtime_path,
        )
        observed = (
            self.allocation_signature,
            self.call_id,
            self.function_return_name,
            self.runtime_type,
            self.valid_scope,
            self.runtime_path,
        )
        if observed != expected:
            raise ValueError(
                "planner.method_output_write_authority_drift: allocation or "
                f"runtime destination differs: expected={expected!r}, "
                f"observed={observed!r}"
            )


class MethodOutputWriteAuthorityFinalizer:
    """Freeze one companion output from exact return allocation authority."""

    @staticmethod
    def finalize(
        *,
        call_id: str,
        invocation_id: str,
        method_id: str,
        output_name: str,
        function_return_name: str,
        runtime_type: str,
        allocation: FunctionalReturnAllocation,
        projected_write: ProjectedStateWrite | None,
        runtime_path: str,
    ) -> MethodOutputWriteAuthority:
        _validate_allocation(
            call_id=call_id,
            function_return_name=function_return_name,
            runtime_type=runtime_type,
            allocation=allocation,
            projected_write=projected_write,
        )
        destination: MethodOutputDestinationAuthority
        if allocation.logical_state_key is not None:
            if allocation.selected_version_id is None:
                raise _missing(
                    call_id,
                    output_name,
                    "state output has no selected StateVersion",
                )
            destination = StateOutputDestinationAuthority(
                logical_state_key=allocation.logical_state_key,
                selected_version_id=allocation.selected_version_id,
                previous_version_id=allocation.previous_version_id,
                runtime_destination=RuntimeDestinationKey(
                    allocation.logical_state_key.object_id,
                    allocation.logical_state_key.state_kind,
                    allocation.logical_state_key.runtime_type,
                    runtime_path,
                ),
                allocation_action=str(allocation.allocation_action or ""),
            )
        else:
            if allocation.allocation_action != "call_local_value":
                raise _drift(
                    call_id,
                    output_name,
                    "value output is not a call-local allocation",
                )
            destination = CallResultOutputDestinationAuthority(
                call_id=call_id,
                return_name=function_return_name,
                runtime_path=runtime_path,
            )
        aliases = _registration_aliases(allocation, runtime_path=runtime_path)
        authority = MethodOutputWriteAuthority(
            call_id=call_id,
            invocation_id=invocation_id,
            method_id=method_id,
            output_name=output_name,
            function_return_name=function_return_name,
            runtime_type=runtime_type,
            valid_scope=allocation.valid_scope,
            allocation_signature=stable_hash(allocation.to_payload()),
            destination=destination,
            registration_aliases=aliases,
        )
        authority.verify(allocation=allocation, runtime_path=runtime_path)
        return authority


def _validate_allocation(
    *,
    call_id: str,
    function_return_name: str,
    runtime_type: str,
    allocation: FunctionalReturnAllocation,
    projected_write: ProjectedStateWrite | None,
) -> None:
    expected = (
        call_id,
        function_return_name,
        runtime_type,
    )
    observed = (
        allocation.call_id,
        allocation.return_name,
        allocation.runtime_type,
    )
    if observed != expected:
        raise _drift(
            call_id,
            function_return_name,
            f"return allocation differs: expected={expected!r}, observed={observed!r}",
        )
    if projected_write is None:
        raise _missing(
            call_id,
            function_return_name,
            "return allocation has no projected write",
        )
    projected = (
        projected_write.step_id,
        projected_write.return_name,
        projected_write.runtime_type,
        projected_write.valid_scope_id,
        projected_write.write_mode,
        projected_write.math_object_id,
        projected_write.logical_state_key,
        projected_write.typed_slot_id,
        projected_write.selected_version_id,
        projected_write.previous_version_id,
        projected_write.allocation_action,
    )
    allocated = (
        allocation.call_id,
        allocation.return_name,
        allocation.runtime_type,
        allocation.valid_scope,
        allocation.write_mode,
        allocation.math_object_id,
        allocation.logical_state_key,
        allocation.typed_slot_id,
        allocation.selected_version_id,
        allocation.previous_version_id,
        allocation.allocation_action,
    )
    if projected != allocated:
        raise _drift(
            call_id,
            function_return_name,
            "projected write differs from return allocation",
        )


def _registration_aliases(
    allocation: FunctionalReturnAllocation,
    *,
    runtime_path: str,
) -> tuple[MethodOutputRegistrationAuthority, ...]:
    candidates: list[tuple[str | None, str]] = [
        (allocation.handle, "allocation_handle"),
        (allocation.state_handle, "state_handle"),
    ]
    if allocation.allocation_action == "call_local_value":
        candidates.append(
            (
                f"runtime:{allocation.call_id}:{allocation.return_name}",
                "exact_call_result",
            )
        )
    result: list[MethodOutputRegistrationAuthority] = []
    seen: set[str] = set()
    for handle, basis in candidates:
        if not handle or handle in seen:
            continue
        seen.add(handle)
        result.append(
            MethodOutputRegistrationAuthority(
                handle=handle,
                runtime_path=runtime_path,
                runtime_type=allocation.runtime_type,
                basis=basis,  # type: ignore[arg-type]
            )
        )
    return tuple(result)


def _destination_from_payload(
    payload: Mapping[str, Any],
) -> MethodOutputDestinationAuthority:
    kind = payload.get("kind")
    if kind == "state":
        previous = payload.get("previous_version_id")
        return StateOutputDestinationAuthority(
            logical_state_key=LogicalStateKey.from_payload(
                _mapping(payload.get("logical_state_key"))
            ),
            selected_version_id=StateVersionId.from_payload(
                _mapping(payload.get("selected_version_id"))
            ),
            previous_version_id=(
                StateVersionId.from_payload(_mapping(previous))
                if previous is not None
                else None
            ),
            runtime_destination=RuntimeDestinationKey.from_payload(
                _mapping(payload.get("runtime_destination"))
            ),
            allocation_action=_required_string(payload, "allocation_action"),
        )
    if kind == "call_result":
        return CallResultOutputDestinationAuthority(
            call_id=_required_string(payload, "call_id"),
            return_name=_required_string(payload, "return_name"),
            runtime_path=_required_string(payload, "runtime_path"),
        )
    raise ValueError("unsupported Method output destination kind")


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Method output authority field must be an object")
    return value


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Method output authority {key} must be non-empty")
    return value


def _missing(call_id: str, output_name: str, reason: str) -> ValueError:
    return ValueError(
        "planner_configuration_error: "
        "planner.method_output_write_authority_missing: "
        f"call={call_id}, output={output_name}: {reason}"
    )


def _drift(call_id: str, output_name: str, reason: str) -> ValueError:
    return ValueError(
        "planner_configuration_error: "
        "planner.method_output_write_authority_drift: "
        f"call={call_id}, output={output_name}: {reason}"
    )


__all__ = [
    "CallResultOutputDestinationAuthority",
    "MethodOutputDestinationAuthority",
    "MethodOutputRegistrationAuthority",
    "MethodOutputWriteAuthority",
    "MethodOutputWriteAuthorityFinalizer",
    "StateOutputDestinationAuthority",
]
