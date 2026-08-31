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
from .quadratic_x_axis_intercept_point import QuadraticXAxisInterceptPointMethod, SPEC as QUADRATIC_X_AXIS_INTERCEPT_POINT_SPEC
from .quadratic_axis_x_intercept_point import QuadraticAxisXInterceptPointMethod, SPEC as QUADRATIC_AXIS_X_INTERCEPT_POINT_SPEC
from .point_on_parabola_at_x import PointOnParabolaAtXMethod, SPEC as POINT_ON_PARABOLA_AT_X_SPEC
from .midpoint_point import MidpointPointMethod, SPEC as MIDPOINT_POINT_SPEC
from .parameter_from_segment_length import ParameterFromSegmentLengthMethod, SPEC as PARAMETER_FROM_SEGMENT_LENGTH_SPEC
from .square_opposite_point import SquareOppositePointMethod, SPEC as SQUARE_OPPOSITE_POINT_SPEC
from .distance_between_points import DistanceBetweenPointsMethod, SPEC as DISTANCE_BETWEEN_POINTS_SPEC
from .parameter_from_minimum_value import ParameterFromMinimumValueMethod, SPEC as PARAMETER_FROM_MINIMUM_VALUE_SPEC
from .parameter_from_expression_value import ParameterFromExpressionValueMethod, SPEC as PARAMETER_FROM_EXPRESSION_VALUE_SPEC
from .line_intersection_point import LineIntersectionPointMethod, SPEC as LINE_INTERSECTION_POINT_SPEC
from .filter_point_candidates_by_quadratic_curve import FilterPointCandidatesByQuadraticCurveMethod, SPEC as FILTER_POINT_CANDIDATES_BY_QUADRATIC_CURVE_SPEC
from .evaluate_expression_at_parameter import EvaluateExpressionAtParameterMethod, SPEC as EVALUATE_EXPRESSION_AT_PARAMETER_SPEC
from .evaluate_point_at_parameter import EvaluatePointAtParameterMethod, SPEC as EVALUATE_POINT_AT_PARAMETER_SPEC
from .parameter_from_curve_point_on_quadratic import ParameterFromCurvePointOnQuadraticMethod, SPEC as PARAMETER_FROM_CURVE_POINT_ON_QUADRATIC_SPEC
from .translated_point import TranslatedPointMethod, SPEC as TRANSLATED_POINT_SPEC
from .angle_sum_equal_angle_candidates import AngleSumEqualAngleCandidatesMethod, SPEC as ANGLE_SUM_EQUAL_ANGLE_CANDIDATES_SPEC
from .axis_intercept_from_equal_acute_angles import AxisInterceptFromEqualAcuteAnglesMethod, SPEC as AXIS_INTERCEPT_FROM_EQUAL_ACUTE_ANGLES_SPEC
from .line_parabola_second_intersection_point import LineParabolaSecondIntersectionPointMethod, SPEC as LINE_PARABOLA_SECOND_INTERSECTION_POINT_SPEC
from .equal_length_ray_point import EqualLengthRayPointMethod, SPEC as EQUAL_LENGTH_RAY_POINT_SPEC
from .quadratic_axis_parameterized_point import QuadraticAxisParameterizedPointMethod, SPEC as QUADRATIC_AXIS_PARAMETERIZED_POINT_SPEC
from .square_adjacent_vertex_from_side import SquareAdjacentVertexFromSideMethod, SPEC as SQUARE_ADJACENT_VERTEX_FROM_SIDE_SPEC
from .point_candidates_from_curve_point_condition import PointCandidatesFromCurvePointConditionMethod, SPEC as POINT_CANDIDATES_FROM_CURVE_POINT_CONDITION_SPEC
from .quadratic_square_path_minimum import QuadraticSquarePathMinimumMethod, SPEC as QUADRATIC_SQUARE_PATH_MINIMUM_SPEC
from .coupled_segment_path_minimum import CoupledSegmentPathMinimumMethod, SPEC as COUPLED_SEGMENT_PATH_MINIMUM_SPEC
from .weighted_axis_path_minimum import WeightedAxisPathMinimumMethod, SPEC as WEIGHTED_AXIS_PATH_MINIMUM_SPEC

