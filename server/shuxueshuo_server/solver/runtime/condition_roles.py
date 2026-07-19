"""Structured object-role resolution for semantic Conditions.

Condition roles come from ProblemIR fields, never from fact handle names or
descriptions. The same resolver is shared by Context projection, FunctionalPlan
reconciliation, and runtime binding so those layers cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.utils import unique_ordered


ConditionObjectRoles = tuple[tuple[str, tuple[str, ...]], ...]
ConditionRoleExtractor = Callable[[Mapping[str, Any]], ConditionObjectRoles]


def _right_angle_equal_length_roles(
    payload: Mapping[str, Any],
) -> ConditionObjectRoles:
    angle = payload.get("angle")
    if (
        not isinstance(angle, list)
        or len(angle) != 3
        or not all(_is_point_handle(item) for item in angle)
    ):
        raise ConditionRoleResolutionError(
            "condition.roles_invalid",
            "right_angle_equal_length requires a structured three-point angle",
            details={"field": "angle"},
        )
    return (
        ("anchor", (str(angle[1]),)),
        ("endpoint", (str(angle[0]), str(angle[2]))),
    )


_CONDITION_ROLE_EXTRACTORS: Mapping[str, ConditionRoleExtractor] = {
    "right_angle_equal_length": _right_angle_equal_length_roles,
}


class ConditionBindingIndex(Protocol):
    """Runtime binding surface required by read-closed condition compilation."""

    fact_types: Mapping[str, str]

    def binding_for(self, handle: str) -> Any: ...

    def fact_payload(self, handle: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ConstructedPointRoles:
    """Resolved object roles for a relation that constructs one endpoint."""

    anchor: str
    reference: str
    target: str


@dataclass(frozen=True)
class ReadClosedRightAngleInputs:
    """Every canonical handle consumed by the right-angle selection recipe."""

    relation: str
    anchor: str
    reference: str
    target: str
    orientation: str
    parameter: str
    parameter_constraint: str


class ConditionRoleResolutionError(ValueError):
    """Typed failure raised while resolving structured Condition roles."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class ConditionRoleResolver:
    """Resolve Condition object roles from registered structured extractors."""

    @classmethod
    def supports(cls, condition_kind: str) -> bool:
        return condition_kind in _CONDITION_ROLE_EXTRACTORS

    @classmethod
    def object_roles(
        cls,
        condition_kind: str,
        payload: Mapping[str, Any],
    ) -> ConditionObjectRoles:
        extractor = _CONDITION_ROLE_EXTRACTORS.get(condition_kind)
        if extractor is None:
            return ()
        return extractor(payload)

    @classmethod
    def resolve_constructed_point_roles(
        cls,
        object_roles: ConditionObjectRoles,
        *,
        target_hints: Sequence[str] = (),
        materialized_points: Sequence[str] = (),
    ) -> ConstructedPointRoles:
        roles = dict(object_roles)
        anchors = roles.get("anchor", ())
        endpoints = roles.get("endpoint", ())
        if len(anchors) != 1 or len(endpoints) != 2:
            raise ConditionRoleResolutionError(
                "condition.roles_invalid",
                "condition must declare one anchor and two endpoints",
                details={
                    "anchor_count": len(anchors),
                    "endpoint_count": len(endpoints),
                },
            )
        hinted = unique_ordered(
            item for item in target_hints if item in endpoints
        )
        if len(hinted) > 1:
            raise ConditionRoleResolutionError(
                "condition.target_ambiguous",
                "multiple target hints match the condition endpoints",
                details={"target_candidates": list(hinted)},
            )
        if hinted:
            target = hinted[0]
        else:
            materialized = set(materialized_points)
            unresolved = tuple(item for item in endpoints if item not in materialized)
            if len(unresolved) != 1:
                raise ConditionRoleResolutionError(
                    (
                        "condition.target_unresolved"
                        if not unresolved
                        else "condition.target_ambiguous"
                    ),
                    "the constructed endpoint cannot be determined uniquely",
                    details={
                        "endpoints": list(endpoints),
                        "materialized_points": sorted(materialized & set(endpoints)),
                        "target_candidates": list(unresolved),
                    },
                )
            target = unresolved[0]
        reference = endpoints[1] if endpoints[0] == target else endpoints[0]
        return ConstructedPointRoles(
            anchor=anchors[0],
            reference=reference,
            target=target,
        )

def resolve_read_closed_right_angle_inputs(
    step: StepIntent,
    index: ConditionBindingIndex,
) -> ReadClosedRightAngleInputs:
    """Resolve recipe inputs exclusively from the current canonical reads."""

    relation, roles = resolve_read_closed_constructed_point_roles(step, index)
    orientation = _unique_read_fact(
        step,
        index,
        fact_type="orientation_constraint",
        predicate=lambda payload: payload.get("subject") == roles.target,
        error_prefix="right_angle_orientation",
    )
    parameter_candidates = tuple(
        handle for handle in step.reads if handle.startswith("symbol:")
    )
    if len(parameter_candidates) != 1:
        raise StrategyDraftValidationError(
            "right_angle_parameter_read_"
            + ("missing" if not parameter_candidates else "ambiguous")
        )
    parameter = parameter_candidates[0]
    parameter_constraint = _unique_read_fact(
        step,
        index,
        fact_type="symbol_constraint",
        predicate=lambda payload: payload.get("subject") == parameter,
        error_prefix="right_angle_parameter_constraint",
    )
    return ReadClosedRightAngleInputs(
        relation=relation,
        anchor=roles.anchor,
        reference=roles.reference,
        target=roles.target,
        orientation=orientation,
        parameter=parameter,
        parameter_constraint=parameter_constraint,
    )


