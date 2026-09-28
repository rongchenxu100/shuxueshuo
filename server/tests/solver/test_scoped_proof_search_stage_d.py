"""Stage D: actual search/checker, bounded scheduling and authorized retrieval."""

import json
from dataclasses import replace
from unittest.mock import patch

import pytest
import sympy as sp
from shuxueshuo_server.solver.math_kernel import proof_kernel as legacy
from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
from shuxueshuo_server.solver.math_kernel.proof_algebra import (
    ProofFailure,
    from_node,
)
from shuxueshuo_server.solver.math_kernel.proof_checker import (
    DEFAULT_RULE_REGISTRY,
    RULESET_HASH,
    _document,
    replay_proof,
)
from shuxueshuo_server.solver.math_kernel.proof_fact_index import ProofFactIndex
from shuxueshuo_server.solver.math_kernel.proof_facts import (
    FactValidity,
    VerifiedMathFact,
)
from shuxueshuo_server.solver.math_kernel.proof_rule_registry import RulePackage
from shuxueshuo_server.solver.math_kernel.proof_search import (
    CandidateDescriptor,
    ProofStrategy,
    SearchScheduler,
    StrategyPackage,
    default_search_configuration,
    run_scheduled_request,
)
from shuxueshuo_server.solver.math_kernel.proof_search_session import ProofSearchSession
from shuxueshuo_server.solver.math_kernel.proof_types import (
    ProofContext,
    ProofLimits,
    ProofResult,
)
from test_scoped_proof_facts_stage_c import environment


def context(premises=(), variables="abx", **kwargs):
    symbols = {n: sp.Symbol(n, real=True) for n in variables}
    return ProofContext(
        symbols,
        {str(i): parse_math_relation(p, symbols) for i, p in enumerate(premises)},
        **kwargs,
    )


def prove(source, ctx, **kwargs):
    request = {
        "kind": "relation",
        "candidate": _document(parse_math_relation(source, ctx.symbols)),
    }
    return run_scheduled_request(ctx, request, **kwargs)


@pytest.mark.parametrize(
    "relation",
    [
        "x^2>=0",
        "a-b>0",
        "b*(a-b)<=a^2/4",
        "1/(b*(a-b))>=4/a^2",
        "x+4/x>=4",
        "(a-b)^2=a^2-2*a*b+b^2",
        "x^(-2)>0",
    ],
)
def test_real_strategies_and_search_free_replay(relation, monkeypatch):
    ctx = context(["a>b", "b>0", "x>0"])
    monkeypatch.setattr(
        legacy._Search, "core", lambda *a: pytest.fail("legacy fallback")
    )
    run = prove(relation, ctx)
    assert run.result.status == "proved", run.result
    assert run.result.proof["ruleset_hash"] == RULESET_HASH
    monkeypatch.setattr(
        SearchScheduler, "prove", lambda *a: pytest.fail("replay searched")
    )
    assert replay_proof(run.result.proof, ctx).status == "proved"


@pytest.mark.parametrize(
    "relation,premises",
    [
        ("x^2<0", ["x>0"]),
        ("1/x=1/x", []),
        ("1/x<0", ["x>0"]),
        ("1/(b*(a-b))<=4/a^2", ["a>b", "b>0"]),
        ("x+4/x>=5", ["x>0"]),
        ("(a-b)^2=a^2+b^2", []),
    ],
)
def test_incorrect_math_or_missing_domain_rejected(relation, premises):
    assert prove(relation, context(premises)).result.status != "proved"


def test_disabled_capability_does_not_match_and_old_certificate_still_replays():
    ctx = context(["x>0"])
    original = prove("x+4/x>=4", ctx)
    strategies, _rules, policy = default_search_configuration()
    disabled = tuple(
        r for r in policy.allowed_rules if "amgm" not in r and "product_bound" not in r
    )
    run = prove("x+4/x>=4", ctx, policy=replace(policy, allowed_rules=disabled))
    assert run.result.status != "proved"
    assert not {"sum_bound", "local_sum_bound", "squared_bound", "product_bound"} & {
        event["strategy"] for event in run.diagnostics["trace"]
    }
    assert replay_proof(original.result.proof, ctx).status == "proved"
    empty = replace(strategies, packages=())
    assert prove("x^2>=0", ctx, strategies=empty).result.code == "invalid_input"


