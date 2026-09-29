"""M01's 原式 is a bound input reference, never a new symbol or assumption."""
import json
from dataclasses import replace
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError
from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
    RewriteError,
    verify_chain,
)


@pytest.mark.parametrize('source,rows,conditions', [
    ('a+b', ['∴ 原式=b+a'], []),
    ('3*a+3*b', ['3*a+3*b=3*(a+b)', '∴ 原式=3*(a+b)'], []),
    ('a+b', ['∴ 原式=b+a=a+b'], []),
    ('a+b', ['∴ b+a=原式'], []),
    ('a+b', ['∵ 原式=b+a；∴ a+b=b+a'], []),
    ('a+b', ['∵ a+b=4；∴ a+b=4', '∵ a+b=4；∴ 原式=4'], ['a+b=4']),
])
def test_original_expression_is_resolved_against_input(source, rows, conditions):
    symbols = {s: sp.Symbol(s, real=True) for s in 'ab'}
    trace = verify_chain(sp.sympify(source, locals=symbols), conditions,
                         [{'math': row} for row in rows], symbols, input_source=source)
    assert trace['submitted_steps'] == [{'math': row} for row in rows]
    origins = [origin for row in trace['relation_origins'] for origin in row['relations']]
    refs = [origin for origin in [*origins, *trace.get('verified_notes', [])]
            if origin.get('expression_references')]
    assert refs
    assert refs[-1]['expression_references'][0]['math'] == source


def test_reference_expansion_preserves_original_location_and_bound_math():
    symbols = {'x': sp.Symbol('x', real=True)}
    source = '∴ 原式 = 2*x'
    row, = parse_derivation([{'math': source}], symbols, original_expression='x+x')
    ref, = row.origin['expression_references']
    assert row.origin['source'] == source
    assert source[slice(*ref['span'])] == '原式'
    assert ref['math'] == 'x+x'
    assert row.parsed.source == '(x+x) = 2*x'
    with pytest.raises(MathParseError):
        parse_derivation([{'math': source}], symbols)


@pytest.mark.parametrize('claim', [
    '∴ 原式=a+b+1', '∴ 原式=a+b+0/(a-a)',
    '∵ 原式=0；∴ a+b=0', '∴ 原式>=0',
    '∴ 原式不是=a+b', '∴ 新原式=a+b',
])
def test_original_reference_does_not_bypass_validation(claim):
    symbols = {s: sp.Symbol(s, real=True) for s in 'ab'}
    with pytest.raises(RewriteError):
        verify_chain(symbols['a']+symbols['b'], [], [{'math': claim}], symbols,
                     input_source='a+b')


def test_original_reference_does_not_cancel_input_domain():
    a = sp.Symbol('a', real=True)
    with pytest.raises(RewriteError, match='input_domain_unverified'):
        verify_chain(sp.Integer(1), [], [{'math': '∴ 原式=1'}], {'a': a}, input_source='a/a')


def test_saved_q30_m01_original_reference(monkeypatch):
    fixture = Path(__file__).parent / 'fixtures/basic-inequality-stage5c/original-expression-m01.json'
    data = json.loads(fixture.read_text())
    symbols = {s: sp.Symbol(s, real=True) for s in 'abc'}
    trace = verify_chain(sp.sympify(data['input'], locals=symbols), data['conditions'],
                         data['steps'], symbols, input_source=data['input'])
    assert sp.cancel(trace['value']-sp.sympify(data['input'], locals=symbols)) == 0
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof
    from shuxueshuo_server.solver.math_kernel.proof_search import SearchScheduler
    from shuxueshuo_server.solver.math_kernel.proof_types import (
        ProofContext,
        ProofLimits,
    )

    monkeypatch.setattr(SearchScheduler, 'prove', lambda *a, **kw: pytest.fail('replay searched'))
    for proof, saved in zip(trace['proofs'], trace['proof_contexts'], strict=True):
        ctx = ProofContext(
            {s: symbols[s] for s in saved['symbols']},
            {key: replace(parse_math_relation(p['source'], symbols), source_path=p['source_path'], step=p['step'])
             for key, p in saved['premises'].items()},
            scope_id=saved['scope_id'], limits=ProofLimits(**saved['limits']))
        assert replay_proof(proof, ctx).status == 'proved'
