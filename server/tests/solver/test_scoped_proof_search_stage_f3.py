"""Default cutover, production search isolation and historical replay boundaries."""

import ast
import inspect
from pathlib import Path

import pytest

from shuxueshuo_server.solver.math_kernel import proof_kernel
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from tools.run_basic_inequality_stage4a import run


def test_runtime_and_authoring_default_to_scoped_protocol():
    assert RuntimeOrchestrator().proof_protocol == "scoped-facts/v2"
    assert inspect.signature(run).parameters["proof_protocol"].default == "scoped-facts/v2"
    assert RuntimeOrchestrator(proof_protocol="bound-conditions/v1").proof_protocol == "bound-conditions/v1"


def test_production_has_no_legacy_search_or_tool_dependency():
    assert not hasattr(proof_kernel, "_Search")
    root = Path(proof_kernel.__file__).parents[2]
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "proof_search_legacy" not in (node.module or ""), path
            if isinstance(node, ast.Import):
                assert all("proof_search_legacy" not in n.name for n in node.names), path


def test_default_q30_creates_full_scoped_committed_chain(tmp_path, monkeypatch):
    from tools.proof_search_legacy import LegacySearch
    from tools.run_basic_inequality_stage5c import full_chain_executed

    def forbidden(*args, **kwargs):
        raise AssertionError("production reached frozen historical search")

    monkeypatch.setattr(LegacySearch, "need", forbidden)
    fixtures = Path(__file__).parent / "fixtures"
    result, runtime = run(
        gold=fixtures / "math-notation-v1/basic-inequality/q30.json",
        problem_ir=fixtures / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
        plan=fixtures / "basic-inequality-stage5c/q30.json",
        output=tmp_path / "default", mode="recorded", debug_artifact_mode="compact_audit",
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"minimum": "4"}}
    artifacts = runtime.last_success_artifacts
    assert full_chain_executed(artifacts.verified_functional_execution.to_payload())
    store = artifacts.context.proof_facts
    assert store.to_payload()["condition_protocol"] == "scoped-facts/v2"
    assert [c.call_id for c in store.snapshot.commits] == ["rewrite", "first", "square", "last", "attain"]

    import json

    from shuxueshuo_server.solver.math_kernel.proof_algebra import digest
    from shuxueshuo_server.solver.runtime.functional_goal_execution import (
        FunctionalGoalExecutionCheckpoint,
        VerifiedFunctionalPlanExecution,
    )

    payload = json.loads((tmp_path / "default/attempt-1.checkpoint.json").read_text())
    restored = FunctionalGoalExecutionCheckpoint.from_payload(payload)
    assert restored.authority_payload() == payload
    assert restored.restore_state.runtime_seed is None

    from hashlib import sha256
    transaction = json.loads((tmp_path / "default/attempt-1.transaction.json").read_text())
    report = transaction["execution_report"]
    ref = report["proof_facts"]
    raw = (tmp_path / "default" / ref["file"]).read_bytes()
    assert sha256(raw).hexdigest() == ref["sha256"]
    full = json.loads(raw)
    for key in ref["pointer"].strip("/").split("/"):
        full = full[key]
    assert full == store.to_payload()
    commits = {c["call_id"]: c for c in full["commits"]}
    for call in report["call_results"]:
        if "proof_commit" in call:
            assert call["proof_commit"]["store_ref"] == ref
            assert call["proof_commit"]["commit_id"] == commits[call["call_id"]]["commit_id"]
    execution_payload = artifacts.verified_functional_execution.to_payload()
    assert VerifiedFunctionalPlanExecution.from_payload(execution_payload).to_payload() == execution_payload
    refs = [e for g in payload["root_scope"].get("goals", []) for step in g["steps"]
            for e in step.get("evidence", []) if e["schema_version"] == "scoped-proof-commit-ref/v1"]
    assert len(refs) == 5
    assert all("commit" not in e for e in refs)
    refs[0]["commit_ref"]["commit_id"] = "foreign-commit"
    refs[0]["evidence_id"] = digest({k: v for k, v in refs[0].items() if k != "evidence_id"})
    with pytest.raises(ValueError, match="reference does not match"):
        FunctionalGoalExecutionCheckpoint.from_payload(payload)


def test_positive_composite_signs_use_structure_and_preserve_domains():
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

    ctx = context(("a-b>0",), variables="ab")
    run = prove("16*(a-b)*(9/(a-b))>0", ctx)
    assert run.result.status == "proved", run.result
    assert any(e["strategy"] == "positive_components" and e["status"] == "proved" for e in run.diagnostics["trace"])
    assert replay_proof(run.result.proof, ctx).status == "proved"
    for premises, relation in (((), "16*(a-b)*(9/(a-b))>0"), (("a-b>=0",), "9/(a-b)>0"), (("a-b>0",), "16*(a-b)<0")):
        assert prove(relation, context(premises, variables="ab")).result.status != "proved"


def test_standalone_budget_session_reuses_only_replayable_context_facts():
    import pytest
    from test_math_proof_kernel import context, relation

    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from shuxueshuo_server.solver.math_kernel.proof_checker import _document
    from shuxueshuo_server.solver.math_kernel.proof_types import _Budget

    ctx = context("x>0")
    budget = _Budget(ctx.limits)
    request = {"kind": "relation", "candidate": _document(relation("x>0"))}
    assert proof_kernel._run_request(ctx, request, budget=budget).status == "proved"
    session = budget.local_search_session
    assert proof_kernel._run_request(ctx, request, budget=budget).status == "proved"
    assert budget.local_search_session is session
    # A proof cached with a premise is never treated as unconditional later.
    with pytest.raises(ProofFailure):
        proof_kernel._run_request(context(), request, budget=budget)


