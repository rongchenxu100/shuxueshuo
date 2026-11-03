"""A source-binding failure must not become a range lesson without its reading step."""

import json

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_function_range import candidate
from tests.solver.test_graph_stage_three_execution import constructed_upstream


@pytest.mark.parametrize('mismatch', [None, 'interval', 'formula'])
def test_range_source_diagnostics_gate_the_photo_lesson(tmp_path, mismatch):
    value = candidate()
    if mismatch == 'interval':
        value['original_text'] = value['original_text'].replace('[0,3]', '[0,2]')
    elif mismatch == 'formula':
        value['original_text'] = value['original_text'].replace('x^2-2*x+2', 'x^2-2*x+3')
    stage_two = json.loads(constructed_upstream(tmp_path, value).read_text())
    lesson = present_lesson(stage_two, extract_features(value)['features'],
                            value['original_text'], candidate=value)
    (goal,) = lesson['goals']
    assert goal['status'] == 'resolved'
    if mismatch:
        assert goal['d1']['diagnostics'] == stage_two['goals'][0]['d1']['diagnostics']
        assert {item['code'] for item in goal['d1']['diagnostics']} == {'d1.function_range_source_not_located'}
        assert goal['walk'] is None
    else:
        assert not goal['d1'].get('diagnostics')
        assert goal['d1']['rows']
        assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'


@pytest.mark.parametrize('name', ['f', 'h'])
@pytest.mark.parametrize('mismatch', [None, 'formula', 'function'])
def test_printed_y_alias_keeps_range_source_binding(tmp_path, name, mismatch):
    value = {'original_text': r'函数 $y=\sqrt{-x^2-6x-5}$ 的值域为 ____。',
             'root': {'definitions': [f'{name}(x)=sqrt(-x^2-6*x-5)'],
                      'goals': [{'kind': 'find_range', 'object': name}]}}
    if mismatch == 'formula':
        value['original_text'] = value['original_text'].replace('-6x', '-5x')
    elif mismatch == 'function':
        value['original_text'] = value['original_text'].replace('y=', 'g(x)=')
    result = json.loads(constructed_upstream(tmp_path, value).read_text())
    lesson = present_lesson(result, extract_features(value)['features'],
                            value['original_text'], candidate=value)
    goal = lesson['goals'][0]
    assert bool(goal['d1'].get('diagnostics')) is bool(mismatch)
    assert (goal['walk'] is None) is bool(mismatch)


@pytest.mark.parametrize('separator', ['&', ',', '，'])
def test_piecewise_range_reading_accepts_printed_row_separators(tmp_path, separator):
    formula = (r'f(x)=\begin{cases}x^2-4x+3' + separator + r'0\le x<3\\'
               r'x+3' + separator + r'-3\le x<0\end{cases}')
    value = {'original_text': f'【例 11】函数 ${formula}$ 的值域为（　　）。',
             'root': {'definitions': ['f(x)=piecewise(x^2-4*x+3,0<=x<3,x+3,-3<=x<0)'],
                      'goals': [{'kind': 'find_range', 'object': 'f'}]}}
    stage_two = json.loads(constructed_upstream(tmp_path, value).read_text())
    goal = present_lesson(stage_two, extract_features(value)['features'],
                          value['original_text'], candidate=value)['goals'][0]
    assert not goal['d1'].get('diagnostics')
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'
    # Binding must keep the original formula and its exact offsets, not rewrite it.
    fragment = stage_two['goals'][0]['d1']['fragments'][0]
    assert value['original_text'][fragment['start']:fragment['end']] == formula


@pytest.mark.parametrize('rows', [
    r'x^2-4x+3,0<x<3\\x+3,-3\le x<0',  # Changed endpoint.
    r'x^2-4x+2,0\le x<3\\x+3,-3\le x<0',  # Changed expression.
    r'x^2-4x+3,0\le x<3',  # Missing branch.
    r'x+3,-3\le x<0\\x^2-4x+3,0\le x<3',  # Reordered branches.
    r'x^2-4x+3,0\le x<3,1\\x+3,-3\le x<0',  # Extra cell.
    r'x^2-4x+3\,0\le x<3\\x+3\,-3\le x<0',  # Spacing is not punctuation.
])
def test_comma_separated_cases_still_require_every_exact_branch(rows):
    from shuxueshuo_server.graph_lesson.stage_two.evaluation_surface import _piecewise_source_matches
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches

    body = r'f(x)=\begin{cases}' + rows + r'\end{cases}'
    source = 'f(x)=piecewise(x^2-4*x+3,0<=x<3,x+3,-3<=x<0)'
    assert not _piecewise_source_matches(body, source, _abstract_formula_matches)


def test_piecewise_row_separator_leaves_function_arguments_grouped():
    from shuxueshuo_server.graph_lesson.stage_two.evaluation_surface import _piecewise_source_matches
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches

    body = r'f(x)=\begin{cases}g(x,1), x<0\\x+3, x\ge0\end{cases}'
    source = 'f(x)=piecewise(g(x,1),x<0,x+3,x>=0)'
    assert _piecewise_source_matches(body, source, _abstract_formula_matches)
