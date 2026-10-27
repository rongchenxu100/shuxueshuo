"""Whole structural contract for root-ratio domains on either open halfline."""

from copy import deepcopy

import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson.stage_one.function_domain_parameter import (
    inspect_match_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_three import capabilities, driver
from shuxueshuo_server.graph_lesson.stage_three.capabilities import ranges
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_domain import (
    admitted_parameter,
    extract_domain_parameter_conditions,
    reduce_domain_equality_to_universal,
)
from shuxueshuo_server.graph_lesson.stage_three.math_values import math_value
from shuxueshuo_server.graph_lesson.stage_three.verification import (
    endpoint_check,
    verify,
)
from tests.solver.test_graph_domain_parameter import (
    TARGET,
    candidate,
    execute,
    recognized,
)


def source(polynomial="x^2-3*x-m", denominator="x-1", domain="(1,∞)"):
    value = candidate(f"sqrt({polynomial})/sqrt({denominator})", parameter="m", domain=domain)
    value["original_text"] = f"函数 f(x)=sqrt({polynomial})/sqrt({denominator}) 的定义域为 {domain}，求 m 的取值范围。"
    return value


def reduction(value):
    context = build_context(value, TARGET)
    extracted = extract_domain_parameter_conditions(context)["outputs"]
    reduced = reduce_domain_equality_to_universal(**{
        key: extracted[key] for key in ("constraints", "description", "variable", "parameter", "goal", "context")
    })
    return context, extracted, reduced


MATRIX = [
    ("x^2-3*x-m", "x-1", "(1,∞)", sp.Interval(-sp.oo, -sp.Rational(9, 4)), "interior_vertex"),
    ("x^2-2*x-m", "x-1", "(1,∞)", sp.Interval(-sp.oo, -1), "vertex_at_boundary"),
    ("x^2+2*x-m", "x-1", "(1,∞)", sp.Interval(-sp.oo, 3), "vertex_outside_domain"),
    ("x^2-3*x+2*m", "x-1", "(1,∞)", sp.Interval(sp.Rational(9, 8), sp.oo), "interior_vertex"),
    ("-x^2-3*x-m", "x-1", "(1,∞)", sp.S.EmptySet, "unbounded_below"),
    ("2*x+3-m", "x-1", "(1,∞)", sp.Interval(-sp.oo, 5), "linear_boundary_limit"),
    ("-2*x+3-m", "x-1", "(1,∞)", sp.S.EmptySet, "unbounded_below"),
    ("3-m", "x-1", "(1,∞)", sp.Interval(-sp.oo, 3), "constant"),
    ("m", "x-1", "(1,∞)", sp.Interval(0, sp.oo), "constant"),
    ("x^2+2*x-m", "1-x", "(-∞,1)", sp.Interval(-sp.oo, -1), "interior_vertex"),
    ("x^2-2*x-m", "1-x", "(-∞,1)", sp.Interval(-sp.oo, -1), "vertex_at_boundary"),
    ("x^2-4*x-m", "1-x", "(-∞,1)", sp.Interval(-sp.oo, -3), "vertex_outside_domain"),
    ("-x^2+m", "1-x", "(-∞,1)", sp.S.EmptySet, "unbounded_below"),
    ("-2*x+3-m", "1-x", "(-∞,1)", sp.Interval(-sp.oo, 1), "linear_boundary_limit"),
    ("2*x+3-m", "1-x", "(-∞,1)", sp.S.EmptySet, "unbounded_below"),
    ("-3+2*m", "1-x", "(-∞,1)", sp.Interval(sp.Rational(3, 2), sp.oo), "constant"),
    ("x^2-m", "2*x-1", "(1/2,∞)", sp.Interval(-sp.oo, sp.Rational(1, 4)), "vertex_outside_domain"),
    ("x^2-m", "-3*x-2", "(-∞,-2/3)", sp.Interval(-sp.oo, sp.Rational(4, 9)), "vertex_outside_domain"),
    ("(x-2)^2-m", "x-1", "(1,∞)", sp.Interval(-sp.oo, 0), "interior_vertex"),
    ("(x-2)^2-m/2", "x-1", "(1,∞)", sp.Interval(-sp.oo, 0), "interior_vertex"),
]


@pytest.mark.parametrize("polynomial,denominator,domain,expected,kind", MATRIX)
def test_halfline_contract_has_independent_complete_proof(polynomial, denominator, domain, expected, kind):
    value = source(polynomial, denominator, domain)
    frozen = deepcopy(value)
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is True, description
    assert description["parameter_family"] == "halfline_root_ratio"
    assert recognized(value) == ["type-function-domain"]
    context, extracted, reduced = reduction(value)
    assert admitted_parameter(context)
    assert [(row["kind"], row["ast_path"], row["basis_refs"]) for row in extracted["constraints"]] == [
        ("radicand_nonnegative", [1, 2], ["square-root-expression#meaning"]),
        ("radicand_nonnegative", [2, 2], ["square-root-expression#meaning"]),
        ("denominator_nonzero", [2], ["rational-expression#meaning"]),
    ]
    outputs = reduced["outputs"]
    assert outputs["borrowed_method"] == "method-separation"
    assert outputs["strict"] is False and outputs["relation"].rel_op == ">="
    assert outputs["relation"] == extracted["constraints"][0]["condition"]
    equivalence = outputs["domain_equivalence"]
    assert equivalence["passed"] and equivalence["outside_excluded"]
    assert equivalence["condition_ids"] == ["c1", "c2", "c3"]
    assert equivalence["denominator_condition_ids"] == ["c2", "c3"]
    assert equivalence["denominator_condition"].rel_op == ">"
    assert equivalence["outside_condition"].rel_op == "<="
    assert equivalence["prescribed_domain"] == equivalence["denominator_domain"] == outputs["domain"]
    assert outputs["domain"] == outputs["denominator_domain"]
    assert sp.Union(equivalence["outside_domain"], outputs["domain"]) == sp.S.Reals
    assert sp.Intersection(equivalence["outside_domain"], outputs["domain"]) == sp.S.EmptySet
    proof = verify(value, TARGET, context, expected)
    assert proof["status"] == "verified", proof
    assert proof["proof"]["reconstructed_set"] == math_value(expected)
    assert proof["proof"]["domain_equivalence"]["outside_excluded"] is True
    assert {row["evidence"]["certificate"]["kind"] for row in proof["proof"]["cells"]} == {kind}
    assert endpoint_check(value, TARGET, expected)["status"] == "passed"
    assert value == frozen


@pytest.mark.parametrize("polynomial,denominator,domain", [
    ("x^2-m", "x-1", "[1,∞)"),
    ("x^2-m", "x-1", "(2,∞)"),
    ("x^2-m", "x-1", "(-∞,1)"),
    ("x^2-m", "x-1", "(1,3)"),
    ("x^2-m", "x-1", "ℝ"),
    ("x^2-m", "1", "(1,∞)"),
    ("x^2-m", "x^2-1", "(1,∞)"),
    ("x^2-m", "m*x-1", "(1,∞)"),
    ("m*x^2-1", "x-1", "(1,∞)"),
    ("x^2+m*x", "x-1", "(1,∞)"),
    ("x^3-m", "x-1", "(1,∞)"),
    ("x^2-m^2", "x-1", "(1,∞)"),
    ("x^2-1", "x-1", "(1,∞)"),
    ("x^2-m+0/x", "x-1", "(1,∞)"),
    ("x^2-m+x^0", "x-1", "(1,∞)"),
])
def test_wrong_guard_domains_and_unsupported_polynomials_are_rejected(polynomial, denominator, domain):
    value = source(polynomial, denominator, domain)
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is False, description
    assert not admitted_parameter(build_context(value, TARGET))
    assert "type-function-domain" not in recognized(value)


@pytest.mark.parametrize("power", [5, 6])
def test_cancellation_does_not_admit_an_over_budget_original_expansion(power):
    # The parenthesized term equals 1, but its original expansion has 6**power
    # combinations. The coefficient normal form alone must not admit it.
    value = source(f"x^2-m+((x+1)^2-x^2-2*x)^{power}")
    description = inspect_match_domain_target(value, TARGET)
    assert description["structure_supported"] is False, description
    assert description["reason"] == "semantic.expansion_limit"
    assert "type-function-domain" not in recognized(value)
    context = build_context(value, TARGET)
    assert not admitted_parameter(context)
    # Execution admission also recomputes the budget instead of trusting a
    # stale/forged supported feature from before the structural check.
    context["domain_goal"]["structure_supported"] = True
    assert not admitted_parameter(context)


def test_original_expansion_within_budget_still_executes_and_verifies():
    value = source("x^2-m+((x+1)^2-x^2-2*x)^4")
    assert inspect_match_domain_target(value, TARGET)["structure_supported"] is True
    assert recognized(value) == ["type-function-domain"]
    _, state = execute(value)
    assert state["status"] == "method_complete", state.get("diagnostics")
    assert driver.export_values(state)["feasible_set"] == sp.Interval(-sp.oo, 2)
    assert state["verification"]["status"] == "verified"


@pytest.mark.parametrize("polynomial", ["x^2-m+x^0", "x^2-m+((x+1)^12)^12"])
def test_structural_safety_checks_precede_symbolic_expansion(monkeypatch, polynomial):
    from shuxueshuo_server.graph_lesson.stage_one import function_domain_parameter

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsupported source must be rejected before SymPy conversion")

    monkeypatch.setattr(function_domain_parameter, "expression", forbidden)
    assert inspect_match_domain_target(source(polynomial), TARGET)["structure_supported"] is False


def test_halfline_proof_never_calls_method_or_range_solver(monkeypatch):
    value = source()
    context = build_context(value, TARGET)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("independent source proof cannot use a solver capability")

    monkeypatch.setattr(capabilities, "execute", forbidden)
    monkeypatch.setattr(ranges, "quadratic_interval_range", forbidden)
    monkeypatch.setattr(ranges, "linear_range", forbidden)
    monkeypatch.setattr(sp, "solve_univariate_inequality", forbidden)
    monkeypatch.setattr(sp, "reduce_inequalities", forbidden)
    correct = sp.Interval(-sp.oo, -sp.Rational(9, 4))
    assert verify(value, TARGET, context, correct)["status"] == "verified"
    for wrong in [sp.Interval.open(-sp.oo, -sp.Rational(9, 4)), sp.Interval(-sp.oo, -2),
                  sp.Interval(-3, -sp.Rational(9, 4)), sp.S.Reals, sp.S.EmptySet]:
        checked = verify(value, TARGET, context, wrong)
        assert checked["status"] == "math_failed", checked
        assert checked["counterexample"]["original_holds"] != checked["counterexample"]["candidate_includes"]
        # Endpoint membership cannot detect removal of an entire valid tail;
        # that is why the complete independent source partition is required.
        expected_status = "passed" if wrong == sp.Interval(-3, -sp.Rational(9, 4)) else "failed"
        assert endpoint_check(value, TARGET, wrong)["status"] == expected_status


@pytest.mark.parametrize("polynomial,endpoint", [("x^2-2*x-m", -1), ("x^2+2*x-m", 3), ("2*x+3-m", 5)])
def test_open_input_boundary_does_not_open_the_parameter_bound(polynomial, endpoint):
    value = source(polynomial)
    checked = endpoint_check(value, TARGET, sp.Interval(-sp.oo, endpoint))
    boundary = next(row for row in checked["points"] if row["point"] == math_value(sp.Integer(endpoint)))
    assert boundary["included"] and boundary["holds"] and boundary["passed"]
    certificate = boundary["evidence"]["certificate"]
    assert certificate["infimum"] == math_value(sp.Integer(0))
    assert certificate["infimum_attained"] is False
    assert verify(value, TARGET, build_context(value, TARGET), sp.Interval.open(-sp.oo, endpoint))["status"] == "math_failed"


@pytest.mark.parametrize("tamper", ["omit_denominator", "move_source", "change_domain", "change_family"])
def test_halfline_reduction_refuses_forged_domain_equivalence(tamper):
    context = build_context(source(), TARGET)
    extracted = extract_domain_parameter_conditions(context)["outputs"]
    values = {key: deepcopy(extracted[key]) for key in (
        "constraints", "description", "variable", "parameter", "goal", "context"
    )}
    if tamper == "omit_denominator":
        values["constraints"].pop()
    elif tamper == "move_source":
        values["constraints"][1]["ast_path"] = [1, 2]
    elif tamper == "change_domain":
        values["description"]["prescribed_domain_ast"] = ["real"]
    else:
        values["description"].pop("parameter_family")
    with pytest.raises(capabilities.LocalCheckFailed, match="domain.parameter_source_mismatch"):
        reduce_domain_equality_to_universal(**values)


@pytest.mark.parametrize("polynomial,denominator,domain,expected,_kind", MATRIX)
def test_halfline_driver_reuses_separation_and_existing_ranges(polynomial, denominator, domain, expected, _kind):
    _, state = execute(source(polynomial, denominator, domain))
    assert state["status"] == "method_complete", state.get("diagnostics") or state["trajectory"]
    assert driver.export_values(state)["feasible_set"] == expected
    assert state["verification"]["status"] == "verified"
    methods = {step["method"] for step in state["trajectory"]["steps"]}
    assert "method-separation" in methods and "method-discriminant" not in methods
    assert methods <= {"method-domain-parameter", "method-separation", "quadratic-inequality-solve"}


def test_halfline_source_preserves_renamed_symbols_and_scaled_denominator():
    value = {
        "original_text": "g(t)=sqrt((t+2)^2+2*a)/sqrt(-2*t-2) 的定义域是 (-∞,-1)，求 a。",
        "root": {"definitions": ["g(t)=sqrt((t+2)^2+2*a)/sqrt(-2*t-2)"],
                 "goals": [{"kind": "match_domain", "object": "g", "domain": "(-∞,-1)", "symbol": "a"}]},
    }
    context, extracted, reduced = reduction(value)
    assert str(extracted["variable"]) == "t" and str(extracted["parameter"]) == "a"
    assert reduced["outputs"]["domain"] == sp.Interval.open(-sp.oo, -1)
    expected = sp.Interval(0, sp.oo)
    assert verify(value, TARGET, context, expected)["status"] == "verified"
    _, state = execute(value)
    assert state["status"] == "method_complete", state.get("diagnostics")
    assert driver.export_values(state)["feasible_set"] == expected


@pytest.mark.parametrize("formula,input_domain,expected", [
    ("sqrt(2-x)", "(-∞,1]", sp.Interval(-sp.oo, 1)),
    ("sqrt(x+2)", "(-∞,1)", sp.Interval.Ropen(-2, 1)),
])
def test_signed_infinity_preserves_the_adjacent_concrete_domain_route(formula, input_domain, expected):
    from tests.solver.test_graph_stage_three_function_domain import (
        candidate as concrete_source,
    )
    from tests.solver.test_graph_stage_three_function_domain import (
        execute as concrete_execute,
    )

    value = concrete_source(formula, input_domain=input_domain)
    _, state = concrete_execute(value)
    assert state["status"] == "method_complete", state.get("diagnostics")
    assert driver.export_values(state)["feasible_set"] == expected
    assert state["verification"]["status"] == "verified"
