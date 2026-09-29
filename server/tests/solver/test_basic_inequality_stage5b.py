"""M07 acceptance through real compilation, transactions, closure and lessons."""

import json
from pathlib import Path

import pytest
from tools.run_basic_inequality_stage4a import run
from tools.run_basic_inequality_stage5b import verified_method_dependencies

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("case,answer", [("q25", "25"), ("q12", "4/5")])
def test_substitution_closes_original_problem(case, answer, tmp_path):
    result, runtime = run(
        gold=FIXTURES / f"math-notation-v1/basic-inequality/{case}.json",
        problem_ir=FIXTURES / f"basic-inequality-problem-ir/v1/{case}/problem-ir.json",
        plan=FIXTURES / f"basic-inequality-stage5b/{case}.json",
        output=tmp_path / case,
        mode="recorded",
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"minimum": answer}}
    execution = (
        runtime.last_success_artifacts.verified_functional_execution.to_payload()
    )
    if case == "q12":
        assert "substitute" in execution["dependency_graph"]["eliminate"]
        assert "eliminate" in execution["dependency_graph"]["bound"]
        edges = {
            (e["producer"], e["consumer"])
            for e in verified_method_dependencies(execution)
        }
        assert edges == {
            ("substitute_expressions", "eliminate_by_constraint"),
            ("eliminate_by_constraint", "apply_two_term_amgm"),
            ("apply_two_term_amgm", "close_equality_and_restore"),
        }
    else:
        assert "substitute" in execution["dependency_graph"]["bound"]
    assert "substitution-teaching-evidence/v1" in json.dumps(execution)


from copy import deepcopy

from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonAuthoringPipeline,
    lesson_ir_from_payload,
)
from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError
from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
    close_bound,
    public_bound,
    verify_bound,
)
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.math_kernel.substitution import (
    replay_substitution,
    verify_substitution,
)
from shuxueshuo_server.solver.visual import VisualStepBuilder, VisualStepIRValidator
from shuxueshuo_server.solver.visual.models import visual_step_ir_from_payload


def affine_case(x="a", y="b", p=4, q=9):
    target = {
        "type": "extremum_target",
        "goal_kind": "find_minimum",
        "scope_id": "problem",
        "scalar_symbols": [x, y],
        "target_math": f"{p}*{x}/({x}-1)+{q}*{y}/({y}-1)",
        "source_conditions": [
            {"handle": f"c{i}", "source_path": f"/facts/{i}", "math": s}
            for i, s in enumerate([f"{x}>0", f"{y}>0", f"1/{x}+1/{y}=1"])
        ],
    }
    params = {
        "definitions": {"r": f"{x}-1", "s": f"{y}-1"},
        "steps": [
            {"math": s}
            for s in [
                f"{x}-1={x}/{y}",
                f"{y}-1={y}/{x}",
                f"r={x}/{y}",
                f"s={y}/{x}",
                "r>0",
                "s>0",
                "r*s=1",
            ]
        ],
        "expression": f"{p + q}+{p}/r+{q}/s",
    }
    return target, params


def square_case():
    return (
        {
            "type": "extremum_target",
            "goal_kind": "find_minimum",
            "scope_id": "problem",
            "scalar_symbols": ["x"],
            "target_math": "x^2",
            "source_conditions": [
                {"handle": "domain", "source_path": "/facts/0", "math": "x^2>=0"}
            ],
        },
        {"definitions": {"u": "x^2"}, "steps": [{"math": "u>=0"}], "expression": "u"},
    )


