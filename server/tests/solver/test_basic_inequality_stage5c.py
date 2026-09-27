"""q30 executes parameter AM-GM, square completion and joint attainment."""

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
    close_bound,
    public_bound,
    verify_bound,
)
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.math_kernel.quadratic_bound import verify_quadratic
from tools.run_basic_inequality_stage4a import run

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("complete_relations", [False, True])
def test_q30_consumes_mixed_bound_chain(tmp_path, complete_relations):
    plan = FIXTURES / "basic-inequality-stage5c/q30.json"
    if complete_relations:
        payload = json.loads(plan.read_text())
        rewrite = payload["root_scope"]["goals"][0]["steps"][0]
        before, after = rewrite["parameters"]["steps"]
        rewrite["parameters"]["steps"] = [{"math": before["math"] + "=" + after["math"]}]
        plan = tmp_path / "relations.json"
        plan.write_text(json.dumps(payload))
    result, runtime = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q30.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
        plan=plan,
        output=tmp_path / "q30",
        mode="recorded",
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"minimum": "4"}}
    execution = (
        runtime.last_success_artifacts.verified_functional_execution.to_payload()
    )
    graph = execution["dependency_graph"]
    for producer, consumer in [
        ("rewrite", "first"),
        ("first", "square"),
        ("square", "last"),
        ("last", "attain"),
    ]:
        assert producer in graph[consumer]


def rows(*values):
    return [{"math": value} for value in values]


def target(expression, conditions, symbols):
    return {
        "type": "extremum_target",
        "goal_kind": "find_minimum",
        "scope_id": "problem",
        "scalar_symbols": symbols,
        "target_math": expression,
        "source_conditions": [
            {"handle": f"c{i}", "source_path": f"/facts/{i}", "math": c}
            for i, c in enumerate(conditions)
        ],
    }


def mixed_case(a="a", b="b", c="c", k=5):
    rest = f"2*{a}^2-{2 * k}*{a}*{c}+{k * k}*{c}^2"
    t = target(
        rest + f"+1/({b}*({a}-{b}))", [f"{a}>{b}", f"{b}>{c}", f"{c}>0"], [a, b, c]
    )
    first = public_bound(
        verify_bound(
            t,
            rows(
                f"{b}>0",
                f"{a}-{b}>0",
                f"{b}*({a}-{b})<={a}^2/4",
                f"1/({b}*({a}-{b}))>=4/{a}^2",
                t["target_math"] + f">={rest}+4/{a}^2",
            ),
        )
    )
    square = public_bound(
        verify_quadratic(
            t,
            rows(
                f"{rest}+4/{a}^2=({a}-{k}*{c})^2+{a}^2+4/{a}^2",
                f"({a}-{k}*{c})^2+{a}^2+4/{a}^2>={a}^2+4/{a}^2",
            ),
            variable=c,
            previous_bound=first,
        )
    )
    last = public_bound(
        verify_bound(t, rows(f"{a}^2+4/{a}^2>=4"), previous_bound=square)
    )
    return t, first, square, last


@pytest.mark.parametrize(
    "names,k", [(("a", "b", "c"), 5), (("x", "y", "z"), 3), (("p", "q", "r"), 7)]
)
def test_mixed_chain_generalizes(names, k):
    t, _first, _square, last = mixed_case(*names, k)
    assert [a.get("kind", "amgm") for a in last["applications"]] == [
        "amgm",
        "quadratic",
        "amgm",
    ]
    assert len(last["equalities"]) == 3
    a, b, c = names
    assert (
        close_bound(
            t, last, rows(f"{a}=sqrt(2)", f"{b}=sqrt(2)/2", f"{c}=sqrt(2)/{k}")
        )[0]
        == 4
    )


def test_mixed_certificates_replay_without_search(monkeypatch):
    t, _, _, last = mixed_case()

    def no_search(*args, **kwargs):
        raise AssertionError("certificate replay must not search")

    from shuxueshuo_server.solver.math_kernel import inequality_bound_v2, proof_kernel

    monkeypatch.setattr(proof_kernel, "_run_request", no_search)
    monkeypatch.setattr(inequality_bound_v2, "_run_request", no_search)
    assert public_bound(replay_bound(t, json.loads(json.dumps(last)))) == last


