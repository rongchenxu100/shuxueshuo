"""filter_point_candidates_by_quadratic_curve 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class FilterPointCandidatesByQuadraticCurveMethod:
    """用当前二次函数表达式和参数约束筛选点候选。

    这个 method 只做“快速验证/筛选”：把每个候选点代入当前问已经化简好的
    二次函数，检查在给定参数约束下是否存在可行参数值。它不输出最终参数值，
    也不负责补齐二次函数系数；这些应交给后续“点在曲线上求参数”的 method。
    """

    method_id = "filter_point_candidates_by_quadratic_curve"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        candidates = list(inputs["candidates"])
        target: PointRef = inputs["target"]
        parabola = inputs["parabola"]
        x = inputs["x"]
        parameter = inputs["parameter"]
        constraint = inputs.get("parameter_constraint")

        kept: list[Point] = []
        rejected: list[Point] = []
        details: list[str] = []
        for index, candidate in enumerate(candidates, start=1):
            equation = sp.Eq(parabola.subs(x, candidate[0]), candidate[1])
            solutions = kernel.solve_equations([equation], [parameter])
            valid_solutions = [
                sp.simplify(solution[parameter])
                for solution in solutions
                if parameter in solution and _satisfies_constraint(solution[parameter], constraint)
            ]
            if valid_solutions:
                kept.append(candidate)
                details.append(
                    f"{target.name}{index}: {parameter.name}="
                    + " 或 ".join(kernel.sstr(value) for value in valid_solutions)
                )
            else:
                rejected.append(candidate)
                details.append(f"{target.name}{index}: 无满足 {_constraint_text(parameter, constraint, kernel)} 的解")

        outputs = {
            "filtered_candidates": TypedValue("PointList", kept, source=self.method_id),
            "rejected_candidates": TypedValue("PointList", rejected, source=self.method_id),
        }
        if len(kept) == 1:
            outputs["selected_candidate"] = TypedValue("Point", kept[0], source=self.method_id)

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs=outputs,
            checks=[
                _check("at_least_one_candidate_kept", bool(kept), "至少有一个候选点能满足曲线条件"),
                _check(
                    "candidate_filter_completed",
                    len(kept) + len(rejected) == len(candidates),
                    "所有候选点都已完成曲线条件验证",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "用抛物线条件筛选候选点",
                    f"筛选 {target.name} 的可行候选",
                    "把每个候选点代入当前问的二次函数，并结合参数约束判断是否可能在曲线上。",
                    "；".join(details),
                    f"保留 {len(kept)} 个候选点",
                )
            ],
        )


def _satisfies_constraint(
    value: sp.Expr,
    constraint: dict[str, sp.Expr | str] | None,
) -> bool:
    """按当前 Constraint 结构校验一元参数值。

    首版只需要支持 ``>``，因此保持轻量；后续遇到区间或复合约束时再扩展。
    """
    if constraint is None:
        return True
    if str(constraint.get("operator", "")) != ">":
        return True
    try:
        return bool(sp.simplify(value - sp.sympify(constraint["value"])) > 0)
    except TypeError:
        return False


def _constraint_text(
    parameter: sp.Symbol,
    constraint: dict[str, sp.Expr | str] | None,
    kernel: SympyKernel,
) -> str:
    """把参数约束格式化成 trace 中的短文本。"""
    if constraint is None:
        return "题设参数约束"
    operator = str(constraint.get("operator", ""))
    value = constraint.get("value")
    return f"{parameter.name}{operator}{kernel.sstr(value)}"


SPEC = MethodSpecSource(
    method_cls=FilterPointCandidatesByQuadraticCurveMethod,
    title="用二次函数条件筛选点候选",
    summary="输入: 候选点与抛物线；输出: 在抛物线上的候选点列表。",
    solves=("filter_point_candidates_by_quadratic_curve",),
    inputs={
        "candidates": {"type": "PointList", "required": True},
        "target": {"type": "PointRef", "required": True},
        "parabola": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "parameter_constraint": {"type": "Constraint", "required": False},
    },
    outputs={
        "filtered_candidates": "PointList",
        "rejected_candidates": "PointList",
        "selected_candidate": "Point",
    },
    preconditions=("parabola 已代入当前问能确定的已知条件", "candidates 来自几何构造"),
    postconditions=("filtered_candidates 中每个候选在参数约束下可满足曲线条件", "若唯一保留候选，则 selected_candidate 为该候选点"),
)
