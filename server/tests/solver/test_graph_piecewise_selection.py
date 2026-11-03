"""Piecewise goals present one admitted method without a selection exercise."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_three import selection
from shuxueshuo_server.learning.graph_walk import grade

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


def authored(name):
    path = next((ROOT/'internal/senior-high/authored-courses').glob(f'piecewise*/{name}.json'))
    return json.loads(path.read_text())['candidate']


def choose(candidate, primary):
    return selection.evaluate_goal(candidate, TARGET, [], primary)


@pytest.mark.parametrize(('name', 'primary', 'method'), [
    ('b10', 'type-function-evaluation', 'method-function-evaluation'),
    ('b10-v1', 'type-piecewise-function', 'method-piecewise-equation'),
    ('b10-v2', 'type-piecewise-function', 'method-piecewise-inequality'),
])
def test_current_target_presents_one_method_without_judgment(name, primary, method):
    result = choose(authored(name), primary)
    assert result['selection']['kind'] == 'direct_method'
    assert result['selection']['rule'] is None
    assert result['d3']['query']['from'] == primary  # Evaluation keeps its existing type.
    assert [row['target'] for row in result['selection']['branches']] == [method]
    d3 = result['d3']
    schema = json.loads((ROOT/'internal/schemas/graph-stage-three-result-v1.schema.json').read_text())
    Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/D3'}).validate(d3)
    assert d3['title'] == '解题方法'
    assert d3['submit_label'] == '开始解题'
    assert d3['interaction'] == {'type': 'read'}
    assert d3['expected_answer'] == d3['verdicts'] == {}
    assert len(result['d4']['options']) == 1
    # Feed the authoritative grader the same route bindings the exporter adds.
    route = result['d4']['options'][0]['route_id']
    d3['route_by_answer'] = {'read': route}
    assert grade(d3, {'value': 'read'}, route) == 'passed'
    assert grade(d3, {'value': 'read'}, 'different-route') == 'wrong'
    assert grade(d3, {'value': {'checks': ['inequality'], 'method': 'inequality'}}, route) == 'wrong'


def test_rule_is_not_shown_for_non_piecewise_or_unused_piecewise_function():
    c = {'root': {'definitions': ['g(x)=x^2+1'],
                  'goals': [{'kind': 'find_value', 'expression': 'g(2)'}]}}
    for extra in ([], ['f(x)=piecewise(x,x<=0,x^2,x>0)']):
        value = deepcopy(c); value['root']['definitions'] += extra
        result = choose(value, 'type-function-evaluation')
        assert result['selection']['rule'] is None
        assert result['d3']['interaction']['type'] == 'read'
    relation = json.loads((ROOT/'internal/senior-high/authored-courses/function-formula-a3-20261101/b05-v3.json').read_text())['candidate']
    assert choose(relation, 'type-function-evaluation')['d3']['interaction']['type'] == 'read'


@pytest.mark.parametrize('name', ['b10', 'b10-v1', 'b10-v2'])
def test_wrong_type_or_uncertain_conditions_do_not_grant_a_route(name):
    c = authored(name)
    primary = 'type-function-evaluation' if name == 'b10' else 'type-piecewise-function'
    other = 'type-piecewise-function' if name == 'b10' else 'type-function-evaluation'
    assert choose(c, other)['d3'] is None
    c['root']['uncertainties'] = [{'kind': 'ambiguous_symbol', 'text': '分界点开闭不清'}]
    assert choose(c, primary)['d3'] is None


def test_selection_uses_structure_and_current_target_not_problem_identity():
    c = authored('b10-v2')
    c['root']['definitions'] = ['h(t)=piecewise(t^2,t>=0,t+2,t<0)']
    c['root']['facts'] = ['h(2)<=h(x)']
    result = choose(c, 'type-piecewise-function')
    assert result['d3']['interaction']['type'] == 'read'
    assert result['selection']['branches'][0]['target'] == 'method-piecewise-inequality'
    assert '逐段解不等式' in result['d3']['question']
