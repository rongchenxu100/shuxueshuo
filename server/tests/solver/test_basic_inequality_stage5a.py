"""M08 must participate in a real frozen-input solve; no mocked authority."""

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonAuthoringPipeline,
    lesson_ir_from_payload,
)
from shuxueshuo_server.solver.math_kernel.constraint_elimination import (
    replay_elimination,
    verify_elimination,
)
from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
    close_bound,
    public_bound,
    verify_bound,
)
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.visual import VisualStepBuilder, VisualStepIRValidator
from shuxueshuo_server.solver.visual.models import visual_step_ir_from_payload
from tools.run_basic_inequality_stage4a import run

FIXTURES = Path(__file__).parent / "fixtures"


def test_q25_elimination_is_consumed_and_original_goal_closes(tmp_path):
    result, runtime = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q25.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q25/problem-ir.json",
        output=tmp_path / "q25",
        mode="recorded",
        plan=FIXTURES / "basic-inequality-stage5a/q25.json",
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"minimum": "25"}}
    execution = (
        runtime.last_success_artifacts.verified_functional_execution.to_payload()
    )
    assert "eliminate_by_constraint" in json.dumps(execution)
    assert "elimination-teaching-evidence/v1" in json.dumps(execution)
    assert "eliminate" in execution["dependency_graph"]["bound"]


def scalar_case(x="a", y="b", p=4, q=9):
    t = {
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
        "eliminate": y,
        "expression": f"{p + q}+{q}*({x}-1)+{p}/({x}-1)",
        "steps": [
            {"math": s}
            for s in [
                f"{x}-1={x}/{y}",
                f"{x}-1>0",
                f"{y}-1={y}/{x}",
                f"{y}-1>0",
                f"{y}={x}/({x}-1)",
            ]
        ],
    }
    return t, params


def test_elimination_replay_generalizes_and_restores_original_variables(monkeypatch):
    t, params = scalar_case("u", "v", 9, 16)
    evidence, _ = verify_elimination(t, params)
    bound = public_bound(
        verify_bound(t, [{"math": params["expression"] + ">=49"}], elimination=evidence)
    )
    assert close_bound(t, bound, [{"math": "u=7/4,v=7/3"}])[0] == 49
    from shuxueshuo_server.solver.math_kernel import proof_kernel

    def forbidden(*args, **kwargs):
        raise AssertionError("replay must not search")

    monkeypatch.setattr(proof_kernel, "_run_request", forbidden)
    replay_elimination(t, json.loads(json.dumps(evidence)))
    assert evidence["remaining_conditions"] and evidence["origins"]


@pytest.mark.parametrize(
    "mutation", ["wrong_formula", "cyclic", "not_reduced", "domain", "wrong_expression"]
)
def test_invalid_elimination_does_not_grant_authority(mutation):
    t, p = scalar_case()
    if mutation == "wrong_formula":
        p["steps"][-1]["math"] = "b=a/(a+1)"
    if mutation == "cyclic":
        p["steps"][-1]["math"] = "b=b+1"
    if mutation == "not_reduced":
        p["expression"] = t["target_math"]
    if mutation == "domain":
        t["source_conditions"] = t["source_conditions"][-1:]
    if mutation == "wrong_expression":
        p["expression"] = "12+9*(a-1)+4/(a-1)"
    with pytest.raises(ProofFailure):
        verify_elimination(t, p)


@pytest.mark.parametrize(
    "mutation",
    ["scope", "target", "proof", "origins", "range", "restore", "delete_domain"],
)
def test_elimination_tampering_is_rejected(mutation):
    t, p = scalar_case()
    e, _ = verify_elimination(t, p)
    if mutation == "scope":
        t["scope_id"] = "other"
    if mutation == "target":
        t["target_math"] = "a+b"
    if mutation == "proof":
        e["proofs"][0]["ruleset_hash"] = "wrong"
    if mutation == "origins":
        e["origins"][0]["source"] = "a=0"
    if mutation == "range":
        e["remaining_conditions"].clear()
    if mutation == "restore":
        e["restoration"] = "b=a"
    if mutation == "delete_domain":
        e["proofs"].pop(1)
    with pytest.raises(ProofFailure):
        replay_elimination(t, e)


def test_failed_elimination_transaction_has_no_writes(tmp_path):
    plan = json.loads((FIXTURES / "basic-inequality-stage5a/q25.json").read_text())
    plan["root_scope"]["goals"][0]["steps"][0]["parameters"]["expression"] = "a+b"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(plan))
    result, runtime = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q25.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q25/problem-ir.json",
        output=tmp_path / "bad",
        mode="recorded",
        plan=path,
    )
    assert result.status != "ok" and not result.answers
    assert runtime.last_success_artifacts is None
    transactions = list((tmp_path / "bad").glob("*transaction.json"))
    assert transactions
    for path in transactions:
        data = json.loads(path.read_text())
        assert data["state_writes"] == []
        assert data["root_issues"]