def resolve_read_closed_constructed_point_roles(
    step: StepIntent,
    index: ConditionBindingIndex,
) -> tuple[str, ConstructedPointRoles]:
    """Resolve relation object roles without consulting non-read state."""

    relation_handles = tuple(
        handle
        for handle in step.reads
        if index.fact_types.get(handle) == "right_angle_equal_length"
    )
    if len(relation_handles) != 1:
        raise StrategyDraftValidationError(
            "right_angle_relation_read_"
            + ("missing" if not relation_handles else "ambiguous")
        )
    relation = relation_handles[0]
    try:
        object_roles = ConditionRoleResolver.object_roles(
            "right_angle_equal_length",
            index.fact_payload(relation),
        )
        endpoint_handles = dict(object_roles).get("endpoint", ())
        materialized = tuple(
            handle
            for handle in endpoint_handles
            if _read_handle_for_object(
                handle,
                expected_type="Point",
                step=step,
                index=index,
            )
            is not None
        )
        target_hints = tuple(
            handle
            for handle in endpoint_handles
            if _read_handle_for_object(
                handle,
                expected_type="PointRef",
                step=step,
                index=index,
            )
            is not None
        )
        roles = ConditionRoleResolver.resolve_constructed_point_roles(
            object_roles,
            target_hints=target_hints,
            materialized_points=materialized,
        )
    except ConditionRoleResolutionError as exc:
        raise StrategyDraftValidationError(f"{exc.code}: {exc}") from exc

    return relation, ConstructedPointRoles(
        anchor=_require_read_object_type(
            step,
            index,
            roles.anchor,
            "Point",
        ),
        reference=_require_read_object_type(
            step,
            index,
            roles.reference,
            "Point",
        ),
        target=_require_read_object_type(
            step,
            index,
            roles.target,
            "PointRef",
        ),
    )


def resolve_read_closed_right_angle_method_roles(
    step: StepIntent,
    index: ConditionBindingIndex,
) -> ConstructedPointRoles:
    """Resolve direct method roles from the same structured relation contract."""

    _relation, roles = resolve_read_closed_constructed_point_roles(step, index)
    return roles


def _read_binding_type(
    handle: str,
    *,
    step: StepIntent,
    index: ConditionBindingIndex,
) -> str | None:
    if handle not in step.reads:
        return None
    try:
        return str(index.binding_for(handle).value_type)
    except StrategyDraftValidationError:
        return None


def _require_read_object_type(
    step: StepIntent,
    index: ConditionBindingIndex,
    object_handle: str,
    expected_type: str,
) -> str:
    handle = _read_handle_for_object(
        object_handle,
        expected_type=expected_type,
        step=step,
        index=index,
    )
    if handle is None:
        raise StrategyDraftValidationError(
            f"right_angle_role_state_unavailable: handle={object_handle}, "
            f"expected={expected_type}, actual=None"
        )
    return handle


def _read_handle_for_object(
    object_handle: str,
    *,
    expected_type: str,
    step: StepIntent,
    index: ConditionBindingIndex,
) -> str | None:
    """Find the read alias carrying one structured object's required state."""

    object_path = None
    try:
        object_path = str(index.binding_for(object_handle).path)
    except StrategyDraftValidationError:
        pass
    provenance = tuple(getattr(index, "state_write_provenance", ()))
    matches: list[str] = []
    for handle in step.reads:
        try:
            binding = index.binding_for(handle)
        except StrategyDraftValidationError:
            continue
        if str(binding.value_type) != expected_type:
            continue
        identity_matches = handle == object_handle
        if not identity_matches and object_path is not None:
            identity_matches = str(binding.path) == object_path
        if not identity_matches and index.fact_types.get(handle) is not None:
            payload = index.fact_payload(handle)
            identity_matches = any(
                payload.get(key) == object_handle
                for key in ("point", "subject", "target", "object")
            )
        if not identity_matches:
            identity_matches = any(
                getattr(item, "produced_handle", None) == handle
                and getattr(item, "object_ref", None) == object_handle
                for item in provenance
            )
        if identity_matches:
            matches.append(handle)
    return unique_ordered(matches)[0] if matches else None


def _unique_read_fact(
    step: StepIntent,
    index: ConditionBindingIndex,
    *,
    fact_type: str,
    predicate: Any,
    error_prefix: str,
) -> str:
    matches = tuple(
        handle
        for handle in step.reads
        if index.fact_types.get(handle) == fact_type
        and predicate(index.fact_payload(handle))
    )
    if len(matches) != 1:
        raise StrategyDraftValidationError(
            f"{error_prefix}_read_"
            + ("missing" if not matches else "ambiguous")
        )
    return matches[0]


def _is_point_handle(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("point:")
