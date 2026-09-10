"""Public provenance helpers for parameterized visual geometry identity."""

from __future__ import annotations

from typing import Any, Mapping
import re

import sympy as sp

from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingSource,
    iter_teaching_sources,
    teaching_source_owners,
)


ParameterizedPointContext = tuple[str, str]


def verified_parameter_values_from_source(
    source: TeachingSource,
) -> dict[str, str]:
    """Return parameter values explicitly certified by one runtime source.

    Atomic methods usually publish a ``ParameterValue`` output.  An atomic
    macro can close a point and a curve together and expose the same verified
    value in a ``parameter_solution`` calculation instead.  Both forms are
    runtime evidence and must advance the visual state identically.
    """

    values: dict[str, str] = {}
    input_parameter_names = {
        text
        for items in source.inputs.values()
        for item in items
        if isinstance(item, Mapping)
        and str(item.get("runtime_type") or "") in {"ParameterValue", "Symbol"}
        for candidate in (item.get("value"), item.get("display"))
        if re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*",
            text := str(candidate or "").strip(),
        )
    }

    def publish(name: Any, value: Any) -> None:
        normalized_name = str(name or "").strip()
        normalized_value = str(value if value is not None else "").strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", normalized_name):
            return
        if not normalized_value:
            return
        existing = values.get(normalized_name)
        if existing is not None and existing != normalized_value:
            try:
                equivalent = (
                    sp.simplify(
                        sp.sympify(existing) - sp.sympify(normalized_value)
                    )
                    == 0
                )
            except Exception:
                equivalent = False
            if not equivalent:
                raise ValueError(
                    "visual_verified_parameter_value_conflict: "
                    f"step={source.source_step_id}, parameter={normalized_name}, "
                    f"values={[existing, normalized_value]}"
                )
            return
        values[normalized_name] = normalized_value

    for return_name, output in source.outputs.items():
        if output.get("runtime_type") == "Coefficients" and isinstance(output.get("value"), Mapping):
            for symbol, value in output["value"].items():
                if not sp.sympify(str(value)).free_symbols:
                    publish(symbol, value)
            continue
        if str(output.get("runtime_type") or "") != "ParameterValue":
            continue
        name = str(source.output_targets.get(return_name) or "")
        if not name:
            for candidate in (output.get("display"), output.get("value")):
                text = str(candidate or "").strip()
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text):
                    name = text
                    break
        if not name and len(input_parameter_names) == 1:
            name = next(iter(input_parameter_names))
        publish(name, output.get("value"))

    for calculation in source.calculations:
        if not isinstance(calculation, Mapping):
            continue
        if str(calculation.get("kind") or "") != "parameter_solution":
            continue
        publish(calculation.get("parameter"), calculation.get("value"))
    return values


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
