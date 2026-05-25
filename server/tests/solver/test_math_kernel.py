"""``SympyKernel`` 单元测试。

覆盖 Method Solver 依赖的核心符号能力：联立与化简、等价验证、
点在抛物线上、距离平方、直线交点。测试使用小规模整数/有理数
实例，便于断言且与初中题常见数值尺度一致。

运行方式（在 ``server/`` 目录下）::

    pytest tests/solver/test_math_kernel.py -v
"""

import sympy as sp

from shuxueshuo_server.solver.math_kernel import SympyKernel


def test_solve_equations_and_simplify() -> None:
    """联立方程组与表达式化简。

    场景对应：由两个线性关系求交点坐标，或由恒等变形验证
    ``x^2 + 2x + 1`` 与 ``(x+1)^2`` 等价。

    断言：
    - ``x+y=10`` 且 ``x-y=2`` 的唯一整数解为 ``(6, 4)``。
    - 完全平方式化简后与展开式差为零。
    """
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "y"])
    x, y = symbols["x"], symbols["y"]

    # dict=True 时返回 [{x: 6, y: 4}] 形式的解列表
    solutions = kernel.solve_equations([sp.Eq(x + y, 10), sp.Eq(x - y, 2)], [x, y])

    assert solutions == [{x: 6, y: 4}]
    # 字符串输入需传入 symbols 环境，否则 "x" 不会被识别为符号 x
    assert sp.simplify(kernel.simplify_expr("x**2 + 2*x + 1", symbols) - (x + 1) ** 2) == 0


def test_verify_equivalent_and_point_on_curve() -> None:
    """恒等式验证与「点是否在抛物线上」。

    场景对应：
    - 因式分解/展开是否等价（验算中间步）。
    - 已知 ``y = x^2 - 2x - 2``，判断 ``(3, 1)`` 在曲线上而 ``(3, 2)`` 不在。

    断言：
    - 因式分解形式与展开式等价。
    - 代入横坐标 3 时纵坐标应为 1，不是 2。
    """
    kernel = SympyKernel()
    symbols = kernel.symbols(["x"])
    x = symbols["x"]

    assert kernel.verify_equivalent("x**2 - 1", "(x - 1)*(x + 1)", symbols)
    # (3, 1): 3^2 - 6 - 2 = 1，在曲线上
    assert kernel.point_on_curve((3, 1), x**2 - 2 * x - 2, x)
    # (3, 2): 纵坐标与曲线值不符
    assert not kernel.point_on_curve((3, 2), x**2 - 2 * x - 2, x)


def test_distance_and_line_intersection() -> None:
    """距离平方与两直线交点。

    场景对应：
    - 勾股/距离公式：``(1,0)`` 到 ``(3,1)`` 的距离平方为 ``1^2+1^2=5``。
    - 坐标几何中求两直线交点（可用有理数精确表示）。

    断言：
    - ``distance_squared`` 避免开方带来的符号分支。
    - ``line_intersection`` 返回与手算一致的交点 ``(4, -13/3)``。
    """
    kernel = SympyKernel()

    assert kernel.distance_squared((1, 0), (3, 1)) == 5
    # 第二条直线使用有理数坐标，检验内核不依赖浮点近似
    assert kernel.line_intersection(((2, -7), (8, 1)), ((9, -6), (sp.Rational(3, 2), sp.Rational(-7, 2)))) == (
        4,
        sp.Rational(-13, 3),
    )
