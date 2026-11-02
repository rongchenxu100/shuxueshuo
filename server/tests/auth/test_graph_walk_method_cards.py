import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import HTTPException

from shuxueshuo_server.learning.graph_walk import grade


def decision():
    return {'interaction': {'type': 'method_cards',
                            'checks': [{'id': 'remainder', 'options': [{'value': 'constant'}, {'value': 'variable'}]}],
                            'methods': [{'value': 'fraction', 'route': 'm5'}, {'value': 'equation', 'route': 'm4'}]},
            'expected_answer': {'checks': {'remainder': 'constant'}}}


def test_method_cards_grade_premises_and_route_without_trusting_confirmation():
    d = decision()
    for method, route in [('fraction', 'm5'), ('equation', 'm4')]:
        answer = {'checks': ['constant'], 'method': method}
        assert grade(d, {'value': answer}, route) == 'passed'
        assert grade(d, {'value': answer}, 'wrong-route') == 'wrong'
        assert grade(d, {'value': {**answer, 'checks': ['variable'], 'confirmed': 1}}, route) == 'wrong'
    d = deepcopy(d);d['interaction']['methods'][0].pop('route');d['alternatives'] = {'fraction': {'message': '未展开'}}
    assert grade(d, {'value': {'checks': ['constant'], 'method': 'fraction'}}, 'm4') == 'uncovered'
    assert grade(d, {'value': {'checks': ['variable'], 'method': 'fraction'}}, 'm4') == 'wrong'


def test_method_cards_without_extra_checks_still_gate_unavailable_methods():
    d = decision()
    d['interaction']['checks'] = []
    d['expected_answer']['checks'] = {}
    assert grade(d, {'value': {'checks': [], 'method': 'fraction'}}, 'm5') == 'passed'
    assert grade(d, {'value': {'checks': [], 'method': 'equation'}}, 'm4') == 'passed'
    d['interaction']['methods'][1].pop('route')
    d['alternatives'] = {'equation': {'message': '本题需要域内实根筛选'}}
    assert grade(d, {'value': {'checks': [], 'method': 'equation'}}, 'm5') == 'uncovered'


def test_sequential_course_grades_second_goal_against_its_own_method_route():
    root = Path(__file__).resolve().parents[3]
    bundle = json.loads((root/'site/data/graph-walk/function-representations-b05-v3.json').read_text())
    route = 'function-evaluation'
    d = next(step for step in bundle['routes'][route]['steps'] if step['id'] == 'goal-2-D3')
    assert d['route_id'] == 'function-matching'
    good = {'checks': ['composite_input'], 'method': 'matching'}
    assert grade(d, {'value': good}, route) == 'passed'
    assert grade(d, {'value': {**good, 'checks': ['function_type']}}, route) == 'wrong'
    assert grade(d, {'value': {**good, 'method': 'coefficients'}}, route) == 'wrong'


@pytest.mark.parametrize('answer', [None, [], {'checks': [], 'method': 'fraction'},
                                    {'checks': ['invalid'], 'method': 'fraction'},
                                    {'checks': ['constant'], 'method': 'invalid'}])
def test_method_cards_reject_malformed_answers(answer):
    with pytest.raises(HTTPException):
        grade(decision(), {'value': answer}, 'm5')


def test_formula_connections_grade_evidence_and_method_and_keep_matching_uncovered():
    root = Path(__file__).resolve().parents[3]
    bundle = json.loads((root/'site/data/graph-walk/function-representations-b05-v2-r4.json').read_text())
    d3 = next(step for step in bundle['intro'] if step['id'] == 'D3')
    route = 'function-substitution'
    good = {'checks': ['composite_input'], 'method': 'substitution'}
    assert grade(d3, {'value': good}, route) == 'passed'
    assert grade(d3, {'value': {**good, 'confirmed': 99}}, 'other-route') == 'wrong'
    for method in ('coefficients', 'system', 'assignment'):
        assert grade(d3, {'value': {**good, 'method': method}}, route) == 'wrong'
    assert grade(d3, {'value': {**good, 'method': 'matching'}}, route) == 'uncovered'
    assert grade(d3, {'value': {**good, 'checks': ['function_type'], 'confirmed': 1}}, route) == 'wrong'
