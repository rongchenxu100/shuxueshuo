"""Stage 3: proof certificates are conditional evidence, not Runtime facts."""

import json
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.solver.math_kernel.expression_parser import (
    parse_math_expression,
    parse_math_relation,
    parse_math_steps,
)
from shuxueshuo_server.solver.math_kernel.proof_algebra import (
    Arithmetic,
    ProofFailure,
    from_node,
)
from shuxueshuo_server.solver.math_kernel.proof_kernel import (
    ProofContext,
    ProofLimits,
    Witness,
    _Budget,
    _replay,
    _Search,
    prove_domain,
    prove_relation,
    replay_proof,
    verify_witnesses,
)

SYMBOLS = {name: sp.Symbol(name, real=True) for name in ("x", "y", "a", "b")}
FIXTURES = Path(__file__).parent / "fixtures/basic-inequality-problem-ir/v1"


def relation(text, symbols=SYMBOLS):
    return parse_math_relation(text, symbols)


def scalar(text, symbols=SYMBOLS):
    return parse_math_expression(text, symbols)


def context(*premises, limits=None, symbols=SYMBOLS):
    return ProofContext(
        symbols,
        {
            f"given_{i}": replace(relation(p, symbols), source_path=f"/given/{i}")
            for i, p in enumerate(premises)
        },
        limits or ProofLimits(),
    )


def check(text, ctx, expected=True):
    result = prove_relation(relation(text, ctx.symbols), ctx)
    assert result.status == ("proved" if expected else "not_proved"), (
        result.to_payload()
    )
    if expected:
        replay = replay_proof(json.loads(json.dumps(result.proof)), ctx)
        assert replay.status == "proved", replay.to_payload()
    return result


@pytest.mark.parametrize("candidate", ["x>-1", "-x<1"])
def test_relation_transport_certifies_substitution_and_direction(candidate):
    ctx = context("x+y>0", "y=1")
    result = check(candidate, ctx)
    nodes = [
        n for n in result.proof["nodes"] if n["rule_id"] == "math.relation_transport"
    ]
    assert nodes
    changed = deepcopy(result.proof)
    node = next(
        n for n in changed["nodes"] if n["rule_id"] == "math.relation_transport"
    )
    node["certificate"]["ratio"] = "-7"
    assert replay_proof(changed, ctx).status == "not_proved"
    check(candidate, context("x+y>0"), False)


def test_squared_amgm_rule_replays_its_positive_term_dependencies():
    ctx = context("x>0", "y>0", "x+y>=2*sqrt(x*y)")
    result = check("x*y<=(x+y)^2/4", ctx)
    changed = deepcopy(result.proof)
    node = next(
        n for n in changed["nodes"] if n["rule_id"] == "math.amgm_squared_bound"
    )
    node["children"].pop()
    assert replay_proof(changed, ctx).status == "not_proved"
    check("x*y<=(x+y)^2/4-1", ctx, False)


@pytest.mark.parametrize(
    ("facts", "goal"),
    [
        (("x!=0",), "x/x=1"),
        (("x=2",), "x^2=4"),
        (("x+y=3", "x-y=1"), "x=2"),
        (("x*y=1", "x>0", "y>0"), "1/x+1/y=x+y"),
        (("x>0", "y>0"), "x*y>0"),
        (("x<0", "y<0"), "x*y>0"),
        (("x>0", "y<0"), "x/y<0"),
        (("x>=0", "y>0"), "x+y>0"),
        (("x>0",), "x>=0"),
        (("x<0",), "x!=0"),
        ((), "x^2>=0"),
        (("x!=0",), "x^2>0"),
        (("x!=0",), "x^-2>0"),
        (("x<0",), "x^3<0"),
        (("x*y>0",), "x!=0"),
        (("x*y=2",), "y!=0"),
        (("a>b",), "a+x>b+x"),
        (("a>b", "x>0"), "a*x>b*x"),
        (("a>b", "x<0"), "a*x<b*x"),
        (("a>b", "x<0"), "a/x<b/x"),
        (("x>=0",), "sqrt(x^2)=x"),
        (("x<=0",), "sqrt(x^2)=-x"),
        (("x>=0",), "sqrt(x)^2=x"),
        (("x>=y", "y>=0"), "sqrt(x)>=sqrt(y)"),
        (("x>y", "y>0"), "1/x<1/y"),
        (("x>=-2", "x<=2"), "(4-x^2)/3>=0"),
        (("x>=0", "x<=2"), "(x-1)^2>=0"),
        (("x>=-2", "x<=2"), "x+2>=0"),
    ],
)
def test_registered_proof_rules(facts, goal):
    check(goal, context(*facts))


