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
    do_not_use_when=(
        "目标是构造另一个几何点；本能力只把参数值代入同一 Point 的已有坐标状态，不改变对象身份。",
    ),
    solves=("evaluate_point_at_parameter",),
    inputs={
        "point": {"type": "Point", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "parameter_value": {"type": "ParameterValue", "required": True},
    },
    outputs={"evaluated_point": "Point"},
    plan_transformer="substitute_all_point_parameters",
    reconciliation_validators=("companion_symbol_coverage",),
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
            "message": "最终答案点不能由当前参数代入直接得到；缺少从极值状态动点恢复目标点的几何状态转移。",
            "next_actions": (
                "先产生极值状态 moving point，再读取题设几何条件把该状态转移到最终目标点。",
                "从当前 catalog 中选择返回角色、对象身份和 scope 均满足这些缺失状态的能力。",
            ),
            "do_not": (
                "不要用 `evaluate_point_at_parameter` 直接 produces 最终 Point answer。",
            ),
        },
    ),
)