def test_affine_substitution_generalizes_and_replays_without_search(monkeypatch):
    t, p = affine_case("x", "y", 9, 16)
    e, _ = verify_substitution(t, p)
    bound = public_bound(
        verify_bound(t, [{"math": p["expression"] + ">=49"}], substitution=e)
    )
    assert close_bound(t, bound, [{"math": "x=7/4,y=7/3"}])[0] == 49
    from shuxueshuo_server.solver.math_kernel import (
        constraint_elimination,
        proof_kernel,
    )

    def no_search(*a, **kw):
        raise AssertionError("certificate replay searched")

    monkeypatch.setattr(proof_kernel, "_run_request", no_search)
    monkeypatch.setattr(constraint_elimination, "_run_request", no_search)
    replay_substitution(t, json.loads(json.dumps(e)))
    from shuxueshuo_server.solver.math_kernel import inequality_bound_v2

    monkeypatch.setattr(inequality_bound_v2, "_run_request", no_search)
    rebuilt = inequality_bound_v2.verify(
        t,
        [{"math": p["expression"] + ">=49"}],
        substitution=json.loads(json.dumps(e)),
        certificates=bound["certificate_bundle"],
    )
    assert public_bound(rebuilt) == bound


@pytest.mark.parametrize(
    "mutation",
    [
        "shadow",
        "unknown",
        "cycle",
        "shared_source",
        "wrong_target",
        "wrong_condition",
        "domain",
        "estimate",
        "unsupported",
    ],
)
def test_invalid_substitution_is_rejected(mutation):
    t, p = affine_case()
    if mutation == "shadow":
        p["definitions"] = {"a": "a-1", "s": "b-1"}
    if mutation == "unknown":
        p["definitions"]["r"] = "z-1"
    if mutation == "cycle":
        p["definitions"]["r"] = "s-1"
    if mutation == "shared_source":
        p["definitions"]["s"] = "a+1"
    if mutation == "wrong_target":
        p["expression"] = "a+b"
    if mutation == "wrong_condition":
        p["steps"].append({"math": "r*s=2"})
    if mutation == "domain":
        t["source_conditions"] = []
    if mutation == "estimate":
        p["steps"].append({"math": "r+s>=2*sqrt(r*s)"})
    if mutation == "unsupported":
        p["definitions"]["r"] = "a^3"
    with pytest.raises((ProofFailure, MathParseError)):
        verify_substitution(t, p)


@pytest.mark.parametrize(
    "mutation", ["scope", "target", "definition", "certificate", "branch", "condition"]
)
def test_substitution_tampering_cannot_be_consumed(mutation):
    t, p = affine_case()
    e, _ = verify_substitution(t, p)
    if mutation == "scope":
        t["scope_id"] = "other"
    if mutation == "target":
        t["target_math"] = "a+b"
    if mutation == "definition":
        e["definitions"]["r"] = "a+1"
    if mutation == "certificate":
        e["certificates"]["relations"][0]["ruleset_hash"] = "changed"
    if mutation == "branch":
        e["restoration_branches"][0]["a"] = "r-1"
    if mutation == "condition":
        e["relations"].pop()
    with pytest.raises(ProofFailure):
        verify_bound(t, [{"math": "13+4/r+9/s>=25"}], substitution=e)


def test_square_is_nonnegative_and_retains_both_inverse_signs():
    t, p = square_case()
    e, _ = verify_substitution(t, p)
    assert e["restoration_branches"] == [{"x": "sqrt(u)"}, {"x": "-sqrt(u)"}]
    bad = deepcopy(e)
    bad["restoration_branches"].pop()
    with pytest.raises(ProofFailure):
        replay_substitution(t, bad)
    p["steps"] = [{"math": "u>0"}]
    with pytest.raises(ProofFailure):
        verify_substitution(t, p)


def test_source_domain_is_checked_before_cancellation():
    t, p = square_case()
    p["definitions"] = {"u": "x^3/x"}
    with pytest.raises(ProofFailure):
        verify_substitution(t, p)


def test_substitution_budget_is_shared_and_finite():
    from shuxueshuo_server.solver.math_kernel.proof_kernel import ProofLimits, _Budget

    t, p = affine_case()
    with pytest.raises(ProofFailure) as exc:
        verify_substitution(t, p, budget=_Budget(ProofLimits(nodes=1)))
    assert exc.value.code == "proof_search_exhausted"


