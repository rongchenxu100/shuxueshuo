"""translated_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec

from ._common import *
from ._spec import MethodSpecSource


class TranslatedPointMethod:
    """由已知点和平移向量求目标点坐标。

    适用于题面直接定义“D 是 C 向右平移 2 个单位得到的点”这类对象。method
    只执行点平移，不负责从函数或几何条件推导 source point。
    """

    method_id = "translated_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        source: Point = inputs["source"]
        target: PointRef = inputs["target"]
        raw_vector = target.definition.get(
            "vector",
            [target.definition.get("dx", "0"), target.definition.get("dy", "0")],
        )
        if not isinstance(raw_vector, list) or len(raw_vector) != 2:
            raise ValueError("translated point target requires 2D vector")
        dx = kernel.expr(raw_vector[0])
        dy = kernel.expr(raw_vector[1])
        point = (sp.simplify(source[0] + dx), sp.simplify(source[1] + dy))

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "translation_vector_applied",
                    sp.simplify(point[0] - source[0] - dx) == 0
                    and sp.simplify(point[1] - source[1] - dy) == 0,
                    "目标点坐标等于源点坐标加平移向量",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由平移求点坐标",
                    f"确定 {target.name} 的坐标",
                    "题面给出目标点由源点平移得到，按向量加法计算。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=TranslatedPointMethod,
    title="由平移求点坐标",
    summary="输入: 源点坐标和目标 PointRef 中的平移向量；输出: 目标点坐标。",
    solves=("derive_translated_point",),
    inputs={
        "source": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"point": "Point"},
    preconditions=("target.definition 包含 vector 或 dx/dy 平移信息",),
    postconditions=("输出点等于 source 加平移向量",),
    explanation=MethodExplanationSpec(
        role_schema={
            "source_point": "被平移的源点。",
            "target_point": "平移后得到的目标点。",
            "vector": "平移向量。",
        },
        student_goal_template="根据题设平移关系，由源点坐标求目标点坐标。",
        student_title_template="由平移关系求点坐标",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "source_point": "被平移的源点。",
            "target_point": "平移后得到的目标点。",
            "vector": "平移向量。",
        },
        scene_templates=(
            {
                "component": "TranslationMarker",
                "source_role": "source_point",
                "target_role": "target_point",
                "vector_role": "vector",
                "style_intent": "construction",
            },
        ),
        role_binder_id="translated_point",
    ),
)
