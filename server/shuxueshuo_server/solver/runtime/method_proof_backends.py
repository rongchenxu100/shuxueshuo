"""Explicit proof-backend routing, independent of the selected condition protocol.

Native Methods retain their own mathematical validation; this is not a fallback
from bounded-real proof search. New Methods must register their backend here.
"""

SCOPED_PROOF_METHODS = frozenset(
    {
        "apply_two_term_amgm",
        "bound_univariate_quadratic",
        "close_equality_and_restore",
        "eliminate_by_constraint",
        "organize_expressions",
        "substitute_expressions",
    }
)

NATIVE_VALIDATION_METHODS = frozenset(
    {
        "angle_sum_equal_angle_candidates",
        "axis_intercept_from_equal_acute_angles",
        "coupled_segment_endpoint_replacement_path_minimum_kernel",
        "distance_between_points",
        "equal_length_ray_point",
        "evaluate_expression_at_parameter",
        "evaluate_point_at_parameter",
        "filter_point_candidates_by_quadratic_curve",
        "line_intersection_point",
        "line_parabola_second_intersection_point",
        "midpoint_point",
        "parameter_from_curve_point_on_quadratic",
        "parameter_from_expression_value",
        "parameter_from_minimum_value",
        "parameter_from_segment_length",
        "point_candidates_from_curve_point_condition",
        "point_on_parabola_at_x",
        "quadratic_axis_from_relation",
        "quadratic_axis_parameterized_point",
        "quadratic_axis_x_intercept_point",
        "quadratic_from_constraints",
        "quadratic_square_path_minimum_kernel",
        "quadratic_vertex_point",
        "quadratic_x_axis_intercept_point",
        "quadratic_y_axis_intercept_point",
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
        "square_adjacent_vertex_from_side",
        "square_opposite_point",
        "translated_point",
        "weighted_axis_path_minimum_kernel",
    }
)


def requires_scoped_proof(method_id):
    if method_id in SCOPED_PROOF_METHODS:
        return True
    if method_id in NATIVE_VALIDATION_METHODS:
        return False
    raise ValueError(f"proof_facts: unregistered Method proof backend: {method_id}")
