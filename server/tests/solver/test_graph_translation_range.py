"""Integer translates preserve source ownership, exact coverage and image gaps."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.range_presentation import compile_range
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.graph_lesson.stage_three.translation_range import (
    admitted,
    image_endpoints,
    independent_verify,
    solve,
    translate_range,
)
from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
from shuxueshuo_server.graph_lesson.stage_two.translation_surface import (
    translation_source_spans,
)

TARGET = '/root/goals/0'


def candidate(**overrides):
    goal = {'kind': 'find_translation_range', 'function_relation': 'f(x)=x+g(x)',
            'periodic_function': 'g', 'period': '1', 'periodic_domain': 'ℝ',
            'known_domain': '[3,4]', 'known_range': '[-2,5]', 'input_domain': '[-10,10]'}
    goal.update(overrides)
    text = (f'设 $g(x)$ 是定义在 ${goal["periodic_domain"]}$ 上、以 ${goal["period"]}$ 为周期的函数，'
            f'若 ${goal["function_relation"]}$ 在 ${goal["known_domain"]}$ 上的值域为 ${goal["known_range"]}$，'
            f'则 $f(x)$ 在区间 ${goal["input_domain"]}$ 上的值域为____。')
    return {'original_text': text, 'root': {'goals': [goal]}}


@pytest.mark.parametrize('changes,expected', [
    ({}, sp.Interval(-15, 11)),
    ({'function_relation': 'f(x)=-x+g(x)'}, sp.Interval(-8, 18)),
    ({'function_relation': 'f(x)=g(x)'}, sp.Interval(-2, 5)),
    ({'period': '2', 'known_domain': '[0,2]', 'known_range': '[1,5]', 'input_domain': '[2,6]'}, sp.Interval(3, 9)),
    ({'period': '1/2', 'function_relation': 'f(x)=2*x+g(x)', 'known_domain': '[0,1/2)',
      'known_range': '[0,1/4]', 'input_domain': '[-1,0)'},
     sp.Union(sp.Interval(-2, sp.Rational(-7, 4)), sp.Interval(-1, sp.Rational(-3, 4)))),
    ({'known_domain': '(0,1]', 'known_range': '(0,1)', 'input_domain': '(0,2]'},
     sp.Union(sp.Interval.open(0, 1), sp.Interval.open(1, 2))),
    ({'known_domain': '(0,1)', 'known_range': '[0,1]', 'input_domain': '(0,1)∪(2,3)'},
     sp.Union(sp.Interval(0, 1), sp.Interval(2, 3))),
    ({'function_relation': 'f(x)=0*x+g(x)', 'known_domain': '[0,1)',
      'known_range': '{3}', 'input_domain': '[0,4)'}, sp.FiniteSet(3)),
    ({'input_domain': '[3,4]'}, sp.Interval(-2, 5)),
])
def test_translation_images(changes, expected):
    value = candidate(**changes)
    context = build_context(value, TARGET)
    assert admitted(context)
    computed = solve(context['translation_range_goal'])
    assert computed['feasible_set'] == expected
    assert independent_verify(value, TARGET, expected)['status'] == 'verified'
    assert image_endpoints(value, TARGET, expected)['status'] == 'passed'
    assert independent_verify(value, TARGET, expected | sp.FiniteSet(99))['status'] == 'math_failed'
    selected = evaluate_goal(value, TARGET, [], 'type-function-range')
    assert selected['selection']['branches'][0]['target'] == 'method-translation-range'
    assert selected['d3']['prerequisites'][0]['id'] == 'D3-domain'
    data = translate_range(context)['outputs']
    titles = {
        'translation_relation': '写出平移后的函数值',
        'translation_coverage': '用平移盖住输入范围',
        'translation_union': '把各段值域合起来',
    }
    for phase, title in titles.items():
        part = compile_range([{'values': encode_value({**data, 'phase': phase})}], 'translate')['parts'][0]
        assert part['title'] == title
        assert part['stem_board']['items'][1]['math'] is None
        assert part['interaction']['type'] == 'choice'
        board = json.dumps(part['stem_board'], ensure_ascii=False)
        assert 'I_0' not in board and 'D=' not in board
        if phase == 'translation_relation':
            assert 'f(' in part['question'] and '挪到' in part['question']
        if phase == 'translation_coverage':
            assert '例如' in part['question'] and '盖住' in part['question']
            assert '向左平移' in part['question'] and '向右平移' in part['question']
            assert 'k=-1' in part['question'].replace(' ', '') or 'k=-1' in part['question']
            assert part['graph']['kind'] == 'number_line'
            assert '要求的输入范围' in part['graph']['params']['title']
            assert '已知区间' in board and 'k=-1' in board.replace(' ', '')
        if phase == 'translation_union':
            assert '合起来' in part['question']
            assert part['graph']['kind'] == 'number_line'
            assert part['graph']['params']['variable'] == 'y'
            assert '已知区间上的值域' in part['graph']['params']['title']


@pytest.mark.parametrize('changes', [
    {'input_domain': '[-10,19/2]'}, {'input_domain': '(-10,10)'},
    {'known_domain': '(0,1)', 'input_domain': '(0,2)'},
    {'known_domain': '[0,2]'}, {'known_domain': '[3,3]'},
    {'known_range': '[0,1/2]'},  # Two shared endpoints must differ by 1.
    {'input_domain': '[0,65]'}, {'input_domain': 'ℝ'},
    {'periodic_domain': '[0,1]'}, {'period': '0'}, {'period': '-1'},
    {'function_relation': 'f(x)=x^2+g(x)'},
    {'function_relation': 'f(x)=x+g(2*x)'},
    {'function_relation': 'f(x)=x+g(x)+1/x-1/x'},
])
def test_partial_or_unsupported_sources_fail_closed(changes):
    assert not admitted(build_context(candidate(**changes), TARGET))


def test_extra_condition_cannot_be_discarded():
    value = candidate()
    value['root']['facts'] = ['a>0']
    assert not admitted(build_context(value, TARGET))


def test_source_binding_cannot_borrow_period_or_image_from_other_function():
    value = candidate()
    desc = build_context(value, TARGET)['translation_range_goal']
    locate = lambda c: translation_source_spans(c, TARGET, [(0, len(c['original_text']))], desc, _abstract_formula_matches)
    spans = locate(value)
    assert spans and len(spans) == 8
    for old, new in [('$g(x)$', '$h(x)$'), ('$1$ 为周期', '$2$ 为周期'),
                     ('$[-2,5]$', '$[-2,6]$'), ('则 $f(x)$', '则 $h(x)$'),
                     ('在 $[3,4]$', '，$h(x)$ 在 $[3,4]$'),
                     ('以 $1$', '$h(x)$ 以 $1$')]:
        changed = deepcopy(value)
        changed['original_text'] = changed['original_text'].replace(old, new)
        assert locate(changed) is None
    plain = deepcopy(value)
    plain['original_text'] = plain['original_text'].replace('$1$ 为周期', '1 为周期')
    assert locate(plain)


def test_notation_and_structural_feature_preserve_source_not_answer():
    value = candidate()
    assert validate_candidate(value)['contract_valid']
    feature = next(f for f in extract_features(value)['features'] if f['feature_id'] == 'translation_range')
    assert feature['value']['structure_supported']
    assert 'feasible_set' not in feature['value']
    wrong = deepcopy(value)
    wrong['root']['goals'][0]['periodic_function'] = 'f'
    assert not validate_candidate(wrong)['contract_valid']


@pytest.mark.stage_three_db
def test_complete_translation_lesson(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import (
        constructed_upstream,
        store,
    )
    from tools.export_graph_walk_course import export_course

    value = json.loads((Path(__file__).parent/'fixtures/function-range/q18-candidate.json').read_text())
    # Stage two consumes the mathematical candidate; public display content
    # travels separately in the normal photo pipeline.
    value.pop('public_content', None)
    upstream = constructed_upstream(tmp_path, value)
    output = tmp_path/'run'
    completed = runner.run_sample(upstream, output)
    goal = completed['goals'][0]
    assert goal['status'] == 'solved', goal
    assert goal['answer']['set']['expression'] == 'Interval(-15, 11)'
    snapshot = store(output).snapshot()
    assert len(snapshot['math_steps']) == 3
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    course = export_course(output, 'translation-range-regression')
    assert course['lesson']['goals'][0]['walk'] is not None
    assert not course['lesson']['goals'][0]['d1'].get('diagnostics')
