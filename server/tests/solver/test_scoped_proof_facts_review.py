"""Runtime and teaching integration regressions from the stage C review."""

import json
from dataclasses import replace

import pytest
import sympy as sp
from shuxueshuo_server.solver.math_kernel.proof_facts import (
    FactValidity,
    default_fact_kinds,
)
from shuxueshuo_server.solver.math_kernel.proof_types import ProofContext
from shuxueshuo_server.solver.runtime import proof_fact_transactions as bridge
from shuxueshuo_server.solver.runtime.scoped_proof_facts import (
    ProofCallAuthority,
    ScopedProofFacts,
)
from test_scoped_proof_facts_stage_c import environment, publish


def test_irrelevant_symbols_do_not_change_visibility_or_statement_identity():
    store = environment()
    original = store.snapshot.roots[0]
    other = replace(
        original,
        symbol_bindings=(*original.symbol_bindings, ("unused", "different/id")),
    )
    assert other.symbol_bindings == original.symbol_bindings
    assert other.statement_key == original.statement_key
    producer = replace(
        store.calls[0], symbol_bindings=(*store.bindings, ("unused", "extra/id"))
    )
    store = ScopedProofFacts(
        store.context, store.source_context, store.bindings, (producer, store.calls[1])
    )
    fact = publish(store).facts[0]
    assert fact.symbol_bindings == store.bindings
    assert fact in store.begin("second").view.facts


@pytest.mark.parametrize("nonempty", [False, True])
def test_enabled_facts_build_real_teaching_snapshot_without_extra_actions(
    monkeypatch, nonempty
):
    from _problem_planning_support import cached_planning_binding_fixture
    from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
    from shuxueshuo_server.solver.lesson_authoring_support import CASE_ID
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
    from shuxueshuo_server.solver.runtime.proof_fact_evidence import (
        ProofFactsExecutionEvidence,
    )
    from test_verified_functional_plan_execution import _execution_evidence

    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    bundle, *_ = cached_planning_binding_fixture(CASE_ID)

    def solve():
        runtime = RuntimeOrchestrator(
            family_registry=config.build_family_registry(),
            default_planner_provider=config.build_default_planner_provider(),
            max_attempts=config.max_llm_attempts,
            proof_protocol="bound-conditions/v1", # synthetic C-stage bridge injection
        )
        result = runtime.solve_verified(bundle)
        assert result.status == "ok", result.errors
        return runtime.last_success_artifacts

    baseline = ExplanationSnapshotBuilder().build(solve()).to_payload()
    begin = bridge.begin_call
    attached = []

    def enable(branch, call_id, compiled, graph):
        if branch.proof_facts is None:
            node = next(c for c in graph.calls if c.call_id == call_id)
            method = compiled.plans[0].invocations[0].method_id
            grant = ProofCallAuthority(
                call_id,
                node.declared_scope_id,
                method,
                (("x", "test/universal/x"),),
                FactValidity(node.declared_scope_id),
                bridge.call_fingerprint(compiled),
            )
            branch.proof_facts = ScopedProofFacts(
                branch,
                ProofContext({"x": sp.Symbol("x", real=True)}, {}, scope_id="problem"),
                grant.symbol_bindings,
                (grant,),
                registry=default_fact_kinds((method,)),
            )
            attached.append(call_id)
        begin(branch, call_id, compiled, graph)
        if branch.proof_fact_overlay is not None and nonempty:
            branch.proof_fact_overlay.prove("x^2>=0", semantic_kind="domain")

    monkeypatch.setattr(bridge, "begin_call", enable)
    artifacts = solve()
    assert attached
    assert any(
        isinstance(e, ProofFactsExecutionEvidence)
        for e in _execution_evidence(artifacts.verified_functional_execution.root_scope)
    )
    snapshot = ExplanationSnapshotBuilder().build(artifacts).to_payload()
    for key in ("root_scope", "evidence", "answers"):
        assert snapshot[key] == baseline[key]
    assert "scoped-proof-commit" not in json.dumps(snapshot)


