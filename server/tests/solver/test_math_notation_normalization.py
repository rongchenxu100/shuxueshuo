"""Synthetic equivalence families and counterexamples, independent of exam IDs."""

import json
from copy import deepcopy
from itertools import product

import pytest

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_normalization import (
    normalize_bound,
)
from shuxueshuo_server.problem_understanding.notation_semantics import compare

pytestmark = pytest.mark.generated_gate


def candidate(facts=(), **scope):
    return {
        "root": {"facts": list(facts), **scope},
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "synthetic",
    }


def equivalent(left, right):
    original = deepcopy((left, right))
    result = compare(left, right)
    assert result["ok"], result
    assert compare(right, left)["ok"]
    assert (left, right) == original


@pytest.mark.parametrize(
    "point,symbol,offset,reverse",
    product(("P", "T"), ("v", "y_M"), (1, 3), (False, True)),
)
def test_coordinate_alias_family(point, symbol, offset, reverse):
    common = ["Γ: y=x^2+b", f"{point} ∈ Γ"]
    expected = candidate([*common, f"x({point})=b+{offset}"])
    facts = [*common, f"{point}=(b+{offset},{symbol})"]
    actual = candidate(list(reversed(facts)) if reverse else facts)
    equivalent(expected, actual)
    report = NotationValidator().validate(actual)
    assert any(x["name"] == symbol for x in report.objects)
    assert any(
        x["symbol_ref"].endswith(":" + symbol)
        for x in report.semantic_normalization["coordinate_bindings"]
    )


@pytest.mark.parametrize("use", ["constraint", "goal", "range", "in_terms_of", "child"])
def test_coordinate_alias_keeps_every_use(use):
    expected = candidate(["P∈x_axis", "x(P)=2"])
    actual = candidate(["P∈x_axis", "P=(2,t)"])
    if use == "constraint":
        expected["root"]["facts"].append("y(P)>0")
        actual["root"]["facts"].append("t>0")
    elif use in ("goal", "range"):
        kind, field = (
            ("find_value", "expression") if use == "goal" else ("find_range", "symbol")
        )
        expected["root"]["goals"] = [{"kind": kind, field: "y(P)"}]
        actual["root"]["goals"] = [{"kind": kind, field: "t"}]
    elif use == "child":
        expected["root"]["children"] = [{"facts": ["y(P)>0"]}]
        actual["root"]["children"] = [{"facts": ["t>0"]}]
    else:
        # An answer-form parameter is still a real dependency after aliasing.
        actual["root"]["goals"] = [
            {"kind": "find_value", "expression": "2", "in_terms_of": ["t"]}
        ]
        expected["root"]["goals"] = [{"kind": "find_value", "expression": "2"}]
        assert not compare(expected, actual)["ok"]
        return
    equivalent(expected, actual)
    without_use = candidate(["P∈x_axis", "x(P)=2"])
    assert not compare(without_use, actual)["ok"]


def test_coordinate_shared_variable_retains_equality_between_points():
    left = candidate(["P=(1,t)", "Q=(2,t)"])
    right = candidate(["P=(1,u)", "Q=(2,v)", "u=v"])
    equivalent(left, right)
    assert not compare(left, candidate(["P=(1,u)", "Q=(2,v)"]))["ok"]


def test_coordinate_bindings_do_not_escape_branch_or_sibling():
    expected = candidate(
        children=[{"facts": ["P∈x_axis", "x(P)=1"]}, {"facts": ["t>0"]}]
    )
    actual = candidate(
        children=[{"facts": ["P∈x_axis", "P=(1,t)"]}, {"facts": ["t>0"]}]
    )
    equivalent(expected, actual)
    branch = candidate(["P∈x_axis", "(P=(1,t)) ∨ (P=(2,t))", "t>0"])
    report = NotationValidator().validate(branch)
    assert report.ok and not report.semantic_normalization["coordinate_bindings"]
    assert not compare(branch, candidate(["P∈x_axis", "(x(P)=1) ∨ (x(P)=2)"]))["ok"]


@pytest.mark.parametrize(
    "shape,vertices,reverse,in_child",
    product(
        ("square", "parallelogram"), ("ABCD", "PQRS"), (False, True), (False, True)
    ),
)
def test_diagonal_intersection_family(shape, vertices, reverse, in_child):
    a, b, c, d = vertices
    first, second = (c, a) if reverse else (a, c), (d, b) if reverse else (b, d)
    known = f"{shape}({a},{b},{c},{d})"
    lhs = f"H ∈ segment({a},{c}) ∩ segment({b},{d})"
    rhs = f"line({second[0]},{second[1]}) ∩ line({first[0]},{first[1]}) = {{H}}"
    if in_child:
        left, right = (
            candidate([known], children=[{"facts": [lhs]}]),
            candidate([known], children=[{"facts": [rhs]}]),
        )
    else:
        left, right = candidate([known, lhs]), candidate([rhs, known])
    equivalent(left, right)


@pytest.mark.parametrize(
    "coefficient,premise,should_match",
    [
        ("-2", None, True),
        ("a", "a>0", True),
        ("a", "a<0", True),
        ("a", "a!=0", True),
        ("a", None, False),
        ("a", "a>=0", False),
        ("0", None, False),
    ],
)
def test_axis_unique_requires_nonzero_quadratic_coefficient(
    coefficient, premise, should_match
):
    facts = [f"Γ: y={coefficient}*x^2+b*x+c"] + ([premise] if premise else [])
    a = candidate([*facts, "P ∈ axis(Γ) ∩ x_axis"])
    b = candidate([*facts, "x_axis ∩ axis(Γ) = {P}"])
    assert compare(a, b)["ok"] == should_match


