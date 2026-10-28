"""Mixed abstract/concrete domain recognition and original-source contracts."""

import json
from copy import deepcopy

import pytest
from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.solver.test_graph_abstract_function_domain_q26_recognition import (
    candidate,
    description,
)
from tests.solver.test_graph_abstract_function_domain_source import present
from tests.solver.test_graph_function_equality_ir import identity
from tests.solver.test_graph_function_equality_repair import CONFIRMED, Sequence

TARGET = '/root/goals/0'


@pytest.mark.parametrize(('target', 'form', 'slope', 'intercept', 'variable'), [
    ('f(3-4*x)/sqrt(x-1)', 'sqrt_affine_denominator', '1', '-1', 'x'),
    ('f(2*x-1)/(x-2)', 'affine_denominator', '1', '-2', 'x'),
    ('f(x)/sqrt(3-2*x)', 'sqrt_affine_denominator', '-2', '3', 'x'),
    ('f(x)/(x/2-3/4)', 'affine_denominator', '1/2', '-3/4', 'x'),
    ('f(1)/(x-2)', 'affine_denominator', '1', '-2', 'x'),
    ('f(2*x-1)/2', 'affine_denominator', '0', '2', 'x'),
    ('f(2*x-1)/(-3)', 'affine_denominator', '0', '-3', 'x'),
    ('f(0)/sqrt(2)', 'sqrt_affine_denominator', '0', '2', 't'),
    ('f(2*u-1)/sqrt(u-u+2)', 'sqrt_affine_denominator', '0', '2', 'u'),
])
def test_mixed_target_keeps_original_tree_and_binds_one_outer_variable(target, form, slope, intercept, variable):
    value = candidate('f(t+2)', target)
    detail, features = description(value)
    assert detail['structure_supported'], detail['reason']
    assert detail['target_form'] == form
    assert detail['target_call_ast'][0] == '/'
    assert detail['target_argument_ast'] == detail['target_call_ast'][1][2]
    assert detail['concrete_denominator_ast'] == detail['target_call_ast'][2]
    assert detail['denominator_ast_path'] == [2]
    assert (detail['denominator_slope'], detail['denominator_intercept']) == (slope, intercept)
    assert detail['variable'] == variable and detail['known_variable'] == 't'
    assert detail['known_form'] == 'affine'
    assert detail['target_latex'].startswith(r'\frac{f(')
    assert detail['concrete_denominator_latex'] in detail['target_latex']
    recognition = evaluate_types(features)
    assert any(row['type_id'] == 'type-abstract-function-domain' and row['status'] == 'supported'
               for row in recognition)
    assert not any(row['type_id'] == 'type-function-domain' and row['status'] == 'supported'
                   for row in recognition)


@pytest.mark.parametrize('target', [
    '1/f(x)', 'sqrt(f(x))', 'f(x)^0', 'f(x)/f(x)', 'f(x)+f(x)',
    'f(f(x))', 'f(x)/(x-t)', 'f(x)/sqrt(t)', 'f(a*x)/(x+1)',
    'f(x)/(a*x+1)', 'f(x)/sqrt(x^2)', 'f(x)/(x*x)',
    'f(x)/(x/x)', 'f(x)/sqrt(x^0)', 'f(x^2)/(x+1)',
    'f(x)/sqrt(sqrt(x))', 'f(x)*sqrt(x)', 'f(x)/0', 'f(x)/(x-x)',
    'f(x)/sqrt(0)', 'f(x)/sqrt(-1)', 'f(x)/sqrt(x-x-1)',
    'f(x)/(2^130*x)',
])
def test_unsupported_mixed_structure_never_silently_loses_a_condition(target):
    value = candidate('f(t+2)', target)
    detail, features = description(value)
    assert detail['structure_supported'] is False
    assert detail['reason']
    assert value['root']['goals'][0]['target_call'] == target
    assert not any(row['type_id'] == 'type-abstract-function-domain' and row['status'] == 'supported'
                   for row in evaluate_types(features))


@pytest.mark.parametrize('target', ['f(2*x-1)/2', 'f(1)/sqrt(x+1)'])
def test_d1_keeps_entire_mixed_goal_and_target_outer_range(tmp_path, target):
    value = candidate('f(t+2)', target, outer='(0,2)')
    value['original_text'] = (f'已知 $f(t+2)$ 的定义域为 $[-3,2]$，另限 $x∈(0,2)$，'
                              f'求 ${target}$ 的定义域。')
    (goal,) = present(tmp_path, value)['goals']
    assert goal['primary'] == 'type-abstract-function-domain'
    assert len(goal['d1']['rows']) == 1 and len(goal['d1']['givens']) == 2
    row = goal['d1']['rows'][0]
    correct = next(option['text'] for option in row['options'] if option['correct'])
    denominator = '2' if target.endswith('/2') else r'\sqrt{x+1}'
    assert f'/{denominator}$' in correct and '自变量 $x$' in correct
    assert '具体分母自身有意义且不为零' in goal['d1']['summary']
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'
    assert any('$x\\in (0,2)$' in given['text'] for given in goal['d1']['givens'])


