"""二次函数正方形反射路径最值 family。

这个 family 覆盖“二次函数 + 以 AE 为边的正方形 + 折线反射最短”类题。
题型核心不是单题点名，而是：

- 先用当前问条件确定或化简抛物线；
- 用正方形边的旋转关系表达另一个顶点或轨迹；
- 把由正方形中点/对角线关系得到的多段路径化成单动点折线；
- 最后用反射拉直求最小值并反求参数。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import (
    LegacyExpansionSelectorSpec,
    LegacySelectorInputBindingSpec,
    SourceObjectIdentityDerivationSpec,
)
from shuxueshuo_server.solver.family.models import (
    FamilyMatchRule,
    FamilyRuntimePreflightSpec,
    FunctionalOutputTargetSelectorSpec,
    FamilySourceGoalContractSpec,
    FamilySourceRequirementSpec,
    MethodBindingRuleSpec,
    MethodCompanionOutputSpec,
    MacroSearchSpec,
    RecipeExecutionSpec,
    RecipeInputDerivationSpec,
    recipe_output_alias,
    SolverFamilySpec,
    StateObjectRoleProjectionSpec,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family.capability_packs import (
    BROKEN_PATH_MINIMUM_EXPRESSION_DO_NOT_USE_WHEN,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
    STRAIGHTENED_ENDPOINT_RESULT_FORM,
)
from shuxueshuo_server.solver.family.common_binding_rules import (
    QUADRATIC_STATE_PREP_INVOCATIONS,
    canonical_x_binding,
    quadratic_coefficients_binding,
    quadratic_latest_state_binding,
    quadratic_public_state_binding,
)


_QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticSquareReflectionPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("path-minimum",),
        problem_types=("quadratic_square_reflection_path_minimum",),
    ),
    title="二次函数正方形反射路径最值",
    description=(
        "使用正方形顶点、中点、中心或对角线关系完成路径降维，再通过反射或"
        "折线拉直求最值的二次函数题。"
    ),
    use_when=(
        "题面明确给出正方形，并且正方形的顶点、边、中点、中心或对角线关系"
        "直接参与目标路径的降维、轨迹恢复或反射。"
    ),
    required_source_requirements=(
        FamilySourceRequirementSpec(
            "entity_type",
            ("function",),
            "题面必须声明至少一个二次函数对象。",
        ),
        FamilySourceRequirementSpec(
            "fact_type",
            ("square",),
            "题面必须明确给出正方形事实，不能用直角或等长关系替代。",
            source_authority="printed_source",
            printed_source_markers=("正方形",),
        ),
    ),
    runtime_preflights=(
        FamilyRuntimePreflightSpec(
            method_id="square_path_dimension_reduction",
            trigger_fact_types=("path_minimum_target",),
            required_fact_types=(
                "square",
                "midpoint_definition",
                "square_center",
            ),
            source_trigger_fact_types=("minimum_value_given",),
            source_required_fact_types=(
                "minimum_target",
                "square",
                "midpoint",
                "square_center",
            ),
            source_input_names=(
                "path_condition",
                "square_condition",
                "midpoint_condition",
                "square_center_condition",
            ),
            execution_mode="source_structure_only",
            planner_authored_roles=("moving_point",),
            description=(
                "路径目标须具备正方形、中点、中心和可解析的三段路径结构；"
                "moving_point 由 Planner 显式选择，再由这些事实和实际路径"
                "等价性验证。"
            ),
        ),
    ),
    source_goal_contracts=(
        FamilySourceGoalContractSpec(
            selector_id="square_curve_point_candidates",
            expected_value_type="PointList",
            description=(
                "同一正方形另一顶点落抛物线时，目标顶点为候选集合 PointList。"
            ),
        ),
    ),
    do_not_use_when=(
        "只出现直角、等长或一般四边形，题面没有明确正方形。",
        "虽然存在正方形，但它不参与所求路径的降维、反射或答案点恢复。",
        "核心机制是普通折线路径、非1权重路径或射线等长替换。",
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
        "每个 capability 调用是 Solver 的可执行最小颗粒度，不是给学生看的合并讲解步骤。",
        "先用当前问的已知系数、曲线点或参数条件确定或化简抛物线；若参数已经能求出，优先先定值再代入，避免缓存宽作用域的复杂含参系数。",
        "正方形关系优先转化为点坐标表达式：先把边端点、轴上点或动点写成含参点，再用正方形的旋转/邻顶点关系推出其它顶点坐标。",
        "当某个由正方形得到的点还满足在曲线、直线或其它轨迹上时，用“点坐标表达式代入约束”来求参数或候选点，而不是把整段推导合成一个大 step。",
        "路径最值优先走初中几何：先用正方形的中点、中心、对角线或等长关系做路径降维，再把剩余问题转成单动点折线路径或点到线距离问题。",
        "调用 square_path_dimension_reduction 前，路径中每个结构化固定端点都必须在当前问或祖先 scope 已算出坐标。若端点定义为 axis_x_intercept，先对当前问的抛物线调用 quadratic_axis_x_intercept_point，并把 axis_point 绑定到该题面点；仍然只填题面Entity ref，坐标状态由代码选择，也不能借用 sibling 小问的局部结果。",
        "调用 square_path_dimension_reduction 时必须显式填写 moving_point，声明你选择的降维后单动点。代码会用正方形邻接、中点、中心和原路径验证该选择；不得省略后等待系统猜测，也不得按顶点数组位置机械选择。",
        "若路径降维后出现动点，先求该动点的坐标表达式或轨迹线，再使用通用将军饮马/折线拉直 recipe 产生最小值表达式。",
        "若题设给出最小值，先产生关于主参数的最小值表达式，再反求参数；参数确定后，后续点坐标应通过代入参数值求出。",
        "路径最值首先确定的是降维后的 moving_point；必须对这个 moving_point 依次求轨迹、最短状态点，再恢复最终答案点。若最终答案点不是 moving_point，不能直接用 evaluate_point_at_parameter 收尾。",
        "quadratic_axis_parameterized_point 为轴上点引入独立的位置参数；抛物线系数不是这个位置参数。evaluate_point_at_parameter 只能代入与点坐标中未定符号属于同一数学实体的已知值，绝不能把求出的曲线系数 c 当作点 E 的轴上位置参数。",
        "正方形路径的标准收尾是：Planner 为 square_path_dimension_reduction 声明 moving_point，runtime 验证路径等价后，parameterized_point_locus_line 求该点轨迹，broken_path_straightening_minimum_expression 拉直，line_locus_minimum_point 求最短状态 moving_point，最后用 square_adjacent_vertex_from_side 等正方形关系恢复答案点。",
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
                execution_mode="direct",
                execution_strategy="broken_path_straightening_minimum_expression",
                input_aliases=(
                    (
                        "parameter_value",
                        "distance_between_points.parameter_value",
                    ),
                ),
                input_derivations=(
                    RecipeInputDerivationSpec(
                        target="distance_between_points.parameter",
                        derivation=SourceObjectIdentityDerivationSpec(
                            source_input="parameter_value",
                        ),
                    ),
                ),
                strategy_input_targets=(
                    "broken_path_straightening_candidates.path_transformation",
                    "broken_path_straightening_candidates.moving_point_membership",
                    "broken_path_straightening_candidates.moving_locus",
                    "broken_path_straightening_candidates.fixed_point_1",
                    "broken_path_straightening_candidates.fixed_point_2",
                    "broken_path_straightening_candidates.line_point_1",
                    "broken_path_straightening_candidates.line_point_2",
                    "select_straightening_candidate.target",
                ),
                intermediate_wiring=(
                    (
                        "broken_path_straightening_candidates.candidates",
                        "select_straightening_candidate.candidates",
                    ),
                    (
                        "select_straightening_candidate.minimum_point_1",
                        "distance_between_points.p1",
                    ),
                    (
                        "select_straightening_candidate.minimum_point_2",
                        "distance_between_points.p2",
                    ),
                ),
                output_aliases=(
                    recipe_output_alias(
                        "select_straightening_candidate.minimum_point_1",
                        "Point",
                        "straightened_endpoint_1",
                        required=False,
                        cardinality="optional",
                        identity_policy="derived_role",
                        goal_evidence_tags=("path_minimum_witness",),
                        result_form=STRAIGHTENED_ENDPOINT_RESULT_FORM,
                        description=(
                            "拉直后最短等价线段的第一个端点，通常是由反射构造"
                            "得到的辅助点；它不是原路径动点、极值点或答案点。"
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
                        "straightened_endpoint_2",
                        required=False,
                        cardinality="optional",
                        identity_policy="derived_role",
                        goal_evidence_tags=("path_minimum_witness",),
                        result_form=STRAIGHTENED_ENDPOINT_RESULT_FORM,
                        description=(
                            "拉直后最短等价线段的第二个端点，通常是未被反射的"
                            "另一固定端点；它不是原路径动点、极值点或答案点。"
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
                quadratic_latest_state_binding("quadratic"),
                canonical_x_binding(),
                quadratic_coefficients_binding(),
            ),
            expansion_selectors=(
                LegacyExpansionSelectorSpec("known_coefficients_if_read"),
                LegacyExpansionSelectorSpec("curve_point_if_read"),
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
                quadratic_public_state_binding("parabola"),
                canonical_x_binding(),
                LegacySelectorInputBindingSpec("target", "point_output_ref"),
            ),
            prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
        ),
        MethodBindingRuleSpec(
            method_id="square_path_dimension_reduction",
            input_bindings=(
                LegacySelectorInputBindingSpec("path_condition", "fact:path_minimum_target:Condition"),
                LegacySelectorInputBindingSpec("square_condition", "fact:square:Condition"),
                LegacySelectorInputBindingSpec("midpoint_condition", "fact:midpoint_definition:Condition"),
                LegacySelectorInputBindingSpec("square_center_condition", "fact:square_center:Condition"),
                LegacySelectorInputBindingSpec(
                    "fixed_endpoint_1_ref",
                    "square_path:fixed_endpoint_1_ref",
                ),
                LegacySelectorInputBindingSpec(
                    "fixed_endpoint_2_ref",
                    "square_path:fixed_endpoint_2_ref",
                ),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="quadratic_axis_parameterized_point",
            functional_output_target_selectors=(
                FunctionalOutputTargetSelectorSpec(
                    output_name="point",
                    selector_id="unique_visible_fact_target",
                    fact_kind="point_on_axis",
                    prompt_fact_kind="axis_membership",
                    target_field="point",
                    related_arg="parabola",
                    related_field="curve",
                    required_field_values=(("axis", "symmetry"),),
                    description=(
                        "若可见 axis_membership 事实唯一确定当前抛物线"
                        "对称轴上的 Point，则代码可绑定该已有对象；存在多个"
                        "候选时必须显式 output_targets。"
                    ),
                ),
            ),
            input_bindings=(
                quadratic_public_state_binding("parabola"),
                canonical_x_binding(),
                LegacySelectorInputBindingSpec("target", "point_output_ref"),
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
            functional_output_names=(("point", "adjacent_vertex"),),
            input_bindings=(
                LegacySelectorInputBindingSpec("side_start", "square:side_start"),
                LegacySelectorInputBindingSpec("side_end", "square:side_end"),
                LegacySelectorInputBindingSpec("square_condition", "fact:square:Condition"),
                LegacySelectorInputBindingSpec("target", "point_transition_target"),
                LegacySelectorInputBindingSpec("side_start_ref", "square:side_start_ref", required=False),
                LegacySelectorInputBindingSpec("side_end_ref", "square:side_end_ref", required=False),
                LegacySelectorInputBindingSpec(
                    "parameter",
                    "parameter_symbol",
                    required=False,
                    functional_authority="wire",
                    functional_resolver="unique_parameter_symbol",
                ),
                LegacySelectorInputBindingSpec("parameter_constraint", "parameter_constraint", required=False),
            ),
            expansion_selectors=(
                LegacyExpansionSelectorSpec("parameter_value_if_read"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="point_candidates_from_curve_point_condition",
            input_bindings=(
                LegacySelectorInputBindingSpec("target_point", "curve_condition:target_point"),
                LegacySelectorInputBindingSpec("curve_point", "curve_condition:curve_point"),
                quadratic_public_state_binding("parabola"),
                canonical_x_binding(),
            ),
            prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
        ),
        MethodBindingRuleSpec(
            method_id="parameterized_point_locus_line",
            input_bindings=(
                LegacySelectorInputBindingSpec("point", "read_type:Point"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="line_locus_minimum_point",
            input_bindings=(
                LegacySelectorInputBindingSpec("moving_locus", "read_type:Line"),
                LegacySelectorInputBindingSpec("minimum_point_1", "straightening_minimum:p1"),
                LegacySelectorInputBindingSpec("minimum_point_2", "straightening_minimum:p2"),
                LegacySelectorInputBindingSpec("target", "point_transition_target"),
            ),
            expansion_selectors=(
                LegacyExpansionSelectorSpec("parameter_value_if_read"),
            ),
        ),
    ),
)

QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY = expand_family_spec(
    _QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
