"""broken_path_straightening_minimum_expression recipe spec."""

from __future__ import annotations

from ._spec import RecipeExplanationSpec, RecipeSpecSource, RecipeVisualSpec


SPEC = RecipeSpecSource(
    recipe_id="broken_path_straightening_minimum_expression",
    title="将军饮马计算最小值表达式",
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
            "source_point": "被对称的固定端点。",
            "reflected_point": "把其中一个固定端点关于动点轨迹线对称得到的点。",
            "reflected_point_coordinate": "对称点坐标。",
            "other_fixed_point": "拉直后线段的另一个端点。",
            "transformed_path": "等价后的单动点折线路径。",
            "straightened_path": "拉直后的路径。",
            "segment_equality": "由对称得到的线段等量关系。",
            "straightened_segment": "拉直后用于计算最短距离的线段。",
            "minimum_expression": "最小值表达式。",
            "distance_formula": "最短距离或最小值的计算式。",
        },
        student_title_template="将军饮马计算最小值表达式",
        student_nav_title_template="将军饮马算最小值",
        student_intent_template=(
            "把单动点折线路径拉直成一条线段，用两点之间线段最短求最小值。"
        ),
        proof_outline_templates=(
            "∵{moving_point} 在直线 {moving_locus} 上运动。",
            "∴作 {source_point} 关于 {moving_locus} 的对称点 {reflected_point}，则 {segment_equality}。",
            "∴{transformed_path}={straightened_path}。",
            "∴当 {reflected_point}、{moving_point}、{other_fixed_point} 共线时，路径取得最小值 {straightened_segment}。",
            "∴{straightened_segment}={minimum_expression}。",
        ),
        recommended_lesson_splits=(
            "说明拉直思路。",
            "计算最短线段或最小值表达式。",
        ),
        allowed_llm_completion=(
            "可以解释“将军饮马”为什么能把折线变直线。",
            "不能改变 recipe 已给出的固定点、动点轨迹或最小值表达式。",
        ),
        role_binder_id="broken_path_straightening_minimum_expression",
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "moving_point": "折线路径中的动点。",
            "moving_locus": "动点所在轨迹线。",
            "source_point": "被对称的固定端点。",
            "reflected_point": "对称得到的拉直辅助点。",
            "other_fixed_point": "拉直后线段的另一个端点。",
            "minimum_segment": "拉直后用于计算最小值的线段。",
        },
        teaching_substep_templates={
            "straightening_minimum": (
                {"component": "BrokenPathStraighteningMarker"},
            ),
        },
        role_binder_id="broken_path_straightening_minimum_expression",
    ),
)
