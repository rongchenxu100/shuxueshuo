"""Geometry premises and algebraic implication gates independent of exam names."""

import json
from copy import deepcopy
from itertools import product
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_implication import (
    equivalent as prove,
)
from shuxueshuo_server.problem_understanding.notation_normalization import (
    normalize_bound,
)
from shuxueshuo_server.problem_understanding.notation_semantics import (
    Canonical,
    canonical,
    compare,
)
from shuxueshuo_server.problem_understanding.proof_budget import ProofBudget

FIXTURES = Path(__file__).parent / "fixtures/math-notation-v1"


def candidate(facts=(), **fields):
    return {
        "root": {"facts": list(facts), **fields},
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "synthetic",
    }


def equivalent(a, b):
    original = deepcopy((a, b))
    assert compare(a, b)["ok"], compare(a, b)
    assert compare(b, a)["ok"], compare(b, a)
    assert (a, b) == original


@pytest.mark.parametrize(
    "shape,first,second",
    product(("quadrilateral", "parallelogram", "square"), ("AC", "CA"), ("BD", "DB")),
)
def test_unit_cut_ratio_is_bisection_only_with_certified_diagonals(
    shape, first, second
):
    base = [f"{shape}(A,B,C,D)"]
    equivalent(
        candidate([*base, f"cut_ratio({first},{second})=1"]),
        candidate([*base, "bisects(BD,AC)"]),
    )


def test_positive_ratio_reversal_and_aliases():
    equivalent(
        candidate(["quadrilateral(A,B,C,D)", "cut_ratio(AC,BD)=2"]),
        candidate(["quadrilateral(P,Q,R,S)", "cut_ratio(RP,SQ)=1/2"]),
    )
    assert not compare(
        candidate(["quadrilateral(A,B,C,D)", "cut_ratio(AC,BD)=2"]),
        candidate(["quadrilateral(A,B,C,D)", "cut_ratio(CA,BD)=2"]),
    )["ok"]


@pytest.mark.parametrize(
    "premises",
    [
        [],
        ["segment(A,B)"],
        ["quadrilateral(A,B,A,D)"],
        ["quadrilateral(A,C,B,D)"],
        ["quadrilateral(A,B,C,D) ∨ quadrilateral(A,C,B,D)"],
    ],
)
def test_uncertified_geometry_does_not_gain_ratio_equivalence(premises):
    assert not compare(
        candidate([*premises, "cut_ratio(AC,BD)=1"]),
        candidate([*premises, "bisects(BD,AC)"]),
    )["ok"]


def affine_facts():
    return ["parallelogram(A,B,C,D)", "O∈segment(A,C)∩segment(B,D)", "E=midpoint(O,B)"]


@pytest.mark.parametrize("vertices", ["A,E,C,D", "E,C,D,A", "D,C,E,A"])
def test_affine_construction_proves_redundant_ordered_quadrilateral(vertices):
    base = candidate(affine_facts())
    redundant = candidate([*affine_facts(), f"quadrilateral({vertices})"])
    equivalent(base, redundant)
    report = NotationValidator().validate(redundant)
    proof = next(
        p
        for p in report.semantic_normalization["proofs"]
        if p["rule"] == "affine_convex_quadrilateral"
    )
    assert len(proof["premises"]) == 3
    assert any(f[:2] == ["call", "quadrilateral"] for f in report.semantic["facts"])
    normalized = report.semantic_normalization
    assert (
        normalize_bound(normalized["root"], normalized["objects"])["root"]
        == normalized["root"]
    )


@pytest.mark.parametrize(
    "facts,vertices",
    [
        (affine_facts(), "A,C,E,D"),  # Crossing vertex order.
        (affine_facts(), "A,B,C,E"),  # Concave: our convex certificate is insufficient.
        (affine_facts(), "A,E,E,D"),
        ([*affine_facts()[:2], "E=midpoint(A,C)"], "A,E,C,D"),
        (["segment(A,B)", *affine_facts()[1:]], "A,E,C,D"),
        ([affine_facts()[0], "O∈ray(A,C)", affine_facts()[2]], "A,E,C,D"),
        (
            [affine_facts()[0], "O∈segment(A,B)∩segment(C,D)", affine_facts()[2]],
            "A,E,C,D",
        ),
    ],
)
def test_unproven_or_degenerate_quadrilateral_is_not_erased(facts, vertices):
    assert not compare(
        candidate(facts), candidate([*facts, f"quadrilateral({vertices})"])
    )["ok"]


