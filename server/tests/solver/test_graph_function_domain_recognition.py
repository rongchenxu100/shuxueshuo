"""Concrete domain extraction is structural, scoped and independent of solving."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_one.function_domain import (
    inspect_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
from shuxueshuo_server.graph_lesson.stage_two.recognition import (
    derive_knowledge,
    evaluate_types,
)
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_parser import NotationError
from shuxueshuo_server.problem_understanding.notation_semantics import canonical

REPO = Path(__file__).resolve().parents[3]
TARGET = "/root/goals/0"


def candidate(expression="sqrt(x-1)/(x-2)", *, variable="x", domain=None, goal=None):
    target = goal or {"kind": "find_domain", "object": "f"}
    if domain is not None:
        target["input_domain"] = domain
    return {"original_text": rf"求函数 $f({variable})={expression}$ 的定义域。",
            "root": {"definitions": [f"f({variable})={expression}"], "goals": [target]}}


def rows(value):
    result = extract_features(value)
    assert result["ok"], result
    return result["features"]


def recognized(value):
    return [report["type_id"] for report in evaluate_types(rows(value)) if report["status"] == "supported"]


@pytest.mark.parametrize("expression,variable,domain", [
    ("sqrt(x-1)/(x-2)", "x", None),
    ("sqrt(x-3)/(x-5)", "x", None),
    ("sqrt(x-2)/(x-2)", "x", None),
    ("sqrt(x-1)/(x+1)", "x", None),
    ("sqrt(3-x)/(x-2)", "x", None),
    ("1/sqrt(x-2)", "x", None),
    ("sqrt(x-2)+sqrt(1-x)", "x", None),
    ("sqrt(x-1)/(x-2)", "x", "[0,1]"),
    ("sqrt(5-t)/(t+3)", "t", "(-∞,5]"),
    ("sqrt(0.5*u-1/3)/(2*u+7)", "u", None),
    ("sqrt(x-1)+sqrt(x-1)", "x", None),
    ("(x+4)^0*(x^2-1)/(x-1)", "x", None),
    ("(t-3)^0+t^12", "t", None),
    ("((u-1)/(u-1))^2", "u", None),
    ("sqrt(x-1)^2", "x", None),
    ("(x^8)^8", "x", None),
    ("sqrt(x^2-1)", "x", None),
    ("sqrt(x*x-1)", "x", None),
    ("sqrt(3-2*x-x^2)", "x", None),
    ("abs(x^2)/(x-1)", "x", None),
    ("sqrt((2*x^2+1)^2)", "x", None),
    ("(2*x+1)/((2*x-1)^0*sqrt(3-2*x-x^2))", "x", None),
])
def test_supported_boundary_is_structural_and_keeps_original_source(expression, variable, domain):
    value = candidate(expression, variable=variable, domain=domain)
    frozen = deepcopy(value)
    assert validate_candidate(value)["contract_valid"]
    description = inspect_domain_target(value, TARGET)
    assert description["structure_supported"], description
    assert description["variable"] == variable
    assert description["expression"] == expression
    assert description["source_ref"] == "/root/definitions/0"
    assert description["input_domain_source_ref"] == (TARGET + "/input_domain" if domain else "")
    feature = next(row for row in rows(value) if row["feature_id"] == "function_domain")
    assert feature["status"] == "known"
    assert feature["conditions"] == []  # No solving or domain restrictions manufactured here.
    assert feature["value"] == description
    assert value == frozen
    assert recognized(value) == ["type-function-domain"]


def test_source_paths_point_to_original_radical_and_divisor_even_if_redundant():
    value = inspect_domain_target(candidate("sqrt(x-1)/(x+1)"), TARGET)
    body = value["expression_ast"]
    assert body[1][2] == ["-", ["bound", "function_argument"], ["number", "1"]]
    assert body[2] == ["+", ["bound", "function_argument"], ["number", "1"]]
    assert value["has_radical"] and value["has_division"]
    assert value["expression_latex"].startswith(r"\frac{\sqrt{")
    assert "solution" not in value


@pytest.mark.parametrize("expression,latex", [
    ("sqrt(x-1)/(x-2)", r"\frac{\sqrt{x-1}}{x-2}"),
    ("(sqrt(x))^2", r"\left(\sqrt{x}\right)^{2}"),
    ("sqrt(x^2)", r"\sqrt{x^{2}}"),
    ("(sqrt(x-1))^0", r"\left(\sqrt{x-1}\right)^{0}"),
    ("(2*x+1)/sqrt(3-2*x-x^2)+(2*x-1)^0",
     r"\frac{2\cdot x+1}{\sqrt{3-2\cdot x-x^{2}}}+(2\cdot x-1)^{0}"),
    ("(x+4)^0*(x^2-1)/(x-1)", r"\frac{(x+4)^{0}\cdot (x^{2}-1)}{x-1}"),
])
def test_expression_latex_uses_precedence_not_universal_wrapping(expression, latex):
    assert inspect_domain_target(candidate(expression), TARGET)["expression_latex"] == latex


@pytest.mark.parametrize("expression", [
    "sqrt(m*x-1)/(x-2)",
    "sqrt((x-1)/(x-2))", "sqrt(sqrt(x-1))", "abs(x^3)/(x-1)",
    "1/(x*x-1)", "1/(sqrt(x)+1)", "(x^2-1)^0", "1/(x^2-1)",
    "sqrt(x^3-1)", "sqrt(1/(x-1))",
    "sqrt(x^2+x-1)", "sqrt(x^2-2)", "1/sqrt(x^2+x-1)",
    "sqrt((x-1)^0+1)", "sqrt(((2^12)^12)^12)",
])
def test_out_of_scope_structure_is_not_silently_partially_admitted(expression):
    value = candidate(expression)
    assert validate_candidate(value)["contract_valid"]
    description = inspect_domain_target(value, TARGET)
    assert description["structure_supported"] is False
    assert description["reason"].startswith("domain.")
    assert "type-function-domain" not in recognized(value)


@pytest.mark.parametrize("domain", ["[0,m]", "{1,2}", "[0,1]∪[2,3]"])
def test_non_fixed_or_non_interval_input_restrictions_are_rejected(domain):
    value = candidate(domain=domain)
    if validate_candidate(value)["contract_valid"]:
        assert not inspect_domain_target(value, TARGET)["structure_supported"]
    else:
        with pytest.raises(NotationError, match="domain.invalid_candidate"):
            inspect_domain_target(value, TARGET)


def test_additional_conditions_cannot_be_dropped_to_force_a_domain_route():
    value = candidate()
    value["root"]["facts"] = ["x∈[0,1]"]
    description = inspect_domain_target(value, TARGET)
    assert not description["structure_supported"]
    assert description["reason"] == "domain.additional_conditions_unsupported"


def test_input_domain_is_a_typed_goal_part_and_changes_semantics():
    unrestricted, restricted = candidate(), candidate(domain="[0,1]")
    reports = [NotationValidator().validate_root(v["root"], contracts.schema()["$defs"]) for v in [unrestricted, restricted]]
    assert all(r.ok for r in reports)
    domain = reports[1].semantic["goals"][0]["input_domain"]
    assert domain == ["interval", True, True, ["number", "0"], ["number", "1"]]
    assert canonical(reports[0]) != canonical(reports[1])
    explicit_real = NotationValidator().validate_root(candidate(domain="ℝ")["root"], contracts.schema()["$defs"])
    assert canonical(reports[0]) == canonical(explicit_real)
    assert not validate_candidate(candidate(domain="2"))["contract_valid"]
    invalid = candidate(goal={"kind": "find_domain", "object": "x"})
    assert not validate_candidate(invalid)["contract_valid"]


def test_inherited_definition_and_sibling_restrictions_keep_their_scope():
    value = candidate()
    value["root"]["goals"] = []
    value["root"]["children"] = [
        {"label": "(1)", "goals": [{"kind": "find_domain", "object": "f", "input_domain": "[0,1]"}]},
        {"label": "(2)", "goals": [{"kind": "find_domain", "object": "f"}]},
    ]
    first = inspect_domain_target(value, "/root/children/0/goals/0")
    second = inspect_domain_target(value, "/root/children/1/goals/0")
    assert first["structure_supported"] and second["structure_supported"]
    assert first["source_ref"] == second["source_ref"] == "/root/definitions/0"
    assert first["input_domain_source_ref"] == "/root/children/0/goals/0/input_domain"
    assert second["input_domain_ast"] == ["real"]


@pytest.mark.parametrize("goal", [{"kind": "find_value", "expression": "f(3)"}, {"kind": "find_range", "symbol": "x"}])
def test_same_formula_different_goal_never_becomes_find_domain(goal):
    value = candidate(goal=goal)
    assert "type-function-domain" not in recognized(value)


def test_feature_value_schema_and_only_actual_knowledge_are_used():
    value = candidate()
    schema = json.loads((REPO / "internal/schemas/graph-stage-two-input-feature-values-v1.schema.json").read_text())
    features = rows(value)
    for row in features:
        if row["status"] == "known":
            Draft202012Validator({**schema, "$ref": f"#/$defs/{row['feature_id']}"}).validate(row["value"])
    knowledge = derive_knowledge(features, "type-function-domain")
    assert {item["ref"] for item in knowledge["items"]} == {
        "function-concept#elements", "square-root-expression#meaning", "rational-expression#meaning"}
    assert not any(item["ref"].startswith(("quantifiers#", "quadratic-inequality#")) for item in knowledge["items"])
    assert next(row for row in features if row["feature_id"] == "function_domain")["value"][
        "has_quadratic_condition"
    ] is False


@pytest.mark.parametrize("expression,expected", [
    ("sqrt(x^2-1)", True),
    ("sqrt(3-2*x-x^2)", True),
    ("(2*x+1)/sqrt(3-2*x-x^2)+(2*x-1)^0", True),
    ("sqrt(x-1)/(x-2)", False),
    ("(x+4)^0*(x^2-1)/(x-1)", False),
])
def test_quadratic_radicand_lights_quadratic_inequality_knowledge(expression, expected):
    features = rows(candidate(expression))
    feature = next(row for row in features if row["feature_id"] == "function_domain")
    assert feature["value"]["has_quadratic_condition"] is expected
    refs = {item["ref"] for item in derive_knowledge(features, "type-function-domain")["items"]}
    assert ("quadratic-inequality#signs" in refs) is expected


def test_domain_solve_emits_quadratic_signs_only_for_quadratic_conditions():
    import sympy as sp

    from shuxueshuo_server.graph_lesson.stage_three.capabilities import REGISTRY

    x = sp.Symbol("x", real=True)
    linear = REGISTRY["solve_conditions"](
        conditions=[sp.Ge(x - 1, 0, evaluate=False)],
        combiner="all",
        variable=x,
        purpose="domain",
    )
    assert linear["operations"] == ["domain_condition_sets"]
    quadratic = REGISTRY["solve_conditions"](
        conditions=[sp.Ge(3 - 2 * x - x**2, 0, evaluate=False)],
        combiner="all",
        variable=x,
        purpose="domain",
    )
    assert quadratic["operations"] == ["domain_condition_sets", "quadratic_signs"]


def test_verifier_uses_algebraic_zero_at_radical_roots():
    """Regression: unsimplified radicands at exact roots must stay undefined."""
    import sympy as sp

    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.function_domain import (
        _critical,
        _evaluate,
        verify_domain,
    )

    expression = "1/sqrt(x^2-1)"
    value = candidate(expression)
    context = build_context(value, TARGET)
    correct = sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(1, sp.oo))
    wrong = sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(1, sp.oo))
    assert verify_domain(value, TARGET, context, correct)["status"] == "verified"
    assert verify_domain(value, TARGET, context, wrong)["status"] == "math_failed"
    points, rows = _critical(context["domain_goal"])
    assert points == [-1, 1]
    assert [source["ast_path"] for source in rows[0]["condition_sources"]] == [[2], [2, 2]]
    # Even irrational algebraic roots must evaluate as undefined (not verified as open).
    radical = [
        "/",
        ["number", "1"],
        [
            "call",
            "sqrt",
            [
                "-",
                ["+", ["^", ["bound", "function_argument"], ["number", "2"]], ["bound", "function_argument"]],
                ["number", "1"],
            ],
        ],
    ]
    for root in ((-1 - sp.sqrt(5)) / 2, (-1 + sp.sqrt(5)) / 2):
        assert _evaluate(radical, root) == (False, None)


@pytest.mark.parametrize("expression,expected", [
    ("(x+4)^0*(x^2-1)/(x-1)", True),
    ("x^2", False),
    ("((x+4)^0)^2", True),
    ("sqrt(x-1)/(x-2)", False),
])
def test_zero_power_feature_and_knowledge_follow_original_syntax(expression, expected):
    features = rows(candidate(expression))
    feature = next(row for row in features if row["feature_id"] == "function_domain")
    assert feature["value"]["has_zero_power"] is expected
    refs = {item["ref"] for item in derive_knowledge(features, "type-function-domain")["items"]}
    assert ("integer-power#zero-exponent" in refs) is expected
    if expected:
        assert "^{0}" in feature["value"]["expression_latex"]


@pytest.mark.parametrize("expression,reason", [
    ("x^-1", "domain.fixed_nonnegative_integer_exponent_required"),
    ("x^(1/2)", "domain.fixed_nonnegative_integer_exponent_required"),
    ("x^0.5", "domain.fixed_nonnegative_integer_exponent_required"),
    ("x^m", "domain.fixed_nonnegative_integer_exponent_required"),
    ("x^13", "domain.integer_exponent_limit"),
    ("(x^9)^8", "domain.nested_power_limit"),
    ("(sqrt(x-1))^0", "domain.fixed_affine_condition_required"),
    ("(x^2-1)^0", "domain.fixed_affine_condition_required"),
    ("abs(x^3)", "domain.fixed_affine_condition_required"),
])
def test_power_limits_and_unsupported_reasons_remain_explicit(expression, reason):
    value = candidate(expression)
    description = inspect_domain_target(value, TARGET)
    assert description["structure_supported"] is False
    assert description["reason"] == reason
    assert "type-function-domain" not in recognized(value)


def test_d1_uses_unique_original_definition_and_goal_quotes():
    value = candidate()
    value["original_text"] = r"求函数 $f(x)=\frac{\sqrt{x-1}}{x-2}$ 的定义域。"
    features = rows(value)
    d1 = build_d1(value, TARGET, features, derive_knowledge(features, "type-function-domain"))
    by_kind = {fragment["fragment_kind"]: fragment for fragment in d1["fragments"]}
    assert set(by_kind) == {"expression", "goal"}
    assert "square-root-expression#meaning" in by_kind["expression"]["knowledge_refs"]
    assert "function-concept#elements" in by_kind["goal"]["knowledge_refs"]
    for fragment in d1["fragments"]:
        assert value["original_text"][fragment["start"]:fragment["end"]] == fragment["text"]
    value["original_text"] += r"另有 $f(x)=x-1$。"
    duplicate = build_d1(value, TARGET, features, derive_knowledge(features))
    assert all(fragment["fragment_kind"] != "expression" for fragment in duplicate["fragments"])
    assert any(d["code"] == "d1.function_definition_not_uniquely_located" for d in duplicate["diagnostics"])


@pytest.mark.parametrize("formula", [
    r"f(x)=\frac{\sqrt{x-1}}{x-3}",
    r"f(x)=\sqrt{x-1}",
    r"f(x)=\unknown{\frac{\sqrt{x-1}}{x-2}}",
])
def test_d1_does_not_bind_a_unique_but_different_or_unreadable_definition(formula):
    value = candidate()
    value["original_text"] = "求函数 $" + formula + "$ 的定义域。"
    features = rows(value)
    reading = build_d1(value, TARGET, features, derive_knowledge(features, "type-function-domain"))
    assert {fragment["fragment_kind"] for fragment in reading["fragments"]} == {"goal"}
    assert any(item["code"] == "d1.function_definition_not_uniquely_located" for item in reading["diagnostics"])


def test_d1_cannot_bind_a_cancelled_body_even_when_the_output_values_agree():
    value = candidate("(x-1)/(x-1)")
    value["original_text"] = "求函数 $f(x)=1$ 的定义域。"
    features = rows(value)
    reading = build_d1(value, TARGET, features, derive_knowledge(features, "type-function-domain"))
    assert {fragment["fragment_kind"] for fragment in reading["fragments"]} == {"goal"}