def test_local_quota_does_not_refund_or_prevent_later_candidates():
    strategies, _rules, policy = default_search_configuration()
    policy = replace(policy, branch_reductions=2)

    def expensive(engine, goal, candidate):
        engine.budget.use("reductions", 3)

    slow = ProofStrategy(
        "exhausted", 0, 0, (">=",), (), lambda g, e: (CandidateDescriptor(),), expensive
    )
    package = replace(
        strategies.packages[0], strategies=(slow, *strategies.packages[0].strategies)
    )
    run = prove(
        "x^2>=0",
        context(),
        strategies=replace(strategies, packages=(package,)),
        policy=policy,
    )
    assert run.result.status == "proved"
    assert run.diagnostics["counts"]["reductions"] == 3
    assert run.diagnostics["trace"][0]["status"] == "strategy_budget_exhausted"
    limited = prove(
        "x^2>=0",
        context(limits=replace(ProofLimits(), reductions=2)),
        strategies=replace(strategies, packages=(package,)),
        policy=policy,
    )
    assert limited.result.code == "proof_search_exhausted"


def test_cycle_failure_is_not_permanent_and_trace_is_bounded():
    strategies, _, policy = default_search_configuration()

    def cycle(engine, goal, candidate):
        return engine.need(goal)

    cyclic = ProofStrategy(
        "cycle", 0, 0, (">=",), (), lambda g, e: (CandidateDescriptor(),), cycle
    )
    package = replace(
        strategies.packages[0], strategies=(cyclic, *strategies.packages[0].strategies)
    )
    run = prove(
        "x^2>=0",
        context(),
        strategies=replace(strategies, packages=(package,)),
        policy=replace(policy, trace_limit=1),
    )
    assert run.result.status == "proved"
    assert len(run.diagnostics["trace"]) == 1
    assert run.diagnostics["trace_dropped"] > 0


def facts_for(ctx):
    bindings = tuple((n, "symbol/" + n) for n in ctx.symbols)
    return tuple(
        VerifiedMathFact(
            p.source, bindings, FactValidity(ctx.scope_id), "relation", key
        )
        for key, p in ctx.premises.items()
    ), bindings


def test_dedup_constant_filter_and_irrelevant_fact_invariance():
    ctx = context(["x>0"], variables="xy")
    base, bindings = facts_for(ctx)
    duplicates = tuple(replace(base[0], source=f"copy:{i}") for i in range(50))
    unrelated = tuple(
        VerifiedMathFact(
            f"y>{-i}", bindings, FactValidity(ctx.scope_id), "relation", f"noise:{i}"
        )
        for i in range(150)
    )
    constants = (
        VerifiedMathFact(
            "25>0",
            bindings,
            FactValidity(ctx.scope_id),
            "relation",
            "constant",
            proof_ref="checked-constant",
        ),
    )
    index = ProofFactIndex((*base, *duplicates, *unrelated, *constants), ctx.symbols)
    assert index.duplicates == 50 and index.filtered_constants == 1

    def search(facts):
        return ProofSearchSession().prove(
            "1/x>0",
            facts=facts,
            symbols=ctx.symbols,
            bindings=bindings,
            scope_id=ctx.scope_id,
            manifest_hash="manifest",
            authority_hash="authority",
        )

    before, after = search(base), search((*base, *unrelated, *constants))
    assert before.result.status == after.result.status == "proved"
    assert before.result.proof == after.result.proof
    assert before.diagnostics["counts"] == after.diagnostics["counts"]
    assert len(after.context.premises) == 1
    reversed_index = ProofFactIndex(tuple(reversed((*base, *unrelated))), ctx.symbols)
    tree = from_node(parse_math_relation("1/x>0", ctx.symbols).ast)
    assert index.query(tree, bindings)[0] == reversed_index.query(tree, bindings)[0]


