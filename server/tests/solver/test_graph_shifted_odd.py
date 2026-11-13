"""T6 original sources and mechanism boundaries, without model calls."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import shifted_odd_math as math
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

TARGET = "/root/goals/0"
TYPE = "type-shifted-odd-application"


def candidate(definition="g(x)=f(x)+2", facts=None, expression="f(-1)", text=None):
    return {
        "original_text": text
        or r"已知 $g(x)=f(x)+2$ 是 $\mathbb R$ 上的奇函数，且 $f(1)=9$，求 $f(-1)$ 的值。",
        "root": {
            "definitions": [definition],
            "facts": facts
            if facts is not None
            else ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=9"],
            "goals": [{"kind": "find_value", "expression": expression}],
        },
    }


def originals():
    return [
        candidate(),
        candidate(
            "f(x)=g(x)+1",
            ["parity(g,odd)", "f(-2)=3"],
            "f(2)",
            r"已知 $g(x)$ 为奇函数，$f(x)=g(x)+1$，且 $f(-2)=3$，求 $f(2)$ 的值。",
        ),
        candidate(
            "f(x)=a*x+b/x-2",
            [],
            "f(2024)+f(-2024)",
            r"已知 $f(x)=ax+\frac{b}{x}-2$，求 $f(2024)+f(-2024)$ 的值。",
        ),
        candidate(
            "f(x)=(2024*x^3+2*x^2+3*x+6)/(x^2+3)",
            ["f(a)=14"],
            "f(-a)",
            r"已知函数 $f(x)=\frac{2024x^3+2x^2+3x+6}{x^2+3}$，且 $f(a)=14$，求 $f(-a)$ 的值。",
        ),
        candidate(
            "f(x)=((x+1)^2+a*x^5)/(x^2+1)",
            ["Dom(f)=[-1,1]", "M=max(f(x))", "m=min(f(x))"],
            "M+m",
            r"当 $x\in[-1,1]$ 时，函数 $f(x)=\frac{(x+1)^2+ax^5}{x^2+1}$ 的最大值为 $M$，最小值为 $m$，其中 $a$ 为常数，求 $M+m$ 的值。",
        ),
    ]


def describe(p):
    c = build_context(p, TARGET)
    d = math.describe(c["goal"], c["goal_ast"], TARGET, c["entries"])
    assert d and d["structure_supported"], d
    return d


@pytest.mark.parametrize(
    "p,answer",
    zip(originals(), [-13, -1, -4, -10, 2]),
    ids=["A16", "B01", "B02", "B03", "B04"],
)
def test_original_math_and_frozen_verification(p, answer):
    d = describe(p)
    m = math.solve(d)
    assert m["proof"]["value"] == answer
    assert math.verify(d, m)
    assert math.verify(d, decode_value(encode_value(m)))
    bad = deepcopy(m)
    bad["proof"]["value"] += 1
    assert not math.verify(d, bad)
    if answer == -1:
        assert m["domain"] is None
    if answer == -4:
        assert m["domain"] == sp.S.Reals - sp.FiniteSet(0)


@pytest.mark.parametrize(
    "p,answer",
    zip(originals(), ["-13", "-1", "-4", "-10", "2"]),
    ids=["A16", "B01", "B02", "B03", "B04"],
)
@pytest.mark.stage_three_db
def test_original_recognition_execution_and_resume(p, answer, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_function_parity_recognition import recognize
    from tools.export_graph_walk_course import export_course

    _prepared, recognized = recognize(p, tmp_path)
    (g,) = recognized["goals"]
    assert g["primary"] == TYPE and g["supported"] == [TYPE], g
    assert g["d1"]["fragments"] and not g["d1"]["diagnostics"]
    path = tmp_path / "execution"
    (goal,) = runner.run_sample(tmp_path / "stage-two/stage-two-result.json", path)[
        "goals"
    ]
    assert goal["status"] == "solved", goal
    assert goal["answer"]["value"]["expression"] == answer
    assert runner.resume_sample(path)["goals"][0]["answer"] == goal["answer"]
    evidence = export_course(path, "test-t6")
    assert evidence["stream"]["handoffs"][0]["answer"] == goal["answer"]


@pytest.mark.parametrize(
    "definition,facts,target,answer",
    [
        ("g(x)=-2*f(x)+6", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=5"], "f(-1)", 1),
        (
            "g(x)=f(x)+2",
            ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=sqrt(2)"],
            "f(-1)",
            -4 - sp.sqrt(2),
        ),
        ("g(x)=f(x)", ["Dom(g)=ℝ", "parity(g,odd)"], "f(-2)+f(2)", 0),
        ("g(x)=0*f(x)", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=5"], "f(1)", 5),
        ("g(x)=0*f(x)", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=5"], "f(-1)", None),
        ("g(x)=f(x)+2", ["Dom(g)={0}", "parity(g,odd)"], "f(0)", -2),
        ("f(x)=x^2+3", ["Dom(f)={-1,1}"], "f(-1)+f(1)", 8),
        ("f(x)=abs(x+1)-abs(x-1)+3", [], "f(-2)+f(2)", 6),
        ("f(x)=piecewise(x+2,x<0,x+2,x>=0)", [], "f(-2)+f(2)", 4),
        ("f(x)=0/x+3", [], "f(-2)+f(2)", 6),
        ("g(x)=f(x)-3", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=5"], "f(-1)+f(1)+f(1)", 11),
        ("g(x)=f(x)-3", ["Dom(g)=ℝ", "parity(g,odd)"], "f(-1)+f(1)+f(1)", None),
        ("g(x)=f(x)-3", ["Dom(g)=ℝ", "parity(g,odd)"], "2*f(-1)+2*f(1)", 12),
        ("g(x)=f(x)+k", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=9", "f(-1)=-13"], "k", 2),
        ("g(x)=p*f(x)+2", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=3", "f(-1)=1"], "p", -1),
        ("g(x)=p*f(x)", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=1", "f(-1)=1"], "p", 0),
        (
            "g(x)=p*f(x)+2",
            ["Dom(g)=ℝ", "parity(g,odd)"],
            "p",
            sp.S.Reals - sp.FiniteSet(0),
        ),
        ("g(x)=p*f(x)", ["Dom(g)=ℝ", "parity(g,odd)"], "p", sp.S.Reals),
        (
            "g(x)=p*f(x)+2",
            ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=3", "f(-1)=1"],
            "f(0)",
            2,
        ),
        ("g(x)=p*f(x)+2", ["Dom(g)=ℝ", "parity(g,odd)"], "f(0)", None),
        ("g(x)=p*f(x)", ["Dom(g)=ℝ", "parity(g,odd)"], "f(-1)+f(1)", None),
        ("g(x)=p*f(x)", ["Dom(g)=ℝ", "parity(g,odd)", "f(0)=0"], "f(0)", 0),
    ],
)
def test_mechanisms(definition, facts, target, answer):
    d = describe(candidate(definition, facts, target))
    m = math.solve(d)
    assert m["proof"]["value"] == answer
    assert math.verify(d, decode_value(encode_value(m)))


@pytest.mark.parametrize(
    "definition,facts,target",
    [
        ("g(x)=0*f(x)+1", ["Dom(g)=ℝ", "parity(g,odd)"], "f(1)"),
        ("g(x)=f(x)+2", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=9", "f(-1)=0"], "f(-1)"),
        ("f(x)=x/(x^2+1)+2", ["f(a)=14"], "f(-a)"),
        ("f(x)=x+2", ["f(a)=3", "f(2*a)=3"], "f(-a)"),
        ("f(x)=0/x+3", [], "f(0)+f(1)"),
        ("f(x)=x+1", ["Dom(f)=(-1,1)", "M=max(f(x))", "m=min(f(x))"], "M+m"),
    ],
)
def test_invalid_conditions_do_not_produce_values(definition, facts, target):
    with pytest.raises(ValueError):
        math.solve(describe(candidate(definition, facts, target)))


def test_coefficient_condition_is_a_capability_gap_not_a_contradiction():
    p = candidate("f(x)=a*x+2", ["f(1)=3"], "f(-1)+f(1)")
    with pytest.raises(ValueError, match="coefficient_conditions_unsupported"):
        math.solve(describe(p))


def test_extremum_symbols_cannot_overwrite_their_original_binding():
    p = originals()[4]
    p["root"]["facts"].append("M=min(f(x))")
    c = build_context(p, TARGET)
    d = math.describe(c["goal"], c["goal_ast"], TARGET, c["entries"])
    assert not d["structure_supported"]
    assert "conflicting_extrema" in d["reason"]


def test_verifier_does_not_call_producers(monkeypatch):
    from shuxueshuo_server.graph_lesson import (
        function_parity,
        shifted_odd_identity,
        symmetry_linear,
    )

    samples = [
        *originals(),
        candidate("g(x)=p*f(x)+2", ["Dom(g)=ℝ", "parity(g,odd)"], "f(0)"),
        candidate(
            "g(x)=p*f(x)+2", ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=3", "f(-1)=1"], "f(0)"
        ),
    ]
    pairs = [(describe(p), math.solve(describe(p))) for p in samples]

    def forbidden(*args, **kwargs):
        pytest.fail("verification invoked a producer")

    for module, names in [
        (math, ["solve", "identity", "compatibility"]),
        (shifted_odd_identity, ["identity", "compatibility"]),
        (symmetry_linear, ["certificate", "solve_linear"]),
        (function_parity, ["solve", "relation", "effective_domain"]),
    ]:
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    for d, m in pairs:
        assert math.verify(d, m)


def test_symbolic_input_certificate_is_source_bound():
    d = describe(originals()[3])
    m = math.solve(d)
    for key, new in [
        ("interval", [sp.Integer(20), sp.Integer(21)]),
        ("domain", sp.Interval(0, 1)),
        ("common_polynomial", sp.Symbol("r:scalar:a", real=True)),
    ]:
        bad = deepcopy(m)
        bad["existence"][key] = new
        assert not math.verify(d, bad)


@pytest.mark.parametrize(
    "scope,definition,answer",
    [
        ("(0,2)", "g(t)=f(t)+1", None),
        ("[-2,2]", "g(t)=f(t)+1", -4),
        ("(0,2)", "g(t)=0*f(t)+1", None),
    ],
)
def test_local_relation_only_applies_in_its_scope(scope, definition, answer):
    p = candidate(
        facts=[
            "Dom(f)=ℝ",
            "Dom(g)=ℝ",
            "parity(g,odd)",
            "∀t∈" + scope + ": " + definition,
            "f(1)=2",
        ]
    )
    p["root"]["definitions"] = []
    d = describe(p)
    m = math.solve(d)
    assert m["proof"]["value"] == answer
    assert math.verify(d, decode_value(encode_value(m)))


@pytest.mark.parametrize(
    "definition,expression,expected",
    [
        ("f(x)=x^2+3", "f(1)+f(-1)", False),
        ("f(x)=x+1", "f(1)+f(2)", False),
        ("f(x)=x+1", "f(1)+f(-1)", True),
        ("f(x)=x+1", "f(f(1))", False),
        ("f(x)=x+1", "f(1+f(1))", False),
        ("f(x)=piecewise(3*x,x>=3,-x^2+6*x,x<3)", "f(f(1))", False),
    ],
)
def test_explicit_sources_are_not_all_claimed_by_t6(definition, expression, expected):
    p = candidate(definition, [], expression)
    c = build_context(p, TARGET)
    assert math.owned(c["goal"], c["goal_ast"], c["entries"]) is expected


@pytest.mark.stage_three_db
def test_nested_evaluation_in_a_multi_goal_problem_keeps_its_original_route(tmp_path):
    import json

    from shuxueshuo_server.graph_lesson.stage_three import runner
    from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
    from tests.solver.test_graph_function_parity_recognition import recognize

    record = json.loads((ROOT / 'internal/senior-high/authored-courses/function-monotonicity-t3-20261106/b09.json').read_text())
    _, recognized = recognize(record['candidate'], tmp_path)
    assert [goal['primary'] for goal in recognized['goals']] == [
        'type-function-evaluation', 'type-monotonicity-inequality',
    ]
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', tmp_path / 'execution')
    assert all(goal['status'] == 'solved' for goal in result['goals'])
    assert result['goals'][0]['answer']['value']['expression'] == '15'


def test_paired_finite_sum_preserves_repetition_and_kind():
    p = candidate("f(x)=g(x)+3", ["Dom(g)=ℝ", "parity(g,odd)"])
    p["root"]["goals"] = [
        {
            "kind": "finite_sum",
            "terms": [
                {"expression": "2*f(k)+2*f(-k)", "index": "k", "lower": 1, "upper": 100}
            ],
        }
    ]
    d = describe(p)
    m = math.solve(d)
    assert d["source"]["kind"] == "finite_sum"
    assert m["proof"]["value"] == 1200
    assert math.verify(d, decode_value(encode_value(m)))


def generalized_sources():
    local = candidate(
        facts=[
            "Dom(f)=ℝ",
            "Dom(g)=ℝ",
            "parity(g,odd)",
            "∀t∈(0,2): g(t)=f(t)+1",
            "f(1)=2",
        ],
        text=r"已知函数 $f(x)$、$g(x)$ 的定义域均为 $\mathbb R$，$g(x)$ 为奇函数，对任意 $t\in(0,2)$，有 $g(t)=f(t)+1$，且 $f(1)=2$，求 $f(-1)$ 的值。",
    )
    local["root"]["definitions"] = []
    param = candidate(
        "g(x)=p*f(x)+2",
        ["Dom(g)=ℝ", "parity(g,odd)", "f(1)=3", "f(-1)=1"],
        "p",
        r"已知 $g(x)=pf(x)+2$ 是 $\mathbb R$ 上的奇函数，且 $f(1)=3$、$f(-1)=1$，求 $p$ 的值。",
    )
    pair = candidate(
        "f(x)=g(x)+1",
        ["Dom(g)=ℝ", "parity(g,odd)"],
        "f(-1)+f(1)",
        r"已知 $g(x)$ 是 $\mathbb R$ 上的奇函数，$f(x)=g(x)+1$，求 $f(-1)+f(1)$ 的值。",
    )
    summed = deepcopy(pair)
    summed["root"]["goals"] = [
        {
            "kind": "finite_sum",
            "terms": [{"expression": "f(-1)"}, {"expression": "f(1)"}],
        }
    ]
    return [(local, None), (param, "-1"), (pair, "2"), (summed, "2")]


@pytest.mark.stage_three_db
@pytest.mark.parametrize(
    "p,answer",
    generalized_sources(),
    ids=["local", "parameter", "combination", "finite-sum"],
)
def test_generalized_courses(p, answer, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_function_parity_recognition import recognize

    _prepared, r = recognize(p, tmp_path)
    assert r["goals"][0]["primary"] == TYPE, r["goals"][0]
    (g,) = runner.run_sample(
        tmp_path / "stage-two/stage-two-result.json", tmp_path / "execution"
    )["goals"]
    assert g["status"] == "solved", g
    if answer is None:
        assert g["answer"]["status"] == "insufficient_information"
    else:
        assert g["answer"]["value"]["expression"] == answer
    assert g["answer"]["kind"] == p["root"]["goals"][0]["kind"]


@pytest.mark.parametrize(
    "fault", ["who_is_odd", "wrong_offset", "negation", "extra_condition"]
)
def test_source_edits_cannot_be_solved_with_an_old_candidate(fault, tmp_path):
    from tests.solver.test_graph_function_parity_recognition import recognize

    p = originals()[1]
    if fault == "who_is_odd":
        p["original_text"] = p["original_text"].replace(
            "$g(x)$ 为奇函数", "$f(x)$ 为奇函数"
        )
    elif fault == "wrong_offset":
        p["original_text"] = p["original_text"].replace("g(x)+1", "g(x)-1")
    elif fault == "negation":
        p["original_text"] = p["original_text"].replace("为奇函数", "不一定为奇函数")
    else:
        p["original_text"] = p["original_text"].replace("求 ", r"且 $f(0)=8$，求 ")
    _prepared, r = recognize(p, tmp_path)
    assert r["goals"][0]["primary"] is None


def test_unrecognized_execution_version_is_rejected():
    from shuxueshuo_server.graph_lesson.stage_three.symmetry_runtime import admitted

    c = build_context(originals()[0], TARGET)
    assert admitted(c)
    c["shifted_odd_goal"]["structure_version"] = "future-version"
    assert not admitted(c)
