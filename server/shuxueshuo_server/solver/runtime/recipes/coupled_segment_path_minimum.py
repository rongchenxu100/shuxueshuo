"""coupled_segment_endpoint_replacement_path_minimum recipe spec."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

from ._spec import (
    MacroTeachingSpec,
    RecipeSpecSource,
    RecipeVisualSpec,
)


SPEC = RecipeSpecSource(
    recipe_id="coupled_segment_endpoint_replacement_path_minimum",
    title="耦合线段端点替换路径最值",
    summary=(
        "Use one source segment relation to replace a coupled moving endpoint "
        "with an existing fixed endpoint, then solve the resulting one-moving-"
        "point path and return both its minimum and attainment state."
    ),
    method_sequence=(
        "coupled_segment_endpoint_replacement_path_minimum_kernel",
    ),
    execution_strategy="coupled_segment_path_minimum",
    outputs={
        "minimum_expression": "MinimumExpression",
        "attainment_point": "Point",
    },
    teaching=MacroTeachingSpec(
        teaching_units=(
            TeachingUnitSpec(
                unit_key=(
                    "coupled_segment_endpoint_replacement_path_minimum/"
                    "endpoint_replacement"
                ),
                title_template="利用线段关系替换耦合端点",
                nav_title_template="端点替换",
                goal_template="用题设线段关系把两动点路径等价化为单动点路径。",
                derive_templates=(
                    ("∵", "{replacement_equality}"),
                    ("∴", "{original_objective}＝{reduced_objective}"),
                ),
                box_templates=("{original_objective}＝{reduced_objective}",),
                role_schema={
                    "replacement_equality": "题设关系证明的已有端点替换。",
                    "original_objective": "题设两动点路径。",
                    "reduced_objective": "替换后的单动点路径。",
                },
                role_binder_id="coupled_segment_path_minimum",
            ),
            TeachingUnitSpec(
                unit_key=(
                    "coupled_segment_endpoint_replacement_path_minimum/"
                    "reflection_minimum"
                ),
                title_template="确定{moving_point}的轨迹并拉直折线",
                nav_title_template="轨迹与最短路径",
                goal_template="在保留动点的合法轨迹上拉直折线，求最小值和取等位置。",
                derive_templates=(
                    ("∵", "{moving_point} 的轨迹为 {moving_locus}"),
                    ("作", "{reflection_construction}"),
                    ("∴", "{straightened_path}"),
                    ("∴", "最小值为 {minimum_expression}"),
                    ("∴", "在 {attainment_point} 处取得"),
                ),
                box_templates=(
                    "最小值为 {minimum_expression}",
                    "取等点为 {attainment_point}",
                ),
                role_schema={
                    "moving_point": "端点替换后保留下来的动点。",
                    "moving_locus": "该动点的合法线段轨迹。",
                    "reflection_construction": "verified evidence 中的反射构造。",
                    "straightened_path": "反射后拉直的路径关系。",
                    "minimum_expression": "路径最小值表达式。",
                    "attainment_point": "原题动点的取等位置。",
                },
                role_binder_id="coupled_segment_path_minimum",
            ),
        )
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "endpoint_replacement": "题设关系对应的已有端点替换。",
            "moving_locus": "保留动点的合法线段轨迹。",
            "straightened_path": "内部反射后得到的最短直线路径。",
            "attainment_point": "最短状态下原题动点的位置。",
        },
        teaching_substep_templates={
            "endpoint_replacement": (
                {
                    "component": "EquivalentSegmentMarker",
                    "requires_independent_lesson_step": True,
                },
            ),
            "reflection_minimum": (
                {
                    "component": "AtomicPathMinimumMarker",
                    "requires_independent_lesson_step": True,
                },
            ),
        },
        role_binder_id="generic_visual",
    ),
)
