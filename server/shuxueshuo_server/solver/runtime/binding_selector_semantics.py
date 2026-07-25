"""Single semantic descriptor registry for runtime binding selectors."""

from __future__ import annotations

from dataclasses import dataclass

from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CONDITION_OBJECT_ROLES_RESOLVER,
    PATH_REDUCTION_ROLES_RESOLVER,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class SelectorSemantics:
    """Planner-facing meaning attached to one runtime selector grammar."""

    mechanical: bool = False
    semantic_roles: tuple[str, ...] = ()
    condition_kinds: tuple[str, ...] = ()
    requires_materialized_state: bool = False
    context_prerequisites: tuple[str, ...] = ()
    prerequisite_condition_kind: str | None = None
    semantic_evidence_resolver: str | None = None


@dataclass(frozen=True)
class ExpansionSelectorSemantics:
    """Deterministic Functional arg resolvers supplied by an expansion selector."""

    arg_resolvers: tuple[tuple[str, str], ...] = ()


_EXACT_SELECTOR_SEMANTICS: dict[str, SelectorSemantics] = {
    "function:parabola": SelectorSemantics(
        mechanical=True,
        requires_materialized_state=True,
    ),
    "quadratic_coefficients": SelectorSemantics(mechanical=True),
    "point_output_ref": SelectorSemantics(mechanical=True),
    "point_transition_target": SelectorSemantics(mechanical=True),
    "parameter_symbol": SelectorSemantics(mechanical=True),
    "parameter_symbol_from_reads": SelectorSemantics(mechanical=True),
    "parameter_symbol_from_reads_or_expression": SelectorSemantics(
        mechanical=True,
        semantic_evidence_resolver="unique_parameter_symbol",
    ),
    "known_parameter_symbol_from_reads": SelectorSemantics(mechanical=True),
    "known_parameter_value_from_reads": SelectorSemantics(mechanical=True),
    "parameter_constraint": SelectorSemantics(mechanical=True),
    "angle_sum:target": SelectorSemantics(mechanical=True),
    "angle_equality:target": SelectorSemantics(mechanical=True),
    "fact:length_condition:Condition": SelectorSemantics(
        condition_kinds=("length_squared", "segment_length_relation"),
    ),
    "square:side_start": SelectorSemantics(requires_materialized_state=True),
    "square:side_end": SelectorSemantics(requires_materialized_state=True),
    "curve_condition:target_point": SelectorSemantics(
        requires_materialized_state=True
    ),
    "curve_condition:curve_point": SelectorSemantics(
        requires_materialized_state=True
    ),
    "straightening_minimum:p1": SelectorSemantics(
        semantic_roles=("path_minimum_point_1",),
        requires_materialized_state=True,
    ),
    "straightening_minimum:p2": SelectorSemantics(
        semantic_roles=("path_minimum_point_2",),
        requires_materialized_state=True,
    ),
}

_PREFIX_SELECTOR_SEMANTICS: tuple[tuple[str, SelectorSemantics], ...] = (
    (
        "right_angle:",
        SelectorSemantics(
            mechanical=True,
            prerequisite_condition_kind="right_angle_equal_length",
        ),
    ),
    (
        "midpoint:",
        SelectorSemantics(
            mechanical=True,
            prerequisite_condition_kind="midpoint_definition",
        ),
    ),
    (
        "square:side_start_ref",
        SelectorSemantics(
            mechanical=True,
            prerequisite_condition_kind="square",
        ),
    ),
    (
        "square:side_end_ref",
        SelectorSemantics(
            mechanical=True,
            prerequisite_condition_kind="square",
        ),
    ),
    (
        "intersection:",
        SelectorSemantics(
            context_prerequisites=("fact_type:segment_relation",),
        ),
    ),
    ("symbol:", SelectorSemantics(mechanical=True)),
    ("function:", SelectorSemantics(mechanical=True)),
)

_EXPANSION_SELECTOR_SEMANTICS: dict[str, ExpansionSelectorSemantics] = {
    "parameter_value_if_read": ExpansionSelectorSemantics(
        (("parameter_value", "unique_related_state"),)
    ),
    "distance_parameter_value_if_read": ExpansionSelectorSemantics(
        (("parameter_value", "unique_related_state"),)
    ),
    "intersection_parameter_value_if_read": ExpansionSelectorSemantics(
        (("parameter_value", "unique_related_state"),)
    ),
}

_CONTEXT_SELECTOR_PREFIXES: tuple[
    tuple[str, CapabilityContextResolver, dict[str, str]], ...
] = (
    ("right_angle:", CONDITION_OBJECT_ROLES_RESOLVER, {}),
    (
        "path_reduction:",
        PATH_REDUCTION_ROLES_RESOLVER,
        {"relation": "binding_relation"},
    ),
)


def selector_semantics(selector: str | None) -> SelectorSemantics:
    """Return merged exact/prefix semantics for a selector."""
    if selector is None:
        return SelectorSemantics()
    exact = _EXACT_SELECTOR_SEMANTICS.get(selector, SelectorSemantics())
    prefixes = tuple(
        semantics
        for prefix, semantics in _PREFIX_SELECTOR_SEMANTICS
        if selector.startswith(prefix)
    )
    if not prefixes:
        return exact
    return SelectorSemantics(
        mechanical=exact.mechanical or any(item.mechanical for item in prefixes),
        semantic_roles=_unique(
            (*exact.semantic_roles, *(role for item in prefixes for role in item.semantic_roles))
        ),
        condition_kinds=_unique(
            (*exact.condition_kinds, *(kind for item in prefixes for kind in item.condition_kinds))
        ),
        requires_materialized_state=(
            exact.requires_materialized_state
            or any(item.requires_materialized_state for item in prefixes)
        ),
        context_prerequisites=_unique(
            (
                *exact.context_prerequisites,
                *(value for item in prefixes for value in item.context_prerequisites),
            )
        ),
        prerequisite_condition_kind=(
            exact.prerequisite_condition_kind
            or next(
                (
                    item.prerequisite_condition_kind
                    for item in prefixes
                    if item.prerequisite_condition_kind is not None
                ),
                None,
            )
        ),
        semantic_evidence_resolver=(
            exact.semantic_evidence_resolver
            or next(
                (
                    item.semantic_evidence_resolver
                    for item in prefixes
                    if item.semantic_evidence_resolver is not None
                ),
                None,
            )
        ),
    )


def expansion_selector_semantics(selector: str) -> ExpansionSelectorSemantics:
    return _EXPANSION_SELECTOR_SEMANTICS.get(
        selector,
        ExpansionSelectorSemantics(),
    )


def selector_context_binding(
    selector: str,
) -> tuple[CapabilityContextResolver, str] | None:
    """Project one selector grammar to its Context resolver semantic role."""
    for prefix, resolver_id, role_aliases in _CONTEXT_SELECTOR_PREFIXES:
        if not selector.startswith(prefix):
            continue
        raw_role = selector[len(prefix):]
        if not raw_role:
            return None
        return resolver_id, role_aliases.get(raw_role, raw_role)
    return None


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return unique_ordered(values)


__all__ = [
    "ExpansionSelectorSemantics",
    "SelectorSemantics",
    "expansion_selector_semantics",
    "selector_context_binding",
    "selector_semantics",
]
