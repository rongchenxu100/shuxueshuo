"""Canonical semantic projection for runtime value types.

Runtime types are execution contracts. ``state_kind`` and ``object_kind`` are
their planner/context projection and therefore must not be reinterpreted by
individual facade or compiler modules.
"""

from __future__ import annotations

import re


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


def split_runtime_types(runtime_type: str) -> tuple[str, ...]:
    """Split one runtime union using the canonical declaration grammar."""
    return tuple(part.strip() for part in runtime_type.split("|") if part.strip())


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


__all__ = [
    "OBJECT_SEMANTIC_KIND_ORDER",
    "OBJECT_SEMANTIC_KINDS",
    "dependent_role_object_ref",
    "derived_role_object_ref",
    "is_object_handle",
    "is_object_semantic_kind",
    "object_semantic_kind_for_handle",
    "object_kind_for_runtime_type",
    "runtime_type_for_object_semantic_kind",
    "split_runtime_types",
    "state_kind_for_runtime_type",
]
