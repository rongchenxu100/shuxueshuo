"""Shared output type inference for planner/runtime produced facts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Collection

from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProducedFact,
    answer_output_type_compatible,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class OutputTypeInference:
    """Produced fact output type inference with provenance."""

    output_type: str | None
    source: str


def produced_output_type(
    produced: ProducedFact,
    registry: CanonicalHandleRegistry,
) -> str | None:
    """Infer a produced fact output type from canonical answer/fact metadata."""
    return produced_output_type_inference(produced, registry).output_type


def produced_output_type_inference(
    produced: ProducedFact,
    registry: CanonicalHandleRegistry,
) -> OutputTypeInference:
    """Return output type and source without letting text override handles."""
    if produced.handle.startswith("answer:"):
        if produced.handle in registry.answer_value_types:
            expected_type = registry.answer_value_types[produced.handle]
            if (
                produced.output_type is not None
                and produced.output_type != expected_type
                and answer_output_type_compatible(expected_type, produced.output_type)
            ):
                return OutputTypeInference(produced.output_type, "explicit_output_type")
            return OutputTypeInference(expected_type, "answer_value_type")
        if produced.output_type is not None:
            return OutputTypeInference(produced.output_type, "explicit_output_type")
        return output_type_inference_from_text(produced.handle, produced.description)
    if produced.handle in registry.fact_types:
        fact_type = registry.fact_types[produced.handle]
        if fact_type in FACT_TYPE_TO_OUTPUT_TYPE:
            return OutputTypeInference(
                FACT_TYPE_TO_OUTPUT_TYPE[fact_type],
                "fact_type",
            )
    if produced.output_type is not None:
        return OutputTypeInference(produced.output_type, "explicit_output_type")
    return output_type_inference_from_text(produced.handle, produced.description)


def output_type_from_text(handle: str, description: str) -> str | None:
    """Infer an output type from semantic handle text and description."""
    return output_type_inference_from_text(handle, description).output_type


def output_type_inference_from_text(
    handle: str,
    description: str,
) -> OutputTypeInference:
    """Infer output type from semantic name first, description as fallback."""
    text = f"{handle}\n{description}".lower()
    name = semantic_name_from_handle(handle).lower()
    if (
        ("angle_" in name and "_eq_" in name)
        or "equal_angle" in name
        or "angle_equality" in name
    ):
        return OutputTypeInference("AngleEquality", "semantic_name")
    if "relation" in name or "equation" in name:
        return OutputTypeInference("Equation", "semantic_name")
    if is_parameter_value_semantic_name(name):
        return OutputTypeInference("ParameterValue", "semantic_name")
    if any(value in name for value in ("candidate", "candidates", "候选")):
        return OutputTypeInference("PointList", "semantic_name")
    if any(
        value in name
        for value in ("coord", "coordinate", "intersection", "axis_point", "point")
    ):
        return OutputTypeInference("Point", "semantic_name")
    if "intercept" in name:
        return OutputTypeInference("Point", "semantic_name")
    if any(value in name for value in ("locus", "ray", "line")):
        return OutputTypeInference("Line", "semantic_name")
    if any(value in name for value in ("coefficient", "coefficients")):
        return OutputTypeInference("Coefficients", "semantic_name")
    if any(value in name for value in ("minimum", "min_value", "path_minimum")):
        return OutputTypeInference("MinimumExpression", "semantic_name")
    if any(value in name for value in ("distance", "expr", "expression")):
        return OutputTypeInference("Expression", "semantic_name")
    if any(value in name for value in ("straightened", "straightening", "choice")):
        return OutputTypeInference("StraighteningCandidate", "semantic_name")
    if any(value in name for value in ("path", "equivalence", "reduction")):
        return OutputTypeInference("PathTransformation", "semantic_name")
    if any(value in text for value in ("parabola", "抛物线", "解析式")):
        return OutputTypeInference("Parabola", "description")
    if any(
        value in text
        for value in ("straightened", "straightening", "choice", "拉直", "方案")
    ):
        return OutputTypeInference("StraighteningCandidate", "description")
    if any(
        value in text
        for value in ("path", "equivalence", "reduction", "路径", "等价", "降维")
    ):
        return OutputTypeInference("PathTransformation", "description")
    if any(
        value in text
        for value in ("locus", "ray", "line", "轨迹", "射线", "直线")
    ):
        return OutputTypeInference("Line", "description")
    if any(
        value in name
        for value in ("coord", "coordinate", "intersection", "axis_point", "point")
    ):
        return OutputTypeInference("Point", "semantic_name")
    if any(value in text for value in ("坐标", "交点")):
        return OutputTypeInference("Point", "description")
    if any(value in text for value in ("minimum", "min_value", "最小值")):
        return OutputTypeInference("MinimumExpression", "description")
    if any(value in text for value in ("distance", "距离", "表达式", "expression")):
        return OutputTypeInference("Expression", "description")
    if "关系" in text:
        return OutputTypeInference("Equation", "description")
    return OutputTypeInference(None, "unknown")


def semantic_name_to_runtime_type(
    name: str,
    *,
    allowed_types: Collection[str] | None = None,
    description: str = "",
    default: str | None = None,
) -> str | None:
    """Map a semantic name to a runtime type, optionally within a capability."""
    if allowed_types is not None:
        allowed = set(allowed_types)
        for candidate in semantic_name_output_type_candidates(name, description):
            if candidate in allowed:
                return candidate
        return default
    return output_type_inference_from_text(name, description).output_type or default


def semantic_name_output_type_candidates(
    name: str,
    description: str = "",
) -> tuple[str, ...]:
    """Ordered output type candidates from semantic text.

    This is intentionally capability-friendly: ``parabola_expr`` should choose
    ``Parabola`` when a capability offers it, even though the generic text
    fallback may classify bare ``*_expr`` as ``Expression``.
    """
    text = f"{name}\n{description}".lower()
    candidates: list[str] = []
    if (
        ("angle_" in text and "_eq_" in text)
        or "equal_angle" in text
        or "angle_equality" in text
    ):
        candidates.append("AngleEquality")
    if any(value in text for value in ("parabola", "抛物线")):
        candidates.append("Parabola")
    if "relation" in text or "equation" in text or "关系" in text:
        candidates.append("Equation")
    if is_parameter_value_semantic_name(text):
        candidates.append("ParameterValue")
    if any(value in text for value in ("candidate", "candidates", "候选")):
        candidates.append("PointList")
    if any(
        value in text
        for value in (
            "coord",
            "coordinate",
            "intersection",
            "axis_point",
            "point",
            "坐标",
            "交点",
        )
    ):
        candidates.append("Point")
    if "intercept" in text:
        candidates.append("Point")
    if any(
        value in text
        for value in ("locus", "ray", "line", "轨迹", "射线", "直线")
    ):
        candidates.append("Line")
    if any(value in text for value in ("coefficient", "coefficients")):
        candidates.append("Coefficients")
    if any(
        value in text
        for value in ("minimum", "min_value", "path_minimum", "最小值")
    ):
        candidates.append("MinimumExpression")
    if any(
        value in text
        for value in ("straightened", "straightening", "choice", "拉直", "方案")
    ):
        candidates.append("StraighteningCandidate")
    if any(
        value in text
        for value in ("path", "equivalence", "reduction", "路径", "等价", "降维")
    ):
        candidates.append("PathTransformation")
    if any(
        value in text
        for value in ("distance", "expr", "expression", "距离", "表达式")
    ):
        candidates.append("Expression")
    return unique_ordered(candidates)


def semantic_name_from_handle(handle: str) -> str:
    """Return semantic name from canonical handle-like text."""
    if handle.startswith("answer:"):
        return handle.split(":", 1)[1]
    parts = handle.split(":", 2)
    if len(parts) == 3:
        return parts[2]
    return parts[-1] if parts else handle


def produced_semantic_role(produced: ProducedFact) -> str:
    """Return the declared output role, falling back to handle semantics."""
    marker = " return "
    if marker in produced.description:
        role = produced.description.rsplit(marker, 1)[-1].strip()
        if role:
            return role
    return semantic_name_from_handle(produced.handle)


def is_parameter_value_semantic_name(name: str) -> bool:
    """Return whether a semantic name clearly denotes a parameter value."""
    if name in {"m_value", "a_value", "b_value", "c_value", "parameter_value"}:
        return True
    if re.fullmatch(r"parameter_[a-z][a-z0-9]*", name):
        return True
    return bool(
        re.fullmatch(r"(?:parameter_)?[a-z][a-z0-9]*_(?:parameter_)?value", name)
    )


FACT_TYPE_TO_OUTPUT_TYPE: dict[str, str] = {
    "coefficients": "Coefficients",
    "expression": "Expression",
    "minimum_expression": "MinimumExpression",
    "minimum_value_expression": "MinimumExpression",
    "parabola": "Parabola",
    "point_coordinate": "Point",
    "function_expression": "Parabola",
    "parameter_value": "ParameterValue",
    "symbol_value": "ParameterValue",
    "coefficient_relation": "Equation",
    "length_squared": "Condition",
    "segment_length_relation": "Condition",
    "minimum_value": "MinimumExpression",
    "point_candidates": "PointList",
    "path_minimum_target": "Condition",
    "right_angle_equal_length": "Condition",
    "segment_membership": "Condition",
    "segment_relation": "Condition",
    "midpoint_definition": "Condition",
    "orientation_constraint": "OrientationHint",
}


__all__ = [
    "FACT_TYPE_TO_OUTPUT_TYPE",
    "OutputTypeInference",
    "is_parameter_value_semantic_name",
    "output_type_from_text",
    "output_type_inference_from_text",
    "produced_output_type",
    "produced_output_type_inference",
    "semantic_name_from_handle",
    "semantic_name_output_type_candidates",
    "semantic_name_to_runtime_type",
]
