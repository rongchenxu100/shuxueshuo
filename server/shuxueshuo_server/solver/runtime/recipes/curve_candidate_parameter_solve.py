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
                title_template="将点代入抛物线求参数",
                nav_title_template="代入求参数",
                goal_template="把几何构造得到的点代入抛物线，结合参数范围求出参数。",
                derive_templates=(
                    ("∵", "候选点为 {candidate_points}"),
                    ("计算", "{candidate_substitutions}"),
                    ("∴", "筛选结果为 {candidate_decisions}"),
                ),
                box_templates=("{parameter_result}",),
                role_schema={
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
                title_template="回代参数求点的坐标",
                nav_title_template="回代求点",
                goal_template="把上一步求出的参数直接代回点的坐标。",
                derive_templates=(
                    ("∵", "保留点满足当前曲线条件"),
                    ("计算", "{parameter_equation}"),
                    ("∴", "{parameter_result}"),
                    ("∴", "最终点为 {selected_point}，曲线为 {solved_curve}"),
                ),
                box_templates=("{selected_point}",),
                role_schema={
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
