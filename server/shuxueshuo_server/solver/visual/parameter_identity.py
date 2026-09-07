"""Public provenance helpers for parameterized visual geometry identity."""

from __future__ import annotations

from typing import Any, Mapping
import re

from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    iter_teaching_sources,
    teaching_source_owners,
)


AxisParameterContext = tuple[str, str]


def value_depends_on_symbol(value: Any, symbol: str) -> bool:
    """Return whether a public value contains ``symbol`` as a math identifier."""

    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])"
    )
    if isinstance(value, Mapping):
        return any(value_depends_on_symbol(item, symbol) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(value_depends_on_symbol(item, symbol) for item in value)
    return bool(pattern.search(str(value)))


def axis_parameter_contexts_by_step(
    snapshot: ExplanationSnapshot,
) -> dict[str, frozenset[AxisParameterContext]]:
    """Propagate public axis-parameter identities through exact dependencies.

    The seed is a typed ``quadratic_axis_parameterized_point`` producer.  A
    downstream step inherits the identity only through a precise StepResultRef
    (including a SourceRef's verified ``resolved_from``).  No private runtime
    symbol, point label, problem id, or answer value participates.
    """

    owners = teaching_source_owners(snapshot.root_scope)
    contexts: dict[str, frozenset[AxisParameterContext]] = {}
    for source in iter_teaching_sources(snapshot.root_scope):
        inherited: set[AxisParameterContext] = set()
        for items in source.inputs.values():
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                ref = item.get("resolved_from") or item.get("ref")
                if not isinstance(ref, Mapping) or ref.get("kind") != "step_result":
                    continue
                inherited.update(contexts.get(str(ref.get("step_id") or ""), ()))

        if source.capability_id == "quadratic_axis_parameterized_point":
            point = source.outputs.get("point")
            parameter_output = source.outputs.get("parameter")
            parameter = (
                str(parameter_output.get("value") or "")
                if isinstance(parameter_output, Mapping)
                else ""
            )
            point_value = point.get("value") if isinstance(point, Mapping) else None
            owner = owners.get(source.source_step_id, ("", None))[0]
            if (
                owner
                and isinstance(point_value, (list, tuple))
                and len(point_value) == 2
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", parameter)
                and value_depends_on_symbol(point_value, parameter)
            ):
                inherited.add((owner, parameter))

        contexts[source.source_step_id] = frozenset(inherited)
    return contexts


def step_value_uses_axis_parameter(
    snapshot: ExplanationSnapshot,
    *,
    step_id: str,
    scope_ref: str,
    value: Any,
) -> bool:
    """Check a value against the exact public parameter lineage of its step."""

    matches = {
        context
        for context in axis_parameter_contexts_by_step(snapshot).get(step_id, ())
        if context[0] == scope_ref and value_depends_on_symbol(value, context[1])
    }
    if len(matches) > 1:
        raise ValueError(
            "visual_axis_parameter_context_ambiguous: "
            f"step={step_id}, scope={scope_ref}, contexts={sorted(matches)}"
        )
    return bool(matches)