@pytest.mark.parametrize(
    "mutation",
    ["target", "scope", "direction", "equality", "coefficient", "certificate"],
)
def test_mixed_predecessor_tampering_rejected(mutation):
    t, _, square, _ = mixed_case()
    if mutation == "target":
        t["target_math"] += "+1"
    if mutation == "scope":
        t["scope_id"] = "other"
    if mutation == "direction":
        square["direction"] = "<="
    if mutation == "equality":
        square["equalities"].pop(0)
    if mutation == "coefficient":
        square["coefficient"] = "-25"
    if mutation == "certificate":
        square["certificate_bundle"]["proofs"].pop()
    with pytest.raises(ProofFailure):
        verify_bound(t, rows("a^2+4/a^2>=4"), previous_bound=square)


@pytest.mark.parametrize(
    "coefficient,conditions,valid",
    [("t", ["t>0"], True), ("t", ["t>=0"], False), ("-1", ["z>0"], False)],
)
def test_quadratic_parameter_coefficient_requires_strict_positivity(
    coefficient, conditions, valid
):
    expr = f"({coefficient})*(z-h)^2+5"
    t = target(expr, conditions, ["t", "z", "h"])
    call = lambda: verify_quadratic(
        t, rows(expr + "=" + expr, expr + ">=5"), variable="z"
    )
    if valid:
        result = public_bound(call())
        assert close_bound(t, result, rows("t=2", "z=3", "h=3"))[0] == 5
    else:
        with pytest.raises(ProofFailure):
            call()


@pytest.mark.parametrize(
    "mutation", ["identity", "remainder", "direction", "variable", "domain"]
)
def test_invalid_quadratic_rejected(mutation):
    t = target("z^2-2*z+3", ["z>0"], ["z"])
    chain = rows("z^2-2*z+3=(z-1)^2+2", "(z-1)^2+2>=2")
    variable = "z"
    if mutation == "identity":
        chain[0]["math"] = "z^2-2*z+3=(z-2)^2+2"
    if mutation == "remainder":
        chain[-1]["math"] = "(z-1)^2+2>=3"
    if mutation == "direction":
        chain[-1]["math"] = "(z-1)^2+2<=2"
    if mutation == "variable":
        variable = "u"
    if mutation == "domain":
        t = target("z^2-2*z+3+0/(z-1)", ["z>0"], ["z"])
    with pytest.raises(ProofFailure):
        verify_quadratic(t, chain, variable=variable)


def test_incompatible_attainment_does_not_close():
    # Both segments are valid: AM-GM requires x=1, square completion x=2.
    # Their accumulated lower bound 2 is therefore not an attained minimum.
    t = target("x+1/x+(x-2)^2", ["x>0"], ["x"])
    first = public_bound(verify_bound(t, rows(
        "x+1/x>=2", "x+1/x+(x-2)^2>=2+(x-2)^2",
    )))
    final = public_bound(verify_quadratic(
        t, rows("2+(x-2)^2=(x-2)^2+2", "(x-2)^2+2>=2"),
        variable="x", previous_bound=first,
    ))
    assert len(final["equalities"]) == 2
    replay_bound(t, final)
    for witness in ("x=1", "x=2"):
        with pytest.raises(ProofFailure):
            close_bound(t, final, rows(witness))


def test_local_reciprocal_rejects_missing_positivity_and_wrong_direction():
    t = target("1/(u*v)", ["u+v=2"], ["u", "v"])
    with pytest.raises(ProofFailure):
        verify_bound(t, rows("u*v<=1", "1/(u*v)>=1"))
    t["source_conditions"] += [
        {"handle": "u", "source_path": "/facts/1", "math": "u>0"},
        {"handle": "v", "source_path": "/facts/2", "math": "v>0"},
    ]
    with pytest.raises(ProofFailure):
        verify_bound(t, rows("u*v<=1", "1/(u*v)<=1"))


