"""Teaching and visual contract for candidate filtering and curve closure."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

from ._spec import MacroTeachingSpec, RecipeSpecSource, RecipeVisualSpec


SPEC = RecipeSpecSource(
    recipe_id="curve_candidate_parameter_solve",
    title="曲线候选点筛选并反求参数",
    summary=(
        "Filter materialized geometric point candidates using a parameterized "
        "curve and verified constraints, then solve the unique parameter and "
        "publish the selected point and closed curve state."
    ),
    method_sequence=(
        "filter_point_candidates_by_quadratic_curve",
        "parameter_from_curve_point_on_quadratic",
    ),
    execution_strategy="curve_candidate_parameter_solve",
    outputs={
        "selected_curve_point": "Point",
        "parameter_value": "ParameterValue",
        "solved_parabola": "Parabola",
    },
    teaching=MacroTeachingSpec(
        teaching_units=(
            TeachingUnitSpec(
                unit_key="curve_candidate_parameter_solve/filter_candidates",
                title_template="代入抛物线筛选{target_label}并求参数",
                nav_title_template="筛选{target_label}并求参",
                goal_template=(
                    "把前一步得到的两个{target_label}位置分别代入抛物线，"
                    "结合参数范围判断取舍并求出参数。"
                ),
                derive_templates=(
                    ("∵", "候选点为 {candidate_points}"),
                    ("计算", "{candidate_substitutions}"),
                    ("∴", "筛选结果为 {candidate_decisions}"),
                ),
                box_templates=("{parameter_result}",),
                role_schema={
                    "target_label": "待筛选点的学生名称。",
                    "candidate_points": "前序几何构造产生的候选点。",
                    "candidate_substitutions": "每个候选点代入当前曲线得到的方程。",
                    "candidate_decisions": "各分支的保留或排除理由。",
                    "selected_point": "曲线条件保留的唯一候选点。",
                    "parameter_result": "结合范围筛选后的唯一参数值。",
                },
                role_binder_id="curve_candidate_parameter_solve",
            ),
            TeachingUnitSpec(
                unit_key=(
                    "curve_candidate_parameter_solve/solve_parameter_and_curve"
                ),
                title_template="回代参数确定{target_label}的坐标",
                nav_title_template="回代求{target_label}",
                goal_template=(
                    "把上一步求出的参数同时代回点与抛物线，"
                    "确认已知点和最终点都在同一条确定的曲线上。"
                ),
                derive_templates=(
                    ("∵", "保留点满足当前曲线条件"),
                    ("计算", "{parameter_equation}"),
                    ("∴", "{parameter_result}"),
                    ("∴", "最终点为 {selected_point}，曲线为 {solved_curve}"),
                ),
                box_templates=("{selected_point}",),
                role_schema={
                    "target_label": "最终点的学生名称。",
                    "parameter_equation": "由保留点代入曲线得到的参数方程。",
                    "parameter_result": "筛选后的唯一参数值。",
                    "selected_point": "回代参数后的最终点。",
                    "solved_curve": "回代参数后的曲线。",
                },
                role_binder_id="curve_candidate_parameter_solve",
            ),
        )
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "candidates": "进入曲线筛选的候选点。",
            "selected_point": "唯一保留并闭合后的点。",
            "curve": "参数求解前后的曲线。",
        },
        teaching_substep_templates={
            "filter_candidates": (
                {
                    "component": "CurveCandidateFilterMarker",
                    "requires_independent_lesson_step": True,
                    "persistence": "step_only",
                },
            ),
            "solve_parameter_and_curve": (
                {
                    "component": "SolvedCurveCandidateMarker",
                    "requires_independent_lesson_step": True,
                    "persistence": "carry_forward",
                },
            ),
        },
        role_binder_id="curve_candidate_parameter_solve",
    ),
)
