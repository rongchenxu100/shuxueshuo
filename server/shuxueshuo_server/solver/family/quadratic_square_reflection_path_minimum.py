"""二次函数正方形反射路径最值 family。

这个 family 覆盖“二次函数 + 以 AE 为边的正方形 + 折线反射最短”类题。
题型核心不是单题点名，而是：

- 先用当前问条件确定或化简抛物线；
- 用正方形边的旋转关系表达另一个顶点或轨迹；
- 把由正方形中点/对角线关系得到的多段路径化成单动点折线；
- 最后用反射拉直求最小值并反求参数。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    FamilyMatchRule,
    MethodBindingRuleSpec,
    MethodCompanionOutputSpec,
    MethodInputBindingSpec,
    RecipeExecutionSpec,
    recipe_output_alias,
    SolverFamilySpec,
    StateObjectRoleProjectionSpec,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family.capability_packs import (
    BROKEN_PATH_MINIMUM_EXPRESSION_DO_NOT_USE_WHEN,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
from shuxueshuo_server.solver.family.common_binding_rules import (
    QUADRATIC_STATE_PREP_INVOCATIONS,
)


_QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticSquareReflectionPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("path-minimum",),
        problem_types=("quadratic_square_reflection_path_minimum",),
    ),
    common_goal_types=(
        "derive_parabola",
        "derive_vertex_point",
        "derive_x_axis_intercept_point",
        "derive_square_constrained_point_candidates",
        "derive_square_path_minimum_expression",
        "derive_parameter",
        "derive_extremal_point",
    ),
    strategy_principles=(
        "每个 StepIntent 是 Method Solver 的可执行最小颗粒度，不是给学生看的合并讲解步骤。",
        "先用当前问的已知系数、曲线点或参数条件确定或化简抛物线；若参数已经能求出，优先先定值再代入，避免缓存宽作用域的复杂含参系数。",
        "正方形关系优先转化为点坐标表达式：先把边端点、轴上点或动点写成含参点，再用正方形的旋转/邻顶点关系推出其它顶点坐标。",
        "当某个由正方形得到的点还满足在曲线、直线或其它轨迹上时，用“点坐标表达式代入约束”来求参数或候选点，而不是把整段推导合成一个大 step。",
        "路径最值优先走初中几何：先用正方形的中点、中心、对角线或等长关系做路径降维，再把剩余问题转成单动点折线路径或点到线距离问题。",
        "正方形路径降维后，不要提前猜测单动点是谁；先产生 PathTransformation，系统会在 repair context 中反馈真实 moving_point 与 fixed_points，再围绕该 moving_point 继续求轨迹和最短状态。",
        "若路径降维后出现动点，先求该动点的坐标表达式或轨迹线，再使用通用将军饮马/折线拉直 recipe 产生最小值表达式。",
        "若题设给出最小值，先产生关于主参数的最小值表达式，再反求参数；参数确定后，后续点坐标应通过代入参数值求出。",
        "路径最值首先确定的是降维后的 moving_point；若最终答案点不是这个 moving_point，不能直接用 evaluate_point_at_parameter 收尾，必须先求最短状态 moving_point，再用正方形关系恢复最终点。",
        "最终答案若是正方形中的某个顶点，应优先由已定值的相邻顶点和正方形关系恢复，不要使用针对单题的闭式公式。",
        "网页讲解可以把若干 method 合并成一段说明；这里输出的 steps 必须尽量对应 catalog 中已有 method/recipe。",
    ),
    base_packs=(
        "quadratic_core",
        "parameter_solving_core",
        "coordinate_geometry_core",
        "broken_path_minimum_core",
    ),
    mechanism_packs=("square_path_reduction_core",),
    method_ids=(
        "quadratic_from_constraints",
        "quadratic_vertex_point",
        "quadratic_x_axis_intercept_point",
        "quadratic_axis_x_intercept_point",
        "square_path_dimension_reduction",
        "quadratic_axis_parameterized_point",
        "square_adjacent_vertex_from_side",
        "point_candidates_from_curve_point_condition",
        "parameterized_point_locus_line",
        "evaluate_point_at_parameter",
        "line_locus_minimum_point",
        "parameter_from_expression_value",
    ),
    step_recipes=(
        StepRecipeSpec(
            recipe_id="broken_path_straightening_minimum_expression",
            goal_type="derive_path_minimum_expression",
            title="折线拉直并求最小值表达式",
            description=(
                "对单动点两段折线路径，生成将军饮马拉直候选，选择最适合计算的方案，"
                "再计算对应两端点距离。端点仍含未定参数时输出开放表达式；端点全部"
                "确定时输出闭合值。本能力不猜测动点轨迹：PathTransformation 未携带"
                "轨迹依据时，必须显式提供同一动点的 Line 轨迹。"
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
                    recipe_output_alias(
                        "select_straightening_candidate.minimum_point_1",
                        "Point",
                        "path_minimum_point_1",
                        required=False,
                        cardinality="optional",
                        identity_policy="derived_role",
                        goal_evidence_tags=("path_minimum_witness",),
                        description=(
                            "选中拉直方案后，由反射构造得到的辅助端点；"
                            "仅供距离计算，不是原路径上的动点、极值点或答案点。"
                        ),
                        object_role_projections=(
                            StateObjectRoleProjectionSpec(
                                role="moving_object",
                                source_arg="path_transformation",
                                source_object_role="moving_object",
                            ),
                        ),
                    ),
                    recipe_output_alias(
                        "select_straightening_candidate.minimum_point_2",
                        "Point",
                        "path_minimum_point_2",
                        required=False,
                        cardinality="optional",
                        identity_policy="derived_role",
                        goal_evidence_tags=("path_minimum_witness",),
                        description=(
                            "选中拉直方案后，与反射端点组成最短线段的另一固定端点；"
                            "仅供距离计算，不是原路径上的动点、极值点或答案点。"
                        ),
                        object_role_projections=(
                            StateObjectRoleProjectionSpec(
                                role="moving_object",
                                source_arg="path_transformation",
                                source_object_role="moving_object",
                            ),
                        ),
                    ),
                    recipe_output_alias(
                        "distance_between_points.distance",
                        "MinimumExpression",
                        "path_minimum_expression",
                        goal_evidence_tags=("path_minimum_expression",),
                        description=(
                            "拉直端点之间的距离；含未定参数时供后续求参，不含自由"
                            "参数时可直接作为数值结果。"
                        ),
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
            do_not_use_when=BROKEN_PATH_MINIMUM_EXPRESSION_DO_NOT_USE_WHEN,
        ),
    ),
    method_binding_rules=(
        MethodBindingRuleSpec(
            method_id="quadratic_from_constraints",
            input_bindings=(
                MethodInputBindingSpec("quadratic", "function:parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
                MethodInputBindingSpec("all_coefficients", "quadratic_coefficients"),
            ),
            expansion_selectors=(
                "known_coefficients_if_read",
                "curve_point_if_read",
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
            method_id="quadratic_axis_x_intercept_point",
            input_bindings=(
                MethodInputBindingSpec("parabola", "read_type:Parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
                MethodInputBindingSpec("target", "point_output_ref"),
            ),
            prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
        ),
        MethodBindingRuleSpec(
            method_id="square_path_dimension_reduction",
            input_bindings=(
                MethodInputBindingSpec("path_condition", "fact:path_minimum_target:Condition"),
                MethodInputBindingSpec("square_condition", "fact:square:Condition"),
                MethodInputBindingSpec("midpoint_condition", "fact:midpoint_definition:Condition"),
                MethodInputBindingSpec("square_center_condition", "fact:square_center:Condition"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="quadratic_axis_parameterized_point",
            input_bindings=(
                MethodInputBindingSpec("parabola", "read_type:Parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
                MethodInputBindingSpec("target", "point_output_ref"),
            ),
            prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
            companion_outputs=(
                MethodCompanionOutputSpec(
                    output_name="parameter",
                    target_selector="axis_parameter_symbol",
                    registration_selector="axis_parameter_symbol",
                ),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="square_adjacent_vertex_from_side",
            input_bindings=(
                MethodInputBindingSpec("side_start", "square:side_start"),
                MethodInputBindingSpec("side_end", "square:side_end"),
                MethodInputBindingSpec("square_condition", "fact:square:Condition"),
                MethodInputBindingSpec("target", "point_transition_target"),
                MethodInputBindingSpec("side_start_ref", "square:side_start_ref", required=False),
                MethodInputBindingSpec("side_end_ref", "square:side_end_ref", required=False),
                MethodInputBindingSpec("parameter", "parameter_symbol", required=False),
                MethodInputBindingSpec("parameter_constraint", "parameter_constraint", required=False),
            ),
            expansion_selectors=("parameter_value_if_read",),
        ),
        MethodBindingRuleSpec(
            method_id="point_candidates_from_curve_point_condition",
            input_bindings=(
                MethodInputBindingSpec("target_point", "curve_condition:target_point"),
                MethodInputBindingSpec("curve_point", "curve_condition:curve_point"),
                MethodInputBindingSpec("parabola", "read_type:Parabola"),
                MethodInputBindingSpec("x", "symbol:x"),
            ),
            prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
        ),
        MethodBindingRuleSpec(
            method_id="parameterized_point_locus_line",
            input_bindings=(
                MethodInputBindingSpec("point", "read_type:Point"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="line_locus_minimum_point",
            input_bindings=(
                MethodInputBindingSpec("moving_locus", "read_type:Line"),
                MethodInputBindingSpec("minimum_point_1", "straightening_minimum:p1"),
                MethodInputBindingSpec("minimum_point_2", "straightening_minimum:p2"),
                MethodInputBindingSpec("target", "point_transition_target"),
            ),
            expansion_selectors=("parameter_value_if_read",),
        ),
    ),
)

QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY = expand_family_spec(
    _QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
