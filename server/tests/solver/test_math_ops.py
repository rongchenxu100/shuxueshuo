"""``math_ops`` 模块的单元测试。

覆盖所有公开的纯数学建筑块，使用初中题常见的整数/有理数实例。
每个测试函数对应 ``math_ops.py`` 中的一个或一组函数。

运行::

    cd server && uv run pytest tests/solver/test_math_ops.py -v
"""

import sympy as sp
import pytest

from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.math_ops import (
    axis_x_from_relation,
    dot_from_origin,
    parametric_point_on_line,
    pick_by_lower_bound,
    pick_positive,
    point_collinear,
    point_complexity_score,
    reflect_point_across_line,
    rotated_equal_length_point,
    rotated_point_on_parabola,
    satisfies_lower_bound,
    simplify_abs_by_constraints,
    solve_coefficients_from_curve_points,
    solve_missing_coefficients,
    subs_point,
    substitute_known_coefficients,
    vertex_of_quadratic,
    y_axis_intercept,
)


@pytest.fixture()
def kernel() -> SympyKernel:
    return SympyKernel()


@pytest.fixture()
def abc(kernel: SympyKernel) -> dict[str, sp.Symbol]:
    return kernel.symbols(["x", "a", "b", "c", "m"])


# ---------------------------------------------------------------------------
# 二次函数系数操作
# ---------------------------------------------------------------------------


class TestSubstituteKnownCoefficients:
    """代入已知系数并展开。"""

    def test_partial_substitution(self, kernel: SympyKernel, abc: dict) -> None:
        """a=2, c=-5 代入 a*x²+b*x+c → 2*x²+b*x-5。"""
        x, a, b, c = abc["x"], abc["a"], abc["b"], abc["c"]
        quadratic = a * x**2 + b * x + c
        result = substitute_known_coefficients(kernel, quadratic, {a: sp.Integer(2), c: sp.Integer(-5)})
        assert result == 2 * x**2 + b * x - 5

    def test_full_substitution(self, kernel: SympyKernel, abc: dict) -> None:
        """全部代入得到纯数值多项式。"""
        x, a, b, c = abc["x"], abc["a"], abc["b"], abc["c"]
        quadratic = a * x**2 + b * x + c
        result = substitute_known_coefficients(kernel, quadratic, {a: sp.Integer(1), b: sp.Integer(-2), c: sp.Integer(3)})
        assert result == x**2 - 2 * x + 3


class TestSolveMissingCoefficients:
    """利用系数关系求缺失系数。"""

    def test_solve_b_from_relation(self, kernel: SympyKernel, abc: dict) -> None:
        """已知 a=2, c=-5，关系 2a+b=0 → b=-4。"""
        a, b, c = abc["a"], abc["b"], abc["c"]
        relation = sp.Eq(2 * a + b, 0)
        known = {a: sp.Integer(2), c: sp.Integer(-5)}
        result = solve_missing_coefficients(kernel, relation, known, [a, b, c])
        assert result[b] == -4
        assert result[a] == 2
        assert result[c] == -5

    def test_rejects_when_relation_does_not_determine_all_coefficients(
        self,
        kernel: SympyKernel,
        abc: dict,
    ) -> None:
        """只知道 a 和 2a+b=0 时，c 仍未确定，不能返回半成品。"""
        a, b, c = abc["a"], abc["b"], abc["c"]
        relation = sp.Eq(2 * a + b, 0)

        with pytest.raises(ValueError, match="不足以确定所有缺失系数"):
            solve_missing_coefficients(kernel, relation, {a: sp.Integer(2)}, [a, b, c])

    def test_rejects_inconsistent_known_coefficients(
        self,
        kernel: SympyKernel,
        abc: dict,
    ) -> None:
        """已知 a=2,b=0 与 2a+b=0 矛盾。"""
        a, b, c = abc["a"], abc["b"], abc["c"]
        relation = sp.Eq(2 * a + b, 0)

        with pytest.raises(ValueError, match="系数关系无解"):
            solve_missing_coefficients(
                kernel,
                relation,
                {a: sp.Integer(2), b: sp.Integer(0)},
                [a, b, c],
            )

    def test_rejects_multiple_candidate_coefficients(
        self,
        kernel: SympyKernel,
        abc: dict,
    ) -> None:
        """b²=4 会给出 b=±2，不满足唯一确定。"""
        a, b, c = abc["a"], abc["b"], abc["c"]
        relation = sp.Eq(b**2 - 4, 0)

        with pytest.raises(ValueError, match="不能唯一确定缺失系数"):
            solve_missing_coefficients(
                kernel,
                relation,
                {a: sp.Integer(2), c: sp.Integer(-5)},
                [a, b, c],
            )


