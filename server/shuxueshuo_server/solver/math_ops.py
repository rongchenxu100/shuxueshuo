"""可复用的数学建筑块（Layer 2）。

本模块包含的函数都是**纯数学操作**：输入和输出均为 SymPy 表达式或数值，
完全不依赖 ``SolveContext``、fixture 结构或任何 IO 格式。

这一层介于 ``SympyKernel``（原子操作）与各 Method/RuntimeContext（问题编排）
之间：
- ``SympyKernel``：solve、simplify、distance 等通用数学原语。
- ``math_ops``：由若干原语组合成的**初中几何/代数常见动作**，
  如"代入已知系数得抛物线"、"旋转求直角等腰第三点"、"按定义域筛选候选解"。
- **Method / RuntimeContext**：读取上下文 → 调用 math_ops → 写入结果。

命名惯例:
- ``substitute_*``：代入操作。
- ``solve_*``：求解操作，返回解表达式。
- ``pick_*``：从多个候选中筛选。
- ``compute_*``：计算某个中间量。
- ``rotated_*``：涉及旋转变换。

所有函数均无副作用，可独立单测。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.math_kernel import SympyKernel


# ---------------------------------------------------------------------------
# 二次函数系数操作
# ---------------------------------------------------------------------------


def substitute_known_coefficients(
    kernel: SympyKernel,
    quadratic: sp.Expr,
    known: dict[sp.Symbol, sp.Expr],
) -> sp.Expr:
    """将已知系数代入二次函数并展开。

    例如已知 a=2, c=-5，代入 a*x**2 + b*x + c 得到 2*x**2 + b*x - 5。
    """
    return sp.expand(quadratic.subs(known))


def solve_missing_coefficients(
    kernel: SympyKernel,
    relation: sp.Equality,
    known: dict[sp.Symbol, sp.Expr],
    all_coefficients: Sequence[sp.Symbol],
) -> dict[sp.Symbol, sp.Expr]:
    """利用系数关系式求解缺失系数。

    给定已知系数和一条系数关系（如 2a+b=0），找出 all_coefficients 中
    尚未确定的符号并联立求解。返回 {已知 + 求出} 的完整字典。
    """
    known = dict(known)
    missing = [s for s in all_coefficients if s not in known]
    if not missing:
        if _equation_is_satisfied(relation.subs(known)):
            return known
        raise ValueError(f"已知系数与系数关系矛盾: {relation}, 已知: {known}")
    solved = kernel.solve_equations([relation.subs(known)], missing)
    if not solved:
        raise ValueError(f"系数关系无解: {relation}, 已知: {known}")
    if len(solved) != 1:
        raise ValueError(f"系数关系不能唯一确定缺失系数: {relation}, 已知: {known}")
    solution = solved[0]
    still_missing = [symbol for symbol in missing if symbol not in solution]
    if still_missing:
        names = ", ".join(symbol.name for symbol in still_missing)
        raise ValueError(f"系数关系不足以确定所有缺失系数: {names}")
    values = {**known, **solution}
    unresolved = [
        symbol
        for symbol in all_coefficients
        if any(sp.sympify(values[target]).has(symbol) for target in all_coefficients)
    ]
    if unresolved:
        names = ", ".join(symbol.name for symbol in unresolved)
        raise ValueError(f"求得系数仍依赖未定系数: {names}")
    if not _equation_is_satisfied(relation.subs(values)):
        raise ValueError(f"求得系数不满足系数关系: {relation}, 求得: {values}")
    return values


def _equation_is_satisfied(equation: object) -> bool:
    """判断一个已代入后的方程是否成立。

    SymPy 在 ``Eq(4, 0)`` 这类场景会直接返回 ``False``，而不是 Equality；
    这里统一处理 ``True/False``、``Equality`` 和普通表达式三种形态。
    """
    if equation in (True, sp.S.true):
        return True
    if equation in (False, sp.S.false):
        return False
    if isinstance(equation, sp.Equality):
        return sp.simplify(equation.lhs - equation.rhs) == 0
    return sp.simplify(equation) == 0


def axis_x_from_relation(
    kernel: SympyKernel,
    relation: sp.Equality,
    a: sp.Symbol,
    b: sp.Symbol,
) -> sp.Expr:
    """由系数关系求抛物线对称轴的 x 坐标。

    对称轴公式 x = -b/(2a)，先从关系式中解出 b 关于 a 的表达式，
    再代入得到通用对称轴位置。
    """
    generic_b = kernel.solve_equations([relation], [b])[0][b]
    return sp.simplify((-b / (2 * a)).subs(b, generic_b))


def vertex_of_quadratic(
    quadratic: sp.Expr,
    x: sp.Symbol,
) -> tuple[sp.Expr, sp.Expr]:
    """求二次函数的顶点坐标。

    对 y = Ax² + Bx + C，顶点横坐标为 -B/(2A)，纵坐标代入即得。
    """
    poly = sp.Poly(quadratic, x)
    a2 = poly.coeff_monomial(x**2)
    a1 = poly.coeff_monomial(x)
    vertex_x = sp.simplify(-a1 / (2 * a2))
    return (vertex_x, sp.simplify(quadratic.subs(x, vertex_x)))


def y_axis_intercept(
    quadratic: sp.Expr,
    x: sp.Symbol,
) -> tuple[sp.Expr, sp.Expr]:
    """求二次函数与 y 轴的交点 (0, c)。"""
    return (sp.Integer(0), sp.simplify(quadratic.subs(x, 0)))


# ---------------------------------------------------------------------------
# 直角等腰旋转求点
# ---------------------------------------------------------------------------


def rotated_equal_length_point(
    kernel: SympyKernel,
    anchor: tuple[sp.Expr, sp.Expr],
    reference: tuple[sp.Expr, sp.Expr],
    *,
    quadrant_hint: str = "",
    probe_symbol: sp.Symbol | None = None,
    probe_lower_bound: sp.Expr | None = None,
) -> tuple[sp.Expr, sp.Expr]:
    """将 reference 绕 anchor 旋转 ±90°，得到等腰直角三角形的第三点。

    旋转有两个候选方向（顺时针和逆时针），通过 ``quadrant_hint``
    （如 "第四象限"）或默认取第一个来选择。

    当点坐标含参数时，用 ``probe_symbol`` 和 ``probe_lower_bound``
    代入一个探测值来判断象限。
    """
    candidates = rotated_equal_length_candidates(kernel, anchor, reference)
    if quadrant_hint:
        matching = [
            c for c in candidates
            if _matches_quadrant(
                c, quadrant_hint, probe_symbol, probe_lower_bound,
            )
        ]
        if matching:
            return matching[0]
    return candidates[0]


def rotated_equal_length_candidates(
    kernel: SympyKernel,
    anchor: tuple[sp.Expr, sp.Expr],
    reference: tuple[sp.Expr, sp.Expr],
) -> list[tuple[sp.Expr, sp.Expr]]:
    """将 reference 绕 anchor 顺/逆时针旋转 90°，返回两个候选点。

    这个函数只负责列出直角等腰条件给出的两个数学候选，不根据象限、曲线、
    参数范围等题设条件筛选。候选筛选应该由更具体的 method 显式完成。
    """
    vx = sp.simplify(reference[0] - anchor[0])
    vy = sp.simplify(reference[1] - anchor[1])
    return [
        (sp.simplify(anchor[0] + vy), sp.simplify(anchor[1] - vx)),
        (sp.simplify(anchor[0] - vy), sp.simplify(anchor[1] + vx)),
    ]


def rotated_point_on_parabola(
    kernel: SympyKernel,
    quadratic: sp.Expr,
    x: sp.Symbol,
    anchor: tuple[sp.Expr, sp.Expr],
    reference: tuple[sp.Expr, sp.Expr],
    unknowns: list[sp.Symbol],
    constraints: Mapping[str, str] | None = None,
    symbols: Mapping[str, sp.Symbol] | None = None,
) -> dict:
    """旋转 ±90° 求抛物线上满足直角等腰条件的点及对应系数。

    和 ``rotated_equal_length_point`` 不同，这里同时需要：
    1. 旋转后的点在抛物线上
    2. 求解出未知系数使得约束成立

    返回 ``{"point": (x, y), "solution": {symbol: value}}``。
    """
    vx = sp.simplify(reference[0] - anchor[0])
    vy = sp.simplify(reference[1] - anchor[1])
    candidates = [
        (sp.simplify(anchor[0] - vy), sp.simplify(anchor[1] + vx)),
        (sp.simplify(anchor[0] + vy), sp.simplify(anchor[1] - vx)),
    ]
    anchor_eq = sp.Eq(quadratic.subs(x, anchor[0]), anchor[1])
    for candidate in candidates:
        derived_eq = sp.Eq(quadratic.subs(x, candidate[0]), candidate[1])
        for solution in kernel.solve_equations(
            [anchor_eq, derived_eq], unknowns,
        ):
            if _solution_satisfies_constraints(
                solution, constraints or {}, kernel, symbols or {},
            ):
                return {
                    "point": (
                        sp.simplify(candidate[0].subs(solution)),
                        sp.simplify(candidate[1].subs(solution)),
                    ),
                    "solution": solution,
                }
    raise ValueError("旋转后无满足约束的抛物线上的点")


# ---------------------------------------------------------------------------
# 点在曲线上建方程 & 联立求系数
# ---------------------------------------------------------------------------


def solve_coefficients_from_curve_points(
    kernel: SympyKernel,
    quadratic: sp.Expr,
    x: sp.Symbol,
    points: list[tuple[sp.Expr, sp.Expr]],
    extra_equations: list[sp.Expr | sp.Equality],
    unknowns: list[sp.Symbol],
) -> dict[sp.Symbol, sp.Expr]:
    """联立"点在曲线上"方程 + 额外方程，求解系数。

    典型场景：M、N 在抛物线上 + 系数关系 2a+b=0 → 联立求 a,b,c。
    """
    point_eqs = [
        sp.Eq(quadratic.subs(x, px), py) for px, py in points
    ]
    solutions = kernel.solve_equations(
        [*extra_equations, *point_eqs], unknowns,
    )
    if not solutions:
        raise ValueError(f"联立方程无解: {len(point_eqs)} 个点方程 + {len(extra_equations)} 条额外方程")
    return solutions[0]


# ---------------------------------------------------------------------------
# 候选解筛选
# ---------------------------------------------------------------------------


def pick_by_lower_bound(
    candidates: list[sp.Expr],
    lower_bound: sp.Expr | None,
) -> sp.Expr:
    """从候选解中选取满足下界约束（> lower_bound）的第一个。

    如果没有下界约束，返回化简后的第一个候选。
    """
    if lower_bound is None:
        if not candidates:
            raise ValueError("候选解列表为空")
        return sp.simplify(candidates[0])
    valid = [
        sp.simplify(c) for c in candidates
        if sp.simplify(c - lower_bound) > 0
    ]
    if not valid:
        raise ValueError(f"无候选解大于 {lower_bound}: {candidates}")
    return valid[0]


def pick_positive(candidates: list[sp.Expr]) -> sp.Expr:
    """从候选解中选取严格正值。"""
    for c in candidates:
        simplified = sp.simplify(c)
        if _satisfies_positive(simplified):
            return simplified
    raise ValueError(f"无正值候选解: {candidates}")


def satisfies_lower_bound(
    value: sp.Expr,
    lower_bound: sp.Expr | None,
) -> bool:
    """判断 value 是否严格大于 lower_bound。"""
    if lower_bound is None:
        return True
    return bool(sp.simplify(value - lower_bound) > 0)


# ---------------------------------------------------------------------------
# 向量与共线判定
# ---------------------------------------------------------------------------


def dot_from_origin(
    origin: tuple[sp.Expr, sp.Expr],
    p1: tuple[sp.Expr, sp.Expr],
    p2: tuple[sp.Expr, sp.Expr],
) -> sp.Expr:
    """以 origin 为公共端点，计算向量 (origin→p1) · (origin→p2)。

    结果为零说明两向量垂直。
    """
    return sp.simplify(
        (p1[0] - origin[0]) * (p2[0] - origin[0])
        + (p1[1] - origin[1]) * (p2[1] - origin[1])
    )


def point_collinear(
    p: tuple[sp.Expr, sp.Expr],
    a: tuple[sp.Expr, sp.Expr],
    b: tuple[sp.Expr, sp.Expr],
) -> bool:
    """判断点 p 是否在直线 AB 上（叉积为零）。"""
    cross = (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])
    return sp.simplify(cross) == 0


def subs_point(
    point: tuple[sp.Expr, sp.Expr],
    substitutions: Mapping[sp.Symbol, sp.Expr],
) -> tuple[sp.Expr, sp.Expr]:
    """对点的两个坐标统一做符号替换并化简。"""
    return (
        sp.simplify(point[0].subs(substitutions)),
        sp.simplify(point[1].subs(substitutions)),
    )


def parametric_point_on_line(
    line_point_1: tuple[sp.Expr, sp.Expr],
    line_point_2: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol | None = None,
) -> tuple[sp.Expr, sp.Expr]:
    """用参数表示一条直线上的通用点。

    默认返回 ``line_point_1 + t * (line_point_2 - line_point_1)``。调用方也可以
    传入自己的参数符号，便于在同一推导里复用外部已经声明的动点参数。
    """
    t = parameter or sp.Symbol("t", real=True)
    return (
        sp.simplify(line_point_1[0] + t * (line_point_2[0] - line_point_1[0])),
        sp.simplify(line_point_1[1] + t * (line_point_2[1] - line_point_1[1])),
    )


def reflect_point_across_line(
    point: tuple[sp.Expr, sp.Expr],
    line_point_1: tuple[sp.Expr, sp.Expr],
    line_point_2: tuple[sp.Expr, sp.Expr],
) -> tuple[sp.Expr, sp.Expr]:
    """计算点关于一条直线的对称点。

    直线由 ``line_point_1``、``line_point_2`` 两点确定。实现上先求垂足投影，再用
    ``reflected = 2 * projection - point`` 得到对称点。
    """
    px, py = point
    ax, ay = line_point_1
    bx, by = line_point_2
    vx = sp.simplify(bx - ax)
    vy = sp.simplify(by - ay)
    denominator = sp.simplify(vx**2 + vy**2)
    if denominator == 0:
        raise ValueError("reflection line requires two distinct points")
    projection_ratio = sp.simplify(((px - ax) * vx + (py - ay) * vy) / denominator)
    projection = (
        sp.simplify(ax + projection_ratio * vx),
        sp.simplify(ay + projection_ratio * vy),
    )
    return (
        sp.simplify(2 * projection[0] - px),
        sp.simplify(2 * projection[1] - py),
    )


def point_complexity_score(
    point: tuple[sp.Expr, sp.Expr],
    kernel: SympyKernel,
) -> int:
    """给点坐标一个稳定的“计算复杂度”分数。

    ``count_ops`` 衡量代数操作数量；字符串长度作为轻微 tie-breaker。这个分数只用于
    在多个等价候选中选择更利于后续计算的形式，不代表数学正确性。
    """
    return int(
        sum(sp.count_ops(coordinate) for coordinate in point) * 100
        + sum(len(kernel.sstr(coordinate)) for coordinate in point)
    )


# ---------------------------------------------------------------------------
# 绝对值化简（利用约束）
# ---------------------------------------------------------------------------


def simplify_abs_by_constraints(
    value: sp.Expr,
    constraints: Mapping[str, str],
    kernel: SympyKernel,
    symbols: Mapping[str, sp.Symbol],
) -> sp.Expr:
    """利用参数约束（如 b>0）去掉表达式中可确定符号的 Abs。

    原理：如果 Abs 内部的表达式在约束下恒正，则 Abs(f) = f。
    通过检查边界值和单调性来判断。
    """
    replacements: dict[sp.Expr, sp.Expr] = {}
    for atom in value.atoms(sp.Abs):
        inner = atom.args[0]
        if _inner_is_positive(inner, constraints, kernel, symbols):
            replacements[atom] = inner
    return sp.simplify(value.xreplace(replacements))


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _satisfies_positive(value: sp.Expr) -> bool:
    """判断表达式是否严格大于零。"""
    try:
        return bool(sp.simplify(value) > 0)
    except TypeError:
        return bool(sp.N(value) > 0)


def _matches_quadrant(
    point: tuple[sp.Expr, sp.Expr],
    quadrant: str,
    probe_symbol: sp.Symbol | None,
    probe_lower_bound: sp.Expr | None,
) -> bool:
    """通过代入探测值判断点是否在指定象限。"""
    if probe_symbol is None:
        return False
    probe_value = sp.simplify((probe_lower_bound or 0) + 1)
    x_probe = sp.N(point[0].subs(probe_symbol, probe_value))
    y_probe = sp.N(point[1].subs(probe_symbol, probe_value))
    if quadrant in ("第一象限", "1", "I"):
        return x_probe > 0 and y_probe > 0
    if quadrant in ("第二象限", "2", "II"):
        return x_probe < 0 and y_probe > 0
    if quadrant in ("第三象限", "3", "III"):
        return x_probe < 0 and y_probe < 0
    if quadrant in ("第四象限", "4", "IV"):
        return x_probe > 0 and y_probe < 0
    return False


def _solution_satisfies_constraints(
    solution: Mapping[sp.Symbol, sp.Expr],
    constraints: Mapping[str, str],
    kernel: SympyKernel,
    symbols: Mapping[str, sp.Symbol],
) -> bool:
    """检查一组解是否满足所有 >X 形式的约束。"""
    for name, raw in constraints.items():
        if not raw.startswith(">") or name not in symbols:
            continue
        symbol = symbols[name]
        if symbol not in solution:
            continue
        lower_bound = kernel.expr(raw[1:].strip(), dict(symbols))
        if not _satisfies_positive(sp.simplify(solution[symbol] - lower_bound)):
            return False
    return True


def _inner_is_positive(
    inner: sp.Expr,
    constraints: Mapping[str, str],
    kernel: SympyKernel,
    symbols: Mapping[str, sp.Symbol],
) -> bool:
    """检查 Abs 内部表达式在约束下是否恒正。"""
    for name, raw in constraints.items():
        if not raw.startswith(">") or name not in symbols:
            continue
        symbol = symbols[name]
        if symbol not in inner.free_symbols:
            continue
        lower_bound = kernel.expr(raw[1:].strip(), dict(symbols))
        derivative = sp.diff(inner, symbol)
        boundary_value = sp.simplify(inner.subs(symbol, lower_bound))
        if _satisfies_positive(derivative) and _satisfies_positive(boundary_value):
            return True
    return False
