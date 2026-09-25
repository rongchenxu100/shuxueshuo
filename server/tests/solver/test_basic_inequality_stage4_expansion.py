"""Four frozen inputs through the authenticated transactional solver."""

from pathlib import Path

import pytest
from tools.run_basic_inequality_stage4a import run

FIXTURES = Path(__file__).parent / "fixtures"
PLANS = FIXTURES / "basic-inequality-stage4"


@pytest.mark.parametrize(
    "case,answer", [("q01", "1"), ("q03", "9"), ("q07", "2*sqrt(2)"), ("q08", "4")]
)
def test_four_frozen_cases(case, answer, tmp_path):
    result, runtime = run(
        gold=FIXTURES / f"math-notation-v1/basic-inequality/{case}.json",
        problem_ir=FIXTURES / f"basic-inequality-problem-ir/v1/{case}/problem-ir.json",
        output=tmp_path / case,
        mode="recorded",
        plan=PLANS / f"{case}.json",
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {
        "problem": {"maximum" if case == "q01" else "minimum": answer}
    }
    assert runtime.last_success_artifacts.verified_functional_execution is not None


import sympy as sp
from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
    RewriteError,
    verify_chain,
)
from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
    close_bound,
    public_bound,
    verify_bound,
)
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure


def target(expr="1/a+a/b^2+b", conditions=("a>0", "b>0"), symbols=("a", "b")):
    return {
        "type": "extremum_target",
        "goal_kind": "find_minimum",
        "scope_id": "problem",
        "target_math": expr,
        "scalar_symbols": list(symbols),
        "source_conditions": [
            {"handle": f"c{i}", "math": c, "source_path": f"/facts/{i}/math"}
            for i, c in enumerate(conditions)
        ],
    }


def rows(*lines):
    return [{"math": s} for s in lines]


@pytest.mark.parametrize(
    "total,product,witness,equality,terms",
    [
        ("2*x+y", "2*x*y", ("x=1", "y=2"), "((2)*(x))=(y)", ["(2)*(x)", "y"]),
        ("x+2*y", "x*(2*y)", ("x=2", "y=1"), "(x)=((2)*(y))", ["x", "(2)*(y)"]),
    ],
)
def test_weighted_fixed_sum_maximum_replays_and_closes(
    total, product, witness, equality, terms, monkeypatch
):
    import shuxueshuo_server.solver.math_kernel.inequality_bound_v2 as v2
    import shuxueshuo_server.solver.math_kernel.inequality_evidence as legacy

    t = target("2*x*y", ("x>0", "y>0", f"{total}=4"), ("x", "y"))
    t["goal_kind"] = "find_maximum"
    derivation = rows(f"{total}>=2*sqrt({product})", "2*x*y<=4")
    bound = public_bound(verify_bound(t, derivation))

    def forbidden(*args, **kwargs):
        raise AssertionError("maximum closure must replay certificates without search")

    monkeypatch.setattr(v2, "_run_request", forbidden)
    monkeypatch.setattr(legacy, "_verify_bound_v1", forbidden)
    rebuilt = v2.verify(t, derivation, certificates=bound["certificate_bundle"])
    assert public_bound(rebuilt) == bound
    assert bound["equality"] == equality
    assert bound["equalities"] == [equality]
    assert bound["applications"] == [{"terms": terms, "equality": equality}]
    value, evidence = close_bound(t, bound, rows(*witness))
    assert value == 4
    assert evidence["assignments"] == dict(row.split("=") for row in witness)
    assert public_bound(evidence["bound"]) == bound


def test_v1_weighted_maximum_keeps_original_equality_text():
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        _verify_bound_v1,
    )

    t = target("2*x*y", ("x>0", "y>0", "2*x+y=4"), ("x", "y"))
    t["goal_kind"] = "find_maximum"
    derivation = rows("2*x+y>=2*sqrt(2*x*y)", "2*x*y<=4")
    bound = public_bound(_verify_bound_v1(t, derivation))
    assert bound["schema_version"] == "amgm-bound/v1"
    assert bound["equality"] == "(2*x)=(y)"
    assert close_bound(t, bound, rows("x=1", "y=2"))[0] == 4
    bound["equality"] = "((2)*(x))=(y)"
    with pytest.raises(ProofFailure, match="bound evidence altered"):
        close_bound(t, bound, rows("x=1", "y=2"))


