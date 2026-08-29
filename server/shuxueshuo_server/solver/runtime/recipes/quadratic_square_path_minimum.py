"""quadratic_square_path_minimum recipe spec."""

from __future__ import annotations

from ._spec import RecipeExplanationSpec, RecipeSpecSource, RecipeVisualSpec


SPEC = RecipeSpecSource(
    recipe_id="quadratic_square_path_minimum",
    title="二次函数与正方形中的路径最小值",
    summary=(
        "Use the square midpoint/center relations to reduce the given path to "
        "one moving point, derive its locus from the quadratic state, and "
        "straighten the resulting broken path to obtain the minimum and its "
        "attainment point."
    ),
    method_sequence=("quadratic_square_path_minimum_kernel",),
    execution_strategy="quadratic_square_path_minimum",
    outputs={
        "minimum_expression": "MinimumExpression",
        "attainment_point": "Point",
    },
    explanation=RecipeExplanationSpec(
        role_schema={
            "original_objective": "题设要求最小化的原路径。",
            "reduced_objective": "利用正方形中点、中心关系化简后的单动点路径。",
            "moving_point": "化简后路径中唯一的动点。",
            "attainment_point": "使路径取得最小值时动点的位置。",
            "minimum_strategy": "经过验证的折线拉直最值策略。",
            "minimum_expression": "路径的最小值表达式。",
        },
        student_title_template="正方形关系降维，再用将军饮马求最短路径",
        student_nav_title_template="正方形路径最值",
        student_intent_template=(
            "先利用正方形的中点和中心关系把原路径化为单动点折线，"
            "再把折线拉直，得到最小值及其达到位置。"
        ),
        proof_outline_templates=(
            "由正方形的中点、中心和等边关系，把 {original_objective} 等价化为 {reduced_objective}。",
            "根据二次函数状态确定 {moving_point} 的运动轨迹。",
            "使用 {minimum_strategy} 拉直折线，并检查达到点仍在合法轨迹上。",
            "因此最小值为 {minimum_expression}，在 {attainment_point} 处取得。",
        ),
        recommended_lesson_splits=(
            "利用正方形关系完成路径降维。",
            "确定动点轨迹并拉直折线求最小值。",
        ),
        allowed_llm_completion=(
            "可以把 verified evidence 中的等价关系改写成初中生易读的语言。",
            "不得自造点名、轨迹、对称点、最小值或达到点。",
        ),
        role_binder_id="quadratic_square_path_minimum",
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "square_reduction": "正方形中点、中心关系对应的等价路径替换。",
            "moving_locus": "化简后唯一动点的轨迹。",
            "straightened_path": "反射后得到的最短直线路径。",
            "attainment_point": "最短直线与动点轨迹的合法交点。",
        },
        teaching_substep_templates={
            "path_minimum": (
                {"component": "AtomicSquarePathReductionMarker"},
                {"component": "AtomicPathMinimumMarker"},
            ),
        },
        role_binder_id="generic_visual",
    ),
)