@pytest.mark.parametrize("failure", ["expression", "certificate"])
def test_failed_substitution_transaction_has_no_writes(tmp_path, monkeypatch, failure):
    plan = json.loads((FIXTURES / "basic-inequality-stage5b/q25.json").read_text())
    if failure == "expression":
        plan["root_scope"]["goals"][0]["steps"][0]["parameters"]["expression"] = "a+b"
    else:
        from shuxueshuo_server.solver.math_kernel import substitution

        original = substitution.verify_relation_sequence

        def corrupt_generated(*args, **kwargs):
            proofs = original(*args, **kwargs)
            if kwargs.get("certificates") is None:
                proofs = deepcopy(proofs)
                proofs[0]["ruleset_hash"] = "unreplayable"
            return proofs

        monkeypatch.setattr(substitution, "verify_relation_sequence", corrupt_generated)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    result, runtime = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q25.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q25/problem-ir.json",
        plan=path,
        output=tmp_path / "failed",
        mode="recorded",
    )
    assert result.status != "ok" and runtime.last_success_artifacts is None
    transactions = list((tmp_path / "failed").glob("*transaction.json"))
    assert transactions
    for path in transactions:
        data = json.loads(path.read_text())
        assert data["state_writes"] == [] and data["root_issues"]


@pytest.mark.parametrize("case", ["q25", "q12"])
def test_substitution_lesson_and_diagrams_roundtrip(case, tmp_path):
    result, runtime = run(
        gold=FIXTURES / f"math-notation-v1/basic-inequality/{case}.json",
        problem_ir=FIXTURES / f"basic-inequality-problem-ir/v1/{case}/problem-ir.json",
        plan=FIXTURES / f"basic-inequality-stage5b/{case}.json",
        output=tmp_path / case,
        mode="recorded",
    )
    assert result.status == "ok"
    snapshot = ExplanationSnapshotBuilder().build(runtime.last_success_artifacts)
    built = LessonAuthoringPipeline().build(snapshot)
    assert len(built.lesson.steps) == (6 if case == "q12" else 5)
    assert [s.title for s in built.lesson.steps[:2]] == ["观察原式结构", "整体换元"]
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=built.lesson)
    VisualStepIRValidator().validate(visual, lesson=built.lesson)
    assert not visual.metadata.get("visual_gaps")
    assert all(s.diagram_blocks for s in visual.steps)
    assert (
        lesson_ir_from_payload(
            json.loads(json.dumps(built.lesson.to_payload()))
        ).to_payload()
        == built.lesson.to_payload()
    )
    assert (
        visual_step_ir_from_payload(
            json.loads(json.dumps(visual.to_payload()))
        ).to_payload()
        == visual.to_payload()
    )
    assert "certificates" not in json.dumps(built.projection.plan.to_payload())
    application = next(
        s.diagram_blocks[0]["data"]
        for s in visual.steps
        if s.diagram_blocks[0]["data"]["kind"] == "basic-inequality-mapping"
    )
    assert application["stageLabel"] == "代入定积"
    if case == "q25":
        assert "36" in application["fixedCondition"]
        assert (
            len(
                visual.steps[0].diagram_blocks[0]["data"]["organization"][
                    "substitutionHint"
                ]["mappings"]
            )
            == 2
        )
    else:
        evidence = next(
            v
            for v in snapshot.evidence.values()
            if v.get("schema_version") == "substitution-teaching-evidence/v1"
        )
        assert len(evidence["data"]["restoration_branches"]) == 4
        assert evidence["data"]["result"] == "u+v"
        elimination = next(
            v
            for v in snapshot.evidence.values()
            if v.get("schema_version") == "elimination-teaching-evidence/v1"
        )
        assert elimination["step_id"] == "eliminate"
        assert elimination["data"]["after_substitution"]
        elimination_visual = visual.steps[2].diagram_blocks[0]["data"]
        comparisons = elimination_visual["organization"]["comparisons"]
        assert [row["label"] for row in comparisons] == ["条件", "目标"]
        assert comparisons[0]["before"] == r"\(5\cdot u\cdot v+v^{2}=1\)"
        assert comparisons[0]["after"] == r"\(" + elimination["data"]["restoration"] + r"\)"
        assert "motive" not in elimination_visual["organization"]
        assert "note" not in elimination_visual["organization"]
        assert elimination_visual["caption"] == "由条件表示并消去 u"
        assert built.lesson.steps[2].title == "条件消元"
        assert (
            visual.steps[1].diagram_blocks[0]["data"]["organization"]["comparisons"][1][
                "after"
            ]
            == r"\(u+v\)"
        )
        mappings = visual.steps[0].diagram_blocks[0]["data"]["organization"][
            "substitutionHint"
        ]["mappings"]
        assert [m["kind"] for m in mappings] == ["expression", "expression"]
        assert [m["source"] for m in mappings] == [r"\(x^{2}\)", r"\(y^{2}\)"]


