"""Reuse separation on the exact denominator domain, including degeneracies."""

from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.domain_interaction import compile_domain
from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.learning.graph_walk import grade
from tests.solver.test_graph_domain_parameter_interactions import candidate, execute


def halfline(expression, domain="(1,+∞)", variable="x", parameter="m", function="f"):
    value = candidate(expression, variable, parameter, function)
    value["root"]["goals"][0]["domain"] = domain
    value["original_text"] = f"函数 {function}({variable})={expression} 的定义域是 {domain}，求 {parameter}。"
    return value


def answer(part):
    expected, kind = part["expected_answer"], part["interaction"]["type"]
    return ("read" if kind == "read" else expected["one_of"][0] if kind == "choice" else
            [*expected["cell"], expected["method"]] if kind == "plane" else expected["terms"])


@pytest.fixture(scope="module")
def course():
    return execute(halfline("sqrt(x^2-3*x-m)/sqrt(x-1)"))


def test_original_three_sources_and_exact_denominator_domain_are_taught_before_borrow(course):
    _, state, chunks = course
    rows = decode_value(state["interaction_seeds"][0]["values"])["constraints"]
    assert [(row["kind"], row["ast_path"]) for row in rows] == [
        ("radicand_nonnegative", [1, 2]), ("radicand_nonnegative", [2, 2]), ("denominator_nonzero", [2]),
    ]
    assert all(row["source_ref"] == "/root/definitions/0" for row in rows)
    part = chunks[0][0]["parts"][0]
    assert part["expected_answer"]["terms"] == ["s1o1", "s2o1", "s3o1"]
    for index, row in enumerate(rows):
        chosen = next(option for option in part["interaction"]["slots"][index]["options"]
                      if option["value"] == f"s{index + 1}o1")
        assert latex(row["condition"]) in chosen["label"]
        wrong = answer(part).copy()
        wrong[index] = f"s{index + 1}o2"
        assert grade(part, {"value": wrong}, "domain-parameter") == "wrong"
    merged, universal = chunks[1][0]["parts"]
    assert "x - 1" in merged["question"] and "x^{2}" not in merged["question"]
    assert next(option["label"] for option in merged["interaction"]["options"] if option["value"] == "o1") == "$u>0$"
    assert "域外" in universal["question"] and "分母为零" in universal["question"]
    assert "分子" in universal["question"]
    assert "无需要求域外的分子非负" in state["fragments"][1]["explanation"]
    assert "mathbb{R}" not in universal["question"]
    assert grade(universal, {"value": "o2"}, "domain-parameter") == "wrong"
    values = decode_value(state["interaction_seeds"][1]["values"])
    assert values["domain"] == sp.Interval.open(1, sp.oo)
    assert values["strict"] is False
    assert values["domain_equivalence"]["outside_excluded"] is True


def test_actual_interval_selects_separation_and_returns_to_original_domain(course):
    _, state, chunks = course
    borrow = chunks[2][0]["parts"][0]
    assert borrow["interaction"]["type"] == "plane"
    assert borrow["expected_answer"] == {"cell": ["interval", "free"], "method": "separation"}
    assert r"\left(1, \infty\right)" in borrow["question"]
    assert grade(borrow, {"value": ["real", "free", "separation"]}, "domain-parameter") == "wrong"
    assert grade(borrow, {"value": answer(borrow)}, "domain-parameter") == "passed"
    assert all(not fragment["method_ref"].startswith("method-discriminant#") for fragment in state["fragments"])
    assert any(fragment["method_ref"].startswith("method-separation#") for fragment in state["fragments"])
    result = driver.export_values(state)["feasible_set"]
    assert result == sp.Interval(-sp.oo, -sp.Rational(9, 4))
    assert result.contains(-sp.Rational(9, 4)) is sp.S.true
    returned = chunks[-1][0]["parts"][0]
    assert r"D_{f}=\left(1, \infty\right)" in next(
        option["label"] for option in returned["interaction"]["options"] if option["value"] == "o1")
    assert "分离参数法" in state["fragments"][-1]["explanation"]
    assert len(state["fragments"]) == 8
    assert sum(len(chunk["parts"]) for chunk, _ in chunks) == 10


