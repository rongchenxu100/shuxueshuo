"""Independent selection gold and mathematical counterexamples; zero LLM."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import fragments, premises, selection
from shuxueshuo_server.graph_lesson.stage_three.premises import (
    check_premise,
    parse_expression,
)
from shuxueshuo_server.graph_lesson.stage_three.selection import (
    evaluate_goal,
    load_contract,
)
from shuxueshuo_server.graph_lesson.stage_three.verification import VerificationGap
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.problem_understanding.notation_semantics import bounded_expand
from tests.solver.test_graph_stage_one_features import assert_subset

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = FIXTURES / "graph-guided-stage-one/quadratic-always"
GOLD = json.loads((FIXTURES / "graph-guided-stage-three/selection.gold.json").read_text())["cases"]
ROOT = Path(__file__).resolve().parents[3]
PRIMARY = "type-quantified-quadratic"
TARGET = "/root/goals/0"


def candidate(fact, symbol="a", kind="find_range"):
    return {"original_text": fact, "root": {"facts": [fact], "goals": [
        {"kind": kind, "symbol" if kind == "find_range" else "expression": symbol}
    ]}}


def problem(case):
    return (candidate("∀x∈(0,1/2]:x^2+a*x+1>=0", kind="find_minimum") if case == "q13" else
            json.loads((CORPUS / case / "notation.gold.json").read_text()))


def evaluate(value, target=TARGET):
    rows = extract_features(value)
    assert rows["ok"], rows
    return evaluate_goal(value, target, rows["features"], PRIMARY)


@pytest.mark.parametrize("admission", [None, "another_problem_type"])
def test_unknown_direct_admission_cannot_fall_through_to_function_domain(monkeypatch, admission):
    from shuxueshuo_server.graph_lesson.stage_three import function_domain

    contract = load_contract("type-function-domain")
    if admission is None:
        contract.pop("admission")
    else:
        contract["admission"] = admission
    # Simulate a future loader/schema accepting a new category. Runtime must
    # reject it before interpreting the candidate with the current domain guard.
    monkeypatch.setattr(selection, "load_contract", lambda primary: contract)

    def unexpected_domain_check(context):
        pytest.fail("unknown direct admission used the function-domain check")

    monkeypatch.setattr(function_domain, "admitted", unexpected_domain_check)
    with pytest.raises(ValueError, match="^selection.unsupported_direct_admission$"):
        evaluate_goal({}, TARGET, [], "type-function-domain")


@pytest.mark.parametrize("expression,expected", [
    ("sqrt(x-1)/(x-2)", "no_verified_route"),
    ("sqrt(x-a)/(x-2)", "no_applicable_method"),
])
def test_declared_function_domain_admission_rechecks_original_candidate(expression, expected):
    value = {"original_text": "求函数定义域", "root": {
        "definitions": ["f(x)=" + expression], "facts": [],
        "goals": [{"kind": "find_domain", "object": "f"}],
    }}
    result = evaluate_goal(value, TARGET, [], "type-function-domain")
    assert result["status"] == expected


def branch(result, key):
    return next(b for b in result["selection"]["branches"] if b["branch"] == key)


def assert_gold(result, expected):
    assert result["status"] == "no_verified_route"
    assert result["d3"]["expected_answer"]["cell"] == expected["cell"]
    for key, conclusion in expected["branches"].items():
        actual = branch(result, key)
        assert {field: actual[field] for field in conclusion} == conclusion
    options = result["d4"]["options"]
    assert options and all(o["route_plan"] == "capability_gap" for o in options)
    assert all(o["message"] == "详细步骤暂不支持" for o in options)


@pytest.mark.parametrize("case", list(GOLD))
def test_independent_authored_selection_gold(case):
    value = problem(case)
    original = deepcopy(value)
    rows = extract_features(value)["features"]
    if case != "q13":
        feature_gold = json.loads((CORPUS / case / "features.gold.json").read_text())["features"]
        lookup = {(row["target_ref"], row["feature_id"]): row for row in rows}
        for expected in feature_gold:
            assert_subset(expected, lookup[expected["target_ref"], expected["feature_id"]])
    for expected in GOLD[case]:
        selected = [r for r in rows if r["target_ref"] == expected["target_ref"]]
        assert next(t for t in evaluate_types(selected) if t["type_id"] == PRIMARY)["status"] == "supported"
        assert_gold(evaluate_goal(value, expected["target_ref"], rows, PRIMARY), expected)
    assert value == original


def test_q01_demo_shape_and_evidence():
    result = evaluate(problem("q01"))
    demo = json.loads((ROOT / "site/data/graph-walk/quadratic-always-q01.source.json").read_text())
    expected = next(item for item in demo["intro"] if item["id"] == "D3")
    actual = result["d3"]
    assert actual["interaction"]["coverage"] == expected["interaction"]["coverage"]
    assert actual["expected_answer"] == expected["expected_answer"]
    assert {key: v["value"] for key, v in actual["verdicts"].items()} == {
        key: v["value"] for key, v in expected["verdicts"].items()
    }
    assert "$-1$" in actual["verdicts"]["discriminant"]["message"]
    assert "已在一边" in actual["verdicts"]["separation"]["message"]
    assert "也是区间" in actual["verdicts"]["interval"]["message"]
    assert "参数 $a$" in actual["verdicts"]["swap"]["message"]


@pytest.mark.parametrize("case,zeros", [("q01", "EmptySet"), ("q02", "{0}"), ("q03", "{-1, 1}")])
def test_exact_degeneration_sets(case, zeros):
    check = branch(evaluate(problem(case)), "discriminant")["checks"][0]
    assert check["status"] == "holds"
    assert check["bindings"]["zero_set"] == zeros


def test_sign_counterexample_points_are_in_domain_and_have_claimed_sign():
    result = evaluate(problem("q02"))
    check = next(c for c in branch(result, "separation")["checks"] if c["check_id"] == "divisor_sign")
    assert check["status"] == "fails"
    assert {e["sign"] for e in check["evidence"]} >= {"positive", "negative"}
    for evidence in check["evidence"]:
        point, value = (parse_expression(evidence[k]) for k in ("point", "value"))
        assert bounded_expand(point**2 + 2*point - 1 - value) == 0


def test_zero_divisor_without_sign_change_is_not_applicable():
    result = evaluate(candidate("∀x∈[-1,1]:a*x^2+1>=0"))
    check = next(c for c in branch(result, "separation")["checks"] if c["check_id"] == "divisor_sign")
    assert check["status"] == "fails"
    assert any(e["point"] == "0" and e["sign"] == "zero" for e in check["evidence"])


def test_negative_domain_divisor_and_parameter_rank_failure():
    negative = branch(evaluate(problem("q06")), "separation")["checks"]
    assert next(c for c in negative if c["check_id"] == "divisor_sign")["bindings"]["sign"] == "negative"
    rank = branch(evaluate(problem("q03")), "separation")["checks"]
    assert rank[0]["status"] == "fails"
    assert rank[0]["reason"] == "parameter_coefficients_not_proportional"


def test_existential_full_real_prefers_discriminant_and_dynamic_coverage():
    result = evaluate(candidate("∃x∈ℝ:x^2-2*x+a>=0"))
    assert result["selection"]["recommendation_rule"] == "discriminant-first"
    assert branch(result, "discriminant")["recommendation"] == "preferred"
    assert branch(result, "interval")["recommendation"] == "superseded"
    coverage = result["d3"]["interaction"]["coverage"]
    assert ["real", "free"] not in coverage["interval"]
    assert ["real", "free"] in coverage["discriminant"]
    message = result["d3"]["verdicts"]["discriminant"]["message"]
    assert "存在实数 $x$" in message and "对所有" not in message


@pytest.mark.parametrize("fact,rule", [
    ("∀x∈[1,2]:(a^2-1)*x^2-(a-1)*x-1<0", "interval-with-cases"),
    ("∃x∈[1,2]:(a^2-1)*x^2-(a-1)*x-1<0", "interval-with-cases"),
])
def test_recommendation_when_interval_is_only_applicable_method(fact, rule):
    result = evaluate(candidate(fact))
    assert result["selection"]["recommendation_rule"] == rule
    assert branch(result, "interval")["recommendation"] == "preferred"
    assert [option["branch"] for option in result["d4"]["options"]] == ["interval"]


def test_unknown_and_conditional_inputs_do_not_turn_into_counterevidence():
    value = problem("q01")
    for status in ("unknown", "conditional"):
        rows = extract_features(value)["features"]
        for row in rows:
            row["status"] = status
        result = evaluate_goal(value, TARGET, rows, PRIMARY)
        assert result["status"] == "no_applicable_method"
        assert result["d3"] is None and result["d4"] is None
        assert all(b["trigger"] == "unknown" and b["applicability"] == "unknown"
                   for b in result["selection"]["branches"])


def test_unknown_leading_coefficient_hides_only_discriminant_verdict():
    value = problem("q01")
    rows = extract_features(value)["features"]
    next(row for row in rows if row["feature_id"] == "leading_coeff_in_bound")["status"] = "unknown"
    result = evaluate_goal(value, TARGET, rows, PRIMARY)
    assert branch(result, "discriminant")["applicability"] == "unknown"
    assert "discriminant" not in result["d3"]["verdicts"]
    assert ["real", "free"] not in result["d3"]["interaction"]["coverage"]["discriminant"]


@pytest.mark.parametrize("feature", [
    "quantifier", "bound_vars", "free_vars", "goal", "domain", "domain_kind", "relation",
    "normal_form", "degree_in_bound", "degree_in_goal", "leading_coeff_in_bound", "coefficients",
    "range_var_is_principal",
])
def test_each_independently_unknown_feature_remains_an_explicit_result(feature):
    value = problem("q01")
    rows = extract_features(value)["features"]
    next(row for row in rows if row["feature_id"] == feature)["status"] = "unknown"
    result = evaluate_goal(value, TARGET, rows, PRIMARY)
    assert result["status"] in ("no_verified_route", "no_applicable_method")
    if feature in ("bound_vars", "goal"):
        assert result["status"] == "no_applicable_method"
        assert result["d3"] is None


@pytest.mark.parametrize("fact,symbol", [
    ("∀t∈ℝ:-2*t^2+8*t+7<=b^2-5*b", "b"),
    ("∀z∈[3,5]:z^2+p*z+9<0", "p"),
    ("∀u∈(-∞,0):u^2+c*u+7>=0", "c"),
])
def test_same_structure_with_new_letters_and_coefficients(fact, symbol):
    result = evaluate(candidate(fact, symbol))
    assert result["status"] == "no_verified_route"
    assert len(result["d4"]["options"]) == 2


def test_equivalent_moved_relation_does_not_claim_parameter_already_separated():
    result = evaluate(candidate("∀x∈ℝ:x^2-2*x+a^2-3*a-3>=0"))
    message = result["d3"]["verdicts"]["separation"]["message"]
    assert "移项后" in message and "无需除以" in message
    assert "已在一边" not in message
    assert_gold(result, GOLD["q01"][0])


def test_swap_zero_slope_is_accepted_and_nonlinearity_refuted():
    value = problem("q09")
    rows = extract_features(value)["features"]
    indexed = {r["feature_id"]: r for r in rows}
    check = check_premise("swap_linearity", indexed)
    assert check["status"] == "holds"
    assert parse_expression(check["bindings"]["coefficient"]).subs(parse_expression("x"), 1) == 0
    next(r for r in rows if r["feature_id"] == "normal_form")["value"]["expression"] = "a^2*x^2+1"
    assert check_premise("swap_linearity", indexed)["status"] == "fails"


@pytest.mark.parametrize("principal,parameter", [("x", "m"), ("u", "b")])
def test_swap_method_plane_keeps_original_letter_roles(principal, parameter):
    value = candidate(
        f"∀{parameter}∈[1,3]:{parameter}*{principal}^2-{parameter}*{principal}+{parameter}-6<0",
        principal,
    )
    result = evaluate(value)
    plane = result["d3"]
    assert plane["interaction"]["x"]["label"] == f"${principal}$ 取全体实数吗？"
    assert plane["interaction"]["y"]["label"] == f"参数 ${parameter}$ 有给定范围吗？"
    assert plane["expected_answer"]["cell"] == ["real", "given"]
    assert plane["feedback"]["x"] == f"再看横轴：${principal}$ 取遍全体实数。"
    assert plane["feedback"]["y"] == (
        f"再看纵轴：给出范围的是 ${parameter}$，要求的是 ${principal}$。"
    )
    coverage = plane["interaction"]["coverage"]
    assert ["real", "given"] in coverage["swap"]
    assert all(["real", "given"] not in coverage[name]
               for name in ("discriminant", "interval", "separation"))
    assert [item["branch"] for item in result["d4"]["options"]] == ["swap"]


@pytest.mark.parametrize("restriction,cell", [
    ("u∈ℝ", "real"),
    ("u∈[0,2]", "interval"),
    ("u>0", "interval"),
])
def test_swap_plane_uses_visible_original_principal_domain(restriction, cell):
    value = candidate("∀b∈[1,3]:b*u^2-b*u+b-6<0", "u")
    value["root"]["facts"].insert(0, restriction)
    plane = evaluate(value)["d3"]
    assert plane["expected_answer"]["cell"] == [cell, "given"]
    assert plane["interaction"]["x"]["label"] == "$u$ 取全体实数吗？"


def test_swap_plane_only_uses_current_target_visible_domain():
    value = candidate("∀b∈[1,3]:b*u^2-b*u+b-6<0", "u")
    goal = value["root"].pop("goals")[0]
    value["root"]["children"] = [
        {"facts": ["u∈[0,2]"], "goals": [deepcopy(goal)]},
        {"goals": [deepcopy(goal)]},
    ]
    restricted = evaluate(value, "/root/children/0/goals/0")["d3"]
    unrestricted = evaluate(value, "/root/children/1/goals/0")["d3"]
    assert restricted["expected_answer"]["cell"] == ["interval", "given"]
    assert unrestricted["expected_answer"]["cell"] == ["real", "given"]


def test_swap_selection_survives_parameter_dependent_quantifier_endpoint():
    value = candidate("∀m∈[1,x]:m*x^2-m*x+m-6<0", "x")
    result = evaluate(value)
    assert result["status"] == "no_verified_route"
    assert result["d3"]["expected_answer"]["cell"] == ["interval", "given"]
    assert result["d3"]["interaction"]["x"]["label"] == "$x$ 取全体实数吗？"
    assert any(option["branch"] == "swap" for option in result["d4"]["options"])


@pytest.mark.parametrize("reason", [
    "route_constraints.single_quantifier_required",
    "route_constraints.fixed_quantifier_domain_required",
])
def test_swap_selection_constraint_gap_falls_back_to_feature_domain(monkeypatch, reason):
    def unsupported(*_args):
        raise VerificationGap(reason)

    monkeypatch.setattr(fragments, "apply_visible_constraints", unsupported)
    result = evaluate(candidate("∀m∈[1,3]:m*x^2-m*x+m-6<0", "x"))
    assert result["d3"]["expected_answer"]["cell"] == ["interval", "given"]
    assert result["d4"]["options"]


def test_swap_selection_does_not_hide_constraint_implementation_errors(monkeypatch):
    def broken(*_args):
        raise ValueError("unexpected implementation error")

    monkeypatch.setattr(fragments, "apply_visible_constraints", broken)
    with pytest.raises(ValueError, match="unexpected implementation error"):
        evaluate(candidate("∀m∈[1,3]:m*x^2-m*x+m-6<0", "x"))


def test_no_selection_contract_and_duplicate_feature_are_explicit():
    value = problem("q01")
    rows = extract_features(value)["features"]
    assert evaluate_goal(value, TARGET, rows, "type-amgm-quantified")["status"] == "unsupported_type"
    with pytest.raises(ValueError, match="duplicate_feature"):
        evaluate_goal(value, TARGET, [*rows, rows[0]], PRIMARY)
    contract = load_contract(PRIMARY)
    assert {b["branch"]: b["route_id"] for b in contract["branches"]} == {
        "discriminant": "discriminant", "interval": "interval", "separation": "extremum", "swap": "variable"
    }


def test_parser_rejects_executable_text_and_symbolic_premises_remain_unknown():
    with pytest.raises(ValueError):
        parse_expression("__import__('os').system('echo bad')")
    value = candidate("∀x∈[1/a,2]:x^2+a*x+1>=0")
    indexed = {r["feature_id"]: r for r in extract_features(value)["features"]}
    assert check_premise("divisor_sign", indexed)["status"] == "unknown"


def test_student_messages_use_latex_while_machine_bindings_remain_available():
    q01, q03 = evaluate(problem("q01")), evaluate(problem("q03"))
    separation = next(c for c in branch(q01, "separation")["checks"] if c["check_id"] == "param_separable")
    assert separation["bindings"]["parameter_expression"] == "a^2 - 3*a"
    assert separation["display_bindings"]["parameter_expression"] == "a^{2} - 3 a"
    assert "$a^{2} - 3 a$" in q01["d3"]["verdicts"]["separation"]["message"]
    assert r"\left\{-1, 1\right\}" in q03["d3"]["verdicts"]["discriminant"]["message"]
    for result in (q01, q03):
        messages = " ".join(v["message"] for v in result["d3"]["verdicts"].values())
        assert "*" not in messages and "sqrt(" not in messages and "Interval(" not in messages


def test_radicals_and_intervals_are_rendered_from_computed_objects():
    result = evaluate(candidate("∀x∈ℝ:(a^2-2)*x^2+x+1>=0"))
    check = branch(result, "discriminant")["checks"][0]
    assert "sqrt(2)" in check["bindings"]["zero_set"]
    assert check["display_bindings"]["zero_set"] == sp.latex(sp.FiniteSet(-sp.sqrt(2), sp.sqrt(2)))
    message = result["d3"]["verdicts"]["discriminant"]["message"]
    assert r"\sqrt{2}" in message and "sqrt(" not in message
    check = branch(evaluate(problem("q13")), "interval")["checks"][0]
    assert check["bindings"]["domain"] == "Interval.Lopen(0, 1/2)"
    assert check["display_bindings"]["domain"] == sp.latex(sp.Interval.Lopen(0, sp.Rational(1, 2)))


@pytest.mark.parametrize("case,sign,direction", [("q04", ">0", "方向不变"), ("q06", "<0", "反向")])
def test_separation_message_states_the_proved_divisor_sign(case, sign, direction):
    message = evaluate(problem(case))["d3"]["verdicts"]["separation"]["message"]
    assert f"$x{sign}$" in message
    assert f"不等号{direction}" in message


@pytest.mark.parametrize("fact,opening,bound_kind", [
    ("∀x∈(1,2):x^2+a*x+4<0", "向下", "值域下端"),
    ("∃x∈(1,2):x^2+a*x+4>0", "向上", "值域上端"),
])
def test_endpoint_message_uses_normalized_direction_and_handles_open_endpoints(fact, opening, bound_kind):
    message = evaluate(candidate(fact))["d3"]["verdicts"]["interval"]["message"]
    assert f"规范化后的二次式开口{opening}" in message and f"需判断{bound_kind}" in message
    assert "端点值或端点极限" in message and "检查边界是否取得" in message
    assert "无需按对称轴位置分类" in message and "在端点取得" not in message


def test_interval_message_explains_parameter_axis_and_coefficient_cases():
    message = evaluate(problem("q06"))["d3"]["verdicts"]["interval"]["message"]
    assert "对称轴" in message and "含参数" in message and "位置关系分类" in message
    message = evaluate(candidate("∀x∈[1,2]:(a^2-1)*x^2+x+1>=0"))["d3"]["verdicts"]["interval"]["message"]
    assert "二次项系数" in message and "分类讨论开口方向与退化" in message


def test_full_real_existential_vertex_needs_no_parameter_location_cases():
    result = evaluate(candidate("∃x∈ℝ:-x^2+a*x+1>=0"))
    check = result["selection"]["recommendation_checks"][0]
    assert check["status"] == "fails" and check["reason"] == "no_parameter_cases"
    assert result["selection"]["recommendation_rule"] == "discriminant-first"
    assert branch(result, "discriminant")["recommendation"] == "preferred"
    assert branch(result, "interval")["recommendation"] == "superseded"


def test_unknown_case_split_is_not_described_as_proved(monkeypatch):
    def unknown(_):
        raise premises.UnknownPremise("unsupported_classification")

    monkeypatch.setitem(premises.CHECKS, "interval_case_split", unknown)
    message = evaluate(problem("q06"))["d3"]["verdicts"]["interval"]["message"]
    assert "是否需要按参数分类尚不能确定" in message


@pytest.mark.parametrize("error", [KeyError, ValueError, TypeError, NotImplementedError, RecursionError])
def test_premise_programming_errors_are_not_silenced(monkeypatch, error):
    def broken(_):
        raise error("implementation_bug")

    monkeypatch.setitem(premises.CHECKS, "interval_case_split", broken)
    with pytest.raises(error, match="implementation_bug"):
        check_premise("interval_case_split", {})


def test_misspelled_feature_key_is_a_programming_error(monkeypatch):
    def typo(values):
        return values.value("norml_form")

    monkeypatch.setitem(premises.CHECKS, "interval_case_split", typo)
    with pytest.raises(KeyError, match="selection.unregistered_feature:norml_form"):
        check_premise("interval_case_split", {})


@pytest.mark.parametrize("indexed", [{}, {"normal_form": {"status": "unknown"}}])
def test_registered_missing_or_unknown_feature_remains_unknown(monkeypatch, indexed):
    def read(values):
        return values.value("normal_form")

    monkeypatch.setitem(premises.CHECKS, "interval_case_split", read)
    check = check_premise("interval_case_split", indexed)
    assert check["status"] == "unknown"
    assert check["reason"] == "unknown_feature:normal_form"


@pytest.mark.parametrize("solver,check", [
    ("solveset", "degenerate_branches"), ("solve_univariate_inequality", "divisor_sign"),
])
def test_known_sympy_solver_limit_is_unknown(monkeypatch, solver, check):
    def unsupported(*args, **kwargs):
        raise NotImplementedError("unsupported math")

    monkeypatch.setattr(sp, solver, unsupported)
    indexed = {r["feature_id"]: r for r in extract_features(problem("q01"))["features"]}
    assert check_premise(check, indexed)["status"] == "unknown"