def test_wrong_original_witness_is_not_fixed_by_new_variable_values():
    t, p = affine_case()
    e, _ = verify_substitution(t, p)
    bound = public_bound(verify_bound(t, [{"math": "13+4/r+9/s>=25"}], substitution=e))
    with pytest.raises(ProofFailure):
        close_bound(t, bound, [{"math": "a=2,b=2,r=2/3,s=3/2"}])
    with pytest.raises(ProofFailure):
        close_bound(t, bound, [{"math": "r=2/3,s=3/2"}])


def test_reciprocal_domain_derivation_and_long_restoration_are_replayable():
    t, p = affine_case()
    p["steps"] = [
        {"math": s}
        for s in [
            "a>0,b>0,1/a+1/b=1",
            "1/a<1,1/b<1",
            "a>1,b>1",
            "r=a-1,s=b-1",
            "r>0,s>0",
            "a+b=a*b",
            "a*b-a-b=0",
            "(a-1)*(b-1)=1",
            "r*s=1",
        ]
    ]
    e, _ = verify_substitution(t, p)
    replay_substitution(t, e)
    b = public_bound(verify_bound(t, [{"math": "13+4/r+9/s>=25"}], substitution=e))
    steps = [
        {"math": s}
        for s in [
            "9*r=4/r",
            "9*r^2=4",
            "r^2=4/9",
            "r>0",
            "r=2/3",
            "r*s=1",
            "s=3/2",
            "r=a-1,s=b-1",
            "a=5/3,b=5/2",
            "1/a+1/b=1",
            "4*a/(a-1)+9*b/(b-1)=25",
        ]
    ]
    assert close_bound(t, b, steps)[0] == 25


def test_reciprocal_sign_transport_still_requires_positive_denominators():
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import target_context
    from shuxueshuo_server.solver.math_kernel.proof_kernel import (
        verify_relation_sequence,
    )

    t, _ = affine_case()
    t["source_conditions"] = [
        {"handle": "c", "source_path": "/facts/0", "math": "1/a<1"}
    ]
    context, _ = target_context(t)
    with pytest.raises(ProofFailure):
        verify_relation_sequence([parse_math_relation("a>1", context.symbols)], context)


def test_new_condition_projection_deduplicates_without_losing_strict_signs():
    import sympy as sp
    from shuxueshuo_server.solver.runtime.substitution_teaching_evidence import (
        project_new_conditions,
    )

    symbols = {n: sp.Symbol(n, real=True) for n in ("u", "v")}
    rows = [
        "u>=0",
        "v>=0",
        "5*u*v+v^2=1",
        "v*(5*u+v)=1",
        "v!=0",
        "v>0",
        "u=(1-v^2)/(5*v)",
    ]
    assert project_new_conditions(rows, symbols, symbols) == [
        "u>=0",
        "5*u*v+v^2=1",
        "v>0",
    ]
    assert rows[-1] == "u=(1-v^2)/(5*v)"


