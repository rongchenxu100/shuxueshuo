"""Teaching and visual contract for the direct right-angle construction Macro."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

from ._spec import MacroTeachingSpec, RecipeSpecSource, RecipeVisualSpec


SPEC = RecipeSpecSource(
    recipe_id="right_angle_equal_length_construct_and_select",
    title="直角等腰构造并筛选点",
    summary=(
        "Construct both points permitted by one right-angle equal-length relation, "
        "then select the unique point allowed by the verified direction, quadrant, "
        "or parameter constraint."
    ),
    method_sequence=(
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
    ),
    execution_strategy="right_angle_construct_select",
    outputs={"selected_target_point": "Point"},
    teaching=MacroTeachingSpec(
        teaching_units=(
            TeachingUnitSpec(
                unit_key=(
                    "right_angle_equal_length_construct_and_select/"
                    "construct_candidates"
                ),
                title_template="由直角等腰关系构造候选点",
                nav_title_template="构造候选点",
                goal_template=(
                    "利用直角等腰关系和坐标投影，完整构造两个候选点。"
                ),
                derive_templates=(
                    ("∵", "{construction_condition}"),
                    ("作", "将已知边分别顺、逆时针旋转 90°"),
                    ("∴", "候选点为 {candidate_points}"),
                ),
                box_templates=("{candidate_points}",),
                role_schema={
                    "construction_condition": "直角顶点、已知端点及等长关系。",
                    "candidate_points": "经验证的两个旋转候选点。",
                },
                role_binder_id="right_angle_equal_length_construct_and_select",
            ),
            TeachingUnitSpec(
                unit_key=(
                    "right_angle_equal_length_construct_and_select/"
                    "select_candidate"
                ),
                title_template="根据题设条件确定唯一候选点",
                nav_title_template="筛选唯一点",
                goal_template=(
                    "逐一判断两个候选点是否满足题设方向或范围，保留唯一合法点。"
                ),
                derive_templates=(
                    ("∵", "筛选条件为 {selection_condition}"),
                    ("计算", "{candidate_decisions}"),
                    ("∴", "所求点为 {selected_point}"),
                ),
                box_templates=("{selected_point}",),
                role_schema={
                    "selection_condition": "实际用于筛选旋转分支的题设条件。",
                    "candidate_decisions": "各候选点的保留或排除理由。",
                    "selected_point": "筛选出的唯一目标点。",
                },
                role_binder_id="right_angle_equal_length_construct_and_select",
            ),
        )
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "anchor": "直角顶点。",
            "reference": "已知直角边端点。",
            "candidates": "顺、逆时针旋转候选点。",
            "selected_point": "最终保留的候选点。",
        },
        teaching_substep_templates={
            "construct_candidates": (
                {
                    "component": "QuadraticContextMarker",
                    "persistence": "carry_forward",
                },
                {
                    "component": "RightAngleEqualLengthCandidatesMarker",
                    "input_roles": ["anchor", "reference"],
                    "output_role": "candidates",
                    "requires_independent_lesson_step": True,
                    "persistence": "carry_forward",
                },
            ),
            "select_candidate": (
                {
                    "component": "CandidateSelectionMarker",
                    "requires_independent_lesson_step": True,
                    "persistence": "carry_forward",
                },
            ),
        },
        role_binder_id="right_angle_equal_length_construct_and_select",
    ),
)
