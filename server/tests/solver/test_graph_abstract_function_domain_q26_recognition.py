"""Q26 structural/source contracts, independent of image-model acceptance."""

import json
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.abstract_function_domain import VERSION
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.solver.test_graph_abstract_function_domain_source import present
from tests.solver.test_graph_function_equality_ir import identity
from tests.solver.test_graph_function_equality_repair import CONFIRMED, Sequence

TARGET = '/root/goals/0'


def candidate(known='f(x+2)', target='f(2*x-1)', *, outer=None):
    return {
        'original_text': f'已知 ${known}$ 的定义域为 $[-3,2]$，求 ${target}$ 的定义域。',
        'root': {'goals': [{'kind': 'find_abstract_domain', 'known_call': known,
                           'known_domain': '[-3,2]', 'strength': 'exact',
                           'target_call': target, **({'input_domain': outer} if outer else {})}]},
    }


def description(value):
    before = deepcopy(value)
    extracted = extract_features(value)
    assert extracted['ok'], extracted
    assert value == before
    by_id = {row['feature_id']: row for row in extracted['features'] if row['target_ref'] == TARGET}
    detail = by_id['abstract_function_domain']['value']
    assert by_id['goal']['value']['known_form'] == detail['known_form']
    assert detail['structure_version'] == VERSION
    return detail, extracted['features']


@pytest.mark.parametrize(('known', 'target', 'form', 'slope', 'intercept', 'dummy', 'variable'), [
    ('f(x)', 'f(2*x-1)', 'identity', '1', '0', 'x', 'x'),
    ('f(t+2)', 'f(2*x-1)', 'affine', '1', '2', 't', 'x'),
    ('f(1-2*u)', 'f(3*t+2)', 'affine', '-2', '1', 'u', 't'),
    ('f(t/2-3/4)', 'f(-2*x)', 'affine', '1/2', '-3/4', 't', 'x'),
    ('f(3*(t-2))', 'f(0)', 'affine', '3', '-6', 't', 't'),
    ('f(t+t-t)', 'f(2*x-1)', 'affine', '1', '0', 't', 'x'),
])
def test_exact_invertible_known_call_keeps_independent_variable_and_coefficients(
        known, target, form, slope, intercept, dummy, variable):
    detail, _ = description(candidate(known, target))
    assert detail['structure_supported'], detail['reason']
    assert detail['known_form'] == form
    assert (detail['known_slope'], detail['known_intercept']) == (slope, intercept)
    assert (detail['known_variable'], detail['variable']) == (dummy, variable)
    assert dummy in detail['known_argument_latex']
    assert detail['input_range_ready'] is (form == 'identity')
    assert detail['known_domain_ast'] == ['interval', True, True, ['neg', ['number', '3']], ['number', '2']]
    assert detail['known_call_source_ref'] == TARGET + '/known_call'


def test_q26_recognizes_selects_m2_and_reads_original_composite_call(tmp_path):
    value = candidate()
    detail, features = description(value)
    assert (detail['target_slope'], detail['target_intercept']) == ('2', '-1')
    recognition = evaluate_types(features)
    assert recognition[0]['type_id'] == 'type-abstract-function-domain'
    assert recognition[0]['status'] == 'supported'
    selection = evaluate_goal(value, TARGET, features, 'type-abstract-function-domain')
    assert selection['d3'] is not None
    assert selection['d4']['options'][0]['method'] == 'method-input-domain-correspondence'
    goal, = present(tmp_path, value)['goals']
    assert 'f(x+2)' in goal['d1']['givens'][0]['text']
    assert '[-3,2]' in goal['d1']['givens'][0]['text']
    assert '[-1,4]' not in json.dumps(goal['d1'], ensure_ascii=False)
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'
    rewritten = deepcopy(value)
    rewritten['root']['goals'][0].update(known_call='f(x)', known_domain='[-1,4]')
    rewritten['original_text'] = '已知 $f(x)$ 的定义域为 $[-1,4]$，求 $f(2*x-1)$ 的定义域。'
    for item in (value, rewritten):
        item['public_content'] = {
            'completeness': 'complete', 'privacy': 'separated', 'figure': 'not_required',
            'scopes': [{'scope_ref': '/root', 'statement': item['original_text'],
                        'choices': [{'target_ref': TARGET, 'status': 'none', 'selection_mode': 'none', 'options': []}]}],
        }
    assert identity(value) != identity(rewritten)