def test_q25_teaching_and_visuals_are_source_bound_and_serializable(tmp_path):
    result, runtime = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q25.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q25/problem-ir.json",
        output=tmp_path / "lesson",
        mode="recorded",
        plan=FIXTURES / "basic-inequality-stage5a/q25.json",
    )
    assert result.status == "ok"
    snapshot = ExplanationSnapshotBuilder().build(runtime.last_success_artifacts)
    built = LessonAuthoringPipeline().build(snapshot)
    assert not built.projection.diagnostics
    assert len(built.lesson.steps) == 4
    assert built.lesson.steps[0].title == "条件消元"
    assert all(s.visuals and s.derive for s in built.lesson.steps)
    visual = VisualStepBuilder().build(snapshot=snapshot, lesson=built.lesson)
    VisualStepIRValidator().validate(visual, lesson=built.lesson)
    assert not visual.metadata.get("visual_gaps")
    assert all(s.diagram_blocks for s in visual.steps)
    assert (
        visual.steps[0].diagram_blocks[0]["spec_id"]
        == "constraint_elimination.reduction"
    )
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
    assert "proofs" not in json.dumps(built.projection.plan.to_payload())


def test_equivalent_condition_forms_do_not_fill_equation_budget():
    target = {
        "type": "extremum_target",
        "goal_kind": "find_minimum",
        "scope_id": "scope",
        "scalar_symbols": ["u", "v"],
        "target_math": "u+2*v",
        "source_conditions": [
            {"handle": "sum", "source_path": "/sum", "math": "u+v=3"}
        ],
    }
    params = {
        "eliminate": "v",
        "expression": "6-u",
        "steps": [
            {"math": s}
            for s in ["v+u=3", "2*u+2*v=6", "3*u+3*v=9", "u=3-v", "4*u+4*v=12", "v=3-u"]
        ],
    }
    evidence, _ = verify_elimination(target, params)
    assert len(evidence["proofs"]) == 7
    replay_elimination(target, evidence)


def test_elimination_has_a_shared_finite_budget():
    from shuxueshuo_server.solver.math_kernel.proof_kernel import ProofLimits, _Budget

    target, params = scalar_case()
    with pytest.raises(ProofFailure, match="nodes budget") as error:
        verify_elimination(target, params, budget=_Budget(ProofLimits(nodes=1)))
    assert error.value.code == "proof_limit"


def test_elimination_cannot_smuggle_an_amgm_estimate():
    target = {
        "type": "extremum_target",
        "goal_kind": "find_minimum",
        "scope_id": "scope",
        "scalar_symbols": ["u", "v"],
        "target_math": "u+2*v",
        "source_conditions": [
            {"handle": str(i), "source_path": f"/facts/{i}", "math": s}
            for i, s in enumerate(["u>0", "v>0", "u+v=3"])
        ],
    }
    params = {
        "eliminate": "v",
        "expression": "6-u",
        "steps": [{"math": "u+v>=2*sqrt(u*v)"}, {"math": "v=3-u"}],
    }
    with pytest.raises(ProofFailure) as error:
        verify_elimination(target, params)
    assert error.value.code == "elimination_estimate_forbidden"


def test_bound_rejects_foreign_or_tampered_elimination():
    target, params = scalar_case()
    evidence, _ = verify_elimination(target, params)
    evidence["expression"] = "0"
    with pytest.raises(ProofFailure) as error:
        verify_bound(target, [{"math": "0>=0"}], elimination=evidence)
    assert error.value.code == "invalid_proof"


