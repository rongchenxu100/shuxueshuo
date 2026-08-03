"""Non-authoritative string aliases for debug and legacy wire payloads."""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.state_identity import StateSlotId


def functional_state_slot_debug_alias(slot_id: StateSlotId) -> str:
    return legacy_state_slot_aliases(slot_id)[0]


def functional_call_local_debug_alias(
    *,
    scope_id: str,
    call_id: str,
    return_name: str,
) -> str:
    return f"functional:{scope_id}:{call_id}:{return_name}"


def legacy_state_slot_aliases(slot_id: StateSlotId) -> tuple[str, ...]:
    prefix = (
        f"{slot_id.logical_key.object_id.value}."
        f"{slot_id.logical_key.state_kind}@{slot_id.storage_scope_id}"
    )
    return (
        f"{prefix}:{slot_id.logical_key.runtime_type}",
        prefix,
    )


__all__ = [
    "functional_call_local_debug_alias",
    "functional_state_slot_debug_alias",
    "legacy_state_slot_aliases",
]
