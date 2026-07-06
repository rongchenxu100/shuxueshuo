"""二次函数路径最值 SolverFamilySpec。

这里抽取的是“二次函数 + 构造点 + 路径最值”这类题的共性上下文，供后续通用
Planner 参考。它不包含南开 25 的固定 StepPlan，也不包含最终答案结构。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    FamilyMatchRule,
    MethodCompanionOutputSpec,
    MethodBindingRuleSpec,
    MethodInputBindingSpec,
    RecipeExecutionSpec,
    SolverFamilySpec,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family.capability_packs import (
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)


_QUADRATIC_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("path-minimum",),
        problem_types=("quadratic_path_minimum",),
    ),
    common_goal_types=(
        "derive_parabola",
        "derive_axis_point",
        "derive_constructed_point",
        "derive_parameter",
        "reduce_path_expression",
        "straighten_broken_path",
        "derive_minimum_value",
        "derive_extremal_point",
    ),
    strategy_principles=(
        "先解析题设中的函数、点、关系和参数约束。",
        "每一问进入几何或路径推导前，先尽量代入该问已知系数与已知曲线点，化简当前问函数表达式。",
        "函数化简的目标不是缓存复杂含参式，而是让 a、b、c 完全确定或只剩一个后续条件会用到的未知量；若 b、c 等多个参数都能表达同一函数，应根据后续长度、最值、曲线点或答案目标选择保留哪个参数，无法判断时先等待更多约束。",
        "若构造点坐标未知，先由几何关系生成候选，再用题设约束筛选。",
        "能先确定未知参数时，优先先求参数再代入后续表达式。",
        "每一步优先消去已确定的信息：若当前问条件已能确定参数数值，先求参数再代入；若参数暂不能定值，但代入已知系数、已知点或系数关系能减少未知量，则可以先化简表达式。",
        "路径最值先做路径转化，再做折线拉直或等价最短路径处理。",
        "普通路径最值按 recipe 独立拆分：先 two_moving_points_path_reduction 降维，再 broken_path_straightening_and_select 选择拉直方案，最后 path_minimum_by_straightened_distance 单独求最小值表达式。",
        "最短路径对应点通常来自约束轨迹与拉直线段的交点。",
    ),
    base_packs=(
        "quadratic_core",
        "parameter_solving_core",
        "coordinate_geometry_core",
        "broken_path_minimum_core",
    ),
    mechanism_packs=("right_angle_equal_length_core",),
    method_ids=(
        "quadratic_axis_from_relation",
        "quadratic_from_constraints",
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
        "parameter_from_segment_length",
        "midpoint_point",
        "two_moving_points_path_reduction",
        "broken_path_straightening_candidates",
        "select_straightening_candidate",
        "distance_between_points",
        "parameter_from_minimum_value",
        "line_intersection_point",
    ),
    step_recipes=(
        StepRecipeSpec(
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
                    ("right_angle_equal_length_candidates.candidates", "select_point_by_quadrant_constraint.candidates"),
                ),
                output_aliases=(
                    ("select_point_by_quadrant_constraint.selected_point", "Point"),
                ),
            ),
        ),
        StepRecipeSpec(
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
        ),
        StepRecipeSpec(
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
                    ("broken_path_straightening_candidates.candidates", "select_straightening_candidate.candidates"),
                ),
                output_aliases=(
                    ("select_straightening_candidate.selected_candidate", "StraighteningCandidate"),
                    ("select_straightening_candidate.auxiliary_point", "Point"),
                ),
            ),
            priority="preferred",
        ),
        StepRecipeSpec(
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
        ),
    ),
    method_binding_rules=(
        MethodBindingRuleSpec(
            method_id="quadratic_axis_from_relation",
            input_bindings=(
                MethodInputBindingSpec("coefficient_relation", "fact:coefficient_relation:Equation"),
                MethodInputBindingSpec("a", "symbol:a"),
                MethodInputBindingSpec("b", "symbol:b"),
                MethodInputBindingSpec("target", "point_output_ref"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="quadratic_from_constraints",
            input_bindings=(
                MethodInputBindingSpec("quadratic", "function:parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
                MethodInputBindingSpec("coefficient_relation", "fact:coefficient_relation:Equation"),
                MethodInputBindingSpec("all_coefficients", "quadratic_coefficients"),
            ),
            expansion_selectors=(
                "known_coefficients_if_read",
                "parameter_value_if_read",
                "curve_point_if_read",
                "curve_points_if_parameterized",
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
            method_id="parameter_from_segment_length",
            input_bindings=(
                MethodInputBindingSpec("p1", "length_segment:p1"),
                MethodInputBindingSpec("p2", "length_segment:p2"),
                MethodInputBindingSpec("parameter", "parameter_symbol"),
                MethodInputBindingSpec("condition", "fact:length_squared:Condition"),
                MethodInputBindingSpec("constraint", "parameter_constraint"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="parameter_from_minimum_value",
            input_bindings=(
                MethodInputBindingSpec("minimum_expression", "read_type:MinimumExpression"),
                MethodInputBindingSpec("condition", "fact:minimum_value:Condition"),
                MethodInputBindingSpec("parameter", "parameter_symbol"),
                MethodInputBindingSpec("constraint", "parameter_constraint"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="two_moving_points_path_reduction",
            input_bindings=(
                MethodInputBindingSpec("original_path", "fact:path_minimum_target:Condition"),
                MethodInputBindingSpec("first_moving_membership", "path_reduction:first_membership"),
                MethodInputBindingSpec("second_moving_membership", "path_reduction:second_membership"),
                MethodInputBindingSpec("binding_relation", "path_reduction:relation"),
                MethodInputBindingSpec("first_segment_start", "path_reduction:first_segment_start"),
                MethodInputBindingSpec("joint_point", "path_reduction:joint_point"),
                MethodInputBindingSpec("second_segment_end", "path_reduction:second_segment_end"),
            ),
        ),
    ),
    # 临时兼容硬门控：当前 V1.5 deterministic planner 只实现 canonical 南开 25。
    # 退出条件：
    # 1. 至少两道同 family 的完整 E2E fixture 通过；
    # 2. planner 不再依赖 D/M/N/F/G、i/ii/ii_1/ii_2 等 canonical 命名；
    # 3. 去掉门控后，alt-label 同构题能通过，其他 family 题仍不会误路由。
    enabled_problem_ids=("tj-2026-nankai-yimo-25",),
)

QUADRATIC_PATH_MINIMUM_FAMILY = expand_family_spec(
    _QUADRATIC_PATH_MINIMUM_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
