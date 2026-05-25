"""quadratic_axis_from_relation 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class QuadraticAxisFromRelationMethod:
    """由二次函数系数关系求对称轴与 x 轴交点。"""

    method_id = "quadratic_axis_from_relation"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        relation = inputs["coefficient_relation"]
        a = inputs["a"]
        b = inputs["b"]
        target: PointRef = inputs["target"]
        free_symbols = relation.free_symbols
        if a not in free_symbols or b not in free_symbols:
            # 这个 method 解决的是“由 a、b 的比例关系确定对称轴”。如果题设只给
            # a、c 关系，或者只给 b 的常数值，都无法推出稳定的 -b/(2a)。
            raise ValueError(
                "quadratic_axis_from_relation requires a coefficient relation involving both a and b"
            )
        b_solutions = sp.solve(relation, b)
        if not b_solutions:
            raise ValueError(
                "quadratic_axis_from_relation requires relation to be solvable for b"
            )
        axis_x = sp.simplify((-b / (2 * a)).subs(b, b_solutions[0]))
        if axis_x.has(a) or axis_x.has(b):
            # 即便能解出 b，如果代回后对称轴仍依赖 a 或 b，说明关系没有确定 b/a。
            # 例如 b+c=0 会得到 x=c/(2a)，仍然不是一个可落地的对称轴结论。
            raise ValueError(
                "quadratic_axis_from_relation requires relation to determine b/a ratio"
            )
        point = (axis_x, sp.Integer(0))
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"axis_point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check("axis_point_on_x_axis", point[1] == 0, f"{target.name} 在 x 轴上"),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    f"由系数关系确定 {target.name}",
                    "确定对称轴与 x 轴交点",
                    "二次函数对称轴为 x=-b/(2a)，再代入题设系数关系。",
                    f"x={kernel.sstr(axis_x)}",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=QuadraticAxisFromRelationMethod,
    title='由系数关系求对称轴交点',
    solves=('derive_axis_point',),
    inputs={
    "coefficient_relation": {
        "type": "Equation",
        "required": True
    },
    "a": {
        "type": "Symbol",
        "required": True
    },
    "b": {
        "type": "Symbol",
        "required": True
    },
    "target": {
        "type": "PointRef",
        "required": True
    }
},
    outputs={
    "axis_point": "Point"
},
    preconditions=('coefficient_relation 必须包含二次项系数 a 和一次项系数 b', 'coefficient_relation 解出 b 后，-b/(2a) 不能再依赖 a 或 b；也就是关系必须能确定 b/a 的比值'),
    postconditions=(),
    trace_template=(),
)
