"""weighted_axis_path_minimum recipe spec."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

from ._spec import (
    MacroTeachingSpec,
    RecipeSpecSource,
    RecipeVisualSpec,
)


SPEC = RecipeSpecSource(
    recipe_id="weighted_axis_path_minimum",
    title="加权轴上路径最值",
    summary=(
        "Resolve a typed two-term weighted path, build the registered internal "
        "right triangle, straighten the linked path, and return its complete "
        "minimum expression with domain-boundary branches represented inside "
        "the expression."
    ),
    method_sequence=("weighted_axis_path_minimum_kernel",),
    execution_strategy="weighted_axis_path_minimum",
    outputs={"minimum_expression": "MinimumExpression"},
    teaching=MacroTeachingSpec(
        teaching_units=(
            TeachingUnitSpec(
                unit_key="weighted_axis_path_minimum/weighted_reduction",
                title_template="构造辅助直角三角形消去路径权重",
                nav_title_template="消去路径权重",
                goal_template="把加权线段转化为同倍率普通线段，得到等价折线路径。",
                derive_templates=(
                    ("作", "{weighted_construction}"),
                    ("∵", "{weighted_equivalence_reason}"),
                    ("∴", "{original_objective}＝{reduced_objective}"),
                ),
                box_templates=("{original_objective}＝{reduced_objective}",),
                role_schema={
                    "weighted_construction": "由权重 profile 确定的辅助直角三角形构造。",
                    "weighted_equivalence_reason": "辅助边与原加权线段的等长或倍率关系。",
                    "original_objective": "题设加权路径。",
                    "reduced_objective": "消去权重后的普通折线路径。",
                },
                role_binder_id="weighted_axis_path_minimum",
            ),
            TeachingUnitSpec(
                unit_key="weighted_axis_path_minimum/domain_minimum",
                title_template="作垂线构造直角三角形求路径最小值",
                nav_title_template="几何求最值",
                goal_template="把普通折线拉直，再作轴上垂线构造特殊直角三角形，逐段计算最短长度并说明边界。",
                derive_templates=(
                    ("∵", "辅助点的轨迹为 {auxiliary_locus}"),
                    ("∴", "{minimum_reason}"),
                    ("∵", "{domain_condition}"),
                    ("∴", "完整最小值为 {minimum_expression}"),
                ),
                box_templates=("最小值为 {minimum_expression}",),
                role_schema={
                    "auxiliary_locus": "辅助点的 verified 合法轨迹。",
                    "minimum_reason": "拉直折线得到的内部最短距离。",
                    "domain_condition": "取等点与边界分支的 verified 定义域说明。",
                    "minimum_expression": "覆盖合法域的完整最小值表达式。",
                },
                role_binder_id="weighted_axis_path_minimum",
            ),
        )
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "weighted_triangle": "内部辅助直角三角形。",
            "auxiliary_locus": "辅助点运动射线。",
            "straightened_path": "拉直后的最短路径。",
        },
        teaching_substep_templates={
            "weighted_reduction": (
                {
                    "component": "AtomicPathMinimumMarker",
                    "context_roles": ["input_curve"],
                    "local_interaction": {
                        "kind": "weighted_axis_motion",
                    },
                    "requires_independent_lesson_step": True,
                },
            ),
            "domain_minimum": (
                {
                    "component": "AtomicPathMinimumMarker",
                    "context_roles": ["input_curve"],
                    "local_interaction": {
                        "kind": "weighted_axis_motion",
                    },
                    "requires_independent_lesson_step": True,
                },
            ),
        },
        role_binder_id="generic_visual",
    ),
)
