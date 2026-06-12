"""broken_path_straightening_minimum_expression recipe spec."""

from __future__ import annotations

from ._spec import RecipeExplanationSpec, RecipeSpecSource


SPEC = RecipeSpecSource(
    recipe_id="broken_path_straightening_minimum_expression",
    title="将军饮马折线最值",
    summary=(
        "Given a one-moving-point broken path and a moving locus, straighten the "
        "path, select the valid straightening scheme, and compute the minimum "
        "distance expression."
    ),
    method_sequence=(
        "broken_path_straightening_candidates",
        "select_straightening_candidate",
        "distance_between_points",
    ),
    execution_strategy="broken_path_straightening_minimum_expression",
    outputs={
        "minimum_expression": "MinimumExpression",
        "minimum_point_1": "Point",
        "minimum_point_2": "Point",
    },
    explanation=RecipeExplanationSpec(
        role_schema={
            "moving_point": "折线路径中的动点。",
            "moving_locus": "动点所在直线或轨迹。",
            "fixed_points": "折线路径两端的固定点。",
            "straightened_segment": "拉直后用于计算最短距离的线段。",
            "minimum_expression": "最小值表达式。",
        },
        student_intent_template=(
            "把单动点折线路径拉直成一条线段，用两点之间线段最短求最小值。"
        ),
        proof_outline_templates=(
            "先确定动点所在的轨迹，再把折线路径的一侧作对称或等价平移。",
            "折线长度转化为一条直线段长度。",
            "当动点落在这条直线段与轨迹的交点位置时，路径取得最小值。",
        ),
        recommended_lesson_splits=(
            "说明拉直思路。",
            "计算最短线段或最小值表达式。",
        ),
        allowed_llm_completion=(
            "可以解释“将军饮马”为什么能把折线变直线。",
            "不能改变 recipe 已给出的固定点、动点轨迹或最小值表达式。",
        ),
    ),
)
