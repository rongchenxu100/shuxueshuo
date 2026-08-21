"""parameter_from_curve_point_on_quadratic 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import (
    MethodInputRelationSpec,
    SymbolicClosureSpec,
)
from shuxueshuo_server.solver.runtime.quadratic_constraint_solver import (
    value_satisfies_constraint,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    materialize_symbolic_closure_outputs,
    solve_symbolic_closure_math,
)

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


class ParameterFromCurvePointOnQuadraticMethod:
    """由含参抛物线和含参曲线点反求参数。

    这个 method 处理的是一个很小、很常见的动作：当前问已经得到只含一个参数的
    抛物线，且某个点坐标也由同一个参数表达。把该点代入抛物线即可解出参数，
    再把参数代回点和抛物线。

    例如，已知当前抛物线 ``y=2*x**2-b*x-b-2``，几何候选已经筛成
    ``P=(b+1,1)``，代入曲线可解出 ``b``，再同步更新点坐标和最终抛物线。
    """

    method_id = "parameter_from_curve_point_on_quadratic"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        x = inputs["x"]
        parameter = inputs["parameter"]
        constraint = inputs.get("parameter_constraint")
        known_parameter = inputs.get("known_parameter")
        known_parameter_value = inputs.get("known_parameter_value")
        if (known_parameter is None) != (known_parameter_value is None):
            missing_arg = (
                "known_parameter"
                if known_parameter is None
                else "known_parameter_value"
            )
            provided_arg = (
                "known_parameter_value"
                if known_parameter is None
                else "known_parameter"
            )
            raise method_input_missing(
                "known_parameter and known_parameter_value must be provided together",
                arg_name=missing_arg,
                role="known_parameter_substitution",
                expected={"paired_arg": provided_arg},
                observed={
                    "missing_inputs": [missing_arg],
                    "provided_inputs": [provided_arg],
                },
                repair_action="provide_substitution_pair",
            )
        math_result = solve_symbolic_closure_math(
            _SYMBOLIC_CLOSURE_SPEC,
            args=inputs,
            kernel=kernel,
        )
        closure = _require_unique_symbolic_closure(
            math_result,
            arg_name="parameter_constraint",
            role="curve_point_parameter_equation",
        )
        outputs, closure_checks = materialize_symbolic_closure_outputs(
            {
                "parameter_value": TypedValue(
                    "ParameterValue", parameter, source=self.method_id
                ),
                "point": TypedValue("Point", inputs["point"], source=self.method_id),
                "parabola": TypedValue(
                    "Parabola", inputs["quadratic"], source=self.method_id
                ),
            },
            closure,
        )
        parameter_value = outputs["parameter_value"].value
        resolved_point = outputs["point"].value
        parabola = sp.expand(outputs["parabola"].value)

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs=outputs,
            checks=[
                _check(
                    "parameter_constraint_satisfied",
                    value_satisfies_constraint(parameter_value, constraint),
                    f"{parameter.name} 满足题设参数约束",
                ),
                _check(
                    "resolved_point_on_parabola",
                    sp.simplify(parabola.subs(x, resolved_point[0]) - resolved_point[1]) == 0,
                    "代入参数后的点在抛物线上",
                ),
                *closure_checks,
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由曲线点反求参数",
                    f"确定参数 {parameter.name} 并代回点坐标",
                    (
                        "把含参点坐标代入当前问含参抛物线；若方程先确定等价的"
                        "内部系数，则沿当前系数表达式闭包到目标参数。"
                    ),
                    f"{parameter.name}={kernel.sstr(parameter_value)}",
                    f"点({_fmt_point(resolved_point, kernel)})，y={kernel.sstr(parabola)}",
                )
            ],
        )


_SYMBOLIC_CLOSURE_SPEC = SymbolicClosureSpec(
    target_arg="parameter",
    equation_builder="point_on_curve",
    known_substitutions=(("known_parameter", "known_parameter_value"),),
    representation_mapper="polynomial_coefficient_template",
    constraint_filter="parameter_value_constraint",
    constraint_args=("parameter_constraint",),
    constraint_args_optional=True,
    substitution_outputs=("parameter_value", "point", "parabola"),
    output_validator="point_on_curve_closure_outputs",
)


SPEC = MethodSpecSource(
    method_cls=ParameterFromCurvePointOnQuadraticMethod,
    title="由曲线点反求参数并代回抛物线",
    summary=(
        "已有当前抛物线和曲线上一点；先代入已知参数值，再用曲线点方程唯一"
        "确定目标参数。若方程直接确定另一二次函数系数，代码会沿当前系数"
        "表达式闭包到目标参数，并更新点和抛物线。"
    ),
    do_not_use_when=(
        "代入当前已知参数值后仍有两个及以上未确定参数，且无法由当前二次函数系数表达式唯一闭包到目标参数。",
        "需要先推导曲线表达式或点坐标，而不是利用已有曲线点条件反求参数。",
        "曲线点方程产生多个合法参数分支，但当前调用没有提供能唯一筛选分支的结构化参数约束。",
        "目标参数没有出现在曲线点方程，也不能由 quadratic_template 中对应系数唯一映射；不要机械复制其他小问的参数反求路线。",
    ),
    solves=("derive_parameter_from_curve_point_on_quadratic",),
    inputs={
        "quadratic": {
            "type": "Parabola",
            "required": True,
            "symbolic_basis_role": "state_anchor",
        },
        "x": {"type": "Symbol", "required": True},
        "point": {
            "type": "Point",
            "required": True,
            "symbolic_basis_role": "align_to_anchor",
        },
        "parameter": {"type": "Symbol", "required": True},
        "parameter_constraint": {
            "type": "Constraint",
            "required": False,
            "symbolic_basis_role": "align_to_anchor",
        },
        "known_parameter": {"type": "Symbol", "required": False},
        "known_parameter_value": {"type": "ParameterValue", "required": False},
        "quadratic_template": {
            "type": "Expression",
            "required": False,
            "functional_exposed": False,
            "description": (
                "由MethodInputReadAuthority注入同一二次函数对象的"
                "ordinal-0原始系数模板；不得使用已消元的latest state代替。"
            ),
        },
    },
    input_views=declare_input_views(
        identity=("x", "parameter", "known_parameter"),
        latest_state=("quadratic", "point", "known_parameter_value"),
        immutable_value=("parameter_constraint", "quadratic_template"),
    ),
    input_relations=(
        MethodInputRelationSpec(
            relation_kind="point_on_curve",
            point_arg="point",
            curve_arg="quadratic",
            cardinality="one",
            accepted_condition_kinds=(
                "point_on_curve",
                "point_on_curve_with_x_coordinate",
            ),
        ),
    ),
    outputs={
        "parameter_value": "ParameterValue",
        "point": "Point",
        "parabola": "Parabola",
    },
    preconditions=(
        "应用已知参数值后，曲线点方程必须直接唯一确定目标参数，或唯一确定可映射到目标参数的二次函数系数",
        "点代入抛物线后，在参数约束下必须唯一确定参数值",
        "若存在多个代数分支，parameter_constraint 必须唯一保留其中一个；无约束时不会默认选择第一个解",
    ),
    postconditions=(
        "输出 point 是代入参数后的坐标",
        "输出 parabola 是代入参数后的当前问抛物线",
    ),
    symbolic_closure=_SYMBOLIC_CLOSURE_SPEC,
)
