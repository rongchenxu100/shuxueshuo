"""equal_length_ray_path_reduction recipe spec."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

from ._spec import (
    MacroTeachingSpec,
    RecipeSpecSource,
    RecipeVisualSpec,
)


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
    teaching=MacroTeachingSpec(
        teaching_units=(
            TeachingUnitSpec(
                unit_key="equal_length_ray_path_reduction/path_reduction",
                title_template="构造等长辅助点，把两动点路径化为单动点路径",
                nav_title_template="两动点转化",
                goal_template="利用等长条件构造辅助点，证明原路径可等价替换。",
                derive_templates=(
                    ("作", "{auxiliary_construction}"),
                    ("∵", "{congruence_facts}"),
                    ("∴", "{replacement_equality}"),
                    ("∴", "{original_objective}＝{reduced_objective}"),
                ),
                box_templates=("{original_objective}＝{reduced_objective}",),
                role_schema={
                    "auxiliary_construction": "在题设射线上作等长辅助点的 verified 构造。",
                    "congruence_facts": "用于证明对应三角形全等的等长与夹角事实。",
                    "replacement_equality": "全等后得到的距离替换关系。",
                    "original_objective": "题设两动点路径。",
                    "reduced_objective": "替换后的单动点路径。",
                },
                role_binder_id="equal_length_ray_path_reduction",
            ),
            TeachingUnitSpec(
                unit_key="equal_length_ray_path_reduction/minimum_by_segment",
                title_template="在单动点路径中求最小值",
                nav_title_template="单动点路径最值",
                goal_template="在等价路径中利用两点之间线段最短得到最小值。",
                derive_templates=(
                    ("∵", "{original_objective}＝{reduced_objective}"),
                    ("∴", "{minimum_reason}"),
                    ("∴", "路径最小值为 {minimum_expression}"),
                ),
                box_templates=("路径最小值为 {minimum_expression}",),
                role_schema={
                    "original_objective": "题设两动点路径。",
                    "reduced_objective": "降维后的单动点路径。",
                    "minimum_reason": "由 verified winner 给出的直线最短依据。",
                    "minimum_expression": "路径最小值表达式。",
                },
                role_binder_id="equal_length_ray_path_reduction",
            ),
        )
    ),
    visual=RecipeVisualSpec(
        role_schema={
            "congruent_triangles": "由等长条件和共线关系得到的一对全等三角形。",
            "replaced_segment": "原路径中被替换的距离段。",
            "replacement_segment": "替换后的等长距离段。",
            "common_path_segment": "路径转化前后共同保留的距离段。",
            "construction_lines": "用于说明共线和辅助点构造的低调辅助线。",
        },
        teaching_substep_templates={
            "path_reduction": (
                {
                    "component": "CongruentTriangleMarker",
                    "requires_independent_lesson_step": True,
                },
                {"component": "EquivalentSegmentMarker"},
            ),
            "minimum_by_segment": (
                {
                    "component": "PathMinimumTriangleMarker",
                    "requires_independent_lesson_step": True,
                },
                {"component": "AuxiliaryRayGuideMarker"},
            ),
        },
        teaching_substep_timeline_templates={
            "path_reduction": (
                {"component": "EqualLengthPointConstruction"},
                {"component": "CongruentTriangleReveal"},
                {"component": "EquivalentSegmentEmphasis"},
                {"component": "PathReplacementReveal"},
            ),
            "minimum_by_segment": (
                {"component": "MovingPointSweepToMinimum"},
                {"component": "MinimumSegmentReveal"},
            ),
        },
        role_binder_id="equal_length_ray_path_reduction",
    ),
)