def test_positive_outer_scaling_keeps_fixed_product_diagram(tmp_path):
    plan = json.loads((FIXTURES / "basic-inequality-stage5b/q12.json").read_text())
    steps = plan["root_scope"]["goals"][0]["steps"]
    steps[1]["parameters"]["expression"] = "(4*v+1/v)/5"
    steps[2]["parameters"]["steps"] = [
        {"math": "4*v+1/v>=4"},
        {"math": "(4*v+1/v)/5>=4/5"},
    ]
    path = tmp_path / "scaled.json"
    path.write_text(json.dumps(plan))
    result, runtime = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q12.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q12/problem-ir.json",
        plan=path,
        output=tmp_path / "scaled",
        mode="recorded",
    )
    assert result.status == "ok", result.to_dict()
    snapshot = ExplanationSnapshotBuilder().build(runtime.last_success_artifacts)
    built = LessonAuthoringPipeline().build(snapshot)
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=built.lesson)
    VisualStepIRValidator().validate(visual, lesson=built.lesson)
    application = next(
        s.diagram_blocks[0]["data"]
        for s in visual.steps
        if s.diagram_blocks[0]["data"]["kind"] == "basic-inequality-mapping"
    )
    assert application["stageLabel"] == "代入定积"
    assert "4" in application["fixedCondition"]
    assert r"\frac{1}{5}" in json.dumps(application, ensure_ascii=False).replace(
        "\\\\", "\\"
    )


def square_elimination_case():
    target = {
        "type": "extremum_target",
        "goal_kind": "find_minimum",
        "scope_id": "problem",
        "scalar_symbols": ["r", "s"],
        "target_math": "r^2+s^2",
        "source_conditions": [
            {"handle": "c", "source_path": "/facts/0", "math": "5*r^2*s^2+s^4=1"}
        ],
    }
    substitution = {
        "definitions": {"p": "r^2", "q": "s^2"},
        "expression": "p+q",
        "steps": [{"math": s} for s in ["p>=0", "q>=0", "5*p*q+q^2=1"]],
    }
    elimination = {
        "eliminate": "p",
        "expression": "(1/q+4*q)/5",
        "steps": [
            {"math": s} for s in ["q*(5*p+q)=1", "q!=0", "q>0", "p=(1-q^2)/(5*q)"]
        ],
    }
    return target, substitution, elimination


def test_substitution_cannot_hide_condition_elimination():
    target, params, _ = square_elimination_case()
    params["steps"] += [{"math": s} for s in ["q*(5*p+q)=1", "q>0", "p=(1-q^2)/(5*q)"]]
    params["expression"] = "(1/q+4*q)/5"
    with pytest.raises(ProofFailure, match="definition-only"):
        verify_substitution(target, params)


def test_nested_substitution_elimination_replays_without_search(monkeypatch):
    from shuxueshuo_server.solver.math_kernel import (
        constraint_elimination,
        proof_kernel,
    )

    target, params, elim_params = square_elimination_case()
    sub, _ = verify_substitution(target, params)
    elim, _ = constraint_elimination.verify_elimination(
        target, elim_params, substitution=sub
    )
    bound = public_bound(
        verify_bound(target, [{"math": "1/(5*q)+4*q/5>=4/5"}], elimination=elim)
    )
    assert (
        str(close_bound(target, bound, [{"math": "r=-sqrt(3/10),s=sqrt(1/2)"}])[0])
        == "4/5"
    )
    with pytest.raises(ProofFailure):
        close_bound(target, bound, [{"math": "r=1,s=1"}])

    def no_search(*args, **kwargs):
        raise AssertionError("nested replay must use saved proofs")

    monkeypatch.setattr(proof_kernel, "_run_request", no_search)
    monkeypatch.setattr(constraint_elimination, "_run_request", no_search)
    constraint_elimination.replay_elimination(target, json.loads(json.dumps(elim)))


