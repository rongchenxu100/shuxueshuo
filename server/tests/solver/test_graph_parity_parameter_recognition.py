"""Bound given properties, honest capability gaps and preserved parent goals."""
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from tests.solver.test_graph_parity_parameter import TARGET, candidate


@pytest.mark.parametrize('text', [
    '已知 $f(x)=m*x^2$ 为奇函数，求 $m$ 的值。',
    '已知 $f(x)=m*x^2$ 为偶函数且不是奇函数，求 $m$ 的值。',
    '已知 $f(x)=m*x^2$ 在 $[-1,1]$ 上为偶函数，求 $m$ 的值。',
    '已知 $f(x)=m*x^2$ 的定义域为 $\\mathbb{R}$，且为偶函数，求 $m$ 的值。',
    '已知二次函数 $f(x)=m*x^2$ 为偶函数，求 $m$ 的值。',
    '已知 $f(x)=m*x^2$ 为偶函数，且 $m>0$，求 $m$ 的值。',
])
def test_missing_or_changed_source_condition_cannot_admit_a_route(text):
    value = candidate('m*x^2')
    value['original_text'] = text
    rows = extract_features(value)['features']
    feature = next(r for r in rows if r['feature_id'] == 'parity_parameter')
    assert not feature['value']['structure_supported']
    assert not any(r['status'] == 'supported' for r in evaluate_types(rows))
    assert evaluate_goal(value, TARGET, rows, 'type-parity-parameter')['status'] == 'no_applicable_method'


def test_known_parity_keeps_the_value_goal_and_changes_canonical_evidence():
    even = candidate('m*x')
    odd = candidate('m*x', 'odd')
    for value in [even, odd]:
        original = deepcopy(value)
        report = extract_features(value)
        assert report['ok']
        assert [r['type_id'] for r in evaluate_types(report['features']) if r['status'] == 'supported'] == ['type-parity-parameter']
        assert value == original
    a, b = (build_context(v, TARGET) for v in (even, odd))
    assert a['goal'] == b['goal'] == {'kind': 'find_value', 'expression': 'm'}
    assert a['entries'] != b['entries']


@pytest.mark.parametrize('extra', ['m>0', 'm=2'])
def test_invented_parameter_restriction_cannot_change_the_answer(extra):
    value = candidate('m*x^2')
    value['root']['facts'].append(extra)
    rows = extract_features(value)['features']
    assert not next(r for r in rows if r['feature_id'] == 'parity_parameter')['value']['structure_supported']
    assert evaluate_goal(value, TARGET, rows, 'type-parity-parameter')['status'] == 'no_applicable_method'


def test_unresolved_source_never_publishes_a_parameter_conclusion():
    value = candidate()
    value['root']['uncertainties'] = [{'kind': 'unreadable', 'text': '原图奇偶性不清楚'}]
    desc = build_context(value, TARGET)['parity_parameter_goal']
    assert not desc['structure_supported'] and desc['reason'] == 'parity_param.unresolved_source'
    rows = extract_features(value)['features']
    assert evaluate_goal(value, TARGET, rows, 'type-parity-parameter')['status'] == 'no_applicable_method'


def test_parameter_subtask_does_not_replace_parent_evaluation():
    value = candidate()
    value['root']['goals'][0]['expression'] = 'f(m)'
    assert 'parity_parameter_goal' not in build_context(value, TARGET)
    report = extract_features(value)
    assert report['ok']
    assert not any(r['type_id'] == 'type-parity-parameter' and r['status'] == 'supported'
                   for r in evaluate_types(report['features']))


def test_same_function_and_parameter_names_in_sibling_questions_are_isolated():
    first, second = candidate('m*x', 'odd'), candidate('m*x^2', 'both')
    value = {'original_text': '(1) ' + first['original_text'] + '\n(2) ' + second['original_text'],
             'root': {'children': [{'label': str(i), **v['root']} for i, v in enumerate([first, second], 1)]}}
    for index, prop in enumerate(['odd', 'both']):
        target = f'/root/children/{index}/goals/0'
        desc = build_context(value, target)['parity_parameter_goal']
        assert desc['structure_supported'], desc['reason']
        assert [fact['property'] for fact in desc['parity_facts']] == [prop]
        assert all(ref.startswith(f'/root/children/{index}/') for ref in desc['source_refs'])


def test_displayed_piecewise_rows_bind_the_original_zero_value():
    value = candidate('piecewise(x^2+m,x>0,m,x=0,-x^2-m,x<0)', 'odd')
    value['original_text'] = (r'已知 $f(x)=\begin{cases}x^2+m,&x>0\\m,&x=0\\-x^2-m,&x<0\end{cases}$'
                              r' 为奇函数，求 $m$ 的值。')
    assert build_context(value, TARGET)['parity_parameter_goal']['structure_supported']
    value['root']['definitions'][0] = 'f(x)=piecewise(x^2+m,x>0,0,x=0,-x^2-m,x<0)'
    assert not build_context(value, TARGET)['parity_parameter_goal']['structure_supported']
