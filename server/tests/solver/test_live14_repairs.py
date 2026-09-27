"""Avoid sign-search detours and parse conclusion-marked attainment references."""
import json
from dataclasses import replace
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError, parse_math_relation
from shuxueshuo_server.solver.math_kernel.inequality_evidence import verify_bound, public_bound, close_bound
from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
from shuxueshuo_server.solver.math_kernel.inequality_bound_v2 import verify as verify_with_budget
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.math_kernel.proof_kernel import ProofContext, ProofLimits, _Budget, prove_relation, replay_proof
from tools.run_basic_inequality_stage4a import run

FIXTURES = Path(__file__).parent/'fixtures'
PLANS = json.loads((FIXTURES/'basic-inequality-stage5c/live14-plans.json').read_text())


def calls(value):
    if isinstance(value, dict):
        if 'capability_id' in value:
            yield value
        else:
            for item in value.values():
                yield from calls(item)
    elif isinstance(value, list):
        for item in value:
            yield from calls(item)


def target(expression, conditions, symbols):
    return {'type':'extremum_target','goal_kind':'find_minimum','scope_id':'problem',
            'scalar_symbols':symbols,'target_math':expression,
            'source_conditions':[{'handle':f'c{i}','source_path':f'/facts/{i}','math':v}
                                 for i,v in enumerate(conditions)]}


@pytest.mark.parametrize('rename', [False, True])
def test_real_m11_stays_within_reduction_and_context_limits(rename):
    steps = next(c for c in calls(PLANS['1']) if c['step_id']=='amgm_b')['parameters']['steps']
    expression = '2*a^2+1/(a*b)+1/(a*(a-b))-10*a*c+25*c^2'
    conditions = ['a>b','b>c','c>0']
    symbols = ['a','b','c']
    if rename:
        import re
        mapping = dict(zip('abc','xyz'))
        def convert(text):
            return re.sub(r'\b[abc]\b', lambda m:mapping[m[0]], text)
        steps = [{'math':convert(row['math'])} for row in steps]
        expression = convert(expression)
        conditions = list(map(convert,conditions))
        symbols = list('xyz')
    t = target(expression, conditions, symbols)
    budget = _Budget(ProofLimits())
    bound = public_bound(verify_with_budget(t, steps, budget=budget))
    assert budget.counts.get('reductions', 0) < 64
    assert replay_bound(t, bound)['bound'] == bound['bound']


@pytest.mark.parametrize('sign, result', [('>','>'),('<','>'),('>=','>=')])
def test_compound_operand_signs_precede_equation_transport(sign, result):
    symbols = {v:sp.Symbol(v,real=True) for v in ['a','b']}
    texts = [f'b{sign}0',f'a-b{sign}0', '1/(a*b)+1/(a*(a-b))=1/(b*(a-b))']
    context = ProofContext(symbols, {f'p{i}':parse_math_relation(t,symbols) for i,t in enumerate(texts)},
                           limits=ProofLimits(reductions=8))
    proof = prove_relation(parse_math_relation(f'b*(a-b){result}0',symbols),context)
    assert proof.status == 'proved', proof
    assert replay_proof(proof.proof, context).status == 'proved'
    # A sign of a-b must not be manufactured from the other factor's sign.
    missing = replace(context, premises={'p0':context.premises['p0']})
    assert prove_relation(parse_math_relation('b*(a-b)>0',symbols),missing).status != 'proved'


@pytest.fixture
def simple_bound():
    t = target('x+4/x',['x>0'],['x'])
    return t,public_bound(verify_bound(t,[{'math':'x+4/x>=4'}]))


@pytest.mark.parametrize('separator', ['；',';',',','，'])
def test_conclusion_marker_references_same_attainment(simple_bound, separator):
    t,b = simple_bound
    text = f'∵ x+4/x>=4 取等{separator}∴ x=4/x；∴ x=2'
    value,evidence = close_bound(t,b,[{'math':text}])
    assert value == 4
    origin = next(o for o in evidence['derivation_origins'] if o.get('equality_reference'))
    assert origin['equality_reference']['inequality'] == 'x+4/x >= 4'
    assert origin['source'] == text
    assert [text[slice(*token['span'])] for token in origin['language_tokens']] == ['取等',separator,'∴']


@pytest.mark.parametrize('text', [
    '∵ x+4/x>=4 取等；∵ x=4/x',
    '∵ x+4/x>=4 取等；x=4/x',
    '∵ x+4/x>=4 取等；∴ x>0',
    '∵ x+4/x>=3 取等；∴ x=4/x',
    '∵ x+4/x>4 取等；∴ x=4/x',
    '∵ x+4/x>=4 不取等；∴ x=4/x',
])
def test_reference_separator_cannot_change_mathematical_role(simple_bound,text):
    t,b = simple_bound
    with pytest.raises((ProofFailure,MathParseError)):
        close_bound(t,b,[{'math':text},{'math':'x=2'}])


@pytest.mark.parametrize('sample',['1','3'])
def test_original_first_response_end_to_end(tmp_path,sample):
    payload = PLANS[sample]
    scoped = {'format':'functional_plan/v2','root_scope':{
        'scope_ref':'problem','steps':payload.get('scope_steps',{}).get('problem',[]),
        'goals':[{'goal_ref':key,**value} for key,value in payload['goal_plans'].items()]}}
    plan = tmp_path/'plan.json'
    plan.write_text(json.dumps(scoped))
    result,_ = run(gold=FIXTURES/'math-notation-v1/basic-inequality/q30.json',
                   problem_ir=FIXTURES/'basic-inequality-problem-ir/v1/q30/problem-ir.json',
                   plan=plan, mode='recorded',output=tmp_path/'run')
    assert result.status == 'ok', result.to_dict()
    assert result.answers == {'problem':{'minimum':'4'}}
    assert len(list((tmp_path/'run').glob('attempt-*.raw-response.txt'))) == 1