@pytest.mark.parametrize(
    ("facts", "goal"),
    [
        ((), "x/x=1"),
        ((), "sqrt(x^2)=x"),
        (("x<=0",), "sqrt(x^2)=x"),
        (("x*y>0",), "x>0"),
        (("a>b",), "a*x>b*x"),
        (("x>=0",), "x>0"),
        (("x=2",), "x^2=5"),
        (("x>=-1", "x<=1"), "x!=0"),
        (("x>0",), "sqrt(y)>=0"),
        (("x/x=1",), "x!=0"),
        (("x=y", "y=x"), "x>0"),
    ],
)
def test_insufficient_evidence_fails_closed(facts, goal):
    result = check(goal, context(*facts), False)
    assert result.code == "proof_missing", result.to_payload()


@pytest.mark.parametrize(
    "source",
    [
        "2*sqrt(3)-3>0",
        "sqrt(2)<sqrt(3)",
        "sqrt(sqrt(3)-1)>0",
        "sqrt(2)*sqrt(2)=2",
        "(sqrt(2)+1)*(sqrt(2)-1)=1",
        "1/3+1/6=1/2",
    ],
)
def test_exact_constants(source):
    result = check(source, context())
    constant = [n for n in result.proof["nodes"] if n["rule_id"] == "math.constant"]
    assert constant
    for node in constant:
        assert set(node["certificate"]) == {
            "polynomial",
            "bits",
            "interval",
            "root_index",
        }


def test_no_external_positive_assumption_is_used():
    symbols = {"x": sp.Symbol("x", positive=True)}
    check("x>0", context(symbols=symbols), False)
    check("sqrt(x^2)=x", context(symbols=symbols), False)
    check("x>0", context("x>0", symbols=symbols))


def test_domain_proof_is_a_conjunction_and_does_not_modify_parser_obligations():
    expression = scalar("x/x+sqrt(y)+x^-2")
    before = expression.obligations
    c = context("x!=0", "y>=0")
    result = prove_domain(expression, c)
    assert result.status == "proved", result.to_payload()
    assert replay_proof(result, c).status == "proved"
    assert expression.obligations == before
    assert all(o.status == "unverified" for o in before)
    assert prove_domain(expression, context("x!=0")).code == "proof_missing"


@pytest.mark.parametrize(
    "facts",
    [("x>0", "x<=0"), ("x=0", "x!=0"), ("x>=2", "x<1"), ("x=1", "x=2"), ("1=2",)],
)
def test_inconsistent_premises_never_prove_a_tautology(facts):
    result = check("1=1", context(*facts), False)
    assert result.code == "inconsistent_premises"


@pytest.mark.parametrize(
    "premise",
    [
        "0*x=1",
        "x-x=1",
        "0*x>0",
        "x*0!=0",
        "x-x<0",
        "x+1<=x",
        "x>=x+1",
        "x/2-x/2=1/3",
        "x*(x+1)-x^2-x=1",
        "x/x=2",
        "(x+1)/(x+1)=2",
        "0*x+sqrt(2)=0",
        "1/x=0",
    ],
)
def test_ghost_symbols_cannot_hide_false_constant_premises(premise):
    c = context(premise)
    for goal in ("1=1", "y=3", "y=2"):
        result = prove_relation(relation(goal), c)
        assert result.status == "not_proved", result.to_payload()
        assert result.code == "inconsistent_premises", result.to_payload()
    assert prove_domain(scalar("x"), c).code == "inconsistent_premises"
    valid = prove_relation(relation("1=1"), context())
    assert replay_proof(valid, c).code == "inconsistent_premises"
    assert (
        verify_witnesses(
            [{name: scalar("1") for name in c.symbols}], [relation("1=1")], c
        ).code
        == "inconsistent_premises"
    )


@pytest.mark.parametrize("premise", ["0*x=0", "x-x>=0", "x+1>x", "x/x=1"])
def test_true_constant_premises_with_symbols_remain_consistent(premise):
    c = context(premise)
    check("1=1", c)
    check("y=3", c, False)
    # Cancellation in consistency checks never discharges the original domain.
    assert prove_domain(scalar("x/x"), c).status == "not_proved"


