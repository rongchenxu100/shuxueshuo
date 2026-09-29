"""Budget accounting is about independent mathematics, not formatting."""
from copy import deepcopy
from dataclasses import replace

import pytest
import sympy as sp
from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure, from_node
from shuxueshuo_server.solver.math_kernel.proof_kernel import (
    ProofContext,
    _Budget,
    _document,
    _replay,
    _run_request,
    fact_key,
)

SYMBOLS = {s: sp.Symbol(s, real=True) for s in 'abc'}


def context(*facts):
    return ProofContext(SYMBOLS, {str(i): parse_math_relation(f, SYMBOLS) for i, f in enumerate(facts)})


def request(math):
    return {'kind': 'relation', 'candidate': _document(parse_math_relation(math, SYMBOLS))}


def test_shared_goal_graph_saves_search_and_nodes_and_replays():
    ctx = context('a>b', 'b>c', 'c>0')
    budget = _Budget(ctx.limits)
    first = _run_request(ctx, request('a*b>0'), budget=budget).proof
    counts = dict(budget.counts)
    second = _run_request(ctx, request('(a*b)>0'), budget=budget).proof
    assert {k:v for k,v in budget.counts.items() if k != "arithmetic_operations"} == {k:v for k,v in counts.items() if k != "arithmetic_operations"}
    # Rechecking imported nodes is metered even when no search is needed.
    replay_budget = _Budget(ctx.limits)
    _replay(first, ctx, budget=replay_budget)
    counts = dict(replay_budget.counts)
    _replay(second, ctx, budget=replay_budget)
    assert replay_budget.counts['nodes'] == counts['nodes']
    assert first['sources'] != second['sources']  # preserve each authored spelling
    corrupt = deepcopy(second)
    corrupt['nodes'][-1]['conclusion'] = ['>', ['symbol', 'c'], ['symbol', 'a']]
    with pytest.raises(ProofFailure):
        _replay(corrupt, ctx, budget=replay_budget)


def test_goal_cache_does_not_leak_changed_premises_or_scope():
    ctx = context('a>0')
    budget = _Budget(ctx.limits)
    _run_request(ctx, request('a>0'), budget=budget)
    for other in (context('a<0'), context()):
        with pytest.raises(ProofFailure):
            _run_request(other, request('a>0'), budget=budget)
    before = budget.counts['nodes']
    _run_request(replace(ctx, scope_id='other'), request('a>0'), budget=budget)
    assert budget.counts['nodes'] > before


def test_duplicate_facts_keep_sources_but_do_not_consume_fact_capacity():
    ctx = context(*(['a>b', 'b<a', '(a)>(b)'] * 7))
    proof = _run_request(ctx, request('a>b')).proof
    assert len([s for s in proof['sources'] if s.startswith('premise:')]) == 21
    _replay(proof, ctx)
    corrupt = deepcopy(proof)
    corrupt['sources']['premise:20']['source'] = 'b>a'
    with pytest.raises(ProofFailure):
        _replay(corrupt, ctx)


def test_distinct_fact_limit_and_domains_are_not_erased():
    with pytest.raises(ProofFailure, match='context size limit'):
        _run_request(context(*(f'a>{i}' for i in range(17))), request('a>0'))
    assert fact_key(from_node(parse_math_relation('a/a=1', SYMBOLS).ast)) != \
        fact_key(from_node(parse_math_relation('1=1', SYMBOLS).ast))


def test_notation_and_line_breaks_have_same_independent_relations():
    facts = ['a>b', 'b>c', 'c>0', 'a>0', 'b>0', 'a-b>0', 'a*b>0', 'a*(a-b)>0', 'b*c>0']
    versions = [[{'math': ','.join(facts)}], [{'math': f} for f in facts],
                [{'math': '∵ a>b>c>0；∴ '+','.join(facts[3:])}]]
    keys = [{fact_key(from_node(r.parsed.ast)) for r in parse_derivation(rows, SYMBOLS)} for rows in versions]
    assert keys[0] == keys[1] == keys[2]


def test_whole_derivation_limit_still_rejects_excess_distinct_relations():
    with pytest.raises(ValueError, match='32'):
        parse_derivation([{'math': ','.join(f'a>{i}' for i in range(33))}], SYMBOLS)


def test_rewrite_limit_applies_across_authored_rows():
    from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
        RewriteError,
        verify_chain,
    )
    rows = [{'math': ','.join(f'a>{i}' for i in range(start, start+11))}
            for start in (0, 11, 22)]
    with pytest.raises(RewriteError, match='32'):
        verify_chain(SYMBOLS['a'], ['a>100'], rows, SYMBOLS, input_source='a')


def test_repeated_sources_still_have_raw_record_limit():
    with pytest.raises(ProofFailure, match='context size limit'):
        _run_request(context(*(['a>0'] * 257)), request('a>0'))


def test_cache_preserves_denominator_obligations():
    ctx = context()
    budget = _Budget(ctx.limits)
    _run_request(ctx, request('1=1'), budget=budget)
    with pytest.raises(ProofFailure):
        _run_request(ctx, request('a/a=1'), budget=budget)


def test_legacy_duplicate_serialized_nodes_remain_replayable():
    ctx = context('a>0')
    proof = _run_request(ctx, request('a>0')).proof
    duplicate = deepcopy(proof['nodes'][-1])
    duplicate['node_id'] = f"p{len(proof['nodes']):04d}"
    proof['nodes'].append(duplicate)
    proof['roots'] = [duplicate['node_id']]
    _replay(proof, ctx)
    # Even an unreferenced node in an old payload must still be checked.
    proof['nodes'][-2]['conclusion'] = ['>', ['symbol', 'b'], ['symbol', 'a']]
    with pytest.raises(ProofFailure):
        _replay(proof, ctx)
