"""M6 teaches its domain-to-universal bridge before the discriminant submethod."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.domain_interaction import compile_domain
from shuxueshuo_server.graph_lesson.stage_three.math_values import latex
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_two.recognition import (
    build_d2,
    evaluate_types,
)
from shuxueshuo_server.learning.graph_walk import grade
from shuxueshuo_server.search.lesson import d2_options
from tests.solver.test_graph_stage_three_methods import finish

TARGET = "/root/goals/0"
TYPE = "type-function-domain"


def candidate(expression="sqrt(k*x^2+2*x+1)", variable="x", parameter="k", function="f"):
    return {
        "original_text": f"函数 {function}({variable})={expression} 的定义域为全体实数，求 {parameter}。",
        "root": {
            "definitions": [f"{function}({variable})={expression}"],
            "goals": [{"kind": "match_domain", "object": function, "domain": "ℝ", "symbol": parameter}],
        },
    }


def execute(value):
    context = build_context(value, TARGET)
    state = finish(driver.create_state(
        features=extract_features(value)["features"], context=context,
        method="method-domain-parameter", route_id="domain-parameter", branch="direct",
        target_ref=TARGET, run_id="domain-parameter-interactions", lesson_version="v1",
    ))
    assert state["status"] == "method_complete", state.get("diagnostics")
    chunks, pending = interaction.compile_route(state["interaction_seeds"], interaction.load_registry())
    assert not pending
    for chunk, diagnostics in chunks:
        assert chunk["status"] == "interactive", diagnostics
        interaction.validate_chunk(chunk)
    return context, state, chunks


@pytest.fixture(scope="module")
def course():
    return execute(candidate())


def test_q22_bridge_has_checked_sources_before_discriminant_and_fourteen_total_decisions(course):
    _, state, chunks = course
    first, second, third, fourth = state["fragments"][:4]
    assert [step["method_ref"] for step in (first, second, third)] == [
        "method-domain-parameter#extract",
        "method-domain-parameter#reduce",
        "method-domain-parameter#reduce",
    ]
    assert fourth["method_ref"].startswith("method-discriminant#")
    assert first["source_refs"] == ["/steps/0/calls/0"]
    assert second["source_refs"] == ["/steps/1/calls/0"]
    assert third["source_refs"] == ["/steps/1/calls/0"]
    assert first["used_basis"] == ["square-root-expression#meaning"]
    assert set(second["used_basis"]) == {
        "function-concept#elements", "quantifiers#universal", "square-root-expression#meaning",
    }
    assert set(third["used_basis"]) == set(second["used_basis"])
    assert "被开方数非负" in first["explanation"]
    assert r"\forall x\in\mathbb{R}" in second["explanation"]
    assert "判别式法" in third["explanation"]
    assert second["highlight"]["connector"] == "⇔"
    assert state["fragments"][-1]["method_ref"] == "method-domain-parameter#solve"
    assert "定义域求参" in state["fragments"][-1]["title"] or "回到" in state["fragments"][-1]["title"]
    assert len(state["fragments"]) == 10
    assert 3 + sum(len(chunk["parts"]) for chunk, _ in chunks) == 14


def test_bridge_grading_distinguishes_zero_from_negative_transform_borrow_and_return(course):
    _, _, chunks = course
    condition, universal, borrow = [chunk["parts"][0] for chunk, _ in chunks[:3]]
    returned = chunks[-1][0]["parts"][0]
    for part in (condition, universal, returned):
        for option in part["interaction"]["options"]:
            expected = "passed" if option["value"] in part["expected_answer"]["one_of"] else "wrong"
            assert grade(part, {"value": option["value"]}, "domain-parameter") == expected
    assert borrow["interaction"]["type"] == "plane"
    assert borrow["expected_answer"]["cell"] == ["real", "free"]
    assert borrow["expected_answer"]["method"] == "discriminant"
    cell = borrow["expected_answer"]["cell"]
    assert grade(borrow, {"value": [*cell, "discriminant"]}, "domain-parameter") == "passed"
    for method in borrow["interaction"]["methods"]:
        if method["value"] == "discriminant":
            continue
        if cell in method["cells"] or list(cell) in method["cells"]:
            assert grade(borrow, {"value": [*cell, method["value"]]}, "domain-parameter") == "wrong"
    def correct(part):
        return next(option["label"] for option in part["interaction"]["options"]
                    if option["value"] in part["expected_answer"]["one_of"])
    assert r"\geq 0" in correct(condition)
    assert "每一个实数" in correct(universal)
    assert next(m["label"] for m in borrow["interaction"]["methods"]
                if m["value"] == "discriminant") == "判别式法"
    assert r"D_{f}=\mathbb{R}" in correct(returned) and "参数" in correct(returned)
    assert borrow["effects"]["nodes"] == ["rule-quadratic-method", "method-discriminant"]
    assert returned["effects"]["nodes"] == ["method-domain-parameter"]
    assert {item["witness"] for item in chunks[0][1]} == {"0", "-1"}
    # For this actual problem k=0 has some legal inputs but not all real inputs.
    x = sp.Symbol("x", real=True)
    relation = sp.Ge(2*x + 1, 0)
    assert relation.subs(x, 0) is sp.S.true
    assert relation.subs(x, -1) is sp.S.false


@pytest.mark.parametrize("expression,variable,parameter,function", [
    ("sqrt(m*t^2+4*t+4)", "t", "m", "g"),
    ("sqrt(x^2+k*x+1)", "x", "k", "f"),
])
def test_bridge_reads_current_expression_and_symbols_without_solving_early(expression, variable, parameter, function):
    context, state, chunks = execute(candidate(expression, variable, parameter, function))
    first, second, borrow = [chunk["parts"][0] for chunk, _ in chunks[:3]]
    assert context["domain_goal"]["expression_latex"] in first["question"]
    extracted = decode_value(state["interaction_seeds"][0]["values"])
    relation = latex(extracted["constraints"][0]["condition"])
    assert relation in second["question"]
    assert relation in borrow["question"]
    assert borrow["interaction"]["type"] == "plane"
    assert borrow["expected_answer"]["method"] == "discriminant"
    assert rf"D_{{{function}}}=\mathbb{{R}}" in state["fragments"][1]["explanation"]
    assert all(f"实数 ${variable}$" in option["label"]
               for option in second["interaction"]["options"])
    for seed in state["interaction_seeds"][:3]:
        assert not {"candidate_set", "feasible_set", "solutions"} & decode_value(seed["values"]).keys()


def test_universal_question_asks_domain_meaning_even_when_quantifiers_are_equivalent():
    x = sp.Symbol("x", real=True)
    assert sp.ask(sp.Q.positive(x**2 + 1)) is True
    _, state, chunks = execute(candidate("sqrt(k*x^2+k)"))
    assert driver.export_values(state)["feasible_set"] == sp.Interval(0, sp.oo)
    universal = chunks[1][0]["parts"][0]
    # Here both quantified predicates give k >= 0. Test the meaning of
    # "domain is R", not a claim that the two predicates are inequivalent.
    assert "按照定义域的含义，应检查哪些实数输入" in universal["question"]
    assert "等价于" not in universal["question"]
    labels = {option["value"]: option["label"] for option in universal["interaction"]["options"]}
    assert "每一个实数" in labels["o1"]
    assert "只需找到一个实数" in labels["o2"]
    assert grade(universal, {"value": "o1"}, "domain-parameter") == "passed"
    assert grade(universal, {"value": "o2"}, "domain-parameter") == "wrong"
    assert "恒成立问题" in state["fragments"][1]["explanation"]
    assert r"\forall x\in\mathbb{R}" in state["fragments"][1]["explanation"]


@pytest.mark.parametrize("index,change,reason", [
    (0, lambda value: value["constraints"][0].update(ast_path=[1]), "condition_source_mismatch"),
    (1, lambda value: value.update(quantifier="∃"), "universal_mismatch"),
    (1, lambda value: value.update(domain=sp.Interval(0, 1)), "universal_mismatch"),
    (2, lambda value: value.update(quantifier="∃"), "universal_mismatch"),
])
def test_bridge_rejects_mismatched_source_or_unverified_reduction(course, index, change, reason):
    seed = deepcopy(course[1]["interaction_seeds"][index])
    values = decode_value(seed["values"])
    change(values)
    seed["values"] = encode_value(values)
    with pytest.raises(ValueError, match=reason):
        compile_domain([seed], "bad-domain-seed")


def test_parameter_type_review_explains_parameter_goal_without_changing_find_domain():
    parameter = candidate()
    fixed = {"original_text": "求定义域", "root": {"definitions": ["f(x)=sqrt(x-1)"],
              "goals": [{"kind": "find_domain", "object": "f"}]}}
    for value, wanted, forbidden in ((parameter, "全部参数", "要求全部合法输入"),
                                     (fixed, "要求全部合法输入", "全部参数")):
        reports = evaluate_types(extract_features(value)["features"])
        primary = next(option for option in d2_options({"primary": TYPE, "target_ref": TARGET,
                                                        "d2": build_d2(reports, TYPE)})
                       if option["role"] == "primary")
        text = "；".join(primary["reasons"])
        assert wanted in text
        assert forbidden not in text


@pytest.mark.parametrize("reciprocal", [False, True])
@pytest.mark.parametrize("polynomial,nonstrict,strict", [
    ("m*x^2-6*m*x+m+8", sp.Interval(0, 1), sp.Interval.Ropen(0, 1)),
    ("m*x^2+m", sp.Interval(0, sp.oo), sp.Interval.open(0, sp.oo)),
    ("m*x^2", sp.Interval(0, sp.oo), sp.S.EmptySet),
    ("m*x^2+2*x", sp.S.EmptySet, sp.S.EmptySet),
    ("x^2+m", sp.Interval(0, sp.oo), sp.Interval.open(0, sp.oo)),
    ("x^2+m*x+1", sp.Interval(-2, 2), sp.Interval.open(-2, 2)),
])
def test_strict_and_nonstrict_domain_courses_keep_all_submethod_interactions(
    reciprocal, polynomial, nonstrict, strict,
):
    expression = ("1/" if reciprocal else "") + f"sqrt({polynomial})"
    _, state, chunks = execute(candidate(expression, parameter="m"))
    assert driver.export_values(state)["feasible_set"] == (strict if reciprocal else nonstrict)
    values = decode_value(state["interaction_seeds"][1]["values"])
    assert values["strict"] is reciprocal
    assert values["universal_statement"].rel_op == (">" if reciprocal else ">=")
    for chunk, _ in chunks:
        for part in chunk["parts"]:
            expected, component = part["expected_answer"], part["interaction"]
            answer = ("read" if component["type"] == "read" else
                      expected["one_of"][0] if component["type"] == "choice" else
                      [*expected["cell"], expected["method"]] if component["type"] == "plane" else
                      expected["cell"] if component["type"] == "grid" else
                      expected["required"] if component["type"] == "multi" else expected["terms"])
            assert grade(part, {"value": answer}, "domain-parameter") == "passed"
    assert len(chunks[1][0]["parts"]) == (2 if reciprocal else 1)
    borrow = chunks[2][0]["parts"][0]
    assert latex(values["universal_statement"]) in borrow["question"]
    assert "回到定义域求参" == chunks[-1][0]["parts"][0]["title"]


def test_reciprocal_root_teaches_both_original_sources_before_strict_reduction():
    _, state, chunks = execute(candidate("1/sqrt(m*x^2-6*m*x+m+8)", parameter="m"))
    rows = decode_value(state["interaction_seeds"][0]["values"])["constraints"]
    assert [(row["kind"], row["ast_path"]) for row in rows] == [
        ("radicand_nonnegative", [2, 2]), ("denominator_nonzero", [2]),
    ]
    assert rows[0]["condition"].rel_op == ">="
    assert rows[1]["condition"].rel_op == "!="
    assert set(state["fragments"][0]["used_basis"]) == {
        "square-root-expression#meaning", "rational-expression#meaning",
    }
    condition = chunks[0][0]["parts"][0]
    assert condition["interaction"]["type"] == "checklist"
    assert condition["expected_answer"]["terms"] == ["s1o1", "s2o1"]
    for index, row in enumerate(rows):
        slot = condition["interaction"]["slots"][index]
        correct = next(option for option in slot["options"] if option["value"] == f"s{index + 1}o1")
        assert latex(row["condition"]) in correct["label"]
        wrong = condition["expected_answer"]["terms"].copy()
        wrong[index] = f"s{index + 1}o2"
        assert grade(condition, {"value": wrong}, "domain-parameter") == "wrong"
    merged, universal = chunks[1][0]["parts"]
    assert merged["title"] == "合并有意义的条件"
    assert next(option["label"] for option in merged["interaction"]["options"]
                if option["value"] == "o1") == "$u>0$"
    assert "按照定义域的含义" in universal["question"]
    assert "等价于" not in universal["question"]
    assert "分母" in state["fragments"][0]["explanation"]
    assert "严格" in merged["feedback"]["answer"]
    parts = [part for chunk, _ in chunks for part in chunk["parts"]]
    zero = next(part for part in parts if part["title"] == "检查二次项系数为 0 的情况")
    assert "$m=0$" in zero["question"] and "$8 > 0$" in zero["question"]
    correct_zero = next(option for option in zero["interaction"]["slots"][0]["options"]
                        if option["value"] == zero["expected_answer"]["terms"][0])
    assert "保留" in correct_zero["label"]
    assert grade(zero, {"value": zero["expected_answer"]["terms"]}, "domain-parameter") == "passed"
    delta = next(part for part in parts if part["title"] == "开口向上：建立判别式条件")
    selected = next(option for option in delta["interaction"]["options"]
                    if option["value"] in delta["expected_answer"]["one_of"])
    assert "< 0" in selected["label"]
    touching = next(option for option in delta["interaction"]["options"] if r"\leq" in option["label"])
    assert grade(delta, {"value": touching["value"]}, "domain-parameter") == "wrong"
    # The existing submethod retains the constant branch m=0 and excludes
    # m=1, where P=(x-3)^2 makes the original denominator zero at x=3.
    answer = driver.export_values(state)["feasible_set"]
    assert answer.contains(0) is sp.S.true
    assert answer.contains(1) is sp.S.false


@pytest.mark.parametrize("index,change,reason", [
    (0, lambda value: value["constraints"][1].update(ast_path=[2, 2]), "condition_source_mismatch"),
    (0, lambda value: value["constraints"][1].update(source_ref="/root/definitions/9"), "condition_source_mismatch"),
    (0, lambda value: value["constraints"].pop(), "single_radicand_required"),
    (0, lambda value: value["description"].update(has_division=False), "single_radicand_required"),
    (1, lambda value: value.update(strict=False), "universal_mismatch"),
    (2, lambda value: value.update(relation=sp.Ge(value["relation"].lhs, 0, evaluate=False)), "universal_mismatch"),
])
def test_reciprocal_projection_rejects_dropped_source_or_weakened_relation(index, change, reason):
    _, state, _ = execute(candidate("1/sqrt(m*x^2-6*m*x+m+8)", parameter="m"))
    seed = deepcopy(state["interaction_seeds"][index])
    values = decode_value(seed["values"])
    change(values)
    seed["values"] = encode_value(values)
    with pytest.raises(ValueError, match=reason):
        compile_domain([seed], "bad-reciprocal-root")