def test_endpoint_transport_preserves_equations_direction_and_remainder():
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

    ctx = context(('a>0', 'b>0', 'a*b=1', '(a+b)/2+8/(a+b)>=4'), variables='ab')
    run = prove('1/(2*a)+1/(2*b)+8/(a+b)>=4', ctx)
    assert run.result.status == 'proved', run.result
    assert any(e['strategy'] == 'endpoint_transport' and e['status'] == 'proved' for e in run.diagnostics['trace'])
    assert replay_proof(run.result.proof, ctx).status == 'proved'
    for expression, premises in (
        ('1/(2*a)+1/(2*b)+8/(a+b)<=4', ('a>0', 'b>0', 'a*b=1', '(a+b)/2+8/(a+b)>=4')),
        ('1/(2*a)+1/(2*b)+8/(a+b)>=4', ('a>0', 'b>0', '(a+b)/2+8/(a+b)>=4')),
        ('1/(2*a)+1/(2*b)>=4', ('a>0', 'b>0', 'a*b=1', '(a+b)/2+8/(a+b)>=4')),
    ):
        assert prove(expression, context(premises, variables='ab')).result.status != 'proved'


def test_transitive_substitution_uses_only_current_case_bindings():
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

    ctx = context(('b=4-a', 'a=2-sqrt(3)'), variables='ab')
    run = prove('b=2+sqrt(3)', ctx)
    assert run.result.status == 'proved', run.result
    assert replay_proof(run.result.proof, ctx).status == 'proved'
    assert prove('b=2+sqrt(3)', context(('b=4-a', 'a=2+sqrt(3)'), variables='ab')).result.status != 'proved'


def test_nonzero_product_uses_equation_before_speculative_strict_sign():
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

    for fact in ('q*(5*p+q)=1', '-3=q*(2*p-q)'):
        ctx = context((fact,), variables='pq')
        result = prove('q!=0', ctx)
        assert result.result.status == 'proved', result.result
        assert any(e['strategy'] == 'known_product_nonzero' and e['status'] == 'proved' for e in result.diagnostics['trace'])
        assert replay_proof(result.result.proof, ctx).status == 'proved'
    for fact in ('q*(5*p+q)=0', 'p=1'):
        assert prove('q!=0', context((fact,), variables='pq')).result.status != 'proved'


def test_node_accounting_ignores_only_unread_premises_and_still_checks_imports():
    from dataclasses import replace

    import pytest
    from test_math_proof_kernel import context, relation

    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from shuxueshuo_server.solver.math_kernel.proof_checker import (
        _document,
        _Environment,
        _replay,
    )
    from shuxueshuo_server.solver.math_kernel.proof_types import _Budget

    ctx = context('x>0')
    request = {'kind': 'relation', 'candidate': _document(relation('x>0'))}
    budget = _Budget(ctx.limits)
    def checked(current, premise):
        env = _Environment(current, request, budget=budget)
        root = env.add('given', ('>', ('symbol', 'x'), ('rat', '0', '1')), certificate={'premise_id': premise})
        guard = env.add('guard', env.by_id[root].conclusion, [root])
        return env.payload([guard])
    key = next(iter(ctx.premises))
    proof = checked(ctx, key)
    nodes = budget.counts['nodes']
    more = replace(ctx, premises={**ctx.premises, 'unread': relation('x<10')})
    expanded = checked(more, key)
    assert budget.counts['nodes'] == nodes
    assert expanded['context_hash'] != proof['context_hash']
    with pytest.raises(ProofFailure):
        _replay(proof, more, budget=budget)
    bad = replace(ctx, premises={key: relation('x<0')})
    with pytest.raises(ProofFailure):
        checked(bad, key)
    checked(replace(ctx, scope_id='another-scope'), key)
    assert budget.counts['nodes'] > nodes


@pytest.mark.parametrize('coefficient', (3, 17))
def test_weighted_even_power_uses_weak_signs_and_keeps_domain(coefficient):
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

    ctx = context((), variables='xy')
    result = prove(f'{coefficient}*(y-x/7)^4>=0', ctx)
    assert result.result.status == 'proved', result.result
    assert replay_proof(result.result.proof, ctx).status == 'proved'
    assert any(e['strategy'] == 'nonnegative_components' and e['status'] == 'proved'
               for e in result.diagnostics['trace'])
    for text in (f'-{coefficient}*(y-x/7)^4>=0',
                 f'{coefficient}*(y-x/7)^4>0',
                 f'{coefficient}*(1/x)^2>=0'):
        assert prove(text, ctx).result.status != 'proved'


def test_frozen_quadratic_context_check_does_not_cross_multiply_compatible_signs():
    import json

    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

    fixture = Path(__file__).parents[3] / 'docs/validation/scoped-proof-search-stage-f3/live-kernel-failures.json'
    case = json.loads(fixture.read_text())[0]
    ctx = context(tuple(case['premises'].values()), variables='abc')
    run = prove(case['request']['candidate']['source'], ctx)
    assert run.result.status == 'proved', run.result
    assert replay_proof(run.result.proof, ctx).status == 'proved'
    bad = context(('x>0', '-2*x>=0'), variables='x')
    assert prove('x>0', bad).result.code == 'inconsistent_premises'


