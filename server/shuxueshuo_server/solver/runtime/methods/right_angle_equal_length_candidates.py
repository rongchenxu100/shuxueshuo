"""right_angle_equal_length_candidates 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class RightAngleEqualLengthCandidatesMethod:
    """由直角等腰条件列出未知直角边端点的两个候选。

    输入语义：

    - ``anchor``：直角顶点；
    - ``reference``：已知直角边的另一个端点；
    - ``target``：待求点引用，只用于命名和 trace；

    该 method 只做旋转候选生成，不根据象限、曲线或参数范围筛选。筛选逻辑必须
    由后续 method 显式接收题设条件后完成。
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
            checks.extend(
                [
                    CheckResult(
                        name=f"candidate_{index}_right_equal_length",
                        status="passed" if sp.simplify(dist_known - dist_derived) == 0 else "failed",
                        detail=f"{target.name} 候选 {index} 与已知直角边等长",
                    ),
                    CheckResult(
                        name=f"candidate_{index}_right_angle",
                        status="passed" if sp.simplify(dot) == 0 else "failed",
                        detail=f"{target.name} 候选 {index} 与已知直角边垂直",
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
                )
            },
            checks=checks,
            trace_fragments=trace,
        )


SPEC = MethodSpecSource(
    method_cls=RightAngleEqualLengthCandidatesMethod,
    title='直角等腰旋转列候选点',
    solves=('derive_right_angle_equal_length_candidates',),
    inputs={
    "anchor": {
        "type": "Point",
        "role": "right_angle_vertex",
        "required": True,
        "description": "直角顶点，例如南开题中的 D。"
    },
    "reference": {
        "type": "Point",
        "role": "known_leg_endpoint",
        "required": True,
        "description": "已知直角边的另一个端点，例如南开题中的 M。"
    },
    "target": {
        "type": "PointRef",
        "role": "unknown_leg_endpoint",
        "required": True,
        "description": "待求坐标的点引用，例如南开题中的 N。"
    }
},
    outputs={
    "candidates": "PointList"
},
    preconditions=('anchor.coordinate is known', 'reference.coordinate is known', 'target is an unresolved point reference'),
    postconditions=('每个候选点都满足 distance(anchor, candidate) == distance(anchor, reference)', '每个候选点都满足 dot(anchor->reference, anchor->candidate) == 0'),
    trace_template=('由直角等腰条件，将 {reference} 绕 {anchor} 顺/逆时针旋转 90°，得到 {target} 的两个候选点。',),
)