def test_session_cache_is_manifest_authority_policy_and_overlay_bound():
    ctx = context(["x>0"])
    facts, bindings = facts_for(ctx)
    session = ProofSearchSession()
    kwargs = {
        "facts": facts,
        "symbols": ctx.symbols,
        "bindings": bindings,
        "scope_id": ctx.scope_id,
        "manifest_hash": "one",
        "authority_hash": "one",
    }
    first = session.prove("x!=0", **kwargs)
    assert first.result.status == "proved"
    assert session.prove("x!=0", **kwargs).diagnostics["session_cache_hit"]
    assert not session.prove("x!=0", **{**kwargs, "manifest_hash": "two"}).diagnostics[
        "session_cache_hit"
    ]
    assert not session.prove("x!=0", **{**kwargs, "authority_hash": "two"}).diagnostics[
        "session_cache_hit"
    ]
    # A failed domain proof cannot reuse the old success with missing premises.
    assert session.prove("x!=0", **{**kwargs, "facts": ()}).result.status != "proved"


def test_scope_retrieval_publishes_real_proof_reads_and_replays(monkeypatch):
    store = environment()
    one = store.begin("first")
    one.prove_scheduled("x!=0", semantic_kind="domain")
    first = store.commit(one, "first")
    two = store.begin("second")
    two.prove_scheduled("1/x>0")
    second = store.commit(two, "second")
    assert second.dependencies == ("first",)
    assert first.facts[0].fact_id in second.proof_reads
    other = store.begin("sibling")
    with pytest.raises(ProofFailure):
        other.prove_scheduled("1/x>0")
    monkeypatch.setattr(
        SearchScheduler, "prove", lambda *a: pytest.fail("restore searched")
    )
    fresh = environment()
    fresh.restore(store.to_payload(), {"first": "first", "second": "second"})
    assert fresh.to_payload() == store.to_payload()


def test_snapshot_cache_is_authorized_and_independent_restore_rechecks(monkeypatch):
    store = environment()
    first = store.begin("first")
    first.prove_scheduled("x!=0")
    store.commit(first, "first")
    counter = []
    original = type(store)._restore_one

    def watched(self, payload):
        counter.append(payload["call_id"])
        return original(self, payload)

    monkeypatch.setattr(type(store), "_restore_one", watched)
    store.begin("second")
    store.fork(store.context).begin("second")
    assert counter == []
    fresh = environment()
    fresh.restore(store.to_payload(), {"first": "first"})
    assert counter == ["first"]
    # Cached manifest cannot hide changed host call authority.
    store.calls = (
        replace(store.calls[0], input_fingerprint="changed"),
        *store.calls[1:],
    )
    with pytest.raises(ValueError, match="binding changed"):
        store.begin("second")


def test_extension_strategy_package_uses_own_checker():
    strategies, rules, policy = default_search_configuration()
    identity = ("test-structural/v1", "b" * 64)
    visits = []

    def check(proof, ctx, *, budget=None):
        visits.append("checked")
        if proof.get("value") != 7:
            return ProofResult("failed", code="invalid_proof")
        return ProofResult("proved", proof=proof)

    class Engine:
        def __init__(self, context, request, **kwargs):
            self.budget = kwargs["budget"]

        def checkpoint(self):
            return ()

        def rollback(self, saved):
            pass

        def requested_since(self, saved):
            return ()

        def dependencies(self, root):
            return ()

        def check_candidate(self, root, goal):
            if root != 7:
                raise ProofFailure("invalid_proof", "bad candidate")

        def run(self):
            value = self.scheduler.prove(self, ("test",))
            return {
                "schema_version": identity[0],
                "ruleset_hash": identity[1],
                "nodes": [{"rule_id": "test.seven"}],
                "value": value,
            }

    strategy = ProofStrategy(
        "seven",
        0,
        0,
        ("test",),
        ("test.seven",),
        lambda g, e: (CandidateDescriptor(),),
        lambda e, g, c: 7,
    )
    package = StrategyPackage(*identity, (strategy,), Engine)
    run = run_scheduled_request(
        context(),
        {},
        strategies=strategies.with_package(package),
        rules=rules.with_package(RulePackage(*identity, ("test.seven",), check)),
        policy=replace(
            policy, package_identity=identity, allowed_rules=("test.seven",)
        ),
    )
    assert run.result.status == "proved" and visits == ["checked"]
    assert (
        DEFAULT_RULE_REGISTRY.resolve(*policy.package_identity).ruleset_hash
        == RULESET_HASH
    )