@pytest.mark.parametrize('sample', (1, 2, 3))
def test_frozen_f3_live_responses_close_without_new_model_calls(tmp_path, sample):
    import gzip
    import json

    fixture = Path(__file__).parents[3] / 'docs/validation/scoped-proof-search-stage-f3/live-responses.json.gz'
    responses = json.loads(gzip.decompress(fixture.read_bytes()))[f'planner-{sample:02}']
    replay = tmp_path / 'responses'
    replay.mkdir()
    for name, content in responses.items():
        (replay / name).write_text(content)
    fixtures = Path(__file__).parent / 'fixtures'
    result, runtime = run(
        gold=fixtures / 'math-notation-v1/basic-inequality/q30.json',
        problem_ir=fixtures / 'basic-inequality-problem-ir/v1/q30/problem-ir.json',
        output=tmp_path / 'replayed', mode='recorded', replay_from=replay,
        debug_artifact_mode='compact_audit',
    )
    assert result.status == 'ok', result.to_dict()
    assert result.answers == {'problem': {'minimum': '4'}}
    store = runtime.last_success_artifacts.context.proof_facts
    assert store is not None
    from unittest.mock import patch

    from shuxueshuo_server.solver.math_kernel.real_proof_strategies import (
        ScheduledRealSearch,
    )
    from shuxueshuo_server.solver.runtime.scoped_proof_facts import ScopedProofFacts

    restored = ScopedProofFacts(store.context, store.source_context, store.bindings, store.calls)
    with patch.object(ScheduledRealSearch, 'need', side_effect=AssertionError('restore searched')):
        restored.restore(store.to_payload(), {c.call_id: c.output_hash for c in store.snapshot.commits})
    assert restored.to_payload() == store.to_payload()


