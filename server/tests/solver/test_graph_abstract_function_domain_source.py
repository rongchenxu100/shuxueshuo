"""Authored T3 source/repair probes; these are not live photo acceptance."""

import json
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.search.lesson import present_lesson, run_stage_two
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.solver.test_graph_function_equality_ir import identity
from tests.solver.test_graph_function_equality_repair import CONFIRMED, Sequence

TARGET = '/root/goals/0'


def candidate(known_variable='x', variable='x', *, outer=False):
    value = {
        'original_text': (f'已知函数 $y=f({known_variable})$ 的定义域是 $[-3,2]$，'
                          + (f'另限 ${variable}∈(0,2)$，' if outer else '')
                          + f'求函数 $y=f(2{variable}-1)$ 的定义域。'),
        'root': {'goals': [{
            'kind': 'find_abstract_domain', 'known_call': f'f({known_variable})',
            'known_domain': '[-3,2]', 'strength': 'exact',
            'target_call': f'f(2*{variable}-1)',
            **({'input_domain': '(0,2)'} if outer else {}),
        }]},
    }
    return value


def present(tmp_path, value):
    extracted = extract_features(value)
    assert extracted['ok']
    result = {'status': 'reviewed_candidate', 'source_reviewed': True, 'candidate': value,
              'features': extracted['features'], 'features_ok': True}

    def forbidden():
        raise AssertionError('T3 unique recognition needs no model')

    stage_two = run_stage_two(tmp_path, result, provider=forbidden, unsupported_root=tmp_path / 'unsupported')
    return present_lesson(stage_two, extracted['features'], value['original_text'], candidate=value)


@pytest.mark.parametrize('known_variable,variable', [('x', 'x'), ('t', 'x'), ('x', 'u')])
def test_d1_reads_given_call_then_requested_outer_variable(tmp_path, known_variable, variable):
    value = candidate(known_variable, variable)
    (goal,) = present(tmp_path, value)['goals']
    assert goal['primary'] == 'type-abstract-function-domain'
    (row,) = goal['d1']['rows']
    (given,) = goal['d1']['givens']
    assert given['source_refs'] == [TARGET + '/known_call', TARGET + '/known_domain']
    assert f'f({known_variable})' in given['text']
    correct = next(option for option in row['options'] if option['correct'])
    assert f'自变量 ${variable}$' in correct['text']
    assert f'f(2{variable}-1)' in correct['text']
    assert row['source_refs'] == [TARGET + '/target_call']
    assert set(row['knowledge_refs']) == {'function-concept#elements', 'function-concept#composite-domain'}
    assert value['original_text'][row['quote'][0]['start']:row['quote'][0]['end']] == row['quote'][0]['text']
    bundle = goal['walk']['bundle']
    assert [decision['id'] for decision in bundle['intro']] == ['D1', 'D2']
    d1 = bundle['intro'][0]
    assert d1['interaction']['type'] == 'choice'
    assert d1['expected_answer'] == {'one_of': [correct['id']]}
    assert given['text'] in d1['question']
    assert d1['effects']['nodes'] == ['function-concept']
    assert goal['walk']['replay']['actions'][0]['reason'] == goal['d1']['summary']
    assert '\\frac{3}{2}' not in json.dumps(goal['d1'])


def test_outer_range_is_preserved_as_separate_given(tmp_path):
    (goal,) = present(tmp_path, candidate('t', 'x', outer=True))['goals']
    assert len(goal['d1']['givens']) == 2
    outer = next(item for item in goal['d1']['givens'] if item['source_refs'] == [TARGET + '/input_domain'])
    assert '$x\\in (0,2)$' in outer['text']
    assert outer['text'] in goal['walk']['bundle']['intro'][0]['question']
    assert goal['d1']['summary'].endswith('题设另给的外层自变量范围也要同时满足。')


@pytest.mark.parametrize('before,after', [
    ('f(x)', 'f(x+2)'), ('f(2x-1)', 'f(2x+1)'), ('[-3,2]', '(-3,2]'),
    ('[-3,2]', '[-3,2)'), ('f(2x-1)', r'\unknown{f(2x-1)}'),
    ('的定义域是', '的值域是'),
])
def test_call_sign_endpoint_and_domain_role_mismatch_never_get_d1_confirmation(tmp_path, before, after):
    value = candidate()
    value['original_text'] = value['original_text'].replace(before, after)
    (goal,) = present(tmp_path, value)['goals']
    assert goal['d1']['rows'] == []
    assert goal['d1']['diagnostics'][0]['code'] == 'd1.abstract_domain_source_not_uniquely_located'
    assert goal['walk'] is None


