"""equal_length_ray_path_reduction recipe spec."""

from __future__ import annotations

from ._spec import RecipeExplanationSpec, RecipeSpecSource, TeachingSubstepSpec


SPEC = RecipeSpecSource(
    recipe_id="equal_length_ray_path_reduction",
    title="等长射线路径降维",
    summary=(
        "Given a segment moving point and a ray moving point constrained by equal "
        "lengths from a common anchor, construct an auxiliary point on the ray and "
        "reduce a two-moving-point path sum to a single moving-point or fixed "
        "distance minimum."
    ),
    method_sequence=("equal_length_ray_point", "distance_between_points"),
    execution_strategy="equal_length_ray_path_reduction",
    outputs={"minimum_expression": "MinimumExpression"},
    explanation=RecipeExplanationSpec(
        role_schema={
            "anchor": "等长关系的公共端点，也是射线端点。",
            "segment_moving_point": "在线段上运动的点。",
            "ray_moving_point": "在射线上运动的点。",
            "segment_reference_point": "线段另一端点，用来确定辅助点的等长半径。",
            "ray_direction_point": "确定射线方向的已知点。",
            "fixed_point": "原路径中连接线段动点的固定点。",
            "auxiliary_point": "讲解中构造在射线上的等长辅助点。",
            "original_replace_segment": "原路径中需要被替换的距离段。",
            "replacement_segment": "替换后同一动点到辅助点的距离段。",
            "original_path": "题设路径和。",
            "reduced_path": "替换后的路径和。",
            "minimum_segment": "取最小值时对应的直线距离。",
        },
        student_intent_template=(
            "通过构造等长辅助点，把两动点路径中的一段距离替换成同一动点到"
            "辅助点的距离，从而把路径最值降维。"
        ),
        proof_outline_templates=(
            "在 {ray_name} 上构造 {auxiliary_point}，使 {anchor}{auxiliary_point} = {anchor}{segment_reference_point}。",
            "因为 {segment_reference_point}、{anchor}、{segment_moving_point} 共线，{ray_moving_point}、{anchor}、{auxiliary_point} 共线，所以对应夹角由同两条直线/射线确定而相等。",
            "又有 {anchor}{ray_moving_point} = {anchor}{segment_moving_point}，可证明对应三角形全等。",
            "因此 {original_replace_segment} = {replacement_segment}。",
            "所以 {original_path} = {reduced_path}。",
        ),
        recommended_lesson_splits=(
            "构造辅助点并证明距离替换。",
            "在降维后的单动点路径中，用最短线段得到最小值表达式。",
        ),
        teaching_substep_specs=(
            TeachingSubstepSpec(
                substep_id="path_reduction",
                title="构造等长辅助点，把两动点路径转化为单动点路径",
                focus="构造辅助点、证明距离替换，并得到等价的单动点路径。",
                preferred_method_ids=("equal_length_ray_point",),
            ),
            TeachingSubstepSpec(
                substep_id="minimum_by_segment",
                title="利用两点之间线段最短，求路径最小值表达式",
                focus="在路径已经降维后，用最短线段计算最小值表达式。",
                preferred_method_ids=("distance_between_points",),
            ),
        ),
        allowed_llm_completion=(
            "可以补充为什么想到在射线上构造等长辅助点。",
            "可以把全等证明写成初中生能读懂的两三句话。",
            "如果三角形名称没有完全绑定，只能用“对应三角形”这类谨慎表达。",
        ),
        role_binder_id="equal_length_ray_path_reduction",
    ),
)