@pytest.mark.parametrize("premise", ["0*x=1", "x-x=1", "1/x=0"])
def test_polynomial_divisor_guard_independently_blocks_construction_and_replay(
    premise, monkeypatch
):
    from shuxueshuo_server.solver.math_kernel import proof_kernel

    c = context(premise, "x!=0")
    # Recreate a pre-fix certificate, then verify the rule-level defense even
    # with the earlier context check deliberately disabled for this test.
    monkeypatch.setattr(proof_kernel._Environment, "_check_context", lambda self: None)
    with monkeypatch.context() as legacy:
        legacy.setattr(Arithmetic, "equation_divisor", Arithmetic.difference)
        unsafe = prove_relation(relation("y=3"), c)
        assert unsafe.status == "proved", unsafe.to_payload()
    constructed = prove_relation(relation("y=3"), c)
    replayed = replay_proof(json.loads(json.dumps(unsafe.proof)), c)
    for result in (constructed, replayed):
        assert result.status == "not_proved"
        assert result.code == "inconsistent_premises"


@pytest.mark.parametrize(
    ("premise", "domain", "false_goal"),
    [
        ("1/x=2/x", "x!=0", "x=0"),
        ("1/x=2/x", "x!=0", "x^2=0"),
        ("1/x=2/x", "x!=0", "x*y=0"),
        ("2/x=3/x", "x!=0", "x=0"),
        ("1/(x+1)=2/(x+1)", "x+1!=0", "x+1=0"),
        ("1/(x*y+1)=2/(x*y+1)", "x*y+1!=0", "x*y+1=0"),
        ("1/(x+y)=2/(x+y)", "x+y!=0", "x+y=0"),
    ],
)
def test_cancelled_denominator_cannot_become_an_equality_premise(
    premise, domain, false_goal, monkeypatch
):
    from shuxueshuo_server.solver.math_kernel import proof_kernel

    c = context(premise, domain)
    # Capture the old invalid certificate with both defenses disabled.
    with monkeypatch.context() as legacy:
        legacy.setattr(proof_kernel._Environment, "_check_context", lambda self: None)
        legacy.setattr(Arithmetic, "equation_divisor", Arithmetic.difference)
        unsafe = prove_relation(relation(false_goal), c)
        assert unsafe.status == "proved", unsafe.to_payload()
    for facts in ((premise,), (premise, domain)):
        current = context(*facts)
        for goal in (false_goal, "1=1"):
            result = prove_relation(relation(goal), current)
            assert result.status == "not_proved", result.to_payload()
            assert result.code == "inconsistent_premises", result.to_payload()
        assert prove_domain(scalar("x"), current).code == "inconsistent_premises"
        assert (
            verify_witnesses(
                [{name: scalar("1") for name in current.symbols}],
                [relation("1=1")],
                current,
            ).code
            == "inconsistent_premises"
        )
    assert replay_proof(unsafe, c).code == "inconsistent_premises"
    # Rule-level construction and replay also reject it independently.
    monkeypatch.setattr(proof_kernel._Environment, "_check_context", lambda self: None)
    assert prove_relation(relation(false_goal), c).code == "inconsistent_premises"
    assert (
        replay_proof(json.loads(json.dumps(unsafe.proof)), c).code
        == "inconsistent_premises"
    )


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("0", "x+1", "x+1"),
        ("x^2-1", "x+1", "x+1"),
        ("(x+1)^2", "(x+1)^3", "(x+1)^2"),
        ("x*y+x", "x*y+y", "1"),
        ("(x+y)*(x+1)", "(x+y)*(y+1)", "x+y"),
        ("(x*y+1)*(x+1)", "(x*y+1)*(y+1)", "x*y+1"),
        ("(y+1)*(x+1)", "(y+1)*(x+2)", "y+1"),
        ("(x+1)^2*(y+1)", "(x+1)*(y+1)^2", "(x+1)*(y+1)"),
        ("(x+y)*(a+b)", "(x+y)*(a+1)", "x+y"),
        ("(x+1)/2", "-(x+1)/3", "x+1"),
    ],
)
def test_bounded_polynomial_gcd_handles_content_and_multiple_generators(
    left, right, expected
):
    arithmetic = Arithmetic(_Budget(ProofLimits()))

    def polynomial(source):
        numerator, denominator = arithmetic.rational(from_node(scalar(source).ast))
        return arithmetic.exact_quotient(numerator, denominator)

    a, b, expected_polynomial = map(polynomial, (left, right, expected))
    common = arithmetic.polynomial_gcd(a, b)
    assert common == expected_polynomial
    assert arithmetic.polynomial_gcd(b, a) == common
    for original in (a, b):
        quotient = arithmetic.exact_quotient(original, common)
        assert arithmetic.mul(quotient, common) == original


