"""Real Planner regressions: natural local rewrites and mixed-bound feedback."""
import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.solver.math_kernel.expression_rewrite import verify_chain, RewriteError
from shuxueshuo_server.solver.math_kernel.inequality_bound_v2 import verify, public, close
from shuxueshuo_server.solver.math_kernel.quadratic_bound import verify_quadratic
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure

FIXTURE = Path(__file__).parent / 'fixtures/basic-inequality-stage5c/live08-failures.json'
F = '2*a^2+1/(a*b)+1/(a*(a-b))-10*a*c+25*c^2'
SYMBOLS = {s: sp.Symbol(s, real=True) for s in 'abc'}
TARGET = {'type': 'extremum_target', 'goal_kind': 'find_minimum', 'scope_id': 'problem',
          'scalar_symbols': list('abc'), 'target_math': F,
          'source_conditions': [{'handle': f'c{i}', 'source_path': f'/facts/{i}', 'math': s}
                                for i, s in enumerate(['a>b', 'b>c', 'c>0'])]}


@pytest.mark.parametrize('variable', ['a', 'b'])
def test_local_summary_can_reference_preceding_state(variable):
    x = variable
    source = f'2*{x}^2-10*{x}*c+25*c^2+1/{x}'
    result = rewrite(source, [
        f'∵ ({x}-5*c)^2={x}^2-10*{x}*c+25*c^2；∴ -10*{x}*c+25*c^2=({x}-5*c)^2-{x}^2',
        f'∴ 2*{x}^2-10*{x}*c+25*c^2={x}^2+({x}-5*c)^2',
        f'∴ {source}={x}^2+({x}-5*c)^2+1/{x}',
    ])
    assert sp.cancel(result['value']-sp.sympify(source, locals=SYMBOLS)) == 0
    assert any(n.get('role') == 'historical_local_summary' for n in result['verified_notes'])


@pytest.mark.parametrize('summary', [
    '2*a^2-10*a*c+25*c^2=a^2+(a-5*c)^2+1',
    '2*a^2-10*a*c+25*c^2=a^2+(a-5*c)^2+0/(b-b)',
    'b+c=c+b',
])
def test_historical_local_summary_cannot_hide_error_or_unrelated_claim(summary):
    with pytest.raises(RewriteError):
        rewrite('2*a^2-10*a*c+25*c^2+1/a', [
            '-10*a*c+25*c^2=(a-5*c)^2-a^2', summary,
        ])


def test_missing_input_domain_conditions_are_actionable():
    with pytest.raises(RewriteError) as caught:
        verify_chain(sp.sympify(F, locals=SYMBOLS), [],
                     [{'math': F+'='+F}], SYMBOLS, input_source=F)
    assert caught.value.code == 'input_domain_unverified'
    assert 'args.conditions' in str(caught.value)
    assert len(caught.value.unverified_conditions) == 2
    assert all('!=' in s for s in caught.value.unverified_conditions)


def calls(key, fixture=FIXTURE):
    result = {}
    def visit(x):
        if isinstance(x, dict):
            if 'capability_id' in x:
                result[x['step_id']] = x['parameters']
            else:
                for v in x.values():
                    visit(v)
        elif isinstance(x, list):
            for v in x:
                visit(v)
    visit(json.loads(fixture.read_text())[key])
    return result


CAPACITY = FIXTURE.with_name('live09-capacity.json')


@pytest.mark.parametrize('key', ['1-1', '1-2'])
def test_live09_natural_rewrite_capacity(key):
    trace = rewrite(F, [r['math'] for r in calls(key, CAPACITY)['organize_target']['steps']])
    assert sp.cancel(trace['value']-sp.sympify(F, locals=SYMBOLS)) == 0


def test_natural_rewrite_capacity_generalizes_names_and_standalone_because():
    import re
    names = dict(zip('abc', 'uvw'))
    rename = lambda text: re.sub(r'\b[abc]\b', lambda m: names[m[0]], text)
    symbols = {s: sp.Symbol(s, real=True) for s in names.values()}
    rows = [{'math': '∵ u>v>w>0'}] + [
        {'math': rename(r['math'])}
        for r in calls('1-2', CAPACITY)['organize_target']['steps']
    ]
    source = rename(F)
    trace = verify_chain(sp.sympify(source, locals=symbols), ['u>v', 'v>w', 'w>0'],
                         rows, symbols, input_source=source)
    assert sp.cancel(trace['value']-sp.sympify(source, locals=symbols)) == 0
    assert trace['verified_notes'][0]['step'] == 0


def test_live09_duplicate_context_capacity():
    bound = public(verify(TARGET, calls('2-2', CAPACITY)['s2_amgm1']['steps'],
                          expression='a^2+(a-5*c)^2+1/(b*(a-b))'))
    from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
    assert replay_bound(TARGET, bound)['bound'] == bound['bound']


def rewrite(source, steps, conditions=None):
    return verify_chain(sp.sympify(source, locals=SYMBOLS), conditions or ['a>b', 'b>c', 'c>0'],
                        [{'math': s} for s in steps], SYMBOLS, input_source=source)


def test_historical_m01_local_identity_preserves_whole_target():
    trace = rewrite(F, [r['math'] for r in calls('1-1')['step1']['steps']])
    assert sp.cancel(trace['value'] - sp.sympify(F, locals=SYMBOLS)) == 0
    assert trace['inferred_transitions'][0]['row'] == 1
    assert len(trace['transitions']) == 2


