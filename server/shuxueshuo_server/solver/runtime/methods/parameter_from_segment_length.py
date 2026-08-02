"""parameter_from_segment_length 无状态 method。

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
    require_unique_symbolic_closure,
    solve_symbolic_closure_math,
)

from ._common import *
from ._spec import MethodSpecSource


class ParameterFromSegmentLengthMethod:
    """由线段长度条件求参数。

    支持两类输入：

    - 绝对长度/长度平方条件，例如 ``MN²=10``；
    - 两条线段成比例的原始题设条件，例如 ``AD=2BC``。

    第二类场景需要额外传入 ``reference_p1/reference_p2``，method 内部会建立
    ``|p1p2|² = scale² * |reference_p1 reference_p2|²``，而不是要求 ProblemIR
    预先把右侧长度展开成表达式。
    """

    method_id = "parameter_from_segment_length"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parameter = inputs["parameter"]
        constraint = inputs.get("constraint")
        math_result = solve_symbolic_closure_math(
            _SYMBOLIC_CLOSURE_SPEC,
            args=inputs,
            kernel=kernel,
        )
        closure = require_unique_symbolic_closure(math_result)
        outputs, closure_checks = materialize_symbolic_closure_outputs(
            {
                "parameter_value": TypedValue(
                    "ParameterValue", parameter, source=self.method_id
                )
            },
            closure,
        )
        value = outputs["parameter_value"].value
        equation = math_result.build_result.equations[0]
        resolved_equation = equation.subs(closure.substitution)
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
                    "length_condition_matches",
                    resolved_equation is sp.S.true
                    or (
                        isinstance(resolved_equation, sp.Equality)
                        and sp.simplify(
                            resolved_equation.lhs - resolved_equation.rhs
                        )
                        == 0
                    ),
                    "距离条件成立",
                ),
                *closure_checks,
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由长度条件求参数",
                    f"求 {parameter.name} 的值",
                    "两点距离平方等于题设值，解一元方程并按定义域筛选。",
                    f"{parameter.name}={kernel.sstr(value)}",
                    f"{parameter.name}={kernel.sstr(value)}",
                )
            ],
        )


_SYMBOLIC_CLOSURE_SPEC = SymbolicClosureSpec(
    target_arg="parameter",
    equation_builder="segment_length_equals_value",
    constraint_filter="parameter_value_constraint",
    constraint_args=("constraint",),
    constraint_args_optional=True,
    substitution_outputs=("parameter_value",),
    output_validator="parameter_value_closure_outputs",
)


SPEC = MethodSpecSource(
    method_cls=ParameterFromSegmentLengthMethod,
    title='由线段长度求参数',
    summary='输入: 线段端点和长度/线段比例条件；输出: 满足条件的参数值。支持 MN²=10 与 AD=2BC 这类原始线段关系。',
    do_not_use_when=(
        "parameter 没有实际出现在由端点和长度条件建立的方程中。",
        "线段比例条件缺少对应 reference_p1/reference_p2；不能按点名或条件文本猜测参照端点。",
        "长度方程有多个合法参数分支但没有提供足以唯一筛选的结构化 constraint；不会默认选择第一个解。",
    ),
    solves=('derive_parameter_from_segment_length',),
    inputs={
    "p1": {
        "type": "Point",
        "required": True
    },
    "p2": {
        "type": "Point",
        "required": True
    },
    "reference_p1": {
        "type": "Point",
        "required": False
    },
    "reference_p2": {
        "type": "Point",
        "required": False
    },
    "parameter": {
        "type": "Symbol",
        "required": True
    },
    "condition": {
        "type": "Condition",
        "required": True
    },
    "constraint": {
        "type": "Constraint",
        "required": False
    }
},
    outputs={
    "parameter_value": "ParameterValue"
},
    preconditions=(
        "p1/p2 必须是 condition 所声明线段的两个端点，顺序可以交换",
        "condition.value 表示绝对长度平方，或 condition.type=segment_length_relation 且提供对应参照线段的 reference_p1/reference_p2",
        "若长度方程有多个分支，constraint 必须唯一筛选一个合法分支",
    ),
    postconditions=("求得参数满足长度方程；若有参数范围约束，按范围筛选唯一解",),
    trace_template=(),
    symbolic_closure=_SYMBOLIC_CLOSURE_SPEC,
)
