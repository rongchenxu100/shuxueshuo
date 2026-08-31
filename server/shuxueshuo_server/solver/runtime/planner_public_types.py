"""Canonical type vocabulary for every LLM-facing planner payload.

Planner inputs name mathematical entities that the model can select. Planner
returns name values produced by capabilities. Those are intentionally separate
projections: a ``QuadraticFunction`` entity produces a ``Parabola`` state, and
a ``Symbol`` entity produces a ``ParameterValue`` state.
"""

from __future__ import annotations

from collections.abc import Iterable

from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)


def planner_input_domain_type(
    runtime_type: str,
    *,
    aggregation: str = "none",
) -> str:
    """Return the public mathematical entity/fact type for one input."""

    if aggregation == "coefficients_by_symbol":
        return "Fact"
    if aggregation == "point_list":
        return "Point"
    if aggregation == "symbol_list":
        return "Symbol"

    variants = set(split_runtime_types(runtime_type))
    if variants <= {"Point", "PointRef"}:
        return "Point"
    if variants <= {"Symbol", "ParameterValue"}:
        return "Symbol"
    if variants <= {"Parabola", "Expression"} and "Parabola" in variants:
        return "QuadraticFunction"
    if variants <= {
        "Condition",
        "Constraint",
        "Equation",
        "AngleEquality",
        "OrientationHint",
    }:
        return "Fact"
    if variants <= {"PointList", "PointCandidates"}:
        return "PointList"
    if variants == {"CandidateSet"}:
        return "CandidateList"
    if len(variants) == 1:
        return next(iter(variants))
    return "|".join(sorted(variants))


def planner_output_value_type(runtime_type: str) -> str:
    """Return the canonical public value type produced by a capability.

    Goal ``answer_type`` values use this same vocabulary. In particular, this
    function must never rename ``Parabola``, ``ParameterValue`` or
    ``PointList`` to their input-entity aliases.
    """

    variants = set(split_runtime_types(runtime_type))
    projected = {_planner_output_variant(item) for item in variants}
    if len(projected) == 1:
        return next(iter(projected))
    return "|".join(sorted(projected))


def planner_prompt_text(value: str) -> str:
    """Remove internal representation vocabulary without renaming values."""

    replacements = (
        ("StateVersionId", "exact state"),
        ("StateVersion", "state"),
        ("MathObjectId", "math entity"),
        ("PointRef", "Point identity"),
        ("runtime path", "internal state locator"),
    )
    result = value
    for runtime_term, public_term in replacements:
        result = result.replace(runtime_term, public_term)
    return result


def join_prompt_descriptions(parts: Iterable[str]) -> str:
    """Join independently-authored descriptions without exact duplication."""

    values = tuple(
        dict.fromkeys(item.strip() for item in parts if item and item.strip())
    )
    return " ".join(values)


def _planner_output_variant(runtime_type: str) -> str:
    return {
        "PointRef": "Point",
        "Point": "Point",
        "Parabola": "Parabola",
        "Symbol": "Symbol",
        "ParameterValue": "ParameterValue",
        "Condition": "Fact",
        "Constraint": "Fact",
        "Equation": "Fact",
        "OrientationHint": "Fact",
        "Expression": "Expression",
        "PointList": "PointList",
        "PointCandidates": "PointList",
        "CandidateSet": "CandidateList",
    }.get(runtime_type, runtime_type)
