"""Parity admission, source evidence and neighbouring types; no model calls."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from tests.solver.test_graph_stage_two_input_values import accepted

TARGET = '/root/goals/0'
TYPE = 'type-function-parity'
ROOT = Path(__file__).resolve().parents[3]


def candidate(expression='x^2', *, variable='x', function='f', **changes):
    domain = '，定义域为 $' + changes['input_domain'] + '$' if 'input_domain' in changes else ''
    return {'original_text': f'判断函数 ${function}({variable})={expression}$ 的奇偶性{domain}。',
            'root': {'goals': [{'kind': 'determine_function_parity', 'function': function,
                                'variable': variable, 'expression': expression, **changes}]}}


def features(value):
    result = extract_features(value)
    assert result['ok'], result
    return result['features']


def recognize(value, tmp_path):
    fixture = Path(__file__)
    prepared = prepare_authored(value, run_id='parity-recognition', reviewer='unit-test', sources=[{
        'reference': str(fixture.relative_to(ROOT)), 'sha256': sha256(fixture.read_bytes()).hexdigest(),
        'location': 'synthetic type-recognition boundaries',
    }])

    def unexpected_provider():
        pytest.fail('a single supported type or unsupported input must not call a model')

    result = run_result(prepared, tmp_path / 'stage-two', admission='authored_topic',
                        provider=unexpected_provider, unsupported_root=tmp_path / 'unsupported')
    assert result['status'] == 'completed', result['input_diagnostics']
    assert result['llm']['new_network_attempts'] == 0
    return prepared, result


@pytest.mark.parametrize('expression,changes', [
    ('x/(x^2+1)', {}),
    ('x^2+x', {}),
    ('0', {}),
    ('abs(x+1)-abs(x-1)', {}),
    ('sqrt(2-x^2)', {}),
    ('piecewise(-x,x<0,x,x>=0)', {}),
    ('x', {'input_domain': '{-1,0,1}'}),
    ('x^2', {'input_domain': '[-2,-1]∪[1,2]'}),
    ('x^2', {'input_domain': '[-2,1]'}),
    ('x^2/x', {'input_domain': '[-1,1]', 'domain_role': 'restriction'}),
    ('t/(t^2+3)', {'variable': 't', 'function': 'h'}),
])
def test_supported_variants_reach_the_parity_method_with_bound_source(expression, changes, tmp_path):
    value = candidate(expression, **changes)
    original = deepcopy(value)
    prepared, result = recognize(value, tmp_path)
    goal, = result['goals']
    assert goal['status'] == 'resolved'
    assert goal['primary'] == TYPE and goal['supported'] == [TYPE]
    assert goal['primary_source'] == 'program'
    assert not goal['d1']['diagnostics'] and goal['d1']['fragments']
    refs = {ref for fragment in goal['d1']['fragments'] for ref in fragment['source_refs']}
    assert TARGET + '/expression' in refs
    if 'input_domain' in changes:
        assert TARGET + '/input_domain' in refs
    selected = evaluate_goal(value, TARGET, prepared['features'], goal['primary'])
    branch, = selected['selection']['branches']
    assert branch['applicability'] == 'applicable'
    assert branch['target'] == 'method-parity-definition' and branch['route_id'] == 'parity-definition'
    assert selected['d4']['options'][0]['method'] == 'method-parity-definition'
    assert value == original


@pytest.mark.parametrize('expression', [
    'sqrt(x^3-2)', 'abs(abs(x)-1)', 'piecewise(x,x<=0,x,x>=0)',
])
def test_unsupported_structures_offer_no_parity_route(expression, tmp_path):
    value = candidate(expression)
    prepared, result = recognize(value, tmp_path)
    goal, = result['goals']
    assert goal['status'] == 'unsupported' and goal['primary'] is None
    assert TYPE not in goal['supported']
    # A forced type choice cannot bypass admission by reusing feature rows.
    selected = evaluate_goal(value, TARGET, prepared['features'], TYPE)
    assert selected['status'] == 'no_applicable_method'
    assert selected['selection']['branches'] == [] and selected['d4'] is None


def test_unavailable_notation_is_rejected_before_type_recognition():
    value = accepted()
    value['candidate'] = candidate('sin(x)')
    assert not extract_features(value['candidate'])['ok']
    assert not validate_input(value)['ok']


@pytest.mark.parametrize('extracted_domain,reason', [
    (None, 'function_parity.source_domain_missing'),
    ('[-2,2]', 'function_parity.source_domain_mismatch'),
])
def test_lost_or_changed_source_domain_blocks_recognition_and_method(extracted_domain, reason, tmp_path):
    value = candidate(**({'input_domain': extracted_domain} if extracted_domain else {}))
    value['original_text'] = '判断函数 $f(x)=x^2$ 在 $[-2,1]$ 上的奇偶性。'
    prepared, result = recognize(value, tmp_path)
    row = next(row for row in prepared['features'] if row['feature_id'] == 'function_parity')
    assert row['value']['reason'] == reason
    assert result['goals'][0]['primary'] is None
    assert evaluate_goal(value, TARGET, prepared['features'], TYPE)['status'] == 'no_applicable_method'


@pytest.mark.parametrize('status', ['unknown', 'conditional'])
def test_unconfirmed_parity_feature_does_not_count_as_type_evidence(status):
    rows = features(candidate())
    next(row for row in rows if row['feature_id'] == 'function_parity')['status'] = status
    report = next(report for report in evaluate_types(rows) if report['type_id'] == TYPE)
    assert report['status'] == 'unknown'


@pytest.mark.parametrize('expression,goal,expected_type', [
    ('x^2', {'kind': 'find_domain', 'object': 'f'}, 'type-function-domain'),
    ('x^2', {'kind': 'find_value', 'expression': 'f(2)'}, 'type-function-evaluation'),
    ('abs(x)', {'kind': 'draw_function_graph', 'expression': 'abs(x)', 'variable': 'x'}, 'type-function-graph'),
])
def test_same_formula_with_another_request_is_not_mistaken_for_parity(expression, goal, expected_type):
    assert TYPE in [r['type_id'] for r in evaluate_types(features(candidate(expression)))
                    if r['status'] == 'supported']
    value = {'original_text': f'已知 $f(x)={expression}$。',
             'root': {'definitions': [f'f(x)={expression}'], 'goals': [goal]}}
    reports = evaluate_types(features(value))
    assert [report['type_id'] for report in reports if report['status'] == 'supported'] == [expected_type]
    assert next(report for report in reports if report['type_id'] == TYPE)['status'] == 'conflict'


def test_parity_goal_requires_its_feature_and_validates_its_source_pointer():
    value = accepted()
    value['candidate'] = candidate('x^2', input_domain='[-1,1]')
    value['features'] = features(value['candidate'])
    assert validate_input(value)['ok']
    broken = deepcopy(value)
    broken['features'] = [row for row in broken['features'] if row['feature_id'] != 'function_parity']
    assert any(d['code'] == 'input.features_incomplete' and 'function_parity' in d['message']
               for d in validate_input(broken)['diagnostics'])
    row = next(row for row in value['features'] if row['feature_id'] == 'function_parity')
    row['source_refs'] = [TARGET + '/missing_domain']
    assert not validate_input(value)['ok']


@pytest.mark.parametrize('field,definition', [
    ('definitions', 'f(x)=x^2'), ('facts', 'f(t)=t^2'),
])
def test_repeated_original_definition_is_not_an_additional_condition(field, definition, tmp_path):
    value = candidate('x^2')
    value['root'][field] = [definition]
    prepared, result = recognize(value, tmp_path)
    assert result['goals'][0]['primary'] == TYPE
    selected = evaluate_goal(value, TARGET, prepared['features'], TYPE)
    assert selected['d4']['options'][0]['method'] == 'method-parity-definition'


@pytest.mark.parametrize('source', ['f(x)=x', 'g(x)=x^2', 'f(x)=x^3/x', 'x>0', 'f(1)=1'])
def test_conflicting_or_extra_facts_still_block_parity(source, tmp_path):
    value = candidate('x^2')
    value['root']['definitions'] = ['f(x)=x^2']
    value['root']['facts'] = [source]
    prepared, result = recognize(value, tmp_path)
    row = next(row for row in prepared['features'] if row['feature_id'] == 'function_parity')
    assert row['value']['reason'] == 'function_parity.additional_conditions_unsupported'
    assert result['goals'][0]['primary'] is None
    assert evaluate_goal(value, TARGET, prepared['features'], TYPE)['status'] == 'no_applicable_method'
