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


def test_q22_bridge_has_checked_sources_before_discriminant_and_twelve_total_decisions(course):
    _, state, chunks = course
    first, second, third = state["fragments"][:3]
    assert [step["method_ref"] for step in (first, second)] == [
        "method-domain-parameter#extract", "method-domain-parameter#reduce",
    ]
    assert third["method_ref"].startswith("method-discriminant#")
    assert first["source_refs"] == ["/steps/0/calls/0"]
    assert second["source_refs"] == ["/steps/1/calls/0"]
    assert first["used_basis"] == ["square-root-expression#meaning"]
    assert set(second["used_basis"]) == {
        "function-concept#elements", "quantifiers#universal", "square-root-expression#meaning",
    }
    assert "被开方数非负" in first["explanation"]
    assert r"\forall x\in\mathbb{R}" in second["explanation"]
    assert second["highlight"]["connector"] == "⇔"
    assert len(state["fragments"]) == 8
    assert 3 + sum(len(chunk["parts"]) for chunk, _ in chunks) == 12


def test_bridge_grading_distinguishes_zero_from_negative_and_all_from_some(course):
    _, _, chunks = course
    condition, universal = [chunk["parts"][0] for chunk, _ in chunks[:2]]
    for part in (condition, universal):
        for option in part["interaction"]["options"]:
            expected = "passed" if option["value"] in part["expected_answer"]["one_of"] else "wrong"
            assert grade(part, {"value": option["value"]}, "domain-parameter") == expected
    def correct(part):
        return next(option["label"] for option in part["interaction"]["options"]
                    if option["value"] in part["expected_answer"]["one_of"])
    assert r"\geq 0" in correct(condition)
    assert correct(universal).startswith("每一个实数")
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
    first, second = [chunk["parts"][0] for chunk, _ in chunks[:2]]
    assert context["domain_goal"]["expression_latex"] in first["question"]
    extracted = decode_value(state["interaction_seeds"][0]["values"])
    relation = latex(extracted["constraints"][0]["condition"])
    assert relation in second["question"]
    assert rf"D_{{{function}}}=\mathbb{{R}}" in state["fragments"][1]["explanation"]
    assert all(f"实数 ${variable}$" in option["label"]
               for option in second["interaction"]["options"])
    for seed in state["interaction_seeds"][:2]:
        assert not {"candidate_set", "feasible_set", "solutions"} & decode_value(seed["values"]).keys()


def test_universal_question_tests_domain_meaning_when_all_and_some_have_the_same_parameter_set():
    # x²+1 is positive everywhere, so both quantifiers happen to produce k≥0.
    # Ask which inputs the definition requires checking, not whether these two
    # particular quantified predicates give different parameter sets.
    x = sp.Symbol("x", real=True)
    assert sp.ask(sp.Q.positive(x**2 + 1)) is True
    _, state, chunks = execute(candidate("sqrt(k*x^2+k)"))
    assert driver.export_values(state)["feasible_set"] == sp.Interval(0, sp.oo)
    universal = chunks[1][0]["parts"][0]
    assert "按照定义域的含义，应检查哪些实数输入" in universal["question"]
    assert "等价" not in universal["question"]
    labels = {option["value"]: option["label"] for option in universal["interaction"]["options"]}
    assert labels == {"o1": "每一个实数 $x$ 都应使原式有意义", "o2": "只需找到一个实数 $x$ 使原式有意义"}
    assert grade(universal, {"value": "o1"}, "domain-parameter") == "passed"
    assert grade(universal, {"value": "o2"}, "domain-parameter") == "wrong"
    assert r"\forall x\in\mathbb{R}" in state["fragments"][1]["explanation"]


@pytest.mark.parametrize("index,change,reason", [
    (0, lambda value: value["constraints"][0].update(ast_path=[1]), "condition_source_mismatch"),
    (1, lambda value: value.update(quantifier="∃"), "universal_mismatch"),
    (1, lambda value: value.update(domain=sp.Interval(0, 1)), "universal_mismatch"),
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
