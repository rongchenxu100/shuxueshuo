"""Canonical compatibility rules for planner-facing runtime value types."""

from __future__ import annotations

import re

from shuxueshuo_server.solver.runtime.output_type_inference import (
    FACT_TYPE_TO_OUTPUT_TYPE,
)
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)


def normalize_runtime_type(value: str) -> str:
    """Normalize fact aliases and LLM-facing names to runtime type names."""
    value = FACT_TYPE_TO_OUTPUT_TYPE.get(value, value)
    key = re.sub(r"[^A-Za-z0-9]+", "", value).lower()
    return {
        "quadratic": "Parabola",
        "pointcoordinate": "Point",
        "coordinate": "Point",
        "symbolvalue": "ParameterValue",
        "parameter": "ParameterValue",
    }.get(key, value.strip())


def runtime_type_compatible(expected: str, actual: str | None) -> bool:
    """Return whether an actual runtime type satisfies an expected union."""
    if actual is None:
        return True
    expected_types = {
        normalize_runtime_type(item)
        for item in split_runtime_types(expected)
    }
    actual_type = normalize_runtime_type(actual)
    if actual_type in expected_types:
        return True
    if actual_type in {"Parabola", "Function"} and "Expression" in expected_types:
        return True
    if {actual_type, *expected_types} <= {"Point", "PointRef"}:
        return True
    return (
        actual_type == "Condition" and "Constraint" in expected_types
    ) or (
        actual_type == "Constraint" and "Condition" in expected_types
    )


__all__ = [
    "normalize_runtime_type",
    "runtime_type_compatible",
    "split_runtime_types",
]