def test_fragment_derived_given_requires_a_new_checked_proof():
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.amgm_application import copy_nodes
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.method_proof_session import (
        MethodProofSession,
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import (
        from_node,
    )
    from shuxueshuo_server.solver.math_kernel.proof_checker import (
        _document,
        _text,
        replay_proof,
    )
    from shuxueshuo_server.solver.math_kernel.proof_search import (
        SearchBudget,
        default_search_configuration,
    )
    from shuxueshuo_server.solver.math_kernel.real_proof_strategies import (
        ScheduledRealSearch,
    )

    original = prove('x*y>=0', context(('x*y>0',), variables='xy')).result.proof
    intermediate = prove('x*y>0', context(('x>0', 'y>0'), variables='xy')).result.proof
    session = MethodProofSession(fragments=(
        ('old-derived', original, original['roots'][0]),
        ('old-intermediate', intermediate, intermediate['roots'][0]),
    ))
    for premises, accepted in ((('x>0', 'y>0'), True), (('x>0',), False)):
        current = context(premises, variables='xy')
        parsed = parse_math_relation('x*y>=0', current.symbols)
        request = {'kind': 'relation', 'candidate': _document(parsed)}
        class CheckedDependencies(ScheduledRealSearch):
            def need(self, goal, current=current):
                checked = proof_kernel._run_request(current, {
                    'kind': 'relation',
                    'candidate': _document(parse_math_relation(_text(goal), current.symbols)),
                })
                return copy_nodes(checked.proof, self)[0]
        policy = default_search_configuration()[2]
        engine = CheckedDependencies(current, request, budget=SearchBudget(current.limits, policy), policy=policy, manifest_hash="test")
        engine.seed_reads = {}
        if not accepted:
            assert session.seed(engine, from_node(parsed.ast)) is None
            assert not engine.nodes and not engine.seed_reads
            continue
        core = session.seed(engine, from_node(parsed.ast))
        root = engine.add('guard', from_node(parsed.ast), [core])
        assert replay_proof(engine.payload([root]), current).status == 'proved'
        assert 'old-derived' in engine.seed_reads.values()


def test_shared_fragment_index_hashes_each_record_once_and_preserves_binding(monkeypatch):
    import json
    from types import SimpleNamespace

    from shuxueshuo_server.solver.math_kernel.proof_facts import FactValidity
    from shuxueshuo_server.solver.runtime import method_proof_integration as module

    validity = FactValidity("problem")
    proof = {"nodes": [{"node_id": "n", "conclusion": [">", ["symbol", "x"], ["rat", "0", "1"]]}]}
    records = [{"evidence": {"proof": proof}}, {"kind": "reuse", "fact_ids": []}]
    digest = module.digest
    proof_ref = digest(records[0])
    hashed = []

    def counted(record):
        hashed.append(record)
        return digest(record)

    monkeypatch.setattr(module, "digest", counted)
    facts = [SimpleNamespace(
        producer_call_id="producer", validity=validity,
        source="producer/proof/nodes/n", proof_ref=proof_ref, fact_id=f"f{i}",
    ) for i in range(100)]
    # A record with the same formula but a different producer hash is unusable.
    facts.append(SimpleNamespace(
        producer_call_id="producer", validity=validity,
        source="producer/proof/nodes/n", proof_ref="unbound", fact_id="bad",
    ))
    overlay = SimpleNamespace(
        owner=SimpleNamespace(snapshot=SimpleNamespace(commits=[SimpleNamespace(
            call_id="producer", records_json=json.dumps(records),
        )])),
        authority=SimpleNamespace(validity=validity, call_id="consumer",
                                  input_fingerprint="input", scope_id="problem"),
        view=SimpleNamespace(facts=facts, committed_manifest_hash="manifest"),
    )
    session = module.method_search_service(overlay)
    assert len(hashed) == len(records)
    imported = [f[0] for group in session.fragments.values() for f in group]
    assert imported == [f"f{i}" for i in range(100)]


def test_premise_index_parses_each_authorized_fact_once(monkeypatch):
    from types import SimpleNamespace

    import sympy as sp

    from shuxueshuo_server.solver.math_kernel import expression_parser
    from shuxueshuo_server.solver.math_kernel.proof_facts import (
        FactValidity,
        VerifiedMathFact,
    )
    from shuxueshuo_server.solver.runtime.method_proof_integration import (
        PremiseFactIndex,
        match_premise_fact,
    )

    authority = SimpleNamespace(symbol_bindings=(("x", "root/x"),), validity=FactValidity("problem"))
    symbols = {"x": sp.Symbol("x", real=True)}
    parsed = expression_parser.parse_math_relation("x>0", symbols)
    facts = [VerifiedMathFact("x>0", authority.symbol_bindings, authority.validity, "domain", source)
             for source in ("a", "z")]
    forbidden = VerifiedMathFact("x>0", (("x", "other/x"),), authority.validity, "domain", "0")
    original = expression_parser.parse_math_relation
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(expression_parser, "parse_math_relation", counted)
    index = PremiseFactIndex(authority)
    index.extend([forbidden, *facts])
    for _ in range(100):
        index.extend(facts)
        assert match_premise_fact(index, parsed, symbols, authority) == facts[0]
    assert calls == ["x>0", "x>0"]
    later = VerifiedMathFact("x!=0", authority.symbol_bindings, authority.validity, "domain", "later")
    index.extend([later])
    assert index.match(original("x!=0", symbols), symbols) == later
    with pytest.raises(ValueError, match="no authorized producer"):
        index.match(parsed, {})


@pytest.mark.parametrize("expanded", [False, True])
def test_checked_search_replays_again_only_when_context_changes(monkeypatch, expanded):
    from test_scoped_proof_search_stage_d import context

    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.method_proof_session import (
        MethodProofSession,
    )
    from shuxueshuo_server.solver.math_kernel.proof_checker import _document
    from shuxueshuo_server.solver.math_kernel.proof_rule_registry import RuleRegistry

    premises = ["x>0"]
    if expanded:
        premises += [f"y^{i}=1" for i in range(2, 11)]
    ctx = context(premises, variables="xy")
    checks = []
    original = RuleRegistry.replay

    def counted(self, proof, context, **kwargs):
        checks.append(proof["context_hash"])
        return original(self, proof, context, **kwargs)

    monkeypatch.setattr(RuleRegistry, "replay", counted)
    request = {"kind": "relation", "candidate": _document(parse_math_relation("x!=0", ctx.symbols))}
    result = MethodProofSession().run_request(ctx, request)
    assert result.status == "proved"
    assert len(checks) == (2 if expanded else 1)
    assert (len(set(checks)) == 2) == expanded
    from shuxueshuo_server.solver.math_kernel.proof_checker import DEFAULT_RULE_REGISTRY
    assert original(DEFAULT_RULE_REGISTRY, result.proof, ctx).status == "proved"


def test_search_still_requires_independent_checker_acceptance(monkeypatch):
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_rule_registry import RuleRegistry
    from shuxueshuo_server.solver.math_kernel.proof_types import ProofResult

    monkeypatch.setattr(RuleRegistry, "replay", lambda *args, **kwargs: ProofResult(
        "failed", code="invalid_proof", diagnostic="checker rejected"))
    run = prove("x!=0", context(["x>0"]))
    assert run.result.status == "failed"
    assert run.result.code == "invalid_proof"


def test_q30_publication_reuses_checked_results_but_external_replay_checks(tmp_path, monkeypatch):
    import json
    from copy import deepcopy
    from dataclasses import replace

    from shuxueshuo_server.solver.math_kernel import bound_chain
    from shuxueshuo_server.solver.math_kernel.method_proof_session import (
        use_proof_session,
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from shuxueshuo_server.solver.math_kernel.proof_rule_registry import RuleRegistry
    from shuxueshuo_server.solver.runtime import method_proof_integration as integration
    from shuxueshuo_server.solver.runtime.scoped_proof_facts import ScopedProofFacts

    in_publication = False
    checks = []
    replayed_bounds = []
    original_check = RuleRegistry.replay
    original_publish = integration.publish_method_result
    original_bound = bound_chain.replay_bound

    def check(*args, **kwargs):
        checks.append(in_publication)
        return original_check(*args, **kwargs)

    def publish(*args, **kwargs):
        nonlocal in_publication
        in_publication = True
        try:
            _, inputs, result = args
            if 'bound' in result.outputs:
                evidence = result.outputs['bound'].value
                service = kwargs['checked']
                assert service.checked_bound(inputs['target'], evidence) is not None
                altered = deepcopy(evidence)
                altered['equalities'] = []
                assert service.checked_bound(inputs['target'], altered) is None
            return original_publish(*args, **kwargs)
        finally:
            in_publication = False

    def replay_bound(*args, **kwargs):
        replayed_bounds.append(True)
        return original_bound(*args, **kwargs)

    monkeypatch.setattr(RuleRegistry, 'replay', check)
    monkeypatch.setattr(integration, 'publish_method_result', publish)
    monkeypatch.setattr(bound_chain, 'replay_bound', replay_bound)
    fixtures = Path(__file__).parent / 'fixtures'
    result, runtime = run(
        gold=fixtures / 'math-notation-v1/basic-inequality/q30.json',
        problem_ir=fixtures / 'basic-inequality-problem-ir/v1/q30/problem-ir.json',
        plan=fixtures / 'basic-inequality-stage5c/q30.json',
        output=tmp_path / 'checked-results', mode='recorded', debug_artifact_mode='compact_audit',
    )
    assert result.status == 'ok', result.to_dict()
    assert result.answers == {'problem': {'minimum': '4'}}
    assert checks and not any(checks), 'publication repeated mathematical verification'
    assert not replayed_bounds, 'execution recursively replayed an authorized bound'
    store = runtime.last_success_artifacts.context.proof_facts
    payload = store.to_payload()
    before = len(checks)
    restored = ScopedProofFacts(store.context, store.source_context, store.bindings,
                                store.calls)
    restored.restore(payload, {c.call_id: c.output_hash for c in store.snapshot.commits})
    assert len(checks) > before and replayed_bounds
    assert restored.to_payload() == payload

    producer = store.snapshot.commits[1]
    bound = next(r['evidence'] for r in json.loads(producer.records_json) if r['kind'] == 'method')
    target = json.loads(store.authority(producer.call_id).target_json)
    grant = replace(store.authority(producer.call_id), call_id='later', dependencies=(producer.call_id,))
    store.register_call(grant)
    overlay = store.begin('later')
    service = integration.method_search_service(overlay)
    with use_proof_session(service):
        before = len(checks)
        assert bound_chain.consume_bound(target, bound)['bound'] == bound['bound']
        assert len(checks) == before
        with pytest.raises(ProofFailure, match='eight bound dependencies'):
            bound_chain.consume_bound(target, bound, depth=9)
        # Explicit replay must ignore even an active execution service.
        bound_chain.replay_bound(target, bound)
        assert len(checks) > before
    bound_refs = {f.fact_id for f in producer.facts
                  if f.source == f'{producer.call_id}/certified_bound'}
    assert bound_refs and overlay._reads == bound_refs
    bad = deepcopy(bound)
    bad['bound'] = '-999'
    assert service.resolve_bound(target, bad) is None
    assert service.resolve_bound({**target, 'target_math': '0'}, bound) is None
    # Identical names with different symbol identities are not authorized reads.
    inaccessible = replace(grant, call_id='inaccessible', symbol_bindings=tuple(
        (name, 'different/' + identity) for name, identity in grant.symbol_bindings))
    store.register_call(inaccessible)
    blocked = integration.method_search_service(store.begin('inaccessible'))
    assert blocked.resolve_bound(target, bound) is None


def test_publication_receipt_requires_exact_proof_context_and_call(monkeypatch):
    from copy import deepcopy
    from dataclasses import replace

    from test_scoped_proof_facts_stage_c import environment

    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.proof_checker import _document
    from shuxueshuo_server.solver.runtime.method_proof_integration import (
        method_search_service,
    )

    store = environment()
    overlay = store.begin('first')
    session = method_search_service(overlay)
    context = store.source_context
    proof = session.run_request(context, {'kind': 'relation', 'candidate': _document(
        parse_math_relation('x!=0', context.symbols))}).proof
    refs = {'positive': overlay.view.facts[0].fact_id}
    site = ('expression_rewrite', 'verify_chain', 'c{i}')
    assert session.accepts_certificate(proof, context)
    assert not session.accepts_certificate(proof, replace(context, scope_id='other'))
    changed = deepcopy(proof)
    changed['nodes'][-1]['rule_id'] = 'invented'
    assert not session.accepts_certificate(changed, context)
    with pytest.raises(ValueError, match='rule'):
        overlay.admit_certificate(changed, context, refs, site, checked=session)
    overlay.admit_certificate(proof, context, refs, site, checked=session)
    other = store.begin('second')
    with pytest.raises(ValueError, match='another invocation'):
        other.admit_certificate(proof, context, refs, site, checked=session)


def test_restore_payload_is_detached_and_normalized_only_once(monkeypatch):
    from shuxueshuo_server.solver.runtime import functional_goal_execution as module

    source = {"nested": [{"value": 3}]}
    state = module.FunctionalExecutionRestoreState(call_results=(source,))
    expected = state.authority_payload()
    source["nested"][0]["value"] = 99
    with pytest.raises(TypeError):
        state.call_results[0]["nested"][0]["value"] = 99

    def forbidden(*args, **kwargs):
        raise AssertionError("repeated restore normalization")

    monkeypatch.setattr(module, "_json_safe_value", forbidden)
    first = state.authority_payload()
    first["call_results"][0]["nested"][0]["value"] = 99
    assert state.authority_payload() == expected
    assert state._payload(include_signature=False) == {
        k: v for k, v in expected.items() if k != "restore_signature"
    }


def test_auxiliary_reference_requires_exact_store_and_keeps_legacy_reader():
    from copy import deepcopy

    from shuxueshuo_server.solver.math_kernel.proof_facts import canonical
    from shuxueshuo_server.solver.runtime.functional_execution_authority import (
        functional_execution_evidence_from_payload,
    )
    from shuxueshuo_server.solver.runtime.proof_fact_evidence import (
        ProofFactsExecutionEvidence,
    )

    commit = {"call_id": "second", "commit_id": "verified-id",
              "dependencies": ["first"], "proof_reads": ["fact:first"],
              "records": [{"large_certificate": "x" * 10000}]}
    ref = ProofFactsExecutionEvidence.from_commit("second", "source", commit)
    assert "large_certificate" not in canonical(ref.to_payload())
    assert functional_execution_evidence_from_payload(ref.to_payload()) == ref
    ref.verify_reference("source", {"second": commit})
    for key, value in (("commit_id", "other"), ("dependencies", []), ("proof_reads", [])):
        changed = deepcopy(commit)
        changed[key] = value
        with pytest.raises(ValueError, match="reference"):
            ref.verify_reference("source", {"second": changed})
    with pytest.raises(ValueError, match="reference"):
        ref.verify_reference("other-source", {"second": commit})
    with pytest.raises(ValueError, match="reference"):
        ref.verify_reference("source", {})
    legacy = ProofFactsExecutionEvidence("second", "source", canonical(commit))
    assert functional_execution_evidence_from_payload(legacy.to_payload()) == legacy


def test_authoring_summary_retains_attempt_references_without_copying_proofs(tmp_path):
    import json
    from hashlib import sha256

    from shuxueshuo_server.solver.result_models import DerivationTrace, SolverResult
    from shuxueshuo_server.solver.runtime.llm_debug import DebugArtifactJournal
    from tools.run_basic_inequality_stage4a import _write_result_summary

    journal = DebugArtifactJournal(tmp_path)
    for attempt in (1, 2):
        journal.write_index(f"attempt-{attempt}", {
            "semantic_attempt": attempt, "phase": "completed", "artifacts": {},
        })
    result = SolverResult("test", "ok", answers={"minimum": "4"}, trace=DerivationTrace(
        "test", "test", steps=[{"method_id": "M11", "calculation": "x>=4", "proofs": "x" * 10000}]
    ))
    _write_result_summary(tmp_path, result)
    summary = json.loads((tmp_path / "result.json").read_text())
    assert summary["answers"] == result.answers
    assert summary["trace"]["steps"] == [{"method_id": "M11", "calculation": "x>=4"}]
    assert "proofs" in result.trace.steps[0]  # API object remains complete.
    assert [r["semantic_attempt"] for r in summary["evidence_indexes"]] == [1, 2]
    for ref in summary["evidence_indexes"]:
        assert sha256((tmp_path / ref["file"]).read_bytes()).hexdigest() == ref["sha256"]
        history = ref["history"]
        assert sha256((tmp_path / history["file"]).read_bytes()).hexdigest() == history["sha256"]


def _only_strategies(*names):
    from dataclasses import replace

    from shuxueshuo_server.solver.math_kernel.proof_search import (
        default_search_configuration,
    )

    registry, _, policy = default_search_configuration()
    return replace(policy, disabled_strategies=tuple(
        s.strategy_id for p in registry.packages for s in p.strategies
        if s.strategy_id not in names
    ))


def test_ground_substitution_closes_dependencies_without_general_fallback():
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

    policy = _only_strategies('given', 'constant', 'ground_substitution')
    ctx = context(('b=4-a', 'a=2-sqrt(3)'), variables='ab')
    run = prove('b=2+sqrt(3)', ctx, policy=policy)
    assert run.result.status == 'proved', run.result
    assert any(t['strategy'] == 'ground_substitution' and t['status'] == 'proved'
               for t in run.diagnostics['trace'])
    assert replay_proof(run.result.proof, ctx).status == 'proved'
    for premises in (('b=4-a',), ('b=4-a', 'a=2+sqrt(3)'), ('b=4-a', 'a=4-b')):
        assert prove('b=2+sqrt(3)', context(premises, variables='ab'), policy=policy).result.status != 'proved'


@pytest.mark.parametrize('premise,goal', [
    ('4<=a+b', '2*a>=4'), ('a+b>=4', '4<=2*a'),
    ('4<a+b', '2*a>4'), ('a+b>4', '4<2*a'),
])
def test_endpoint_transport_matches_both_written_directions(premise, goal):
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

    ctx = context(('a=b', premise), variables='ab')
    policy = _only_strategies('given', 'equality', 'endpoint_transport')
    run = prove(goal, ctx, policy=policy)
    assert run.result.status == 'proved', run.result
    assert any(t['strategy'] == 'endpoint_transport' and t['status'] == 'proved'
               for t in run.diagnostics['trace'])
    assert replay_proof(run.result.proof, ctx).status == 'proved'
    assert prove('2*a<4', ctx, policy=policy).result.status != 'proved'


@pytest.mark.parametrize('code,message', [
    ('proof_limit', 'reductions budget exhausted'),
    ('proof_search_exhausted', 'global reductions exhausted'),
])
def test_local_template_propagates_pair_exhaustion(monkeypatch, code, message):
    from test_scoped_proof_search_stage_d import context

    from shuxueshuo_server.solver.math_kernel import local_bound_contract as local
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from shuxueshuo_server.solver.math_kernel.proof_types import _Budget

    ctx = context(('a>0', 'b>0'), variables='ab')
    attempts = []
    def exhausted(*args):
        attempts.append(1)
        raise ProofFailure(code, message)
    monkeypatch.setattr(local.Arithmetic, 'reduce', exhausted)
    with pytest.raises(ProofFailure) as error:
        local.verify_local_application(ctx, 'a+b', '2*sqrt(a*b)',
                                       ('symbol', 'a'), ('symbol', 'b'), budget=_Budget(ctx.limits))
    assert error.value.code == code and str(error.value) == message
    assert len(attempts) == 1


def test_local_template_skips_structure_limit_and_checks_later_template(monkeypatch):
    from test_scoped_proof_search_stage_d import context

    from shuxueshuo_server.solver.math_kernel import local_bound_contract as local
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from shuxueshuo_server.solver.math_kernel.proof_types import _Budget

    ctx = context(('a>0', 'b>0'), variables='ab')
    original = local.Arithmetic.reduce
    attempts = []
    def oversized_first(self, *args):
        attempts.append(1)
        if len(attempts) == 1:
            raise ProofFailure('proof_limit', 'polynomial term limit')
        return original(self, *args)
    monkeypatch.setattr(local.Arithmetic, 'reduce', oversized_first)
    certificate = local.verify_local_application(ctx, '1/(a*b)', '4/(a+b)^2',
                                                ('symbol', 'a'), ('symbol', 'b'), budget=_Budget(ctx.limits))
    assert len(attempts) > 1
    assert local.verify_local_application(ctx, '1/(a*b)', '4/(a+b)^2',
                                         ('symbol', 'a'), ('symbol', 'b'), budget=_Budget(ctx.limits),
                                         certificates=certificate) == certificate


@pytest.mark.parametrize('code,message,expected_calls', [
    ('proof_search_exhausted', 'global work exhausted', 1),
    ('proof_limit', 'reductions budget exhausted', 1),
    ('strategy_budget_exhausted', 'request quota exhausted', 2),
])
def test_witness_loop_distinguishes_shared_and_request_budgets(monkeypatch, code, message, expected_calls):
    import sympy as sp
    from test_math_proof_kernel import context, relation, scalar

    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure

    ctx = context(symbols={'x': sp.Symbol('x', real=True)})
    attempts = []
    def exhausted(*args, **kwargs):
        attempts.append(1)
        raise ProofFailure(code, message)
    monkeypatch.setattr(proof_kernel, '_run_request', exhausted)
    result = proof_kernel.verify_witnesses(
        [{'x': scalar('1')}, {'x': scalar('2')}], [relation('x>0')], ctx)
    assert len(attempts) == expected_calls
    assert len(result.branches) == 2
    assert all(b['code'] == code for b in result.branches)


@pytest.mark.parametrize('code,message,retry', [
    ('strategy_budget_exhausted', 'request quota exhausted', True),
    ('proof_limit', 'polynomial term limit', True),
    ('proof_search_exhausted', 'pair verification exhausted', True),
    ('proof_limit', 'reductions budget exhausted', True),
    ('invalid_proof', 'invalid effect certificate', False),
])
def test_amgm_pair_loop_retries_only_local_failures(monkeypatch, code, message, retry):
    from test_scoped_proof_search_stage_d import context

    from shuxueshuo_server.solver.math_kernel import amgm_application as app
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from shuxueshuo_server.solver.math_kernel.proof_types import _Budget

    ctx = context(('a>0', 'b>0'), variables='ab')
    pairs = [(('symbol', 'a'), ('symbol', 'b')),
             (('symbol', 'b'), ('symbol', 'a'))]
    monkeypatch.setattr(app, 'application_candidates', lambda *args: pairs)
    attempts = []
    original = app.verify_local_application
    def first_unavailable(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ProofFailure(code, message)
        return original(*args, **kwargs)
    monkeypatch.setattr(app, 'verify_local_application', first_unavailable)
    args = (ctx, {'goal_kind': 'find_minimum'}, 'a+b', '2*sqrt(a*b)', [])
    if retry:
        certificate = app.verify_application(*args, budget=_Budget(ctx.limits))
        assert len(attempts) == 2
        assert app.verify_application(*args, budget=_Budget(ctx.limits), certificate=certificate) == certificate
        attempts.clear()
        with pytest.raises(ProofFailure) as error:
            app.verify_application(*args, budget=_Budget(ctx.limits), certificate=certificate)
        assert error.value.code == code
        assert len(attempts) == 1
    else:
        with pytest.raises(ProofFailure) as error:
            app.verify_application(*args, budget=_Budget(ctx.limits))
        assert error.value.code == code and str(error.value) == message
        assert len(attempts) == 1


@pytest.mark.parametrize('failure_code', [None, 'proof_search_exhausted', 'strategy_budget_exhausted', 'invalid_proof'])
def test_fragment_import_tries_next_candidate_after_recursive_given_failure(failure_code):
    from test_scoped_proof_search_stage_d import context, prove

    from shuxueshuo_server.solver.math_kernel.amgm_application import copy_nodes
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.method_proof_session import (
        MethodProofSession,
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import (
        ProofFailure,
        from_node,
    )
    from shuxueshuo_server.solver.math_kernel.proof_checker import (
        _document,
        _text,
        replay_proof,
    )
    from shuxueshuo_server.solver.math_kernel.proof_search import (
        SearchBudget,
        default_search_configuration,
    )
    from shuxueshuo_server.solver.math_kernel.real_proof_strategies import (
        ScheduledRealSearch,
    )

    current = context(('x>0', 'y>=0'), variables='xy')
    original = prove('x*y>=0', context(('x*y>0',), variables='xy')).result.proof
    intermediate = prove('x*y>0', context(('x>0', 'y>0'), variables='xy')).result.proof
    alternative = prove('x*y>=0', current).result.proof
    assert len(original['nodes']) < len(alternative['nodes'])
    session = MethodProofSession(fragments=(
        ('unavailable', original, original['roots'][0]),
        ('intermediate', intermediate, intermediate['roots'][0]),
        ('usable', alternative, alternative['roots'][0]),
    ))
    attempted = []
    class CheckedDependencies(ScheduledRealSearch):
        def need(self, goal):
            attempted.append(goal)
            # Simulate partial import before the dependency fails. Rollback must
            # discard both nodes and read bookkeeping, but never refund work.
            self.add('given', self.premises['0'], certificate={'premise_id': '0'})
            self.seed_reads['abandoned'] = 'unavailable'
            if failure_code:
                raise ProofFailure(failure_code, 'injected dependency failure')
            checked = proof_kernel._run_request(current, {
                'kind': 'relation',
                'candidate': _document(parse_math_relation(_text(goal), current.symbols)),
            })
            return copy_nodes(checked.proof, self)[0]

    parsed = parse_math_relation('x*y>=0', current.symbols)
    policy = default_search_configuration()[2]
    engine = CheckedDependencies(current, {'kind': 'relation', 'candidate': _document(parsed)},
                                 budget=SearchBudget(current.limits, policy), policy=policy,
                                 manifest_hash='test')
    engine.seed_reads = {}
    if failure_code:
        with pytest.raises(ProofFailure) as error:
            session.seed(engine, from_node(parsed.ast))
        assert error.value.code == failure_code
        assert not engine.nodes and not engine.seed_reads
    else:
        core = session.seed(engine, from_node(parsed.ast))
        root = engine.add('guard', from_node(parsed.ast), [core])
        assert replay_proof(engine.payload([root]), current).status == 'proved'
        assert set(engine.seed_reads.values()) == {'usable'}
    assert len(attempted) == 1


def test_minimum_pair_exhaustion_does_not_block_later_real_application():
    from dataclasses import replace
    from types import SimpleNamespace

    from test_scoped_proof_search_stage_d import context

    from shuxueshuo_server.solver.math_kernel.amgm_application import (
        application_candidates,
        verify_application,
    )
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.local_bound_contract import (
        verify_local_application,
    )
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from shuxueshuo_server.solver.math_kernel.proof_types import ProofLimits, _Budget

    ctx = context(('a>0', 'b>0'), variables='ab', limits=replace(ProofLimits(), reductions=16))
    chain = [SimpleNamespace(parsed=parse_math_relation('(a+b)^3+(a+2*b)^3>0', ctx.symbols),
                             origin={'step': 0})]
    pair = next(application_candidates('a+1/a', chain, ctx.symbols))
    caller_budget = _Budget(ctx.limits)
    with pytest.raises(ProofFailure, match='reductions budget exhausted') as error:
        verify_local_application(ctx, 'a+1/a', '2', *pair, budget=caller_budget)
    assert error.value.code == 'proof_limit'
    assert caller_budget.counts == {}  # Exhaustion belongs to the pair, not the caller.
    args = (ctx, {'goal_kind': 'find_minimum'}, 'a+1/a', '2', chain)
    certificate = verify_application(*args, budget=caller_budget)
    assert certificate['terms'] == ['a', '(1)/(a)']
    assert verify_application(*args, budget=_Budget(ctx.limits), certificate=certificate) == certificate


@pytest.mark.parametrize('goal_kind', ['find_minimum', 'find_maximum'])
def test_application_still_stops_on_real_caller_budget_exhaustion(monkeypatch, goal_kind):
    from test_scoped_proof_search_stage_d import context

    from shuxueshuo_server.solver.math_kernel import amgm_application as app
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    from shuxueshuo_server.solver.math_kernel.proof_types import _Budget

    ctx = context(('a>0', 'b>0'), variables='ab')
    name = 'verify_local_application' if goal_kind == 'find_minimum' else 'verify_upper_effect'
    original = getattr(app, name)
    attempted = []
    def observe(*args, **kwargs):
        attempted.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(app, name, observe)
    budget = _Budget(ctx.limits)
    budget.use('attempts', ctx.limits.attempts)
    source, bound = ('a+1/a', '2') if goal_kind == 'find_minimum' else ('a*b', '(a+b)^2/4')
    with pytest.raises(ProofFailure) as error:
        app.verify_application(ctx, {'goal_kind': goal_kind}, source, bound, [], budget=budget)
    assert error.value.code == 'proof_search_exhausted'
    assert len(attempted) == 1
    assert budget.counts['attempts'] > ctx.limits.attempts
