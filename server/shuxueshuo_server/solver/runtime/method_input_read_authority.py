"""Typed source authority for one lowered Method input item."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, TypeAlias

from shuxueshuo_server.solver.contracts import MethodInputViewMode
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.state_identity import StateVersionId


@dataclass(frozen=True)
class EntityIdentityReadSource:
    entity_handle: str
    runtime_path: str
    kind: Literal["entity_identity"] = "entity_identity"

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "entity_handle": self.entity_handle,
            "runtime_path": self.runtime_path,
        }


@dataclass(frozen=True)
class StateVersionReadSource:
    state_version_id: StateVersionId
    runtime_path: str
    kind: Literal["state_version"] = "state_version"

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "state_version_id": self.state_version_id.to_payload(),
            "runtime_path": self.runtime_path,
        }


@dataclass(frozen=True)
class ConditionReadSource:
    condition_id: str
    runtime_path: str
    kind: Literal["condition"] = "condition"

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "condition_id": self.condition_id,
            "runtime_path": self.runtime_path,
        }


@dataclass(frozen=True)
class CallResultReadSource:
    call_id: str
    return_name: str
    runtime_path: str
    kind: Literal["call_result"] = "call_result"

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "call_id": self.call_id,
            "return_name": self.return_name,
            "runtime_path": self.runtime_path,
        }


@dataclass(frozen=True)
class InvocationResultReadSource:
    invocation_id: str
    return_name: str
    runtime_path: str
    kind: Literal["invocation_result"] = "invocation_result"

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "invocation_id": self.invocation_id,
            "return_name": self.return_name,
            "runtime_path": self.runtime_path,
        }


@dataclass(frozen=True)
class CompilerSelectorReadSource:
    selector_id: str
    runtime_path: str
    kind: Literal["compiler_selector"] = "compiler_selector"

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "selector_id": self.selector_id,
            "runtime_path": self.runtime_path,
        }


MethodInputReadSource: TypeAlias = (
    EntityIdentityReadSource
    | StateVersionReadSource
    | ConditionReadSource
    | CallResultReadSource
    | InvocationResultReadSource
    | CompilerSelectorReadSource
)


@dataclass(frozen=True)
class MethodInputReadAuthority:
    method_id: str
    invocation_id: str
    input_name: str
    item_index: int
    view_mode: MethodInputViewMode
    domain_type: str
    runtime_type: str
    scope_id: str
    source: MethodInputReadSource
    authority_signature: str = field(init=False)
    schema_version: str = "method-input-read-authority/v1"

    def __post_init__(self) -> None:
        for name in (
            "method_id",
            "invocation_id",
            "input_name",
            "domain_type",
            "runtime_type",
            "scope_id",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if self.item_index < 0:
            raise ValueError("Method input item_index must be non-negative")
        _validate_source_for_view(self.view_mode, self.source)
        object.__setattr__(
            self,
            "authority_signature",
            stable_hash(self.authority_payload(include_signature=False)),
        )

    @property
    def runtime_path(self) -> str:
        return self.source.runtime_path

    def authority_payload(self, *, include_signature: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "method_id": self.method_id,
            "invocation_id": self.invocation_id,
            "input_name": self.input_name,
            "item_index": self.item_index,
            "view_mode": self.view_mode,
            "domain_type": self.domain_type,
            "runtime_type": self.runtime_type,
            "scope_id": self.scope_id,
            "source": self.source.to_payload(),
        }
        if include_signature:
            payload["authority_signature"] = self.authority_signature
        return payload

    def verify(
        self,
        *,
        method_id: str,
        invocation_id: str,
        input_name: str,
        item_index: int,
        view_mode: MethodInputViewMode,
        domain_type: str,
        runtime_type: str,
        scope_id: str,
        raw_path: str,
        production: bool = False,
    ) -> None:
        observed = (
            method_id,
            invocation_id,
            input_name,
            item_index,
            view_mode,
            domain_type,
            runtime_type,
            scope_id,
            raw_path,
        )
        expected = (
            self.method_id,
            self.invocation_id,
            self.input_name,
            self.item_index,
            self.view_mode,
            self.domain_type,
            self.runtime_type,
            self.scope_id,
            self.runtime_path,
        )
        if observed != expected:
            raise ValueError(
                "planner.method_input_view_authority_drift: "
                f"input={input_name}[{item_index}], "
                f"expected={expected!r}, observed={observed!r}"
            )
        if production:
            _validate_production_source_for_view(self.view_mode, self.source)

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "MethodInputReadAuthority":
        if payload.get("schema_version") != "method-input-read-authority/v1":
            raise ValueError("unsupported Method input read authority contract")
        source_payload = payload.get("source")
        if not isinstance(source_payload, Mapping):
            raise ValueError("Method input read authority source must be an object")
        source = _source_from_payload(source_payload)
        authority = cls(
            method_id=_required_string(payload, "method_id"),
            invocation_id=_required_string(payload, "invocation_id"),
            input_name=_required_string(payload, "input_name"),
            item_index=_required_int(payload, "item_index"),
            view_mode=_required_view_mode(payload),
            domain_type=_required_string(payload, "domain_type"),
            runtime_type=_required_string(payload, "runtime_type"),
            scope_id=_required_string(payload, "scope_id"),
            source=source,
        )
        if payload.get("authority_signature") != authority.authority_signature:
            raise ValueError("Method input read authority signature drift")
        return authority


def method_input_read_authority_payload(
    value: MethodInputReadAuthority,
) -> Mapping[str, Any]:
    return value.authority_payload()


def _validate_source_for_view(
    view_mode: MethodInputViewMode,
    source: MethodInputReadSource,
) -> None:
    allowed: dict[str, tuple[type[Any], ...]] = {
        "identity": (EntityIdentityReadSource, CompilerSelectorReadSource),
        "latest_state": (
            StateVersionReadSource,
            InvocationResultReadSource,
            CompilerSelectorReadSource,
        ),
        "immutable_value": (
            EntityIdentityReadSource,
            StateVersionReadSource,
            ConditionReadSource,
            InvocationResultReadSource,
            CompilerSelectorReadSource,
        ),
        "exact_result": (
            CallResultReadSource,
            InvocationResultReadSource,
            CompilerSelectorReadSource,
        ),
    }
    if not isinstance(source, allowed[view_mode]):
        raise ValueError(
            "planner.method_input_view_authority_drift: "
            f"view={view_mode}, source={source.kind}"
        )


def _validate_production_source_for_view(
    view_mode: MethodInputViewMode,
    source: MethodInputReadSource,
) -> None:
    """Reject debug selectors where production requires a pinned authority."""

    allowed: dict[str, tuple[type[Any], ...]] = {
        "identity": (EntityIdentityReadSource, CompilerSelectorReadSource),
        "latest_state": (StateVersionReadSource, InvocationResultReadSource),
        "immutable_value": (
            EntityIdentityReadSource,
            StateVersionReadSource,
            ConditionReadSource,
            InvocationResultReadSource,
            CompilerSelectorReadSource,
        ),
        "exact_result": (CallResultReadSource, InvocationResultReadSource),
    }
    if not isinstance(source, allowed[view_mode]):
        raise ValueError(
            "planner.method_input_view_authority_drift: "
            f"production view={view_mode}, source={source.kind}"
        )


def _source_from_payload(payload: Mapping[str, Any]) -> MethodInputReadSource:
    kind = payload.get("kind")
    runtime_path = _required_string(payload, "runtime_path")
    if kind == "entity_identity":
        return EntityIdentityReadSource(
            _required_string(payload, "entity_handle"),
            runtime_path,
        )
    if kind == "state_version":
        version = payload.get("state_version_id")
        if not isinstance(version, Mapping):
            raise ValueError("state_version source must include state_version_id")
        return StateVersionReadSource(
            StateVersionId.from_payload(version),
            runtime_path,
        )
    if kind == "condition":
        return ConditionReadSource(
            _required_string(payload, "condition_id"),
            runtime_path,
        )
    if kind == "call_result":
        return CallResultReadSource(
            _required_string(payload, "call_id"),
            _required_string(payload, "return_name"),
            runtime_path,
        )
    if kind == "invocation_result":
        return InvocationResultReadSource(
            _required_string(payload, "invocation_id"),
            _required_string(payload, "return_name"),
            runtime_path,
        )
    if kind == "compiler_selector":
        return CompilerSelectorReadSource(
            _required_string(payload, "selector_id"),
            runtime_path,
        )
    raise ValueError(f"unsupported Method input read source: {kind!r}")


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _required_int(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _required_view_mode(payload: Mapping[str, Any]) -> MethodInputViewMode:
    value = payload.get("view_mode")
    if value not in {"identity", "latest_state", "immutable_value", "exact_result"}:
        raise ValueError("view_mode is invalid")
    return value


__all__ = [
    "CallResultReadSource",
    "CompilerSelectorReadSource",
    "ConditionReadSource",
    "EntityIdentityReadSource",
    "InvocationResultReadSource",
    "MethodInputReadAuthority",
    "MethodInputReadSource",
    "StateVersionReadSource",
]
