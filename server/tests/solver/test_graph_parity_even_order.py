"""FP-T4 R2: even functions compare absolute inputs; A20 borrows the domain parameter first."""
import copy
import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.parity_inequality_math import solve, verify
from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_runtime import borrow_domain_parameter
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_parity_inequality import candidate
from tests.solver.test_graph_parity_order import TARGET, described
from tools.export_graph_walk_course import export_course

A20 = (r'已知函数 $f(x)$ 是定义在 $[-2b,b+1]$ 上的偶函数，且在 $[-2b,0]$ 上单调递增，'
       r'则 $f(x-1)\le f(2x)$ 的解集为____．')
R = (r'已知 $f(x)$ 是定义在 $\mathbf R$ 上的偶函数，且在 $[0,+\infty)$ 上单调递增，'
     r'则不等式 $f(x-1)<f(2x)$ 的解集为____．')
EVEN_TITLES = ['把两个输入换到非负一侧', '确定非负一侧的单调方向', '去掉函数符号比较输入', '合法输入求交，写出解集']


def given(facts, interval, domain, direction, text=''):
    mono = {'function': 'f', 'domain': interval, 'function_domain': domain, 'direction': direction,
            'strict': True, 'basis': {'kind': 'stated', 'statement': ''}}
    return {'original_text': text, 'root': {'facts': list(facts), 'goals': [
        {'kind': 'find_range', 'symbol': 'x', 'function_monotonicity': mono}]}}


def a20(text=A20):
    return given(['Dom(f)=[-2*b,b+1]', 'parity(f,even)', 'f(x-1)<=f(2*x)'], '[-2*b,0]', '[-2*b,b+1]', 'increasing',
                 text)


def on_reals(inequality='f(x-1)<f(2*x)', interval='[0,∞)', direction='increasing', text=R):
    return given(['Dom(f)=ℝ', 'parity(f,even)', inequality], interval, 'ℝ', direction, text)


def borrowed(value):
    context = build_context(value, TARGET)
    desc = described(value)
    out = dict(desc)
    out['borrowed'] = borrow_domain_parameter(context, desc['parameter']['ref'], desc['parameter']['source_refs'])
    return desc, solve(out)


@pytest.mark.parametrize('value,positive,expected', [
    (on_reals(), 'increasing', sp.Union(sp.Interval.open(-sp.oo, -1), sp.Interval.open(sp.Rational(1, 3), sp.oo))),
    (on_reals('f(x-1)<f(2*x)', '(-∞,0]', 'increasing'), 'decreasing', sp.Interval.open(-1, sp.Rational(1, 3))),
    (candidate(('Dom(f)=ℝ', 'parity(f,even)'), 'x^2+1', '[0,∞)', 'f(x-1)>f(2*x+1)'), 'increasing',
     sp.Interval.open(-2, 0)),
])
def test_even_comparison_uses_absolute_inputs(value, positive, expected):
    desc = described(value)
    assert desc['structure_supported'] and desc['route'] == 'order', desc['reason']
    model = solve(desc)
    assert model['certificate']['positive_direction'] == positive
    assert model['solution'] == expected and verify(desc, model)
    assert not verify(desc, {**model, 'solution': sp.S.Reals - model['solution']})


@pytest.mark.parametrize('value,reason', [
    (on_reals(interval='(0,∞)'), 'parity_ineq.junction_unknown'),
    (on_reals(interval='[-1,∞)'), 'parity_ineq.parity_conflict'),
    (on_reals('f(x-1)+f(2*x)<0'), 'parity_ineq.even_sum_unsupported'),
    (candidate(('Dom(f)=ℝ', 'parity(f,even)'), 'x^2+1', '(0,∞)', 'f(x-1)>f(2*x+1)'), 'parity_ineq.junction_unknown'),
])
def test_unproven_even_comparison_is_a_gap(value, reason):
    desc = described(value)
    if desc['structure_supported']:
        with pytest.raises(ValueError, match=reason):
            solve(desc)
    else:
        assert desc['reason'] == reason


def test_a20_borrows_the_domain_parameter_then_compares():
    desc, model = borrowed(a20())
    assert desc['parameter']['name'] == 'b' and model['borrow']['parameter_value'] == 1
    assert model['legal_set'] == sp.Interval(-1, 1)
    assert model['solution'] == sp.Interval(-1, sp.Rational(1, 3)) and verify(desc, model)
    with pytest.raises(ValueError, match='parameter_requires_borrow'):
        solve(desc)


@pytest.mark.parametrize('change', ['value', 'set', 'instance', 'missing'])
def test_a20_verify_rejects_a_tampered_borrow(change):
    desc, model = borrowed(a20())
    bad = copy.deepcopy(model)
    if change == 'value':
        bad['borrow']['parameter_value'] = sp.Integer(-1)
    elif change == 'set':
        bad['borrow']['output']['parameter_set'] = sp.FiniteSet(-1, 1)
    elif change == 'instance':
        bad['borrow']['output']['instantiated_domain'] = sp.Interval(-2, 3)
    else:
        bad['borrow'] = None
    assert not verify(desc, bad)


@pytest.mark.parametrize('old,new', [('[-2b,b+1]', '[-2b,b+2]'), ('[-2b,0]', '[-b,0]'),
                                     ('偶函数', '奇函数'), (r'f(x-1)\le f(2x)', r'f(x-1)\ge f(2x)')])
def test_a20_binding_follows_the_printed_text(old, new):
    value = a20(A20.replace(old, new))
    assert old in A20
    desc = described(value, bind=True)
    assert not desc['structure_supported'] and desc['reason'] == 'parity_ineq.source_not_bound'
    assert described(a20(), bind=True)['structure_supported']


def _parts(evidence):
    return [part for row in evidence['stream']['interactions'] for part in row['parts']]


@pytest.mark.stage_three_db
def test_a20_end_to_end(tmp_path):
    value = a20()
    prepared, recognized = recognize(value, tmp_path)
    shown = present_lesson(recognized, prepared['features'], value['original_text'], candidate=value)
    reading = shown['goals'][0]['d1']
    assert '只求参数 $b$ 的值' in json.dumps(reading, ensure_ascii=False)
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    goal, = result['goals']
    assert goal['status'] == 'solved', goal
    assert goal['answer']['set']['expression'] == 'Interval(-1, 1/3)'
    assert runner.resume_sample(output)['goals'][0]['answer'] == goal['answer']
    evidence = export_course(output, 'function-parity-a20')
    text = json.dumps(evidence['stream'], ensure_ascii=False)
    assert '左' not in text and '右' not in text
    parts = _parts(evidence)
    assert [part['title'] for part in parts] == ['先确定定义域中的参数', *EVEN_TITLES]
    for part in parts:
        labels = [option['label'] for option in part['interaction']['options']]
        assert len(labels) == len(set(labels)) >= 3
    assert '$b=1$' in [o['label'] for o in parts[0]['interaction']['options']]


@pytest.mark.stage_three_db
def test_corrupt_even_result_never_publishes(tmp_path):
    recognize(a20(), tmp_path)

    def corrupt(state, store):
        state['parity_inequality_result_exact']['solution'] = encode_value(sp.Interval(-1, 1))
    output = tmp_path / 'stage-three'
    result = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output,
                               hooks={'before_verification': corrupt})
    goal, = result['goals']
    assert goal['answer'] is None and goal['routes'][0]['status'] == 'math_failed'
    assert not open_store(output).snapshot()['handoffs']
