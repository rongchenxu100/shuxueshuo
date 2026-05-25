"""SymPy 符号计算内核的薄封装层。

本模块为 Method Solver 提供统一的符号运算入口，避免在各解题方法中散落
``sympy`` 的直接调用。封装目标：

- **接口稳定**：方法名与参数形状固定，便于单测与后续替换实现。
- **语义明确**：每个方法对应初中题常见的代数/几何操作（化简、联立、
  点在曲线上、距离、直线交点等）。
- **默认实数符号**：``symbols()`` 创建的符号带 ``real=True``，减少
  复数根干扰初中题筛选。

调用方应通过 ``SympyKernel`` 实例访问能力，而不是在业务代码里 ``import sympy``。
"""

from __future__ import annotations

from typing import Iterable, Sequence

import sympy as sp


class SympyKernel:
    """SymPy 符号运算门面，供 solver 各 method 复用。

    设计原则：
    - 输入尽量接受字符串、已有 ``Expr`` 或混合形式，由 ``expr()`` 统一解析。
    - 输出在可能时做 ``simplify``，便于 ``verify_equivalent`` 与断言比较。
    - 不缓存全局状态；每次 ``SympyKernel()`` 可视为无状态工具对象。
    """

    def symbols(self, names: Iterable[str]) -> dict[str, sp.Symbol]:
        """按名称批量创建**实数**符号，并返回 ``名称 -> Symbol`` 字典。

        实数假设适合多数中考参数题（如 ``a, b, c, x, y``），避免
        ``solve`` 返回未被过滤的复数解。

        Args:
            names: 符号名字符串序列，如 ``["x", "y", "b"]``。

        Returns:
            例如 ``{"x": Symbol('x', real=True), ...}``。
        """
        return {name: sp.Symbol(name, real=True) for name in names}

    def expr(self, value: object, locals_: dict[str, sp.Symbol] | None = None) -> sp.Expr:
        """将 Python 对象或字符串解析为 SymPy 表达式。

        ``locals_`` 传入 ``symbols()`` 的字典时，字符串中的标识符会绑定到
        对应符号，例如 ``expr("x**2 + b*x", {"x": x, "b": b})``。

        Args:
            value: 已是 ``Expr``、数值、或形如 ``"x**2 - 2*x"`` 的字符串。
            locals_: 符号环境；为 ``None`` 时使用空环境。

        Returns:
            解析后的 ``sp.Expr``。
        """
        return sp.sympify(value, locals=locals_ or {})

    def simplify_expr(self, value: object, locals_: dict[str, sp.Symbol] | None = None) -> sp.Expr:
        """先 ``expr()`` 再 ``simplify``，得到化简后的表达式。

        用于推导链展示、等价性检查前的标准形。

        Args:
            value: 待化简对象，语义同 ``expr()``。
            locals_: 符号环境，语义同 ``expr()``。

        Returns:
            化简后的 ``sp.Expr``。
        """
        return sp.simplify(self.expr(value, locals_))

    def solve_equations(
        self,
        equations: Sequence[sp.Equality | sp.Expr],
        symbols: Sequence[sp.Symbol],
    ) -> list[dict[sp.Symbol, sp.Expr]]:
        """联立求解方程组，返回字典解列表。

        内部调用 ``sympy.solve(..., dict=True)``。若方程为 ``Expr`` 而非
        ``Equality``，SymPy 按表达式等于零处理。

        Args:
            equations: 方程序列，如 ``[Eq(x+y, 10), Eq(x-y, 2)]`` 或
                ``[x+y-10, x-y-2]``。
            symbols: 要求解的未知元顺序，影响解的呈现形式。

        Returns:
            解的列表，每个元素为 ``{符号: 表达式}``。无解或符号不足时
            可能为空列表，调用方需自行判断。

        Example:
            对方程组 ``x+y=10, x-y=2`` 返回 ``[{x: 6, y: 4}]``。
        """
        return list(sp.solve(list(equations), list(symbols), dict=True))

    def solve_values(
        self,
        equation: sp.Equality | sp.Expr,
        symbol: sp.Symbol,
    ) -> list[sp.Expr]:
        """对单未知元求解，返回所有根的列表（未去重、未过滤范围）。

        适合一元二次求参、直线与抛物线交点横坐标等。若需实根或区间筛选，
        应在 method 层根据题意再过滤。

        Args:
            equation: 单个方程。
            symbol: 要求解的未知元。

        Returns:
            根表达式列表，可能含参数解、多值或空列表。
        """
        return list(sp.solve(equation, symbol))

    def verify_equivalent(
        self,
        left: object,
        right: object,
        locals_: dict[str, sp.Symbol] | None = None,
    ) -> bool:
        """判断两式是否恒等（化简差为零）。

        用于验算：学生推导结果 vs 标准答案、中间步合并是否正确。

        Args:
            left: 左式，字符串或 ``Expr``。
            right: 右式，字符串或 ``Expr``。
            locals_: 符号环境。

        Returns:
            ``True`` 当 ``simplify(left - right) == 0``。
        """
        return sp.simplify(self.expr(left, locals_) - self.expr(right, locals_)) == 0

    def point_on_curve(
        self,
        point: tuple[object, object],
        curve_expr: object,
        x_symbol: sp.Symbol,
        locals_: dict[str, sp.Symbol] | None = None,
    ) -> bool:
        """判断平面点 ``(x, y)`` 是否在曲线 ``y = curve_expr(x)`` 上。

        将点的纵坐标与曲线在点横坐标处的值作差并化简；适用于
        ``y = ax^2 + bx + c`` 等显式函数。参数曲线需先化为显式形式。

        Args:
            point: ``(x坐标, y坐标)``，坐标可为数值或含参表达式。
            curve_expr: 关于 ``x_symbol`` 的纵坐标表达式。
            x_symbol: 曲线自变量符号（通常为 ``x``）。
            locals_: 符号环境。

        Returns:
            点在曲线上为 ``True``，否则 ``False``。
        """
        x_value, y_value = point
        curve = self.expr(curve_expr, locals_)
        return sp.simplify(self.expr(y_value, locals_) - curve.subs(x_symbol, self.expr(x_value, locals_))) == 0

    def distance_squared(
        self,
        p1: tuple[object, object],
        p2: tuple[object, object],
        locals_: dict[str, sp.Symbol] | None = None,
    ) -> sp.Expr:
        """两点间距离的**平方**（化简后）。

        勾股定理、``AC^2 + BC^2 = AB^2`` 等场景优先用平方，避免
        ``sqrt`` 带来的化简分支。

        Args:
            p1: 第一点 ``(x1, y1)``。
            p2: 第二点 ``(x2, y2)``。
            locals_: 符号环境。

        Returns:
            ``(x1-x2)^2 + (y1-y2)^2`` 的化简表达式。
        """
        x1, y1 = (self.expr(v, locals_) for v in p1)
        x2, y2 = (self.expr(v, locals_) for v in p2)
        return sp.simplify((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def distance(
        self,
        p1: tuple[object, object],
        p2: tuple[object, object],
        locals_: dict[str, sp.Symbol] | None = None,
    ) -> sp.Expr:
        """两点间欧氏距离（化简后，含 ``sqrt``）。

        Args:
            p1: 第一点 ``(x1, y1)``。
            p2: 第二点 ``(x2, y2)``。
            locals_: 符号环境。

        Returns:
            ``sqrt(distance_squared(...))`` 的化简结果。
        """
        return sp.sqrt(self.distance_squared(p1, p2, locals_))

    def line_intersection(
        self,
        line1: tuple[tuple[object, object], tuple[object, object]],
        line2: tuple[tuple[object, object], tuple[object, object]],
        locals_: dict[str, sp.Symbol] | None = None,
    ) -> tuple[sp.Expr, sp.Expr]:
        """求两条直线（各由两点确定）的交点坐标。

        使用 SymPy ``Line`` 几何对象求交；适用于坐标系中辅助线交点、
        对称轴与直线交点等。

        Args:
            line1: ``((x1,y1), (x2,y2))`` 确定第一条直线。
            line2: 确定第二条直线，格式同上。
            locals_: 符号环境。

        Returns:
            ``(x, y)`` 交点坐标的化简表达式。

        Raises:
            ValueError: 两直线平行或重合、无唯一交点时。
        """
        def point(raw: tuple[object, object]) -> sp.Point:
            """将二元坐标元组转为 SymPy 平面点。"""
            return sp.Point(self.expr(raw[0], locals_), self.expr(raw[1], locals_))

        intersection = sp.Line(point(line1[0]), point(line1[1])).intersection(
            sp.Line(point(line2[0]), point(line2[1]))
        )
        if not intersection:
            raise ValueError("lines do not intersect")
        p = intersection[0]
        return (sp.simplify(p.x), sp.simplify(p.y))

    def sstr(self, value: object) -> str:
        """将表达式化简后转为 SymPy 标准字符串（便于日志与 JSON 输出）。

        与 ``str(expr)`` 相比，``sstr`` 更贴近数学书写习惯；
        输出前统一 ``simplify`` 以减少等价不同形的字符串差异。

        Args:
            value: 任意可 sympify 的对象。

        Returns:
            化简后的字符串表示。
        """
        return sp.sstr(sp.simplify(value))