def test_q29_elimination_reciprocal_closes_original_maximum(tmp_path):
    import sympy as sp

    root = FIXTURES / "basic-inequality-stage5a/q29"
    result, runtime = run(
        gold=root / "notation.json",
        problem_ir=root / "problem-ir.json",
        plan=root / "plan.json",
        output=tmp_path / "q29",
        mode="recorded",
        input_mode="transcribed",
    )
    assert result.status == "ok", result.to_dict()
    assert (
        sp.simplify(
            sp.sympify(result.answers["problem"]["maximum"]) - (3 + 2 * sp.sqrt(3)) / 3
        )
        == 0
    )
    execution = (
        runtime.last_success_artifacts.verified_functional_execution.to_payload()
    )
    assert "eliminate" in execution["dependency_graph"]["bound"]
    assert "elimination-teaching-evidence/v1" in json.dumps(execution)
    snapshot = ExplanationSnapshotBuilder().build(runtime.last_success_artifacts)
    from types import SimpleNamespace
    from shuxueshuo_server.solver.explanation.basic_inequality_teaching import lower_bound_roles

    elimination_data = next(
        e["data"] for e in snapshot.evidence.values()
        if e.get("schema_version") == "elimination-teaching-evidence/v1"
    )
    assert len(elimination_data["remaining_conditions"]) == 3
    assert len(elimination_data["display_remaining_conditions"]) == 2
    assert all("=" not in c for c in elimination_data["display_remaining_conditions"])
    amgm_data = next(
        e["data"] for e in snapshot.evidence.values()
        if e.get("method_id") == "apply_two_term_amgm"
    )
    roles = lower_bound_roles(SimpleNamespace(capability_id="apply_two_term_amgm"), amgm_data)
    application = roles["derive_items_by_unit"]["amgm_apply"]
    assert application.count("∴" + roles["conclusion"]) == 1
    assert application[-1] == "∴" + roles["conclusion"]
    assert "不等号方向改变" in application[-2]
    assert r"\sqrt{3}" in application[-2]
    assert "(a)+(1)" not in str(roles)
    assert r"\(a+1\)" in roles["goal"]
    assert r"\(a+1>0\)" in application[0]
    assert all(r"\(" in row for row in application)
    lesson = LessonAuthoringPipeline().build(snapshot).lesson
    assert len(lesson.steps) == 5
    assert lesson.steps[1].teaching_unit_keys == ("reciprocal_transform",)
    assert lesson.steps[2].teaching_unit_keys == ("amgm_observe",)
    lesson = lesson_ir_from_payload(json.loads(json.dumps(lesson.to_payload())))
    visual = VisualStepBuilder().build(lesson=lesson, snapshot=snapshot)
    payload = visual.to_payload()
    transform = visual.steps[1].diagram_blocks[0]
    assert transform["spec_id"] == "basic_inequality.reciprocal"
    assert transform["source_step_ids"] == ["bound"]
    assert transform["data"]["showFocus"] is False
    assert len(transform["data"]["organization"]["steps"]) == 2
    assert "最大" in transform["data"]["organization"]["steps"][0]["expression"]
    assert "取倒数得到上界" in json.dumps(payload, ensure_ascii=False)
    assert "的最大值为" in json.dumps(payload, ensure_ascii=False)
    assert (
        visual_step_ir_from_payload(json.loads(json.dumps(payload))).to_payload()
        == payload
    )


def reciprocal_case(x="a", y="b"):
    import re

    root = FIXTURES / "basic-inequality-stage5a/q29"
    steps = json.loads((root / "plan.json").read_text())["root_scope"]["goals"][0][
        "steps"
    ]

    def renamed(text):
        return re.sub(r"\b[ab]\b", lambda m: {"a": x, "b": y}[m[0]], text)

    parameters = json.loads(renamed(json.dumps([s["parameters"] for s in steps])))
    target = {
        "type": "extremum_target",
        "goal_kind": "find_maximum",
        "scope_id": "another-scope",
        "scalar_symbols": [x, y],
        "target_math": renamed("b/(a+b^2)+2*a/(a^2+b)"),
        "source_conditions": [
            {"handle": f"c{i}", "source_path": f"/facts/{i}", "math": renamed(s)}
            for i, s in enumerate(["a>0", "b>0", "b+a=1"])
        ],
    }
    return target, parameters


def test_reciprocal_bound_renamed_reordered_and_replay_without_search(monkeypatch):
    import sympy as sp

    from shuxueshuo_server.solver.math_kernel import inequality_bound_v2, proof_kernel

    target, params = reciprocal_case("u", "v")
    elimination, _ = verify_elimination(target, params[0])
    bound = public_bound(verify_bound(target, **params[1], elimination=elimination))
    assert (
        sp.simplify(
            close_bound(target, bound, **params[2])[0] - (3 + 2 * sp.sqrt(3)) / 3
        )
        == 0
    )

    def no_search(*args, **kwargs):
        raise AssertionError("certificate replay attempted proof search")

    monkeypatch.setattr(proof_kernel._Search, "core", no_search)
    rebuilt = inequality_bound_v2.verify(
        target,
        **params[1],
        elimination=elimination,
        certificates=bound["certificate_bundle"],
    )
    assert public_bound(rebuilt) == bound


