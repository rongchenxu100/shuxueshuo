"""Quadratic-function square path minimum family.

The LLM-facing path mechanism is one atomic Macro.  Square reduction, moving
point construction, locus propagation, straightening and attainment remain
runtime-owned and never become authored Plan steps.
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.capability_packs import (
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
from shuxueshuo_server.solver.family.common_binding_rules import (
    canonical_x_binding,
    condition_arg_binding,
    quadratic_public_state_binding,
    quadratic_state_prep_invocations,
    previous_output_identity_binding,
    public_arg_binding,
    related_condition_binding,
    source_object_identity_binding,
)
from shuxueshuo_server.solver.family.models import (
    FamilyMatchRule,
    FamilySourceGoalContractSpec,
    FamilySourceRequirementSpec,
    FunctionalOutputTargetSelectorSpec,
    MethodBindingRuleSpec,
    SolverFamilySpec,
    expand_family_spec,
)


_QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticSquareReflectionPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("path-minimum",),
        problem_types=("quadratic_square_reflection_path_minimum",),
    ),
    title="二次函数正方形路径最值",
    description=(
        "在当前二次函数状态下，利用正方形、中点、中心和轴成员关系，"
        "原子地完成路径降维、轨迹、拉直与达到点求解。"
    ),
    use_when=(
        "题面明确给出二次函数、正方形和路径最值目标，且正方形的中点、"
        "中心或邻接关系决定路径等价变换。"
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
            "题面必须明确给出正方形事实。",
            source_authority="printed_source",
            printed_source_markers=("正方形",),
        ),
    ),
    source_goal_contracts=(
        FamilySourceGoalContractSpec(
            selector_id="square_curve_point_candidates",
            expected_value_type="PointList",
            description="同一正方形另一顶点落抛物线时，目标顶点为候选集合。",
        ),
    ),
    do_not_use_when=(
        "题面没有二次函数或明确正方形。",
        "正方形不参与目标路径的等价变换。",
        "路径仍含两个独立动点、非直线轨迹或非单位权重。",
    ),
    common_goal_types=(
        "derive_parabola",
        "derive_vertex_point",
        "derive_square_constrained_point_candidates",
        "derive_square_path_minimum_expression",
        "derive_parameter",
        "derive_extremal_point",
    ),
    strategy_principles=(
        "每个 capability 调用是可执行数学动作；Macro 在 Plan 与 Retry 中始终是一个原子 step。",
        "先用当前问约束把抛物线化成所需的当前状态，再调用 quadratic_square_path_minimum。",
        "quadratic_square_path_minimum 只填写 parabola、path_minimum_target 和 square；中点、中心、轴成员事实以及边起点、轴上点、路径动点和固定端点均由代码从结构化 ProblemIR 唯一解析。",
        "轴上点的对象身份来自 axis_membership；其坐标由当前抛物线的对称轴在 Macro 内推导，Planner 不单独构造或传入该点。",
        "Macro 内部完成正方形降维、参数化动点、直线轨迹、折线拉直、合法域与达到性验证，只公开 minimum_expression 和 attainment_point。attainment_point 的正方形动点身份由代码绑定，Planner 不设置 output_targets。",
        "题设给出最小值时，用 minimum_expression 反求二次函数参数；需要最终正方形顶点时，通过 StepResultRef 消费 attainment_point，再与已定值相邻点使用 square_adjacent_vertex_from_side。",
        "不得把正方形降维、轨迹求解、内部反射或取等恢复拆成公开步骤；这些证明必须由原子 Macro 一次完成。",
        "网页讲解与图形从 Macro 的 verified evidence 展开，不要求 Planner 重写内部证明步骤。",
    ),
    base_packs=(
        "quadratic_core",
        "parameter_solving_core",
        "coordinate_geometry_core",
    ),
    mechanism_packs=("quadratic_square_path_minimum_core",),
    method_ids=(
        "quadratic_from_constraints",
        "quadratic_vertex_point",
        "quadratic_axis_parameterized_point",
        "square_adjacent_vertex_from_side",
        "point_candidates_from_curve_point_condition",
        "evaluate_point_at_parameter",
        "parameter_from_expression_value",
    ),
    method_binding_rules=(
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
                previous_output_identity_binding("target", output_name="point"),
            ),
            prep_invocations=quadratic_state_prep_invocations("parabola"),
        ),
        MethodBindingRuleSpec(
            method_id="square_adjacent_vertex_from_side",
            functional_output_names=(("point", "adjacent_vertex"),),
            input_bindings=(
                public_arg_binding("side_start"),
                public_arg_binding("side_end"),
                condition_arg_binding("square_condition", public_arg="square"),
                previous_output_identity_binding(
                    "target",
                    output_name="adjacent_vertex",
                ),
                source_object_identity_binding(
                    "side_start",
                    input_name="side_start_ref",
                    required=False,
                ),
                source_object_identity_binding(
                    "side_end",
                    input_name="side_end_ref",
                    required=False,
                ),
                source_object_identity_binding(
                    "parameter_value",
                    input_name="parameter",
                    required=False,
                ),
                related_condition_binding(
                    "parameter_constraint",
                    condition_kinds=("symbol_constraint",),
                    related_args=("parameter",),
                    required=False,
                ),
            ),
        ),
        MethodBindingRuleSpec(
            method_id="point_candidates_from_curve_point_condition",
            input_bindings=(
                public_arg_binding("target_point"),
                public_arg_binding("curve_point"),
                quadratic_public_state_binding("parabola"),
                canonical_x_binding(),
            ),
            prep_invocations=quadratic_state_prep_invocations("parabola"),
        ),
    ),
)


QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY = expand_family_spec(
    _QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)


__all__ = ["QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY"]
