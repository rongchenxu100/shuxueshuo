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
from .quadratic_from_constraints import QuadraticFromConstraintsMethod, SPEC as QUADRATIC_FROM_CONSTRAINTS_SPEC
from .quadratic_vertex_point import QuadraticVertexPointMethod, SPEC as QUADRATIC_VERTEX_POINT_SPEC
from .quadratic_y_axis_intercept_point import QuadraticYAxisInterceptPointMethod, SPEC as QUADRATIC_Y_AXIS_INTERCEPT_POINT_SPEC
from .point_on_parabola_at_x import PointOnParabolaAtXMethod, SPEC as POINT_ON_PARABOLA_AT_X_SPEC
from .midpoint_point import MidpointPointMethod, SPEC as MIDPOINT_POINT_SPEC
from .parameter_from_segment_length import ParameterFromSegmentLengthMethod, SPEC as PARAMETER_FROM_SEGMENT_LENGTH_SPEC
from .parabola_at_parameter import ParabolaAtParameterMethod, SPEC as PARABOLA_AT_PARAMETER_SPEC
from .two_moving_points_path_reduction import TwoMovingPointsPathReductionMethod, SPEC as TWO_MOVING_POINTS_PATH_REDUCTION_SPEC
from .broken_path_straightening_candidates import BrokenPathStraighteningCandidatesMethod, SPEC as BROKEN_PATH_STRAIGHTENING_CANDIDATES_SPEC
from .select_straightening_candidate import SelectStraighteningCandidateMethod, SPEC as SELECT_STRAIGHTENING_CANDIDATE_SPEC
from .square_opposite_point import SquareOppositePointMethod, SPEC as SQUARE_OPPOSITE_POINT_SPEC
from .distance_between_points import DistanceBetweenPointsMethod, SPEC as DISTANCE_BETWEEN_POINTS_SPEC
from .parameter_from_minimum_value import ParameterFromMinimumValueMethod, SPEC as PARAMETER_FROM_MINIMUM_VALUE_SPEC
from .line_intersection_point import LineIntersectionPointMethod, SPEC as LINE_INTERSECTION_POINT_SPEC
from .select_curve_point_candidate_and_solve_coefficients import SelectCurvePointCandidateAndSolveCoefficientsMethod, SPEC as SELECT_CURVE_POINT_CANDIDATE_AND_SOLVE_COEFFICIENTS_SPEC
from .filter_point_candidates_by_quadratic_curve import FilterPointCandidatesByQuadraticCurveMethod, SPEC as FILTER_POINT_CANDIDATES_BY_QUADRATIC_CURVE_SPEC
from .weighted_axis_path_triangle_transform import WeightedAxisPathTriangleTransformMethod, SPEC as WEIGHTED_AXIS_PATH_TRIANGLE_TRANSFORM_SPEC
from .linked_broken_path_geometric_minimum import LinkedBrokenPathGeometricMinimumMethod, SPEC as LINKED_BROKEN_PATH_GEOMETRIC_MINIMUM_SPEC
from .coefficient_at_parameter import CoefficientAtParameterMethod, SPEC as COEFFICIENT_AT_PARAMETER_SPEC

ALL_METHOD_SPEC_SOURCES = (
    RIGHT_ANGLE_EQUAL_LENGTH_CANDIDATES_SPEC,
    SELECT_POINT_BY_QUADRANT_CONSTRAINT_SPEC,
    QUADRATIC_AXIS_FROM_RELATION_SPEC,
    QUADRATIC_FROM_CONSTRAINTS_SPEC,
    QUADRATIC_VERTEX_POINT_SPEC,
    QUADRATIC_Y_AXIS_INTERCEPT_POINT_SPEC,
    POINT_ON_PARABOLA_AT_X_SPEC,
    MIDPOINT_POINT_SPEC,
    PARAMETER_FROM_SEGMENT_LENGTH_SPEC,
    PARABOLA_AT_PARAMETER_SPEC,
    TWO_MOVING_POINTS_PATH_REDUCTION_SPEC,
    BROKEN_PATH_STRAIGHTENING_CANDIDATES_SPEC,
    SELECT_STRAIGHTENING_CANDIDATE_SPEC,
    SQUARE_OPPOSITE_POINT_SPEC,
    DISTANCE_BETWEEN_POINTS_SPEC,
    PARAMETER_FROM_MINIMUM_VALUE_SPEC,
    LINE_INTERSECTION_POINT_SPEC,
    SELECT_CURVE_POINT_CANDIDATE_AND_SOLVE_COEFFICIENTS_SPEC,
    FILTER_POINT_CANDIDATES_BY_QUADRATIC_CURVE_SPEC,
    WEIGHTED_AXIS_PATH_TRIANGLE_TRANSFORM_SPEC,
    LINKED_BROKEN_PATH_GEOMETRIC_MINIMUM_SPEC,
    COEFFICIENT_AT_PARAMETER_SPEC,
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
        QuadraticFromConstraintsMethod(),
        QuadraticVertexPointMethod(),
        QuadraticYAxisInterceptPointMethod(),
        PointOnParabolaAtXMethod(),
        MidpointPointMethod(),
        ParameterFromSegmentLengthMethod(),
        ParabolaAtParameterMethod(),
        TwoMovingPointsPathReductionMethod(),
        BrokenPathStraighteningCandidatesMethod(),
        SelectStraighteningCandidateMethod(),
        SquareOppositePointMethod(),
        DistanceBetweenPointsMethod(),
        ParameterFromMinimumValueMethod(),
        LineIntersectionPointMethod(),
        SelectCurvePointCandidateAndSolveCoefficientsMethod(),
        FilterPointCandidatesByQuadraticCurveMethod(),
        WeightedAxisPathTriangleTransformMethod(),
        LinkedBrokenPathGeometricMinimumMethod(),
        CoefficientAtParameterMethod(),
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
    "QuadraticFromConstraintsMethod",
    "QuadraticVertexPointMethod",
    "QuadraticYAxisInterceptPointMethod",
    "PointOnParabolaAtXMethod",
    "MidpointPointMethod",
    "ParameterFromSegmentLengthMethod",
    "ParabolaAtParameterMethod",
    "TwoMovingPointsPathReductionMethod",
    "BrokenPathStraighteningCandidatesMethod",
    "SelectStraighteningCandidateMethod",
    "SquareOppositePointMethod",
    "DistanceBetweenPointsMethod",
    "ParameterFromMinimumValueMethod",
    "LineIntersectionPointMethod",
    "SelectCurvePointCandidateAndSolveCoefficientsMethod",
    "FilterPointCandidatesByQuadraticCurveMethod",
    "WeightedAxisPathTriangleTransformMethod",
    "LinkedBrokenPathGeometricMinimumMethod",
    "CoefficientAtParameterMethod",
]
