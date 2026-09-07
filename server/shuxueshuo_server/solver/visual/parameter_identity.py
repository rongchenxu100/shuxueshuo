"""Public provenance helpers for parameterized visual geometry identity."""

from __future__ import annotations

from typing import Any, Mapping
import re

from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    iter_teaching_sources,
    teaching_source_owners,
)


ParameterizedPointContext = tuple[str, str]


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


def parameterized_point_contexts_by_step(
    snapshot: ExplanationSnapshot,
) -> dict[str, frozenset[ParameterizedPointContext]]:
    """Propagate public parameterized-point identities through exact dependencies.

    A seed is recognized from public result types: one ``Symbol`` result and
    one ``Point`` result whose coordinates depend on that symbol.  A
    downstream step inherits the identity only through a precise
    StepResultRef (including a SourceRef's verified ``resolved_from``).  No
    capability id, private runtime symbol, point label, problem id, or answer
    value participates.
    """

    owners = teaching_source_owners(snapshot.root_scope)
    contexts: dict[str, frozenset[ParameterizedPointContext]] = {}
    for source in iter_teaching_sources(snapshot.root_scope):
        inherited: set[ParameterizedPointContext] = set()
        for items in source.inputs.values():
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                ref = item.get("resolved_from") or item.get("ref")
                if not isinstance(ref, Mapping) or ref.get("kind") != "step_result":
                    continue
                inherited.update(contexts.get(str(ref.get("step_id") or ""), ()))

        owner = owners.get(source.source_step_id, ("", None))[0]
        parameters = {
            str(output.get("value") or "")
            for output in source.outputs.values()
            if isinstance(output, Mapping)
            and str(output.get("runtime_type") or "") == "Symbol"
            and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]*",
                str(output.get("value") or ""),
            )
        }
        point_values = [
            output.get("value")
            for output in source.outputs.values()
            if isinstance(output, Mapping)
            and str(output.get("runtime_type") or "") == "Point"
        ]
        produced = {
            (owner, parameter)
            for parameter in parameters
            if owner
            and any(
                isinstance(point_value, (list, tuple))
                and len(point_value) == 2
                and value_depends_on_symbol(point_value, parameter)
                for point_value in point_values
            )
        }
        if len(produced) > 1:
            raise ValueError(
                "visual_parameterized_point_context_ambiguous: "
                f"step={source.source_step_id}, contexts={sorted(produced)}"
            )
        inherited.update(produced)

        contexts[source.source_step_id] = frozenset(inherited)
    return contexts


def step_value_uses_parameterized_point_symbol(
    snapshot: ExplanationSnapshot,
    *,
    step_id: str,
    scope_ref: str,
    value: Any,
) -> bool:
    """Check a value against the exact public parameter lineage of its step."""

    matches = {
        context
        for context in parameterized_point_contexts_by_step(snapshot).get(step_id, ())
        if context[0] == scope_ref and value_depends_on_symbol(value, context[1])
    }
    if len(matches) > 1:
        raise ValueError(
            "visual_parameterized_point_context_ambiguous: "
            f"step={step_id}, scope={scope_ref}, contexts={sorted(matches)}"
        )
    return bool(matches)
