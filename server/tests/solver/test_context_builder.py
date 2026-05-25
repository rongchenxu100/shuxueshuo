"""``ContextBuilder`` 从 Problem IR 构建 ``RuntimeContext`` 的单元测试。

以 ``tj-2026-nankai-yimo-25`` 为样板，验证 fixture 题意是否被正确搬进
problem / question / subquestion 作用域树，供 V1.5 Planner/Executor 使用。

运行::

    cd server && uv run pytest tests/solver/test_context_builder.py -v
"""

from __future__ import annotations

import sympy as sp
import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.models import PointRef
from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
    QuadraticPathMinimumPlannerV15,
)


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


@pytest.fixture()
def kernel() -> SympyKernel:
    return SympyKernel()


@pytest.fixture()
def problem():
    return load_problem_ir(NANKAI_FIXTURE)


@pytest.fixture()
def context(kernel: SympyKernel, problem):
    return ContextBuilder(kernel).build(problem)


class TestContextBuilderNankaiStructure:
    """南开一模 fixture 的 scope 树与题面元数据。"""

    def test_fixture_no_longer_provides_solver_config_hints(self, problem) -> None:
        assert problem.solver_config == {}

    def test_preserves_problem_identity(self, context, problem) -> None:
        assert context.problem.problem_id == "tj-2026-nankai-yimo-25"
        assert context.problem is problem
        assert context.problem.pattern == "path-minimum"
        assert context.problem.problem_type == "quadratic_path_minimum"

    def test_builds_question_hierarchy(self, context) -> None:
        assert set(context.scopes) == {"problem", "i", "ii", "ii_1", "ii_2"}
        assert context.get_scope("problem").scope_type == "problem"
        assert context.get_scope("i").scope_type == "question"
        assert context.get_scope("ii").scope_type == "question"
        assert context.get_scope("ii_1").scope_type == "subquestion"
        assert context.get_scope("ii_2").parent_id == "ii"

    def test_registers_symbols_and_constraints(self, context) -> None:
        symbols = context.problem_scope.container("symbols")
        assert set(symbols) == {"x", "a", "b", "c", "m"}
        assert symbols["m"].type == "Symbol"

        constraints = context.problem_scope.constraints
        assert constraints["a"].value == {"operator": ">", "value": sp.Integer(0)}
        assert constraints["m"].value == {"operator": ">", "value": sp.Integer(2)}

        coeff_list = context.problem_scope.container("symbol_lists")["quadratic_coefficients"]
        assert {s.name for s in coeff_list.value} == {"a", "b", "c"}


class TestContextBuilderNankaiFunction:
    """整题共享的抛物线表达式与系数关系。"""

    def test_loads_quadratic_expression(self, context, kernel: SympyKernel) -> None:
        expr = context.read_path(
            "$problem.expressions.quadratic",
            from_scope_id="problem",
            expected_type="Expression",
        ).value
        x, a, b, c = (context.symbols[n] for n in ("x", "a", "b", "c"))
        assert sp.simplify(expr - (a * x**2 + b * x + c)) == 0

    def test_loads_coefficient_relation(self, context) -> None:
        relation = context.read_path(
            "$problem.equations.coefficient_relation",
            from_scope_id="problem",
            expected_type="Equation",
        ).value
        a, b = context.symbols["a"], context.symbols["b"]
        assert relation == sp.Eq(2 * a + b, 0)


class TestContextBuilderNankaiQuestions:
    """各问已知系数与条件。"""

    def test_part_i_known_coefficients(self, context) -> None:
        known = context.get_scope("i").container("coefficients")["known"].value
        assert known[context.symbols["a"]] == 2
        assert known[context.symbols["c"]] == -5
        assert context.symbols["b"] not in known

    def test_question_unknown_quadratic_coefficients(self, context) -> None:
        unknowns = context.get_scope("i").container("symbol_lists")["unknown_quadratic_coefficients"].value
        assert unknowns == [context.symbols["b"]]

    def test_subquestion_conditions(self, context) -> None:
        length_sq = context.read_path(
            "$subquestion.ii_1.conditions.length_squared",
            from_scope_id="ii_1",
            expected_type="Condition",
        ).value
        assert length_sq["type"] == "length_squared"
        assert length_sq["segment"] == ["M", "N"]
        assert length_sq["value"] == "10"

        minimum = context.read_path(
            "$subquestion.ii_2.conditions.minimum_value",
            from_scope_id="ii_2",
            expected_type="Condition",
        ).value
        assert minimum["type"] == "minimum_value"
        assert minimum["path"] == "EG+FG"
        assert minimum["value"] == "5*sqrt(10)/2"

    def test_global_path_conditions(self, context) -> None:
        path = context.read_path(
            "$problem.conditions.path_minimum",
            from_scope_id="ii_1",
            expected_type="Condition",
        ).value
        relation = context.read_path(
            "$problem.conditions.segment_relation_DE_NG",
            from_scope_id="ii_1",
            expected_type="Condition",
        ).value

        assert path["path"] == "EG+FG"
        assert path["type"] == "two_moving_points_path_minimum"
        assert path["scope"] == "ii"
        assert "minimum_segment" not in path
        assert "auxiliary_points" not in path
        assert relation["left"] == "DE"
        assert relation["right"] == "sqrt(2)*NG"