@pytest.mark.parametrize('display', [
    r'g(x)=\frac{f(x+1)}{\sqrt{3x-1}}',
    r'g\left(x\right)=\frac{f(x+1)}{\sqrt{3x-1}}',
])
def test_d1_binds_named_mixed_function_without_dropping_its_denominator(tmp_path, display):
    value = candidate('f(x+2)', 'f(x+1)/sqrt(3*x-1)')
    value['original_text'] = f'已知 $f(x+2)$ 的定义域为 $(-3,4)$，求 ${display}$ 的定义域。'
    value['root']['goals'][0]['known_domain'] = '(-3,4)'
    (goal,) = present(tmp_path, value)['goals']
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'
    assert len(goal['d1']['rows']) == 1
    assert r'\sqrt{3x-1}' in goal['d1']['question']


def test_d1_rejects_target_alias_with_a_different_outer_variable(tmp_path):
    value = candidate('f(t+2)', 'f(x+1)/sqrt(3*x-1)')
    value['original_text'] = (r'已知 $f(t+2)$ 的定义域为 $[-3,2]$，'
                              r'求 $g(t)=\frac{f(x+1)}{\sqrt{3x-1}}$ 的定义域。')
    (goal,) = present(tmp_path, value)['goals']
    assert goal['d1']['rows'] == []
    assert goal['walk'] is None


@pytest.mark.parametrize(('before', 'after'), [
    ('sqrt(x-1)', 'sqrt(x+1)'), ('sqrt(x-1)', '(x-1)'),
    ('f(3-4*x)/sqrt(x-1)', 'f(3-4*x)'),
])
def test_d1_cannot_confirm_a_missing_or_changed_denominator(tmp_path, before, after):
    value = candidate('f(t+2)', 'f(3-4*x)/sqrt(x-1)')
    value['original_text'] = value['original_text'].replace(before, after)
    (goal,) = present(tmp_path, value)['goals']
    assert goal['d1']['rows'] == []
    assert goal['walk'] is None
    assert goal['d1']['diagnostics'][0]['code'] == 'd1.abstract_domain_source_not_uniquely_located'


def _public(value):
    value['public_content'] = {
        'completeness': 'complete', 'privacy': 'separated', 'figure': 'not_required',
        'scopes': [{'scope_ref': '/root', 'statement': value['original_text'],
                    'choices': [{'target_ref': TARGET, 'status': 'none', 'selection_mode': 'none', 'options': []}]}],
    }
    return value


def test_public_identity_retains_concrete_denominator_and_root_scope():
    values = [_public(candidate('f(t+2)', target)) for target in (
        'f(x)/sqrt(x-1)', 'f(x)/(x-1)', 'f(x)', 'f(x)/sqrt(x+1)',
    )]
    assert len({identity(value) for value in values}) == len(values)


def test_shared_extract_review_repair_retains_complete_mixed_target(tmp_path):
    corrected = _public(candidate('f(t+2)', 'f(3-4*x)/sqrt(x-1)'))
    initial = deepcopy(corrected)
    initial['root']['goals'][0]['target_call'] = 'f(3-4*x)'
    review = {'status': 'correction_required', 'findings': [{
        'path': TARGET + '/target_call', 'kind': 'wrong_expression',
        'source_excerpt': 'f(3-4*x)/sqrt(x-1)', 'message': '目标原式的根式分母不能省略。',
    }]}
    provider = Sequence(initial, review, corrected, CONFIRMED)
    # Authored workflow probe only; this image does not claim live mixed-photo acceptance.
    image = contracts.ROOT / 'internal/senior-high/source-images/function-concepts-q25/source-question.png'
    request = build_search_request(image.read_bytes(), ExtractionArtifactStore(tmp_path / 'inputs'))
    result = run_workflow(request, provider, tmp_path / 'workflow', [],
                          problem_id='mixed-authored-source-probe', contract_adapter=SearchStageOneContract())
    assert result['status'] == 'reviewed_candidate' and result['source_reviewed'], result
    assert result['candidate'] == corrected
    assert [event['stage'] for event in result['events']] == ['extract', 'review', 'repair', 'review']
    for request in provider.requests:
        assert contracts.SOURCE_RULES in request.prompt.system
        assert 'target_call 仍转录完整目标原式' in request.prompt.system
        assert '不省略或约去分母' in request.prompt.system
    repair = json.loads(provider.requests[2].prompt.user_prefix)
    assert {item['path'] for item in repair['diagnostics']} == {TARGET + '/target_call'}
    assert extract_features(result['candidate'])['ok']
