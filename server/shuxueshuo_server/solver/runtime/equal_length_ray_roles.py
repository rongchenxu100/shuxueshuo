"""Structured role resolution for equal-length ray path reduction."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.runtime.path_term_parsing import (
    PathTermParseError,
    parse_path_terms,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class EqualLengthRayPathRoles:
    anchor: str
    ray_point: str
    reference_point: str
    fixed_point: str


class EqualLengthRayRoleError(ValueError):
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


def resolve_equal_length_ray_path_roles(
    *,
    ray_payload: Mapping[str, Any],
    segment_payload: Mapping[str, Any],
    equal_payload: Mapping[str, Any],
    target_payload: Mapping[str, Any],
    entity_payload: Callable[[str], Mapping[str, Any]],
    visible_point_handles: Iterable[str],
    resolve_point_name: Callable[[str], str],
) -> EqualLengthRayPathRoles:
    """Resolve all materialized point roles from structured ProblemIR facts."""

    point_handles = tuple(unique_ordered(visible_point_handles))
    point_names = tuple(
        unique_ordered(handle.rsplit(":", 1)[-1] for handle in point_handles)
    )
    ray_dynamic_point = _payload_handle(ray_payload, "point")
    ray_handle = _payload_handle(ray_payload, "ray")
    ray_entity = entity_payload(ray_handle)
    ray_origin = _payload_handle(ray_entity, "origin")
    ray_through = _payload_handle(ray_entity, "through")

    segment_dynamic_point = _payload_handle(segment_payload, "point")
    segment_handle = _payload_handle(segment_payload, "segment")
    segment_endpoints = _segment_endpoints(entity_payload(segment_handle))

    left = _length_endpoints(
        equal_payload.get("left"),
        point_names=point_names,
        resolve_point_name=resolve_point_name,
    )
    right = _length_endpoints(
        equal_payload.get("right"),
        point_names=point_names,
        resolve_point_name=resolve_point_name,
    )
    common = tuple(sorted(set(left) & set(right)))
    if len(common) != 1:
        raise EqualLengthRayRoleError(
            "equal_length_common_anchor_unresolved",
            "equal-length sides must have one common endpoint",
            details={"left": left, "right": right},
        )
    anchor = common[0]
    if anchor != ray_origin:
        raise EqualLengthRayRoleError(
            "equal_length_ray_anchor_mismatch",
            "the equal-length common endpoint must be the ray origin",
        )
    if anchor not in segment_endpoints:
        raise EqualLengthRayRoleError(
            "equal_length_segment_anchor_mismatch",
            "the equal-length common endpoint must be a segment endpoint",
        )
    if ray_dynamic_point not in left and ray_dynamic_point not in right:
        raise EqualLengthRayRoleError(
            "equal_length_ray_dynamic_point_mismatch",
            "the point-on-ray object must occur in the equal-length relation",
        )
    if segment_dynamic_point not in left and segment_dynamic_point not in right:
        raise EqualLengthRayRoleError(
            "equal_length_segment_dynamic_point_mismatch",
            "the point-on-segment object must occur in the equal-length relation",
        )

    reference_point = _other_endpoint(segment_endpoints, anchor)
    try:
        terms = parse_path_terms(
            target_payload,
            point_names=point_names,
            resolve_point=resolve_point_name,
        )
    except PathTermParseError as exc:
        raise EqualLengthRayRoleError(
            exc.code,
            str(exc),
            details=exc.details,
        ) from exc
    fixed_point: str | None = None
    path_reference_point: str | None = None
    for term in terms:
        pair = (term.start, term.end)
        if segment_dynamic_point in pair:
            fixed_point = _other_endpoint(pair, segment_dynamic_point)
        if ray_dynamic_point in pair:
            path_reference_point = _other_endpoint(pair, ray_dynamic_point)
    if fixed_point is None:
        raise EqualLengthRayRoleError(
            "equal_length_path_fixed_point_unresolved",
            "the path target must contain the point-on-segment object",
        )
    if path_reference_point is None:
        raise EqualLengthRayRoleError(
            "equal_length_path_reference_point_unresolved",
            "the path target must contain the point-on-ray object",
        )
    if path_reference_point != reference_point:
        raise EqualLengthRayRoleError(
            "equal_length_path_reference_mismatch",
            "the path target and segment relation identify different reference points",
        )
    return EqualLengthRayPathRoles(
        anchor=anchor,
        ray_point=ray_through,
        reference_point=reference_point,
        fixed_point=fixed_point,
    )


def _payload_handle(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise EqualLengthRayRoleError(
            "structured_payload_field_missing",
            f"structured payload is missing {key}",
            details={"field": key},
        )
    return value


def _segment_endpoints(payload: Mapping[str, Any]) -> tuple[str, str]:
    endpoints = payload.get("endpoints")
    if (
        not isinstance(endpoints, list)
        or len(endpoints) != 2
        or not all(isinstance(item, str) for item in endpoints)
    ):
        raise EqualLengthRayRoleError(
            "segment_endpoints_missing",
            "segment entity must declare exactly two endpoint handles",
        )
    return endpoints[0], endpoints[1]


def _length_endpoints(
    value: Any,
    *,
    point_names: tuple[str, ...],
    resolve_point_name: Callable[[str], str],
) -> tuple[str, str]:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, str) for item in value)
    ):
        return value[0], value[1]
    if not isinstance(value, str) or ":" in value:
        raise EqualLengthRayRoleError(
            "invalid_length_endpoint_pair",
            "equal-length side must identify exactly two points",
        )
    candidates = tuple(
        unique_ordered(
            (start, end)
            for start in point_names
            for end in point_names
            if f"{start}{end}" == value
        )
    )
    if len(candidates) != 1:
        raise EqualLengthRayRoleError(
            "length_endpoint_pair_unresolved",
            "equal-length side must have one unique split against visible points",
            details={"value": value, "candidates": candidates},
        )
    start, end = candidates[0]
    return resolve_point_name(start), resolve_point_name(end)


def _other_endpoint(pair: tuple[str, str], endpoint: str) -> str:
    if pair[0] == endpoint:
        return pair[1]
    if pair[1] == endpoint:
        return pair[0]
    raise EqualLengthRayRoleError(
        "path_endpoint_unresolved",
        "the required point is not an endpoint of the structured segment",
    )


__all__ = [
    "EqualLengthRayPathRoles",
    "EqualLengthRayRoleError",
    "resolve_equal_length_ray_path_roles",
]