def branches(k):
    return (
        f"(cut_ratio(AC,BD)=1 ∧ (cut_ratio(BD,AC)={k} ∨ cut_ratio(BD,AC)=1/({k})))"
        f" ∨ (cut_ratio(BD,AC)=1 ∧ (cut_ratio(AC,BD)={k} ∨ cut_ratio(AC,BD)=1/({k})))"
    )


@pytest.mark.parametrize("k", ["k", "2", "3"])
def test_full_definition_and_explicit_bisection_prove_specialized_relation(k):
    base = ["quadrilateral(A,B,C,D)", "k≥1"] if k == "k" else ["quadrilateral(A,B,C,D)"]
    a = candidate(
        [*base, "bisects(BD,AC)", f"cut_ratio(BD,AC)={k} ∨ cut_ratio(BD,AC)=1/({k})"]
    )
    b = candidate([*base, "cut_ratio(AC,BD)=1", branches(k)])
    equivalent(a, b)
    result = compare(a, b)
    assert result["proofs"][0]["rule"] == "bounded_dnf_linear_implication"
    b["root"]["facts"].remove("cut_ratio(AC,BD)=1")
    assert not compare(a, b)["ok"]


def test_implication_preserves_inequalities_branches_domains_and_goals():
    base = candidate(
        [
            "quadrilateral(A,B,C,D)",
            "k≥1",
            "bisects(BD,AC)",
            "cut_ratio(BD,AC)=k ∨ cut_ratio(BD,AC)=1/k",
        ]
    )
    for old, new in [
        ("k≥1", "k>1"),
        ("cut_ratio(BD,AC)=k ∨ cut_ratio(BD,AC)=1/k", "cut_ratio(BD,AC)=k"),
    ]:
        changed = deepcopy(base)
        changed["root"]["facts"] = [
            new if f == old else f for f in changed["root"]["facts"]
        ]
        assert not compare(base, changed)["ok"]
    a = candidate(["k=1"])
    assert not compare(a, candidate(["k/k=1", "k=1"]))[
        "ok"
    ]  # Domain obligations cannot disappear.
    changed = deepcopy(base)
    changed["root"]["goals"] = [{"kind": "find_value", "expression": "k", "at": "k=1"}]
    assert not compare(base, changed)["ok"]


def test_certificates_inherit_parent_but_never_sibling_or_disjunction():
    a = candidate(["quadrilateral(A,B,C,D)"], children=[{"facts": ["bisects(BD,AC)"]}])
    b = deepcopy(a)
    b["root"]["children"][0]["facts"] = ["cut_ratio(AC,BD)=1"]
    equivalent(a, b)
    a = candidate(
        children=[{"facts": ["quadrilateral(A,B,C,D)"]}, {"facts": ["bisects(BD,AC)"]}]
    )
    b = deepcopy(a)
    b["root"]["children"][1]["facts"] = ["cut_ratio(AC,BD)=1"]
    assert not compare(a, b)["ok"]


def test_proof_budget_fails_closed():
    a, b = candidate(["u=1", "v=u"]), candidate(["u=1", "v=1"])
    ca, cb = Canonical(), Canonical()
    left = canonical(NotationValidator().validate(a), compiler=ca)
    right = canonical(NotationValidator().validate(b), compiler=cb)
    budget = ProofBudget()
    budget.remaining = 0
    assert prove(left, right, {**ca.algebra, **cb.algebra}, budget) is None


def test_recorded_k_math_proof_does_not_cover_structure_or_missing_figures():
    gold = json.loads((FIXTURES / "k-quad.json").read_text())
    actual = json.loads((FIXTURES / "recorded-20260916-135634/k-quad.txt").read_text())
    assert not compare(gold, actual)["ok"]
    diagnostic = deepcopy(actual)
    children = diagnostic["root"]["children"]
    diagnostic["root"]["children"] = [
        {"label": "(1)", "children": children[:2]},
        *children[2:],
    ]
    remaining = compare(gold, diagnostic)
    assert not remaining["ok"]
    assert len(remaining["differences"]) == 4
    assert all(d["path"].endswith("/uncertainties") for d in remaining["differences"])
    # Only in this explicitly modified diagnostic copy: restore the four flags.
    for target, expected in zip(
        [
            *diagnostic["root"]["children"][0]["children"],
            *diagnostic["root"]["children"][1:],
        ],
        [*gold["root"]["children"][0]["children"], *gold["root"]["children"][1:]],
    ):
        target["uncertainties"] = expected["uncertainties"]
    equivalent(gold, diagnostic)