class TestContextBuilderNankaiPoints:
    """点定义的作用域选择与类型。"""

    def test_axis_intercept_on_problem_scope(self, context) -> None:
        d = context.read_path(
            "$problem.points.D",
            from_scope_id="ii_1",
            expected_type="PointRef",
        ).value
        assert isinstance(d, PointRef)
        assert d.name == "D"
        assert d.definition["definition"] == "axis_x_intercept"
        assert d.path == "$problem.points.D"

    def test_explicit_coordinate_on_question_ii(self, context) -> None:
        m = context.read_path(
            "$question.ii.points.M",
            from_scope_id="ii_1",
            expected_type="Point",
        ).value
        assert m == (context.symbols["m"], sp.Integer(1))

    def test_derived_points_on_question_ii(self, context) -> None:
        for point_name in ("N", "F"):
            ref = context.read_path(
                f"$question.ii.points.{point_name}",
                from_scope_id="ii_1",
                expected_type="PointRef",
            ).value
            assert isinstance(ref, PointRef)
            assert ref.scope_id == "ii"

        n_ref = context.read_path(
            "$question.ii.points.N",
            from_scope_id="ii_1",
            expected_type="PointRef",
        ).value
        assert n_ref.definition["definition"] == "unknown"

        n_hint = context.get_scope("ii").constraints["N_quadrant"].value
        assert n_hint["quadrant"] == "第四象限"
        assert "probe_symbol" not in n_hint
        assert "probe_lower_bound" not in n_hint

    def test_context_builder_does_not_inject_straightening_auxiliary_point(self, context) -> None:
        assert "D_prime" not in context.get_scope("ii").container("points")

    def test_planner_creates_straightening_auxiliary_point_placeholder(self, context) -> None:
        QuadraticPathMinimumPlannerV15().plan(context)

        d_prime = context.read_path(
            "$question.ii.points.D_prime",
            from_scope_id="ii_2",
            expected_type="PointRef",
        ).value
        assert isinstance(d_prime, PointRef)
        assert d_prime.definition["definition"] == "straightening_auxiliary_point"
        assert d_prime.scope_id == "ii"

    def test_constructed_point_scope_uses_definition_dependencies_without_ii_hardcode(
        self,
        kernel: SympyKernel,
    ) -> None:
        """构造点依赖都在 iii 时，应归属 iii，而不是历史硬编码的 ii。"""
        problem = ProblemIR(
            problem_id="synthetic-scope-iii",
            pattern="path-minimum",
            problem_type="quadratic_path_minimum",
            symbols=["x", "a", "b", "c"],
            data={
                "function": {
                    "id": "parabola",
                    "type": "quadratic",
                    "expression": "a*x**2 + b*x + c",
                },
                "entities": {
                    "points": {
                        "A": {"coordinate": ["0", "0"]},
                        "B": {"coordinate": ["1", "0"]},
                        "C": {"coordinate": ["0", "1"]},
                        "X": {
                            "definition": "square_opposite_point",
                            "vertex": "A",
                            "adjacent": ["B", "C"],
                        },
                    }
                },
                "relations": [],
                "questions": [
                    {"id": "iii", "label": "第（Ⅲ）问", "asks": ["A、B、C、X"]}
                ],
            },
        )

        context = ContextBuilder(kernel).build(problem)
        ref = context.read_path(
            "$question.iii.points.X",
            from_scope_id="iii",
            expected_type="PointRef",
        ).value

        assert ref.scope_id == "iii"

    def test_constructed_point_cross_scope_dependencies_fall_back_to_problem(
        self,
        kernel: SympyKernel,
    ) -> None:
        """依赖跨 question scope 时，构造点保守放 problem，避免误塞到 ii。"""
        problem = ProblemIR(
            problem_id="synthetic-cross-scope",
            pattern="path-minimum",
            problem_type="quadratic_path_minimum",
            symbols=["x", "a", "b", "c"],
            data={
                "function": {
                    "id": "parabola",
                    "type": "quadratic",
                    "expression": "a*x**2 + b*x + c",
                },
                "entities": {
                    "points": {
                        "A": {"coordinate": ["0", "0"]},
                        "B": {"coordinate": ["1", "0"]},
                        "Y": {
                            "definition": "reflected_point",
                            "source": "A",
                            "mirror_line": ["B", "C"],
                        },
                        "C": {"coordinate": ["0", "1"]},
                    }
                },
                "relations": [],
                "questions": [
                    {"id": "ii", "label": "第（Ⅱ）问", "asks": ["A"]},
                    {"id": "iii", "label": "第（Ⅲ）问", "asks": ["B、C"]},
                ],
            },
        )

        context = ContextBuilder(kernel).build(problem)
        ref = context.read_path(
            "$problem.points.Y",
            from_scope_id="iii",
            expected_type="PointRef",
        ).value

        assert ref.scope_id == "problem"


class TestContextBuilderUsesInjectedKernel:
    """``ContextBuilder(kernel)`` 应复用传入内核。"""

    def test_builder_uses_provided_kernel(self, problem) -> None:
        kernel = SympyKernel()
        context = ContextBuilder(kernel).build(problem)
        assert context.kernel is kernel
