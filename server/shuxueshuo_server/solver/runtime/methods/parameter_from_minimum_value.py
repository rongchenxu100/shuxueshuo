"""parameter_from_minimum_value 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import SymbolicClosureSpec
from shuxueshuo_server.solver.runtime.quadratic_constraint_solver import (
    value_satisfies_constraint,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    materialize_symbolic_closure_outputs,
    solve_symbolic_closure_math,
)

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


class ParameterFromMinimumValueMethod:
    """由最小值表达式和目标值反求参数。"""

    method_id = "parameter_from_minimum_value"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        expression = inputs["minimum_expression"]
        condition = inputs["condition"]
        parameter = inputs["parameter"]
        constraint = inputs.get("constraint")
        target = _require_canonical_runtime_expression(
            condition["value"],
            kernel,
            arg_name="condition",
            role="minimum_target_value",
        )
        closure = _require_unique_symbolic_closure(
            solve_symbolic_closure_math(
                _SYMBOLIC_CLOSURE_SPEC,
                args=inputs,
                kernel=kernel,
            ),
            arg_name="condition",
            role="minimum_value_equation",
        )
        outputs, closure_checks = materialize_symbolic_closure_outputs(
            {
                "parameter_value": TypedValue(
                    "ParameterValue", parameter, source=self.method_id
                )
            },
            closure,
        )
        value = outputs["parameter_value"].value
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs=outputs,
            checks=[
                _check(
                    "minimum_parameter_domain",
                    value_satisfies_constraint(value, constraint),
                    "参数满足定义域",
                ),
                _check("minimum_value_matches", sp.simplify(expression.subs(parameter, value) - target) == 0, "最小值匹配题设"),
                *closure_checks,
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由最小值反求参数",
                    f"求 {parameter.name} 的值",
                    "题目给出最小值，代入最小值表达式解方程。",
                    f"{parameter.name}={kernel.sstr(value)}",
                    f"{parameter.name}={kernel.sstr(value)}",
                )
            ],
        )


_SYMBOLIC_CLOSURE_SPEC = SymbolicClosureSpec(
    target_arg="parameter",
    equation_builder="minimum_expression_equals_value",
    constraint_filter="parameter_value_constraint",
    constraint_args=("constraint",),
    constraint_args_optional=True,
    substitution_outputs=("parameter_value",),
    output_validator="parameter_value_closure_outputs",
)


SPEC = MethodSpecSource(
    method_cls=ParameterFromMinimumValueMethod,
    title='由最小值反求参数',
    summary='输入: 最小值表达式与给定最小值条件；输出: 参数值。',
    do_not_use_when=(
        "输入表达式不具有最小值语义，或题面给出的只是普通表达式取值条件。",
        "尚未得到可代入的最小值表达式。",
        "最小值表达式仍含两个或更多相互独立的未知 Symbol；应先化为单一未知量。",
        (
            "当前目标只是更新函数或几何对象状态；该能力只反求最小值表达式中"
            "实际存在的单一目标参数，不代替状态更新。"
        ),
        "最小值方程有多个合法参数分支但没有提供足以唯一筛选的结构化 constraint；不会默认选择第一个解。",
    ),
    solves=('derive_parameter_from_minimum_value',),
    inputs={
    "minimum_expression": {
        "type": "MinimumExpression",
        "required": True
    },
    "condition": {
        "type": "Condition",
        "required": True
    },
    "parameter": {
        "type": "Symbol",
        "required": True
    },
    "constraint": {
        "type": "Constraint",
        "required": False
    }
},
    input_views=declare_input_views(
        identity=("parameter",),
        immutable_value=("condition", "constraint"),
        exact_result=("minimum_expression",),
    ),
    outputs={
    "parameter_value": "ParameterValue"
},
    plan_transformer="validate_student_single_degree_of_freedom",
    plan_transformer_scope="all_invocations",
    preconditions=(
        "parameter 必须实际参与 minimum_expression=condition.value 方程",
        "若方程有多个分支，constraint 必须唯一筛选一个合法分支",
    ),
    postconditions=("输出参数值满足最小值方程与声明的参数范围",),
    trace_template=(),
    symbolic_closure=_SYMBOLIC_CLOSURE_SPEC,
)
