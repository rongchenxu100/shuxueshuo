"""二次函数等长射线路径最值 family。

这个 family 覆盖和平 25 这类题：前半段可能通过角条件构造曲线交点，
后半段的关键是通过射线上等长构造，把双动点路径转化成固定点到辅助点的距离。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    FamilyMatchRule,
    MethodBindingRuleSpec,
    MethodCompanionOutputSpec,
    MethodInputBindingSpec,
    MethodPrepInvocationSpec,
    RecipeExecutionSpec,
    SolverFamilySpec,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family.capability_packs import (
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)


_QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticEqualLengthRayPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("path-minimum",),
        problem_types=("quadratic_equal_length_ray_path_minimum",),
    ),
    common_goal_types=(
        "derive_parabola",
        "derive_y_axis_intercept_point",
        "derive_translated_point",
        "derive_axis_intercept_point",
        "derive_equal_angle",
        "derive_angle_constructed_point",
        "derive_curve_intersection_point",
        "derive_equal_length_constructed_point",
        "derive_path_minimum_expression",
        "derive_parameter",
    ),
    strategy_principles=(
        "每个 StepIntent 是 Method Solver 的可执行最小颗粒度，不是给学生看的合并讲解步骤。",
        "若当前问的曲线点约束足以确定二次函数，应直接求出完整抛物线；只有只读到一个曲线点约束时，才允许把抛物线化简成单参数表达式。",
        "若题面出现角和、角差或角相等条件，应先把角条件标准化为 AngleEquality，再由等锐角的正切比、相似或三角函数关系求目标点。",
        "当前可用的 angle_sum_equal_angle_candidates 只支持“角和等于 45° 且可由坐标轴参考三角形构造 45° 参考角”的子场景；不满足时应视为能力缺口或选择其它角度 method。",
        "由定义可直接求出的基础点坐标也要用独立 method step 表达，例如 y 轴交点和平移点；不要让后续函数求解 step 隐式解析这些点。",
        "本 family 的路径最值优先使用初中生能理解的几何构造法，而不是把两个动点全部参数化后做复杂解析几何最值。",
        "等长射线路径最值的标准路线是：优先使用 equal_length_ray_path_reduction recipe，把“两动点线段距离和”转化为“单动点/单线段距离”的最小值表达式；辅助点由 recipe 内部构造，StepIntent 不需要 creates 辅助点。",
        "不要单独 produces M_coordinate_expr、N_coordinate_expr、OM_distance_expr、BN_distance_expr 这类参数化/分段距离 utility fact；这些不是初中生优先的解题步骤，也不是本 family 的可执行标准路线。",
        "不要把含参系数缓存、纯文字全等说明或最终讲解段落作为独立 produces；这些可以放在 strategy/reason 中。",
    ),
    base_packs=(
        "quadratic_core",
        "parameter_solving_core",
        "coordinate_geometry_core",
    ),
    mechanism_packs=("equal_length_ray_reduction_core",),
    method_ids=(
        "quadratic_from_constraints",
        "quadratic_y_axis_intercept_point",
        "translated_point",
        "quadratic_x_axis_intercept_point",
        "angle_sum_equal_angle_candidates",
        "axis_intercept_from_equal_acute_angles",
        "line_parabola_second_intersection_point",
        "equal_length_ray_point",
        "distance_between_points",
        "parameter_from_expression_value",
    ),
    step_recipes=(
        StepRecipeSpec(
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
        ),
    ),
    method_binding_rules=(
        MethodBindingRuleSpec(
            method_id="quadratic_from_constraints",
            input_bindings=(
                MethodInputBindingSpec("quadratic", "function:parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
                MethodInputBindingSpec("all_coefficients", "quadratic_coefficients"),
                MethodInputBindingSpec(
                    "free_parameter",
                    "free_parameter:a_if_single_curve_point",
                    required=False,
                ),
            ),
            expansion_selectors=(
                "known_coefficients_if_read",
                "curve_point_if_read",
                "parameter_value_if_read",
            ),
            always_emit_outputs=("coefficients",),
            companion_outputs=(
                MethodCompanionOutputSpec(
                    "coefficients",
                    "answer_scope_output:coefficients",
                    "runtime_step_output:coefficients",
                ),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="quadratic_x_axis_intercept_point",
            input_bindings=(
                MethodInputBindingSpec("quadratic", "read_type:Parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
                MethodInputBindingSpec("target", "point_output_ref"),
                MethodInputBindingSpec("known_point", "x_axis_known_point", required=False),
            ),
            prep_invocations=(
                MethodPrepInvocationSpec(
                    trigger_selector="missing_readable_type:Parabola",
                    method_id="quadratic_from_constraints",
                    output_aliases=(
                        ("coefficients", "prepared_coefficients"),
                        ("parabola", "prepared_parabola"),
                    ),
                    local_output_aliases=(
                        ("type:Coefficients", "coefficients"),
                        ("type:Parabola", "parabola"),
                    ),
                ),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="quadratic_y_axis_intercept_point",
            input_bindings=(
                MethodInputBindingSpec("quadratic", "function:parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
                MethodInputBindingSpec("target", "point_output_ref"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="translated_point",
            input_bindings=(
                MethodInputBindingSpec("source", "translated_point:source"),
                MethodInputBindingSpec("target", "translated_point:target"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="angle_sum_equal_angle_candidates",
            input_bindings=(
                MethodInputBindingSpec("condition", "angle_sum:condition"),
                MethodInputBindingSpec("x_axis_point", "angle_sum:x_axis_point"),
                MethodInputBindingSpec("y_axis_point", "angle_sum:y_axis_point"),
                MethodInputBindingSpec("reference_x_axis_point", "angle_sum:reference_x_axis_point"),
                MethodInputBindingSpec("origin", "angle_sum:origin"),
                MethodInputBindingSpec("target", "angle_sum:target"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="axis_intercept_from_equal_acute_angles",
            input_bindings=(
                MethodInputBindingSpec("angle_equality", "angle_equality:fact"),
                MethodInputBindingSpec("x_axis_point", "angle_equality:x_axis_point"),
                MethodInputBindingSpec("y_axis_point", "angle_equality:y_axis_point"),
                MethodInputBindingSpec("reference_x_axis_point", "angle_equality:reference_x_axis_point"),
                MethodInputBindingSpec("origin", "angle_equality:origin"),
                MethodInputBindingSpec("target", "angle_equality:target"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="line_parabola_second_intersection_point",
            input_bindings=(
                MethodInputBindingSpec("parabola", "read_type:Parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
                MethodInputBindingSpec("line_p1", "line_parabola:line_p1"),
                MethodInputBindingSpec("line_p2", "line_parabola:line_p2"),
                MethodInputBindingSpec("known_point", "line_parabola:known_point"),
                MethodInputBindingSpec("target", "line_parabola:target"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="equal_length_ray_point",
            input_bindings=(
                MethodInputBindingSpec("anchor", "equal_length_ray:anchor"),
                MethodInputBindingSpec("reference_point", "equal_length_ray:reference_point"),
                MethodInputBindingSpec("ray_point", "equal_length_ray:ray_point"),
                MethodInputBindingSpec("target", "equal_length_ray:target"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="distance_between_points",
            input_bindings=(
                MethodInputBindingSpec("p1", "distance:p1"),
                MethodInputBindingSpec("p2", "distance:p2"),
            ),
            expansion_selectors=("distance_parameter_value_if_read",),
        ),
        MethodBindingRuleSpec(
            method_id="parameter_from_expression_value",
            input_bindings=(
                MethodInputBindingSpec("expression", "read_type:MinimumExpression"),
                MethodInputBindingSpec("condition", "fact:minimum_value:Condition"),
                MethodInputBindingSpec("parameter", "parameter_symbol"),
                MethodInputBindingSpec("constraint", "parameter_constraint", required=False),
            ),
        ),
    ),
)

QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY = expand_family_spec(
    _QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