def test_display_tex_and_source_offsets_are_preserved(tmp_path):
    value = candidate('t', 'x')
    value['original_text'] = r'已知 $f\left(t\right)$ 的定义域为 $\left[-3,2\right]$，求 $f\left(2x-1\right)$ 的定义域。'
    (goal,) = present(tmp_path, value)['goals']
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'
    for item in [*goal['d1']['rows'], *goal['d1']['givens']]:
        for quote in item['quote']:
            assert value['original_text'][quote['start']:quote['end']] == quote['text']


def test_target_binding_does_not_borrow_sibling_expression(tmp_path):
    base = candidate()
    value = {'original_text': '已知 $f(x)$ 的定义域为 $[-3,2]$。'
             '（1）求 $f(3x-1)$ 的定义域。（2）求 $f(2x-1)$ 的定义域。',
             'root': {'children': [
                 {'label': '（1）', 'goals': deepcopy(base['root']['goals'])},
                 {'label': '（2）', 'goals': deepcopy(base['root']['goals'])},
             ]}}
    first, second = present(tmp_path, value)['goals']
    assert first['walk'] is None
    assert second['walk']['bundle']['intro'][0]['id'] == 'D1'


def test_another_given_domain_is_not_mistaken_for_the_requested_call(tmp_path):
    value = candidate()
    value['original_text'] = ('已知 $f(x)$ 的定义域为 $[-3,2]$，'
                              '$f(2x-1)$ 的定义域为 $[-1,3/2]$，求 $f(3x-1)$ 的定义域。')
    (goal,) = present(tmp_path, value)['goals']
    assert goal['walk'] is None
    assert goal['d1']['diagnostics'][0]['code'] == 'd1.abstract_domain_source_not_uniquely_located'


def public_candidate():
    value = candidate()
    value['public_content'] = {
        'completeness': 'complete', 'privacy': 'separated', 'figure': 'not_required',
        'scopes': [{'scope_ref': '/root', 'statement': value['original_text'],
                    'choices': [{'target_ref': TARGET, 'status': 'none', 'selection_mode': 'none', 'options': []}]}],
    }
    return value


@pytest.mark.parametrize('overbroad', [False, True])
def test_shared_rules_repair_only_the_reported_call_then_recheck_public_identity(tmp_path, overbroad):
    corrected = public_candidate()
    initial = deepcopy(corrected)
    initial['root']['goals'][0]['target_call'] = 'f(2*x+1)'
    review = {'status': 'correction_required', 'findings': [{
        'path': TARGET + '/target_call', 'kind': 'wrong_expression',
        'source_excerpt': 'f(2x-1)', 'message': '原图完整输入是 2x-1，候选误写为 2x+1。',
    }]}
    changed_domain = deepcopy(corrected)
    changed_domain['root']['goals'][0]['known_domain'] = '[-3,3]'
    provider = Sequence(initial, review, *([changed_domain] if overbroad else []), corrected, CONFIRMED)
    source = contracts.ROOT / 'internal/senior-high/source-images/function-concepts-q25/source-question.png'
    request = build_search_request(source.read_bytes(), ExtractionArtifactStore(tmp_path / 'inputs'))
    result = run_workflow(request, provider, tmp_path / 'workflow', [],
                          problem_id='q25-authored-repair-probe', contract_adapter=SearchStageOneContract())
    assert result['status'] == 'reviewed_candidate' and result['source_reviewed'], result
    assert result['candidate'] == corrected
    assert identity(corrected) != identity(initial)
    assert [event['stage'] for event in result['events']] == [
        'extract', 'review', *(['repair'] if overbroad else []), 'repair', 'review',
    ]
    if overbroad:
        rejected = [event for event in result['events'] if event['stage'] == 'repair' and not event['adopted']]
        assert len(rejected) == 1
        assert TARGET + '/known_domain' in {item['path'] for item in rejected[0]['repair_rejected']}
    for request in provider.requests:
        assert contracts.SOURCE_RULES in request.prompt.system
        assert '没有解析式是这类题的正常题设' in request.prompt.system
        assert 'known_call 与 known_domain 必须对应同一句已知条件' in request.prompt.system
        assert '抽象函数定义域题的 public_content.statement' in request.prompt.system
    repair = json.loads(provider.requests[2].prompt.user_prefix)
    assert {item['path'] for item in repair['diagnostics']} == {TARGET + '/target_call'}
    assert json.loads(provider.requests[-1].prompt.user_prefix)['candidate'] == corrected
