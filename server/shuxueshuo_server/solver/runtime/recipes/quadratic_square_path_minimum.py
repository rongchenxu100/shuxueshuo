"""quadratic_square_path_minimum recipe spec."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

from ._spec import (
    MacroTeachingSpec,
    RecipeExplanationSpec,
    RecipeSpecSource,
    RecipeVisualSpec,
)


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
    teaching=MacroTeachingSpec(
        teaching_units=(
            TeachingUnitSpec(
                unit_key="quadratic_square_path_minimum/path_reduction",
                title_template="利用正方形关系化简路径",
                nav_title_template="化简路径",
                goal_template="用中点、中心和正方形等长关系，把原路径化为单动点路径。",
                derive_templates=(
                    ("∵", "{square_equalities}"),
                    ("∴", "{path_reduction_equality}"),
                    ("∴", "{original_objective}＝{reduced_objective}"),
                ),
                box_templates=("{original_objective}＝{reduced_objective}",),
                role_schema={
                    "square_equalities": "路径化简所用的中点、中心与正方形等长事实。",
                    "path_reduction_equality": "由这些等长事实直接得到的局部路径等式。",
                    "original_objective": "题设要求最小化的原路径。",
                    "reduced_objective": "化简后的单动点路径。",
                },
                role_binder_id="quadratic_square_path_minimum",
            ),
            TeachingUnitSpec(
                unit_key="quadratic_square_path_minimum/reflection_minimum",
                title_template="确定{moving_point}的轨迹并用反射求最短路径",
                nav_title_template="轨迹与反射",
                goal_template="确定动点轨迹，构造对称点拉直折线，并给出最小值与取等位置。",
                derive_templates=(
                    ("∵", "{moving_point} 的轨迹为 {moving_locus}"),
                    ("作", "关于该轨迹构造 {reflected_point}"),
                    ("∵", "{segment_equality}"),
                    ("∴", "{straightened_path}"),
                    ("∴", "最小值为 {minimum_expression}"),
                    ("∴", "在 {attainment_point} 处取得"),
                ),
                box_templates=(
                    "最小值为 {minimum_expression}",
                    "取等点为 {attainment_point}",
                ),
                role_schema={
                    "moving_point": "化简后路径中唯一的动点。",
                    "moving_locus": "由二次函数与正方形关系确定的动点轨迹。",
                    "reflected_point": "为拉直折线构造的对称点及其坐标。",
                    "segment_equality": "反射给出的对应线段等长关系。",
                    "straightened_path": "反射后拉直的路径关系。",
                    "minimum_expression": "路径最小值表达式。",
                    "attainment_point": "使路径取得最小值的动点位置。",
                },
                role_binder_id="quadratic_square_path_minimum",
            ),
        )
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