class TestAxisXFromRelation:
    """由系数关系求对称轴 x 坐标。"""

    def test_2a_plus_b_equals_0(self, kernel: SympyKernel, abc: dict) -> None:
        """2a+b=0 → 对称轴 x = -b/(2a) = 1。"""
        a, b = abc["a"], abc["b"]
        relation = sp.Eq(2 * a + b, 0)
        assert axis_x_from_relation(kernel, relation, a, b) == 1


class TestVertexOfQuadratic:
    """求二次函数顶点。"""

    def test_standard_parabola(self, abc: dict) -> None:
        """y = x²-2x+3 顶点为 (1, 2)。"""
        x = abc["x"]
        vx, vy = vertex_of_quadratic(x**2 - 2 * x + 3, x)
        assert vx == 1
        assert vy == 2

    def test_negative_leading_coefficient(self, abc: dict) -> None:
        """y = -x²+4x-1 顶点为 (2, 3)。"""
        x = abc["x"]
        vx, vy = vertex_of_quadratic(-x**2 + 4 * x - 1, x)
        assert vx == 2
        assert vy == 3


class TestYAxisIntercept:
    """求与 y 轴交点。"""

    def test_intercept(self, abc: dict) -> None:
        """y = x²-2x+3 与 y 轴交于 (0, 3)。"""
        x = abc["x"]
        px, py = y_axis_intercept(x**2 - 2 * x + 3, x)
        assert px == 0
        assert py == 3


# ---------------------------------------------------------------------------
# 直角等腰旋转求点
# ---------------------------------------------------------------------------


class TestRotatedEqualLengthPoint:
    """旋转 ±90° 得等腰直角三角形第三点。"""

    def test_simple_rotation(self, kernel: SympyKernel) -> None:
        """anchor=(1,0), reference=(3,1) → 旋转 90° 候选之一应为 (2,-1)。"""
        result = rotated_equal_length_point(kernel, (sp.Integer(1), sp.Integer(0)), (sp.Integer(3), sp.Integer(1)))
        assert sp.simplify(result[0] - 2) == 0 or sp.simplify(result[0]) == 0

    def test_quadrant_filter(self, kernel: SympyKernel, abc: dict) -> None:
        """带象限提示时应选出第四象限的候选。"""
        m = abc["m"]
        anchor = (sp.Integer(1), sp.Integer(0))
        reference = (m, sp.Integer(1))
        result = rotated_equal_length_point(
            kernel, anchor, reference,
            quadrant_hint="第四象限",
            probe_symbol=m,
            probe_lower_bound=sp.Integer(2),
        )
        probe = {m: sp.Integer(3)}
        assert sp.N(result[0].subs(probe)) > 0
        assert sp.N(result[1].subs(probe)) < 0


class TestRotatedPointOnParabola:
    """旋转点需要同时在抛物线上。"""

    def test_hexi_style_rotation(self, kernel: SympyKernel) -> None:
        """a=2, anchor=(-1,0), reference=(0,c)，旋转后 D 在抛物线上。"""
        symbols = kernel.symbols(["x", "b", "c"])
        x, b, c = symbols["x"], symbols["b"], symbols["c"]
        quadratic = 2 * x**2 - b * x + c
        anchor = (sp.Integer(-1), sp.Integer(0))
        reference = (sp.Integer(0), c)
        result = rotated_point_on_parabola(
            kernel, quadratic, x, anchor, reference, [b, c],
            constraints={"b": ">0"}, symbols=symbols,
        )
        assert "point" in result
        assert "solution" in result
        assert sp.simplify(result["solution"][b]) > 0


# ---------------------------------------------------------------------------
# 联立求系数
# ---------------------------------------------------------------------------


class TestSolveCoefficientsFromCurvePoints:
    """联立点在曲线上求系数。"""

    def test_two_points_plus_relation(self, kernel: SympyKernel, abc: dict) -> None:
        """(1,0) 和 (2,1) 在 ax²+bx+c 上，加关系 2a+b=0，求 a,b,c。"""
        x, a, b, c = abc["x"], abc["a"], abc["b"], abc["c"]
        quadratic = a * x**2 + b * x + c
        points = [(sp.Integer(1), sp.Integer(0)), (sp.Integer(2), sp.Integer(1))]
        relation = sp.Eq(2 * a + b, 0)
        result = solve_coefficients_from_curve_points(
            kernel, quadratic, x, points, [relation], [a, b, c],
        )
        assert a in result and b in result and c in result
        for px, py in points:
            assert sp.simplify(
                result[a] * px**2 + result[b] * px + result[c] - py
            ) == 0


# ---------------------------------------------------------------------------
# 候选解筛选
# ---------------------------------------------------------------------------


class TestPickByLowerBound:
    """按下界筛选候选解。"""

    def test_picks_valid_candidate(self) -> None:
        assert pick_by_lower_bound([sp.Integer(1), sp.Integer(5)], sp.Integer(2)) == 5

    def test_no_bound_picks_first(self) -> None:
        assert pick_by_lower_bound([sp.Integer(3), sp.Integer(7)], None) == 3

    def test_raises_when_none_valid(self) -> None:
        with pytest.raises(ValueError, match="无候选解"):
            pick_by_lower_bound([sp.Integer(1)], sp.Integer(5))


