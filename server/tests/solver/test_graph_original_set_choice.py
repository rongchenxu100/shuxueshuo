"""Set-answer closure is exact and cannot replace T1's statement verdicts."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator
from shuxueshuo_server.graph_lesson.stage_three.choice_matching import (
    match_original_choice,
)
from shuxueshuo_server.graph_lesson.stage_three.choice_source import (
    choice_source,
    option_expression,
)
from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal
from shuxueshuo_server.graph_lesson.stage_three.handoff import (
    complete_route,
    validate_original_choice,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

TARGET = "/root/goals/0"
FIXTURE = Path(__file__).parent / "fixtures/abstract-function-domain/mixed-q03-candidate.json"
EXPECTED = sp.Interval.open(sp.Rational(1, 3), 5)
SCHEMA = json.loads((Path(__file__).parents[3] / "internal/schemas/graph-original-set-choice-v1.schema.json").read_text())


def source(mode="unspecified"):
    candidate = json.loads(FIXTURE.read_text())
    candidate["public_content"]["scopes"][0]["choices"][0]["selection_mode"] = mode
    return candidate


def match(candidate):
    return match_original_choice(candidate, TARGET, finalize_goal(candidate["root"]["goals"][0], EXPECTED), encode_value(EXPECTED))


@pytest.mark.parametrize("mode,kind", [("single", "single_choice"), ("multiple", "multiple_choice"), ("unspecified", "multiple_choice")])
def test_mixed_q03_selects_d_from_verified_exact_set(mode, kind):
    candidate = source(mode)
    before = deepcopy(candidate)
    result = match(candidate)
    assert result["status"] == "matched", result
    assert result["kind"] == kind
    assert result["matching"] == "set_equality"
    assert result["selection_mode"] == mode
    assert result["correct_labels"] == ["D"]
    validate_original_choice(result, TARGET)
    Draft202012Validator(SCHEMA).validate(result)
    assert candidate == before


@pytest.mark.parametrize("count", [0, 2])
def test_multiple_and_unspecified_accept_exact_empty_or_multiple_label_sets(count):
    for mode in ("multiple", "unspecified", "single"):
        candidate = source(mode)
        options = candidate["public_content"]["scopes"][0]["choices"][0]["options"]
        options[0]["text"] = "$(1/3,5)$" if count == 2 else "$(-4,3)$"
        if count == 0:
            options[3]["text"] = "$(1/3,5]$"
        result = match(candidate)
        if mode == "single":
            assert result["status"] == "unavailable"
        else:
            assert result["correct_labels"] == (["A", "D"] if count else [])
            validate_original_choice(result, TARGET)
            Draft202012Validator(SCHEMA).validate(result)


def test_wrong_or_display_only_answer_does_not_publish_labels():
    candidate = source()
    answer = finalize_goal(candidate["root"]["goals"][0], sp.S.Reals)
    assert match_original_choice(candidate, TARGET, answer, encode_value(EXPECTED))["status"] == "unavailable"
    answer = finalize_goal(candidate["root"]["goals"][0], EXPECTED)
    assert match_original_choice(candidate, TARGET, answer)["reason"] == "choice.exact_answer_required"


def test_transcription_only_unspecified_mode_does_not_become_single_from_one_label():
    candidate = source()
    candidate.pop("public_content")
    result = match(candidate)
    assert result["kind"] == "multiple_choice"
    assert result["selection_mode"] == "unspecified"
    assert result["correct_labels"] == ["D"]


@pytest.mark.parametrize("public", [False, True])
def test_variant02_parameter_set_matches_b_without_promoting_guaranteed_domain_to_exact(public):
    candidate = json.loads((FIXTURE.parent / "variant02-candidate.json").read_text())
    if not public:
        candidate.pop("public_content")
    before = deepcopy(candidate)
    feasible = sp.Interval(-sp.Rational(1, 2), sp.Rational(1, 2))
    answer = finalize_goal(candidate["root"]["goals"][0], feasible)
    result = match_original_choice(candidate, TARGET, answer, encode_value(feasible))
    assert result["status"] == "matched", result
    assert result["kind"] == "multiple_choice"
    assert result["matching"] == "set_equality"
    assert result["selection_mode"] == "unspecified"
    assert result["correct_labels"] == ["B"]
    validate_original_choice(result, TARGET)
    Draft202012Validator(SCHEMA).validate(result)
    assert candidate == before
    assert candidate["root"]["goals"][0]["strength"] == "meaningful_only"


def test_parameter_choice_binds_a_not_the_shared_outer_variable_x():
    candidate = json.loads((FIXTURE.parent / "variant02-candidate.json").read_text())
    feasible = sp.Interval(-sp.Rational(1, 2), sp.Rational(1, 2))
    answer = finalize_goal(candidate["root"]["goals"][0], feasible)
    option = candidate["public_content"]["scopes"][0]["choices"][0]["options"][1]
    option["text"] = "$-1/2≤a≤1/2$"
    assert match_original_choice(candidate, TARGET, answer, encode_value(feasible))["correct_labels"] == ["B"]
    option["text"] = "$-1/2≤x≤1/2$"
    assert match_original_choice(candidate, TARGET, answer, encode_value(feasible))["status"] == "unavailable"


def test_set_choices_accept_standard_unbraced_fraction_and_bold_real_notation():
    assert option_expression(r"$[-\frac12,\frac12]$") == "[-((1)/(2)),((1)/(2))]"
    assert option_expression(r"$\mathbf{R}$") == "ℝ"
    assert option_expression(r"$\mathbf R$") == "ℝ"
    assert option_expression(r"$\fracUnknown{1}{2}$") is None
    assert option_expression(r"$\mathbf{R_1}$") is None


def test_public_options_are_scoped_authoritative_and_incomplete_is_not_fallback():
    candidate = source()
    candidate["original_text"] = "单选题 A. 0 B. 1 C. 2 D. 3"
    assert match(candidate)["selection_mode"] == "unspecified"
    assert match(candidate)["correct_labels"] == ["D"]
    candidate["public_content"]["scopes"][0]["choices"][0]["target_ref"] = "/root/children/0/goals/0"
    assert choice_source(candidate, TARGET)["status"] == "unavailable"


def test_set_matching_cannot_be_published_for_function_comparison():
    choice = match(source())
    with pytest.raises(ValueError, match="invalid_original_choice_goal"):
        complete_route(None, {"status": "verified", "target_ref": TARGET, "route_id": "t1"},
                       route={"status": "verified", "result": {"comparison_result": {}}},
                       verification={"status": "verified"}, feasible_set=None,
                       answer={"kind": "compare_functions", "status": "complete"},
                       original_choice=choice, commit_id="invalid")
    for field, value in (("option_verdicts", []), ("select_relation", "equal"), ("correct_labels", ["Z"])):
        with pytest.raises(ValueError, match="invalid_original_choice"):
            validate_original_choice(choice | {field: value}, TARGET)
