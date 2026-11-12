"""Review regressions: source coverage, scalar roles and complete parameter cases."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import shifted_odd_math as math
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_shifted_odd import (
    TARGET,
    TYPE,
    candidate,
    describe,
    originals,
)


@pytest.mark.parametrize(
    "definition,extra,target,expected",
    [
        ("f(x)=p*g(x)+2", [], "f(1)+f(-1)", 4),
        ("f(x)=(p-7)*g(x)-3", [], "2*f(1)+2*f(-1)", -12),
        ("f(t)=x*g(t)+2", [], "f(1)+f(-1)", 4),
        ("f(x)=p*g(x)+p", [], "f(1)+f(-1)", None),
        ("f(x)=p*g(x)+2", ["f(1)=2", "f(-1)=2"], "p", sp.S.Reals),
        ("f(x)=p*g(x)+2", ["f(1)=3", "f(-1)=1"], "p", sp.S.Reals - sp.FiniteSet(0)),
        ("f(x)=(p-7)*g(x)+2", ["f(1)=3"], "p", sp.S.Reals - sp.FiniteSet(7)),
        ("f(x)=p*g(x)+2", ["f(1)=2", "g(1)=2"], "p", 0),
        ("f(x)=p*g(x)+2", ["f(1)=3", "g(1)=2"], "f(-1)", 1),
        ("f(x)=p*g(x)+2", ["f(1)=3", "f(-1)=0"], "p", sp.S.EmptySet),
        ("f(x)=p*g(x)+2", ["f(1)=2"], "g(1)", None),
        ("f(x)=p*g(x)+2", ["g(1)=3"], "f(-1)", None),
        ("f(x)=p*g(x)+2", ["f(1)=sqrt(2)+2", "g(1)=1"], "f(-1)", 2 - sp.sqrt(2)),
        ("f(x)=(p+1)*f(x)+p*g(x)", [], "f(1)+f(-1)", None),
        ("f(x)=(p+1)*f(x)+p*g(x)", ["g(1)=3"], "p", sp.S.Reals),
        ("f(x)=0*g(x)+2", [], "f(1)+f(-1)", 4),
    ],
)
def test_affine_parameter_roles_and_both_zero_coefficients(
    definition, extra, target, expected
):
    d = describe(candidate(definition, ["Dom(g)=ℝ", "parity(g,odd)", *extra], target))
    model = math.solve(d)
    assert model["proof"]["value"] == expected
    assert math.verify(d, decode_value(encode_value(model)))
    bad = deepcopy(model)
    bad["proof"]["value"] = sp.Integer(12345)
    assert not math.verify(d, bad)


@pytest.mark.parametrize(
    "definition", ["g(x)=x*f(x)+2", "f(t)=t*g(t)+2", "g(x)=(x+1)*f(x)+2"]
)
def test_bound_input_is_not_a_coefficient_parameter(definition):
    c = build_context(candidate(definition), TARGET)
    d = math.describe(c["goal"], c["goal_ast"], TARGET, c["entries"])
    assert not d["structure_supported"] and d["reason"] == "shifted_odd.affine_required"
    with pytest.raises(ValueError, match="affine_required"):
        math.solve(d)


def test_input_coefficient_cannot_fall_through_to_a_solved_route(tmp_path):
    from tests.solver.test_graph_function_parity_recognition import recognize

    p = candidate(
        "g(x)=x*f(x)+2",
        ["Dom(g)=ℝ∖{0}", "parity(g,odd)", "f(1)=1"],
        "f(-1)",
        r"已知 $g(x)=x\cdot f(x)+2$ 为奇函数，定义域为 $\mathbb R\setminus\{0\}$，且 $f(1)=1$，求 $f(-1)$ 的值。",
    )
    _, r = recognize(p, tmp_path)
    assert r["goals"][0]["primary"] is None


@pytest.mark.parametrize(
    "domain,extra",
    [
        ("[-4,-3]∪[3,4]", []),
        ("(-∞,-1000)∪(1000,+∞)", []),
        ("{-11,11}", []),
        ("{-sqrt(2),sqrt(2)}", []),
        ("[-4,-3]∪[3,4]", ["f(a+8)=3"]),
    ],
)
def test_common_input_witness_comes_from_all_legal_preimages(domain, extra):
    d = describe(candidate("f(x)=3", ["Dom(f)=" + domain, "f(a)=3", *extra], "f(-a)"))
    m = math.solve(d)
    assert m["proof"]["value"] == 3 and math.verify(d, decode_value(encode_value(m)))
    bad = deepcopy(m)
    bad["existence"]["interval"] = [sp.S.Zero, sp.S.Zero]
    assert not math.verify(d, bad)


def test_disjoint_legal_preimages_are_not_separate_witnesses():
    d = describe(
        candidate("f(x)=3", ["Dom(f)=[-4,-3]∪[3,4]", "f(a)=3", "f(a+20)=3"], "f(-a)")
    )
    with pytest.raises(ValueError, match="conditions_inconsistent"):
        math.solve(d)


def test_root_isolation_refines_inside_a_narrow_legal_domain():
    d = describe(
        candidate(
            "f(x)=x^3+2", ["Dom(f)=[-125993/100000,125993/100000]", "f(a)=4"], "f(-a)"
        )
    )
    m = math.solve(d)
    assert m["proof"]["value"] == 0 and math.verify(d, m)


def test_new_parameter_and_domain_proofs_verify_without_producers(monkeypatch):
    samples = [
        candidate("f(x)=p*g(x)+2", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=2"], "g(1)"),
        candidate("f(x)=3", ["Dom(f)={-sqrt(2),sqrt(2)}", "f(a)=3"], "f(-a)"),
    ]
    pairs = [(describe(p), math.solve(describe(p))) for p in samples]

    def forbidden(*args, **kwargs):
        pytest.fail("verification invoked production solving")

    monkeypatch.setattr(math, "solve", forbidden)
    monkeypatch.setattr(math, "compatibility", forbidden)
    monkeypatch.setattr(math.symmetry_linear, "certificate", forbidden)
    for d, model in pairs:
        assert math.verify(d, model)
        bad = deepcopy(model)
        if "parameter" in bad:
            bad["parameter"]["cases"] = []
        else:
            bad["existence"]["interval"] = [sp.S.Zero, sp.S.Zero]
        assert not math.verify(d, bad)


@pytest.mark.parametrize(
    "clause",
    [
        r"且 $f(x)$ 也是奇函数，",
        r"且 $f(x)$ 是偶函数，",
        r"且 $f(x)$ 为非奇非偶函数，",
        r"且奇函数 $f(x)$ 满足以下条件，",
    ],
)
def test_omitted_prose_properties_cannot_pass_source_binding(clause, tmp_path):
    from tests.solver.test_graph_function_parity_recognition import recognize

    p = originals()[1]
    p["original_text"] = p["original_text"].replace("求 ", clause + "求 ")
    _, r = recognize(p, tmp_path)
    assert r["goals"][0]["primary"] is None


@pytest.mark.parametrize(
    "text",
    [
        r"已知 $f(x)$、$g(x)$ 均为奇函数，$f(x)=g(x)+1$，且 $f(-2)=3$，求 $f(2)$ 的值。",
        r"已知 $g(x)$ 为奇函数，$f(x)=g(x)+1$ 也是奇函数，且 $f(-2)=3$，求 $f(2)$ 的值。",
        r"已知 $g(x)$ 为非奇函数，$f(x)=g(x)+1$，且 $f(-2)=3$，求 $f(2)$ 的值。",
    ],
)
def test_extra_or_negated_properties_are_not_function_introductions(text, tmp_path):
    from tests.solver.test_graph_function_parity_recognition import recognize

    p = originals()[1]
    p["original_text"] = text
    _, r = recognize(p, tmp_path)
    assert r["goals"][0]["primary"] is None


def course_cases():
    scaled = candidate(
        "f(x)=p*g(x)+2",
        ["Dom(g)=ℝ", "parity(g,odd)"],
        "f(1)+f(-1)",
        r"已知 $g(x)$ 是 $\mathbb R$ 上的奇函数，$f(x)=p g(x)+2$，其中 $p$ 为实常数，求 $f(1)+f(-1)$ 的值。",
    )
    constant = candidate(
        "f(x)=3",
        ["Dom(f)=[-4,-3]∪[3,4]", "f(a)=3"],
        "f(-a)",
        r"已知函数 $f(x)=3$，定义域为 $[-4,-3]\cup[3,4]$，且 $f(a)=3$，求 $f(-a)$ 的值。",
    )
    prefixed = originals()[1]
    prefixed["original_text"] = prefixed["original_text"].replace(
        "$g(x)$ 为奇函数", "奇函数 $g(x)$"
    )
    free_zero = candidate(
        "f(x)=p*g(x)+2",
        ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=2"],
        "g(1)",
        r"已知 $g(x)$ 是 $\mathbb R$ 上的奇函数，$f(x)=p g(x)+2$，其中 $p$ 为实常数，且 $f(1)=2$，求 $g(1)$ 的值。",
    )
    return [(scaled, "4"), (constant, "3"), (prefixed, "-1"), (free_zero, None)]


@pytest.mark.stage_three_db
@pytest.mark.parametrize(
    "p,expected",
    course_cases(),
    ids=["odd-scale", "legal-domain", "prefix-property", "zero-coefficient"],
)
def test_generalized_recognition_course_and_resume(p, expected, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_function_parity_recognition import recognize
    from tools.export_graph_walk_course import export_course

    _, recognized = recognize(p, tmp_path)
    assert recognized["goals"][0]["primary"] == TYPE
    path = tmp_path / "execution"
    goal = runner.run_sample(tmp_path / "stage-two/stage-two-result.json", path)[
        "goals"
    ][0]
    assert goal["status"] == "solved"
    if expected is None:
        assert goal["answer"]["status"] == "insufficient_information"
    else:
        assert goal["answer"]["value"]["expression"] == expected
    assert runner.resume_sample(path)["goals"][0]["answer"] == goal["answer"]
    assert (
        export_course(path, "test-t6-generalized")["stream"]["handoffs"][0]["answer"]
        == goal["answer"]
    )
