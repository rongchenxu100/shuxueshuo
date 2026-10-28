"""Keep Q13's domain and range requests distinct without executing T5."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_semantics import canonical


FIXTURE = Path(__file__).parent / 'fixtures/abstract-function-domain/q13-candidate.json'


def candidate():
    value = json.loads(FIXTURE.read_text())
    value.pop('public_content')
    return value


def compile_candidate(value):
    before = deepcopy(value)
    report = NotationValidator().validate_root(value['root'], contracts.schema()['$defs'])
    assert value == before
    return report


def test_q13_preserves_two_goals_and_range_facts_with_shared_function_identity():
    value = candidate()
    report = compile_candidate(value)
    assert report.ok, report.issues
    domain, output_range = report.semantic['goals']
    assert [domain['kind'], output_range['kind']] == ['find_abstract_domain', 'find_abstract_range']
    assert domain['known_range'] == output_range['known_range']
    assert domain['known_range'] != domain['known_domain']
    assert domain['function_ref'] == output_range['function_ref'] == ['ref', '/root:function:f', 'function']
    assert domain['target_ref'] == '/root/goals/0'
    assert output_range['target_ref'] == '/root/goals/1'
    assert domain['known_call'][2][1] != output_range['known_call'][2][1]
    assert report.semantic['facts'] == []
    assert report.semantic_normalization['root']['goals'] == report.semantic['goals']
    assert validate_candidate(value)['contract_valid']


def test_named_target_alias_is_accepted_for_both_domain_and_range_targets():
    value = candidate()
    value['root']['definitions'] = ['g(t)=f(t+1)']
    report = compile_candidate(value)
    assert report.ok, report.issues
    assert report.abstract_target_aliases['r.definitions[0]']['target_refs'] == [
        '/root/goals/0', '/root/goals/1',
    ]
    assert report.semantic['facts'] == []


@pytest.mark.parametrize(('field', 'changed'), [
    ('known_domain', '[1,3]'), ('known_range', '[0,1]'),
])
def test_conflicting_repeated_knowledge_fails_closed(field, changed):
    value = candidate()
    value['root']['goals'][1][field] = changed
    report = compile_candidate(value)
    assert not report.ok
    assert report.issues[0]['reason_code'] == 'abstract_domain.conflicting_known_fact'
    assert report.issues[0]['path'] == f'/root/goals/1/{field}'


def test_known_dummy_variable_rename_does_not_hide_conflicting_range():
    value = candidate()
    value['root']['goals'][1].update(known_call='f(t)', target_call='f(u+1)', known_range='[0,1]')
    report = compile_candidate(value)
    assert not report.ok
    assert report.issues[0]['reason_code'] == 'abstract_domain.conflicting_known_fact'


def test_equivalent_numeric_range_endpoints_do_not_conflict():
    value = candidate()
    value['root']['goals'][1].update(known_call='f(t)', target_call='f(u+1)', known_range='[0,0.5]')
    report = compile_candidate(value)
    assert report.ok, report.issues


def test_equivalent_singleton_set_and_closed_interval_do_not_conflict():
    value = candidate()
    value['root']['goals'][0]['known_range'] = '{0}'
    value['root']['goals'][1]['known_range'] = '[0,0]'
    report = compile_candidate(value)
    assert report.ok, report.issues


@pytest.mark.parametrize('known_range', ['[0,0)', '(1,1)', '[2,1]'])
def test_nonempty_known_domain_cannot_have_an_empty_complete_range(known_range):
    value = candidate()
    for goal in value['root']['goals']:
        goal['known_range'] = known_range
    report = compile_candidate(value)
    assert not report.ok
    assert report.issues[0]['reason_code'] == 'abstract_domain.empty_range_for_nonempty_domain'
    assert report.issues[0]['path'] == '/root/goals/0/known_range'


@pytest.mark.parametrize('known_range', ['{3}', '[3,3]'])
def test_singleton_complete_range_remains_valid_for_nonempty_domain(known_range):
    value = candidate()
    for goal in value['root']['goals']:
        goal['known_range'] = known_range
    report = compile_candidate(value)
    assert report.ok, report.issues
    assert report.semantic['goals'][0]['known_domain'] != report.semantic['goals'][0]['known_range']


def test_same_function_name_in_sibling_scopes_has_independent_identity():
    value = candidate()
    left, right = deepcopy(value['root']), deepcopy(value['root'])
    for goal in right['goals']:
        goal.update(known_domain='[2,3]', known_range='[1,2]')
    value['root'] = {'children': [left, right]}
    report = compile_candidate(value)
    assert report.ok, report.issues
    left, right = report.semantic['children']
    assert left['goals'][0]['function_ref'] == left['goals'][1]['function_ref']
    assert right['goals'][0]['function_ref'] == right['goals'][1]['function_ref']
    assert left['goals'][0]['function_ref'] != right['goals'][0]['function_ref']


def test_distinct_functions_in_one_scope_do_not_share_range_claims():
    value = candidate()
    value['root']['goals'][1].update(known_call='g(x)', target_call='g(x+1)', known_range='[3,4]')
    report = compile_candidate(value)
    assert report.ok, report.issues
    domain, output_range = report.semantic['goals']
    assert domain['function_ref'] != output_range['function_ref']


def test_missing_optional_range_is_not_borrowed_from_another_goal():
    value = candidate()
    del value['root']['goals'][0]['known_range']
    report = compile_candidate(value)
    assert report.ok, report.issues
    assert 'known_range' not in report.semantic['goals'][0]
    assert 'known_range' in report.semantic['goals'][1]


def test_range_goal_without_its_own_known_range_is_schema_invalid():
    value = candidate()
    del value['root']['goals'][1]['known_range']
    result = validate_candidate(value)
    assert not result['contract_valid']
    assert result['reports']['ir']['issues'][0]['code'] == 'schema.invalid'


def test_changed_known_range_changes_canonical_problem_identity():
    value = candidate()
    first = compile_candidate(value)
    for goal in value['root']['goals']:
        goal['known_range'] = '[0,1]'
    second = compile_candidate(value)
    assert first.ok and second.ok
    assert canonical(first) != canonical(second)


def test_range_goal_does_not_authorize_removing_a_real_extra_condition():
    value = candidate()
    value['root']['definitions'] = ['g(x)=f(x+1)']
    value['root']['facts'] = ['g(x)>0']
    report = compile_candidate(value)
    assert not report.ok
    assert not report.abstract_target_aliases