@pytest.mark.parametrize("fixture_key", ["2", "3"])
def test_frozen_budget_derivations_have_no_legacy_fallback(fixture_key, monkeypatch):
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import verify_bound
    from tools.proof_search_baseline import ROOT, verify_assets

    manifest = verify_assets()
    sample = next(
        c
        for c in manifest["cases"]
        if c["key"] == fixture_key and c["kind"] == "local_bound"
    )
    steps = json.loads((ROOT / sample["input"]).read_text())[fixture_key]
    captured = []
    original = legacy._Search.__init__

    def observe(self, ctx, request, **kwargs):
        captured.append((ctx, request))
        return original(self, ctx, request, **kwargs)

    with patch.object(legacy._Search, "__init__", observe):
        verify_bound(manifest["local_target"], steps)
    monkeypatch.setattr(
        legacy._Search, "core", lambda *a: pytest.fail("legacy fallback")
    )
    assert captured
    for ctx, request in captured:
        run = run_scheduled_request(ctx, request)
        assert run.result.status == "proved", (request, run.result)
        assert replay_proof(run.result.proof, ctx).status == "proved"


@pytest.mark.parametrize(
    "profile",
    [
        "default",
        "elimination",
        "substitution",
        "elimination_after_substitution",
        "substitution_after_elimination",
    ],
)
def test_effective_profiles_are_preserved(profile):
    from shuxueshuo_server.solver.math_kernel.proof_types import _Budget
    from tools.proof_search_baseline import profiles

    limits = ProofLimits(**profiles()[profile])
    ctx = context(["a>b", "b>0"])
    run = prove("1/(b*(a-b))>=4/a^2", ctx, budget=_Budget(limits))
    assert run.result.status == "proved"
    assert run.diagnostics["counts"]["attempts"] <= limits.attempts
    assert replay_proof(run.result.proof, ctx).status == "proved"


def test_failed_candidate_rolls_back_checked_nodes_and_local_cache():
    strategies, _, _policy = default_search_configuration()

    def temporary(engine, goal, candidate):
        engine.need(
            (">=", ("pow", ("symbol", "x"), ("rat", "2", "1")), ("rat", "0", "1"))
        )
        raise ProofFailure("proof_missing", "discard this branch")

    strategy = ProofStrategy(
        "aaa_temporary",
        0,
        0,
        (">",),
        (),
        lambda g, e: (CandidateDescriptor(),),
        temporary,
    )
    package = replace(
        strategies.packages[0],
        strategies=(strategy, *strategies.packages[0].strategies),
    )
    run = prove(
        "x>0", context(["x>0"]), strategies=replace(strategies, packages=(package,))
    )
    assert run.result.status == "proved"
    assert {n["rule_id"] for n in run.result.proof["nodes"]} == {
        "math.guard",
        "math.given",
    }
    assert run.diagnostics["counts"]["nodes"] > len(run.result.proof["nodes"])


def test_original_constant_contradiction_is_not_filtered():
    ctx = context(["1=0"])
    facts, bindings = facts_for(ctx)
    run = ProofSearchSession().prove(
        "x=x",
        facts=facts,
        symbols=ctx.symbols,
        bindings=bindings,
        scope_id=ctx.scope_id,
        manifest_hash="one",
        authority_hash="one",
    )
    assert run.result.status != "proved"
    assert run.result.code == "inconsistent_premises"


def test_retrieval_follows_bounded_equation_chain():
    ctx = context(["x=y", "y=z", "z=w", "w>0"], variables="xyzw")
    facts, bindings = facts_for(ctx)
    run = ProofSearchSession().prove(
        "x>0",
        facts=facts,
        symbols=ctx.symbols,
        bindings=bindings,
        scope_id=ctx.scope_id,
        manifest_hash="one",
        authority_hash="one",
    )
    assert run.result.status == "proved", run.result
    assert len(run.context.premises) == 4


def test_search_metadata_replays_without_current_policy_and_detects_tampering(
    monkeypatch,
):
    store = environment()
    overlay = store.begin("first")
    overlay.prove_scheduled("x!=0")
    store.commit(overlay, "first")
    payload = store.to_payload()
    metadata = payload["commits"][0]["records"][0]["search"]
    assert metadata["policy"]["version"] == "layered-search/v1"
    monkeypatch.setattr(
        SearchScheduler, "prove", lambda *a: pytest.fail("replay searched")
    )
    fresh = environment()
    fresh.restore(payload, {"first": "first"})
    metadata["manifest_hash"] = "changed"
    with pytest.raises(ValueError, match="metadata changed"):
        environment().restore(payload, {"first": "first"})


