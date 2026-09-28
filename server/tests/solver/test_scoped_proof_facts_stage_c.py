"""Scope authority and transactional fact reuse, with actual mathematical proofs."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
import sympy as sp
from shuxueshuo_server.solver.math_kernel import SympyKernel, proof_kernel
from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
from shuxueshuo_server.solver.math_kernel.proof_facts import (
    ConditionalRequirement,
    FactKind,
    FactValidity,
    canonical,
)
from shuxueshuo_server.solver.math_kernel.proof_types import ProofContext
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import RuntimeScope
from shuxueshuo_server.solver.runtime.proof_evidence_adapters import (
    PREMISE_POLICIES,
    premise_policy,
)
from shuxueshuo_server.solver.runtime.scoped_proof_facts import (
    ProofCallAuthority,
    ScopedProofFacts,
)


def environment():
    symbols = {"x": sp.Symbol("x", real=True)}
    runtime = RuntimeContext(
        ProblemIR("facts-test", "", "", ["x"]), SympyKernel(), symbols
    )
    for scope, parent in [("q", "problem"), ("other", "problem"), ("child", "q")]:
        runtime.add_scope(RuntimeScope(scope, "question", parent_id=parent))
    context = ProofContext(
        symbols, {"positive": parse_math_relation("x>0", symbols)}, scope_id="q"
    )
    bindings = (("x", "q/object/x"),)

    def grant(name, scope="q", **kwargs):
        return ProofCallAuthority(
            name,
            scope,
            "verified_relation",
            bindings,
            FactValidity(scope),
            "input:" + name,
            **kwargs,
        )

    calls = (
        grant("first"),
        grant("second"),
        grant("third", "child"),
        grant("sibling", "other"),
        grant("parent", "problem"),
    )
    return ScopedProofFacts(runtime, context, bindings, calls)


def publish(store, call="first"):
    overlay = store.begin(call)
    root = overlay.view.facts[0]
    overlay.prove("x!=0", [root.fact_id], semantic_kind="domain")
    return store.commit(overlay, "outputs:" + call)


def test_real_cross_call_import_and_independent_replay(monkeypatch):
    store = environment()
    first = publish(store)
    next_call = store.begin("second")
    result = next_call.prove(
        "1/x>0",
        [first.facts[0].fact_id, store.snapshot.roots[0].fact_id],
        semantic_kind="domain",
    )
    assert result
    second = store.commit(next_call, "outputs:second")
    assert first.facts[0].fact_id in second.proof_reads
    assert second.dependencies == ("first",)
    assert store.dependency_closure(["second"]) == {"first", "second"}
    payload = json.loads(json.dumps(store.to_payload()))
    monkeypatch.setattr(
        proof_kernel._Search, "need", lambda *a, **k: pytest.fail("replay searched")
    )
    restored = environment()
    restored.restore(
        payload, {c.call_id: c.output_hash for c in store.snapshot.commits}
    )
    assert restored.to_payload() == payload


def test_private_overlay_failed_proof_and_closed_commit():
    store = environment()
    first = store.begin("first")
    candidate = first.prove("x!=0", [first.view.facts[0].fact_id])[0]
    second = store.begin("second")
    with pytest.raises(ValueError, match="not committed"):
        second.prove("x!=0", [candidate.fact_id])
    before = store.to_payload()
    with pytest.raises(ValueError):
        first.prove("x<0", [first.view.facts[0].fact_id])
    assert store.to_payload() == before
    store.commit(first, "outputs:first")
    with pytest.raises(ValueError, match="stale"):
        store.commit(second, "outputs:second")
    with pytest.raises(ValueError, match="closed"):
        first.prove("x=x")


def test_visibility_symbol_identity_and_version_views():
    store = environment()
    fact = publish(store).facts[0]
    assert fact in store.begin("third").view.facts
    for call in ("sibling", "parent"):
        assert not store.begin(call).view.facts
        with pytest.raises(ValueError, match="invisible"):
            store.begin(call).prove("x!=0", [fact.fact_id])
    changed = replace(store.calls[1], symbol_bindings=(("x", "other/object/x"),))
    other = ScopedProofFacts(
        store.context,
        store.source_context,
        store.bindings,
        (store.calls[0], changed),
        snapshot=store.snapshot,
    )
    assert not other.begin("second").view.facts
    with pytest.raises(FrozenInstanceError):
        fact.relation = "x<0"


@pytest.mark.parametrize(
    "mutation", ["proof", "reads", "source", "output", "scope", "version", "future"]
)
def test_restore_rejects_tampering_and_changed_authority(mutation):
    store = environment()
    publish(store)
    payload = json.loads(json.dumps(store.to_payload()))
    restored = environment()
    outputs = {"first": "outputs:first"}
    if mutation == "proof":
        payload["commits"][0]["records"][0]["proof"]["nodes"][-1]["conclusion"] = [
            "=",
            ["rat", "1", "1"],
            ["rat", "0", "1"],
        ]
    elif mutation == "reads":
        payload["commits"][0]["proof_reads"] = []
    elif mutation == "source":
        payload["source_hash"] = "forged"
    elif mutation == "output":
        outputs["first"] = "different-output"
    elif mutation in ("scope", "version"):
        first = restored.calls[0]
        first = (
            replace(first, scope_id="other", validity=FactValidity("other"))
            if mutation == "scope"
            else replace(first, input_fingerprint="new-version")
        )
        restored.calls = (first, *restored.calls[1:])
    else:
        payload["commits"].append(payload["commits"][0])
    with pytest.raises(ValueError):
        restored.restore(payload, outputs)
    assert not restored.snapshot.commits


def test_registry_unknown_kinds_no_authority_inheritance_and_requirements():
    store = environment()
    overlay = store.begin("first")
    with pytest.raises(ValueError, match="cannot publish"):
        overlay.prove("x=x", semantic_kind="extension")
    kind = FactKind(
        "extension",
        ("different_method",),
        True,
        lambda f: f.fact_id,
        lambda f: (),
        lambda f: True,
    )
    store.registry = store.registry.with_kind(kind)
    store.calls = (replace(store.calls[0], allowed_kinds=("extension",)),)
    with pytest.raises(ValueError, match="not authorized"):
        store.begin("first").prove("x=x", semantic_kind="extension")
    requirement = ConditionalRequirement(
        "extraneous_root_check",
        "solution",
        "x=1",
        FactValidity("q", assumption_refs=("case:1",)),
        "characterization",
    )
    assert requirement.validity.assumption_refs == ("case:1",)
    assert not store.snapshot.commits


def test_constructor_inventory_is_exhaustive_and_unknown_is_rejected():
    inventory = json.loads(
        (
            Path(__file__).parent / "fixtures/scoped-proof-search/premise-sites.json"
        ).read_text()
    )
    keys = {
        (Path(s["file"]).stem, s["function"], s["namespace"])
        for s in inventory["sites"]
    }
    assert keys == set(PREMISE_POLICIES)
    for key, policy in PREMISE_POLICIES.items():
        assert premise_policy(*key) == policy
    with pytest.raises(ValueError, match="unknown"):
        premise_policy("unknown", "verify", "substitution:verified:")


def test_invalidation_removes_consumers_and_snapshot_identity_changes():
    store = environment()
    first = publish(store)
    overlay = store.begin("second")
    overlay.prove("x!=0", [first.facts[0].fact_id])
    store.commit(overlay, "outputs:second")
    old = store.snapshot
    assert store.invalidate({"first"}) == ("first", "second")
    assert old.committed_manifest_hash != store.snapshot.committed_manifest_hash
    assert len(old.commits) == 2


def test_non_numeric_substitution_producer_actual_domain_reuse(monkeypatch):
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import target_context
    from shuxueshuo_server.solver.math_kernel.substitution import verify_substitution

    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/scoped-proof-search/q12-subchain.json"
        ).read_text()
    )
    from shuxueshuo_server.solver.math_kernel.constraint_elimination import (
        verify_elimination,
    )

    original_add = proof_kernel._Search.add

    def no_amgm(search, rule, *args, **kwargs):
        assert rule not in {
            "two_term_amgm",
            "amgm_squared_bound",
            "local_two_term_amgm",
            "two_term_product_bound",
        }
        return original_add(search, rule, *args, **kwargs)

    monkeypatch.setattr(proof_kernel._Search, "add", no_amgm)
    target = fixture["target"]
    source, _ = target_context(target)
    runtime = RuntimeContext(
        ProblemIR("subchain", "", "", list(source.symbols)),
        SympyKernel(),
        source.symbols,
    )
    bindings = tuple((n, "original/" + n) for n in source.symbols)
    producer = ProofCallAuthority(
        "sub",
        "problem",
        "substitute_expressions",
        bindings,
        FactValidity("problem"),
        "target",
        allowed_kinds=("domain", "identity", "definition", "relation"),
        target_json=canonical(target),
    )
    definitions = ("sub/definition/p", "sub/definition/q")
    new_bindings = tuple(
        sorted(
            (
                *bindings,
                ("p", "target/sub/definition/p"),
                ("q", "target/sub/definition/q"),
            )
        )
    )
    consumer = ProofCallAuthority(
        "elim",
        "problem",
        "eliminate_by_constraint",
        new_bindings,
        FactValidity("problem", definition_refs=definitions),
        "target",
        target_json=canonical(target),
    )
    store = ScopedProofFacts(runtime, source, bindings, (producer, consumer))
    evidence, _ = verify_substitution(target, fixture["substitution"])
    overlay = store.begin("sub")
    overlay.admit_method(evidence)
    commit = store.commit(overlay, "substitution-output")
    view = store.begin("elim")
    q_nonnegative = next(
        f
        for f in view.view.facts
        if f.relation.replace("(", "").replace(")", "") == "q>=0"
    )
    assert q_nonnegative.producer_call_id == "sub"
    # Import the committed nonnegative fact itself, not its defining square.
    candidate = view.prove("q>=0", [q_nonnegative.fact_id], semantic_kind="domain")[0]
    assert candidate.dependency_fact_refs == (q_nonnegative.fact_id,)
    elimination, _ = verify_elimination(
        target, fixture["elimination"], substitution=evidence
    )
    view.admit_method(elimination, producer_refs={"substitution": "sub"})
    result = store.commit(view, "consumer-output")
    assert result.dependencies == ("sub",)
    payload = json.loads(json.dumps(store.to_payload()))
    monkeypatch.setattr(
        proof_kernel._Search, "need", lambda *a, **k: pytest.fail("replay searched")
    )
    store.verify_snapshot()
    assert store.to_payload() == payload
    assert commit.facts


def test_native_transaction_commits_reads_and_rolls_back_failed_consumer():
    from shuxueshuo_server.solver.math_kernel.proof_facts import default_fact_kinds
    from shuxueshuo_server.solver.runtime.context import ContextBuilder
    from shuxueshuo_server.solver.runtime.executor import InvocationExecutor
    from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
        FunctionalTransactionalInterpreter,
        build_functional_execution_restore_seed,
    )
    from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
    from shuxueshuo_server.solver.runtime.proof_fact_transactions import (
        call_fingerprint,
    )
    from test_functional_transaction_execution import _authority_fixture, _replay

    legacy = _replay("nankai", mode="context_authoritative")
    _, _, problem, inputs, payload, registry, parent, _ = _authority_fixture("nankai")
    report = legacy.transactional_execution_report
    first, second = report.compiled_calls[:2]
    grants = tuple(
        ProofCallAuthority(
            c.call_id,
            "i",
            c.plans[0].invocations[0].method_id,
            (("x", "internal/universal/x"),),
            FactValidity("i"),
            call_fingerprint(c),
        )
        for c in (first, second)
    )
    kinds = default_fact_kinds(tuple(c.method_id for c in grants))

    def run(fail=False, restored_seed=None):
        context = ContextBuilder().build(problem)
        context.proof_facts = ScopedProofFacts(
            context,
            ProofContext({"x": sp.Symbol("x", real=True)}, {}, scope_id="i"),
            grants[0].symbol_bindings,
            grants,
            registry=kinds,
        )

        class Executor:
            def execute_plan(self, branch, plans):
                delegate = InvocationExecutor(
                    inputs.method_specs,
                    methods=default_stateless_registry(),
                    kernel=branch.kernel,
                )
                result = delegate.execute_plan(branch, plans)
                session = branch.proof_fact_overlay
                if session is not None:
                    if session.authority.call_id == first.call_id:
                        session.prove("x^2>=0", semantic_kind="domain")
                    else:
                        fact = next(
                            f
                            for f in session.view.facts
                            if f.producer_call_id == first.call_id
                        )
                        session.prove("x^2>=0", [fact.fact_id], semantic_kind="domain")
                        if fail:
                            raise ValueError(
                                "failure after valid proof and Method output"
                            )
                return result

        attempt = FunctionalTransactionalInterpreter(
            executor_factory=lambda *a: Executor()
        ).execute_attempt(
            raw_plan=legacy.functional_reconciliation.plan,
            reconciliation=legacy.functional_reconciliation,
            runtime_context=context,
            parent_context=parent,
            inputs=inputs,
            handle_registry=registry,
            problem_payload=payload,
            restored_seed=restored_seed,
        )
        assert (
            not context.proof_facts.snapshot.commits
        )  # caller's branch remains untouched
        return attempt

    attempt = run()
    result = attempt.execution_report
    assert result.ok, result.to_payload()
    commits = result.runtime_context.proof_facts.snapshot.commits
    assert len(commits) == 2
    assert commits[1].dependencies == (first.call_id,)
    assert any(
        e.kind == "proof_read" and e.consumer_call_id == second.call_id
        for e in result.graph.dependencies
    )
    from shuxueshuo_server.solver.runtime.functional_goal_execution import (
        FunctionalExecutionRestoreState,
        _transaction_execution_evidence,
    )
    from shuxueshuo_server.solver.runtime.proof_fact_evidence import (
        ProofFactsExecutionEvidence,
    )

    state = FunctionalExecutionRestoreState.from_transaction(
        attempt, legacy.functional_reconciliation
    )
    document = json.loads(json.dumps(state.authority_payload()))
    assert (
        FunctionalExecutionRestoreState.from_payload(document).authority_payload()
        == document
    )
    projected = _transaction_execution_evidence(attempt)
    assert any(
        isinstance(e, ProofFactsExecutionEvidence)
        and first.call_id in e.commit["dependencies"]
        for e in projected[second.call_id]
    )
    seed = build_functional_execution_restore_seed(
        result, legacy.functional_reconciliation
    )
    assert (
        state.seed_for_calls(frozenset(seed.call_ids)).proof_fact_checkpoint
        == seed.proof_fact_checkpoint
    )
    again = run(restored_seed=seed)
    assert again.execution_report.ok, again.execution_report.to_payload()
    assert (
        again.execution_report.runtime_context.proof_facts.to_payload()
        == result.runtime_context.proof_facts.to_payload()
    )
    failed = run(fail=True).execution_report
    assert [c.call_id for c in failed.runtime_context.proof_facts.snapshot.commits] == [
        first.call_id
    ]
    assert not any(
        e.kind == "proof_read" and e.consumer_call_id == second.call_id
        for e in failed.graph.dependencies
    )
    assert (
        next(r for r in failed.call_results if r.call_id == second.call_id).proof_commit
        is None
    )


def test_bound_adapters_require_committed_predecessor_and_keep_attainment_separate():
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import target_context
    from test_basic_inequality_stage5c import mixed_case

    target, first, square, _ = mixed_case()
    source, _ = target_context(target)
    context = RuntimeContext(
        ProblemIR("mixed", "", "", list(source.symbols)), SympyKernel(), source.symbols
    )
    bindings = tuple((n, "original/" + n) for n in source.symbols)
    calls = tuple(
        ProofCallAuthority(
            name,
            "problem",
            method,
            bindings,
            FactValidity("problem"),
            "input:" + name,
            target_json=canonical(target),
        )
        for name, method in [
            ("first", "apply_two_term_amgm"),
            ("square", "bound_univariate_quadratic"),
        ]
    )
    store = ScopedProofFacts(context, source, bindings, calls)
    overlay = store.begin("square")
    with pytest.raises(ValueError, match="exact producer"):
        overlay.admit_method(square)
    with pytest.raises(ValueError, match="not committed"):
        overlay.admit_method(square, producer_refs={"previous_bound": "first"})
    overlay = store.begin("first")
    overlay.admit_method(first)
    one = store.commit(overlay, "first-output")
    overlay = store.begin("square")
    overlay.admit_method(square, producer_refs={"previous_bound": "first"})
    two = store.commit(overlay, "square-output")
    assert two.dependencies == ("first",)
    assert one.requirements and two.requirements
    assert any(f.semantic_kind == "bound" for f in two.facts)
    assert two.requirements[0].required_relation == square["equality"]
    assert square["equality"] not in {f.relation for f in store.snapshot.facts}
    store.verify_snapshot()


def test_m01_domain_certificate_admission_and_branch_constructor_rejection():
    from shuxueshuo_server.solver.math_kernel.proof_kernel import prove_relation

    store = environment()
    call = replace(store.calls[0], method_id="organize_expressions")
    store = ScopedProofFacts(
        store.context, store.source_context, store.bindings, (call,)
    )
    context = ProofContext(
        store.source_context.symbols,
        {"c0": parse_math_relation("x>0", store.source_context.symbols)},
    )
    proof = prove_relation(parse_math_relation("x/x=1", context.symbols), context).proof
    overlay = store.begin("first")
    refs = {"c0": store.snapshot.roots[0].fact_id}
    with pytest.raises(ValueError, match="conditional constructor"):
        overlay.admit_certificate(
            proof, context, refs, ("inequality_bound_v2", "close", "solution_case")
        )
    facts = overlay.admit_certificate(
        proof, context, refs, ("expression_rewrite", "verify_chain", "c{i}")
    )
    assert any(f.semantic_kind == "domain" for f in facts)
    store.commit(overlay, "output")
    store.verify_snapshot()


def test_validity_references_are_not_lost_or_rebound():
    base = environment()
    producer = replace(
        base.calls[0], validity=FactValidity("q", state_version_refs=("x/v1",))
    )
    consumer = replace(
        base.calls[1], validity=FactValidity("q", state_version_refs=("x/v2",))
    )
    store = ScopedProofFacts(
        base.context, base.source_context, base.bindings, (producer, consumer)
    )
    fact = publish(store).facts[0]
    assert fact not in store.begin("second").view.facts
    with pytest.raises(ValueError, match="invisible"):
        store.begin("second").prove("x!=0", [fact.fact_id])
    for validity in (
        FactValidity("q", assumption_refs=("case:1",)),
        FactValidity("q", witness_ref="w1"),
    ):
        branch = replace(producer, validity=validity)
        conditional = ScopedProofFacts(
            base.context, base.source_context, base.bindings, (branch,)
        )
        with pytest.raises(ValueError, match="not authorized"):
            conditional.begin("first").prove("x=x")


def test_overlay_mutation_cannot_bypass_replay_and_source_origins_are_bound():
    store = environment()
    overlay = store.begin("first")
    overlay.prove("x=x")
    overlay._candidates[0] = replace(overlay._candidates[0], relation="x<x")
    with pytest.raises(ValueError, match="evidence"):
        store.commit(overlay, "output")
    assert not store.snapshot.commits
    publish(store)
    changed = replace(
        store.source_context,
        premises={
            "positive": replace(
                store.source_context.premises["positive"], source_path="/different"
            ),
        },
    )
    other = ScopedProofFacts(store.context, changed, store.bindings, store.calls)
    with pytest.raises(ValueError, match="source changed"):
        other.restore(store.to_payload(), {"first": "outputs:first"})


def test_checkpoint_prefix_and_execution_closure_include_auxiliary_dependencies():
    from types import SimpleNamespace

    from shuxueshuo_server.solver.runtime.functional_execution_authority import (
        functional_execution_evidence_from_payload,
    )
    from shuxueshuo_server.solver.runtime.proof_fact_evidence import (
        ProofFactsExecutionEvidence,
        include_proof_dependencies,
    )
    from shuxueshuo_server.solver.runtime.proof_fact_transactions import (
        select_checkpoint,
    )

    store = environment()
    first = publish(store)
    session = store.begin("second")
    session.prove("x!=0", [first.facts[0].fact_id])
    second = store.commit(session, "second-output")
    evidence = ProofFactsExecutionEvidence(
        "second", store.snapshot.source_hash, canonical(second.to_payload())
    )
    assert functional_execution_evidence_from_payload(evidence.to_payload()) == evidence
    root = SimpleNamespace(
        scope_steps=(SimpleNamespace(step_id="second", evidence=(evidence,)),),
        goals=(),
        children=(),
    )
    assert include_proof_dependencies({"first": (), "second": ()}, root)["second"] == (
        "first",
    )
    with pytest.raises(ValueError, match="cyclic"):
        include_proof_dependencies({"first": ("second",), "second": ()}, root)
    with pytest.raises(ValueError, match="exact committed prefix"):
        select_checkpoint(store.to_payload(), {"second"})
    prefix = select_checkpoint(store.to_payload(), {"first"})
    restored = environment()
    restored.restore(prefix, {"first": first.output_hash})
    assert len(restored.snapshot.commits) == 1


def test_registered_fact_kind_has_explicit_publisher_and_shared_layer_stays_generic():
    store = environment()
    store.calls = (replace(store.calls[0], allowed_kinds=("extension",)),)
    with pytest.raises(ValueError, match="unregistered"):
        store.begin("first").prove("x=x", semantic_kind="extension")
    store.registry = store.registry.with_kind(
        FactKind(
            "extension",
            ("verified_relation",),
            True,
            lambda f: f.statement_key,
            lambda f: ("extension:" + f.statement_key,),
            lambda f: True,
        )
    )
    session = store.begin("first")
    session.prove("x=x", semantic_kind="extension")
    store.commit(session, "extension-output")
    store.verify_snapshot()
    root = Path(__file__).parents[2] / "shuxueshuo_server/solver"
    for file in (
        "math_kernel/proof_facts.py",
        "runtime/scoped_proof_facts.py",
        "runtime/proof_fact_transactions.py",
        "runtime/proof_fact_evidence.py",
    ):
        text = (root / file).read_text()
        assert all(
            token not in text
            for token in ("two_term_amgm", "AmgmApplication", "q30", "q12")
        )


def test_cold_functional_import_and_lazy_teaching_exports():
    import subprocess
    import sys

    script = """
from shuxueshuo_server.solver.runtime.functional_plan import FunctionalPlanValidator
from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.snapshot import ExplanationSnapshotBuilder as Direct
assert ExplanationSnapshotBuilder is Direct
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)
