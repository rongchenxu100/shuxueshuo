"""Stage 4A through the authenticated Functional/transactional Runtime entry."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.solver.basic_inequality_stage4a import (
    build_authoring_bundle,
    load_frozen_authoring_bundle,
)
from shuxueshuo_server.solver.extraction.problem_planner_authority import (
    VerifiedPlannerProblemAuthority,
)
from shuxueshuo_server.solver.extraction.source_identity import thaw_json
from shuxueshuo_server.solver.family import (
    BASIC_INEQUALITY_FAMILY,
    DEFAULT_FAMILY_REGISTRY,
)
from shuxueshuo_server.solver.family.basic_inequality_runtime import (
    STAGE4A_FAMILY_REGISTRY,
)
from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
    close_bound,
    public_bound,
    target_context,
    verify_bound,
)
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.math_kernel.proof_kernel import replay_proof
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.projection import problem_from_canonical_input
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    strategy_planner_provider,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures/basic-inequality-problem-ir/v1/q01/problem-ir.json"
)


def source():
    return json.loads(FIXTURE.read_text())["input"]


def plan():
    path = (
        Path(__file__).resolve().parents[3]
        / "internal/functional-plan-fixtures/basic-inequality-q01.functional-plan.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


class RecordedClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def complete(self, payload, **kwargs):
        self.requests.append(payload)
        return (
            self.response[min(len(self.requests) - 1, len(self.response) - 1)]
            if isinstance(self.response, list)
            else self.response
        )


def solve(data=None, candidate=None, debug_dir=None, repair=None):
    bundle = (
        build_authoring_bundle(data)
        if data is not None
        else load_frozen_authoring_bundle(GOLD, FIXTURE)
    )
    authority = VerifiedPlannerProblemAuthority.from_bundle(bundle)
    parsed, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        candidate or plan()
    )
    assert report.ok, report.to_payload()
    content = functional_plan_content_from_plan(
        parsed,
        frame=FunctionalPlanAuthorityFrame.from_planning_context(
            authority.planning_context
        ),
    )
    response = json.dumps(content.to_payload(), ensure_ascii=False)
    client = RecordedClient(
        [response, json.dumps(repair, ensure_ascii=False)] if repair else response
    )
    runtime = RuntimeOrchestrator(
        family_registry=STAGE4A_FAMILY_REGISTRY,
        default_planner_provider=strategy_planner_provider(
            mode="deepseek",
            client=client,
            argument_encoding="source-ref",
            functional_few_shot_mode="strict_test",
        ),
        max_attempts=2 if repair else 1,
        debug_dir=debug_dir,
    )
    result = runtime.solve_verified(bundle)
    return result, runtime, client


def test_q01_runtime_closes_maximum(tmp_path):
    result, runtime, client = solve(debug_dir=tmp_path)
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"maximum": "1"}}
    assert runtime.last_success_artifacts is not None
    assert runtime.last_success_artifacts.verified_functional_execution is not None
    transaction = json.loads((tmp_path / "attempt-1.transaction.json").read_text())
    assert transaction["execution_report"]["ok"]
    assert all(g["status"] == "passed" for g in transaction["goal_report"]["goals"])
    writes = transaction["state_writes"]
    assert [(w["runtime_type"], w["identity_policy"]) for w in writes] == [
        ("AmgmBound", "value_only"),
        ("MaximumExpression", "value_only"),
    ]
    assert (
        transaction["execution_report"]["graph"]["dependencies"][0]["kind"]
        == "call_result"
    )
    assert len(client.requests) == 1


GOLD = FIXTURE.parents[3] / "math-notation-v1/basic-inequality/q01.json"


def target(data=None):
    return thaw_json(build_authoring_bundle(data or source()).canonical_solver_input)[
        "facts"
    ][-1]


def steps():
    return plan()["root_scope"]["goals"][0]["steps"]


def test_frozen_entry_replays_and_rejects_changed_ir(tmp_path):
    bundle = load_frozen_authoring_bundle(GOLD, FIXTURE)
    assert len(bundle.provenance["samples"]) == 2
    assert bundle.admission_evidence["kind"] == "verified_frozen_authoring"
    changed = json.loads(FIXTURE.read_text())
    changed["input"]["question_goals"][0]["target_expression"] = "m+n"
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="differs"):
        load_frozen_authoring_bundle(GOLD, path)


def test_certificates_replay_and_public_bound_contains_no_runtime_identity():
    t = target()
    bound = verify_bound(t, steps()[0]["parameters"]["steps"])
    ctx, _ = target_context(t)
    for proof in bound["proofs"]:
        assert replay_proof(proof, ctx).status == "proved"
    public = public_bound(bound)
    assert "fact:" not in json.dumps(public)
    value, trace = close_bound(t, public, steps()[1]["parameters"]["steps"])
    assert value == 1
    assert replay_proof(trace["witness_proof"], ctx).status == "proved"
    assert trace["exhaustive"] is False
    public["bound"] = "2"
    with pytest.raises(ProofFailure, match="altered"):
        close_bound(t, public, steps()[1]["parameters"]["steps"])


@pytest.mark.parametrize(
    "assignments",
    [
        ["m=2", "n=0"],
        ["m=1"],
        ["m=1", "m=1"],
        ["m=n", "n=m"],
        ["m=1", "n=1", "m+n=3"],
        ["m=1", "n=1", "m+n=2,m*n=2"],
        ["∵m=n=1", "∴m>n"],
        ["m=1", "n=1", "m=2"],
    ],
)
def test_invalid_witness_never_commits_maximum(assignments, tmp_path):
    p = plan()
    p["root_scope"]["goals"][0]["steps"][1]["parameters"]["steps"] = [
        {"math": row} for row in assignments
    ]
    result, runtime, _ = solve(candidate=p, debug_dir=tmp_path)
    assert result.status != "ok"
    assert not result.answers
    assert runtime.last_success_artifacts is None
    paths = list(tmp_path.glob("**/*transaction.json"))
    assert paths
    for path in paths:
        payload = json.loads(path.read_text())
        assert all(w["runtime_type"] == "AmgmBound" for w in payload["state_writes"])
        failed = next(
            row
            for row in payload["execution_report"]["call_results"]
            if row["call_id"] == "attain"
        )
        assert failed["status"] == "failed"
        assert failed["state_writes"] == []
        assert failed["runtime_results"] == []


@pytest.mark.parametrize("math", ["m*n<=1/2", "m*n>=1", "m+n<=1"])
def test_invalid_bound_never_answers(math, tmp_path):
    p = plan()
    p["root_scope"]["goals"][0]["steps"][0]["parameters"]["steps"][1]["math"] = math
    result, _, _ = solve(candidate=p, debug_dir=tmp_path)
    assert result.status != "ok"
    assert not result.answers
    if math == "m*n<=1/2":
        transaction = json.loads((tmp_path / "attempt-1.transaction.json").read_text())
        issue = transaction["root_issues"][0]["diagnostic_authority"]
        assert issue["observed"]["code"] == "target_bound_mismatch"
        assert issue["repair_action"] == "repair_derivation"
        assert "定和代入" in issue["original_message"]


@pytest.mark.parametrize(
    ("total", "submitted", "expected"),
    [("2", "1/2", "1"), ("6", "8", "9"), ("3/2", "1/2", "9/16"), ("2", "2", "1")],
)
def test_constant_bound_mismatch_has_specific_diagnostic(total, submitted, expected):
    t = target()
    ctx, _ = target_context(t)
    equality = next(
        c for c in t["source_conditions"] if ctx.premises[c["handle"]].ast.op == "="
    )
    equality["math"] = f"{total}=n+m"
    with pytest.raises(ProofFailure) as caught:
        verify_bound(t, math_rows("n+m>=2*sqrt(n*m)", f"n*m<={submitted}"))
    assert caught.value.code == "target_bound_mismatch"
    assert f"常数 {expected}" in str(caught.value)
    assert "steps[1].math" in str(caught.value)
    assert "支持该机制的能力" in str(caught.value)


def test_matching_constant_does_not_hide_real_proof_budget_failure(monkeypatch):
    from dataclasses import replace

    from shuxueshuo_server.solver.math_kernel import inequality_evidence

    original = inequality_evidence.target_context

    def limited(target):
        ctx, expression = original(target)
        return replace(ctx, limits=replace(ctx.limits, nodes=1)), expression

    monkeypatch.setattr(inequality_evidence, "target_context", limited)
    with pytest.raises(ProofFailure) as caught:
        verify_bound(target(), math_rows("m+n>=2*sqrt(m*n)", "m*n<=1"))
    assert caught.value.code == "proof_limit"


def test_bound_is_not_a_maximum_answer(tmp_path):
    p = plan()
    goal = p["root_scope"]["goals"][0]
    goal["steps"] = goal["steps"][:1]
    goal["answer_from"] = {"step_id": "bound", "return": "bound"}
    result, _, _ = solve(candidate=p, debug_dir=tmp_path)
    assert result.status != "ok"
    assert not result.answers


def test_all_original_conditions_checked_even_when_bound_proves(tmp_path):
    data = source()
    extra = deepcopy(data["facts"][0])
    extra.update(
        handle="fact:s0:extra",
        normalized_expression="m>1",
        source_text="m>1",
        source_path="/root/facts/3",
    )
    data["facts"].append(extra)
    t = target(data)
    verify_bound(t, steps()[0]["parameters"]["steps"])
    result, _, _ = solve(data=data, debug_dir=tmp_path)
    assert result.status != "ok"
    assert not result.answers


def test_missing_positivity_fails_closed(tmp_path):
    data = source()
    data["facts"] = [f for f in data["facts"] if f["type"] == "equation"]
    result, _, _ = solve(data=data, debug_dir=tmp_path)
    assert result.status != "ok"
    assert not result.answers


def test_renamed_symbols_changed_constant_and_problem_id_use_same_runtime(tmp_path):
    # This anonymous case is not a new frozen extraction or ProblemIR asset.
    data = source()
    data["problem_id"] = "anonymous-product"
    for entity, name in zip(data["entities"], ("a", "b"), strict=True):
        entity.update(name=name, handle=f"symbol:s0:{name}")
    for fact, math in zip(data["facts"], ("a>0", "b>0", "a+b=6"), strict=True):
        fact.update(normalized_expression=math, source_text=math)
    data["question_goals"][0]["target_expression"] = "a*b"
    p = plan()
    calls = p["root_scope"]["goals"][0]["steps"]
    calls[0]["parameters"]["steps"] = [{"math": "a+b>=2*sqrt(a*b)"}, {"math": "a*b<=9"}]
    calls[1]["parameters"]["steps"] = [{"math": "a=3"}, {"math": "b=3"}]
    result, _, _ = solve(data=data, candidate=p, debug_dir=tmp_path)
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"maximum": "9"}}


def test_default_registry_stays_closed_and_authoring_catalog_stays_inert():
    assert DEFAULT_FAMILY_REGISTRY.match(problem_from_canonical_input(source())) is None
    assert all(
        c.execution_status == "catalog_only"
        for c in BASIC_INEQUALITY_FAMILY.capability_contracts
    )
    family = STAGE4A_FAMILY_REGISTRY.match(problem_from_canonical_input(source()))
    assert family.method_ids == ("apply_two_term_amgm", "close_equality_and_restore")


def test_catalog_exposes_only_verified_stage4a_methods():
    from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
        FunctionalCapabilityCatalog,
    )
    from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
    from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry

    family = STAGE4A_FAMILY_REGISTRY.families[0]
    methods = MethodSpecRegistry.load_from_code()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        family, methods
    ).to_prompt_payload()
    assert [row["capability_id"] for row in catalog["capabilities"]] == list(
        family.method_ids
    )
    assert MacroSpecRegistry.from_family_spec(family, methods).specs == {}


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_symbol",
        "duplicate_condition",
        "wrong_type",
        "extra_scope",
        "wrong_goal",
    ],
)
def test_authoring_projection_rejects_unsupported_sources(mutation):
    data = source()
    if mutation == "duplicate_symbol":
        data["entities"].append(deepcopy(data["entities"][0]))
    elif mutation == "duplicate_condition":
        data["facts"].append(deepcopy(data["facts"][0]))
    elif mutation == "wrong_type":
        data["facts"][-1]["normalized_expression"] = "m+n<2"
    elif mutation == "extra_scope":
        data["scopes"].append({"scope_id": "child", "parent": "s0", "label": "child"})
    else:
        data["question_goals"][0]["value_type"] = "MinimumExpression"
    with pytest.raises(ValueError):
        build_authoring_bundle(data)


@pytest.mark.parametrize("bad_bound", [False, True])
def test_retry_repairs_witness_without_reusing_failed_answer(tmp_path, bad_bound):
    candidate = plan()
    bad_goal = candidate["root_scope"]["goals"][0]
    if bad_bound:
        bad_goal["steps"][0]["parameters"]["steps"][-1]["math"] = "m*n<=1/2"
    else:
        bad_goal["steps"][1]["parameters"]["steps"].append({"math": "m=2"})
    goal = plan()["root_scope"]["goals"][0]
    repair = {
        "schema_version": "functional-scope-repair/v1",
        "scope_replacements": {
            "problem": {
                "scope_steps": [],
                "goals": {
                    goal["goal_ref"]: {
                        "steps": goal["steps"],
                        "answer_from": goal["answer_from"],
                    }
                },
            }
        },
    }
    result, runtime, client = solve(
        candidate=candidate, repair=repair, debug_dir=tmp_path
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"maximum": "1"}}
    assert len(client.requests) == 2
    first = json.loads((tmp_path / "attempt-1.transaction.json").read_text())
    assert [row["runtime_type"] for row in first["state_writes"]] == (
        [] if bad_bound else ["AmgmBound"]
    )
    assert first["root_issues"][0]["diagnostic_authority"]["observed"]["code"] == (
        "target_bound_mismatch" if bad_bound else "proof_missing"
    )
    second = json.loads((tmp_path / "attempt-2.transaction.json").read_text())
    assert second["goal_report"]["goals"][0]["status"] == "passed"
    assert runtime.last_success_artifacts.verified_functional_execution is not None


@pytest.mark.parametrize("total", ["m+n", "n+m"])
@pytest.mark.parametrize("product", ["m*n", "n*m"])
@pytest.mark.parametrize("bound_product", ["m*n", "n*m"])
def test_commuted_amgm_closes_same_maximum(total, product, bound_product, tmp_path):
    candidate = plan()
    rows = candidate["root_scope"]["goals"][0]["steps"][0]["parameters"]["steps"]
    rows[0]["math"] = f"{total}>=2*sqrt({product})"
    rows[1]["math"] = f"{bound_product}<=1"
    bound = verify_bound(target(), rows)
    assert bound["steps"] == rows
    assert bound["equality"] == ("(m)=(n)" if total == "m+n" else "(n)=(m)")
    result, runtime, client = solve(candidate=candidate, debug_dir=tmp_path)
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"maximum": "1"}}
    assert runtime.last_success_artifacts.verified_functional_execution is not None
    assert len(client.requests) == 1


def test_scalar_input_does_not_invent_a_quadratic_function(tmp_path):
    result, runtime, _ = solve(debug_dir=tmp_path)
    assert result.status == "ok"
    artifacts = runtime.last_success_artifacts
    assert artifacts.problem.data["function"] == {}
    assert "quadratic" not in artifacts.context.problem_scope.container("expressions")


def test_bound_cannot_attach_a_different_proved_amgm_pair():
    t = target()
    t["scalar_symbols"] += ["a", "b"]
    t["source_conditions"] += [
        {"handle": f"given:{i}", "math": math, "source_path": f"/extra/{i}"}
        for i, math in enumerate(("a>0", "b>0", "a+b=2"))
    ]
    with pytest.raises(ProofFailure, match="submitted AM-GM"):
        verify_bound(t, [{"math": "b+a>=2*sqrt(a*b)"}, {"math": "m*n<=1"}])


@pytest.mark.parametrize("bad_math", ["m*n<=", r"m*n\le 1"])
def test_invalid_amgm_syntax_has_actionable_repair_hint(bad_math):
    with pytest.raises(ProofFailure) as caught:
        verify_bound(target(), [{"math": "m+n>=2*sqrt(m*n)"}, {"math": bad_math}])
    assert "steps[1].math" in str(caught.value)
    assert "sqrt(...)" in str(caught.value)
    assert caught.value.code in {"invalid_syntax", "unsupported_syntax"}


def math_rows(*values):
    return [{"math": value} for value in values]


@pytest.mark.parametrize("separator", ["；", ";", ",", "，", " ", "", "\n"])
def test_inline_because_therefore_clauses_do_not_require_repair(tmp_path, separator):
    p = plan()
    calls = p["root_scope"]["goals"][0]["steps"]
    calls[0]["parameters"]["steps"] = math_rows(
        f"∵m>0,n>0{separator}∴m+n>=2*sqrt(m*n)",
        f"∵m+n=2{separator}∴2>=2*sqrt(m*n)",
        "∴sqrt(m*n)<=1",
        "∴m*n<=1",
    )
    calls[1]["parameters"]["steps"] = math_rows(
        f"∵m>0,n>0,m+n=2,m=n{separator}∴m=1,n=1",
        "∴m+n=2,m*n=1",
    )
    result, _, client = solve(candidate=p, debug_dir=tmp_path)
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"maximum": "1"}}
    assert len(client.requests) == 1
    ctx, _ = target_context(target())
    from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation

    relations = parse_derivation(calls[0]["parameters"]["steps"], ctx.symbols)
    assert [item.origin["marker"] for item in relations[:3]] == ["∵", "∵", "∴"]
    assert relations[2].origin["source"] == calls[0]["parameters"]["steps"][0]["math"]
    assert relations[2].parsed.source == " ".join(
        relations[2].origin["source"][a:b] for a, b in relations[2].origin["segments"]
    )


@pytest.mark.parametrize(
    "math",
    [
        "∵m>∴n>0",
        "∵m>0∴",
        "∵m>0∴∴n>0",
        "∵m>n n>0",
    ],
)
def test_marker_fallback_never_discards_incomplete_or_unseparated_relations(math):
    with pytest.raises(ProofFailure) as caught:
        verify_bound(target(), math_rows(math, "m*n<=1"))
    assert caught.value.code == "invalid_syntax"
    assert "steps[0].math" in str(caught.value)


def test_marker_fallback_preserves_verification_and_clause_budget():
    with pytest.raises(ProofFailure):
        verify_bound(target(), math_rows("∵m=n∴m+n>=2*sqrt(m*n)", "m*n<=1"))
    with pytest.raises(ProofFailure) as caught:
        verify_bound(target(), math_rows("∵m>0" + "∴m>0" * 8, "m*n<=1"))
    assert caught.value.code == "proof_limit"


@pytest.mark.parametrize(
    "derivation",
    [
        math_rows(
            "∵m>0,n>0",
            "∴m+n>=2*sqrt(m*n)",
            "∵m+n=2",
            "∴2>=2*sqrt(m*n)",
            "∴sqrt(m*n)<=1",
            "∴m*n<=1",
        ),
        math_rows("∵m+n=2,m>0,n>0", "∴m+n>=2*sqrt(n*m)", "∴m*n<=(m+n)^2/4=1"),
    ],
)
@pytest.mark.parametrize(
    "witness",
    [
        math_rows("∵m=n,m+n=2", "∴m=n=1", "∴m+n=2,m*n=1"),
        math_rows("m=1", "n=1", "∴m>0,n>0", "∴m+n=2,m*n=1"),
    ],
)
def test_complete_derivations_close_transaction(derivation, witness, tmp_path):
    p = plan()
    calls = p["root_scope"]["goals"][0]["steps"]
    calls[0]["parameters"]["steps"] = derivation
    calls[1]["parameters"]["steps"] = witness
    result, runtime, client = solve(candidate=p, debug_dir=tmp_path)
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"maximum": "1"}}
    assert len(client.requests) == 1
    assert runtime.last_success_artifacts.verified_functional_execution is not None


@pytest.mark.parametrize("extra", ["∵m=n", "∵m+n=3", "∴sqrt(m*n)>=1", "∴m*n<=1/2"])
def test_unproved_intermediate_cannot_hide_behind_correct_final_bound(extra):
    with pytest.raises(ProofFailure):
        verify_bound(target(), math_rows("m+n>=2*sqrt(m*n)", extra, "m*n<=1"))


def test_chain_checks_every_link_not_only_endpoint():
    with pytest.raises(ProofFailure):
        verify_bound(target(), math_rows("m+n>=2*sqrt(m*n)", "m*n<=0=1"))


@pytest.mark.parametrize(
    "tamper", ["origin", "remove", "conclusion", "premise", "reorder"]
)
def test_derivation_replay_binds_sources_and_verified_predecessors(tamper):
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        replay_derivation,
    )

    rows = math_rows("∵m>0,n>0", "∴m+n>=2*sqrt(m*n)", "∴2>=2*sqrt(m*n)", "∴m*n<=1")
    ctx, _ = target_context(target())
    evidence = verify_bound(target(), rows)["derivation"]
    replay_derivation(rows, evidence, ctx)
    assert evidence == verify_bound(target(), rows)["derivation"]
    if tamper == "origin":
        evidence["origins"][0]["segments"][0][0] += 1
    elif tamper == "remove":
        evidence["proofs"].pop(2)
    elif tamper == "conclusion":
        evidence["proofs"][-1]["request"]["candidate"]["source"] = "m*n<=0"
    elif tamper == "premise":
        evidence["proofs"][3]["sources"]["candidate"]["source"] = "0=1"
    else:
        evidence["proofs"][2], evidence["proofs"][3] = (
            evidence["proofs"][3],
            evidence["proofs"][2],
        )
    with pytest.raises(ProofFailure):
        replay_derivation(rows, evidence, ctx)


def test_derivation_source_segments_and_shared_budget():
    from dataclasses import replace

    from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
    from shuxueshuo_server.solver.math_kernel.proof_kernel import (
        verify_relation_sequence,
    )

    ctx, _ = target_context(target())
    rows = math_rows("∵ m>0，n>0", "∴ m*n ≤ (m+n)²/4 = 1")
    parsed = parse_derivation(rows, ctx.symbols)
    for item in parsed:
        assert item.parsed.source_path == item.origin["derived_source_path"]
        assert item.parsed.source == " ".join(
            item.origin["source"][a:b] for a, b in item.origin["segments"]
        )
        assert (
            item.origin["source_path"] == f"/parameters/steps/{item.parsed.step}/math"
        )
    assert parsed[-1].origin["chain_endpoint"]
    small = replace(ctx, limits=replace(ctx.limits, nodes=3))
    repeated = [parse_derivation(math_rows("m>0"), ctx.symbols)[0].parsed] * 2
    with pytest.raises(ProofFailure, match="nodes budget"):
        verify_relation_sequence(repeated, small)
