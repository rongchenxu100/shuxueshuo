"""Canonical semantic projection for runtime value types.

Runtime types are execution contracts. ``state_kind`` and ``object_kind`` are
their planner/context projection and therefore must not be reinterpreted by
individual facade or compiler modules.
"""

from __future__ import annotations


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
    "ParameterValue": "symbol",
    "Symbol": "symbol",
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


def _primary_runtime_type(runtime_type: str) -> str:
    """Use the first declared member when projecting a runtime union."""
    return next(
        (part.strip() for part in runtime_type.split("|") if part.strip()),
        runtime_type,
    )


__all__ = ["object_kind_for_runtime_type", "state_kind_for_runtime_type"]
