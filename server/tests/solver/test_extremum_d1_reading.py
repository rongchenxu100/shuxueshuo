"""T2 function_extremum goals get a student reading card before type selection."""
import json
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
from shuxueshuo_server.search.lesson import d1_rows
from shuxueshuo_server.search.walk import walk

ROOT = Path(__file__).resolve().parents[3]
RECORDS = ROOT / 'internal/senior-high/authored-courses/function-monotonicity-t2-20261104'
TARGET = '/root/goals/0'


def _case(name):
    record = json.loads((RECORDS / f'{name}.json').read_text())
    candidate = record['candidate']
    features = extract_features(candidate)['features']
    located = build_d1(candidate, TARGET, features, {'items': [], 'links': []})
    known = {row['feature_id']: row['value'] for row in features if row.get('status') == 'known'}
    reading = d1_rows(TARGET, located['fragments'], known, candidate['original_text'],
                      candidate=candidate)
    return record, candidate, features, reading


@pytest.mark.parametrize(
    ('name', 'task', 'needle'),
    [
        ('a16', 'direct', '最大值'),
        ('a14', 'direct', '最小值'),
        ('a07', 'quantified', '参数'),
        ('b08', 'specified', '指定点'),
        ('b14', 'specified', '指定点'),
    ],
)
def test_extremum_d1_reading_matches_task(name, task, needle):
    _, _, features, reading = _case(name)
    desc = next(row['value'] for row in features if row['feature_id'] == 'function_extremum')
    assert desc['task'] == task
    assert len(reading['rows']) == 1
    assert reading['interaction'] == 'choice'
    assert needle in reading['summary']
    correct = [option['text'] for option in reading['rows'][0]['options'] if option['correct']]
    assert len(correct) == 1 and needle in correct[0]


def test_extremum_walk_includes_d1_before_d2():
    record, candidate, features, reading = _case('a16')
    goal = {
        'status': 'resolved',
        'target_ref': TARGET,
        'primary': 'type-monotonicity-extremum',
        'd1': reading,
        'd2': [{
            'type_id': 'type-monotonicity-extremum',
            'label': '利用单调性求最值',
            'role': 'primary',
            'feedback': '',
            'reasons': ['借助单调性求最值'],
        }],
        'knowledge': [{'ref': 'function-range-extrema'}],
    }
    package = walk(goal, candidate['original_text'], record['problem_id'])
    assert package is not None
    assert [step['id'] for step in package['bundle']['intro']][:2] == ['D1', 'D2']
    assert package['bundle']['intro'][0]['title'] == '读题'
