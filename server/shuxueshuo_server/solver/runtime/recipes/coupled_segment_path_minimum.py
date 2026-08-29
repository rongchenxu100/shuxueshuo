"""coupled_segment_endpoint_replacement_path_minimum recipe spec."""

from __future__ import annotations

from ._spec import RecipeExplanationSpec, RecipeSpecSource, RecipeVisualSpec


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
    explanation=RecipeExplanationSpec(
        role_schema={
            "original_objective": "题设要求最小化的两动点路径。",
            "reduced_objective": "用题设线段关系替换端点后的单动点路径。",
            "moving_point": "端点替换后保留下来的原题动点。",
            "attainment_point": "原路径取得最小值时该动点的位置。",
            "minimum_strategy": "经过验证的折线拉直策略。",
            "minimum_expression": "原路径的最小值表达式。",
        },
        student_title_template="先用线段关系替换端点，再求最短路径",
        student_nav_title_template="耦合路径最值",
        student_intent_template=(
            "利用题设线段关系把两动点路径等价化为单动点路径，"
            "再拉直折线，得到最小值和原题动点的取等位置。"
        ),
        proof_outline_templates=(
            "由题设线段关系，把 {original_objective} 等价化为 {reduced_objective}。",
            "确定 {moving_point} 的合法轨迹，并使用 {minimum_strategy} 拉直折线。",
            "因此最小值为 {minimum_expression}，在 {attainment_point} 处取得。",
        ),
        recommended_lesson_splits=(
            "证明原路径与单动点路径等价。",
            "拉直路径并恢复原题动点的取等状态。",
        ),
        allowed_llm_completion=(
            "可以把 verified evidence 中的等价关系改写为学生易读语言。",
            "不得自造辅助点、路径等价关系、最小值或取等点。",
        ),
        role_binder_id="coupled_segment_path_minimum",
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "endpoint_replacement": "题设关系对应的已有端点替换。",
            "moving_locus": "保留动点的合法线段轨迹。",
            "straightened_path": "内部反射后得到的最短直线路径。",
            "attainment_point": "最短状态下原题动点的位置。",
        },
        teaching_substep_templates={
            "path_minimum": (
                {"component": "EquivalentSegmentMarker"},
                {"component": "AtomicPathMinimumMarker"},
            ),
        },
        role_binder_id="generic_visual",
    ),
)
