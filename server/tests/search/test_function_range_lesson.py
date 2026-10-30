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