def test_arithmetic_budget_and_ancestor_quota_unwind():
    _strategies, _, policy = default_search_configuration()
    run = prove(
        "(a-b)^2=a^2-2*a*b+b^2",
        context(),
        policy=replace(policy, arithmetic_operations=1),
    )
    assert run.result.code == "proof_search_exhausted"
    assert run.diagnostics["counts"]["arithmetic_operations"] == 2
    from shuxueshuo_server.solver.math_kernel.proof_search import (
        BranchBudgetExhausted,
        SearchBudget,
    )

    budget = SearchBudget(ProofLimits(), replace(policy, branch_attempts=2))
    with budget.branch() as outer:
        budget.use("attempts", 2)
        with budget.branch() as inner:
            with pytest.raises(BranchBudgetExhausted) as failure:
                budget.use("attempts")
            assert failure.value.owner is outer and failure.value.owner is not inner
    assert budget.counts["attempts"] == 3
    # Leaving the expired branch restores availability, never spent charges.
    with budget.branch():
        budget.use("attempts")
    assert budget.counts["attempts"] == 4


def test_snapshot_cache_cannot_hide_mutated_source_authority():
    store = environment()
    overlay = store.begin("first")
    overlay.prove_scheduled("x!=0")
    store.commit(overlay, "first")
    store.source_context.premises["positive"] = parse_math_relation(
        "x<0", store.source_context.symbols
    )
    with pytest.raises(ValueError, match="committed manifest changed"):
        store.begin("second")


@pytest.mark.parametrize("fixture_key", ["2", "3"])
def test_frozen_rows_use_one_authorized_retrieving_session(fixture_key, monkeypatch):
    from shuxueshuo_server.solver.math_kernel import SympyKernel
    from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import target_context
    from shuxueshuo_server.solver.problem_models import ProblemIR
    from shuxueshuo_server.solver.runtime.context import RuntimeContext
    from shuxueshuo_server.solver.runtime.scoped_proof_facts import (
        ProofCallAuthority,
        ScopedProofFacts,
    )
    from tools.proof_search_baseline import ROOT, verify_assets

    manifest = verify_assets()
    sample = next(
        c
        for c in manifest["cases"]
        if c["key"] == fixture_key and c["kind"] == "local_bound"
    )
    ctx, _ = target_context(manifest["local_target"])
    bindings = tuple((name, "problem/" + name) for name in ctx.symbols)
    runtime = RuntimeContext(
        ProblemIR("frozen-session", "", "", list(ctx.symbols)),
        SympyKernel(),
        ctx.symbols,
    )
    call = ProofCallAuthority(
        "bound",
        "problem",
        "verified_relation",
        bindings,
        FactValidity("problem"),
        "frozen-input",
    )
    store = ScopedProofFacts(runtime, ctx, bindings, (call,))
    overlay = store.begin("bound")
    rows = parse_derivation(
        json.loads((ROOT / sample["input"]).read_text())[fixture_key], ctx.symbols
    )
    monkeypatch.setattr(
        legacy._Search, "core", lambda *a: pytest.fail("session used legacy search")
    )
    for row in rows:
        overlay.prove_scheduled(row.parsed.source)
    commit = store.commit(overlay, "checked-output")
    assert len(commit.records_json) > 0
    assert overlay._search_session.budget.counts["attempts"] <= ctx.limits.attempts
    assert overlay._search_session.budget.counts["reductions"] <= ctx.limits.reductions
    monkeypatch.setattr(
        SearchScheduler, "prove", lambda *a: pytest.fail("restore searched")
    )
    fresh = ScopedProofFacts(runtime, ctx, bindings, (call,))
    fresh.restore(store.to_payload(), {"bound": "checked-output"})
    assert fresh.to_payload() == store.to_payload()


def test_review_symbol_adjacency_excludes_unrelated_call_bindings():
    ctx = context(["x>0", "y>0"], variables="xy")
    facts, bindings = facts_for(ctx)
    assert facts[0].symbol_bindings == (("x", dict(bindings)["x"]),)
    index = ProofFactIndex(facts, ctx.symbols)
    selected, diagnostic = index.query(
        from_node(parse_math_relation("x!=0", ctx.symbols).ast), bindings
    )
    assert selected == (facts[0].fact_id,)
    assert diagnostic["matched"] == 1 < diagnostic["available"]
    assert not diagnostic["truncated"]