@pytest.mark.parametrize("field", ("equality", "equalities", "applications"))
def test_v2_weighted_maximum_still_rejects_altered_equality_evidence(field):
    t = target("2*x*y", ("x>0", "y>0", "2*x+y=4"), ("x", "y"))
    t["goal_kind"] = "find_maximum"
    bound = public_bound(verify_bound(t, rows("2*x+y>=2*sqrt(2*x*y)", "2*x*y<=4")))
    # Even mathematically equivalent text must not bypass strict evidence replay.
    if field == "equality":
        bound[field] = "(2*x)=(y)"
    elif field == "equalities":
        bound[field] = ["(2*x)=(y)"]
    else:
        bound[field][0]["terms"][0] = "2*x"
    with pytest.raises(ProofFailure, match="bound or dependency evidence altered"):
        close_bound(t, bound, rows("x=1", "y=2"))


@pytest.mark.parametrize(
    "first", ["1/a+a/b^2+b>=2/b+b", "∵a>0,b>0；∴b+a/b^2+1/a>=b+2/b"]
)
def test_continuous_bound_replays_and_closes(first):
    t = target()
    b = public_bound(verify_bound(t, rows(first)))
    final = public_bound(verify_bound(t, rows("2/b+b>=2*sqrt(2)"), previous_bound=b))
    assert len(final["equalities"]) == 2
    value, evidence = close_bound(t, final, rows("a=b=sqrt(2)"))
    assert value == 2 * sp.sqrt(2)
    assert evidence["exhaustive"] is False


def test_continuous_bound_renamed_variables_and_coefficients():
    t = target("1/p+p/q^2+4*q", ("p>0", "q>0"), ("p", "q"))
    t["problem_id"] = "unrelated-id"
    first = public_bound(verify_bound(t, rows("4*q+p/q^2+1/p>=4*q+2/q")))
    final = public_bound(
        verify_bound(t, rows("4*q+2/q>=4*sqrt(2)"), previous_bound=first)
    )
    value, _ = close_bound(t, final, rows("p=q=1/sqrt(2)"))
    assert value == 4 * sp.sqrt(2)


def test_distinct_local_pairs_are_ambiguous():
    # Either 1+4 -> 4, or 4+9 -> 12; equal final constants do not
    # authorize selecting one of these different equality conditions.
    with pytest.raises(ProofFailure) as error:
        verify_bound(target("1+4+9"), rows("1+4+9>=13"))
    assert error.value.code == "inequality_ambiguous"


def test_reordered_predecessor_is_not_a_new_amgm_application():
    t = target()
    first = public_bound(verify_bound(t, rows("1/a+a/b^2+b>=2/b+b")))
    second = public_bound(
        verify_bound(
            t,
            rows(
                "b+2/b>=2*sqrt(b*(2/b))",
                "b+2/b>=2*sqrt(2)",
                "1/a+a/b^2+b>=b+2/b",
                "1/a+a/b^2+b>=2*sqrt(2)",
            ),
            previous_bound=first,
        )
    )
    assert len(second["applications"]) == 2
    assert close_bound(t, second, rows("a=b=sqrt(2)"))[0] == 2 * sp.sqrt(2)


