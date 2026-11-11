"""FP-T4 R3: the sign route — signs from a strict direction and one zero, carried by parity, met with a factor."""
import copy
import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.parity_inequality_math import solve, verify
from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_order import described
from tools.export_graph_walk_course import export_course

A19 = (r'已知 $f(x)$ 是奇函数，且在 $(0,+\infty)$ 上是增函数，又 $f(2)=0$，'
       r'则 $\frac{f(x-1)}{x}<0$ 的解集为____．')
SIGN_TITLES = ['确定已知区间上函数值的符号', '用奇偶性得到另一侧的符号', '结合分母列出符号条件', '解出各种情况，写出解集']
o = sp.Interval.open


def given(facts, interval='(0,∞)', direction='increasing', domain=None, text='', strict=True):
    mono = {'function': 'f', 'domain': interval, 'direction': direction, 'strict': strict,
            'basis': {'kind': 'stated', 'statement': ''}}
    if domain:
        mono['function_domain'] = domain
    return {'original_text': text, 'root': {'facts': list(facts), 'goals': [
        {'kind': 'find_range', 'symbol': 'x', 'function_monotonicity': mono}]}}


def a19(text=A19, relation='f(x-1)/x<0'):
    return given(['parity(f,odd)', 'f(2)=0', relation], text=text)


@pytest.mark.parametrize('value,identity,expected', [
    (a19(), 'zero_membership_open', o(-1, 0) | o(1, 3)),
    (given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=0', 'f(x-1)/x<=0']), 'explicit',
     sp.Interval.Ropen(-1, 0) | sp.Interval(1, 3)),
    (given(['parity(f,odd)', 'f(-3)=0', 'x*f(x)<0']), 'zero_membership_open', o(-3, 0) | o(0, 3)),
    (given(['parity(f,even)', 'f(2)=0', 'x*f(x)>0'], direction='decreasing'), 'zero_membership_open',
     o(-sp.oo, -2) | o(0, 2)),
    (given(['parity(f,odd)', 'f(-2)=0', 'f(x)/(x^2-1)>0'], interval='(-∞,0)'), 'zero_membership_open',
     o(-2, -1) | o(0, 1) | o(2, sp.oo)),
    (given(['Dom(f)=(-3,3)', 'parity(f,odd)', 'f(1)=0', 'f(x)<0'], interval='(0,3)'), 'explicit',
     o(-3, -1) | o(0, 1)),
])
def test_sign_route_solves_and_verifies(value, identity, expected):
    desc = described(value)
    assert desc['structure_supported'] and desc['route'] == 'sign', desc['reason']
    model = solve(desc)
    assert model['certificate']['domain_identity'] == identity
    assert model['solution'] == expected and verify(desc, model)


@pytest.mark.parametrize('value,reason', [
    (a19(relation='f(x-1)/x<=0'), 'parity_ineq.domain_dependent_answer'),
    (given(['parity(f,even)', 'f(2)=0', 'f(x)<0']), 'parity_ineq.zero_value_unknown'),
    (given(['parity(f,odd)', 'f(x-1)/x<0']), 'parity_ineq.sign_zero_unknown'),
    (given(['parity(f,odd)', 'f(2)=0', 'f(x-1)/x<0'], interval='(-1,∞)'), 'parity_ineq.sign_interval_not_one_side'),
    (given(['parity(f,odd)', 'f(2)=0', 'f(3)=0', 'f(x)<0']), 'parity_ineq.zero_conflict'),
    (given(['Dom(f)=(-3,3)', 'parity(f,odd)', 'f(5)=0', 'f(x)<0'], interval='(0,3)'), 'parity_ineq.zero_outside_domain'),
    (given(['parity(f,odd)', 'f(2)=0', 'f(x-1)/x<0'], interval='(0,3)'), 'parity_ineq.domain_required'),
    (given(['parity(f,odd)', 'f(2)=0', 'f(x-1)<f(x)']), 'parity_ineq.unprocessed_fact'),
])
def test_unproven_sign_is_a_gap(value, reason):
    desc = described(value)
    assert desc is not None and not desc['structure_supported'] and desc['reason'] == reason