@pytest.mark.parametrize("a,b,c,k", [("a", "b", "c", 1), ("p", "q", "r", 3)])
def test_reciprocal_bound_with_full_product_identity_within_default_budget(a,b,c,k):
    source = f"{a}^2+({a}-5*{c})^2+{k}/({b}*({a}-{b}))"
    t = target(source, [f"{a}>{b}", f"{b}>{c}", f"{c}>0"], [a,b,c])
    evidence = public_bound(verify_bound(t, rows(
        f"∵ {a}>{b},{b}>{c},{c}>0；∴ {b}>0,{a}-{b}>0",
        f"{b}*({a}-{b})<=({b}+({a}-{b}))^2/4={a}^2/4",
        f"1/({b}*({a}-{b}))>=4/{a}^2",
        f"{source}>={a}^2+({a}-5*{c})^2+{4*k}/{a}^2",
    )))
    replay_bound(t, evidence)


@pytest.mark.parametrize("complete_relations", [False, True])
def test_q30_seven_steps_and_semantic_visuals(tmp_path, complete_relations):
    from tools.run_basic_inequality_stage4b import build

    output = tmp_path / "page"
    plan = None
    if complete_relations:
        payload = json.loads((FIXTURES / "basic-inequality-stage5c/q30.json").read_text())
        rewrite = payload["root_scope"]["goals"][0]["steps"][0]
        before, after = rewrite["parameters"]["steps"]
        rewrite["parameters"]["steps"] = [{"math": before["math"] + "=" + after["math"]}]
        plan = tmp_path / "relations.json"
        plan.write_text(json.dumps(payload))
    build(case="q30", output=output, plan=plan)
    lesson = json.loads((output / "lesson-ir.json").read_text())
    steps = lesson["root_scope"]["goals"]["problem.minimum"]["steps"]
    assert len(steps) == 7
    assert all(s["section_label"] == "基本不等式与配方" for s in steps)
    audit = json.loads((output / "visual-binding-audit.json").read_text())
    assert audit["gaps"] == []
    diagrams = [d for s in audit["steps"] for d in s["diagrams"]]
    assert any(d["spec_id"] == "basic_inequality.quadratic" for d in diagrams)
    assert any(d["spec_id"] == "basic_inequality.local_reciprocal" for d in diagrams)
    assert steps[2]["teaching_unit_keys"] == ["local_reciprocal_transform"]
    assert steps[3]["teaching_unit_keys"] == ["amgm_apply"]
    assert steps[2]["source_step_ids"] == steps[3]["source_step_ids"] == ["first"]
    transform_text = json.dumps(steps[2]["derive"], ensure_ascii=False)
    assert "分母" in transform_text and "其余项保持不变" in transform_text
    assert "4}" not in transform_text  # no computed bound before applying AM-GM
    by_spec = {d["spec_id"]: d["data"] for d in diagrams}
    merge = by_spec["expression_rewrite.fraction_merge"]["organization"]["expressionFlow"]
    assert [r["relation"] for r in merge] == ["", "="]
    assert all(any(p.get("highlight") for p in r["parts"]) for r in merge)
    assert all("c" in "".join(p["expression"] for p in r["parts"]) for r in merge)
    mapping = by_spec["basic_inequality.local_reciprocal"]
    assert mapping["kind"] == "basic-inequality-mapping"
    assert mapping["formulaStyle"] == "sum-geometric"
    assert mapping["sumNote"] == r"定和 \(a\)"
    assert [m["shape"] for m in mapping["mappings"]] == ["square", "circle"]
    assert [m["value"] for m in mapping["mappings"]] == [r"\(b\)", r"\(a-b\)"]
    application = mapping["expressionFlow"]
    assert len(application) == 2 and all(not row["label"] for row in application)
    for spec in ("expression_rewrite.fraction_merge", "basic_inequality.local_reciprocal_transform", "basic_inequality.local_reciprocal", "basic_inequality.quadratic"):
        assert "caption" not in by_spec[spec]
    items = by_spec["basic_inequality.equality"]["conceptEqualityItems"]
    assert [item["kind"] for item in items] == ["amgm", "quadratic", "amgm"]
    assert [items[0]["first"], items[0]["second"]] == [m["value"] for m in mapping["mappings"]]
    assert "=0" in items[1]["expression"] and "c" in items[1]["expression"]

    assert application[-1]["relation"] == "≥"
    assert "b" not in "".join(p["expression"] for p in application[-1]["parts"])
    assert all("c" in "".join(p["expression"] for p in r["parts"]) for r in application[-2:])
    square = by_spec["basic_inequality.quadratic"]["organization"]["expressionFlow"]
    assert [r["relation"] for r in square] == ["", "=", "≥"]
    assert any(p.get("highlight") and "c" in p["expression"] for p in square[1]["parts"])
    overview = diagrams[0]["data"]["organization"]
    assert overview["relationCountHint"]["result"]["value"] == "3"
    assert set(overview) == {"label", "relationCountHint"}
    assert diagrams[0]["data"]["showFocus"] is False
    assert diagrams[0]["data"]["showRoute"] is False
    assert steps[0]["title"] == "观察结构：规划取等关系"
    first_text = json.dumps(steps[0]["derive"], ensure_ascii=False)
    assert "可考虑补充 3 条取等关系" in first_text
    assert all(word in first_text for word in ("基本不等式", "平方非负", "一元二次", "联立"))
    assert all(word not in first_text for word in ("消去 b", "消去 c", "frac", "≥"))
    draft = json.loads((output / "rule-draft.json").read_text())
    overview_material = draft["root_scope"]["goals"]["problem.minimum"][0]["materials"][0]
    material_text = json.dumps(overview_material, ensure_ascii=False)
    assert "规划取等关系" in material_text
    assert all(word not in material_text for word in ("消去 b", "消去 c", "frac", "≥"))



