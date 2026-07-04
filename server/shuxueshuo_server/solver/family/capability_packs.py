"""Capability Pack registry for solver families.

Phase 1a packs organize method/recipe catalog exposure only. Method binding
rules intentionally remain on SolverFamilySpec until Phase 1b.
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    CapabilityPackRegistry,
    CapabilityPackSpec,
    RecipeExecutionSpec,
    StepRecipeSpec,
)


RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT = StepRecipeSpec(
    recipe_id="right_angle_equal_length_construct_and_select",
    goal_type="derive_constructed_point",
    title="直角等腰构造并筛选点",
    description=(
        "由直角等腰/旋转关系先列出候选点，再结合象限、参数范围或曲线条件"
        "筛选出符合题设的点。"
    ),
    method_ids=(
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
    ),
    execution=RecipeExecutionSpec(
        recipe_id="right_angle_equal_length_construct_and_select",
        method_sequence=(
            "right_angle_equal_length_candidates",
            "select_point_by_quadrant_constraint",
        ),
        execution_strategy="right_angle_construct_select",
        intermediate_wiring=(
            (
                "right_angle_equal_length_candidates.candidates",
                "select_point_by_quadrant_constraint.candidates",
            ),
        ),
        output_aliases=(
            ("select_point_by_quadrant_constraint.selected_point", "Point"),
        ),
    ),
)

TWO_MOVING_POINTS_PATH_REDUCTION = StepRecipeSpec(
    recipe_id="two_moving_points_path_reduction",
    goal_type="reduce_path_expression",
    title="两动点路径降维：已有固定点替换",
    description=(
        "利用线段比例、共线或绑定关系，把原路径中的两动点线段替换为"
        "题面已有固定点到动点的等长线段，从而转化为单动点折线路径；"
        "本 recipe 不创建辅助点或辅助轨迹。"
    ),
    method_ids=("two_moving_points_path_reduction",),
    execution=RecipeExecutionSpec(
        recipe_id="two_moving_points_path_reduction",
        method_sequence=("two_moving_points_path_reduction",),
        execution_strategy="single_method",
        output_aliases=(
            ("two_moving_points_path_reduction.path_transformation", "PathTransformation"),
        ),
    ),
    priority="preferred",
)

BROKEN_PATH_STRAIGHTENING_AND_SELECT = StepRecipeSpec(
    recipe_id="broken_path_straightening_and_select",
    goal_type="straighten_broken_path",
    title="折线拉直并选择方案",
    description=(
        "为单动点折线路径构造拉直候选方案，再选择最方便计算且符合题设"
        "结构的方案；本 recipe 只产出拉直方案，不直接产出最小值表达式。"
    ),
    method_ids=(
        "broken_path_straightening_candidates",
        "select_straightening_candidate",
    ),
    execution=RecipeExecutionSpec(
        recipe_id="broken_path_straightening_and_select",
        method_sequence=(
            "broken_path_straightening_candidates",
            "select_straightening_candidate",
        ),
        execution_strategy="straightening_candidates_select",
        creates=("point",),
        intermediate_wiring=(
            (
                "broken_path_straightening_candidates.candidates",
                "select_straightening_candidate.candidates",
            ),
        ),
        output_aliases=(
            ("select_straightening_candidate.selected_candidate", "StraighteningCandidate"),
            ("select_straightening_candidate.auxiliary_point", "Point"),
        ),
    ),
    priority="preferred",
)

PATH_MINIMUM_BY_STRAIGHTENED_DISTANCE = StepRecipeSpec(
    recipe_id="path_minimum_by_straightened_distance",
    goal_type="derive_minimum_value",
    title="拉直后距离求最小值",
    description=(
        "在折线已经拉直或等价路径已经确定后，单独用端点间距离或垂线距离"
        "求路径最小值表达式；不要并入折线拉直步骤。"
    ),
    method_ids=("distance_between_points",),
    execution=RecipeExecutionSpec(
        recipe_id="path_minimum_by_straightened_distance",
        method_sequence=("distance_between_points",),
        execution_strategy="straightened_distance_minimum",
        output_aliases=(
            ("distance_between_points.distance", "MinimumExpression"),
            ("distance_between_points.evaluated_distance", "MinimumExpression"),
        ),
    ),
    priority="preferred",
)

BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION = StepRecipeSpec(
    recipe_id="broken_path_straightening_minimum_expression",
    goal_type="derive_path_minimum_expression",
    title="折线拉直并求最小值表达式",
    description=(
        "对单动点两段折线路径，生成将军饮马拉直候选，选择最适合计算的方案，"
        "再计算对应两端点距离得到最小值表达式。"
    ),
    method_ids=(
        "broken_path_straightening_candidates",
        "select_straightening_candidate",
        "distance_between_points",
    ),
    execution=RecipeExecutionSpec(
        recipe_id="broken_path_straightening_minimum_expression",
        method_sequence=(
            "broken_path_straightening_candidates",
            "select_straightening_candidate",
            "distance_between_points",
        ),
        execution_strategy="broken_path_straightening_minimum_expression",
        output_aliases=(
            ("select_straightening_candidate.minimum_point_1", "Point"),
            ("select_straightening_candidate.minimum_point_2", "Point"),
            ("distance_between_points.distance", "MinimumExpression"),
            ("distance_between_points.evaluated_distance", "MinimumExpression"),
        ),
    ),
    priority="preferred",
)

EQUAL_LENGTH_RAY_PATH_REDUCTION = StepRecipeSpec(
    recipe_id="equal_length_ray_path_reduction",
    goal_type="derive_path_minimum_expression",
    title="等长射线路径降维为单距离最值",
    description=(
        "当一个动点在线段上、另一个动点在射线上，且二者满足同端点等长关系时，"
        "把原来的两动点线段距离和转化为一个固定点到内部构造辅助点的单距离"
        "最小值表达式。辅助点由系统在 recipe 内部创建，LLM 不需要在 creates 中"
        "声明辅助点，也不要拆成单独的 equal_length_ray_point step。"
    ),
    method_ids=("equal_length_ray_point", "distance_between_points"),
    execution=RecipeExecutionSpec(
        recipe_id="equal_length_ray_path_reduction",
        method_sequence=("equal_length_ray_point", "distance_between_points"),
        execution_strategy="equal_length_ray_path_reduction",
        creates=("point",),
        output_aliases=(
            ("distance_between_points.distance", "MinimumExpression"),
            ("distance_between_points.evaluated_distance", "MinimumExpression"),
        ),
    ),
    priority="preferred",
)


DEFAULT_CAPABILITY_PACK_REGISTRY = CapabilityPackRegistry((
    CapabilityPackSpec(
        pack_id="quadratic_core",
        kind="base",
        method_ids=(
            "quadratic_axis_from_relation",
            "quadratic_from_constraints",
            "quadratic_vertex_point",
            "quadratic_x_axis_intercept_point",
            "quadratic_y_axis_intercept_point",
            "quadratic_axis_x_intercept_point",
            "point_on_parabola_at_x",
            "line_parabola_second_intersection_point",
        ),
    ),
    CapabilityPackSpec(
        pack_id="parameter_solving_core",
        kind="base",
        method_ids=(
            "parameter_from_expression_value",
            "parameter_from_segment_length",
            "parameter_from_minimum_value",
            "parameter_from_curve_point_on_quadratic",
            "evaluate_expression_at_parameter",
            "evaluate_point_at_parameter",
        ),
    ),
    CapabilityPackSpec(
        pack_id="coordinate_geometry_core",
        kind="base",
        method_ids=(
            "distance_between_points",
            "line_intersection_point",
            "translated_point",
            "midpoint_point",
        ),
    ),
    CapabilityPackSpec(
        # Base for path-minimum families, not a universal base for all
        # quadratic families.
        pack_id="broken_path_minimum_core",
        kind="base",
        method_ids=(
            "two_moving_points_path_reduction",
            "broken_path_straightening_candidates",
            "select_straightening_candidate",
            "distance_between_points",
        ),
        step_recipes=(
            TWO_MOVING_POINTS_PATH_REDUCTION,
            BROKEN_PATH_STRAIGHTENING_AND_SELECT,
            PATH_MINIMUM_BY_STRAIGHTENED_DISTANCE,
            BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION,
        ),
    ),
    CapabilityPackSpec(
        pack_id="right_angle_equal_length_core",
        kind="mechanism",
        method_ids=(
            "right_angle_equal_length_candidates",
            "select_point_by_quadrant_constraint",
        ),
        step_recipes=(RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT,),
    ),
    CapabilityPackSpec(
        pack_id="weighted_path_transform_core",
        kind="mechanism",
        method_ids=(
            "weighted_axis_path_triangle_transform",
            "linked_broken_path_minimum_expression",
        ),
    ),
    CapabilityPackSpec(
        pack_id="equal_length_ray_reduction_core",
        kind="mechanism",
        method_ids=(
            "equal_length_ray_point",
            "distance_between_points",
        ),
        step_recipes=(EQUAL_LENGTH_RAY_PATH_REDUCTION,),
    ),
    CapabilityPackSpec(
        pack_id="square_path_reduction_core",
        kind="mechanism",
        method_ids=(
            "square_path_dimension_reduction",
            "quadratic_axis_parameterized_point",
            "square_adjacent_vertex_from_side",
            "point_candidates_from_curve_point_condition",
            "parameterized_point_locus_line",
            "line_locus_minimum_point",
        ),
    ),
))


__all__ = [
    "DEFAULT_CAPABILITY_PACK_REGISTRY",
    "RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT",
    "TWO_MOVING_POINTS_PATH_REDUCTION",
    "BROKEN_PATH_STRAIGHTENING_AND_SELECT",
    "PATH_MINIMUM_BY_STRAIGHTENED_DISTANCE",
    "BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION",
    "EQUAL_LENGTH_RAY_PATH_REDUCTION",
]