def test_scope_retry_reexecutes_independent_calls_after_replaced_middle_scope(
    tmp_path, monkeypatch
):
    from _problem_planning_support import planning_binding_fixture
    from _scoped_functional_plan_support import load_v2_fixture_payload
    from shuxueshuo_server.solver.runtime.context import ContextBuilder
    from shuxueshuo_server.solver.runtime.functional_goal_execution import (
        ScopedFunctionalGoalExecutionService,
    )
    from shuxueshuo_server.solver.runtime.functional_scope_retry import (
        FunctionalScopeRetryAuthority,
        build_scope_retry_restore_seed,
    )
    from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
        scoped_functional_plan_id,
    )

    case = "tj-2026-nankai-yimo-25"
    fixture = planning_binding_fixture(tmp_path, case=case)
    raw = json.dumps(load_v2_fixture_payload(case))

    def execute(context, seed=None, raw_plan=None):
        return ScopedFunctionalGoalExecutionService().execute_raw_json(
            raw_plan or raw,
            inputs=fixture[3],
            planning_context=fixture[1],
            problem_binding_catalog=fixture[7],
            handle_registry=fixture[5],
            context=context,
            planner_state_context=fixture[6],
            problem_payload=fixture[4],
            restored_seed=seed,
        )

    baseline = execute(ContextBuilder().build(fixture[2]))
    assert baseline.verified_execution is not None
    report = baseline.replay.transactional_execution_report
    nodes = {c.call_id: c for c in report.graph.calls}
    # Three real Methods in separate scopes, with an independent later sibling.
    chosen = tuple(
        next(
            c
            for c in report.compiled_calls
            if nodes[c.call_id].declared_scope_id == scope
            and len(c.plans[0].invocations) == 1
        )
        for scope in ("i", "ii_1", "ii_2")
    )
    grants = tuple(
        ProofCallAuthority(
            c.call_id,
            nodes[c.call_id].declared_scope_id,
            c.plans[0].invocations[0].method_id,
            (("x", "test/universal/x"),),
            FactValidity(nodes[c.call_id].declared_scope_id),
            bridge.call_fingerprint(c),
        )
        for c in chosen
    )
    begin = bridge.begin_call
    executed = []

    def with_proof(branch, call_id, compiled, graph):
        executed.append(call_id)
        begin(branch, call_id, compiled, graph)
        if branch.proof_fact_overlay is not None:
            branch.proof_fact_overlay.prove("x^2>=0", semantic_kind="domain")

    monkeypatch.setattr(bridge, "begin_call", with_proof)

    def context():
        result = ContextBuilder().build(fixture[2])
        result.proof_facts = ScopedProofFacts(
            result,
            ProofContext({"x": sp.Symbol("x", real=True)}, {}, scope_id="problem"),
            grants[0].symbol_bindings,
            grants,
            registry=default_fact_kinds(tuple(g.method_id for g in grants)),
        )
        return result

    initial = execute(context())
    assert initial.verified_execution is not None, initial.to_payload()
    plan = initial.canonical_plan
    authority = FunctionalScopeRetryAuthority(
        plan,
        scoped_functional_plan_id(plan),
        initial.checkpoint.checkpoint_id,
        ("ii_1",),
    )
    # Replace B's actual inputs: segment MN and NM give the same length, but
    # source bindings differ and this call must be executed again.
    from _functional_scope_retry_support import step

    revised = json.loads(raw)
    middle = step(revised, grants[1].call_id)
    middle["args"]["p1"], middle["args"]["p2"] = (
        middle["args"]["p2"],
        middle["args"]["p1"],
    )
    revised_raw = json.dumps(revised)
    revised_baseline = execute(ContextBuilder().build(fixture[2]), raw_plan=revised_raw)
    assert revised_baseline.verified_execution is not None
    next_compiled = {
        c.call_id: c
        for c in revised_baseline.replay.transactional_execution_report.compiled_calls
    }
    grants = tuple(
        replace(g, input_fingerprint=bridge.call_fingerprint(next_compiled[g.call_id]))
        for g in grants
    )
    seed = build_scope_retry_restore_seed(
        authority, initial, next_plan=revised_baseline.canonical_plan
    )
    assert grants[0].call_id in seed.call_ids
    assert grants[1].call_id not in seed.call_ids
    assert grants[2].call_id not in seed.call_ids  # reexecute even though independent
    executed.clear()
    repaired = execute(context(), seed, revised_raw)
    assert repaired.verified_execution is not None, repaired.to_payload()
    assert grants[0].call_id not in executed
    assert grants[1].call_id in executed and grants[2].call_id in executed
    assert (
        len(
            repaired.replay.transactional_execution_report.runtime_context.proof_facts.snapshot.commits
        )
        == 3
    )