def test_because_local_identity_then_whole_conclusion():
    local = '1/(a*b)+1/(a*(a-b))=1/(b*(a-b))'
    after = '2*a^2+1/(b*(a-b))-10*a*c+25*c^2'
    trace = rewrite(F, ['∵ '+local+'；∴ '+F+'='+after])
    assert sp.cancel(trace['value'] - sp.sympify(F, locals=SYMBOLS)) == 0


@pytest.mark.parametrize('prefix', ['', '∵ ', '∴ '])
@pytest.mark.parametrize('symbol,k', [('a', 2), ('b', 3)])
def test_local_rewrite_generalizes_without_required_markers(prefix, symbol, k):
    source = f'c^2+1/{symbol}+{k}/{symbol}'
    trace = rewrite(source, [prefix+f'1/{symbol}+{k}/{symbol}={(k+1)}/{symbol}'])
    assert sp.cancel(trace['value']-sp.sympify(source, locals=SYMBOLS)) == 0


def test_local_because_in_separate_row_then_whole_conclusion():
    after = '2*a^2+1/(b*(a-b))-10*a*c+25*c^2'
    trace = rewrite(F, ['∵ 1/(a*b)+1/(a*(a-b))=1/(b*(a-b))',
                        '∴ '+F+'='+after])
    assert sp.cancel(trace['value']-sp.sympify(F, locals=SYMBOLS)) == 0


@pytest.mark.parametrize('claim', [
    '1/(a*b)+1/(a*(a-b))=2/(b*(a-b))',
    F+'=1/(b*(a-b))',
    '∵ a=b；∴ '+F+'='+F,
    '∵ 1/(a-a)=1/(a-a)；∴ '+F+'='+F,
    'c+1=c+1',
])
def test_bad_local_or_whole_claim_is_rejected(claim):
    with pytest.raises(RewriteError):
        rewrite(F, [claim])


def test_ambiguous_local_replacement_is_rejected():
    with pytest.raises(RewriteError, match='ambiguous'):
        rewrite('1/(a+b)+(a+b)^2', ['a+b=b+a'])


def first_bound():
    return public(verify(TARGET, calls('2-1')['step2']['steps'],
                         expression='a^2+(a-5*c)^2+1/(b*(a-b))'))


def test_m11_square_removal_reports_contract_instead_of_budget():
    with pytest.raises(ProofFailure) as exc:
        verify(TARGET, calls('2-2')['step3']['steps'], previous_bound=first_bound())
    assert exc.value.code == 'amgm_remainder_changed'


@pytest.mark.parametrize('expression', ['4+(a-5*c)^2>=4', '7+(b-3*c)^2>=7'])
def test_square_with_common_addend_has_direct_replayable_proof(expression):
    from shuxueshuo_server.solver.math_kernel.proof_kernel import ProofContext, prove_relation, replay_proof
    from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
    premises = ['a>b', 'b>c', 'c>0', 'a^2+4/a^2>=4', '4/a^2>0']
    context = ProofContext(SYMBOLS, {str(i): parse_math_relation(s, SYMBOLS) for i, s in enumerate(premises)})
    result = prove_relation(parse_math_relation(expression, SYMBOLS), context)
    assert result.status == 'proved'
    assert replay_proof(result.proof, context).status == 'proved'


def test_historical_m11_incomplete_final_target_rejected():
    with pytest.raises(ProofFailure) as exc:
        verify(TARGET, calls('2-1')['step3']['steps'], previous_bound=first_bound())
    assert exc.value.code == 'target_bound_mismatch'


def last_bound():
    c = calls('2-3')
    quadratic = public(verify_quadratic(TARGET, **c['step3'], previous_bound=first_bound()))
    return public(verify(TARGET, c['step4']['steps'], previous_bound=quadratic))


def test_m13_natural_comparison_chains_all_verified():
    value, evidence = close(TARGET, last_bound(), [calls('2-3')['step5']['steps']])
    assert value == 4
    branch = evidence['branches'][0]
    assert len(branch['proof_batches']) == 2
    assert max(c['proof_requirement'] for c in branch['requirement_coverage']) == 16
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import target_context
    from shuxueshuo_server.solver.math_kernel.proof_kernel import replay_proof
    from copy import deepcopy
    context, _ = target_context(TARGET)
    for proof in branch['proof_batches']:
        assert replay_proof(proof, context).status == 'proved'
    corrupt = deepcopy(branch['proof_batches'][-1])
    corrupt['request']['requirements'][0]['source'] = 'a=3'
    assert replay_proof(corrupt, context).status != 'proved'


def test_live09_m13_natural_satisfies_clause_closes_without_editing_input():
    rows = calls('1-2', CAPACITY)['close_and_minimum']['steps']
    assert any('满足' in row['math'] for row in rows)
    value, evidence = close(TARGET, last_bound(), [rows])
    assert value == 4
    assert evidence['branches']
    wrong_rows = rows + [{'math': '因此满足 a<b'}]
    with pytest.raises(ProofFailure):
        close(TARGET, last_bound(), [wrong_rows])


def test_m13_false_tail_in_second_batch_is_not_ignored():
    rows = calls('2-3')['step5']['steps'] + [{'math': 'a=3'}]
    with pytest.raises(ProofFailure):
        close(TARGET, last_bound(), [rows])
