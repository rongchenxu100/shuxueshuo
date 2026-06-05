"""parameter_from_segment_length 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

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
        p1: Point = inputs["p1"]
        p2: Point = inputs["p2"]
        reference_p1: Point | None = inputs.get("reference_p1")
        reference_p2: Point | None = inputs.get("reference_p2")
        parameter = inputs["parameter"]
        condition = inputs["condition"]
        constraint = inputs.get("constraint")
        locals_ = {
            symbol.name: symbol
            for symbol in _free_symbols_in_points(
                p1,
                p2,
                *(point for point in (reference_p1, reference_p2) if point is not None),
            ) | {parameter}
        }
        lower_bound = constraint["value"] if isinstance(constraint, dict) and constraint.get("operator") == ">" else None
        length_sq = kernel.distance_squared(p1, p2)
        equation, target = _length_equation(
            kernel,
            condition,
            locals_,
            length_sq=length_sq,
            reference_p1=reference_p1,
            reference_p2=reference_p2,
        )
        candidates = kernel.solve_values(equation, parameter)
        value = pick_by_lower_bound(candidates, lower_bound)
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"parameter_value": TypedValue("ParameterValue", value, source=self.method_id)},
            checks=[
                _check("parameter_domain", satisfies_lower_bound(value, lower_bound), "参数满足定义域"),
                _check(
                    "length_condition_matches",
                    sp.simplify(length_sq.subs(parameter, value) - target.subs(parameter, value)) == 0,
                    "距离条件成立",
                ),
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


def _length_equation(
    kernel: SympyKernel,
    condition: dict[str, Any],
    locals_: dict[str, sp.Symbol],
    *,
    length_sq: sp.Expr,
    reference_p1: Point | None,
    reference_p2: Point | None,
) -> tuple[sp.Equality, sp.Expr]:
    """把不同形态的长度条件统一成一元方程。"""
    condition_type = str(condition.get("type", ""))
    if condition_type == "segment_length_relation" or (
        "left_segment" in condition and "right_segment" in condition and "scale" in condition
    ):
        if reference_p1 is None or reference_p2 is None:
            raise ValueError("segment_length_relation requires reference_p1/reference_p2")
        scale = kernel.expr(str(condition.get("scale", "1")), locals_)
        reference_sq = kernel.distance_squared(reference_p1, reference_p2)
        target = sp.simplify(scale**2 * reference_sq)
        return sp.Eq(length_sq, target), target
    if "value" not in condition:
        raise ValueError("length condition requires value or segment_length_relation fields")
    target = kernel.expr(condition["value"], locals_)
    return sp.Eq(length_sq, target), target


def _free_symbols_in_points(*points: Point) -> set[sp.Symbol]:
    """收集点坐标中的符号，确保条件表达式复用同一批 runtime Symbol。"""
    result: set[sp.Symbol] = set()
    for point in points:
        result.update(sp.sympify(point[0]).free_symbols)
        result.update(sp.sympify(point[1]).free_symbols)
    return result


SPEC = MethodSpecSource(
    method_cls=ParameterFromSegmentLengthMethod,
    title='由线段长度求参数',
    summary='输入: 线段端点和长度/线段比例条件；输出: 满足条件的参数值。支持 MN²=10 与 AD=2BC 这类原始线段关系。',
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
    preconditions=("condition.value 表示绝对长度平方，或 condition.type=segment_length_relation 且提供 reference_p1/reference_p2",),
    postconditions=("求得参数满足长度方程；若有参数范围约束，按范围筛选唯一解",),
    trace_template=(),
)