@pytest.mark.parametrize("expression,domain,expected,borrow_kind", [
    ("sqrt(x^2-3*x-m)/sqrt(x-1)", "(1,+∞)", sp.Interval(-sp.oo, -sp.Rational(9, 4)), "plane"),
    ("sqrt(x^2-m)/sqrt(x-1)", "(1,+∞)", sp.Interval(-sp.oo, 1), "plane"),
    ("sqrt((x-2)^2-m/2)/sqrt(x-1)", "(1,+∞)", sp.Interval(-sp.oo, 0), "plane"),
    ("sqrt(x^2+3*x+2*m)/sqrt(-x-1)", "(-∞,-1)", sp.Interval(sp.Rational(9, 8), sp.oo), "plane"),
    ("sqrt(-x^2-m)/sqrt(x-1)", "(1,+∞)", sp.S.EmptySet, "plane"),
    ("sqrt(2*x-m)/sqrt(x-1)", "(1,+∞)", sp.Interval(-sp.oo, 2), "read"),
    ("sqrt(-2*x+m)/sqrt(-x-1)", "(-∞,-1)", sp.Interval(-2, sp.oo), "read"),
    ("sqrt(-2*x-m)/sqrt(x-1)", "(1,+∞)", sp.S.EmptySet, "read"),
    ("sqrt(3-m)/sqrt(x-1)", "(1,+∞)", sp.Interval(-sp.oo, 3), "read"),
    ("sqrt(2*m-3)/sqrt(-x-1)", "(-∞,-1)", sp.Interval(sp.Rational(3, 2), sp.oo), "read"),
])
def test_halfline_quadratic_linear_and_constant_courses_remain_fully_interactive(expression, domain, expected, borrow_kind):
    _, state, chunks = execute(halfline(expression, domain))
    assert driver.export_values(state)["feasible_set"] == expected
    borrow = chunks[2][0]["parts"][0]
    assert borrow["interaction"]["type"] == borrow_kind
    if borrow_kind == "read":
        assert borrow["expected_answer"] == {}
        assert "rule-quadratic-method" not in borrow["effects"]["nodes"]
        assert "退化" in borrow["question"]
    for chunk, _ in chunks:
        for part in chunk["parts"]:
            assert grade(part, {"value": answer(part)}, "domain-parameter") == "passed"
    solve = next(step for step in state["trajectory"]["steps"]
                 if step["method"] == "method-domain-parameter" and step["step"] == "solve")
    assert [row["public_ref"] for row in solve["calls"]] == ["method-separation"]
    assert solve["merges"]


@pytest.mark.parametrize("change", [
    lambda value: value.update(domain=sp.S.Reals),
    lambda value: value.update(strict=True),
    lambda value: value["domain_equivalence"].update(passed=False),
    lambda value: value["domain_equivalence"].update(outside_excluded=False),
    lambda value: value["domain_equivalence"].update(source_refs=["/root/definitions/9"]),
    lambda value: value["domain_equivalence"].update(denominator_condition=sp.Ge(value["constraints"][1]["condition"].lhs, 0, evaluate=False)),
    lambda value: value["constraints"][1].update(ast_path=[1, 2]),
])
def test_halfline_projection_rejects_mismatched_domain_or_source_certificate(course, change):
    seed = deepcopy(course[1]["interaction_seeds"][1])
    values = decode_value(seed["values"])
    change(values)
    seed["values"] = encode_value(values)
    with pytest.raises(ValueError):
        compile_domain([seed], "bad-halfline")


def test_already_separated_confirmation_is_explicit_and_rejects_changed_math():
    _, state, chunks = execute(halfline("sqrt(3-m)/sqrt(x-1)"))
    seed = next(row for row in state["interaction_seeds"] if row["template"] == "separated")
    part = next(part for chunk, _ in chunks for part in chunk["parts"] if part["title"] == "确认已分离的形式")
    assert part["interaction"] == {"type": "read"}
    assert grade(part, {"value": "read"}, "domain-parameter") == "passed"
    values = decode_value(seed["values"])
    values["after"] = [sp.Lt(sp.Symbol("m", real=True), 1, evaluate=False)]
    seed["values"] = encode_value(values)
    rule = interaction.load_registry()["templates"]["separated"]
    with pytest.raises(ValueError, match="already_separated_source_mismatch"):
        interaction.compile_interaction([seed], rule, {}, interaction_id="bad-separated")
    chunk = deepcopy(chunks[2][0])
    chunk["parts"][0]["expected_answer"] = {"one_of": ["o1"]}
    with pytest.raises(ValidationError):
        interaction.validate_chunk(chunk)


@pytest.mark.parametrize("operator", [">=", ">"])
def test_existing_separation_confirms_reversed_relation_without_accepting_other_changes(operator):
    from tests.solver.test_graph_stage_three_methods import (
        candidate as quantified_candidate,
    )
    from tests.solver.test_graph_stage_three_methods import finish, start

    state = finish(start(quantified_candidate(f"∀x∈ℝ:x^2+4{operator}a^2"), "method-separation"))
    assert state["status"] == "method_complete"
    seed = next(row for row in state["interaction_seeds"] if row["template"] == "separated")
    values = decode_value(seed["values"])
    before, after = values["before"][0], values["after"][0]
    assert before != after and before.reversed == after
    rule = interaction.load_registry()["templates"]["separated"]
    projected = interaction.compile_interaction([seed], rule, {}, interaction_id="reversed-separation")
    part = projected["parts"][0]
    assert part["interaction"] == {"type": "read"}
    assert latex(after) in part["question"]
    assert grade(part, {"value": "read"}, "extremum") == "passed"
    chunk, diagnostics = interaction.build_chunk([seed], interaction.load_registry(), {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    interaction.validate_chunk(chunk)
    for wrong in [(sp.Lt if operator == ">=" else sp.Le)(after.lhs, after.rhs, evaluate=False),
                  sp.Le(after.lhs, after.rhs + 1, evaluate=False)]:
        bad_seed = deepcopy(seed)
        bad_seed["values"] = encode_value({**values, "after": [wrong]})
        with pytest.raises(ValueError, match="already_separated_source_mismatch"):
            interaction.compile_interaction([bad_seed], rule, {}, interaction_id="wrong-reversed-separation")
