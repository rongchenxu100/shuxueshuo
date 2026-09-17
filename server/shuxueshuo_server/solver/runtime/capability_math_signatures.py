"""Mathematical documentation for the registered public capabilities.

Names, parameters, optionality and returns still come from the executable
catalog. These guards describe its mathematics, not a new executable DSL.
Internal binding instructions belong to the existing production prompt only.
"""

MATH_PRECONDITIONS = {
    "quadratic_axis_from_relation": ["Γ: y=a*x^2+b*x+c", "a != 0"],
    "quadratic_from_constraints": [
        "Γ: y=a*x^2+b*x+c",
        "a != 0",
        "known_coefficients ∪ coefficient_relation ∪ extra_equation ∪ {P ∈ Γ: P ∈ curve_points ∪ {curve_point}}",
        "free_parameters = independent_basis(a,b,c | constraints)",
        "target_parameter ∉ free_parameters",
    ],
    "quadratic_vertex_point": ["degree(parabola)=2"],
    "quadratic_x_axis_intercept_point": [
        "degree(parabola)=2",
        "y(point)=0",
        "known_point ∈ parabola ⇒ point != known_point",
    ],
    "quadratic_y_axis_intercept_point": ["degree(quadratic)=2", "x(point)=0"],
    "point_on_parabola_at_x": ["degree(parabola)=2", "x(point)=given_x"],
    "line_parabola_second_intersection_point": [
        "line_p1 != line_p2",
        "known_point ∈ line(line_p1,line_p2) ∩ parabola",
        "point != known_point",
    ],
    "parameter_from_expression_value": [
        "expression(parameter)=minimum_value",
        "parameter ∈ given_domain",
    ],
    "parameter_from_segment_length": [
        "|p1-p2|^2=length_squared",
        "parameter ∈ given_domain",
    ],
    "parameter_from_minimum_value": [
        "minimum_expression(parameter)=minimum_value",
        "parameter ∈ given_domain",
    ],
    "evaluate_expression_at_parameter": ["parameter=parameter_value"],
    "evaluate_point_at_parameter": ["parameter=parameter_value"],
    "distance_between_points": ["p1,p2 ∈ ℝ^2"],
    "line_intersection_point": [
        "line1_p1 != line1_p2",
        "line2_p1 != line2_p2",
        "det(line1_p2-line1_p1,line2_p2-line2_p1) != 0",
    ],
    "translated_point": ["point=source+given_vector"],
    "midpoint_point": ["M=midpoint(A,B)"],
    "right_angle_equal_length_construct_and_select": [
        "angle(A,O,B)=90°",
        "OA=OB",
        "B ∈ given_region",
    ],
    "coupled_segment_endpoint_replacement_path_minimum": [
        "E ∈ segment(D,M)",
        "G ∈ segment(M,N)",
        "DE=k*NG",
        "k>0",
    ],
    "quadratic_axis_parameterized_point": [
        "degree(parabola)=2",
        "point ∈ axis(parabola)",
    ],
    "square_adjacent_vertex_from_side": [
        "side_start != side_end",
        "square(side_start,side_end,C,D)",
        "D ∈ given_half_plane",
    ],
    "point_candidates_from_curve_point_condition": [
        "curve_point ∈ parabola",
        "parameter ∈ given_domain",
    ],
    "quadratic_square_path_minimum": [
        "degree(parabola)=2",
        "square(A,E,K,G)",
        "E ∈ axis(parabola)",
        "min(path_minimum_target) attained",
    ],
    "equal_length_ray_point": ["N ∈ ray(C,D)", "MN=given_length"],
    "angle_sum_equal_angle_candidates": ["angle(A,B,C)+angle(D,E,F)=given_angle"],
    "axis_intercept_from_equal_acute_angles": ["angle_1=angle_2", "0°<angle_1<90°"],
    "equal_length_ray_path_reduction": [
        "M ∈ segment(A,B)",
        "N ∈ ray(C,D)",
        "MN=given_length",
    ],
    "right_angle_equal_length_candidates": ["angle(A,O,B)=90°", "OA=OB"],
    "weighted_axis_path_minimum": [
        "path_minimum_target=min(k*MN+AN)",
        "k>1",
        "N=(n,0)",
        "n ∈ given_domain",
        "min(k*MN+AN) attained",
    ],
    "curve_candidate_parameter_solve": [
        "target_point ∈ candidates",
        "target_point ∈ parabola",
        "parameter ∈ given_domain",
    ],
}
