"""Regression gates for critical evidence identity and number-line row binding."""
from copy import deepcopy

import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson.stage_one.function_domain import (
    inspect_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_three.domain_visuals import number_lines
from shuxueshuo_server.graph_lesson.stage_three.function_domain import _critical
from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_three.verification import verify
from tests.solver.test_graph_stage_three_function_domain import (
    TARGET,
    candidate,
    execute,
)


def test_sqrt_divisor_has_one_polynomial_with_both_original_requirements():
    original = candidate("1/sqrt(x-2)")
    description = inspect_domain_target(original, TARGET)
    points, rows = _critical(description)
    assert points == [sp.Integer(2)]
    (row,) = rows
    assert row["source_ref"] == "/root/definitions/0"
    assert row["ast_path"] == [2, 2]
    assert row["expression_ast"] == description["expression_ast"][2][2]
    assert {(tuple(source["ast_path"]), source["kind"]) for source in row["condition_sources"]} == {
        ((2,), "denominator_nonzero"), ((2, 2), "radicand_nonnegative")}
    context, _ = execute(original)
    proof = verify(original, TARGET, context, sp.Interval.open(2, sp.oo))
    assert proof["status"] == "verified"
    assert proof["proof"]["critical_polynomials"] == rows


def test_equal_expressions_at_distinct_original_positions_keep_distinct_evidence():
    description = inspect_domain_target(candidate("sqrt(x-2)+1/sqrt(x-2)"), TARGET)
    points, rows = _critical(description)
    assert points == [sp.Integer(2)]
    assert len(rows) == 2
    assert {tuple(row["ast_path"]) for row in rows} == {(1, 2), (2, 2, 2)}
    assert rows[0]["expression_ast"] == rows[1]["expression_ast"]
    assert sorted(len(row["condition_sources"]) for row in rows) == [1, 2]
    for row in rows:
        original = description["expression_ast"]
        for index in row["ast_path"]:
            original = original[index]
        assert row["expression_ast"] == original


def _values(expression="sqrt(x-1)/(x-2)", interval=None):
    _, state = execute(candidate(expression, interval))
    return decode_value(state["result"])["domain_evidence"]


def test_condition_input_and_result_labels_follow_their_bound_sets():
    values = _values(interval="[0,1]")
    lines = number_lines(values, include_result=True)
    assert len(lines) == 4
    for line, condition, solution in zip(lines[:2], values["constraints"], values["solutions"], strict=True):
        assert line["condition_id"] == condition["condition_id"]
        assert line["label"] == latex(condition["condition"]) + r"\quad\Longrightarrow\quad " + latex(solution)
        assert decode_value(line["exact_set"]["exact"]) == solution
    assert lines[2]["condition_id"] == "input-domain"
    assert lines[2]["source_ref"] == "/root/goals/0/input_domain"
    assert lines[2]["label"] == r"x\in " + latex(values["input_domain"])
    assert lines[3]["label"] == "D_{f}=" + latex(sp.FiniteSet(1))
    assert decode_value(lines[3]["exact_set"]["exact"]) == sp.FiniteSet(1)


@pytest.mark.parametrize("extra", [True, False])
def test_misaligned_condition_solutions_are_rejected_before_rendering(extra):
    values = _values()
    if extra:
        values["solutions"].append(sp.S.Reals)
    else:
        values["solutions"].pop()
    with pytest.raises(ValueError, match="domain.condition_solution_count_mismatch"):
        number_lines(values, include_result=True)


@pytest.mark.parametrize("solutions", [[], [sp.Interval(1, sp.oo)], [sp.S.Reals, sp.S.Reals]])
def test_unrestricted_row_cannot_hide_a_nonreal_or_extra_solution(solutions):
    values = _values("x")
    values["solutions"] = deepcopy(solutions)
    with pytest.raises(ValueError, match="domain.unrestricted_solution_required"):
        number_lines(values, include_result=True)


def test_unrestricted_real_line_is_rendered_from_its_verified_value():
    values = _values("x", "[0,1]")
    lines = number_lines(values, include_result=True)
    assert lines[0]["label"] == latex(values["solutions"][0])
    assert decode_value(lines[0]["exact_set"]["exact"]) == sp.S.Reals
    assert lines[1]["condition_id"] == "input-domain"
    assert lines[2]["label"] == "D_{f}=" + latex(sp.Interval(0, 1))
