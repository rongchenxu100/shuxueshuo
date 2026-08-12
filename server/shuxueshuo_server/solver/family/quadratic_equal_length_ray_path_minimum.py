"""二次函数等长射线路径最值 family。

这个 family 覆盖和平 25 这类题：前半段可能通过角条件构造曲线交点，
后半段的关键是通过射线上等长构造，把双动点路径转化成固定点到辅助点的距离。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    FamilyMatchRule,
    FamilySourceRequirementSpec,
    GoalEvidencePolicySpec,
    MethodBindingRuleSpec,
    MethodCompanionOutputSpec,
    MethodInputBindingSpec,
    RecipeExecutionSpec,
    recipe_output_alias,
    SolverFamilySpec,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family.capability_packs import (
    DEFAULT_CAPABILITY_PACK_REGISTRY,
    EQUAL_LENGTH_RAY_PATH_REDUCTION_DESCRIPTION,
    EQUAL_LENGTH_RAY_PATH_REDUCTION_DO_NOT_USE_WHEN,
)


_QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticEqualLengthRayPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("path-minimum",),
        problem_types=("quadratic_equal_length_ray_path_minimum",),
    ),
    title="二次函数等长射线路径最值",
    description=(
        "通过射线上动点与等长条件构造辅助点，把双动点路径转换为单段距离的"
        "二次函数路径最值题。"
    ),
    use_when=(
        "题面同时明确给出射线、射线上的动点和与该动点相关的等长条件，且这些"
        "结构直接承担路径和的等价替换。"
    ),
    required_source_requirements=(
        FamilySourceRequirementSpec(
            "entity_type",
            ("ray",),
            "题面必须明确声明一条射线，而不是普通线段或直线。",
            source_authority="printed_source",
            printed_source_markers=("射线",),
        ),
        FamilySourceRequirementSpec(
            "fact_type",
            ("point_on_ray",),
            "题面必须明确声明动点位于该射线上。",
        ),
        FamilySourceRequirementSpec(
            "fact_type",
            ("equal_length_condition",),
            "题面必须明确给出参与路径替换的等长条件。",
        ),
    ),
    do_not_use_when=(
        "只有直角、等腰或两条普通线段等长，但题面没有射线或射线上动点。",
        "只是普通两动点距离和，可直接降维和折线拉直。",
        "核心机制是非1权重路径或正方形反射。",
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
        "每个 capability 调用是 Solver 的可执行最小颗粒度，不是给学生看的合并讲解步骤。",
        "若当前问的曲线点约束足以确定二次函数，应直接求出完整抛物线；只有只读到一个曲线点约束时，才允许把抛物线化简成单参数表达式。",
        "若题面出现角和、角差或角相等条件，应先把角条件标准化为 AngleEquality，再由等锐角的正切比、相似或三角函数关系求目标点。",
        "当前可用的 angle_sum_equal_angle_candidates 只支持“角和等于 45° 且可由坐标轴参考三角形构造 45° 参考角”的子场景；不满足时应视为能力缺口或选择其它角度 method。",
        "由定义可直接求出的基础点坐标也要用独立 method step 表达，例如 y 轴交点和平移点；不要让后续函数求解 step 隐式解析这些点。",
        "本 family 的路径最值优先使用初中生能理解的几何构造法，而不是把两个动点全部参数化后做复杂解析几何最值。",
        "等长射线路径最值的标准路线是：优先使用 equal_length_ray_path_reduction recipe，把“两动点线段距离和”转化为“单动点/单线段距离”的最小值表达式；辅助点由 recipe 内部构造，FunctionalPlan 不声明内部辅助点。",
        "每个子问的参数闭合链必须留在该子问：路径最值问从本问 minimum_target/minimum_value 求出的 ParameterValue 只能服务本问，不能代入 sibling 子问的抛物线或点；同名参数在不同子问中也要分别由各自事实求值。",
        "公共 scope 只保存所有相关子问从一开始就共享的题面函数模板或开放状态；只要某次求值读取了子问私有 Fact，它的结果就不是公共状态，不能通过 CallResultRef 跨 sibling 复用。",
        "不要单独 produces M_coordinate_expr、N_coordinate_expr、OM_distance_expr、BN_distance_expr 这类参数化/分段距离 utility fact；这些不是初中生优先的解题步骤，也不是本 family 的可执行标准路线。",
        "不要把含参系数缓存、纯文字全等说明或最终讲解段落作为独立 produces；这些可以放在 strategy/reason 中。",
    ),
    base_packs=(
        "quadratic_core",
        "parameter_solving_core",
        "coordinate_geometry_core",
    ),
    mechanism_packs=("equal_length_ray_reduction_core",),
    goal_evidence_policies=(
        GoalEvidencePolicySpec(
            goal_types=(),
            value_types=("Point",),
            required_evidence_tags=("curve_membership",),
            producer_goal_types=(
                "derive_line_parabola_second_intersection",
                "derive_curve_intersection_point",
                "derive_point_on_parabola_at_x",
            ),
        ),
    ),
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
            description=EQUAL_LENGTH_RAY_PATH_REDUCTION_DESCRIPTION,
            method_ids=("equal_length_ray_point", "distance_between_points"),
            execution=RecipeExecutionSpec(
                recipe_id="equal_length_ray_path_reduction",
                method_sequence=("equal_length_ray_point", "distance_between_points"),
                execution_strategy="equal_length_ray_path_reduction",
                creates=("point",),
                output_aliases=(
                    recipe_output_alias(
                        "distance_between_points.distance",
                        "MinimumExpression",
                        "path_minimum_expression",
                        goal_evidence_tags=("path_minimum_expression",),
                    ),
                    recipe_output_alias(
                        "distance_between_points.evaluated_distance",
                        "MinimumExpression",
                        "evaluated_path_minimum_expression",
                        required=False,
                        cardinality="optional",
                        goal_evidence_tags=("path_minimum_expression",),
                    ),
                ),
            ),
            priority="preferred",
            do_not_use_when=EQUAL_LENGTH_RAY_PATH_REDUCTION_DO_NOT_USE_WHEN,
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
            method_id="equal_length_ray_point",
            input_bindings=(
                MethodInputBindingSpec("anchor", "equal_length_ray:anchor"),
                MethodInputBindingSpec("reference_point", "equal_length_ray:reference_point"),
                MethodInputBindingSpec("ray_point", "equal_length_ray:ray_point"),
                MethodInputBindingSpec("target", "equal_length_ray:target"),
            ),
        ),
    ),
)

QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY = expand_family_spec(
    _QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