@pytest.mark.parametrize(
    ("premise", "domain", "goal"),
    [
        ("(x^2-1)/(x+1)=0", "x+1!=0", "x^2=1"),
        ("(x*y+x)/(y+1)=0", "y+1!=0", "x^2=0"),
    ],
)
def test_reduced_equality_keeps_original_domain_guards(premise, domain, goal):
    c = context(premise, domain)
    before = deepcopy(c.premises)
    result = check(goal, c)
    assert c.premises == before
    assert any(n["rule_id"] == "math.polynomial" for n in result.proof["nodes"])
    # Removing the original denominator's guard must not authorize cancellation.
    check(goal, context(premise), False)


def test_polynomial_gcd_uses_shared_reduction_budget():
    budget = _Budget(ProofLimits(reductions=1))
    arithmetic = Arithmetic(budget)
    a = arithmetic.rational(from_node(scalar("x^2-1").ast))[0]
    b = arithmetic.rational(from_node(scalar("x+1").ast))[0]
    with pytest.raises(ProofFailure) as caught:
        arithmetic.polynomial_gcd(a, b)
    assert caught.value.code == "proof_limit"
    c = context("1/(x+1)=2/(x+1)", limits=ProofLimits(reductions=1))
    assert prove_relation(relation("1=1"), c).code == "proof_limit"


@pytest.mark.parametrize(
    "premise",
    [
        "1/(x^2-1)=2/((x-1)*(x+1))",
        "1/(x^2-1)=1/(x^2+x)",
        "x/(x+1)=(x+2)/(x+1)",
    ],
)
def test_equivalent_or_overlapping_denominators_cannot_hide_contradictions(premise):
    assert (
        prove_relation(relation("1=1"), context(premise)).code
        == "inconsistent_premises"
    )


@pytest.mark.parametrize(
    "facts",
    [
        ("x>=0", "x<=-1"),
        ("x>=(1/2)", "x<=(1/3)"),
        ("x>=-1", "x<=-2"),
        ("-1<=x", "-2>=x"),
        ("1/2<=x", "1/3>=x"),
        ("x=-1/2", "x<=-2/3"),
        ("x>-(1/2)", "x<=(-2)/4"),
        ("x>=1-3/2", "x<=-(2/3)"),
        ("x>=2^-1", "x<=1/3"),
    ],
)
def test_rational_endpoint_contradictions_reject_even_tautologies(facts):
    c = context(*facts)
    assert prove_relation(relation("1=1"), c).code == "inconsistent_premises"
    assert prove_domain(scalar("x"), c).code == "inconsistent_premises"
    valid = prove_relation(relation("1=1"), context())
    assert replay_proof(valid, c).code == "inconsistent_premises"
    assert (
        verify_witnesses(
            [{name: scalar("0") for name in c.symbols}], [relation("1=1")], c
        ).code
        == "inconsistent_premises"
    )


@pytest.mark.parametrize(
    ("facts", "goal"),
    [
        (("x>=-2", "x<=-1"), "-x^2-3*x-2>=0"),
        (("1/3<=x", "1/2>=x"), "-x^2+5*x/6-1/6>=0"),
        (("x>=-1/2", "x<=(-2)/4"), "1=1"),
    ],
)
def test_consistent_rational_intervals_prove_and_replay(facts, goal):
    check(goal, context(*facts))


@pytest.mark.parametrize(
    ("source", "value"),
    [
        ("-(1/2)", Fraction(-1, 2)),
        ("1/(-2)", Fraction(-1, 2)),
        ("1-3/2", Fraction(-1, 2)),
        ("2^-1", Fraction(1, 2)),
        ("x/x", None),
        ("sqrt(4)", None),
    ],
)
def test_literal_rational_normalization_preserves_source_ast(source, value):
    parsed = scalar(source)
    tree = from_node(parsed.ast)
    before = deepcopy(tree)
    assert Arithmetic(_Budget(ProofLimits())).literal_rational(tree) == value
    assert tree == before


def test_literal_rational_normalization_respects_coefficient_budget():
    arithmetic = Arithmetic(_Budget(ProofLimits(coefficient_bits=4)))
    with pytest.raises(ProofFailure) as caught:
        arithmetic.literal_rational(from_node(scalar("1/(4*4)").ast))
    assert caught.value.code == "proof_limit"


def test_only_used_polynomial_premises_are_recorded():
    c = context("x=2", "y=3")
    r = check("x^2=4", c)
    root = next(n for n in r.proof["nodes"] if n["node_id"] == r.proof["roots"][0])
    assert root["premises"] == ["given_0"]