def test_scope_retry_invalidates_a_consumer_connected_only_by_proof_reads(monkeypatch):
    from types import SimpleNamespace as NS

    from shuxueshuo_server.solver.math_kernel.proof_facts import canonical
    from shuxueshuo_server.solver.runtime.functional_scope_retry import (
        build_scope_retry_restore_seed,
    )
    from shuxueshuo_server.solver.runtime.proof_fact_evidence import (
        ProofFactsExecutionEvidence,
    )

    store = environment()
    publish(store)
    b = store.begin("second")
    b.prove("x>0", [store.snapshot.roots[0].fact_id])
    producer = store.commit(b, "second")
    c = store.begin("third")
    c.prove("x>0", [producer.facts[0].fact_id])
    consumer = store.commit(c, "third")
    proof = ProofFactsExecutionEvidence(
        "third", store.snapshot.source_hash, canonical(consumer.to_payload())
    )
    ids = ("first", "second", "third")

    def scope(name, steps=(), children=()):
        return NS(
            scope_ref=name,
            steps=tuple(NS(step_id=s) for s in steps),
            children=children,
            goals=(),
        )

    plan = NS(
        root_scope=scope(
            "root",
            ("first",),
            (scope("editable", ("second",)), scope("closed", ("third",))),
        ),
        steps=tuple(NS(step_id=s) for s in ids),
    )
    root = NS(
        scope_steps=(NS(step_id="third", evidence=(proof,)),), goals=(), children=()
    )
    seed = NS(call_ids=ids, proof_fact_checkpoint=store.to_payload())
    restore_state = NS(runtime_seed=seed, seed_for_calls=lambda selected: selected)
    execution = NS(
        checkpoint=NS(root_scope=root, restore_state=restore_state),
        replay=NS(functional_reconciliation=NS(dependency_graph={s: () for s in ids})),
    )
    selection_before_prefix = []
    retain = bridge.retained_proof_prefix

    def capture(payload, selected, order):
        selection_before_prefix.append(selected)
        return retain(payload, selected, order)

    monkeypatch.setattr(bridge, "retained_proof_prefix", capture)
    restored = build_scope_retry_restore_seed(
        NS(base_plan=plan, editable_scope_refs=("editable",)), execution, next_plan=plan
    )
    assert selection_before_prefix == [frozenset({"first"})]
    assert restored == {"first"}


def test_certificate_import_retains_validity_requirements():
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.proof_kernel import prove_relation

    store = environment()
    session = store.begin("first")
    candidate = session.prove("x>0", [store.snapshot.roots[0].fact_id])[0]
    # Mutating an admitted fact cannot widen its definition authority.
    # Reject before importing it into any subsequent certificate.
    session._candidates[0] = replace(
        candidate, validity=FactValidity("q", definition_refs=("definition:d",))
    )
    context = ProofContext(
        store.source_context.symbols,
        {"c0": parse_math_relation("x>0", store.source_context.symbols)},
    )
    proof = prove_relation(parse_math_relation("x!=0", context.symbols), context).proof
    with pytest.raises(ValueError, match="verified evidence was modified"):
        session.admit_certificate(
            proof,
            context,
            {"c0": session._candidates[0].fact_id},
            ("expression_rewrite", "verify_chain", "c{i}"),
        )
    assert not store.snapshot.commits


def test_proof_output_hash_ignores_only_runtime_rebinding_metadata():
    from types import SimpleNamespace as NS

    source = {
        "goal_unit_ids": ["old"],
        "call_binding_signature": "old-signature",
        "input_source_unit_ids": ["source:1"],
        "problem_revision_id": "revision:1",
    }

    def value(content=1, provenance=source):
        return NS(
            to_payload=lambda: {
                "value": content,
                "problem_source_provenance": provenance,
                "state_version": "v1",
            }
        )

    original = bridge.proof_output_hash([], [value()])
    rebound = {
        **source,
        "goal_unit_ids": ["new"],
        "call_binding_signature": "new-signature",
    }
    assert bridge.proof_output_hash([], [value(provenance=rebound)]) == original
    assert bridge.proof_output_hash([], [value(2)]) != original
    assert (
        bridge.proof_output_hash(
            [], [value(provenance={**source, "input_source_unit_ids": ["source:2"]})]
        )
        != original
    )
    assert (
        bridge.proof_output_hash(
            [], [value(provenance={**source, "problem_revision_id": "revision:2"})]
        )
        != original
    )
