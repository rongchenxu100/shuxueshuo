"""weighted_axis_path_minimum recipe spec."""

from __future__ import annotations

from ._spec import RecipeExplanationSpec, RecipeSpecSource, RecipeVisualSpec


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
    explanation=RecipeExplanationSpec(
        role_schema={
            "original_objective": "题设给出的加权距离和。",
            "weighted_triangle": "把权重线段换成同倍率普通线段的辅助直角三角形。",
            "auxiliary_locus": "辅助点随原轴上动点形成的合法射线。",
            "attainment_condition": "直线垂足对应原动点仍在定义域内的条件。",
            "boundary_minimum_expression": "垂足越界时由动点定义域边界给出的分支。",
            "minimum_expression": "覆盖合法域的完整最小值表达式。",
        },
        student_title_template="构造辅助三角形，化加权路径为最短折线",
        student_nav_title_template="加权路径最值",
        student_intent_template=(
            "用辅助直角三角形消去路径中的权重，再拉直折线，并检查"
            "垂足是否对应合法动点；必要时保留定义域边界分支。"
        ),
        proof_outline_templates=(
            "构造 {weighted_triangle}，把 {original_objective} 化为同倍率普通折线。",
            "辅助点沿 {auxiliary_locus} 运动，拉直后得到内部最短距离。",
            "检查 {attainment_condition}；越界时使用 {boundary_minimum_expression}。",
            "因此完整最小值表达式为 {minimum_expression}。",
        ),
        recommended_lesson_splits=(
            "构造辅助三角形并证明路径等价。",
            "拉直路径并验证取等点与定义域。",
        ),
        allowed_llm_completion=(
            "可以把 verified evidence 改写为学生易读的几何证明。",
            "不得自造辅助点身份、路径权重、定义域分支或最小值。",
        ),
        role_binder_id="weighted_axis_path_minimum",
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "weighted_triangle": "内部辅助直角三角形。",
            "auxiliary_locus": "辅助点运动射线。",
            "straightened_path": "拉直后的最短路径。",
        },
        teaching_substep_templates={
            "path_minimum": (
                {"component": "AtomicPathMinimumMarker"},
            ),
        },
        role_binder_id="generic_visual",
    ),
)
