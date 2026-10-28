"""Original answer letters require complete, exact, scoped option equivalence."""

from copy import deepcopy

import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson.stage_three.choice_matching import (
    dispatch,
    match_original_choice,
)
from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

TARGET = "/root/goals/0"
FEASIBLE = sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(2, sp.oo))


def candidate(options=None, *, symbol="m", kind="find_range", prefix="单选题"):
    options = options or [f"{symbol}≤-2 或 {symbol}≥2", f"-2≤{symbol}≤2",
                          f"{symbol}<-2 或 {symbol}>2", f"-2<{symbol}<2"]
    goal = {"kind": kind, "symbol" if kind == "find_range" else "expression": symbol}
    return {"original_text": prefix + "求参数范围（ ）\n" + "\n".join(
        f"{label}. {text}" for label, text in zip("ABCDEFGH", options, strict=False)),
        "root": {"facts": [f"∃x∈ℝ: -x^2+{symbol}*x-1≥0"], "goals": [goal]}}


def match(source, feasible=FEASIBLE, target=TARGET):
    root = source["root"]
    for part in target.removeprefix("/root").split("/children/")[1:]:
        root = root["children"][int(part.split("/")[0])]
    answer = finalize_goal(root["goals"][0], feasible)
    return match_original_choice(source, target, answer, encode_value(feasible))


def test_verified_range_selects_original_letter_without_changing_problem_or_answer():
    source = candidate()
    answer = finalize_goal(source["root"]["goals"][0], FEASIBLE)
    unchanged = deepcopy((source, answer))
    result = dispatch({"candidate": source, "target_ref": TARGET,
                       "answer": answer, "feasible_set_exact": encode_value(FEASIBLE)})
    assert result == {"status": "matched", "kind": "single_choice", "target_ref": TARGET,
                      "matching": "set_equality", "selection_mode": "single",
                      "options": [{"label": "A", "text": "m≤-2 或 m≥2"},
                                  {"label": "B", "text": "-2≤m≤2"},
                                  {"label": "C", "text": "m<-2 或 m>2"},
                                  {"label": "D", "text": "-2<m<2"}],
                      "correct_labels": ["A"]}
    assert (source, answer) == unchanged


@pytest.mark.parametrize("symbol", ["a", "k", "t"])
def test_answer_letter_comes_from_equivalence_not_problem_or_label(symbol):
    options = [f"{symbol}>3", f"{symbol}≤-2 或 {symbol}≥2", f"{symbol}<1", f"{symbol}=0"]
    assert match(candidate(options, symbol=symbol))["correct_labels"] == ["B"]


@pytest.mark.parametrize("text", ["m^2≥4", "(-∞,-2]∪[2,∞)", "m∈(-∞,-2]∪[2,∞)",
                                  "{t∈ℝ|t^2≥4}", "m≤-sqrt(4) 或 m≥sqrt(4)"])
def test_algebraic_and_set_spellings_are_compared_exactly(text):
    result = match(candidate(["m>10", "m=1", text, "m=0"]))
    assert result["status"] == "matched", result
    assert result["correct_labels"] == ["C"]


def test_holes_before_cancellation_are_retained():
    source = candidate(["m/m≥1", "m≥0", "m∈ℝ", "m∈{0}"])
    assert match(source, sp.S.Reals - sp.FiniteSet(0))["correct_labels"] == ["A"]


def test_exam_set_builder_choices_match_d_without_changing_the_printed_options():
    source = candidate([
        r"$\{k \mid k<-4\}$", r"$\{k \mid k>0\}$",
        r"$\{k \mid -4<k<0\}$", r"$\{k \mid k<-4 \text{ 或 } k>0\}$",
    ], symbol="k")
    source["root"]["facts"] = ["∃x∈ℝ: k*x^2-k*x-1>0"]
    before = deepcopy(source)
    result = match(source, sp.Union(sp.Interval.open(-sp.oo, -4), sp.Interval.open(0, sp.oo)))
    assert result["status"] == "matched", result
    assert result["correct_labels"] == ["D"]
    assert result["options"][3]["text"] == r"$\{k \mid k<-4 \text{ 或 } k>0\}$"
    assert source == before


