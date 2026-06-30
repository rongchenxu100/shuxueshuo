"""evaluate_point_at_parameter 无状态 method。

本 method 只处理“点坐标代入参数值”这一层通用代数动作。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec

from ._common import *
from ._spec import MethodSpecSource


class EvaluatePointAtParameterMethod:
    """把点坐标中的参数替换为已求出的参数值。"""

    method_id = "evaluate_point_at_parameter"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        point: Point = inputs["point"]
        parameter = inputs["parameter"]
        parameter_value = sp.sympify(inputs["parameter_value"])
        evaluated = _subs_point(point, {parameter: parameter_value})
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "evaluated_point": TypedValue(
                    "Point",
                    evaluated,
                    source=self.method_id,
                )
            },
            checks=[
                _check(
                    "point_parameter_substituted",
                    all(parameter not in sp.sympify(coord).free_symbols for coord in evaluated),
                    "参数已代入点坐标",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "代入参数求点坐标",
                    "求点在参数取值下的坐标",
                    "前序步骤已经确定参数值，因此直接代入点坐标并化简。",
                    f"{parameter.name}={kernel.sstr(parameter_value)}",
                    f"({_fmt_point(evaluated, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=EvaluatePointAtParameterMethod,
    title="代入参数求点坐标",
    summary="Given 含参点坐标、参数符号和参数值, derive 代入参数后的点坐标。",
    solves=("evaluate_point_at_parameter",),
    inputs={
        "point": {"type": "Point", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "parameter_value": {"type": "ParameterValue", "required": True},
    },
    outputs={"evaluated_point": "Point"},
    preconditions=("point 坐标可以包含 parameter",),
    postconditions=("输出点坐标不再含 parameter",),
    explanation=MethodExplanationSpec(
        role_schema={
            "source_point": "代入前的含参点坐标。",
            "parameter": "已求出的参数名。",
            "parameter_value": "已求出的参数值。",
            "evaluated_point": "代入参数后的点坐标。",
        },
        student_goal_template="把已求出的参数代入含参点坐标，得到定点坐标。",
        student_title_template="代入参数求点坐标",
        student_nav_title_template="代入参数求点坐标",
        derive_templates=(
            "∵{source_point}，{parameter}＝{parameter_value}",
            "∴{evaluated_point}",
        ),
        box_templates=("{evaluated_point}",),
        role_binder_id="evaluate_point_at_parameter",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "source_point": "代入前的含参点。",
            "evaluated_point": "代入参数后的点。",
        },
        scene_templates=(
            {
                "component": "EvaluatedPointMarker",
                "point_role": "evaluated_point",
                "point_color": "#b45309",
                "persistence": "carry_forward",
            },
        ),
        role_binder_id="evaluate_point_at_parameter",
    ),
    repair_hints=(
        {
            "code": "final_point_requires_square_recovery",
            "applies_to": ("method:evaluate_point_at_parameter",),
            "message": "最终答案点不能直接参数代入；应先求最短状态 moving point，再用正方形关系恢复。",
            "next_actions": (
                "先用 `line_locus_minimum_point` 读取动点轨迹、`fact:<scope>:path_minimum_point_1/2` 和参数值，求最短状态 moving point。",
                "再用 `square_adjacent_vertex_from_side` 读取正方形条件、已知边端点和该 moving point，恢复最终答案点。",
            ),
            "do_not": (
                "不要用 `evaluate_point_at_parameter` 直接 produces 最终 Point answer。",
            ),
        },
    ),
)
