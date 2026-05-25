"""select_point_by_quadrant_constraint 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class SelectPointByQuadrantConstraintMethod:
    """根据象限条件和参数约束，从候选点中选出唯一点。"""

    method_id = "select_point_by_quadrant_constraint"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        candidates: list[Point] = inputs["candidates"]
        target: PointRef = inputs["target"]
        quadrant = inputs["quadrant"]
        parameter = inputs["parameter"]
        parameter_constraint = inputs["parameter_constraint"]
        quadrant_text = str(quadrant.get("quadrant", quadrant)) if isinstance(quadrant, dict) else str(quadrant)
        operator = str(parameter_constraint.get("operator", ""))
        if operator != ">":
            raise ValueError("select_point_by_quadrant_constraint currently requires a > parameter constraint")
        lower_bound = sp.sympify(parameter_constraint["value"])
        matching = [
            point for point in candidates
            if _point_matches_quadrant_under_lower_bound(
                point,
                quadrant_text,
                parameter,
                lower_bound,
            )
        ]
        if len(matching) != 1:
            raise ValueError(
                f"quadrant constraint should select exactly one candidate, got {len(matching)}"
            )
        selected = matching[0]
        condition_text = f"{target.name} 在{quadrant_text}，且 {parameter.name}>{kernel.sstr(lower_bound)}"
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "selected_point": TypedValue(
                    "Point",
                    selected,
                    locked=False,
                    source=self.method_id,
                )
            },
            checks=[
                _check("quadrant_filter_unique", True, "象限与参数约束选出唯一候选点"),
                _check("parameter_constraint_used", True, condition_text),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    f"由象限与参数约束筛选 {target.name}",
                    f"确定唯一的 {target.name} 坐标",
                    "把候选点分别放到题设象限和参数范围下判断。",
                    f"{_fmt_point_candidates(target.name, candidates, kernel)}; {condition_text}",
                    f"{target.name}({_fmt_point(selected, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=SelectPointByQuadrantConstraintMethod,
    title='由象限与参数约束筛选点',
    solves=('select_point_by_region',),
    inputs={
    "candidates": {
        "type": "PointList",
        "role": "candidate_points",
        "required": True,
        "description": "上一步得到的候选点列表。"
    },
    "target": {
        "type": "PointRef",
        "role": "target_point",
        "required": True,
        "description": "待筛选的目标点引用。"
    },
    "quadrant": {
        "type": "OrientationHint",
        "role": "region_condition",
        "required": True,
        "description": "目标点所在象限，例如第四象限。"
    },
    "parameter": {
        "type": "Symbol",
        "role": "dynamic_parameter",
        "required": True,
        "description": "候选点中出现的动态参数，例如 m。"
    },
    "parameter_constraint": {
        "type": "Constraint",
        "role": "parameter_domain",
        "required": True,
        "description": "参数范围约束，例如 m > 2。"
    }
},
    outputs={
    "selected_point": "Point"
},
    preconditions=('candidates 至少包含一个点', 'quadrant 必须给出明确象限', 'parameter_constraint 必须显式给出参数下界'),
    postconditions=('selected_point 是 candidates 中唯一满足象限和参数约束的点',),
    trace_template=('根据 {target} 的象限条件和参数约束，从候选点中筛选唯一坐标。',),
)