def test_shorthand_set_builder_preserves_division_holes_and_explicit_domains():
    source = candidate(["{m|m/m≥1}", "{m∈[0,1]|m>0}", "m∈ℝ", "m=0"])
    assert match(source, sp.S.Reals - sp.FiniteSet(0))["correct_labels"] == ["A"]
    assert match(source, sp.Interval.Lopen(0, 1))["correct_labels"] == ["B"]


def test_all_options_must_be_interpretable_even_when_first_matches():
    result = match(candidate(["m^2≥4", "m=1", "以上都正确", "m=0"]))
    assert result["status"] == "unavailable"
    assert result["reason"] == "choice.unsupported_option"
    assert "correct_labels" not in result


@pytest.mark.parametrize("bad", ["n^2≥4", "m+n>0", "m>1/0", "m∈[∞,∞]", "sqrt(m)>0",
                                 "m=__import__('os')", "m∈{1,∞}"])
def test_unsafe_undefined_or_foreign_options_disable_matching(bad):
    result = match(candidate(["m^2≥4", "m=1", bad, "m=0"]))
    assert result["status"] == "unavailable"
    assert "correct_labels" not in result


@pytest.mark.parametrize("options,reason", [
    (["m^2≥4", "m≤-2 或 m≥2", "m=1", "m=0"], "choice.ambiguous_match"),
    (["m^2>4", "m=2", "m=-2", "m=0"], "choice.no_match"),
    (["m^2≥4", "m=2", "m=-2"], "choice.incomplete_options"),
])
def test_no_unique_complete_match_never_guesses(options, reason):
    assert match(candidate(options))["reason"] == reason


def test_explicit_multiple_choice_matches_all_equivalent_sets():
    result = match(candidate(["m^2≥4", "m≤-2 或 m≥2", "m=0", "m=1"], prefix="多选题"))
    assert result["kind"] == "multiple_choice"
    assert result["correct_labels"] == ["A", "B"]


def test_non_choice_and_ambiguous_scope_do_not_add_a_choice():
    source = candidate()
    source["original_text"] = "求实数 m 的取值范围。"
    assert match(source) is None
    source = candidate()
    source["root"]["goals"].append({"kind": "find_range", "symbol": "x"})
    assert match(source)["reason"] == "choice.ambiguous_scope"


def test_child_uses_its_own_symbol_and_option_block():
    first, second = candidate(symbol="a"), candidate(symbol="k")
    first["root"]["label"], second["root"]["label"] = "（1）", "（2）"
    source = {"original_text": "（1）" + first["original_text"] + "（2）" + second["original_text"],
              "root": {"children": [first["root"], second["root"]]}}
    result = match(source, target="/root/children/1/goals/0")
    assert result["status"] == "matched"
    assert result["target_ref"] == "/root/children/1/goals/0"
    assert result["options"][0]["text"] == "k≤-2 或 k≥2"


def test_range_matching_requires_the_verified_exact_set_not_its_display():
    source = candidate()
    answer = finalize_goal(source["root"]["goals"][0], FEASIBLE)
    assert match_original_choice(source, TARGET, answer)["reason"] == "choice.exact_answer_required"
    assert match_original_choice(source, TARGET, answer, encode_value(sp.S.Reals))["status"] == "unavailable"


@pytest.mark.parametrize("kind,feasible,options,label", [
    ("find_minimum", sp.Interval(-sp.Rational(5, 2), sp.oo), ["-2", "-5/2", "0", "2"], "B"),
    ("find_maximum", sp.Interval(-sp.oo, sp.sqrt(2)), ["1", "2", "sqrt(8)/2", "0"], "C"),
    ("find_minimum", sp.FiniteSet(2), ["m=0", "m=1", "m=2", "m=3"], "C"),
])
def test_attained_scalar_extrema_are_matched_exactly(kind, feasible, options, label):
    assert match(candidate(options, kind=kind), feasible)["correct_labels"] == [label]


@pytest.mark.parametrize("feasible", [sp.Interval.open(2, sp.oo), sp.S.Reals, sp.S.EmptySet])
def test_unattained_or_nonexistent_minimum_never_selects_the_bound(feasible):
    result = match(candidate(["0", "1", "2", "3"], kind="find_minimum"), feasible)
    assert result["reason"] == "choice.unattained_answer_unsupported"


def test_scalar_goal_does_not_accept_a_range_of_values_as_one_option():
    result = match(candidate(["2", "m≥2", "0", "1"], kind="find_minimum"), sp.Interval(2, sp.oo))
    assert result["status"] == "unavailable"
