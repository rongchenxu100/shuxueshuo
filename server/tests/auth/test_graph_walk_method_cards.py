from copy import deepcopy

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


@pytest.mark.parametrize('answer', [None, [], {'checks': [], 'method': 'fraction'},
                                    {'checks': ['invalid'], 'method': 'fraction'},
                                    {'checks': ['constant'], 'method': 'invalid'}])
def test_method_cards_reject_malformed_answers(answer):
    with pytest.raises(HTTPException):
        grade(decision(), {'value': answer}, 'm5')