def test_deterministic_proof_and_source_spans():
    c = context("x!=0")
    p = replace(relation(" x/x = 1 "), source_path="/goals/0/math")
    first = prove_relation(p, c)
    assert first.to_payload() == prove_relation(p, c).to_payload()
    root = first.proof["nodes"][-1]
    assert any(ref["source_path"] == "/goals/0/math" for ref in root["input_nodes"])
    assert all(
        ref["node_path"]
        and len(ref["source_sha256"]) == 64
        and ref["span"][1] > ref["span"][0]
        for ref in root["input_nodes"]
    )


def test_replay_never_searches(monkeypatch):
    c = context("x>=0")
    result = check("sqrt(x^2)=x", c)

    def fail(*args, **kwargs):
        raise AssertionError("replay invoked proof search")

    monkeypatch.setattr(_Search, "need", fail)
    assert replay_proof(result, c).status == "proved"


@pytest.mark.parametrize(
    "tamper",
    [
        "conclusion",
        "domain",
        "premise",
        "source",
        "rule",
        "version",
        "cycle",
        "coefficient",
        "constant",
        "root",
    ],
)
def test_tampered_certificates_are_rejected(tamper):
    c = context("x!=0", "x=2")
    result = check("x/x+x=3", c)
    proof = deepcopy(result.proof)
    if tamper == "conclusion":
        proof["nodes"][-1]["conclusion"][0] = "<"
    elif tamper == "domain":
        proof["nodes"][-1]["children"].pop()
    elif tamper == "premise":
        node = next(n for n in proof["nodes"] if n["rule_id"] == "math.given")
        node["certificate"]["premise_id"] = "missing"
    elif tamper == "source":
        proof["nodes"][-1]["input_nodes"][0]["span"] = [0, 0]
    elif tamper == "rule":
        proof["nodes"][-1]["rule_id"] = "math.trust_me"
    elif tamper == "version":
        proof["ruleset_hash"] = "obsolete"
    elif tamper == "cycle":
        proof["nodes"][-1]["children"] = [proof["nodes"][-1]["node_id"]]
    elif tamper == "coefficient":
        proof = deepcopy(check("x^2=4", c).proof)
        node = next(
            n
            for n in proof["nodes"]
            if n["rule_id"] == "math.polynomial"
            and any(n["certificate"]["multipliers"])
        )
        node["certificate"]["multipliers"][0][0][1] = "99"
    elif tamper == "constant":
        proof = deepcopy(check("2*sqrt(3)-3>0", c).proof)
        node = next(
            n
            for n in proof["nodes"]
            if n["rule_id"] == "math.constant" and n["certificate"]["bits"]
        )
        node["certificate"]["interval"] = ["10", "11"]
    else:
        proof["roots"] = [proof["nodes"][-1]["children"][0]]
    assert replay_proof(proof, c).status == "not_proved"


def fixture_context(case):
    data = json.loads((FIXTURES / case / "problem-ir.json").read_text())["input"]
    symbols = {e["name"]: sp.Symbol(e["name"], real=True) for e in data["entities"]}
    facts = {
        f"fact_{i}": replace(
            relation(f["normalized_expression"], symbols), source_path=f["source_path"]
        )
        for i, f in enumerate(data["facts"])
        if f["bound_expression"][0] not in {"default_domain", "∈"}
    }
    return ProofContext(symbols, facts)


def test_q20_same_target_principal_square_root():
    c = fixture_context("q20")
    goal = "1/x+1/y=sqrt(x*y+4/(x*y))"
    r = check(goal, c)
    assert any(n["rule_id"] == "math.square_equal" for n in r.proof["nodes"])
    only_equation = {k: v for k, v in c.premises.items() if v.ast.op == "="}
    check(goal, replace(c, premises=only_equation), False)


def test_q12_all_four_frozen_witnesses_and_bad_branch():
    c = fixture_context("q12")
    data = json.loads((FIXTURES / "q12/expected.json").read_text())
    assignments = [
        {name: scalar(value, c.symbols) for name, value in branch.items()}
        for branch in data["equality_branches"]
    ]
    requirements = [relation("x^2+y^2=4/5", c.symbols)]
    result = verify_witnesses(assignments, requirements, c)
    assert result.status == "proved", result.to_payload()
    assert len(result.branches) == 4
    assert replay_proof(json.loads(json.dumps(result.proof)), c).status == "proved"
    assignments[2] = {"x": scalar("0", c.symbols), "y": scalar("1", c.symbols)}
    failed = verify_witnesses(assignments, requirements, c)
    assert failed.status == "not_proved" and len(failed.branches) == 4
    assert [x["status"] for x in failed.branches] == [
        "proved",
        "proved",
        "not_proved",
        "proved",
    ]


