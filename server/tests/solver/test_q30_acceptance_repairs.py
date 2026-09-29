"""Regressions from the 2026-09-29 saved Planner responses; no live model."""
import json
from pathlib import Path

import pytest
import sympy as sp
from test_scoped_proof_search_stage_d import context, prove

from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
    RewriteError,
    verify_chain,
)
from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof

FIXTURES = Path(__file__).parent / 'fixtures'
SAVED = FIXTURES / 'basic-inequality-stage5c/acceptance-20260929.json'


@pytest.mark.parametrize('names,k', [('abc', 1), ('uvw', 3)])
def test_local_chain_survives_cancellation_in_whole(names, k):
    a, b, c = names
    symbols = {s: sp.Symbol(s, real=True) for s in names}
    source = f'{c}^2+{k}/({a}*{b})+{k}/({a}*({a}-{b}))'
    trace = verify_chain(sp.sympify(source, locals=symbols), [f'{a}>{b}', f'{b}>0'], [
        {'math': f'{k}/({a}*{b})+{k}/({a}*({a}-{b}))=(1/{a})*({k}/{b}+{k}/({a}-{b}))'},
        {'math': f'{k}/{b}+{k}/({a}-{b})=({k}*({a}-{b})+{k}*{b})/({b}*({a}-{b}))={k}*{a}/({b}*({a}-{b}))'},
    ], symbols, input_source=source)
    assert sp.cancel(trace['value']-sp.sympify(source, locals=symbols)) == 0
    assert trace['verified_notes']


@pytest.mark.parametrize('tail', ['2*a/(b*(a-b))', 'a/(b*(a-b))+0/(a-a)', 'a/(b*(a-b)), c+1=c+1'])
def test_local_chain_cannot_hide_false_undefined_or_unrelated_tail(tail):
    symbols = {s: sp.Symbol(s, real=True) for s in 'abc'}
    source = 'c^2+(1/a)*(1/b+1/(a-b))'
    with pytest.raises(RewriteError):
        verify_chain(sp.sympify(source, locals=symbols), ['a>b', 'b>0'], [
            {'math': '1/b+1/(a-b)=(a-b+b)/(b*(a-b))='+tail},
        ], symbols, input_source=source)


@pytest.mark.parametrize('variable,k', [('a', 4), ('x', 9), ('u', 16)])
def test_cancelled_radicand_uses_bounded_direct_proof(variable, k):
    ctx = context([f'{variable}^2>0', f'{k}/{variable}^2>0'], variables=variable)
    run = prove(f'2*sqrt({variable}^2*({k}/{variable}^2))={2*int(k**0.5)}', ctx)
    assert run.result.status == 'proved', run.result
    assert replay_proof(run.result.proof, ctx).status == 'proved'
    assert run.diagnostics['counts']['arithmetic_operations'] < 3000
    assert not any(e.get('status') == 'strategy_budget_exhausted' for e in run.diagnostics['trace'])


@pytest.mark.parametrize('premises,relation', [
    ((), '2*sqrt(a^2*(4/a^2))=4'),
    (('a^2>0',), '2*sqrt(a^2*(4/a^2))=-4'),
    (('a^2>0',), '2*sqrt(a^2*(4/a^2))=5'),
])
def test_root_simplification_still_requires_domain_and_correct_sign(premises, relation):
    assert prove(relation, context(premises, variables='a')).result.status != 'proved'


def test_saved_local_chain_is_valid_without_changing_model_math():
    plan = json.loads(SAVED.read_text())['local_chain']
    steps = plan['root_scope']['steps'][0]['parameters']['steps']
    from test_natural_derivation_repairs import SYMBOLS, F
    trace = verify_chain(sp.sympify(F, locals=SYMBOLS), ['a>b', 'b>c', 'c>0'],
                         steps, SYMBOLS, input_source=F)
    assert sp.cancel(trace['value']-sp.sympify(F, locals=SYMBOLS)) == 0


@pytest.mark.parametrize('case', ['binding_error', 'root_equality'])
def test_saved_plan_binding_feedback_and_direct_root_closure(case, tmp_path):
    from tools.run_basic_inequality_stage4a import run
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps(json.loads(SAVED.read_text())[case]))
    output = tmp_path / 'result'
    result, _ = run(gold=FIXTURES / 'math-notation-v1/basic-inequality/q30.json',
                    problem_ir=FIXTURES / 'basic-inequality-problem-ir/v1/q30/problem-ir.json',
                    mode='recorded', plan=plan, output=output)
    if case == 'root_equality':
        assert result.status == 'ok', result.to_dict()
        assert result.answers == {'problem': {'minimum': '4'}}
        assert not (output / 'attempt-2.canonical-plan.json').exists()
    else:
        assert result.status != 'ok'
        report = json.loads((output / 'attempt-1.functional-reconciliation-report.json').read_text())
        issues = report['issues']
        assert any(i['code'] == 'functional.arg_type_mismatch' and i['details'].get('arg_name') == 'expression'
                   for i in issues), issues
        assert not any(i['code'] == 'functional.return_type_mismatch' for i in issues), issues
        request = json.loads((output / 'attempt-2.request.json').read_text())
        user = next(m['content'] for m in request['messages'] if m['role'] == 'user')
        annotated = json.loads(user.split('## Annotated Previous Plan\n\n')[1].split('\n\n## ')[0])
        error = annotated['root_scope']['scope_steps'][0]['execution']['error']
        assert error['code'] == 'functional.arg_type_mismatch'
        assert error['expected']['argument'] == 'expression'
        assert error['observed']['compatible_refs'][0]['ref'] == 'target_expression'


def test_live_acceptance_allows_alternative_order_but_requires_verified_replay():
    from tools.run_basic_inequality_stage5c import planner_runs_pass
    rows = [{'status': 'ok', 'replay_ok': True, 'mixed_chain_executed': False}] * 3
    assert planner_runs_pass(rows, 3)
    assert not planner_runs_pass(rows[:2], 3)
    assert not planner_runs_pass([*rows[:2], {'status': 'ok', 'replay_ok': False}], 3)
    assert not planner_runs_pass([*rows[:2], {'status': 'failed', 'replay_ok': True}], 3)