@pytest.mark.parametrize(
    "mutation",
    ["scope", "definition", "target", "source", "proof", "missing_dependency"],
)
def test_nested_elimination_rejects_changed_dependency(mutation):
    from shuxueshuo_server.solver.math_kernel.constraint_elimination import (
        replay_elimination,
        verify_elimination,
    )

    target, params, elim_params = square_elimination_case()
    sub, _ = verify_substitution(target, params)
    elim, _ = verify_elimination(target, elim_params, substitution=sub)
    if mutation == "scope":
        target["scope_id"] = "other"
    if mutation == "definition":
        elim["substitution"]["definitions"]["p"] = "r"
    if mutation == "target":
        target["target_math"] = "r+s"
    if mutation == "source":
        elim["source_math"] = "p-q"
    if mutation == "proof":
        elim["substitution"]["certificates"]["relations"][0]["ruleset_hash"] = "wrong"
    if mutation == "missing_dependency":
        del elim["substitution"]
    with pytest.raises((ProofFailure, MathParseError)):
        replay_elimination(target, elim)


def test_elimination_after_substitution_requires_new_variable():
    from shuxueshuo_server.solver.math_kernel.constraint_elimination import (
        verify_elimination,
    )

    target, params, elim_params = square_elimination_case()
    sub, _ = verify_substitution(target, params)
    elim_params["eliminate"] = "r"
    with pytest.raises(ProofFailure, match="from the bound substitution"):
        verify_elimination(target, elim_params, substitution=sub)


@pytest.mark.parametrize("restoration", ["p=r^2", "r^2=p", "p=r^2+q-q"])
def test_elimination_after_substitution_rejects_original_variable_restoration(restoration):
    from shuxueshuo_server.solver.math_kernel.constraint_elimination import (
        verify_elimination,
    )

    target, params, elimination = square_elimination_case()
    sub, _ = verify_substitution(target, params)
    elimination["steps"][-1] = {"math": restoration}
    with pytest.raises(ProofFailure) as error:
        verify_elimination(target, elimination, substitution=sub)
    assert error.value.code == "elimination_restoration_invalid"


@pytest.mark.parametrize("certificate_kind", ["domains", "relations"])
def test_substitution_rejects_its_unreplayable_certificate_before_return(monkeypatch, certificate_kind):
    from shuxueshuo_server.solver.math_kernel import substitution

    function = "verify_relation_sequence" if certificate_kind == "domains" else "_verify_sequence"
    original = getattr(substitution, function)

    def corrupt_generated(*args, **kwargs):
        proofs = original(*args, **kwargs)
        if kwargs.get("certificates") is None:
            proofs = deepcopy(proofs)
            proofs[0]["ruleset_hash"] = "unreplayable"
        return proofs

    monkeypatch.setattr(substitution, function, corrupt_generated)
    target, params = square_case()
    with pytest.raises(ProofFailure):
        substitution.verify_substitution(target, params)


@pytest.mark.parametrize("expression", ["u+v", "u^4", "u^10", "u^(-1)", "2^u"])
def test_student_substitution_definitions_use_math_display(expression):
    from shuxueshuo_server.solver.explanation.annotated_teaching import (
        _project_student_runtime_value,
    )

    projected = _project_student_runtime_value(
        {"definitions": {"u": "x^2", "v": "y^2"}, "expression": expression},
        runtime_type="Substitution", student_object_aliases={}, path="/test",
    )
    assert projected == {"definitions": ["u=x²", "v=y²"], "expression": expression}


def test_elimination_without_substitution_rejects_variables_outside_target():
    from shuxueshuo_server.solver.math_kernel.constraint_elimination import (
        verify_elimination,
    )

    target = {
        "type": "extremum_target", "goal_kind": "find_minimum", "scope_id": "problem",
        "scalar_symbols": ["a", "b", "c"], "target_math": "a+b",
        "source_conditions": [
            {"handle": f"c{i}", "source_path": f"/facts/{i}", "math": relation}
            for i, relation in enumerate(["a=c", "a+b=3"])
        ],
    }
    params = {"eliminate": "a", "steps": [{"math": "a=c"}], "expression": "3"}
    with pytest.raises(ProofFailure) as error:
        verify_elimination(target, params)
    assert error.value.code == "elimination_restoration_invalid"