def test_shape_premise_in_or_or_sibling_is_not_unconditional():
    left = "H ∈ segment(A,C) ∩ segment(B,D)"
    right = "line(A,C) ∩ line(B,D) = {H}"
    for known in ["quadrilateral(A,B,C,D)", "square(A,B,C,D) ∨ parallelogram(A,B,C,D)"]:
        assert not compare(candidate([known, left]), candidate([known, right]))["ok"]
    a = candidate(
        children=[
            {"facts": ["square(A,B,C,D)"]},
            {"facts": ["quadrilateral(A,B,C,D)", left]},
        ]
    )
    b = deepcopy(a)
    b["root"]["children"][1]["facts"][-1] = right
    assert not compare(a, b)["ok"]


@pytest.mark.parametrize(
    "mutation", ["side", "ray", "wrong_point", "wrong_polygon_order"]
)
def test_intersection_rule_does_not_hide_geometry_changes(mutation):
    a = candidate(["square(A,B,C,D)", "H ∈ segment(A,C) ∩ segment(B,D)"])
    b = deepcopy(a)
    if mutation == "side":
        b["root"]["facts"][-1] = "line(A,B) ∩ line(B,D) = {H}"
    elif mutation == "ray":
        b["root"]["facts"][-1] = "ray(A,C) ∩ line(B,D) = {H}"
    elif mutation == "wrong_point":
        b["root"]["facts"][-1] = "line(A,C) ∩ line(B,D) = {A}"
    else:
        b["root"]["facts"][0] = "square(A,C,B,D)"
    assert not compare(a, b)["ok"]


@pytest.mark.parametrize(
    "last_point,should_match",
    [("D=(3,5)", True), ("D=(3,2)", False), ("D=(3,1)", False)],
)
def test_numeric_intersection_checks_segment_bounds_and_parallel_lines(
    last_point, should_match
):
    base = ["A=(1,3)", "B=(5,3)", "C=(3,1)", last_point]
    a = candidate([*base, "P ∈ segment(A,B) ∩ segment(C,D)"])
    b = candidate([*base, "line(A,B) ∩ line(C,D) = {P}"])
    assert compare(a, b)["ok"] == should_match


def test_set_membership_redundancy_is_directional_and_scoped():
    a = candidate(["Γ: y=x^2-1", "Γ ∩ x_axis = {A,B}"])
    b = deepcopy(a)
    b["root"]["facts"] += ["A∈Γ", "B∈x_axis"]
    equivalent(a, b)
    extra = deepcopy(a)
    extra["root"]["facts"].append("A∈y_axis")
    assert not compare(a, extra)["ok"]
    weaker = candidate(["Γ: y=x^2-1", "A∈Γ", "B∈Γ", "A∈x_axis", "B∈x_axis"])
    assert not compare(a, weaker)["ok"]
    or_premise = candidate(
        ["Γ: y=x^2-1", "(Γ ∩ x_axis = {A,B}) ∨ (Γ ∩ y_axis = {A,B})"]
    )
    added = deepcopy(or_premise)
    added["root"]["facts"].append("A∈x_axis")
    assert not compare(or_premise, added)["ok"]


def test_normalization_is_idempotent_auditable_and_preserves_at():
    payload = candidate(
        ["square(A,B,C,D)", "line(A,C)∩line(B,D)={H}", "P=(2,t)", "t>0"],
        goals=[{"kind": "find_coordinates", "object": "P", "at": "y(P)=min(y(P))"}],
    )
    report = NotationValidator().validate(payload)
    assert report.ok, report.issues
    first = report.semantic_normalization
    second = normalize_bound(first["root"], first["objects"])
    assert first["root"] == second["root"]
    assert any(
        p["rule"] == "nondegenerate_parallelogram_diagonals" and p["premises"]
        for p in first["proofs"]
    )
    assert report.payload()["coordinate_bindings"]
    altered = deepcopy(payload)
    altered["root"]["goals"][0].pop("at")
    assert not compare(payload, altered)["ok"]


def test_normalization_budget_exhaustion_fails_closed(monkeypatch):
    from shuxueshuo_server.problem_understanding import notation_normalization

    class EmptyBudget:
        def use(self):
            raise ValueError("equivalence.proof_budget")

    monkeypatch.setattr(notation_normalization, "ProofBudget", EmptyBudget)
    report = NotationValidator().validate(candidate(["P=(1,t)"]))
    assert not report.ok
    assert "equivalence.proof_budget" in json.dumps(report.issues)


def test_normalization_composes_with_consistent_object_renaming():
    equivalent(
        candidate(["Γ: y=x^2+b", "P∈Γ", "x(P)=b+1"]),
        candidate(["Δ: y=x^2+c", "T=(1+c,u)", "T∈Δ"]),
    )
    equivalent(
        candidate(["square(A,B,C,D)", "H∈segment(A,C)∩segment(B,D)"]),
        candidate(["square(P,Q,R,S)", "line(S,Q)∩line(R,P)={T}"]),
    )