def proof_node_count(proof):
    return len(proof["nodes"]) + sum(
        proof_node_count(node["certificate"]["proof"])
        for node in proof["nodes"]
        if node["rule_id"] == "math.witness"
    )


@pytest.mark.parametrize("case", ["simple", "exists", "q12"])
def test_witness_nodes_are_charged_once_across_all_branches(case):
    if case == "q12":
        c = fixture_context(case)
        data = json.loads((FIXTURES / "q12/expected.json").read_text())
        assignments = [
            {name: scalar(value, c.symbols) for name, value in branch.items()}
            for branch in data["equality_branches"]
        ]
        requirements = [relation("x^2+y^2=4/5", c.symbols)]
    else:
        c = context("x>=0", symbols={"x": SYMBOLS["x"]})
        assignments = [{"x": scalar("1", c.symbols)}]
        requirements = [relation("x=1", c.symbols)]
    options = {"mode": "exists", "selected_branch": 0} if case == "exists" else {}
    result = verify_witnesses(assignments, requirements, c, **options)
    assert result.status == "proved", result.to_payload()
    count = proof_node_count(result.proof)
    tight = replace(c, limits=replace(c.limits, nodes=count))
    result = verify_witnesses(assignments, requirements, tight, **options)
    assert result.status == "proved", result.to_payload()
    assert proof_node_count(result.proof) == count
    assert replay_proof(json.loads(json.dumps(result.proof)), tight).status == "proved"
    insufficient = replace(c, limits=replace(c.limits, nodes=count - 1))
    assert (
        verify_witnesses(assignments, requirements, insufficient, **options).code
        == "proof_limit"
    )

    # Independent replay still charges nested nodes against one shared budget.
    replay_budget = _Budget(tight.limits)
    replay_budget.use("nodes")
    with pytest.raises(ProofFailure, match="nodes") as caught:
        _replay(result.proof, tight, budget=replay_budget)
    assert caught.value.code == "proof_limit"