class TestPickPositive:
    """选取正值候选解。"""

    def test_picks_positive(self) -> None:
        assert pick_positive([sp.Integer(-2), sp.Integer(3)]) == 3

    def test_raises_when_all_negative(self) -> None:
        with pytest.raises(ValueError, match="无正值"):
            pick_positive([sp.Integer(-1), sp.Integer(-2)])


class TestSatisfiesLowerBound:
    """下界判定。"""

    def test_above_bound(self) -> None:
        assert satisfies_lower_bound(sp.Integer(5), sp.Integer(2)) is True

    def test_below_bound(self) -> None:
        assert satisfies_lower_bound(sp.Integer(1), sp.Integer(2)) is False

    def test_no_bound(self) -> None:
        assert satisfies_lower_bound(sp.Integer(-1), None) is True


# ---------------------------------------------------------------------------
# 向量与共线
# ---------------------------------------------------------------------------


class TestDotFromOrigin:
    """向量点积。"""

    def test_perpendicular_vectors(self) -> None:
        """(0,0)→(1,0) 和 (0,0)→(0,1) 正交 → 点积为 0。"""
        origin = (sp.Integer(0), sp.Integer(0))
        assert dot_from_origin(origin, (sp.Integer(1), sp.Integer(0)), (sp.Integer(0), sp.Integer(1))) == 0

    def test_parallel_vectors(self) -> None:
        """(0,0)→(1,0) 和 (0,0)→(2,0) 平行 → 点积为 2。"""
        origin = (sp.Integer(0), sp.Integer(0))
        assert dot_from_origin(origin, (sp.Integer(1), sp.Integer(0)), (sp.Integer(2), sp.Integer(0))) == 2


class TestPointCollinear:
    """共线判定。"""

    def test_collinear_points(self) -> None:
        assert point_collinear((sp.Integer(2), sp.Integer(2)), (sp.Integer(0), sp.Integer(0)), (sp.Integer(4), sp.Integer(4))) is True

    def test_non_collinear_points(self) -> None:
        assert point_collinear((sp.Integer(1), sp.Integer(2)), (sp.Integer(0), sp.Integer(0)), (sp.Integer(4), sp.Integer(4))) is False


class TestSubsPoint:
    """点坐标代入。"""

    def test_substitution(self) -> None:
        m = sp.Symbol("m", real=True)
        point = (m + 1, 2 * m)
        result = subs_point(point, {m: sp.Integer(3)})
        assert result == (4, 6)


class TestLinePointTransforms:
    """直线参数点与轴对称。"""

    def test_parametric_point_on_line(self) -> None:
        """过 (1,0)、(3,2) 的通用点应为 (1+2t, 2t)。"""
        t = sp.Symbol("t", real=True)
        point = parametric_point_on_line((sp.Integer(1), sp.Integer(0)), (sp.Integer(3), sp.Integer(2)), t)
        assert point == (1 + 2 * t, 2 * t)

    def test_reflect_point_across_horizontal_line(self) -> None:
        """点 (2,3) 关于 x 轴对称为 (2,-3)。"""
        point = reflect_point_across_line(
            (sp.Integer(2), sp.Integer(3)),
            (sp.Integer(0), sp.Integer(0)),
            (sp.Integer(4), sp.Integer(0)),
        )
        assert point == (2, -3)

    def test_point_complexity_score_prefers_simpler_point(self, kernel: SympyKernel) -> None:
        """简单坐标点的复杂度应低于含分式表达式的坐标点。"""
        m = sp.Symbol("m", real=True)
        simple = (m + 1, 2 - m)
        complex_point = (m / 2 + sp.Rational(3, 2), sp.Rational(3, 2) - m)

        assert point_complexity_score(simple, kernel) < point_complexity_score(complex_point, kernel)


# ---------------------------------------------------------------------------
# 绝对值化简
# ---------------------------------------------------------------------------


class TestSimplifyAbsByConstraints:
    """利用约束去除 Abs。"""

    def test_removes_abs_when_positive(self, kernel: SympyKernel) -> None:
        """b>0 时 Abs(b+1) = b+1。"""
        symbols = kernel.symbols(["b"])
        b = symbols["b"]
        expr = sp.Abs(b + 1)
        result = simplify_abs_by_constraints(expr, {"b": ">0"}, kernel, symbols)
        assert result == b + 1

    def test_keeps_abs_when_unknown(self, kernel: SympyKernel) -> None:
        """无约束时 Abs 保留。"""
        symbols = kernel.symbols(["b"])
        b = symbols["b"]
        expr = sp.Abs(b - 5)
        result = simplify_abs_by_constraints(expr, {}, kernel, symbols)
        assert result.has(sp.Abs)
