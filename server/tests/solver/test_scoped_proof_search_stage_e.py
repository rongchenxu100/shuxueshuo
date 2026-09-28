"""Formal Method execution under the explicit scoped-facts/v2 protocol."""

import json
from pathlib import Path

import pytest
from tools.run_basic_inequality_stage4a import run

FIXTURES = Path(__file__).parent / "fixtures"


def test_q30_real_method_chain_with_scoped_search(tmp_path, monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_kernel

    def forbidden(*a, **kw):
        raise AssertionError("v2 execution called legacy search")

    monkeypatch.setattr(proof_kernel._Search, "need", forbidden)
    from shuxueshuo_server.solver.runtime.scoped_proof_facts import ScopedProofFacts

    replayed_commits = []
    restore_one = ScopedProofFacts._restore_one

    def counted_commit(self, payload):
        replayed_commits.append(payload["call_id"])
        return restore_one(self, payload)

    monkeypatch.setattr(ScopedProofFacts, "_restore_one", counted_commit)
    from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
        FunctionalTransactionalInterpreter,
        build_functional_execution_restore_seed,
    )

    execute = FunctionalTransactionalInterpreter.execute_attempt
    captured = []

    def capture(self, **kwargs):
        attempt = execute(self, **kwargs)
        captured.append((self, kwargs, attempt))
        return attempt

    monkeypatch.setattr(FunctionalTransactionalInterpreter, "execute_attempt", capture)
    result, runtime = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q30.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
        plan=FIXTURES / "basic-inequality-stage5c/q30.json",
        output=tmp_path / "execution",
        mode="recorded",
        proof_protocol="scoped-facts/v2",
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"minimum": "4"}}
    execution = (
        runtime.last_success_artifacts.verified_functional_execution.to_payload()
    )
    assert len(execution["dependency_graph"]) == 5
    store = runtime.last_success_artifacts.context.proof_facts
    assert store is not None
    assert len(store.snapshot.commits) == 5
    assert replayed_commits == ["rewrite", "first", "square", "last", "attain"]
    replayed_commits.clear()
    assert sum(len(c.requirements) for c in store.snapshot.commits) == 3
    assert "rewrite" in store.snapshot.commits[1].dependencies
    assert any(
        r["kind"] == "reuse"
        for c in store.snapshot.commits
        for r in json.loads(c.records_json)
    )
    for commit in store.snapshot.commits:
        reads = [
            ref
            for r in json.loads(commit.records_json)
            if r["kind"] == "reuse"
            for ref in r["fact_ids"]
        ]
        assert len(reads) == len(set(reads))
    for producer, consumer in zip(
        ("rewrite", "first", "square", "last"), ("first", "square", "last", "attain")
    ):
        assert producer in execution["dependency_graph"][consumer]
    monkeypatch.setattr(proof_kernel, "_run_request", forbidden)
    from shuxueshuo_server.solver.runtime.scoped_proof_facts import ScopedProofFacts

    restored = ScopedProofFacts(
        store.context, store.source_context, store.bindings, store.calls
    )
    restored.restore(
        store.to_payload(), {c.call_id: c.output_hash for c in store.snapshot.commits}
    )
    assert restored.to_payload() == store.to_payload()
    assert replayed_commits == ["rewrite", "first", "square", "last", "attain"]
    replayed_commits.clear()
    (tmp_path / "q30-verified-proof-snapshot.json").write_text(
        json.dumps(
            {
                "proof_protocol": "scoped-facts/v2",
                "facts": store.to_payload(),
                "execution": execution,
                "checker_only_restore": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    interpreter, args, original = captured[-1]
    seed = build_functional_execution_restore_seed(
        original.execution_report, args["reconciliation"]
    )
    restore = ScopedProofFacts.restore
    restored_sizes = []

    def counted_restore(self, payload, hashes):
        restored_sizes.append(len(payload["commits"]))
        return restore(self, payload, hashes)

    monkeypatch.setattr(ScopedProofFacts, "restore", counted_restore)
    replayed = execute(interpreter, **{**args, "restored_seed": seed})
    assert restored_sizes == [1, 2, 3, 4, 5]
    assert replayed_commits == ["rewrite", "first", "square", "last", "attain"]
    assert replayed.execution_report.ok, replayed.execution_report.to_payload()
    assert (
        replayed.execution_report.runtime_context.proof_facts.to_payload()
        == store.to_payload()
    )
    with pytest.raises(ValueError, match="condition protocol"):
        restored.restore(
            {k: v for k, v in store.to_payload().items() if k != "condition_protocol"},
            {},
        )


@pytest.mark.parametrize("case,answer", [("q12", "4/5"), ("q25", "25")])
def test_substitution_uses_scoped_search(case, answer, tmp_path, monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_kernel

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy search called")

    monkeypatch.setattr(proof_kernel._Search, "need", forbidden)
    result, runtime = run(
        gold=FIXTURES / f"math-notation-v1/basic-inequality/{case}.json",
        problem_ir=FIXTURES / f"basic-inequality-problem-ir/v1/{case}/problem-ir.json",
        plan=FIXTURES / f"basic-inequality-stage5b/{case}.json",
        output=tmp_path / case,
        mode="recorded",
        proof_protocol="scoped-facts/v2",
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"minimum": answer}}
    store = runtime.last_success_artifacts.context.proof_facts
    if case == "q12":
        elimination = store.snapshot.commits[1]
        assert "substitute" in elimination.dependencies
        records = json.loads(elimination.records_json)
        assert any(r["kind"] == "reuse" for r in records)
        assert "math.two_term_amgm" not in json.dumps(records)


@pytest.mark.parametrize("case", ["q30", "q29", "q01"])
def test_v2_compiled_lesson(case, tmp_path, monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_kernel
    from tools.run_basic_inequality_stage4b import build

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy search called")

    monkeypatch.setattr(proof_kernel._Search, "need", forbidden)
    output = tmp_path / case
    build(case=case, output=output, proof_protocol="scoped-facts/v2")
    assert (output / "lesson.html").exists()
    data = json.loads((output / "visual-binding-audit.json").read_text())
    assert data["gaps"] == []
    if case == "q30":
        lesson = json.loads((output / "lesson-ir.json").read_text())
        steps = lesson["root_scope"]["goals"]["problem.minimum"]["steps"]
        assert len(steps) == 7
        specs = {d["spec_id"] for s in data["steps"] for d in s["diagrams"]}
        assert {
            "basic_inequality.local_reciprocal",
            "basic_inequality.quadratic",
            "basic_inequality.equality",
        } <= specs


@pytest.mark.parametrize("hint", [None, [], ["y>0"], ["x>0", "y>0"]])
def test_m01_condition_protocol_matrix(hint):
    import sympy as sp
    from shuxueshuo_server.solver.runtime.methods.organize_expressions import (
        OrganizeExpressionsMethod,
    )

    x, y = sp.symbols("x y", real=True)
    inputs = {
        "expression": 1 / x,
        "__visible_symbols__": {"x": x, "y": y},
        "__parameters__": {"steps": [{"math": "1/x=2/(2*x)"}]},
        "__proof_protocol__": "scoped-facts/v2",
        "__scope_conditions__": ["x>0", "y>0"],
    }
    if hint is not None:
        inputs["conditions"] = hint
    result = OrganizeExpressionsMethod().run(inputs, None)
    trace = result.trace_fragments[0]
    assert trace["condition_protocol"] == "scoped-facts/v2"
    assert set(trace["proof_contexts"][0]["premises"]) == {"c0", "c1"}


def test_m01_scoped_domain_feedback_does_not_ask_for_rebinding():
    import sympy as sp
    from shuxueshuo_server.solver.runtime.methods.organize_expressions import (
        OrganizeExpressionsMethod,
    )

    x = sp.Symbol("x", real=True)
    inputs = {
        "expression": 1 / x,
        "__visible_symbols__": {"x": x},
        "__parameters__": {"steps": [{"math": "1/x=2/(2*x)"}]},
        "__proof_protocol__": "scoped-facts/v2",
        "__scope_conditions__": [],
    }
    with pytest.raises(Exception) as error:
        OrganizeExpressionsMethod().run(inputs, None)
    assert error.value.authority.observed["code"] == "domain_unproved"
    assert error.value.authority.repair_action == "repair_domain_proof"
    assert error.value.authority.observed["unverified_conditions"]


@pytest.mark.parametrize("names,k", [(("x", "y", "z"), 3), (("p", "q", "r"), 7)])
def test_scoped_mixed_chain_generalizes_and_replays(names, k, monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_kernel
    from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        close_bound,
        public_bound,
    )
    from shuxueshuo_server.solver.math_kernel.method_proof_session import (
        MethodProofSession,
        use_proof_session,
    )
    from test_basic_inequality_stage5c import mixed_case, rows

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy search or replay search called")

    monkeypatch.setattr(proof_kernel._Search, "need", forbidden)
    with use_proof_session(MethodProofSession()):
        target, first, _square, last = mixed_case(*names, k)
        a, b, c = names
        assert (
            close_bound(
                target, last, rows(f"{a}=sqrt(2)", f"{b}=sqrt(2)/2", f"{c}=sqrt(2)/{k}")
            )[0]
            == 4
        )
    assert first["certificate_bundle"]["method_application"]["local_rule_root_ref"]
    assert len(last["equalities"]) == 3
    monkeypatch.setattr(proof_kernel, "_run_request", forbidden)
    assert public_bound(replay_bound(target, json.loads(json.dumps(last)))) == last


def test_application_anchor_tampering_and_old_bound_rejected(monkeypatch):
    from copy import deepcopy

    from shuxueshuo_server.solver.math_kernel import proof_kernel
    from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        public_bound,
        verify_bound,
    )
    from shuxueshuo_server.solver.math_kernel.method_proof_session import (
        MethodProofSession,
        use_proof_session,
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from test_basic_inequality_stage5c import rows, target

    t = target("x+4/x", ["x>0"], ["x"])
    with use_proof_session(MethodProofSession()):
        bound = public_bound(verify_bound(t, rows("x+4/x>=4")))
        with pytest.raises(ProofFailure):
            verify_bound(t, rows("x+4/x>=4"), previous_bound=bound)
    monkeypatch.setattr(
        proof_kernel, "_run_request", lambda *a, **k: pytest.fail("replay searched")
    )
    for key, value in [
        ("application_id", "forged"),
        ("source_math", "x+5/x"),
        ("target_hash", "other"),
        ("local_rule_root_ref", "unknown"),
    ]:
        bad = deepcopy(bound)
        bad["certificate_bundle"]["method_application"][key] = value
        with pytest.raises((ProofFailure, ValueError)):
            replay_bound(t, bad)


def test_normalized_radical_bound_transport_uses_checked_identity(monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_kernel
    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof
    from test_scoped_proof_search_stage_d import context, prove

    monkeypatch.setattr(
        proof_kernel._Search, "need", lambda *a, **k: pytest.fail("legacy search")
    )
    ctx = context(["x<=1/(2*sqrt(3)-3)"], variables="x")
    result = prove("x<=1+2*sqrt(3)/3", ctx).result
    assert result.status == "proved", result
    assert "math.relation_transport" in {n["rule_id"] for n in result.proof["nodes"]}
    assert replay_proof(result.proof, ctx).status == "proved"
    assert prove("x<=1+sqrt(3)/3", ctx).result.status != "proved"


def test_exact_constant_search_cache_does_not_replace_checking():
    from copy import deepcopy

    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_expression,
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import (
        Arithmetic,
        ProofFailure,
        from_node,
    )
    from shuxueshuo_server.solver.math_kernel.proof_search import (
        SearchBudget,
        default_search_configuration,
    )
    from shuxueshuo_server.solver.math_kernel.proof_types import ProofLimits, _Budget
    from shuxueshuo_server.solver.math_kernel.real_proof_strategies import (
        SearchArithmetic,
    )

    limits = ProofLimits()
    budget = SearchBudget(limits, default_search_configuration()[2])
    search = SearchArithmetic(budget)
    value = from_node(parse_math_expression("sqrt(3)-sqrt(2)", {}).ast)
    first = search.constant_certificate(value)
    refinements = budget.counts["refinements"]
    second = search.constant_certificate(value)
    assert budget.counts["refinements"] == refinements > 0
    assert second == first
    first[1]["bits"] = 0
    assert search.constant_certificate(value) == second
    assert (
        Arithmetic(_Budget(limits)).constant_certificate(value, supplied=second[1])
        == second
    )
    bad = deepcopy(second[1])
    bad["bits"] = 0
    with pytest.raises(ProofFailure, match="isolation budget"):
        search.constant_certificate(value, supplied=bad)
    with pytest.raises(ProofFailure, match="isolation budget"):
        Arithmetic(_Budget(limits)).constant_certificate(value, supplied=bad)


def test_application_search_preserves_global_exhaustion(monkeypatch):
    from shuxueshuo_server.solver.math_kernel import amgm_application
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import verify_bound
    from shuxueshuo_server.solver.math_kernel.method_proof_session import (
        MethodProofSession,
        use_proof_session,
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from test_basic_inequality_stage5c import rows, target

    def exhausted(*args, **kwargs):
        raise ProofFailure("proof_search_exhausted", "session total exhausted")

    monkeypatch.setattr(amgm_application, "verify_local_application", exhausted)
    with use_proof_session(MethodProofSession()), pytest.raises(ProofFailure) as error:
        verify_bound(target("x+4/x", ["x>0"], ["x"]), rows("x+4/x>=4"))
    assert error.value.code == "proof_search_exhausted"


@pytest.mark.parametrize("protocol", ["scoped-facts/v2", "bound-conditions/v1", None])
def test_empty_v2_checkpoint_restores_only_with_matching_protocol(protocol):
    from types import SimpleNamespace

    from shuxueshuo_server.solver.math_kernel.proof_algebra import digest
    from shuxueshuo_server.solver.runtime.proof_fact_transactions import restore_facts

    payload = {
        "commits": [],
        "source_hash": "source",
        "committed_manifest_hash": digest(("source", [])),
    }
    if protocol is not None:
        payload["condition_protocol"] = protocol
    context = SimpleNamespace(proof_protocol="scoped-facts/v2", proof_facts=None)
    seed = SimpleNamespace(proof_fact_checkpoint=payload, call_results=())
    if protocol == "scoped-facts/v2":
        restore_facts(context, seed)
        assert context.proof_facts is None
    else:
        with pytest.raises(ValueError, match="condition protocol"):
            restore_facts(context, seed)


@pytest.mark.parametrize(
    "methods",
    [
        [],
        ["organize_expressions", "apply_two_term_amgm"],
        ["midpoint_point", "organize_expressions"],
    ],
)
def test_v2_requires_registered_single_method_adapter(methods):
    from types import SimpleNamespace

    from shuxueshuo_server.solver.runtime.method_proof_integration import (
        prepare_scoped_call,
    )

    compiled = SimpleNamespace(
        plans=[
            SimpleNamespace(invocations=[SimpleNamespace(method_id=m) for m in methods])
        ]
    )
    with pytest.raises(ValueError, match="single-Method proof adapter"):
        prepare_scoped_call(None, "call", compiled, None)


def test_v2_invocation_without_overlay_never_uses_legacy_search(tmp_path, monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_kernel
    from shuxueshuo_server.solver.runtime import method_proof_integration

    monkeypatch.setattr(
        method_proof_integration, "prepare_scoped_call", lambda *a: None
    )
    monkeypatch.setattr(
        proof_kernel._Search, "need", lambda *a, **k: pytest.fail("legacy fallback")
    )
    result, _ = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q30.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
        plan=FIXTURES / "basic-inequality-stage5c/q30.json",
        output=tmp_path / "missing-adapter",
        mode="recorded",
        proof_protocol="scoped-facts/v2",
    )
    assert result.status != "ok"
    assert (
        "no authorized proof adapter"
        in (tmp_path / "missing-adapter/attempt-1.blockers.json").read_text()
    )


def test_m01_premise_matching_checks_identity_and_is_order_independent():
    from types import SimpleNamespace

    import sympy as sp
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.proof_facts import (
        FactValidity,
        VerifiedMathFact,
    )
    from shuxueshuo_server.solver.runtime.method_proof_integration import (
        match_premise_fact,
    )

    symbols = {"x": sp.Symbol("x", real=True)}
    validity = FactValidity("problem")
    authority = SimpleNamespace(
        symbol_bindings=(("x", "problem/x"),), validity=validity
    )
    good = VerifiedMathFact("x>0", authority.symbol_bindings, validity, "relation", "a")
    duplicate = VerifiedMathFact(
        "x>0", authority.symbol_bindings, validity, "relation", "z"
    )
    other = VerifiedMathFact("x>0", (("x", "other/x"),), validity, "relation", "0")
    parsed = parse_math_relation("x>0", symbols)
    for facts in ([other, duplicate, good], [good, duplicate, other]):
        assert match_premise_fact(facts, parsed, symbols, authority) == good
    with pytest.raises(ValueError, match="no authorized producer"):
        match_premise_fact([other], parsed, symbols, authority)


def test_current_application_origin_is_one_submitted_row_and_checked():
    from copy import deepcopy

    from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
    from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        public_bound,
        target_context,
        verify_bound,
    )
    from shuxueshuo_server.solver.math_kernel.method_proof_session import (
        MethodProofSession,
        use_proof_session,
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from test_basic_inequality_stage5c import rows, target

    t = target("x+4/x", ["x>0"], ["x"])
    steps = rows("x>0", "4/x>0", "x+4/x>=4")
    context, _ = target_context(t)
    with use_proof_session(MethodProofSession()):
        evidence = public_bound(verify_bound(t, steps))
    app = evidence["certificate_bundle"]["method_application"]
    assert app["local_rule_origin"] == {
        "kind": "submitted_relation",
        "origin": parse_derivation(steps, context.symbols)[2].origin,
    }
    # Existing application/v1 records predate the optional origin field.
    from shuxueshuo_server.solver.math_kernel.proof_algebra import digest

    legacy = deepcopy(evidence)
    old_app = legacy["certificate_bundle"]["method_application"]
    old_app.pop("local_rule_origin")
    old_app.pop("application_id")
    old_app["application_id"] = digest(old_app)
    assert public_bound(replay_bound(t, legacy)) == legacy
    from types import SimpleNamespace

    from shuxueshuo_server.solver.runtime.proof_evidence_adapters import (
        validate_application_binding,
    )

    call = SimpleNamespace(
        method_id="apply_two_term_amgm",
        call_id="current",
        input_fingerprint="inputs",
        scope_id="problem",
    )
    for wrapper in (
        lambda x: x,
        lambda x: {"certificate_bundle": {"reciprocal_bound": x}},
    ):
        with pytest.raises(ProofFailure, match="local_rule_origin"):
            validate_application_binding(wrapper(legacy), call, "manifest")
    bad = deepcopy(evidence)
    bad["certificate_bundle"]["method_application"]["local_rule_origin"]["origin"] = (
        "other"
    )
    with pytest.raises(ProofFailure):
        replay_bound(t, bad)


def test_proof_backend_registration_is_exhaustive_and_unknown_is_rejected():
    from shuxueshuo_server.solver.runtime.method_proof_backends import (
        NATIVE_VALIDATION_METHODS,
        SCOPED_PROOF_METHODS,
        requires_scoped_proof,
    )
    from shuxueshuo_server.solver.runtime.methods import ALL_METHOD_SPEC_SOURCES

    assert not (SCOPED_PROOF_METHODS & NATIVE_VALIDATION_METHODS)
    assert {s.method_cls.method_id for s in ALL_METHOD_SPEC_SOURCES} == (
        SCOPED_PROOF_METHODS | NATIVE_VALIDATION_METHODS
    )
    with pytest.raises(ValueError, match="unregistered Method proof backend"):
        requires_scoped_proof("unregistered")


def test_v2_native_geometry_call_executes_multiple_invocations_without_proof_facts(
    monkeypatch,
):
    from types import SimpleNamespace

    import sympy as sp
    from shuxueshuo_server.solver.fixtures import load_problem_ir
    from shuxueshuo_server.solver.math_kernel import proof_kernel
    from shuxueshuo_server.solver.runtime.context import ContextBuilder
    from shuxueshuo_server.solver.runtime.context_inventory import (
        ContextInventoryBuilder,
    )
    from shuxueshuo_server.solver.runtime.executor import InvocationExecutor
    from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
    from shuxueshuo_server.solver.runtime.planner import RuleBasedStepPlannerV15
    from shuxueshuo_server.solver.runtime.proof_fact_transactions import (
        begin_call,
        finalize_call,
    )

    monkeypatch.setattr(
        proof_kernel._Search, "need", lambda *a, **k: pytest.fail("legacy search")
    )
    context = ContextBuilder().build(
        load_problem_ir("../internal/solver-fixtures/tj-2026-nankai-yimo-25.json")
    )
    context.proof_protocol = "scoped-facts/v2"
    specs = MethodSpecRegistry.load_from_code()
    signal = next(
        s
        for s in ContextInventoryBuilder().build(context, specs).planning_signals
        if s.signal_type == "constructible_right_angle_equal_length_point"
        and s.roles["target"] == "N"
    )
    plan = RuleBasedStepPlannerV15(specs).plan(context, signal)
    assert len(plan.invocations) == 2
    begin_call(context, "native", SimpleNamespace(plans=[plan]), None)
    result = InvocationExecutor(specs).execute_step(context, plan)
    assert result.checks and all(c.ok for c in result.checks)
    point = context.read_path(
        "$question.ii.points.N", from_scope_id="ii", expected_type="Point"
    ).value
    assert sp.simplify(point[0] - 2) == 0
    assert sp.simplify(point[1] - (1 - context.symbols["m"])) == 0
    assert finalize_call(context, (), ()) is None
    assert context.proof_facts is None and context.proof_fact_overlay is None
