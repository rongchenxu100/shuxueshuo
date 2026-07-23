"""加权二次函数路径最值 SolverFamilySpec。

这里描述的是河西 25 所代表的“二次函数 + 加权路径最值”题型上下文。它只用于
RuntimeOrchestrator 匹配 family，并给 Planner 提供题型级参考，不保存具体答案。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    CapabilityContractSpec,
    ConditionPattern,
    FamilyMatchRule,
    MethodCompanionOutputSpec,
    MethodBindingRuleSpec,
    MethodInputBindingSpec,
    RecipeExecutionSpec,
    recipe_output_alias,
    SolverFamilySpec,
    StateSlotPattern,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family.capability_packs import (
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
_QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticWeightedPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("weighted-path-minimum",),
        problem_types=("quadratic_weighted_path_minimum",),
    ),
    common_goal_types=(
        "derive_parabola",
        "derive_vertex_point",
        "derive_constructed_point",
        "derive_weighted_path_minimum",
        "derive_parameter",
    ),
    strategy_principles=(
        "先将每一问的已知系数与已知曲线点尽量代入，得到当前问最简抛物线表达式。",
        "函数化简只有在能显著减少未知量时才单独成步：理想状态是 a、b、c 完全确定，或只剩一个后续条件会直接求解/引用的未知量；若 b、c 等多个参数都能表达同一函数，应结合后续曲线点、几何筛选、最值或答案目标选择保留哪个参数。",
        "几何构造点先列候选；若候选点还需落在含参曲线上，再用候选曲线点求参 recipe 筛选并反求参数。",
        "加权路径最值优先寻找几何转化：用辅助直角三角形把加权段转成同倍率折线，再用折线拉直或等价最短路径处理。",
        "加权路径最值按可执行颗粒拆成：weighted_axis_path_triangle_transform 做几何转化，linked_broken_path_minimum_expression 求最小值表达式，parameter_from_expression_value 由给定值反求参数；不要把三步合成一个 utility step。",
    ),
    base_packs=(
        "quadratic_core",
        "parameter_solving_core",
        "coordinate_geometry_core",
    ),
    mechanism_packs=(
        "right_angle_equal_length_core",
        "weighted_path_transform_core",
    ),
    method_ids=(
        "quadratic_from_constraints",
        "quadratic_vertex_point",
        "quadratic_y_axis_intercept_point",
        "quadratic_x_axis_intercept_point",
        "right_angle_equal_length_candidates",
        "filter_point_candidates_by_quadratic_curve",
        "parameter_from_curve_point_on_quadratic",
        "point_on_parabola_at_x",
        "evaluate_expression_at_parameter",
        "parameter_from_segment_length",
        "weighted_axis_path_triangle_transform",
        "linked_broken_path_minimum_expression",
        "parameter_from_expression_value",
    ),
    step_recipes=(
        StepRecipeSpec(
            recipe_id="curve_candidate_parameter_solve",
            goal_type="derive_constructed_point",
            title="曲线候选点筛选并反求参数",
            description=(
                "候选点已经由前序几何构造得到后，用当前问含参抛物线和参数约束"
                "筛出唯一候选点，再把该含参点代入抛物线反求参数并代回抛物线。"
            ),
            method_ids=(
                "filter_point_candidates_by_quadratic_curve",
                "parameter_from_curve_point_on_quadratic",
            ),
            execution=RecipeExecutionSpec(
                recipe_id="curve_candidate_parameter_solve",
                method_sequence=(
                    "filter_point_candidates_by_quadratic_curve",
                    "parameter_from_curve_point_on_quadratic",
                ),
                execution_strategy="curve_candidate_parameter_solve",
                intermediate_wiring=(
                    ("filter_point_candidates_by_quadratic_curve.selected_candidate", "parameter_from_curve_point_on_quadratic.point"),
                ),
                output_aliases=(
                    recipe_output_alias(
                        "parameter_from_curve_point_on_quadratic.point",
                        "Point",
                        "selected_curve_point",
                        identity_policy="target_object",
                    ),
                    recipe_output_alias(
                        "parameter_from_curve_point_on_quadratic.parameter_value",
                        "ParameterValue",
                        "parameter_value",
                        required=False,
                        cardinality="optional",
                    ),
                    recipe_output_alias(
                        "parameter_from_curve_point_on_quadratic.parabola",
                        "Parabola",
                        "solved_parabola",
                        required=False,
                        cardinality="optional",
                    ),
                ),
            ),
        ),
    ),
    capability_contracts=(
        CapabilityContractSpec(
            capability_id="curve_candidate_parameter_solve",
            kind="recipe",
            slot_reads=(
                StateSlotPattern(
                    "candidate",
                    "PointList",
                    object_kind="point",
                    semantic_role="candidates",
                ),
                StateSlotPattern(
                    "expression",
                    "Parabola",
                    object_kind="function",
                    semantic_role="parabola",
                ),
                StateSlotPattern(
                    "coordinate",
                    "Point",
                    object_kind="point",
                    semantic_role="target_point",
                ),
            ),
            condition_reads=(
                ConditionPattern("point_on_curve", required=False),
                ConditionPattern("symbol_constraint", required=False),
            ),
            slot_writes=(
                StateSlotPattern(
                    "coordinate",
                    "Point",
                    object_kind="point",
                    semantic_role="selected_curve_point",
                    output_key="parameter_from_curve_point_on_quadratic.point",
                    write_mode="create",
                ),
            ),
        ),
    ),
    method_binding_rules=(
        MethodBindingRuleSpec(
            method_id="right_angle_equal_length_candidates",
            input_bindings=(
                MethodInputBindingSpec("anchor", "right_angle:anchor"),
                MethodInputBindingSpec("reference", "right_angle:reference"),
                MethodInputBindingSpec("target", "right_angle:target"),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="parameter_from_segment_length",
            input_bindings=(
                MethodInputBindingSpec("p1", "length_segment:p1"),
                MethodInputBindingSpec("p2", "length_segment:p2"),
                MethodInputBindingSpec("reference_p1", "length_reference_segment:p1", required=False),
                MethodInputBindingSpec("reference_p2", "length_reference_segment:p2", required=False),
                MethodInputBindingSpec("parameter", "parameter_symbol"),
                MethodInputBindingSpec("condition", "fact:length_condition:Condition"),
                MethodInputBindingSpec("constraint", "parameter_constraint", required=False),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="weighted_axis_path_triangle_transform",
            input_bindings=(
                MethodInputBindingSpec("condition", "weighted_path:condition"),
                MethodInputBindingSpec("fixed_point", "weighted_path:fixed_point"),
                MethodInputBindingSpec("moving_point", "weighted_path:moving_point"),
                MethodInputBindingSpec("dynamic_parameter", "dynamic_symbol"),
                MethodInputBindingSpec("auxiliary_point_ref", "weighted_path:auxiliary_point_ref"),
            ),
            always_emit_outputs=("auxiliary_point", "auxiliary_locus"),
            companion_outputs=(
                MethodCompanionOutputSpec(
                    "auxiliary_point",
                    "weighted_path_auxiliary_point",
                    "weighted_path_auxiliary_point",
                ),
                MethodCompanionOutputSpec(
                    "auxiliary_locus",
                    "scope_output:auxiliary_locus",
                    "runtime_step_output:auxiliary_locus",
                ),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="linked_broken_path_minimum_expression",
            input_bindings=(
                MethodInputBindingSpec("path_transformation", "read_type:PathTransformation"),
                MethodInputBindingSpec("auxiliary_locus", "read_type:Line"),
                MethodInputBindingSpec("fixed_point", "weighted_path:fixed_point"),
                MethodInputBindingSpec("curve_point", "weighted_path:curve_point"),
                MethodInputBindingSpec("moving_point", "weighted_path:moving_point"),
                MethodInputBindingSpec("auxiliary_point", "weighted_path:auxiliary_point"),
                MethodInputBindingSpec("parameter", "parameter_symbol"),
                MethodInputBindingSpec("dynamic_parameter", "dynamic_symbol"),
                MethodInputBindingSpec("parameter_constraint", "parameter_constraint"),
                MethodInputBindingSpec("dynamic_constraint", "dynamic_constraint"),
            ),
        ),
    ),
)

QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY = expand_family_spec(
    _QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
