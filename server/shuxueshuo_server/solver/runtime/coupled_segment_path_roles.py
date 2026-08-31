"""Structured roles for coupled-segment endpoint-replacement minima.

The mechanism is independent of problem ids and display labels.  One selected
path target and one selected segment relation must determine the complete
two-moving-point reduction graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.path_reduction_roles import (
    PathReductionRoleError,
    PathReductionRoleResolver,
)


@dataclass(frozen=True)
class CoupledSegmentPathRoles:
    path_minimum_target: str
    segment_binding_relation: str
    first_membership: str
    second_membership: str
    first_moving_point: str
    moving_point: str
    first_segment_start: str
    joint_point: str
    second_segment_end: str
    transformed_fixed_endpoint: str

    @property
    def candidate_id(self) -> str:
        return stable_hash(self.to_payload())[:20]

    def to_payload(self) -> dict[str, str]:
        return {
            "path_minimum_target": self.path_minimum_target,
            "segment_binding_relation": self.segment_binding_relation,
            "first_membership": self.first_membership,
            "second_membership": self.second_membership,
            "first_moving_point": self.first_moving_point,
            "moving_point": self.moving_point,
            "first_segment_start": self.first_segment_start,
            "joint_point": self.joint_point,
            "second_segment_end": self.second_segment_end,
            "transformed_fixed_endpoint": self.transformed_fixed_endpoint,
        }


class CoupledSegmentPathRoleError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def build_coupled_segment_path_role_candidates(
    *,
    path_minimum_target: str,
    segment_binding_relation: str,
    scope_id: str,
    registry: CanonicalHandleRegistry,
) -> tuple[CoupledSegmentPathRoles, ...]:
    """Return the unique endpoint-replacement graph selected by public Facts."""

    try:
        roles = PathReductionRoleResolver.resolve(
            path_target=path_minimum_target,
            scope_id=scope_id,
            registry=registry,
        )
    except PathReductionRoleError as exc:
        raise CoupledSegmentPathRoleError(
            exc.code,
            str(exc),
            details=exc.details,
        ) from exc
    if roles.binding_relation != segment_binding_relation:
        return ()
    candidate = CoupledSegmentPathRoles(
        path_minimum_target=roles.path_target,
        segment_binding_relation=roles.binding_relation,
        first_membership=roles.first_membership,
        second_membership=roles.second_membership,
        first_moving_point=roles.first_moving_point,
        moving_point=roles.second_moving_point,
        first_segment_start=roles.first_segment_start,
        joint_point=roles.joint_point,
        second_segment_end=roles.second_segment_end,
        transformed_fixed_endpoint=roles.transformed_fixed_endpoint,
    )
    return (candidate,)


__all__ = [
    "CoupledSegmentPathRoleError",
    "CoupledSegmentPathRoles",
    "build_coupled_segment_path_role_candidates",
]
