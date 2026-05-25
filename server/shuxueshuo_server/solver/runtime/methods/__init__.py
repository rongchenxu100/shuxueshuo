"""V1.5 无状态 methods 包。

公共导入路径保持为 ``shuxueshuo_server.solver.runtime.methods``。
每个具体 method 位于独立文件，并在同文件内声明 ``SPEC``，使代码成为
MethodSpec JSON 的唯一事实源。
"""

from __future__ import annotations

from ._common import StatelessMethod, StatelessMethodRegistry
from .right_angle_equal_length_candidates import RightAngleEqualLengthCandidatesMethod, SPEC as RIGHT_ANGLE_EQUAL_LENGTH_CANDIDATES_SPEC
from .select_point_by_quadrant_constraint import SelectPointByQuadrantConstraintMethod, SPEC as SELECT_POINT_BY_QUADRANT_CONSTRAINT_SPEC
from .quadratic_axis_from_relation import QuadraticAxisFromRelationMethod, SPEC as QUADRATIC_AXIS_FROM_RELATION_SPEC
from .quadratic_from_known_coefficients import QuadraticFromKnownCoefficientsMethod, SPEC as QUADRATIC_FROM_KNOWN_COEFFICIENTS_SPEC
from .midpoint_point import MidpointPointMethod, SPEC as MIDPOINT_POINT_SPEC
from .quadratic_coefficients_from_curve_points import QuadraticCoefficientsFromCurvePointsMethod, SPEC as QUADRATIC_COEFFICIENTS_FROM_CURVE_POINTS_SPEC
from .parameter_from_segment_length import ParameterFromSegmentLengthMethod, SPEC as PARAMETER_FROM_SEGMENT_LENGTH_SPEC
from .parabola_at_parameter import ParabolaAtParameterMethod, SPEC as PARABOLA_AT_PARAMETER_SPEC
from .two_moving_points_path_reduction import TwoMovingPointsPathReductionMethod, SPEC as TWO_MOVING_POINTS_PATH_REDUCTION_SPEC
from .broken_path_straightening_candidates import BrokenPathStraighteningCandidatesMethod, SPEC as BROKEN_PATH_STRAIGHTENING_CANDIDATES_SPEC
from .select_straightening_candidate import SelectStraighteningCandidateMethod, SPEC as SELECT_STRAIGHTENING_CANDIDATE_SPEC
from .square_opposite_point import SquareOppositePointMethod, SPEC as SQUARE_OPPOSITE_POINT_SPEC
from .distance_between_points import DistanceBetweenPointsMethod, SPEC as DISTANCE_BETWEEN_POINTS_SPEC
from .parameter_from_minimum_value import ParameterFromMinimumValueMethod, SPEC as PARAMETER_FROM_MINIMUM_VALUE_SPEC
from .line_intersection_point import LineIntersectionPointMethod, SPEC as LINE_INTERSECTION_POINT_SPEC

ALL_METHOD_SPEC_SOURCES = (
    RIGHT_ANGLE_EQUAL_LENGTH_CANDIDATES_SPEC,
    SELECT_POINT_BY_QUADRANT_CONSTRAINT_SPEC,
    QUADRATIC_AXIS_FROM_RELATION_SPEC,
    QUADRATIC_FROM_KNOWN_COEFFICIENTS_SPEC,
    MIDPOINT_POINT_SPEC,
    QUADRATIC_COEFFICIENTS_FROM_CURVE_POINTS_SPEC,
    PARAMETER_FROM_SEGMENT_LENGTH_SPEC,
    PARABOLA_AT_PARAMETER_SPEC,
    TWO_MOVING_POINTS_PATH_REDUCTION_SPEC,
    BROKEN_PATH_STRAIGHTENING_CANDIDATES_SPEC,
    SELECT_STRAIGHTENING_CANDIDATE_SPEC,
    SQUARE_OPPOSITE_POINT_SPEC,
    DISTANCE_BETWEEN_POINTS_SPEC,
    PARAMETER_FROM_MINIMUM_VALUE_SPEC,
    LINE_INTERSECTION_POINT_SPEC,
)


def method_spec_payloads() -> list[dict]:
    """返回由 method 代码生成的 MethodSpec JSON payload。"""
    return [spec.to_payload() for spec in ALL_METHOD_SPEC_SOURCES]


def default_stateless_registry() -> StatelessMethodRegistry:
    """构建 V1.5 默认 method 注册表。"""
    methods: list[StatelessMethod] = [
        RightAngleEqualLengthCandidatesMethod(),
        SelectPointByQuadrantConstraintMethod(),
        QuadraticAxisFromRelationMethod(),
        QuadraticFromKnownCoefficientsMethod(),
        MidpointPointMethod(),
        QuadraticCoefficientsFromCurvePointsMethod(),
        ParameterFromSegmentLengthMethod(),
        ParabolaAtParameterMethod(),
        TwoMovingPointsPathReductionMethod(),
        BrokenPathStraighteningCandidatesMethod(),
        SelectStraighteningCandidateMethod(),
        SquareOppositePointMethod(),
        DistanceBetweenPointsMethod(),
        ParameterFromMinimumValueMethod(),
        LineIntersectionPointMethod(),
    ]
    return StatelessMethodRegistry({method.method_id: method for method in methods})


__all__ = [
    "ALL_METHOD_SPEC_SOURCES",
    "StatelessMethod",
    "StatelessMethodRegistry",
    "default_stateless_registry",
    "method_spec_payloads",
    "RightAngleEqualLengthCandidatesMethod",
    "SelectPointByQuadrantConstraintMethod",
    "QuadraticAxisFromRelationMethod",
    "QuadraticFromKnownCoefficientsMethod",
    "MidpointPointMethod",
    "QuadraticCoefficientsFromCurvePointsMethod",
    "ParameterFromSegmentLengthMethod",
    "ParabolaAtParameterMethod",
    "TwoMovingPointsPathReductionMethod",
    "BrokenPathStraighteningCandidatesMethod",
    "SelectStraighteningCandidateMethod",
    "SquareOppositePointMethod",
    "DistanceBetweenPointsMethod",
    "ParameterFromMinimumValueMethod",
    "LineIntersectionPointMethod",
]
