"""Structured role resolution for two-moving-point path reduction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.path_term_parsing import (
    PathTermParseError,
    parse_legacy_path_expression,
    parse_path_terms,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class PathSegmentRef:
    start: str
    end: str

    @property
    def endpoints(self) -> tuple[str, str]:
        return self.start, self.end

    def other(self, point_ref: str) -> str:
        if self.start == point_ref:
            return self.end
        if self.end == point_ref:
            return self.start
        raise PathReductionRoleError(
            "path_reduction.point_not_on_segment",
            f"{point_ref} is not an endpoint of {self.start}-{self.end}",
        )


@dataclass(frozen=True)
class ScaledPathSegmentRef:
    scale: str
    segment: PathSegmentRef


@dataclass(frozen=True)
class PathReductionRoles:
    path_target: str
    first_membership: str
    second_membership: str
    binding_relation: str
    first_moving_point: str
    second_moving_point: str
    first_segment_start: str
    joint_point: str
    second_segment_end: str
    transformed_fixed_endpoint: str
    first_track: str
    second_track: str

    @property
    def required_condition_handles(self) -> tuple[str, ...]:
        return (
            self.path_target,
            self.first_membership,
            self.second_membership,
            self.binding_relation,
        )

    @property
    def required_point_handles(self) -> tuple[str, ...]:
        return (
            self.first_segment_start,
            self.joint_point,
            self.second_segment_end,
        )


class PathReductionRoleError(ValueError):
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


class PathReductionBindingIndex(Protocol):
    fact_types: Mapping[str, str]
    handle_registry: CanonicalHandleRegistry

    def binding_for(self, handle: str) -> Any: ...


class PathReductionRoleResolver:
    """Resolve one unique path-reduction graph from canonical ProblemIR."""

    @classmethod
    def resolve(
        cls,
        *,
        path_target: str,
        scope_id: str,
        registry: CanonicalHandleRegistry,
    ) -> PathReductionRoles:
        path_payload = registry.fact_payloads.get(path_target, {})
        path_segments = _path_segments(path_payload, registry, scope_id=scope_id)
        if len(path_segments) != 2:
            raise PathReductionRoleError(
                "path_reduction.path_shape_invalid",
                "path reduction requires a two-segment path",
            )
        second_moving = _common_endpoint(path_segments[0], path_segments[1])
        if second_moving is None:
            raise PathReductionRoleError(
                "path_reduction.moving_point_unresolved",
                "the two path terms do not share one moving endpoint",
            )
        memberships = _visible_facts(
            registry,
            fact_type="segment_membership",
            scope_id=scope_id,
        )
        path_outer_points = tuple(
            segment.other(second_moving) for segment in path_segments
        )
        moving_candidates = tuple(
            point_ref
            for point_ref in path_outer_points
            if any(
                registry.fact_payloads.get(handle, {}).get("point")
                == point_ref
                for handle in memberships
            )
        )
        if len(moving_candidates) != 1:
            raise PathReductionRoleError(
                "path_reduction.first_moving_point_ambiguous",
                "one outer path endpoint must be the first moving point",
                details={"candidates": list(moving_candidates)},
            )
        first_moving = moving_candidates[0]
        transformed_fixed = next(
            point_ref
            for point_ref in path_outer_points
            if point_ref != first_moving
        )
        first_membership = _unique_membership(
            first_moving,
            memberships,
            registry=registry,
        )
        second_membership = _unique_membership(
            second_moving,
            memberships,
            registry=registry,
        )
        first_track = _membership_segment(
            registry.fact_payloads[first_membership],
        )
        second_track = _membership_segment(
            registry.fact_payloads[second_membership],
        )
        first_track_segment = _entity_segment(first_track, registry)
        second_track_segment = _entity_segment(second_track, registry)
        joint = _common_endpoint(first_track_segment, second_track_segment)
        if joint is None:
            raise PathReductionRoleError(
                "path_reduction.joint_point_unresolved",
                "the moving-point tracks do not share one joint point",
            )

        relations = _visible_facts(
            registry,
            fact_type="segment_relation",
            scope_id=scope_id,
        )
        compatible: list[tuple[str, str, str]] = []
        for relation in relations:
            terms = _relation_terms(
                registry.fact_payloads.get(relation, {}),
                registry,
                scope_id=scope_id,
            )
            if len(terms) != 2:
                continue
            first_term = next(
                (
                    item
                    for item in terms
                    if first_moving in item.segment.endpoints
                ),
                None,
            )
            second_term = next(
                (
                    item
                    for item in terms
                    if second_moving in item.segment.endpoints
                ),
                None,
            )
            if first_term is None or second_term is None or first_term == second_term:
                continue
            first_fixed = first_term.segment.other(first_moving)
            second_fixed = second_term.segment.other(second_moving)
            if (
                first_fixed not in first_track_segment.endpoints
                or second_fixed not in second_track_segment.endpoints
                or joint not in first_track_segment.endpoints
                or joint not in second_track_segment.endpoints
            ):
                continue
            compatible.append((relation, first_fixed, second_fixed))
        if len(compatible) != 1:
            raise PathReductionRoleError(
                (
                    "path_reduction.binding_relation_missing"
                    if not compatible
                    else "path_reduction.binding_relation_ambiguous"
                ),
                "one binding relation must connect the two moving points",
                details={"candidates": [item[0] for item in compatible]},
            )
        relation, first_fixed, second_fixed = compatible[0]
        return PathReductionRoles(
            path_target=path_target,
            first_membership=first_membership,
            second_membership=second_membership,
            binding_relation=relation,
            first_moving_point=first_moving,
            second_moving_point=second_moving,
            first_segment_start=first_fixed,
            joint_point=joint,
            second_segment_end=second_fixed,
            transformed_fixed_endpoint=transformed_fixed,
            first_track=first_track,
            second_track=second_track,
        )


def resolve_read_closed_path_reduction_inputs(
    step: StepIntent,
    index: PathReductionBindingIndex,
) -> PathReductionRoles:
    targets = tuple(
        handle
        for handle in step.reads
        if index.fact_types.get(handle) == "path_minimum_target"
    )
    if len(targets) != 1:
        raise StrategyDraftValidationError(
            "path_reduction_target_read_"
            + ("missing" if not targets else "ambiguous")
        )
    try:
        roles = PathReductionRoleResolver.resolve(
            path_target=targets[0],
            scope_id=step.scope_id,
            registry=index.handle_registry,
        )
    except PathReductionRoleError as exc:
        raise StrategyDraftValidationError(f"{exc.code}: {exc}") from exc
    missing_conditions = [
        handle
        for handle in roles.required_condition_handles
        if handle not in step.reads
    ]
    if missing_conditions:
        raise StrategyDraftValidationError(
            "path_reduction_condition_reads_missing: "
            f"{missing_conditions}"
        )
    for handle in roles.required_point_handles:
        if handle not in step.reads:
            raise StrategyDraftValidationError(
                f"path_reduction_point_read_missing: {handle}"
            )
        try:
            binding = index.binding_for(handle)
        except StrategyDraftValidationError as exc:
            raise StrategyDraftValidationError(
                f"path_reduction_point_state_unavailable: {handle}"
            ) from exc
        if binding.value_type != "Point":
            raise StrategyDraftValidationError(
                f"path_reduction_point_state_unavailable: {handle}, "
                f"actual={binding.value_type}"
            )
    return roles


def _visible_facts(
    registry: CanonicalHandleRegistry,
    *,
    fact_type: str,
    scope_id: str,
) -> tuple[str, ...]:
    return tuple(
        handle
        for handle, current_type in registry.fact_types.items()
        if current_type == fact_type
        and visible_from_valid_scope(
            registry.handle_valid_scopes.get(handle, "problem"),
            scope_id=scope_id,
            registry=registry,
        )
    )


def _unique_membership(
    point_ref: str,
    memberships: Sequence[str],
    *,
    registry: CanonicalHandleRegistry,
) -> str:
    matches = tuple(
        handle
        for handle in memberships
        if registry.fact_payloads.get(handle, {}).get("point") == point_ref
    )
    if len(matches) != 1:
        raise PathReductionRoleError(
            (
                "path_reduction.membership_missing"
                if not matches
                else "path_reduction.membership_ambiguous"
            ),
            f"one segment membership is required for {point_ref}",
            details={"point_ref": point_ref, "candidates": list(matches)},
        )
    return matches[0]


def _membership_segment(payload: Mapping[str, Any]) -> str:
    segment = payload.get("segment")
    if not isinstance(segment, str) or not segment.startswith("segment:"):
        raise PathReductionRoleError(
            "path_reduction.membership_invalid",
            "segment membership must reference a canonical segment",
        )
    return segment


def _entity_segment(
    handle: str,
    registry: CanonicalHandleRegistry,
) -> PathSegmentRef:
    payload = registry.entity_payloads.get(handle, {})
    endpoints = payload.get("endpoints")
    if (
        not isinstance(endpoints, list)
        or len(endpoints) != 2
        or not all(_is_point_ref(item) for item in endpoints)
    ):
        raise PathReductionRoleError(
            "path_reduction.segment_invalid",
            f"segment entity has no canonical endpoints: {handle}",
        )
    return PathSegmentRef(str(endpoints[0]), str(endpoints[1]))


def _path_segments(
    payload: Mapping[str, Any],
    registry: CanonicalHandleRegistry,
    *,
    scope_id: str,
) -> tuple[PathSegmentRef, ...]:
    try:
        terms = parse_path_terms(
            payload,
            point_names=_visible_point_names(registry, scope_id=scope_id),
            resolve_point=lambda name: _point_ref_by_name(
                name,
                registry,
                scope_id=scope_id,
            ),
        )
    except PathTermParseError as exc:
        raise PathReductionRoleError(
            exc.code.replace("path_terms.", "path_reduction."),
            str(exc),
            details=exc.details,
        ) from exc
    return tuple(PathSegmentRef(item.start, item.end) for item in terms)


def _relation_terms(
    payload: Mapping[str, Any],
    registry: CanonicalHandleRegistry,
    *,
    scope_id: str,
) -> tuple[ScaledPathSegmentRef, ...]:
    structured = tuple(
        _structured_scaled_segment(payload.get(key))
        for key in ("left_term", "right_term")
    )
    if all(item is not None for item in structured):
        return tuple(item for item in structured if item is not None)
    return (
        _legacy_scaled_segment(
            str(payload.get("left", "")),
            registry,
            scope_id=scope_id,
        ),
        _legacy_scaled_segment(
            str(payload.get("right", "")),
            registry,
            scope_id=scope_id,
        ),
    )


def _structured_scaled_segment(value: Any) -> ScaledPathSegmentRef | None:
    if not isinstance(value, Mapping):
        return None
    segment = _structured_segment(value.get("segment"))
    if segment is None:
        return None
    return ScaledPathSegmentRef(str(value.get("scale", "1")), segment)


def _structured_segment(value: Any) -> PathSegmentRef | None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(_is_point_ref(item) for item in value)
    ):
        return None
    return PathSegmentRef(str(value[0]), str(value[1]))


def _legacy_scaled_segment(
    value: str,
    registry: CanonicalHandleRegistry,
    *,
    scope_id: str,
) -> ScaledPathSegmentRef:
    try:
        terms = parse_legacy_path_expression(
            value,
            point_names=_visible_point_names(registry, scope_id=scope_id),
            resolve_point=lambda name: _point_ref_by_name(
                name,
                registry,
                scope_id=scope_id,
            ),
        )
    except PathTermParseError as exc:
        raise PathReductionRoleError(
            exc.code.replace("path_terms.", "path_reduction."),
            str(exc),
            details=exc.details,
        ) from exc
    if len(terms) != 1:
        raise PathReductionRoleError(
            "path_reduction.relation_term_invalid",
            f"cannot parse segment term: {value}",
        )
    term = terms[0]
    return ScaledPathSegmentRef(
        term.scale,
        PathSegmentRef(term.start, term.end),
    )


def _visible_point_names(
    registry: CanonicalHandleRegistry,
    *,
    scope_id: str,
) -> tuple[str, ...]:
    return unique_ordered(
        handle.rsplit(":", 1)[-1]
        for handle in registry.entity_handles
        if handle.startswith("point:")
        and visible_from_valid_scope(
            registry.handle_valid_scopes.get(handle, "problem"),
            scope_id=scope_id,
            registry=registry,
        )
    )


def _point_ref_by_name(
    name: str,
    registry: CanonicalHandleRegistry,
    *,
    scope_id: str,
) -> str:
    candidates = tuple(
        handle
        for handle in registry.entity_handles
        if handle.startswith("point:")
        and handle.rsplit(":", 1)[-1] == name
        and visible_from_valid_scope(
            registry.handle_valid_scopes.get(handle, "problem"),
            scope_id=scope_id,
            registry=registry,
        )
    )
    if len(candidates) != 1:
        raise PathReductionRoleError(
            "path_reduction.point_ref_ambiguous",
            f"point name cannot be resolved uniquely: {name}",
            details={"candidates": list(candidates)},
        )
    return candidates[0]


def _common_endpoint(
    first: PathSegmentRef,
    second: PathSegmentRef,
) -> str | None:
    common = set(first.endpoints) & set(second.endpoints)
    return next(iter(common)) if len(common) == 1 else None


def _is_point_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("point:")
