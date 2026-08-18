"""parameter_from_expression_value 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import (
    MethodExplanationSpec,
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


class ParameterFromExpressionValueMethod:
    """由表达式等于题设给定值反求参数。

    这是 ``parameter_from_minimum_value`` 的泛化命名版：method 不关心表达式的
    来源是否为“最小值”，只关心它已经是一个可求值的表达式，并且题设给出它应
    等于某个目标值。首版输入类型仍复用 runtime 里已有的 ``MinimumExpression``，
    避免过早扩大类型系统；后续若普通 ``Expression`` 也需要同样能力，再放宽
    MethodSpec 输入类型。
    """

    method_id = "parameter_from_expression_value"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        expression = inputs["expression"]
        condition = inputs["condition"]
        parameter = inputs["parameter"]
        constraint = inputs.get("constraint")

        target = _require_canonical_runtime_expression(
            condition["value"],
            kernel,
            arg_name="condition",
            role="expression_target_value",
        )
        closure = _require_unique_symbolic_closure(
            solve_symbolic_closure_math(
                _SYMBOLIC_CLOSURE_SPEC,
                args=inputs,
                kernel=kernel,
            ),
            arg_name="condition",
            role="expression_value_equation",
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
                    "parameter_domain",
                    value_satisfies_constraint(value, constraint),
                    "参数满足定义域",
                ),
                _check(
                    "expression_value_matches",
                    sp.simplify(expression.subs(parameter, value) - target) == 0,
                    "表达式取值匹配题设",
                ),
                *closure_checks,
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由表达式取值反求参数",
                    f"求 {parameter.name} 的值",
                    "题目给出某个表达式的取值，代入表达式解方程。",
                    f"{parameter.name}={kernel.sstr(value)}",
                    f"{parameter.name}={kernel.sstr(value)}",
                )
            ],
        )


_SYMBOLIC_CLOSURE_SPEC = SymbolicClosureSpec(
    target_arg="parameter",
    equation_builder="expression_equals_value",
    constraint_filter="parameter_value_constraint",
    constraint_args=("constraint",),
    constraint_args_optional=True,
    substitution_outputs=("parameter_value",),
    output_validator="parameter_value_closure_outputs",
)


SPEC = MethodSpecSource(
    method_cls=ParameterFromExpressionValueMethod,
    title="由表达式取值反求参数",
    summary="输入: 已推导表达式与给定值条件；输出: 参数值。使用原则: 当几何或代数步骤已经给出含参数表达式，而题设给出该表达式的取值时使用。",
    do_not_use_when=(
        "尚未得到可代入的含参表达式，或题面没有给出该表达式对应的取值条件。",
        "目标是完成路径转化或推导最小值表达式，而不是由一个已知表达式取值反求参数。",
        "表达式仍含两个或更多相互独立的未知 Symbol；中学生解法应先利用显式关系或已知参数值化为单一未知量。",
        "所选 parameter 没有实际出现在 expression 中；此时应改用真正含该参数的表达式，不能按其他小问的步骤机械反求。",
        "方程有多个合法参数分支但没有提供足以唯一筛选的结构化 constraint；该能力不会默认选择第一个解。",
    ),
    solves=("derive_parameter_from_expression_value",),
    inputs={
        "expression": {"type": "MinimumExpression", "required": True},
        "condition": {"type": "Condition", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "constraint": {"type": "Constraint", "required": False},
    },
    input_views=declare_input_views(
        identity=("parameter",),
        immutable_value=("condition", "constraint"),
        exact_result=("expression",),
    ),
    outputs={"parameter_value": "ParameterValue"},
    plan_transformer="validate_student_single_degree_of_freedom",
    plan_transformer_scope="all_invocations",
    preconditions=(
        "expression 已由前序 method 推导得到，且 parameter 实际参与 expression=condition.value 方程",
        "若方程有多个分支，constraint 必须唯一筛选一个合法分支",
    ),
    postconditions=("输出参数值满足表达式取值条件",),
    explanation=MethodExplanationSpec(
        role_schema={
            "expression": "前序步骤得到的含参表达式。",
            "target_value": "题设给出的表达式取值。",
            "parameter": "需要反求的参数。",
            "parameter_value": "解出的参数值。",
        },
        student_goal_template="把题设给定值代入已得到的表达式，解出参数。",
        student_title_template="由表达式取值反求参数",
        derive_templates=(
            "∵{expression}＝{target_value}",
            "∴{parameter}＝{parameter_value}",
        ),
        box_templates=("{parameter}＝{parameter_value}",),
        role_binder_id="parameter_from_expression_value",
    ),
    symbolic_closure=_SYMBOLIC_CLOSURE_SPEC,
)