@pytest.mark.parametrize(
    "mutation",
    ["target", "equality", "constant", "certificate", "source", "dependency"],
)
def test_bound_tampering_is_rejected(mutation):
    t = target()
    first = public_bound(verify_bound(t, rows("1/a+a/b^2+b>=2/b+b")))
    b = public_bound(verify_bound(t, rows("2/b+b>=2*sqrt(2)"), previous_bound=first))
    if mutation == "target":
        t["scope_id"] = "other"
    if mutation == "equality":
        b["equalities"].pop(0)
    if mutation == "constant":
        b["bound"] = "3"
    if mutation == "certificate":
        b["certificate_bundle"]["derivation"]["proofs"][0]["ruleset_hash"] = "wrong"
    if mutation == "source":
        b["certificate_bundle"]["derivation"]["origins"][0]["source"] = "wrong"
    if mutation == "dependency":
        b["previous_bound"]["bound"] = "3/b+b"
    with pytest.raises((ProofFailure, ValueError)):
        close_bound(t, b, rows("a=b=sqrt(2)"))


def test_symbolic_bound_cannot_close_and_wrong_witness_fails():
    t = target()
    b = public_bound(verify_bound(t, rows("1/a+a/b^2+b>=2/b+b")))
    with pytest.raises(ProofFailure):
        close_bound(t, b, rows("a=b=1"))
    b = public_bound(verify_bound(t, rows("2/b+b>=2*sqrt(2)"), previous_bound=b))
    with pytest.raises(ProofFailure):
        close_bound(t, b, rows("a=1", "b=sqrt(2)"))


@pytest.mark.parametrize("relation", ["1/a+a/b^2+b>=3/b+b", "1/a+a/b^2+b<=2/b+b"])
def test_false_bound_fails(relation):
    with pytest.raises(ProofFailure):
        verify_bound(target(), rows(relation))


@pytest.mark.parametrize(
    "expression,bound", [("5+u+4/u", "9"), ("2*(u+4/u)", "8"), ("(u+4/u)/2", "2")]
)
def test_unchanged_context_and_positive_scaling(expression, bound):
    t = target(expression, ("u>0",), ("u",))
    result = verify_bound(t, rows(expression + ">=" + bound))
    assert result["bound"] == bound


def test_m01_radical_domains_and_replay():
    x = sp.Symbol("x", real=True)
    ss = {"x": x}
    conditions = [sp.Ge(x, 0, evaluate=False)]
    trace = verify_chain(
        sp.sqrt(x**2), conditions, rows("sqrt(x^2)", "x"), ss, input_source="sqrt(x^2)"
    )
    assert trace["value"] == x and trace["proofs"]
    with pytest.raises(RewriteError):
        verify_chain(sp.sqrt(x**2), [], rows("sqrt(x^2)", "x"), ss)
    with pytest.raises(RewriteError):
        verify_chain(sp.Integer(1), [], rows("x/x", "1"), ss, input_source="x/x")


def test_closure_replays_certificates_without_search(monkeypatch):
    import shuxueshuo_server.solver.math_kernel.inequality_bound_v2 as v2

    t = target("u+4/u", ("u>0",), ("u",))
    b = public_bound(verify_bound(t, rows("u+4/u>=4")))

    def forbidden(*args, **kwargs):
        raise AssertionError("bound proof search during closure")

    monkeypatch.setattr(v2, "_run_request", forbidden)
    assert close_bound(t, b, rows("u=2"))[0] == 4


def test_radical_constant_cancellation_keeps_domain_guards():
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.proof_kernel import (
        ProofContext,
        prove_relation,
        replay_proof,
    )

    ss = {n: sp.Symbol(n, real=True) for n in ("x", "y")}
    parse = lambda text: parse_math_relation(text, ss)
    context = ProofContext(ss, {"x": parse("x>0"), "y": parse("y>0")})
    candidate = parse("2*sqrt((x/y)*(4*y/x))=4")
    result = prove_relation(candidate, context)
    assert result.status == "proved"
    assert replay_proof(result.proof, context).status == "proved"
    assert prove_relation(candidate, ProofContext(ss)).status == "not_proved"