def test_alternate_q30_page_preserves_local_remainder_and_method_order(tmp_path):
    from tools.run_basic_inequality_stage4b import build

    plan = json.loads((FIXTURES / "basic-inequality-stage5c/q30.json").read_text())
    rewrite, first, square, last, attain = plan["root_scope"]["goals"][0]["steps"]
    rewrite["parameters"]["steps"] += rows("a^2+(a-5*c)^2+1/(b*(a-b))")
    first["parameters"]["steps"][-1]["math"] = (
        "a^2+(a-5*c)^2+1/(b*(a-b))>=a^2+(a-5*c)^2+4/a^2"
    )
    last["args"]["previous_bound"]["step_id"] = "first"
    last["parameters"]["steps"] = rows(
        "a^2+4/a^2>=4", "a^2+(a-5*c)^2+4/a^2>=4+(a-5*c)^2",
    )
    square["args"]["previous_bound"]["step_id"] = "last"
    square["parameters"]["steps"] = rows(
        "4+(a-5*c)^2=25*(c-a/5)^2+4", "25*(c-a/5)^2+4>=4",
    )
    attain["args"]["bound"]["step_id"] = "square"
    plan["root_scope"]["goals"][0]["steps"] = [rewrite, first, last, square, attain]
    path = tmp_path / "alternate.json"
    path.write_text(json.dumps(plan))
    output = tmp_path / "page"
    build(case="q30", plan=path, output=output)
    lesson = json.loads((output / "lesson-ir.json").read_text())
    steps = lesson["root_scope"]["goals"]["problem.minimum"]["steps"]
    assert len(steps) == 7
    assert steps[0]["title"] == "观察结构：规划取等关系"
    assert steps[4]["source_step_ids"] == ["last"]
    assert steps[4]["title"] == "应用基本不等式求局部下界"
    assert steps[5]["source_step_ids"] == ["square"]
    assert steps[5]["title"] == "利用平方非负取极值"
    audit = json.loads((output / "visual-binding-audit.json").read_text())
    assert audit["gaps"] == []
    diagrams = [d for s in audit["steps"] for d in s["diagrams"]]
    overview = diagrams[0]["data"]
    assert set(overview["organization"]) == {"label", "relationCountHint"}
    assert overview["organization"]["relationCountHint"]["result"]["value"] == "3"
    mapping = next(d["data"] for d in diagrams
                   if d["source_step_ids"] == ["last"])
    assert mapping["productNote"] == r"定积 \(4\)"
    before, after = mapping["expressionFlow"]
    assert before["parts"][1] == after["parts"][1]
    assert "c" in after["parts"][1]["expression"]
    assert after["parts"][0] == {"expression": "4", "highlight": True}
    assert after["relation"] == "≥"
    equality = next(d["data"] for d in diagrams
                    if d["spec_id"] == "basic_inequality.equality")
    assert [item["kind"] for item in equality["conceptEqualityItems"]] == [
        "amgm", "amgm", "quadratic",
    ]
    assert (output / "lesson.html").is_file()


