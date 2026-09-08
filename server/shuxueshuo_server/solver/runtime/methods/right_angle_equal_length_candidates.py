"""right_angle_equal_length_candidates 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodVisualSpec, TeachingUnitSpec

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


class RightAngleEqualLengthCandidatesMethod:
    """由直角等腰条件列出未知直角边端点的两个候选。

    输入语义：

    - ``anchor``：直角顶点；
    - ``reference``：已知直角边的另一个端点；
    - ``target``：待求点引用，只用于命名和 trace；

    该 method 只做旋转候选生成，不根据象限、曲线或参数范围筛选。筛选逻辑必须
    由后续 method 显式接收题设条件后完成。

    ``anchor`` 和 ``reference`` 可以包含符号参数。method 会按旋转公式直接得到
    含参候选点，例如已知端点是 ``(0, -b-2)`` 时，候选点坐标也会保留 ``b``。
    后续再由象限、曲线或参数约束筛选。
    """

    method_id = "right_angle_equal_length_candidates"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        """执行两种 90° 旋转，并返回候选点列表。"""
        anchor: Point = inputs["anchor"]
        reference: Point = inputs["reference"]
        target: PointRef = inputs["target"]
        candidates = rotated_equal_length_candidates(kernel, anchor, reference)
        dist_known = kernel.distance_squared(anchor, reference)
        checks: list[CheckResult] = []
        for index, candidate in enumerate(candidates, start=1):
            dist_derived = kernel.distance_squared(anchor, candidate)
            dot = dot_from_origin(anchor, reference, candidate)
            candidate_display = f"{target.name}({_fmt_point(candidate, kernel)})"
            checks.extend(
                [
                    CheckResult(
                        name=f"candidate_{index}_right_equal_length",
                        status="passed" if sp.simplify(dist_known - dist_derived) == 0 else "failed",
                        detail=f"候选位置 {candidate_display} 与已知直角边等长",
                    ),
                    CheckResult(
                        name=f"candidate_{index}_right_angle",
                        status="passed" if sp.simplify(dot) == 0 else "failed",
                        detail=f"候选位置 {candidate_display} 与已知直角边垂直",
                    ),
                ]
            )
        trace = [
            DerivationStep(
                title=f"由直角等腰条件列出 {target.name} 候选点",
                goal=f"列出 {target.name} 的候选坐标",
                reason="直角等腰三角形的另一条直角边可由已知直角边顺、逆时针旋转 90° 得到。",
                calculation=_fmt_point_candidates(target.name, candidates, kernel),
                conclusion=f"{target.name} 有 {len(candidates)} 个候选点",
                method_id=self.method_id,
            )
        ]
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "candidates": TypedValue(
                    "PointList",
                    candidates,
                    locked=False,
                    source=self.method_id,
                ),
                "construction_evidence": TypedValue(
                    "Condition",
                    {
                        "kind": "right_angle_equal_length_rotation",
                        "target": target.name,
                        "anchor": tuple(kernel.sstr(item) for item in anchor),
                        "reference": tuple(
                            kernel.sstr(item) for item in reference
                        ),
                        "candidates": tuple(
                            tuple(kernel.sstr(item) for item in candidate)
                            for candidate in candidates
                        ),
                    },
                    locked=True,
                    source=self.method_id,
                ),
            },
            checks=checks,
            trace_fragments=trace,
        )


SPEC = MethodSpecSource(
    method_cls=RightAngleEqualLengthCandidatesMethod,
    title='直角等腰旋转列候选点',
    summary='输入: 直角顶点、已知端点和未知端点定义，点坐标可含参数；输出: 直角等腰旋转得到的两个候选点，候选坐标可保留参数。',
    solves=('derive_right_angle_equal_length_candidates',),
    inputs={
    "anchor": {
        "type": "Point",
        "role": "anchor",
        "required": True,
        "description": "直角顶点。"
    },
    "reference": {
        "type": "Point",
        "role": "reference",
        "required": True,
        "description": "已知直角边的另一个端点。"
    },
    "target": {
        "type": "PointRef",
        "role": "target",
        "required": True,
        "description": "待求坐标的点引用。"
    }
},
    input_views=declare_input_views(
        identity=("target",),
        latest_state=("anchor", "reference"),
    ),
    outputs={
    "candidates": "PointList",
    "construction_evidence": "Condition"
},
    internal_outputs=("construction_evidence",),
    preconditions=('anchor.coordinate is known, can be symbolic', 'reference.coordinate is known, can be symbolic', 'target is an unresolved point reference'),
    postconditions=('每个候选点都满足 distance(anchor, candidate) == distance(anchor, reference)', '每个候选点都满足 dot(anchor->reference, anchor->candidate) == 0'),
    trace_template=('由直角等腰条件，将 {reference} 绕 {anchor} 顺/逆时针旋转 90°，得到 {target} 的两个候选点。',),
    teaching_unit=TeachingUnitSpec(
        unit_key="right_angle_equal_length_candidates/construct_candidates",
        title_template="{construction_title}",
        nav_title_template="{construction_nav_title}",
        goal_template="{construction_goal}",
        derive_templates=(
            ("∵", "以 {anchor} 为直角顶点，已知边端点为 {reference}"),
            ("作", "将已知边顺、逆时针旋转 90°"),
            ("∴", "得到候选点 {candidates}"),
        ),
        box_templates=("{construction_result}",),
        role_schema={
            "anchor": "直角顶点。",
            "reference": "已知直角边的另一个端点。",
            "candidates": "顺、逆时针旋转所得候选点。",
            "construction_title": "当前数据适用的学生构造标题。",
            "construction_nav_title": "当前数据适用的学生导航标题。",
            "construction_goal": "当前数据适用的几何构造目标。",
            "construction_result": "顺、逆时针旋转所得的两个候选位置。",
        },
        role_binder_id="right_angle_equal_length_candidates",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "anchor": "直角顶点。",
            "reference": "已知边端点。",
            "candidates": "两个旋转候选点。",
        },
        scene_templates=(
            {
                "component": "RightAngleEqualLengthCandidatesMarker",
                "input_roles": ["anchor", "reference"],
                "output_role": "candidates",
                "requires_independent_lesson_step": True,
                "persistence": "carry_forward",
            },
        ),
        role_binder_id="generic_visual",
    ),
)