def test_review_unique_fact_limit_is_after_deduplication():
    ctx = context(["x>0", "x>1"])
    facts, _ = facts_for(ctx)
    copies = tuple(replace(facts[0], source=f"duplicate:{i}") for i in range(4100))
    index = ProofFactIndex(copies, ctx.symbols, limit=1)
    assert len(index.facts) == 1 and index.duplicates == 4099
    with pytest.raises(ProofFailure, match="unique authorized fact index limit"):
        ProofFactIndex((*copies, facts[1]), ctx.symbols, limit=1)


def test_review_local_definition_fact_does_not_poison_search():
    store = environment()
    overlay = store.begin("first")
    root = overlay.view.facts[0]
    conditional = replace(
        root,
        relation="x!=0",
        source="definition-local",
        validity=replace(root.validity, definition_refs=("definition:local",)),
    )
    overlay._candidates.append(conditional)
    overlay.prove_scheduled("x!=0")
    record = json.loads(overlay._records[-1])
    assert conditional.fact_id not in record["fact_ids"]
    assert root.fact_id in record["fact_ids"]


def test_review_registry_structure_and_callback_replacement_invalidate_memo():
    store = environment()
    first = store.begin("first")
    first.prove_scheduled("x!=0")
    store.commit(first, "first")
    before = store._verification_key()
    old = store.registry
    kind = old.kinds[0]
    store.registry = replace(
        old,
        kinds=(replace(kind, publishers=(*kind.publishers, "another")), *old.kinds[1:]),
    )
    assert store._verification_key() != before
    assert not store._verified_snapshots

    # Same qualified name is not sufficient authority for different closures.
    def validator(allowed):
        return lambda fact: allowed

    a, b = validator(True), validator(False)
    store.registry = replace(old, kinds=(replace(kind, publishable=a), *old.kinds[1:]))
    key = store._verification_key()
    store._verified_snapshots.add(key)
    store.registry = replace(old, kinds=(replace(kind, publishable=b), *old.kinds[1:]))
    assert not store.fork(store.context)._verified_snapshots
    assert store._verification_key() == key
    assert not store._verified_snapshots


def test_review_match_only_evaluates_selected_strategy(monkeypatch):
    from types import SimpleNamespace

    from shuxueshuo_server.solver.math_kernel import real_proof_strategies as real

    package = real.real_strategy_package()

    def unexpected(*args):
        pytest.fail("unrelated structural predicate was evaluated")

    monkeypatch.setattr(real, "_factors", unexpected)
    monkeypatch.setattr(real, "walk", unexpected)
    monkeypatch.setattr(real, "names", unexpected)
    goal = ("!=", ("symbol", "x"), ("rat", 0, 1))
    strategy = next(s for s in package.strategies if s.strategy_id == "strict_nonzero")
    assert strategy.match(goal, SimpleNamespace(premises={"x": goal}))


def test_review_request_candidate_exhaustion_allows_context_widening():
    strategies, rules, policy = default_search_configuration()
    policy = replace(policy, candidate_limit=2)

    def match(goal, engine):
        return tuple(
            CandidateDescriptor(str(i))
            for i in range(3 if len(engine.premises) <= 4 else 1)
        )

    # Exercise real request queue exhaustion in a smaller context, then actual
    # checker-validated proof in the expanded context; no synthetic error result.
    original = next(
        s for s in strategies.packages[0].strategies if s.strategy_id == "given"
    )
    strategy = replace(original, match=match)
    package = replace(strategies.packages[0], strategies=(strategy,))
    session = ProofSearchSession(
        policy=policy, strategies=replace(strategies, packages=(package,)), rules=rules
    )
    ctx = context(["x>0", "x>-1", "x>-2", "x>-3", "x>-4"])
    facts, bindings = facts_for(ctx)
    result = session.prove(
        "x>0",
        facts=facts,
        symbols=ctx.symbols,
        bindings=bindings,
        scope_id=ctx.scope_id,
        manifest_hash="snapshot",
        authority_hash="authority",
    )
    assert result.result.status == "proved", result.result
    assert len(result.diagnostics["attempts"]) == 2
    assert result.diagnostics["attempts"][0]["candidates"] == 0
