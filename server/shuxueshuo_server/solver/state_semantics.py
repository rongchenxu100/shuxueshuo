"""Canonical semantic projection for runtime value types.

Runtime types are execution contracts. ``state_kind`` and ``object_kind`` are
their planner/context projection and therefore must not be reinterpreted by
individual facade or compiler modules.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)

@dataclass(frozen=True)
class StateObjectRoleBinding:
    """One named object identity carried by a semantic state."""

    role: str
    object_refs: tuple[str, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "role": self.role,
            "object_refs": list(self.object_refs),
            "source_state_slot_ids": list(self.source_state_slot_ids),
        }


@dataclass(frozen=True)
class StateSemanticLineage:
    """Stable semantic identity metadata propagated across state writes."""

    semantic_roles: tuple[str, ...] = ()
    evidence_tags: tuple[str, ...] = ()
    object_roles: tuple[StateObjectRoleBinding, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "semantic_roles": list(self.semantic_roles),
            "evidence_tags": list(self.evidence_tags),
            "object_roles": [item.to_payload() for item in self.object_roles],
            "source_state_slot_ids": list(self.source_state_slot_ids),
        }


def state_semantic_lineage(
    *,
    semantic_roles: Iterable[str] = (),
    evidence_tags: Iterable[str] = (),
    object_roles: Iterable[StateObjectRoleBinding] = (),
    source_state_slot_ids: Iterable[str] = (),
) -> StateSemanticLineage:
    """Build normalized lineage without making callers own deduplication."""
    roles_by_name: dict[str, StateObjectRoleBinding] = {}
    for item in object_roles:
        current = roles_by_name.get(item.role)
        roles_by_name[item.role] = StateObjectRoleBinding(
            role=item.role,
            object_refs=_unique_strings(
                (
                    *((current.object_refs if current is not None else ())),
                    *item.object_refs,
                )
            ),
            source_state_slot_ids=_unique_strings(
                (
                    *((
                        current.source_state_slot_ids
                        if current is not None
                        else ()
                    )),
                    *item.source_state_slot_ids,
                )
            ),
        )
    return StateSemanticLineage(
        semantic_roles=_unique_strings(semantic_roles),
        evidence_tags=_unique_strings(evidence_tags),
        object_roles=tuple(roles_by_name.values()),
        source_state_slot_ids=_unique_strings(source_state_slot_ids),
    )


def merge_state_semantic_lineages(
    *items: StateSemanticLineage,
    semantic_roles: Iterable[str] = (),
    evidence_tags: Iterable[str] = (),
    object_roles: Iterable[StateObjectRoleBinding] = (),
    source_state_slot_ids: Iterable[str] = (),
) -> StateSemanticLineage:
    """Merge source lineage with roles declared by the current write."""
    return state_semantic_lineage(
        semantic_roles=(
            *(role for item in items for role in item.semantic_roles),
            *semantic_roles,
        ),
        evidence_tags=(
            *(tag for item in items for tag in item.evidence_tags),
            *evidence_tags,
        ),
        object_roles=(
            *(binding for item in items for binding in item.object_roles),
            *object_roles,
        ),
        source_state_slot_ids=(
            *(
                slot_id
                for item in items
                for slot_id in item.source_state_slot_ids
            ),
            *source_state_slot_ids,
        ),
    )


def state_object_refs_for_role(
    lineage: StateSemanticLineage,
    role: str,
) -> tuple[str, ...]:
    """Return canonical object refs carried under one structured role."""
    return _unique_strings(
        object_ref
        for item in lineage.object_roles
        if item.role == role
        for object_ref in item.object_refs
    )


def state_semantic_lineage_from_payload(
    payload: object,
) -> StateSemanticLineage:
    """Parse persisted lineage at the untrusted debug/context boundary."""
    if not isinstance(payload, Mapping):
        return StateSemanticLineage()
    object_roles: list[StateObjectRoleBinding] = []
    raw_object_roles = payload.get("object_roles", ())
    if isinstance(raw_object_roles, Iterable) and not isinstance(
        raw_object_roles,
        (str, bytes, Mapping),
    ):
        for item in raw_object_roles:
            if not isinstance(item, Mapping):
                continue
            role = item.get("role")
            if not isinstance(role, str) or not role:
                continue
            object_roles.append(
                StateObjectRoleBinding(
                    role=role,
                    object_refs=_string_items(item.get("object_refs")),
                    source_state_slot_ids=_string_items(
                        item.get("source_state_slot_ids")
                    ),
                )
            )
    return state_semantic_lineage(
        semantic_roles=_string_items(payload.get("semantic_roles")),
        evidence_tags=_string_items(payload.get("evidence_tags")),
        object_roles=object_roles,
        source_state_slot_ids=_string_items(
            payload.get("source_state_slot_ids")
        ),
    )


OBJECT_SEMANTIC_KIND_ORDER = (
    "point",
    "line",
    "segment",
    "ray",
    "function",
    "symbol",
    "angle",
    "circle",
    "polygon",
)
OBJECT_SEMANTIC_KINDS = frozenset(OBJECT_SEMANTIC_KIND_ORDER)

_STATE_KIND_BY_RUNTIME_TYPE: dict[str, str] = {
    "Parabola": "expression",
    "Function": "expression",
    "Expression": "expression",
    "MinimumExpression": "expression",
    "Equation": "expression",
    "Point": "coordinate",
    "PointList": "coordinate",
    "PointRef": "coordinate",
    "Line": "locus",
    "Segment": "segment",
    "Ray": "ray",
    "Angle": "angle",
    "Circle": "circle",
    "Polygon": "polygon",
    "Coefficients": "coefficients",
    "PathTransformation": "transformation",
    "StraighteningCandidate": "candidate",
    "ParameterValue": "value",
    "Symbol": "symbol",
    "Condition": "condition",
    "Constraint": "condition",
}

_OBJECT_KIND_BY_RUNTIME_TYPE: dict[str, str] = {
    "Parabola": "function",
    "Function": "function",
    "Point": "point",
    "PointList": "point",
    "PointRef": "point",
    "Line": "line",
    "Segment": "segment",
    "Ray": "ray",
    "Angle": "angle",
    "Circle": "circle",
    "Polygon": "polygon",
    "ParameterValue": "symbol",
    "Symbol": "symbol",
}

_RUNTIME_TYPE_BY_OBJECT_SEMANTIC_KIND: dict[str, str] = {
    "point": "Point",
    "line": "Line",
    "segment": "Segment",
    "ray": "Ray",
    "function": "Parabola|Function",
    "symbol": "Symbol",
    "angle": "Angle",
    "circle": "Circle",
    "polygon": "Polygon",
}


def state_kind_for_runtime_type(runtime_type: str) -> str:
    """Return the one canonical StateSlot kind for a runtime type."""
    primary_type = _primary_runtime_type(runtime_type)
    return _STATE_KIND_BY_RUNTIME_TYPE.get(
        primary_type,
        primary_type[:1].lower() + primary_type[1:],
    )


def object_kind_for_runtime_type(runtime_type: str) -> str | None:
    """Return the canonical math-object kind for a runtime type, if any."""
    return _OBJECT_KIND_BY_RUNTIME_TYPE.get(_primary_runtime_type(runtime_type))


def runtime_type_for_object_semantic_kind(semantic_kind: str) -> str | None:
    """Project an object-facing semantic ref kind to its runtime union."""
    return _RUNTIME_TYPE_BY_OBJECT_SEMANTIC_KIND.get(semantic_kind)


def is_object_semantic_kind(value: object) -> bool:
    """Return whether a semantic kind denotes a first-class math object."""
    return isinstance(value, str) and value in OBJECT_SEMANTIC_KINDS


def object_semantic_kind_for_handle(handle: object) -> str | None:
    """Return the canonical object kind encoded by a handle prefix."""
    if not isinstance(handle, str) or ":" not in handle:
        return None
    kind = handle.split(":", 1)[0]
    return kind if is_object_semantic_kind(kind) else None


def is_object_handle(value: object) -> bool:
    """Return whether a value uses a canonical math-object handle prefix."""
    return object_semantic_kind_for_handle(value) is not None


def object_ref_matches_runtime_type(
    object_ref: object,
    runtime_type: str,
) -> bool:
    """Return whether an object identity can own the declared runtime state.

    Preserved state writes must keep the identity of the matching math object.
    In particular, a Point mentioned by an expression cannot become the owner
    of a Parabola state merely because both values share a runtime path.
    """
    actual_kind = object_semantic_kind_for_handle(object_ref)
    if actual_kind is None:
        return False
    expected_kinds = {
        object_kind
        for member in split_runtime_types(runtime_type)
        if (object_kind := object_kind_for_runtime_type(member)) is not None
    }
    return actual_kind in expected_kinds


def derived_role_object_ref(
    *,
    call_id: str,
    semantic_role: str,
    scope_id: str,
    runtime_type: str,
) -> str:
    """Return the stable object identity for one call-local derived role.

    A semantic role describes an output inside a capability; it is not
    globally unique. Including the producing call prevents independent macro
    invocations from becoming accidental writers of one StateSlot.
    """
    call = _safe_identity_token(call_id)
    role = _safe_identity_token(semantic_role)
    if object_kind_for_runtime_type(runtime_type) == "point":
        return f"point:{scope_id}:{call}_{role}"
    return f"role:{call}:{role}@{scope_id}"


def dependent_role_object_ref(
    *,
    source_object_ref: str,
    semantic_role: str,
    scope_id: str,
    runtime_type: str,
) -> str:
    """Return the identity of a state derived for one existing object.

    Companion states such as a point's internal parameter are neither the
    source object itself nor a call-local anonymous value. Their identity must
    therefore include the source object and the declared semantic role.
    """
    object_name = _safe_identity_token(source_object_ref.rsplit(":", 1)[-1])
    role = _safe_identity_token(semantic_role)
    object_kind = object_kind_for_runtime_type(runtime_type)
    if object_kind is not None:
        return f"{object_kind}:{scope_id}:{object_name}_{role}"
    return f"role:{object_name}:{role}@{scope_id}"


def _primary_runtime_type(runtime_type: str) -> str:
    """Use the first declared member when projecting a runtime union."""
    return next(iter(split_runtime_types(runtime_type)), runtime_type)


def _safe_identity_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return token or "state"


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _string_items(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Iterable) or isinstance(
        value,
        (str, bytes, Mapping),
    ):
        return ()
    return _unique_strings(item for item in value if isinstance(item, str))


__all__ = [
    "OBJECT_SEMANTIC_KIND_ORDER",
    "OBJECT_SEMANTIC_KINDS",
    "StateObjectRoleBinding",
    "StateSemanticLineage",
    "dependent_role_object_ref",
    "derived_role_object_ref",
    "is_object_handle",
    "is_object_semantic_kind",
    "object_semantic_kind_for_handle",
    "object_kind_for_runtime_type",
    "object_ref_matches_runtime_type",
    "runtime_type_for_object_semantic_kind",
    "merge_state_semantic_lineages",
    "split_runtime_types",
    "state_object_refs_for_role",
    "state_kind_for_runtime_type",
    "state_semantic_lineage",
    "state_semantic_lineage_from_payload",
]