def test_expression_input_requires_committed_same_target_authority():
    from shuxueshuo_server.solver.math_kernel import SympyKernel
    from shuxueshuo_server.solver.runtime.functional_diagnostics import (
        StatelessMethodError,
    )
    from shuxueshuo_server.solver.runtime.methods.apply_two_term_amgm import (
        ApplyTwoTermAmgmMethod,
    )

    with pytest.raises(StatelessMethodError, match="committed M01"):
        ApplyTwoTermAmgmMethod().run(
            {
                "target": target("a+b"),
                "expression": sp.Symbol("a") + sp.Symbol("b"),
                "__parameters__": {"steps": rows("a+b>=2*sqrt(a*b)")},
            },
            SympyKernel(),
        )


def test_missing_certificate_and_one_bad_branch_fail_closed():
    t = target("u+4/u", ("u>0",), ("u",))
    b = public_bound(verify_bound(t, rows("u+4/u>=4")))
    with pytest.raises(ProofFailure):
        close_bound(t, b, branches=[{"steps": rows("u=2")}, {"steps": rows("u=1")}])
    b.pop("certificate_bundle")
    with pytest.raises(ProofFailure, match="missing"):
        close_bound(t, b, rows("u=2"))


@pytest.mark.parametrize("math", ["m*n<=((m+n)/2)^2", "(m+n)/2>=sqrt(m*n)"])
def test_maximum_equivalent_amgm_forms(math):
    t = target("m*n", ("m>0", "n>0", "m+n=2"), ("m", "n"))
    t["goal_kind"] = "find_maximum"
    b = public_bound(verify_bound(t, rows(math, "m*n<=1")))
    assert close_bound(t, b, rows("m=n=1"))[0] == 1


def test_m01_preserves_raw_premise_and_ignores_symbol_positive_assumption():
    x = sp.Symbol("x", positive=True)
    with pytest.raises(RewriteError):
        verify_chain(
            x,
            [{"math": "sqrt(x^2)=-x"}],
            [
                {"math": "x"},
                {"math": "0", "using": ["sqrt(x^2)=-x"]},
            ],
            {"x": x},
            input_source="x",
        )
    trace = verify_chain(
        sp.Pow(x**2, sp.Rational(1, 2), evaluate=False),
        [],
        [
            {"math": "sqrt(x^2)"},
            {"math": "sqrt(x^2)"},
        ],
        {"x": x},
        input_source="sqrt(x^2)",
    )
    assert trace["value"] != x
    assert next(iter(trace["value"].free_symbols)) is x


def test_long_valid_bound_keeps_a_shared_bounded_algebra_cache():
    t = target("1/(2*a)+1/(2*b)+8/(a+b)", ("a>0", "b>0", "a*b=1"))
    b = public_bound(
        verify_bound(
            t,
            rows(
                "∵a>0,b>0,a*b=1",
                "∴a+b>0",
                "∴(a+b)/2>0,8/(a+b)>0",
                "∴(a+b)/2+8/(a+b)>=2*sqrt(((a+b)/2)*(8/(a+b)))",
                "∴2*sqrt(((a+b)/2)*(8/(a+b)))=4",
                "∴(a+b)/2+8/(a+b)>=4",
                "∴1/(2*a)+1/(2*b)+8/(a+b)>=4",
            ),
            expression="(a+b)/2+8/(a+b)",
        )
    )
    assert close_bound(t, b, rows("a=2+sqrt(3),b=2-sqrt(3)"))[0] == 4


def test_repeated_witness_assertions_keep_source_coverage():
    t = target("u+4/u", ("u>0",), ("u",))
    b = public_bound(verify_bound(t, rows("u+4/u>=4")))
    _, evidence = close_bound(t, b, rows(*(["u=2,u+4/u=4"] * 8)))
    coverage = evidence["branches"][0]["requirement_coverage"]
    assert len(coverage) == 18
    assert len({c["proof_requirement"] for c in coverage}) == 3
    with pytest.raises(ProofFailure):
        close_bound(t, b, rows(*(["u=2,u+4/u=4"] * 7), "u=3"))


def test_v1_upper_bound_cannot_authorize_a_minimum():
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        _verify_bound_v1,
    )

    t = target("m*n", ("m>0", "n>0", "m+n=2"), ("m", "n"))
    with pytest.raises(ProofFailure, match="v1 is a maximum"):
        _verify_bound_v1(t, rows("m+n>=2*sqrt(m*n)", "m*n<=1"))


