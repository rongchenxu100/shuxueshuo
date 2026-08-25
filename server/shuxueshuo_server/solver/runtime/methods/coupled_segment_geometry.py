"""Pure symbolic proof helpers for coupled segment endpoint replacement."""

from __future__ import annotations

import sympy as sp

from shuxueshuo_server.solver.contracts import Point

from ._common import SympyKernel


class CoupledSegmentGeometryError(Exception):
    """The structured coupled-segment geometry is mathematically invalid."""


def coupled_segment_endpoint_residuals(
    kernel: SympyKernel,
    *,
    first_track_fixed_endpoint: Point,
    joint_point: Point,
    second_track_fixed_endpoint: Point,
    first_relation_scale: sp.Expr,
    second_relation_scale: sp.Expr,
) -> tuple[sp.Expr, sp.Expr]:
    """Return the binding and endpoint-replacement squared-distance residuals."""

    first_track_length = sp.simplify(
        kernel.distance(first_track_fixed_endpoint, joint_point)
    )
    second_track_length = sp.simplify(
        kernel.distance(second_track_fixed_endpoint, joint_point)
    )
    if first_track_length == 0 or second_track_length == 0:
        raise CoupledSegmentGeometryError(
            "coupled segment tracks must be nondegenerate"
        )
    if sp.simplify(first_relation_scale) == 0:
        raise CoupledSegmentGeometryError(
            "the first relation scale must be nonzero"
        )

    parameter = sp.Symbol("coupled_segment_parameter", real=True)
    first_ratio = sp.simplify(
        (second_relation_scale / first_relation_scale)
        * second_track_length
        / first_track_length
    )
    first_moving_point = (
        sp.simplify(
            first_track_fixed_endpoint[0]
            + first_ratio
            * parameter
            * (joint_point[0] - first_track_fixed_endpoint[0])
        ),
        sp.simplify(
            first_track_fixed_endpoint[1]
            + first_ratio
            * parameter
            * (joint_point[1] - first_track_fixed_endpoint[1])
        ),
    )
    second_moving_point = (
        sp.simplify(
            second_track_fixed_endpoint[0]
            + parameter
            * (joint_point[0] - second_track_fixed_endpoint[0])
        ),
        sp.simplify(
            second_track_fixed_endpoint[1]
            + parameter
            * (joint_point[1] - second_track_fixed_endpoint[1])
        ),
    )
    first_bound_distance_squared = kernel.distance_squared(
        first_track_fixed_endpoint,
        first_moving_point,
    )
    second_bound_distance_squared = kernel.distance_squared(
        second_track_fixed_endpoint,
        second_moving_point,
    )
    moving_distance_squared = kernel.distance_squared(
        first_moving_point,
        second_moving_point,
    )
    replacement_distance_squared = kernel.distance_squared(
        first_track_fixed_endpoint,
        second_moving_point,
    )
    return (
        sp.simplify(
            first_relation_scale**2 * first_bound_distance_squared
            - second_relation_scale**2 * second_bound_distance_squared
        ),
        sp.simplify(
            moving_distance_squared - replacement_distance_squared
        ),
    )


__all__ = [
    "CoupledSegmentGeometryError",
    "coupled_segment_endpoint_residuals",
]
