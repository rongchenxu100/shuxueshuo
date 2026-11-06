"""Certified interval case partitions, attained bounds and guarded unions."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    CapabilityGap,
    LocalCheckFailed,
    parametric,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.parametric import (
    _same_bound,
    merge_interval_cases,
    parametric_interval_extremum,
    partition_interval_cases,
    solve_interval_conditions,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.quantified import (
    apply_quantifier_policy,
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_stage_three_verification import check, problem

X, A = sp.symbols("x a", real=True)


@pytest.fixture
def partition_calls(monkeypatch):
    """Count full proofs, independently of cache hit/miss implementation."""
    parametric._session_partition.cache_clear()
    original = parametric._partition
    calls = []

    def counted(*arguments):
        calls.append(arguments)
        return original(*arguments)

    monkeypatch.setattr(parametric, "_partition", counted)
    yield calls
    parametric._session_partition.cache_clear()


def test_all_cases_reuse_one_partition_and_keep_complete_checks(partition_calls):
    expression, domain = X*X - 2*A*X + 3, sp.Interval(1, 2)
    policy = select_quantifier_policy("∃", ">", domain)["outputs"]["policy"]
    partition = partition_interval_cases(expression, X, A, domain, policy)
    cases = partition["outputs"]["cases"]
    assert len(cases) == 3
    for case in cases:
        computed = parametric_interval_extremum(expression, X, A, domain, policy, case)
        assert computed["checks"][0]["polynomials"] == partition["outputs"]["critical_polynomials"]
        assert computed["checks"][1]["cells"] == case["cells"]
        assert all(check["passed"] for check in computed["checks"])
    assert len(partition_calls) == 1


@pytest.mark.parametrize("changed", ["expression", "variable", "parameter", "domain", "bound",
                                    "strict", "quantifier", "operator", "empty"])
def test_partition_cache_key_covers_all_mathematical_inputs(partition_calls, changed):
    arguments = {"expression": sp.S.One, "variable": X, "parameter": A,
                 "domain": sp.Interval(1, 2),
                 "policy": {"bound": "inf", "strict": False, "quantifier": "∀", "operator": "<="}}
    first = partition_interval_cases(**arguments)
    if changed == "expression":
        arguments[changed] = X*X + A
    elif changed in ("variable", "parameter"):
        arguments[changed] = sp.Symbol("other", real=True)
    elif changed == "domain":
        arguments[changed] = sp.Interval.open(1, 2)
    else:
        arguments["policy"][changed] = {"bound": "sup", "strict": True, "quantifier": "∃",
                                         "operator": "<", "empty": True}[changed]
    second = partition_interval_cases(**arguments)
    assert len(partition_calls) == 2
    arguments["policy"] = dict(reversed(list(arguments["policy"].items())))
    assert partition_interval_cases(**arguments) == second
    assert len(partition_calls) == 2
    if changed in ("expression", "bound"):
        assert first != second


def test_returned_partition_and_extremum_evidence_cannot_poison_cache(partition_calls):
    arguments = (X*X+A*X+2, X, A, sp.Interval.open(-sp.oo, 0), {"bound": "inf"})
    initial = partition_interval_cases(*arguments)
    expected = deepcopy(initial)
    case = deepcopy(initial["outputs"]["cases"][0])
    computed = parametric_interval_extremum(*arguments, case)
    expected_computed = deepcopy(computed)
    initial["outputs"]["cases"][0]["range"]["inf"] = sp.Integer(100)
    initial["checks"][0]["polynomials"].clear()
    computed["outputs"]["range"]["inf"] = sp.Integer(200)
    computed["checks"][0]["polynomials"].clear()
    computed["checks"][1]["cells"][0]["signs"].clear()
    case["range"]["inf"] = sp.Integer(300)
    case["cells"][0]["signs"].clear()
    with pytest.raises(LocalCheckFailed, match="parametric_case_certificate_mismatch"):
        parametric_interval_extremum(*arguments, case)
    actual = partition_interval_cases(*arguments)
    assert actual == expected
    assert parametric_interval_extremum(*arguments, actual["outputs"]["cases"][0]) == expected_computed
    assert len(partition_calls) == 1


def test_partition_failure_is_not_cached(monkeypatch, partition_calls):
    counted = parametric._partition

    def fail_once(*arguments):
        if not partition_calls:
            partition_calls.append(arguments)
            raise CapabilityGap("injected_partition_failure")
        return counted(*arguments)

    monkeypatch.setattr(parametric, "_partition", fail_once)
    arguments = (X*X+A*X+2, X, A, sp.Interval.open(-sp.oo, 0), {"bound": "inf"})
    with pytest.raises(CapabilityGap, match="injected_partition_failure"):
        partition_interval_cases(*arguments)
    recovered = partition_interval_cases(*arguments)
    assert recovered["outputs"]["cases"]
    assert partition_interval_cases(*arguments) == recovered
    assert len(partition_calls) == 2


def test_partition_cache_is_bounded_and_evicted_input_recomputes(partition_calls):
    for value in range(33):
        partition_interval_cases(sp.Integer(value), X, A, sp.Interval(1, 2), {"bound": "inf"})
    assert len(partition_calls) == 33
    partition_interval_cases(sp.S.Zero, X, A, sp.Interval(1, 2), {"bound": "inf"})
    assert len(partition_calls) == 34


def solve(expression, domain, *, quantifier="∀", operator=">=", variable=X, parameter=A):
    reversed_operator = {">": "<", ">=": "<=", "<": ">", "<=": ">="}[operator]
    policy = select_quantifier_policy(quantifier, reversed_operator, domain)["outputs"]["policy"]
    partition = partition_interval_cases(expression, variable, parameter, domain, policy)
    cases = decode_value(encode_value(partition["outputs"]["cases"]))
    records = []
    for case in cases:
        computed = parametric_interval_extremum(expression, variable, parameter, domain, policy, case)
        assert all(row["passed"] for row in computed["checks"])
        conditions = apply_quantifier_policy(policy, computed["outputs"]["range"], sp.S.Zero)["outputs"]
        solution = solve_interval_conditions(conditions["conditions"], conditions["combiner"], parameter,
                                            case["domain"])["outputs"]["solution"]
        records.append({"case_id": case["id"], "condition": case["condition"], "domain": case["domain"],
                        "outputs": {"solution": solution}, "case_path": [case["id"]] if len(cases) > 1 else [],
                        "source_refs": [f"/steps/{len(records)}/calls/0"]})
    merged = merge_interval_cases(cases, records)
    assert all(row["passed"] for row in merged["checks"])
    return merged["outputs"]["solution"], cases, records


def original(expression, domain, quantifier, operator, variable=X, parameter=A):
    def endpoint(value):
        return "-∞" if value is -sp.oo else "+∞" if value is sp.oo else sp.sstr(value)

    text_domain = ("(" if domain.left_open else "[") + endpoint(domain.start) + "," + endpoint(domain.end)
    text_domain += ")" if domain.right_open else "]"
    return problem(f"{quantifier}{variable}∈{text_domain}:{sp.sstr(expression).replace('**', '^')}{operator}0",
                   symbol=str(parameter))


def test_q06_merges_zero_into_unattained_endpoint_case():
    expected = sp.Interval(-sp.oo, 2*sp.sqrt(2))
    actual, cases, _ = solve(X*X + A*X + 2, sp.Interval.open(-sp.oo, 0))
    assert actual == expected
    assert [case["domain"] for case in cases] == [sp.Interval(-sp.oo, 0), sp.Interval.open(0, sp.oo)]
    assert [case["range"]["inf_attained"] for case in cases] == [False, True]
    assert cases[0]["range"]["inf"] == 2
    assert cases[1]["range"]["inf"] == 2 - A*A/4
    assert len(cases[0]["cells"]) == 2  # Open sign cell plus independently checked zero.
    assert cases[1]["range"]["candidates"][0]["location"] == "vertex"


def test_q07_constant_case_is_explicit_numeric_and_cannot_be_lost():
    actual, cases, records = solve(A*X*X - A*X - 1, sp.Interval(2, 3), operator="<")
    assert actual == sp.Interval.open(-sp.oo, sp.Rational(1, 6))
    assert [case["kind"] for case in cases] == ["quadratic", "constant", "quadratic"]
    constant = cases[1]
    assert constant["domain"] == sp.FiniteSet(0)
    assert constant["value"] == 0 and constant["expression"] == -1 and constant["numeric"] is True
    assert constant["range"]["sup_attained"] is True
    assert records[1]["outputs"]["solution"] == sp.FiniteSet(0)
    with pytest.raises(LocalCheckFailed, match="incomplete_case_partition"):
        merge_interval_cases([cases[0], cases[2]], [records[0], records[2]])


def test_q10_interior_critical_point_keeps_vertex_formula_and_complete_cell_evidence():
    expression, domain = X*X - 2*A*X + 3, sp.Interval(1, 2)
    actual, cases, _ = solve(expression, domain, quantifier="∃", operator="<")
    assert actual == sp.Interval.open(sp.sqrt(3), sp.oo)
    assert [case["domain"] for case in cases] == [
        sp.Interval(-sp.oo, 1), sp.Interval.open(1, 2), sp.Interval(2, sp.oo),
    ]
    assert [case["range"]["inf"] for case in cases] == [4 - 2*A, 3 - A*A, 7 - 4*A]
    assert [case["range"]["candidates"][0]["point"] for case in cases] == [1, A, 2]
    middle = cases[1]
    assert [cell["domain"] for cell in middle["cells"]] == [
        sp.Interval.open(1, sp.Rational(3, 2)), sp.FiniteSet(sp.Rational(3, 2)),
        sp.Interval.open(sp.Rational(3, 2), 2),
    ]
    assert middle["cells"][1]["range"]["inf"] == sp.Rational(3, 4)
    assert sum(len(case["cells"]) for case in cases) == 9
    for case in cases:
        assert sp.Union(*(cell["domain"] for cell in case["cells"])) == case["domain"]
        for cell in case["cells"]:
            assert cell["signs"] and cell["candidates"]
            assert sp.simplify((case["range"]["inf"] - cell["range"]["inf"]).subs(A, cell["sample"])) == 0
    assert check(original(expression, domain, "∃", "<"), actual)["status"] == "verified"


def test_open_endpoint_cases_do_not_absorb_attained_vertex_cases():
    cases = partition_interval_cases(X*X - 2*A*X + 3, X, A, sp.Interval.open(1, 2),
                                     {"bound": "inf"})["outputs"]["cases"]
    assert [case["domain"] for case in cases] == [
        sp.Interval(-sp.oo, 1), sp.Interval.open(1, 2), sp.Interval(2, sp.oo),
    ]
    assert [case["range"]["inf_attained"] for case in cases] == [False, True, False]


def test_equal_endpoint_values_at_critical_parameter_do_not_merge_different_locations():
    cases = partition_interval_cases(-X*X + 2*A*X, X, A, sp.Interval(0, 2),
                                     {"bound": "inf"})["outputs"]["cases"]
    assert [case["domain"] for case in cases] == [sp.Interval.open(-sp.oo, 1), sp.Interval(1, sp.oo)]
    assert [case["range"]["candidates"][0]["location"] for case in cases] == ["right_endpoint", "left_endpoint"]


def _bound_case(domain, value, point=A):
    return {"domain": domain, "kind": "quadratic", "range": {
        "bound": "inf", "inf": value, "inf_attained": True,
        "candidates": [{"value": value, "point": point, "location": "vertex", "attained": True}],
    }}


def test_singleton_agreement_does_not_bridge_distinct_open_cell_formulas():
    left = _bound_case(sp.Interval.open(-sp.oo, 0), A)
    singleton = _bound_case(sp.FiniteSet(0), sp.S.Zero, sp.S.Zero)
    right = _bound_case(sp.Interval.open(0, sp.oo), 2*A)
    assert _same_bound(left, singleton, A) and _same_bound(singleton, right, A)
    # Once joined, this is a non-singleton group and requires global equality.
    left["domain"] = sp.Interval(-sp.oo, 0)
    assert not _same_bound(left, right, A)


@pytest.mark.parametrize("formula", [1/A, sp.Mul(A, sp.Pow(A, -1, evaluate=False), evaluate=False)])
def test_undefined_specialization_cannot_merge_a_singleton(formula):
    open_cell = _bound_case(sp.Interval.open(0, sp.oo), formula)
    singleton = _bound_case(sp.FiniteSet(0), sp.S.One, sp.S.Zero)
    assert not _same_bound(singleton, open_cell, A)


@pytest.mark.parametrize("field", ["kind", "attainment", "point", "bound"])
def test_singleton_merge_rejects_changed_extremum_certificate(field):
    left = _bound_case(sp.Interval.open(-sp.oo, 0), A)
    singleton = _bound_case(sp.FiniteSet(0), sp.S.Zero, sp.S.Zero)
    if field == "kind":
        singleton["kind"] = "constant"
    elif field == "attainment":
        singleton["range"]["inf_attained"] = False
    elif field == "point":
        singleton["range"]["candidates"][0]["point"] = sp.S.One
    else:
        singleton["range"]["inf"] = sp.S.One
    assert not _same_bound(left, singleton, A)


@pytest.mark.parametrize("expression,domain,quantifier,operator,expected", [
    (X*X+A*X+8, sp.Interval.open(-sp.oo, 0), "∀", ">=", sp.Interval(-sp.oo, 4*sp.sqrt(2))),
    (X*X+A*X+2, sp.Interval(-sp.oo, -2), "∀", ">=", sp.Interval(-sp.oo, 3)),
    (X*X+A*X+2, sp.Interval.open(-sp.oo, 0), "∀", ">", sp.Interval.open(-sp.oo, 2*sp.sqrt(2))),
    (X*X+A*X+2, sp.Interval.open(-sp.oo, 0), "∃", ">=", sp.S.Reals),
    (A*X*X-A*X-1, sp.Interval(2, 4), "∀", "<", sp.Interval.open(-sp.oo, sp.Rational(1, 12))),
    (A*X*X-A*X-2, sp.Interval(2, 3), "∀", "<", sp.Interval.open(-sp.oo, sp.Rational(1, 3))),
    (A*X*X-A*X-1, sp.Interval(2, 3), "∀", "<=", sp.Interval(-sp.oo, sp.Rational(1, 6))),
    (A*X*X-A*X-1, sp.Interval(2, 3), "∃", "<", sp.Interval.open(-sp.oo, sp.Rational(1, 2))),
    (A*X*X-A*X-1, sp.Interval.open(2, 3), "∀", "<", sp.Interval(-sp.oo, sp.Rational(1, 6))),
    (-A*X*X+A*X+1, sp.Interval.open(2, 3), "∀", ">", sp.Interval(-sp.oo, sp.Rational(1, 6))),
    (X*X+A*X+1, sp.S.Reals, "∀", ">=", sp.Interval(-2, 2)),
    (A*X*X+1, sp.Interval(0, 1), "∀", ">=", sp.Interval(-1, sp.oo)),
    (A*X*X+X, sp.Interval.open(0, 1), "∀", ">", sp.Interval(-1, sp.oo)),
    (A*X*X+X, sp.Interval.open(0, 1), "∃", ">=", sp.S.Reals),
])
def test_parameter_and_domain_variations_are_verified_from_the_original(expression, domain, quantifier,
                                                                      operator, expected):
    actual, _, _ = solve(expression, domain, quantifier=quantifier, operator=operator)
    assert actual == expected
    verified = check(original(expression, domain, quantifier, operator), actual)
    assert verified["status"] == "verified", verified


@pytest.mark.parametrize("bound", ["inf", "sup"])
@pytest.mark.parametrize("domain", [sp.Interval(-2, 3), sp.Interval.Lopen(-2, 3),
                                    sp.Interval.open(-sp.oo, 0), sp.Interval.open(1, sp.oo)])
def test_parameter_axis_and_opening_partitions_are_complete(bound, domain):
    expression = (A*A-2)*X*X + (A+1)*X + 2
    operator = ">=" if bound == "inf" else "<="
    solution, cases, _ = solve(expression, domain, operator=operator)
    assert sp.Union(*(case["domain"] for case in cases)) == sp.S.Reals
    assert any(case["kind"] == "linear" for case in cases)
    for case in cases:
        assert all(record["complete"] for record in case["critical_polynomials"])
        assert all(cell["signs"] for cell in case["cells"])
    verified = check(original(expression, domain, "∀", operator), solution)
    assert verified["status"] == "verified", verified


def test_variable_names_and_rational_coefficients_are_not_hard_coded():
    variable, parameter = sp.symbols("t p", real=True)
    expression = variable*variable/2 + parameter*variable + 4
    actual, _, _ = solve(expression, sp.Interval.open(-sp.oo, 0), variable=variable, parameter=parameter)
    assert actual == sp.Interval(-sp.oo, 2*sp.sqrt(2))
    assert check(original(expression, sp.Interval.open(-sp.oo, 0), "∀", ">=", variable, parameter), actual)["status"] == "verified"


@pytest.mark.parametrize("condition,expected", [
    (sp.Ge((A-1)/(A+1), 0), sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval(1, sp.oo))),
    (sp.Lt((A-1)/(A+1), 0), sp.Interval.open(-1, 1)),
    (sp.Le((A-1)**2/(A+1), 0), sp.Union(sp.Interval.open(-sp.oo, -1), sp.FiniteSet(1))),
    (sp.Eq((A-1)/(A+1), 0), sp.FiniteSet(1)),
    (sp.Ne((A-1)/(A+1), 0), sp.S.Reals-sp.FiniteSet(-1, 1)),
    (sp.And(A > -1, A <= sp.sqrt(2)), sp.Interval.Lopen(-1, sp.sqrt(2))),
    (sp.Contains(A, sp.Interval.Ropen(0, 2), evaluate=False), sp.Interval.Ropen(0, 2)),
])
def test_fractional_and_composite_conditions_exclude_poles_and_respect_case_domain(condition, expected):
    result = solve_interval_conditions([condition], "all", A, sp.S.Reals)
    assert result["outputs"]["solution"] == expected
    restricted = solve_interval_conditions([condition], "all", A, sp.Interval(-2, 0))
    assert restricted["outputs"]["solution"] == expected.intersect(sp.Interval(-2, 0))


def test_union_of_conditions_is_intersected_with_the_current_case():
    actual = solve_interval_conditions([A < -1, A > 1], "any", A, sp.Interval(0, 2))
    assert actual["outputs"]["solution"] == sp.Interval.Lopen(1, 2)


def test_membership_case_conditions_are_accepted_by_the_union_check():
    expected, cases, records = solve(X*X+A*X+2, sp.Interval.open(-sp.oo, 0))
    for case, record in zip(cases, records, strict=True):
        case["condition"] = sp.Contains(A, case["domain"], evaluate=False)
        record["condition"] = case["condition"]
    assert merge_interval_cases(cases, records)["outputs"]["solution"] == expected


def test_cancelled_fraction_factor_is_still_excluded_from_parameter_conditions():
    expression = sp.Mul(A*A-1, sp.Pow(A-1, -1, evaluate=False), evaluate=False)
    condition = sp.Ge(expression, 0, evaluate=False)
    actual = solve_interval_conditions([condition], "all", A, sp.S.Reals)["outputs"]["solution"]
    assert actual == sp.Interval(-1, sp.oo) - sp.FiniteSet(1)


@pytest.mark.parametrize("mutation", ["domain", "range", "sign", "condition", "id"])
def test_execution_rejects_a_modified_case_certificate(mutation):
    expression, domain, policy = X*X+A*X+2, sp.Interval.open(-sp.oo, 0), {"bound": "inf"}
    case = deepcopy(partition_interval_cases(expression, X, A, domain, policy)["outputs"]["cases"][0])
    if mutation == "domain":
        case["domain"] = sp.S.Reals
    elif mutation == "range":
        case["range"]["inf"] = 100
    elif mutation == "sign":
        case["cells"][0]["signs"]["leading"] = -1
    elif mutation == "condition":
        case["condition"] = sp.true
    else:
        case["id"] = "invented"
    with pytest.raises(LocalCheckFailed, match="parametric_case_certificate_mismatch"):
        parametric_interval_extremum(expression, X, A, domain, policy, case)


@pytest.mark.parametrize("mutation", ["source", "path", "outside", "condition", "overlap"])
def test_merge_rejects_missing_provenance_and_invalid_partitions(mutation):
    _, cases, records = solve(A*X*X-A*X-1, sp.Interval(2, 3), operator="<")
    if mutation == "source":
        records[0]["source_refs"] = []
    elif mutation == "path":
        records[0]["case_path"] = []
    elif mutation == "outside":
        records[0]["outputs"]["solution"] = sp.S.Reals
    elif mutation == "condition":
        records[0]["condition"] = sp.true
    else:
        cases[0]["domain"] = sp.Interval(-sp.oo, 0)
        cases[0]["condition"] = A <= 0
        records[0].update(domain=cases[0]["domain"], condition=cases[0]["condition"])
    with pytest.raises(LocalCheckFailed):
        merge_interval_cases(cases, records)


@pytest.mark.parametrize('path', [[], ['parent']])
def test_single_uncased_endpoint_route_can_merge_without_a_case_path(path):
    cases = [{"id": "uncased", "kind": "nondegenerate", "mode": "endpoint",
              "domain": sp.S.Reals, "condition": sp.true}]
    records = [{"case_id": "uncased", "condition": sp.true, "domain": sp.S.Reals,
                "case_path": path, "source_refs": ["/steps/1/calls/0"],
                "outputs": {"solution": sp.Interval.open(-sp.oo, -5)}}]
    assert merge_interval_cases(cases, records)["outputs"]["solution"] == sp.Interval.open(-sp.oo, -5)


@pytest.mark.parametrize("expression,domain,code", [
    (X*X+A*X+1, sp.Interval(0, sp.sqrt(2)), "rational_interval_endpoints"),
    (X*X+X/A+1, sp.Interval(0, 1), "rational_parameter_polynomial"),
    ((A**3-A-1)*X*X+1, sp.Interval(0, 1), "parameter_root_checkpoint"),
    (X**3+A, sp.Interval(0, 1), "polynomial_degree"),
])
def test_unsupported_categories_report_capability_gaps(expression, domain, code):
    with pytest.raises(CapabilityGap, match=code):
        partition_interval_cases(expression, X, A, domain, {"bound": "inf"})