@pytest.mark.parametrize("names,k", [("x y", 2), ("u v", 3)])
def test_equation_derivation_is_conditional_replayable_and_not_witness_assumption(
    names, k
):
    from copy import deepcopy

    from shuxueshuo_server.solver.math_kernel.inequality_bound_v2 import (
        verify_equality_derivation,
    )
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import target_context

    x, y = names.split()
    t = target(f"{x}+{k * k}*{y}", (f"{x}>0", f"{y}>0", f"1/{x}+1/{y}=1"), (x, y))
    context, _ = target_context(t)
    eq = f"{x}/{y}={k * k}*{y}/{x}"
    rows = [
        {"math": f"{x}^2={k * k}*{y}^2", "using": [eq]},
        {"math": f"{x}={k}*{y}", "using": [f"{x}^2={k * k}*{y}^2"]},
        {"math": f"{k + 1}/({k}*{y})=1", "using": [f"{x}={k}*{y}", f"1/{x}+1/{y}=1"]},
        {"math": f"{y}={k + 1}/{k}", "using": [f"{k + 1}/({k}*{y})=1"]},
        {"math": f"{x}={k + 1}", "using": [f"{x}={k}*{y}", f"{y}={k + 1}/{k}"]},
    ]
    certs = verify_equality_derivation(context, [eq], rows)
    assert verify_equality_derivation(context, [eq], rows, certificates=certs) == certs
    bad = deepcopy(certs)
    bad[-1]["proof"]["nodes"][-1]["conclusion"] = ["=", ["rat", 1, 1], ["rat", 2, 1]]
    with pytest.raises(ProofFailure):
        verify_equality_derivation(context, [eq], rows, certificates=bad)
    circular = [{"math": f"{x}={k + 1}", "using": [f"{x}={k + 1}"]}]
    with pytest.raises(ProofFailure, match="known equality"):
        verify_equality_derivation(context, [eq], circular)
    # Equality alone is not a license to discard the negative square root.
    no_sign, _ = target_context(target(t["target_math"], (f"1/{x}+1/{y}=1",), (x, y)))
    with pytest.raises(ProofFailure):
        verify_equality_derivation(no_sign, [eq], rows[:2])


def test_branch_equation_derivation_keeps_case_assumptions_local_and_rejects_wrong_case():
    import json
    from copy import deepcopy

    parameters = json.loads((PLANS / "q08.json").read_text())["root_scope"]["goals"][0][
        "steps"
    ][-1]["parameters"]
    t = target("1/(2*a)+1/(2*b)+8/(a+b)", ("a>0", "b>0", "a*b=1"))
    bound = public_bound(
        verify_bound(t, rows("(a+b)/2+8/(a+b)>=4"), expression="(a+b)/2+8/(a+b)")
    )
    value, evidence = close_bound(t, bound, **parameters)
    assert value == 4 and evidence["exhaustive"] is False
    assert len(evidence["branches"]) == 2
    for i, branch in enumerate(evidence["branches"]):
        assert len(branch["equality_derivation"]) == 3
        assert (
            branch["equality_derivation"][0]["source_path"]
            == f"/parameters/branches/{i}/equality_derivation/0/math"
        )
        assert "solution_case" not in str(evidence["witness_proof"]["sources"])
    bad = deepcopy(parameters)
    bad["branches"][0]["when"] = "a-2<=0"
    with pytest.raises(ProofFailure):
        close_bound(t, bound, **bad)
    bad = deepcopy(parameters)
    bad["branches"][0]["equality_derivation"][-1]["math"] = "b=2+sqrt(3)"
    with pytest.raises(ProofFailure):
        close_bound(t, bound, **bad)
    bad = deepcopy(parameters)
    bad["branches"][0]["equality_derivation"].pop()
    with pytest.raises(ProofFailure, match="every submitted assignment"):
        close_bound(t, bound, **bad)
