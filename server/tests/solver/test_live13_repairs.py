"""Natural local algebra and explicit references to certified attainment."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.solver.math_kernel.derivation_math import parse_derivation
from shuxueshuo_server.solver.math_kernel.inequality_evidence import verify_bound, public_bound, close_bound
from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError
from tools.run_basic_inequality_stage4a import run

FIXTURES = Path(__file__).parent / 'fixtures'
PLANS = json.loads((FIXTURES/'basic-inequality-stage5c/live13-plans.json').read_text())


def target(expr, conditions, symbols):
    return {'type':'extremum_target', 'goal_kind':'find_minimum', 'scope_id':'problem',
            'scalar_symbols':symbols, 'target_math':expr,
            'source_conditions':[{'handle':f'c{i}', 'source_path':f'/facts/{i}', 'math':v}
                                 for i,v in enumerate(conditions)]}


@pytest.mark.parametrize('coefficient', [1, 3])
@pytest.mark.parametrize('symbols', [('a','b','c'), ('x','y','z')])
def test_split_reciprocals_preserve_parameter_remainder(coefficient, symbols):
    a,b,c = symbols
    expr = f'{a}^2+{coefficient}/({a}*{b})+{coefficient}/({a}*({a}-{b}))+({a}-5*{c})^2'
    t = target(expr, [f'{a}>{b}', f'{b}>0'], list(symbols))
    steps = [{'math': f'{b}*({a}-{b})<=({a}/2)^2'},
             {'math': f'1/({b}*({a}-{b}))>=4/{a}^2'},
             {'math': f'{expr}>=({a}-5*{c})^2+{4*coefficient}/{a}^2+{a}^2'}]
    bound = public_bound(verify_bound(t, steps))
    assert replay_bound(t, bound)['bound'] == bound['bound']
    bad = deepcopy(steps)
    bad[-1]['math'] = f'{expr}>={4*coefficient}/{a}^2+{a}^2'
    with pytest.raises(ProofFailure):
        verify_bound(t, bad)
    with pytest.raises(ProofFailure):
        verify_bound({**t, 'source_conditions':[]}, steps)
    tampered = deepcopy(bound)
    tampered['certificate_bundle']['local_application']['relations'][0] = '1=1'
    with pytest.raises(ProofFailure):
        replay_bound(t, tampered)


@pytest.fixture
def simple_bound():
    t = target('x+4/x', ['x>0'], ['x'])
    return t, public_bound(verify_bound(t, [{'math':'x+4/x>=4'}]))


@pytest.mark.parametrize('colon', [':','：'])
def test_attainment_reference_is_verified_and_located(simple_bound, colon):
    t,b = simple_bound
    phrase = f'∵ x+4/x>=4 取等{colon}x=4/x；∴ x=2'
    value, evidence = close_bound(t,b,[{'math':phrase}])
    assert value == 4
    origin = next(o for o in evidence['derivation_origins'] if o.get('equality_reference'))
    assert origin['source'] == phrase
    assert origin['source_path'] == '/parameters/steps/0/math'
    token = origin['language_tokens'][0]
    assert phrase[slice(*token['span'])] == '取等'
    with pytest.raises(MathParseError):
        parse_derivation([{'math':phrase}], {'x'})


@pytest.mark.parametrize('phrase', [
    '∵ x+4/x>=4 取等：x=2', # not a certificate condition, even at a valid witness
    '∵ x+4/x>=3 取等：x=4/x', # valid inequality, wrong attainment association
    '∵ x>=2 取等：x=4/x', # only true at the witness, not universally valid
    '∵ x+4/x>4 取等：x=4/x',
    '∵ x+4/x>=4 取等：x>0',
    '∵ x+4/x>=4 不取等：x=4/x',
])
def test_attainment_reference_cannot_create_authority(simple_bound, phrase):
    t,b = simple_bound
    with pytest.raises((ProofFailure,MathParseError)):
        close_bound(t,b,[{'math':phrase},{'math':'x=2'}])


def test_reference_does_not_supply_witness(simple_bound):
    t,b = simple_bound
    with pytest.raises(ProofFailure, match='explicit constant assignment'):
        close_bound(t,b,[{'math':'∵ x+4/x>=4 取等：x=4/x'}])


@pytest.mark.parametrize('sample', ['1','2','3'])
def test_real_first_attempt_plan(tmp_path, sample):
    plan = tmp_path/'plan.json'
    plan.write_text(json.dumps({'format':'functional_plan/v2', 'root_scope':{'scope_ref':'problem', 'steps':PLANS[sample].get('scope_steps',{}).get('problem',[]), 'goals':[{'goal_ref':key, **value} for key,value in PLANS[sample]['goal_plans'].items()]}}))
    result,_ = run(gold=FIXTURES/'math-notation-v1/basic-inequality/q30.json',
                   problem_ir=FIXTURES/'basic-inequality-problem-ir/v1/q30/problem-ir.json',
                   plan=plan, mode='recorded', output=tmp_path/'run')
    assert result.status == 'ok', result.to_dict()
    assert result.answers == {'problem':{'minimum':'4'}}
    execution = (tmp_path/'run'/'attempt-1.verified-execution.json').read_text()
    assert '"local_reciprocal_roles"' in execution


def test_reference_cannot_borrow_another_stages_equality():
    t = target('x+4/x+y+4/y', ['x>0','y>0'], ['x','y'])
    first = public_bound(verify_bound(t, [{'math':'x+4/x+y+4/y>=4+y+4/y'}]))
    last = public_bound(verify_bound(t, [{'math':'4+y+4/y>=8'}], previous_bound=first))
    with pytest.raises(ProofFailure):
        close_bound(t, last, [{'math':'∵ x+4/x>=4 取等：y=4/y'}, {'math':'x=2,y=2'}])
