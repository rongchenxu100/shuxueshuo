"""M1 fixed-polynomial domains use complete exact partitions, not samples as proof."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.function_domain import (
    MAX_FIXED_POLYNOMIAL_DEGREE,
    MAX_RADICAND_DEGREE,
    inspect_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_one.function_domain_parameter import (
    inspect_match_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    function_domain,
    interaction,
)
from tests.solver.test_graph_stage_three_function_domain import (
    TARGET,
    candidate,
    execute,
)


@pytest.mark.parametrize("expression,expected", [
    ("sqrt(-2*x^3)", sp.Interval(-sp.oo, 0)),
    ("sqrt((x-2)^3*(x+1)^2)", sp.Union(sp.FiniteSet(-1), sp.Interval(2, sp.oo))),
    ("sqrt(-x^2*(x-1)^2*(x+2)^2)", sp.FiniteSet(-2, 0, 1)),
    ("sqrt((x-3)*(x-1)*(x+1)*(x+2))", sp.Union(sp.Interval(-sp.oo, -2), sp.Interval(-1, 1), sp.Interval(3, sp.oo))),
    ("sqrt(x^6+1)", sp.S.Reals),
    ("sqrt(x^6+x^2+1)", sp.S.Reals),
    ("sqrt(-x^6-1)", sp.S.EmptySet),
    ("sqrt(x^6-x^6)", sp.S.Reals),
    ("sqrt((x^2+1)*(x-1)^3)", sp.Interval(1, sp.oo)),
    ("sqrt(x^4+2*x^2+1)", sp.S.Reals),
    ("sqrt((x^3-1)^2)", sp.S.Reals),
    ("1/sqrt((x^3-1)^2)", sp.S.Reals - sp.FiniteSet(1)),
    ("sqrt(-2*x^3)/(x^2-1)", sp.Interval(-sp.oo, 0) - sp.FiniteSet(-1)),
    ("1/(x^6+1)", sp.S.Reals),
    ("1/(x^4-1)", sp.S.Reals - sp.FiniteSet(-1, 1)),
    ("1/(x^4-2*x^2+1)", sp.S.Reals - sp.FiniteSet(-1, 1)),
    ("1/(0*x^6)", sp.S.EmptySet),
    ("1/((x^3-1)*0)", sp.S.EmptySet),
    ("(x^3-x)^0", sp.S.Reals - sp.FiniteSet(-1, 0, 1)),
    ("abs(x^6+1)", sp.S.Reals),
    ("(sqrt(-2*x^3))^2", sp.Interval(-sp.oo, 0)),
    ("sqrt(-2*x^3)*sqrt(1-x)", sp.Interval(-sp.oo, 0)),
    ("sqrt((x^3-1)^2)/(x^4-1)", sp.S.Reals - sp.FiniteSet(-1, 1)),
    ("sqrt((x^2-1)^3)", sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(1, sp.oo))),
    ("sqrt((2*x-1)^3*(3*x+2)^2)", sp.Union(sp.FiniteSet(sp.Rational(-2, 3)), sp.Interval(sp.Rational(1, 2), sp.oo))),
    ("sqrt(x)/(-sqrt(x))", sp.Interval.open(0, sp.oo)),
    ("1/(-(-sqrt(x)))", sp.Interval.open(0, sp.oo)),
    ("1/(-(sqrt(x)*(x-1)))", sp.Interval.open(0, sp.oo) - sp.FiniteSet(1)),
    ("1/(-(x-1)^0)", sp.S.Reals - sp.FiniteSet(1)),
    ("1/(-sqrt(0*x))", sp.S.EmptySet),
])
def test_complete_polynomial_domain_solves_verifies_and_compiles_all_m1_interactions(expression, expected):
    original = candidate(expression)
    frozen = deepcopy(original)
    context, state = execute(original)
    assert context["domain_goal"]["structure_supported"]
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == expected
    assert state["verification"]["status"] == "verified"
    wrong = sp.S.EmptySet if expected == sp.S.Reals else sp.S.Reals
    assert function_domain.verify_domain(original, TARGET, context, wrong)["status"] == "math_failed"
    endpoints = function_domain.domain_endpoints(original, TARGET, expected)
    assert endpoints["status"] == "passed" and all(row["passed"] for row in endpoints["points"])
    chunks, pending = interaction.compile_route(state["interaction_seeds"], interaction.load_registry())
    assert not pending and len(chunks) == 4
    for chunk, diagnostics in chunks:
        assert chunk["status"] == "interactive", diagnostics
        interaction.validate_chunk(chunk)
    assert original == frozen


@pytest.mark.parametrize("expression", [
    "sqrt(x^7-1)", "sqrt((x^4+1)^2)", "sqrt(x^3-2)",
    "sqrt((x-1)*(x^3-2))", "sqrt((x^2-2)^2)", "sqrt(x^6-2)",
    "1/(x^4-2)", "(x^3-2)^0", "abs(x^4-2)",
    "sqrt((x^3-1)/(x-1))", "sqrt((sqrt(x))^2)", "sqrt(a*x^3)",
])
def test_degree_irrational_roots_inner_holes_and_parameters_stay_unadmitted(expression):
    original = candidate(expression)
    assert not inspect_domain_target(original, TARGET)["structure_supported"]
    context, state = execute(original)
    assert state["status"] == "capability_gap"
    assert function_domain.verify_domain(original, TARGET, context, sp.S.Reals)["status"] == "capability_gap"


def test_independent_roots_record_zero_polynomial_and_repeated_roots_correctly():
    _, repeated = execute(candidate("sqrt((x-2)^3*(x+1)^2)"))
    row, = repeated["verification"]["proof"]["critical_polynomials"]
    assert row["ast_path"] == [2]
    assert row["root_completeness"] == {
        "method": "exact_real_roots_and_sturm_count", "passed": True,
        "distinct_real_roots": 2, "all_rational": True,
    }
    _, zero = execute(candidate("sqrt(x^6-x^6)"))
    row, = zero["verification"]["proof"]["critical_polynomials"]
    assert row["root_completeness"] == {
        "method": "constant_polynomial", "passed": True,
        "identically_zero": True, "critical_points_required": False,
    }


def test_negated_radical_denominator_retains_original_paths_and_strict_zero_exclusion():
    context, state = execute(candidate("1/(-sqrt(x))"))
    rows = function_domain.extract_domain_conditions(context)["outputs"]["constraints"]
    assert [(row["kind"], row["ast_path"]) for row in rows] == [
        ("denominator_nonzero", [2, 1]), ("radicand_nonnegative", [2, 1, 2]),
    ]
    polynomial, = state["verification"]["proof"]["critical_polynomials"]
    assert polynomial["ast_path"] == [2, 1, 2]
    assert {(row["kind"], tuple(row["ast_path"])) for row in polynomial["condition_sources"]} == {
        ("denominator_nonzero", (2, 1)), ("radicand_nonnegative", (2, 1, 2)),
    }
    assert driver.export_values(state)["feasible_set"] == sp.Interval.open(0, sp.oo)


def test_producer_root_list_cannot_convince_original_domain_verifier(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three.capabilities import cases

    original = candidate("sqrt((x-2)^3*(x+1)^2)")
    # Deliberately corrupt only the producer. It misses the isolated legal x=-1;
    # verification must reconstruct that point from the source independently.
    monkeypatch.setattr(cases, "_real_roots", lambda polynomial: [sp.Integer(2)])
    context, state = execute(original)
    assert state["status"] == "method_complete"
    assert driver.export_values(state)["feasible_set"] == sp.Interval(2, sp.oo)
    assert state["verification"]["status"] == "math_failed"
    assert function_domain.verify_domain(original, TARGET, context,
                                         sp.Union(sp.FiniteSet(-1), sp.Interval(2, sp.oo)))["status"] == "verified"


def test_fixed_polynomial_extension_preserves_coefficient_and_parameter_family_limits():
    assert MAX_RADICAND_DEGREE == 2 and MAX_FIXED_POLYNOMIAL_DEGREE == 6
    large = 2**100
    for expression in (f"sqrt(({large}*x+1)*({large}*x-1))", f"sqrt(({large}*x+1)^2)"):
        description = inspect_domain_target(candidate(expression), TARGET)
        assert not description["structure_supported"] and description["reason"] == "domain.coefficient_limit"
    source = {"original_text": "已知定义域求参数", "root": {
        "definitions": ["f(x)=sqrt(m*x^3+1)"], "facts": [],
        "goals": [{"kind": "match_domain", "object": "f", "domain": "ℝ", "symbol": "m"}],
    }}
    assert not inspect_match_domain_target(source, TARGET)["structure_supported"]
