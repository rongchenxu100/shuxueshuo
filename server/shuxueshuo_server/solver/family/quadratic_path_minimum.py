"""二次函数路径最值 SolverFamilySpec。

这里抽取的是“二次函数 + 构造点 + 路径最值”这类题的共性上下文，供后续通用
Planner 参考。它不包含南开 25 的固定 StepPlan，也不包含最终答案结构。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    FamilyMatchRule,
    FamilySourceRequirementSpec,
    MethodBindingRuleSpec,
    RecipeExecutionSpec,
    recipe_output_alias,
    SolverFamilySpec,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family.capability_packs import (
    DEFAULT_CAPABILITY_PACK_REGISTRY,
    RIGHT_ANGLE_EQUAL_LENGTH_DO_NOT_USE_WHEN,
)
from shuxueshuo_server.solver.family.common_binding_rules import (
    canonical_symbol_binding,
    canonical_x_binding,
    condition_arg_binding,
    exact_call_result_binding,
    parameter_basis_binding,
    previous_output_identity_binding,
    public_arg_binding,
    quadratic_coefficients_binding,
    quadratic_latest_state_binding,
    related_condition_binding,
)


_QUADRATIC_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("path-minimum",),
        problem_types=("quadratic_path_minimum",),
    ),
    title="普通二次函数路径最值",
    description=(
        "二次函数题中的普通点、线段或折线路径最值；核心机制是不带特殊权重、"
        "射线等长替换或正方形反射的通用路径降维与拉直。"
    ),
    use_when=(
        "题面要求普通距离和或折线路径的最小值，允许出现辅助性的直角、等长或"
        "中点关系，但路径机制本身不依赖非1权重、射线等长构造或正方形反射。"
    ),
    required_source_requirements=(
        FamilySourceRequirementSpec(
            "entity_type",
            ("function",),
            "题面必须声明至少一个二次函数对象。",
        ),
        FamilySourceRequirementSpec(
            "fact_type",
            ("path_minimum_target", "minimum_value"),
            "题面必须显式给出路径/距离最值目标或最小值条件。",
        ),
    ),
    do_not_use_when=(
        "目标路径含明确的非1权重系数，并以加权几何变换为核心。",
        "题面明确声明射线、射线上动点和等长条件，并用它们替换路径。",
        "题面以正方形顶点、中点、中心或对角线关系完成路径降维或反射。",
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
        "若路径 Macro 需要的固定端点由中点等题面构造定义，先在该构造所属 Scope 用普通 Function 物化端点坐标；不要在各子问重复构造。",
        "若目标路径中的两动点通过一条题设线段关系耦合，直接调用耦合线段端点替换路径最值 Macro；只选择路径目标和负责耦合的线段关系。",
        "若多个子问消费同一含参最小值表达式或取等状态，把该 Macro 放在它们最近公共父 Scope，只调用一次；子问通过 StepResultRef 求值。",
        "端点替换、保留动点、内部反射和取等恢复均由 Macro 验证；Planner 只调用原子能力，不拆写其内部几何构造。",
        "Macro 同时返回最小值表达式与原题动点的取等状态；后续求具体坐标时用 StepResultRef 消费 attainment_point。",
    ),
    base_packs=(
        "quadratic_core",
        "parameter_solving_core",
        "coordinate_geometry_core",
    ),
    mechanism_packs=(
        "right_angle_equal_length_core",
        "coupled_segment_path_minimum_core",
    ),
    method_ids=(
        "quadratic_axis_from_relation",
        "quadratic_from_constraints",
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
        "parameter_from_segment_length",
        "midpoint_point",
        "parameter_from_minimum_value",
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
                execution_mode="direct",
                execution_strategy="right_angle_construct_select",
                strategy_input_targets=(
                    "right_angle_equal_length_candidates.anchor",
                    "right_angle_equal_length_candidates.reference",
                    "right_angle_equal_length_candidates.target",
                    "select_point_by_quadrant_constraint.target",
                    "select_point_by_quadrant_constraint.quadrant",
                    "select_point_by_quadrant_constraint.parameter",
                    "select_point_by_quadrant_constraint.parameter_constraint",
                ),
                intermediate_wiring=(
                    ("right_angle_equal_length_candidates.candidates", "select_point_by_quadrant_constraint.candidates"),
                ),
                output_aliases=(
                    recipe_output_alias(
                        "select_point_by_quadrant_constraint.selected_point",
                        "Point",
                        "selected_target_point",
                        identity_policy="target_object",
                        identity_arg="target",
                    ),
                ),
            ),
            do_not_use_when=RIGHT_ANGLE_EQUAL_LENGTH_DO_NOT_USE_WHEN,
        ),
    ),
    method_binding_rules=(
        MethodBindingRuleSpec(
            method_id="quadratic_axis_from_relation",
            input_bindings=(
                condition_arg_binding("coefficient_relation"),
                canonical_symbol_binding("a", symbol_name="a"),
                canonical_symbol_binding("b", symbol_name="b"),
                previous_output_identity_binding(
                    "target",
                    output_name="axis_point",
                ),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="quadratic_from_constraints",
            input_bindings=(
                quadratic_latest_state_binding("quadratic"),
                canonical_x_binding(),
                condition_arg_binding(
                    "coefficient_relation",
                    required=False,
                ),
                quadratic_coefficients_binding(),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="parameter_from_segment_length",
            input_bindings=(
                public_arg_binding("p1"),
                public_arg_binding("p2"),
                parameter_basis_binding(
                    (
                        "p1",
                        "p2",
                        "reference_p1",
                        "reference_p2",
                        "condition",
                        "constraint",
                    )
                ),
                condition_arg_binding("condition", public_arg="length_squared"),
                related_condition_binding(
                    "constraint",
                    condition_kinds=("symbol_constraint",),
                    related_args=("parameter",),
                ),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="parameter_from_minimum_value",
            input_bindings=(
                exact_call_result_binding("minimum_expression"),
                condition_arg_binding("condition", public_arg="minimum_value"),
                parameter_basis_binding(
                    ("minimum_expression", "condition", "constraint")
                ),
                related_condition_binding(
                    "constraint",
                    condition_kinds=("symbol_constraint",),
                    related_args=("parameter",),
                ),
            ),
        ),
    ),
)

QUADRATIC_PATH_MINIMUM_FAMILY = expand_family_spec(
    _QUADRATIC_PATH_MINIMUM_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