def test_witness_attachment_still_rejects_corrupt_child_proof(monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_kernel

    run_request = proof_kernel._run_request

    def corrupt(*args, **kwargs):
        result = run_request(*args, **kwargs)
        result.proof["nodes"][-1]["children"] = []
        return result

    monkeypatch.setattr(proof_kernel, "_run_request", corrupt)
    c = context("x>=0", symbols={"x": SYMBOLS["x"]})
    result = verify_witnesses(
        [{"x": scalar("1", c.symbols)}], [relation("x=1", c.symbols)], c
    )
    assert result.status == "not_proved"
    assert result.code == "invalid_proof"


def range_witness(c):
    data = json.loads((FIXTURES / "q17/expected.json").read_text())["range_attainment"]
    symbols = {**c.symbols, "s": sp.Symbol("s", real=True)}
    assignments = {
        name: scalar(data[name].replace("Delta", f"({data['Delta']})"), symbols)
        for name in ("x", "y")
    }
    return Witness(assignments, "s", ("-2", "2")), relation("x+y=s", symbols)


def test_q17_parameterization_proves_whole_interval_and_endpoints_do_not():
    c = fixture_context("q17")
    witness, requirement = range_witness(c)
    result = verify_witnesses([witness], [requirement], c, require_parameterized=True)
    assert result.status == "proved", result.to_payload()
    assert replay_proof(json.loads(json.dumps(result.proof)), c).status == "proved"
    endpoints = [
        {name: scalar(str(sign), c.symbols) for name in ("x", "y")} for sign in (-1, 1)
    ]
    rejected = verify_witnesses(
        endpoints, [relation("x=y", c.symbols)], c, require_parameterized=True
    )
    assert rejected.code == "proof_missing"
    wrong = replace(witness, interval=("-3", "3"))
    assert (
        verify_witnesses([wrong], [requirement], c, require_parameterized=True).status
        == "not_proved"
    )


def test_witness_tampering_cannot_remove_original_conditions():
    c = context("x>0", symbols={"x": SYMBOLS["x"]})
    result = verify_witnesses(
        [{"x": scalar("1", c.symbols)}], [relation("x=1", c.symbols)], c
    )
    assert result.status == "proved", result.to_payload()
    proof = deepcopy(result.proof)
    proof["nodes"][-1]["certificate"]["proof"]["request"]["relations"].pop(0)
    assert replay_proof(proof, c).status == "not_proved"


def test_explicit_existential_branch_does_not_claim_all_branches():
    c = context("x>0", symbols={"x": SYMBOLS["x"]})
    assignments = [{"x": scalar("1", c.symbols)}, {"x": scalar("-1", c.symbols)}]
    result = verify_witnesses(
        assignments, [relation("x=1", c.symbols)], c, mode="exists", selected_branch=0
    )
    assert result.status == "proved", result.to_payload()
    assert result.branches == ({"index": 0, "status": "proved"},)
    assert replay_proof(result, c).status == "proved"
    assert (
        verify_witnesses(assignments, [relation("x=1", c.symbols)], c).status
        == "not_proved"
    )


def test_cycle_and_missing_assignments_fail():
    c = context(symbols={"x": SYMBOLS["x"], "y": SYMBOLS["y"]})
    r = verify_witnesses(
        [{"x": scalar("y", c.symbols), "y": scalar("x", c.symbols)}],
        [relation("x=y", c.symbols)],
        c,
    )
    assert r.code == "proof_missing"
    r = verify_witnesses(
        [{"x": scalar("1", c.symbols)}], [relation("x=y", c.symbols)], c
    )
    assert r.status == "not_proved"


@pytest.mark.parametrize(
    ("limit", "value", "facts", "goal"),
    [
        ("nodes", 1, (), "x=x"),
        ("attempts", 1, ("x>0",), "x*x>0"),
        ("reductions", 1, ("x=2",), "x^2=4"),
        ("depth", 1, ("x>0",), "x*x>0"),
        ("polynomial_degree", 1, (), "x^2=x*x"),
        ("polynomial_terms", 1, (), "x+y=y+x"),
        ("coefficient_bits", 2, (), "10=10"),
        ("radicals", 1, (), "sqrt(2)<sqrt(3)"),
        ("algebraic_degree", 1, (), "sqrt(2)>1"),
        ("refinements", 1, (), "sqrt(2)>7/5"),
        ("premises", 1, ("x>0", "y>0"), "x>0"),
        ("variables", 1, (), "x=x"),
    ],
)
def test_shared_budgets_fail_closed(limit, value, facts, goal):
    limits = replace(ProofLimits(), **{limit: value})
    result = check(goal, context(*facts, limits=limits), False)
    assert result.code == "proof_limit", result.to_payload()


def test_parser_markers_and_removed_obligations_do_not_become_facts():
    marker = parse_math_steps([{"math": "u:=x"}], SYMBOLS)[0]
    assert prove_relation(marker, context()).status == "not_proved"
    broken = replace(relation("x/x=1"), obligations=())
    assert prove_relation(broken, context("x!=0")).code == "invalid_input"


def test_no_solver_or_float_fallback(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unbounded or numerical fallback")

    for name in ("solve", "solveset", "reduce_inequalities", "groebner"):
        monkeypatch.setattr(sp, name, forbidden)
    check("x^2=4", context("x=2"))
    check("sqrt(x^2)=x", context("x>=0"))
    check("2*sqrt(3)-3>0", context())


def test_replay_resolves_default_source_pointers_and_detects_scope_changes():
    c = ProofContext(
        {"x": SYMBOLS["x"]}, {"a/b~c": relation("x!=0")}, scope_id="problem/child"
    )
    result = check("x/x=1", c)
    for node in result.proof["nodes"]:
        for ref in node["input_nodes"]:
            target = result.proof
            for part in ref["source_path"].split("/")[1:]:
                target = target[part.replace("~1", "/").replace("~0", "~")]
            assert isinstance(target, str)
    assert (
        replay_proof(result, replace(c, scope_id="problem/sibling")).code
        == "invalid_proof"
    )


def test_parameter_label_alone_does_not_certify_range_attainment():
    c = context(symbols={"x": SYMBOLS["x"]})
    witness = Witness({"x": scalar("1", c.symbols)}, "s", ("-2", "2"))
    result = verify_witnesses(
        [witness], [relation("x=1", c.symbols)], c, require_parameterized=True
    )
    assert result.code == "proof_missing"


def test_equation_and_branch_budgets():
    c = context("x+y=3", "x-y=1", limits=replace(ProofLimits(), equations=1))
    assert check("x=2", c, False).code == "proof_limit"
    c = context(symbols={"x": SYMBOLS["x"]}, limits=replace(ProofLimits(), branches=1))
    branch = {"x": scalar("1", c.symbols)}
    assert (
        verify_witnesses([branch, branch], [relation("x=1", c.symbols)], c).code
        == "proof_limit"
    )


def test_repeated_sign_dependencies_are_valid_dag_edges():
    check("x*x>0", context("x>0"))
    check("x/x>0", context("x>0"))


def test_corrupt_polynomial_denominator_is_a_structured_rejection():
    c = context("x=2")
    proof = deepcopy(check("x^2=4", c).proof)
    polynomial = next(
        n
        for n in proof["nodes"]
        if n["rule_id"] == "math.polynomial" and any(n["certificate"]["multipliers"])
    )
    polynomial["certificate"]["multipliers"][0][0][2] = "0"
    assert replay_proof(proof, c).code == "invalid_proof"


def test_altered_parser_source_spans_are_rejected():
    parsed = relation("x=x")
    altered = replace(parsed, ast=replace(parsed.ast, span=(0, 0)))
    assert prove_relation(altered, context()).code == "invalid_input"


def test_explicitly_nonreal_symbol_is_rejected():
    symbols = {"x": sp.Symbol("x", imaginary=True)}
    result = prove_relation(relation("x^2>=0", symbols), ProofContext(symbols))
    assert result.status == "not_proved" and result.code == "invalid_input"


@pytest.mark.parametrize("total,bound", [("2", "1"), ("6", "9"), ("1/2", "1/16")])
def test_amgm_fixed_sum_certificate_replays(total, bound):
    ctx = context("x>0", "y>0", f"x+y={total}")
    check("x+y>=2*sqrt(x*y)", ctx)
    result = check(f"x*y<={bound}", ctx)
    assert any(
        n["rule_id"] == "math.fixed_sum_product_bound" for n in result.proof["nodes"]
    )
    damaged = deepcopy(result.proof)
    node = next(
        n for n in damaged["nodes"] if n["rule_id"] == "math.fixed_sum_product_bound"
    )
    node["certificate"]["sum_premise"] = "given_0"
    assert replay_proof(damaged, ctx).status == "not_proved"


@pytest.mark.parametrize(
    "facts,goal",
    [
        (("x+y=2",), "x+y>=2*sqrt(x*y)"),
        (("x>0", "y>0", "x+y=2"), "x*y<=1/2"),
        (("x>0", "y>0", "x+y=2"), "x*y>=1"),
        (("x>0", "y>0"), "x+y>=3*sqrt(x*y)"),
        (("x>0", "y>0"), "x+y<=2*sqrt(x*y)"),
        (("x>0", "y>0", "x+y=2"), "a*b<=1"),
        (("x>0", "y>0", "x+y=-2"), "x*y<=1"),
    ],
)
def test_amgm_rejects_unproved_conditions_or_wrong_bound(facts, goal):
    check(goal, context(*facts), False)


@pytest.mark.parametrize("total", ["x+y", "y+x"])
@pytest.mark.parametrize("product", ["x*y", "y*x"])
@pytest.mark.parametrize("root_first", [False, True])
def test_amgm_commuted_terms_preserve_source_and_replay(total, product, root_first):
    rhs = f"sqrt({product})*2" if root_first else f"2*sqrt({product})"
    text = f"{total}>={rhs}"
    parsed = relation(text)
    original_ast = from_node(parsed.ast)
    result = check(text, context("x>0", "y>0", "x+y=2"))
    theorem = next(
        n for n in result.proof["nodes"] if n["rule_id"] == "math.two_term_amgm"
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import freeze

    assert freeze(theorem["conclusion"]) == original_ast
    assert parsed.source == text
    assert from_node(parsed.ast) == original_ast
    check(text, context("x+y=2"), False)


@pytest.mark.parametrize(
    "rhs", ["2*sqrt(y/x)", "2*sqrt(y-x)", "3*sqrt(y*x)", "2*sqrt(x*x)"]
)
def test_amgm_commutation_does_not_change_operations_or_factors(rhs):
    check(f"x+y>={rhs}", context("x>0", "y>0", "x+y=2"), False)


def test_commuted_amgm_retains_denominator_obligations():
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ZERO, freeze

    result = check("x+1/x>=2*sqrt((1/x)*x)", context("x>0"))
    assert any(
        freeze(node["conclusion"]) == ("!=", ("symbol", "x"), ZERO)
        for node in result.proof["nodes"]
    )
    check("x+1/x>=2*sqrt((1/x)*x)", context(), False)


def test_commuted_amgm_replay_rejects_different_radical():
    result = check("y+x>=2*sqrt(x*y)", context("x>0", "y>0"))
    proof = deepcopy(result.proof)
    node = next(n for n in proof["nodes"] if n["rule_id"] == "math.two_term_amgm")
    node["conclusion"] = from_node(relation("y+x>=2*sqrt(x/y)").ast)
    assert replay_proof(proof, context("x>0", "y>0")).status == "not_proved"