def test_a_non_strict_direction_is_not_admitted():
    with pytest.raises(ValueError, match='context.invalid_candidate'):
        described(given(['parity(f,odd)', 'f(2)=0', 'f(x-1)/x<0'], strict=False))


def test_two_increasing_halves_are_not_one_increasing_function():
    desc = described(given(['Dom(f)=ℝ', 'parity(f,odd)', 'f(x-1)<f(2*x)']))
    assert desc['route'] == 'order' and desc['reason'] == 'parity_ineq.junction_unknown'


def _tampered(change):
    desc = described(a19())
    model = copy.deepcopy(solve(desc))
    cert = model['certificate']
    if change == 'solution':
        model['solution'] = o(-1, 0) | sp.Interval.Lopen(1, 3)
    elif change == 'zero':
        cert['zero'] = sp.Integer(3)
    elif change == 'direction':
        cert['direction'] = 'decreasing'
    elif change == 'identity':
        cert['domain_identity'] = 'explicit'
    elif change == 'case':
        model['cases'][1]['zero_sign'] = 1
    elif change == 'legal':
        model['cases'][0]['legal_set'] = sp.S.Reals
    elif change == 'factor':
        model['factor'] = sp.Symbol('x', real=True) + 1
    return desc, model


@pytest.mark.parametrize('change', ['solution', 'zero', 'direction', 'identity', 'case', 'legal', 'factor'])
def test_verify_rejects_tampered_sign_models(change):
    desc, model = _tampered(change)
    assert not verify(desc, model)


@pytest.mark.parametrize('old,new', [('f(2)=0', 'f(3)=0'), ('增函数', '减函数'), ('奇函数', '偶函数'),
                                     ('<0$', '>0$'), ('{x}', '{x+1}'), (r'(0,+\infty)', r'(1,+\infty)')])
def test_a19_binding_follows_the_printed_text(old, new):
    assert old in A19
    desc = described(a19(A19.replace(old, new)), bind=True)
    assert not desc['structure_supported'] and desc['reason'] == 'parity_ineq.source_not_bound'
    assert described(a19(), bind=True)['structure_supported']


def _parts(evidence):
    return [part for row in evidence['stream']['interactions'] for part in row['parts']]


@pytest.mark.stage_three_db
def test_a19_end_to_end(tmp_path):
    value = a19()
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][0]['d1']
    assert '求不等式 $\\frac{f(x-1)}{x}<0$ 的解集' in reading['summary']
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['answer']['set']['expression'] == 'Union(Interval.open(-1, 0), Interval.open(1, 3))'
    assert runner.resume_sample(output)['goals'][0]['answer'] == goal['answer']
    evidence = export_course(output, 'function-parity-a19')
    text = json.dumps(evidence['stream'], ensure_ascii=False)
    assert '左' not in text and '右' not in text
    parts = _parts(evidence)
    assert [part['title'] for part in parts] == SIGN_TITLES
    for part in parts:
        labels = [option['label'] for option in part['interaction']['options']]
        assert len(labels) == len(set(labels)) >= 3
    assert '异号' not in parts[2]['question']
    assert '$x\\in \\left(-1, 0\\right) \\cup \\left(1, 3\\right)$' in [o['label'] for o in parts[3]['interaction']['options']]


@pytest.mark.stage_three_db
def test_corrupt_sign_result_never_publishes(tmp_path):
    recognize(a19(), tmp_path)

    def corrupt(state, store):
        state['parity_inequality_result_exact']['solution'] = encode_value(o(-1, 0) | sp.Interval(1, 3))
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    goal, = result['goals']
    assert goal['answer'] is None and goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