@pytest.mark.parametrize(
    "mutation",
    [
        "direction",
        "constant",
        "domain",
        "owner",
        "elimination",
        "certificate",
        "lower_certificate",
    ],
)
def test_reciprocal_bound_rejects_missing_or_changed_evidence(mutation):
    from copy import deepcopy

    target, params = reciprocal_case()
    elimination, _ = verify_elimination(target, params[0])
    if mutation in {"direction", "constant", "domain", "owner"}:
        if mutation == "direction":
            params[1]["steps"][-1]["math"] = params[1]["steps"][-1]["math"].replace(
                ">=", "<="
            )
        elif mutation == "constant":
            params[1]["steps"][-1]["math"] = params[1]["steps"][-1]["math"].replace(
                "2*sqrt(3)-3", "1"
            )
        elif mutation == "domain":
            target["source_conditions"] = target["source_conditions"][-1:]
        else:
            target["scope_id"] = "foreign"
        with pytest.raises(ProofFailure):
            verify_bound(target, **params[1], elimination=elimination)
        return
    bound = deepcopy(
        public_bound(verify_bound(target, **params[1], elimination=elimination))
    )
    if mutation == "elimination":
        bound["elimination"]["expression"] = "1"
    elif mutation == "certificate":
        bound["certificate_bundle"]["proofs"][-1]["nodes"][-1]["conclusion"] = [
            "=",
            ["rat", "1", "1"],
            ["rat", "0", "1"],
        ]
    else:
        bound["certificate_bundle"]["reciprocal_bound"]["bound"] = "1"
    with pytest.raises(ProofFailure):
        close_bound(target, bound, **params[2])


def test_reciprocal_accepts_bound_before_trailing_positivity():
    target, params = reciprocal_case()
    elimination, _ = verify_elimination(target, params[0])
    params[1]["steps"] += [
        {"math": "2*sqrt(3)-3>0"},
    ]
    bound = public_bound(verify_bound(target, **params[1], elimination=elimination))
    assert bound["reciprocal"] is True
    assert close_bound(target, bound, **params[2])


def test_m08_acceptance_checks_scope_steps_and_requires_verified_evidence():
    from tools.run_basic_inequality_stage5a import m08_executed

    step = {
        "status": "runtime_verified",
        "authored_step": {"capability_id": "eliminate_by_constraint"},
        "evidence": [{"schema_version": "elimination-teaching-evidence/v1"}],
    }
    assert m08_executed({"root_scope": {"steps": [step], "goals": []}})
    assert m08_executed({"root_scope": {"goals": [{"steps": [step]}]}})
    step["evidence"] = []
    assert not m08_executed({"root_scope": {"steps": [step]}})


def test_elimination_diagram_uses_roles_not_every_submitted_relation():
    from shuxueshuo_server.solver.explanation.elimination import visual

    data = {
        "conditions": ["u>0", "v>0", "u+v=1"],
        "source": "u/v", "result": "u/(1-u)", "restoration": "v=1-u",
        "remaining_conditions": ["u>0", "1-u>0"],
        "relations": ["long derivation not needed in diagram"] * 15,
    }
    diagram = visual(data)
    assert len(diagram["organization"]["steps"]) == 3
    assert "long derivation" not in json.dumps(diagram)
    assert "1-u>0" in json.dumps(diagram)


def test_witness_only_teaching_does_not_present_checked_rows_as_equation_solving():
    from types import SimpleNamespace
    from shuxueshuo_server.solver.explanation.basic_inequality_teaching import lower_bound_roles

    data = {
        "direction": ">=", "terms": ["u", "4/u"], "equalities": ["u=4/u"],
        "claim_scope": "submitted_witness", "target": "u+4/u", "bound": "4",
        "verified_branches": [{"assignments": {"u": "2"}, "relations": ["u=2"]}],
    }
    roles = lower_bound_roles(SimpleNamespace(capability_id="close_equality_and_restore"), data)
    text = json.dumps(roles, ensure_ascii=False)
    assert r"当 \(u=2\) 时" in roles["derive_items"][1]
    assert "设取" not in text and "解得" not in text
    assert "∴u=2" not in text


def test_fraction_typography_handles_fullwidth_subtraction_in_denominator():
    from shuxueshuo_server.solver.explanation.math_typography import fraction_prose

    text = fraction_prose("∴ (a²－a＋1)/(a＋1)≥－3＋2√3")
    assert r"\frac{a^{2}-a+1}{a+1}" in text
    assert "≥-" in text and "－" not in text


def test_fraction_typography_preserves_mixed_tex_radical_boundary():
    from shuxueshuo_server.solver.explanation.math_typography import fraction_prose

    text = fraction_prose(r"(a＋1)＋3/(a＋1)≥2√[ \((a+1)\cdot\frac{3}{a+1}\) ]")
    assert text.count(r"\frac{3}{a+1}") == 2
    assert "≥2√[" in text
