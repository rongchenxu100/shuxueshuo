"""Declarative object-identity validation for Functional capabilities."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence

from shuxueshuo_server.solver.family.models import StateIdentityConstraintSpec
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalPlanIssue,
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
    _issue,
)
from shuxueshuo_server.solver.state_semantics import (
    state_object_refs_for_role,
)
from shuxueshuo_server.solver.utils import unique_ordered


_SELECTOR = re.compile(
    r"^(?P<kind>arg|return):(?P<name>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<field>object_ref|object_role:[A-Za-z_][A-Za-z0-9_]*)$"
)


def validate_state_identity_constraint_specs(
    constraints: Sequence[StateIdentityConstraintSpec],
    *,
    arg_names: Sequence[str],
    return_names: Sequence[str],
) -> None:
    """Reject malformed identity contracts before an LLM request is made."""
    known_args = set(arg_names)
    known_returns = set(return_names)
    for constraint in constraints:
        for selector in (constraint.left, constraint.right):
            match = _SELECTOR.fullmatch(selector)
            if match is None:
                raise ValueError(
                    "planner_configuration_error: invalid state identity "
                    f"selector: {selector}"
                )
            name = match.group("name")
            known = known_args if match.group("kind") == "arg" else known_returns
            if name not in known:
                raise ValueError(
                    "planner_configuration_error: state identity selector "
                    f"references unknown {match.group('kind')}: {selector}"
                )


@dataclass(frozen=True)
class _IdentitySelection:
    selector: str
    object_refs: tuple[str, ...]
    source_call_ids: tuple[str, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()


class StateIdentityConstraintValidator:
    """Evaluate contract identity joins without capability-specific dispatch.

    Contract selectors are directional: ``left`` is the value being checked and
    ``right`` is the authoritative identity required by the capability. This
    lets graph retry repair the incorrect producer without discarding the
    already verified identity anchor.
    """

    def validate(
        self,
        constraints: Sequence[StateIdentityConstraintSpec],
        *,
        call_id: str,
        scope_id: str,
        resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
        returns: Sequence[FunctionalReturnAllocation],
    ) -> tuple[FunctionalPlanIssue, ...]:
        issues: list[FunctionalPlanIssue] = []
        returns_by_name = {item.return_name: item for item in returns}
        for constraint in constraints:
            if (
                constraint.applicability == "when_all_present"
                and not all(
                    _selector_has_value(
                        selector,
                        resolved_args=resolved_args,
                        returns_by_name=returns_by_name,
                    )
                    for selector in (constraint.left, constraint.right)
                )
            ):
                continue
            left = self._select(
                constraint.left,
                resolved_args=resolved_args,
                returns_by_name=returns_by_name,
            )
            right = self._select(
                constraint.right,
                resolved_args=resolved_args,
                returns_by_name=returns_by_name,
            )
            if (
                left is None
                or right is None
                or len(left.object_refs) != 1
                or len(right.object_refs) != 1
            ):
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.identity_constraint_unresolved",
                        "object identity constraint could not be resolved uniquely",
                        call_id=call_id,
                        scope_id=scope_id,
                        details={
                            "left": _selection_payload(left, constraint.left),
                            "right": _selection_payload(right, constraint.right),
                            "relation": constraint.relation,
                            "repair_call_ids": list(
                                _repair_call_ids(left, call_id)
                            ),
                        },
                    )
                )
                continue
            if left.object_refs[0] == right.object_refs[0]:
                continue
            issues.append(
                _issue(
                    "functional_reconciliation",
                    "functional.object_identity_mismatch",
                    "capability inputs and return refer to different math objects",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "left": _selection_payload(left, constraint.left),
                        "right": _selection_payload(right, constraint.right),
                        "actual_object_refs": list(left.object_refs),
                        "expected_object_refs": list(right.object_refs),
                        "relation": constraint.relation,
                        "requirement": constraint.description,
                        "repair_call_ids": list(_repair_call_ids(left, call_id)),
                    },
                )
            )
        return tuple(issues)

    def _select(
        self,
        selector: str,
        *,
        resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
        returns_by_name: Mapping[str, FunctionalReturnAllocation],
    ) -> _IdentitySelection | None:
        match = _SELECTOR.fullmatch(selector)
        if match is None:
            raise ValueError(
                "planner_configuration_error: invalid state identity selector: "
                f"{selector}"
            )
        kind = match.group("kind")
        name = match.group("name")
        field = match.group("field")
        if kind == "arg":
            values = resolved_args.get(name, ())
            return _selection_from_values(selector, field, values)
        returned = returns_by_name.get(name)
        if returned is None:
            return None
        return _selection_from_return(selector, field, returned)


def infer_unique_return_object_refs(
    constraints: Sequence[StateIdentityConstraintSpec],
    *,
    return_name: str,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
) -> tuple[str, ...]:
    """Infer a return identity from declarative ``same_object`` constraints.

    This is intentionally narrower than validation: only an argument selector
    may supply the identity, every applicable constraint must resolve uniquely,
    and all resolved constraints must agree. It therefore cannot invent an
    object from type compatibility or from a globally unique Point/Line.
    """

    return_selector = f"return:{return_name}.object_ref"
    inferred: list[str] = []
    for constraint in constraints:
        if constraint.relation != "same_object":
            continue
        if constraint.left == return_selector:
            source_selector = constraint.right
        elif constraint.right == return_selector:
            source_selector = constraint.left
        else:
            continue
        match = _SELECTOR.fullmatch(source_selector)
        if match is None or match.group("kind") != "arg":
            continue
        values = resolved_args.get(match.group("name"), ())
        if not values and constraint.applicability == "when_all_present":
            continue
        selection = _selection_from_values(
            source_selector,
            match.group("field"),
            values,
        )
        if len(selection.object_refs) != 1:
            return ()
        inferred.append(selection.object_refs[0])
    refs = unique_ordered(inferred)
    return refs if len(refs) == 1 else ()


def _selector_has_value(
    selector: str,
    *,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    returns_by_name: Mapping[str, FunctionalReturnAllocation],
) -> bool:
    match = _SELECTOR.fullmatch(selector)
    if match is None:
        raise ValueError(
            "planner_configuration_error: invalid state identity selector: "
            f"{selector}"
        )
    if match.group("kind") == "arg":
        return bool(resolved_args.get(match.group("name")))
    return match.group("name") in returns_by_name


def _selection_from_values(
    selector: str,
    field: str,
    values: Sequence[ResolvedFunctionalValue],
) -> _IdentitySelection:
    role = field.split(":", 1)[1] if field.startswith("object_role:") else None
    object_refs: list[str] = []
    source_call_ids: list[str] = []
    source_slots: list[str] = []
    for value in values:
        if role is None:
            if value.object_ref is not None:
                object_refs.append(value.object_ref)
        else:
            object_refs.extend(state_object_refs_for_role(value.lineage, role))
            object_refs.extend(dict(value.object_roles).get(role, ()))
        if value.source_call_id is not None:
            source_call_ids.append(value.source_call_id)
        source_slots.extend(value.source_state_slot_ids)
        if value.state_slot_id is not None:
            source_slots.append(value.state_slot_id)
    return _IdentitySelection(
        selector=selector,
        object_refs=unique_ordered(object_refs),
        source_call_ids=unique_ordered(source_call_ids),
        source_state_slot_ids=unique_ordered(source_slots),
    )


def _selection_from_return(
    selector: str,
    field: str,
    returned: FunctionalReturnAllocation,
) -> _IdentitySelection:
    role = field.split(":", 1)[1] if field.startswith("object_role:") else None
    object_refs = (
        state_object_refs_for_role(returned.lineage, role)
        if role is not None
        else ((returned.object_ref,) if returned.object_ref is not None else ())
    )
    return _IdentitySelection(
        selector=selector,
        object_refs=unique_ordered(object_refs),
        source_call_ids=(returned.call_id,),
        source_state_slot_ids=unique_ordered(
            (returned.state_slot_id, *returned.source_state_slot_ids)
        ),
    )


def _selection_payload(
    selection: _IdentitySelection | None,
    selector: str,
) -> dict[str, object]:
    return {
        "selector": selector,
        "object_refs": list(selection.object_refs) if selection else [],
        "source_call_ids": list(selection.source_call_ids) if selection else [],
        "source_state_slot_ids": (
            list(selection.source_state_slot_ids) if selection else []
        ),
    }


def _repair_call_ids(
    actual: _IdentitySelection | None,
    current_call_id: str,
) -> tuple[str, ...]:
    return unique_ordered(
        (
            *((actual.source_call_ids if actual is not None else ())),
            current_call_id,
        )
    )


__all__ = [
    "StateIdentityConstraintValidator",
    "infer_unique_return_object_refs",
    "validate_state_identity_constraint_specs",
]