def test_target_outer_range_does_not_restrict_the_known_dummy():
    detail, _ = description(candidate('f(t+2)', 'f(2*x-1)', outer='(0,2)'))
    assert detail['structure_supported']
    assert detail['known_variable'] == 't' and detail['variable'] == 'x'
    assert detail['has_outer_domain'] is True
    assert detail['outer_domain_ast'] != detail['known_domain_ast']


@pytest.mark.parametrize('known', [
    'f(2)', 'f(0*t+2)', 'f(t-t+2)', 'f(t^2)', 'f(1/t)', 'f(t^2/t)',
    'f(c*t+1)', 'f(t+u)', 'f(sqrt(t))', 'f(2^130*t)',
])
def test_unproved_or_noninvertible_known_calls_never_enter_m2(known):
    detail, features = description(candidate(known))
    assert detail['structure_supported'] is False
    assert detail['reason']
    assert detail['known_form'] is None
    assert detail['known_slope'] is detail['known_intercept'] is None
    assert not any(row['type_id'] == 'type-abstract-function-domain' and row['status'] == 'supported'
                   for row in evaluate_types(features))


@pytest.mark.parametrize('inherited', [False, True])
def test_known_side_extra_range_remains_unsupported_in_own_or_parent_scope(inherited):
    value = candidate('f(t+2)')
    if inherited:
        value['root'] = {'facts': ['t∈[0,1]'], 'children': [value['root']]}
        extracted = extract_features(value)
        assert extracted['ok'], extracted
        detail = next(row['value'] for row in extracted['features'] if row['feature_id'] == 'abstract_function_domain')
    else:
        value['root']['facts'] = ['t∈[0,1]']
        detail, _ = description(value)
    assert detail['structure_supported'] is False
    assert detail['reason'] == 'abstract_domain.additional_conditions_unsupported'
    assert detail['known_slope'] is detail['known_intercept'] is None


def test_meaningful_only_is_not_promoted_to_an_exact_domain():
    value = candidate()
    value['root']['goals'][0]['strength'] = 'meaningful_only'
    extracted = extract_features(value)
    assert extracted['ok'] is False
    assert value['root']['goals'][0]['strength'] == 'meaningful_only'


def test_q26_shared_repair_keeps_known_call_and_repairs_only_reported_field(tmp_path):
    corrected = candidate()
    corrected['public_content'] = {
        'completeness': 'complete', 'privacy': 'separated', 'figure': 'not_required',
        'scopes': [{'scope_ref': '/root', 'statement': corrected['original_text'],
                    'choices': [{'target_ref': TARGET, 'status': 'none', 'selection_mode': 'none', 'options': []}]}],
    }
    initial = deepcopy(corrected)
    initial['root']['goals'][0]['known_call'] = 'f(x)'
    review = {'status': 'correction_required', 'findings': [{
        'path': TARGET + '/known_call', 'kind': 'wrong_expression',
        'source_excerpt': 'f(x+2)', 'message': '原题给定 f(x+2) 的定义域，不能删去 +2。',
    }]}
    provider = Sequence(initial, review, corrected, CONFIRMED)
    image = contracts.ROOT / 'internal/senior-high/source-images/function-concepts-q25/source-question.png'
    request = build_search_request(image.read_bytes(), ExtractionArtifactStore(tmp_path / 'inputs'))
    result = run_workflow(request, provider, tmp_path / 'workflow', [],
                          problem_id='q26-authored-source-probe', contract_adapter=SearchStageOneContract())
    assert result['status'] == 'reviewed_candidate' and result['source_reviewed'], result
    assert result['candidate'] == corrected
    assert [event['stage'] for event in result['events']] == ['extract', 'review', 'repair', 'review']
    for request in provider.requests:
        assert contracts.SOURCE_RULES in request.prompt.system
        assert '不能把推导出的 [-1,4] 填入 known_domain' in request.prompt.system
        assert '不能省略，也不能搬到目标的 input_domain' in request.prompt.system
        assert '公开题干与 root 中该目标的 known_call 都必须保留 x+2' in request.prompt.system
    repair = json.loads(provider.requests[2].prompt.user_prefix)
    assert {item['path'] for item in repair['diagnostics']} == {TARGET + '/known_call'}
