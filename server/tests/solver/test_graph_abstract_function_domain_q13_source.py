"""Q13 source roles keep domain and range conditions and goals distinct."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.search.extraction import SearchStageOneContract
from tests.solver.test_graph_abstract_function_domain_source import present
from tests.solver.test_graph_function_equality_ir import identity

FIXTURE = Path(__file__).parent / 'fixtures/abstract-function-domain/q13-candidate.json'


def candidate():
    value = json.loads(FIXTURE.read_text())
    value.pop('public_content')  # The search pipeline separates public content before stage two.
    return value


def test_search_contract_retains_both_targets_and_known_range_in_public_identity():
    public = json.loads(FIXTURE.read_text())
    checked = SearchStageOneContract().parse(
        json.dumps(public), problem_id='q13', source_hash='fixture', registry=[], store=None,
    )
    assert checked['contract_valid'], checked
    first = identity(public)
    changed = deepcopy(public)
    for goal in changed['root']['goals']:
        goal['known_range'] = '[0,1]'
    changed['original_text'] = changed['original_text'].replace('[0,1/2]', '[0,1]')
    changed['public_content']['scopes'][0]['statement'] = changed['original_text']
    assert identity(changed) != first
    missing_target = deepcopy(public)
    missing_target['public_content']['scopes'][0]['choices'].pop()
    checked = SearchStageOneContract().parse(
        json.dumps(missing_target), problem_id='q13', source_hash='fixture', registry=[], store=None,
    )
    assert not checked['contract_valid']


@pytest.mark.parametrize('reverse_targets', [False, True])
def test_q13_keeps_both_goal_sources_and_distinct_reading_tasks(tmp_path, reverse_targets):
    value = candidate()
    if reverse_targets:
        value['root']['goals'].reverse()
    before = deepcopy(value)
    lesson = present(tmp_path, value)
    domain_index = int(reverse_targets)
    domain = lesson['goals'][domain_index]
    pending = lesson['goals'][1 - domain_index]
    assert domain['target_ref'] == f'/root/goals/{domain_index}'
    assert domain['status'] == 'resolved'
    assert domain['walk'] is not None
    assert pending['status'] == 'resolved'
    assert pending['walk'] is not None
    assert pending['d1']['rows'][0]['quote'][0]['text'] == '值域'
    assert '完整覆盖' in pending['d1']['summary']
    given_range = next(row for row in domain['d1']['givens'] if row['kind'] == 'given_range')
    assert given_range['source_refs'] == [domain['target_ref'] + '/known_call', domain['target_ref'] + '/known_range']
    assert '值域' in given_range['text'] and '\\frac{1}{2}' in given_range['text']
    assert given_range['text'] in domain['walk']['bundle']['intro'][0]['question']
    assert '不用它限制自变量' in domain['d1']['summary']
    assert value == before
    assert 'children' not in value['root']
    for row in [*domain['d1']['rows'], *domain['d1']['givens']]:
        for quote in row['quote']:
            assert value['original_text'][quote['start']:quote['end']] == quote['text']


@pytest.mark.parametrize('text', [
    '已知函数 $f(x)$ 的定义域为 $[1,2]$，$f(x)$ 的值域为 $[0,1/2]$，求 $f(x+1)$ 的定义域和值域。',
    '已知函数 $f(x)$ 的值域为 $[0,1/2]$，定义域为 $[1,2]$，求 $f(x+1)$ 的值域和定义域。',
])
def test_q13_given_and_requested_roles_can_be_reordered_without_becoming_each_other(tmp_path, text):
    value = candidate()
    value['original_text'] = text
    domain, pending = present(tmp_path, value)['goals']
    assert domain['walk'] is not None
    assert pending['walk'] is not None
    assert pending['d1']['rows'][0]['quote'][0]['text'] == '值域'
    assert domain['d1']['rows'][0]['quote'][0]['text'] == '定义域'


@pytest.mark.parametrize('text', [
    '已知函数 $f(x)$ 的定义域为 $[1,2]$，值域为 $[0,1]$，求 $f(x+1)$ 的定义域和值域。',
    '已知函数 $f(x)$ 的定义域为 $[1,2]$，$g(x)$ 的值域为 $[0,1/2]$，求 $f(x+1)$ 的定义域和值域。',
    '已知函数 $f(x)$ 的定义域为 $[1,2]$，求 $f(x+1)$ 的定义域和值域。',
    '已知函数 $f(x)$ 的值域为 $[1,2]$，定义域为 $[0,1/2]$，求 $f(x+1)$ 的定义域和值域。',
])
def test_unbound_or_swapped_known_range_never_gets_a_confirmed_domain_lesson(tmp_path, text):
    value = candidate()
    value['original_text'] = text
    domain, pending = present(tmp_path, value)['goals']
    assert domain['d1']['rows'] == []
    assert domain['walk'] is None
    assert pending['walk'] is None
    assert domain['d1']['diagnostics'][0]['code'] == 'd1.abstract_domain_source_not_uniquely_located'


def test_photo_wording_omits_given_range_verb_and_has_two_answer_blanks(tmp_path):
    value = candidate()
    value['original_text'] = (
        r'13. 若 $y=f(x)$ 的定义域为 $[1,2]$，值域 $[0,\frac{1}{2}]$，'
        r'则 $y=f(x+1)$ 的定义域为____，值域为____。')
    goals = present(tmp_path, value)['goals']
    assert all(goal['walk'] is not None for goal in goals)
    assert [goal['d1']['rows'][0]['quote'][0]['text'] for goal in goals] == ['定义域', '值域']