ALL_METHOD_SPEC_SOURCES = (
    RIGHT_ANGLE_EQUAL_LENGTH_CANDIDATES_SPEC,
    SELECT_POINT_BY_QUADRANT_CONSTRAINT_SPEC,
    QUADRATIC_AXIS_FROM_RELATION_SPEC,
    QUADRATIC_FROM_CONSTRAINTS_SPEC,
    QUADRATIC_VERTEX_POINT_SPEC,
    QUADRATIC_Y_AXIS_INTERCEPT_POINT_SPEC,
    QUADRATIC_X_AXIS_INTERCEPT_POINT_SPEC,
    QUADRATIC_AXIS_X_INTERCEPT_POINT_SPEC,
    POINT_ON_PARABOLA_AT_X_SPEC,
    MIDPOINT_POINT_SPEC,
    PARAMETER_FROM_SEGMENT_LENGTH_SPEC,
    SQUARE_OPPOSITE_POINT_SPEC,
    DISTANCE_BETWEEN_POINTS_SPEC,
    PARAMETER_FROM_MINIMUM_VALUE_SPEC,
    PARAMETER_FROM_EXPRESSION_VALUE_SPEC,
    LINE_INTERSECTION_POINT_SPEC,
    FILTER_POINT_CANDIDATES_BY_QUADRATIC_CURVE_SPEC,
    EVALUATE_EXPRESSION_AT_PARAMETER_SPEC,
    EVALUATE_POINT_AT_PARAMETER_SPEC,
    PARAMETER_FROM_CURVE_POINT_ON_QUADRATIC_SPEC,
    TRANSLATED_POINT_SPEC,
    ANGLE_SUM_EQUAL_ANGLE_CANDIDATES_SPEC,
    AXIS_INTERCEPT_FROM_EQUAL_ACUTE_ANGLES_SPEC,
    LINE_PARABOLA_SECOND_INTERSECTION_POINT_SPEC,
    EQUAL_LENGTH_RAY_POINT_SPEC,
    QUADRATIC_AXIS_PARAMETERIZED_POINT_SPEC,
    SQUARE_ADJACENT_VERTEX_FROM_SIDE_SPEC,
    POINT_CANDIDATES_FROM_CURVE_POINT_CONDITION_SPEC,
    QUADRATIC_SQUARE_PATH_MINIMUM_SPEC,
    COUPLED_SEGMENT_PATH_MINIMUM_SPEC,
    WEIGHTED_AXIS_PATH_MINIMUM_SPEC,
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
        QuadraticXAxisInterceptPointMethod(),
        QuadraticAxisXInterceptPointMethod(),
        PointOnParabolaAtXMethod(),
        MidpointPointMethod(),
        ParameterFromSegmentLengthMethod(),
        SquareOppositePointMethod(),
        DistanceBetweenPointsMethod(),
        ParameterFromMinimumValueMethod(),
        ParameterFromExpressionValueMethod(),
        LineIntersectionPointMethod(),
        FilterPointCandidatesByQuadraticCurveMethod(),
        EvaluateExpressionAtParameterMethod(),
        EvaluatePointAtParameterMethod(),
        ParameterFromCurvePointOnQuadraticMethod(),
        TranslatedPointMethod(),
        AngleSumEqualAngleCandidatesMethod(),
        AxisInterceptFromEqualAcuteAnglesMethod(),
        LineParabolaSecondIntersectionPointMethod(),
        EqualLengthRayPointMethod(),
        QuadraticAxisParameterizedPointMethod(),
        SquareAdjacentVertexFromSideMethod(),
        PointCandidatesFromCurvePointConditionMethod(),
        QuadraticSquarePathMinimumMethod(),
        CoupledSegmentPathMinimumMethod(),
        WeightedAxisPathMinimumMethod(),
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
    "QuadraticXAxisInterceptPointMethod",
    "QuadraticAxisXInterceptPointMethod",
    "PointOnParabolaAtXMethod",
    "MidpointPointMethod",
    "ParameterFromSegmentLengthMethod",
    "SquareOppositePointMethod",
    "DistanceBetweenPointsMethod",
    "ParameterFromExpressionValueMethod",
    "ParameterFromMinimumValueMethod",
    "LineIntersectionPointMethod",
    "FilterPointCandidatesByQuadraticCurveMethod",
    "EvaluateExpressionAtParameterMethod",
    "EvaluatePointAtParameterMethod",
    "ParameterFromCurvePointOnQuadraticMethod",
    "TranslatedPointMethod",
    "AngleSumEqualAngleCandidatesMethod",
    "AxisInterceptFromEqualAcuteAnglesMethod",
    "LineParabolaSecondIntersectionPointMethod",
    "EqualLengthRayPointMethod",
    "QuadraticAxisParameterizedPointMethod",
    "SquareAdjacentVertexFromSideMethod",
    "PointCandidatesFromCurvePointConditionMethod",
    "QuadraticSquarePathMinimumMethod",
    "CoupledSegmentPathMinimumMethod",
    "WeightedAxisPathMinimumMethod",
]