def test_m12_consumes_exact_m01_state_version(tmp_path):
    plan = json.loads((FIXTURES / "basic-inequality-stage5c/q30.json").read_text())
    rewrite, first, square, last, attain = plan["root_scope"]["goals"][0]["steps"]
    square["args"].pop("previous_bound")
    square["args"]["expression"] = "target_expression"
    square["parameters"]["steps"] = rows(
        "2*a^2+1/(b*(a-b))-10*a*c+25*c^2=(a-5*c)^2+a^2+1/(b*(a-b))",
        "(a-5*c)^2+a^2+1/(b*(a-b))>=a^2+1/(b*(a-b))",
    )
    first["args"].pop("expression")
    first["args"]["previous_bound"] = {"step_id": "square", "return": "bound"}
    first["parameters"]["steps"][-1]["math"] = "a^2+1/(b*(a-b))>=a^2+4/a^2"
    last["args"]["previous_bound"] = {"step_id": "first", "return": "bound"}
    plan["root_scope"]["goals"][0]["steps"] = [rewrite, square, first, last, attain]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    result, _ = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q30.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
        plan=path,
        output=tmp_path / "runtime",
        mode="recorded",
    )
    assert result.status == "ok", result.to_dict()


def test_one_amgm_cannot_discard_an_independent_square():
    t = target("(a-5*c)^2+a^2+4/a^2", ["a>0", "c>0"], ["a", "c"])
    with pytest.raises(ProofFailure):
        verify_bound(t, rows("(a-5*c)^2>=0", "a^2+4/a^2>=4", t["target_math"] + ">=4"))


def test_local_reciprocal_positive_parameter_preserves_remainder():
    t = target("z+k/(u*v)", ["u>0", "v>0", "k>0"], ["u", "v", "k", "z"])
    derivation = rows(
        "u*v<=(u+v)^2/4",
        "1/(u*v)>=4/(u+v)^2",
        "k/(u*v)>=4*k/(u+v)^2",
        "z+k/(u*v)>=z+4*k/(u+v)^2",
    )
    bound = public_bound(verify_bound(t, derivation))
    assert bound["bound"] == "z+4*k/(u+v)^2"
    replay_bound(t, bound)
    t["source_conditions"] = t["source_conditions"][:2]
    with pytest.raises(ProofFailure):
        verify_bound(t, derivation)


@pytest.mark.parametrize("x,y,k,root", [("a", "c", 5, 2), ("p", "q", 3, 3), ("u", "v", 7, 4)])
def test_local_amgm_preserves_square_despite_unparseable_internal_candidate(x, y, k, root):
    # The reciprocal candidate generated from the expanded remainder contains
    # (x^2 + root^2/x^2)^2. It must not block this ordinary sum AM-GM.
    pair = f"{x}^2+{root**2}/{x}^2"
    square = f"({x}-{k}*{y})^2"
    source = f"{x}^2+{square}+{root**2}/{x}^2"
    t = target(source, [f"{x}>0"], [x, y])
    evidence = public_bound(verify_bound(t, rows(
        f"{pair}>=2*sqrt({x}^2*{root**2}/{x}^2)",
        f"2*sqrt({x}^2*{root**2}/{x}^2)={2*root}",
        f"{source}>={2*root}+{square}",
    )))
    assert evidence["bound"] == f"{2*root}+{square}"
    replay_bound(t, evidence)
    evidence["certificate_bundle"]["local_application"]["relations"][0] = "0=1"
    with pytest.raises(ProofFailure):
        replay_bound(t, evidence)


def test_user_submitted_nested_power_still_rejected():
    from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError

    t = target("x^2+4/x^2", ["x>0"], ["x"])
    with pytest.raises(MathParseError, match="嵌套幂"):
        verify_bound(t, rows("(x^2+4/x^2)^2>=16", "x^2+4/x^2>=4"))
