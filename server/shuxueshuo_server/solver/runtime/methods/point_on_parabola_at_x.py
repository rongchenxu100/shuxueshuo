"""point_on_parabola_at_x 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


class PointOnParabolaAtXMethod:
    """由目标点结构化定义中的横坐标，在抛物线上求同一对象的坐标。"""

    method_id = "point_on_parabola_at_x"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parabola = inputs["parabola"]
        x = inputs["x"]
        target: PointRef = inputs["target"]
        raw_x = target.definition.get("x") or target.definition.get("x_coordinate")
        if raw_x is None:
            raise method_precondition_failed(
                "point_on_parabola_at_x requires a structured target x-coordinate",
                arg_name="target",
                role="curve_point_at_known_x",
                internal_ref=target.name,
                expected={
                    "type": "Point",
                    "state": "structured_x_coordinate",
                    "definition_keys": ["x", "x_coordinate"],
                },
                observed={
                    "state": "x_coordinate_missing",
                    "construction": target.definition.get("definition", "unspecified"),
                    "definition_keys": sorted(target.definition),
                },
                repair_action="choose_applicable_point_construction_capability",
            )
        x_value = _require_canonical_runtime_expression(
            raw_x,
            kernel,
            arg_name="target",
            role="curve_point_at_known_x",
        )
        point = (sp.simplify(x_value), sp.simplify(parabola.subs(x, x_value)))
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "point_on_parabola",
                    sp.simplify(parabola.subs(x, point[0]) - point[1]) == 0,
                    "点坐标满足抛物线解析式",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由横坐标求曲线上点",
                    f"确定 {target.name} 的坐标",
                    "点在抛物线上，已知横坐标时把横坐标代入解析式。",
                    f"x_{target.name}={kernel.sstr(x_value)}",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=PointOnParabolaAtXMethod,
    title="由横坐标求抛物线上点",
    summary=(
        "仅在题面已把目标点的横坐标作为结构化条件直接给出、只需代入当前"
        "抛物线求纵坐标时使用。"
        "FunctionalPlan 只显式传入 parabola，并把 point return 绑定到该已有目标点；"
        "代码从目标点的结构化 definition.x 或 definition.x_coordinate 读取横坐标。"
        "strategy/reason 中自行写出的横坐标不能替代这项题面证据。"
    ),
    solves=("derive_point_on_parabola_at_x",),
    inputs={
        "parabola": {
            "type": "Parabola",
            "required": True,
            "symbolic_basis_role": "state_anchor",
        },
        "x": {"type": "Symbol", "required": True},
        "target": {
            "type": "PointRef",
            "required": True,
            "symbolic_basis_role": "align_to_anchor",
        },
    },
    input_views=declare_input_views(
        identity=("x", "target"),
        latest_state=("parabola",),
    ),
    outputs={"point": "Point"},
    do_not_use_when=(
        "目标点没有题面结构化横坐标定义时禁止使用；仅知道点在抛物线上、只有"
        "几何关系，或只在 strategy/reason 中写出横坐标，都需要先通过其它能力"
        "确定横坐标。",
        "前序几何构造已经产生多个有坐标的候选点，需要继续筛选唯一候选。",
        "需要从候选分支反求参数并把参数代回抛物线。",
    ),
    preconditions=("target.definition.x 或 target.definition.x_coordinate 必须存在",),
    postconditions=("输出点在给定抛物线上",),
)
