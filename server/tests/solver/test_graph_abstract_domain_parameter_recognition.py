"""Source and admission contracts for existential multi-call parameter goals."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.abstract_domain_parameter import (
    inspect_abstract_domain_parameter_target,
)
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
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
FIXTURE = Path(__file__).parent / 'fixtures/abstract-function-domain/variant02-candidate.json'


def candidate(target='f(x+a)+f(x-a)', *, domain='[0,1]', strength='meaningful_only'):
    value = json.loads(FIXTURE.read_text())
    value['root']['goals'][0].update(target_call=target, known_domain=domain, strength=strength)
    return value


def describe(value):
    before = deepcopy(value)
    result = extract_features(value)
    assert result['ok'], result
    assert value == before
    return inspect_abstract_domain_parameter_target(value, TARGET), result['features']


def present_math(tmp_path, value):
    # The search adapter removes its public projection before graph validation.
    math_candidate = deepcopy(value)
    math_candidate.pop('public_content', None)
    return present(tmp_path, math_candidate)


@pytest.mark.parametrize(('target', 'coefficients'), [
    ('f(x+a)+f(x-a)', [('1', '1', '0'), ('1', '-1', '0')]),
    ('f(2*x-a/2+3)*f(-x+a)', [('2', '-1/2', '3'), ('-1', '1', '0')]),
    ('f(a)+f(1-a)', [('0', '1', '0'), ('0', '-1', '1')]),
    ('f(0)+f(1)', [('0', '0', '0'), ('0', '0', '1')]),
    ('f(x+a)-f(x+a)', [('1', '1', '0'), ('1', '1', '0')]),
])
def test_linear_roles_and_each_original_call_are_preserved(target, coefficients):
    detail, features = describe(candidate(target))
    assert detail['structure_supported'], detail['reason']
    assert detail['known_strength'] == 'meaningful_only'
    assert detail['variable_ref'][1].endswith(':x') and detail['parameter_ref'][1].endswith(':a')
    assert [(call['x_coefficient'], call['parameter_coefficient'], call['constant'])
            for call in detail['calls']] == coefficients
    assert [call['ast_path'] for call in detail['calls']] == [[1], [2]]
    for call in detail['calls']:
        node = detail['target_call_ast']
        for index in call['ast_path']:
            node = node[index]
        assert node[0] == 'function_call' and node[2] == call['argument_ast']
    supported = [row['type_id'] for row in evaluate_types(features) if row['status'] == 'supported']
    assert supported == ['type-abstract-function-domain']


@pytest.mark.parametrize('domain', ['(0,1)', '(0,1]', '[0,0]', '{0}'])
def test_finite_interval_endpoint_forms_and_singletons_are_admitted(domain):
    detail, _ = describe(candidate(domain=domain, strength='exact'))
    assert detail['structure_supported'], detail['reason']
    assert detail['known_strength'] == 'exact'


@pytest.mark.parametrize('target', [
    'f(x*a)+f(x-a)', 'f(x^2)+f(x-a)', 'f(x+a)/f(x-a)',
    'sqrt(f(x+a))+f(x-a)', 'f(x+a)^0+f(x-a)', 'f(f(x+a))+f(x-a)',
    'f(x/a)+f(x-a)', 'f(x+b)+f(x-a)', 'f(x+a)',
])
def test_unsupported_parameter_shapes_fail_closed(target):
    detail, features = describe(candidate(target))
    assert not detail['structure_supported']
    assert detail['reason']
    assert not any(row['status'] == 'supported' for row in evaluate_types(features))


@pytest.mark.parametrize('domain', ['[0,0)', '[1,0]', '(0,oo)', 'ℝ'])
def test_empty_or_unbounded_known_range_is_outside_this_contract(domain):
    detail, _ = describe(candidate(domain=domain))
    assert not detail['structure_supported']


def test_known_composite_call_and_extra_source_conditions_are_not_discarded():
    value = candidate()
    value['root']['goals'][0]['known_call'] = 'f(x+2)'
    detail, _ = describe(value)
    assert detail['reason'] == 'abstract_domain.identity_known_call_required'
    value = candidate()
    value['root']['facts'] = ['a>0']
    detail, _ = describe(value)
    assert detail['reason'] == 'abstract_domain.additional_conditions_unsupported'


def test_d1_preserves_meaningful_only_and_reads_parameter_existence(tmp_path):
    value = candidate()
    (goal,) = present_math(tmp_path, value)['goals']
    assert goal['primary'] == 'type-abstract-function-domain'
    assert goal['d1']['rows']
    assert '在 $[0,1]$ 上有定义' in goal['d1']['givens'][0]['text']
    correct = next(option['text'] for option in goal['d1']['rows'][0]['options'] if option['correct'])
    assert '题设给定的输入范围内' in correct and '至少存在一个合法 $x$' in correct
    assert '$a$ 范围' in correct
    assert '定义域恰为' not in json.dumps(goal['d1'], ensure_ascii=False)
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'


@pytest.mark.parametrize(('before', 'after'), [
    ('在 $[0,1]$ 上有定义', '的定义域为 $[0,1]$'),
    ('f(x+a)+f(x-a)', 'f(x+a)-f(x-a)'),
    ('要使函数', '对任意 $x$，要使函数'),
])
def test_d1_cannot_confirm_changed_strength_call_or_quantifier(tmp_path, before, after):
    value = candidate()
    value['original_text'] = value['original_text'].replace(before, after)
    (goal,) = present_math(tmp_path, value)['goals']
    assert goal['d1']['rows'] == []
    assert goal['walk'] is None


@pytest.mark.parametrize('requirement', [
    '对任意实数 $x$，', '对所有的 $x$，', '对一切实数 $x$，',
    r'对 $\forall x\in\mathbb{R}$，', '对 $∀x∈ℝ$，',
    r'对 $\forall\,x\in\mathbb R$，',
])
def test_d1_rejects_universal_outer_variable_in_normalized_source(tmp_path, requirement):
    value = candidate()
    value['original_text'] = value['original_text'].replace('要使函数', requirement + '要使函数')
    (goal,) = present_math(tmp_path, value)['goals']
    assert goal['d1']['rows'] == []
    assert goal['walk'] is None
    assert goal['d1']['diagnostics'][0]['code'] == 'd1.abstract_domain_source_not_uniquely_located'


@pytest.mark.parametrize('requirement', [
    '对任意实数 $t$，', '对所有的 $t$，', r'对 $\forall t\in\mathbb R$，',
])
def test_d1_does_not_bind_another_variables_universal_quantifier(tmp_path, requirement):
    value = candidate()
    value['original_text'] = value['original_text'].replace('要使函数', requirement + '要使函数')
    (goal,) = present_math(tmp_path, value)['goals']
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'


@pytest.mark.parametrize('display', [
    'g(x)=f(x+a)+f(x-a)', r'g\left(x\right)=f(x+a)+f(x-a)',
])
def test_d1_binds_named_parameter_target_with_its_outer_variable(tmp_path, display):
    value = candidate()
    value['root']['definitions'] = ['g(x)=f(x+a)+f(x-a)']
    value['original_text'] = value['original_text'].replace('$f(x+a)+f(x-a)$', f'${display}$')
    (goal,) = present_math(tmp_path, value)['goals']
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'
    assert goal['primary'] == 'type-abstract-function-domain'
    assert goal['d1']['rows']


@pytest.mark.parametrize('display', [
    'g(a)=f(x+a)+f(x-a)', 'g(t)=f(x+a)+f(x-a)',
    'g(x)=f(x+a)-f(x-a)', 'g(x)=f(x+a)', 'a=f(x+a)+f(x-a)',
])
def test_d1_rejects_parameter_alias_with_wrong_binder_or_changed_expression(tmp_path, display):
    value = candidate()
    value['original_text'] = value['original_text'].replace('$f(x+a)+f(x-a)$', f'${display}$')
    (goal,) = present_math(tmp_path, value)['goals']
    assert goal['d1']['rows'] == []
    assert goal['walk'] is None


def test_public_identity_distinguishes_strength_and_target_parameter():
    first = candidate()
    second = candidate(strength='exact')
    third = candidate()
    third['root']['goals'][0].update(variable='a', parameter='x')
    assert len({identity(first), identity(second), identity(third)}) == 3


def test_review_repair_restores_source_strength_without_changing_target(tmp_path):
    corrected = candidate()
    initial = deepcopy(corrected)
    initial['root']['goals'][0]['strength'] = 'exact'
    review = {'status': 'correction_required', 'findings': [{
        'path': TARGET + '/strength', 'kind': 'wrong_expression',
        'source_excerpt': '在 [0,1] 上有定义', 'message': '题面只保证该输入区间，不能改成完整定义域。',
    }]}
    provider = Sequence(initial, review, corrected, CONFIRMED)
    image = contracts.ROOT / 'internal/senior-high/source-images/function-concepts-parameter-variant02/source-question.png'
    request = build_search_request(image.read_bytes(), ExtractionArtifactStore(tmp_path / 'inputs'))
    result = run_workflow(request, provider, tmp_path / 'workflow', [],
                          problem_id='parameter-authored-source-probe', contract_adapter=SearchStageOneContract())
    assert result['status'] == 'reviewed_candidate' and result['source_reviewed'], result
    assert result['candidate'] == corrected
    # Assert the repair's mathematical effect and source binding, not a retired
    # topic-specific sentence in the shared extraction prompt.
    assert len(provider.requests) == 4
    detail = inspect_abstract_domain_parameter_target(result['candidate'], TARGET)
    assert detail['structure_supported'] and detail['known_strength'] == 'meaningful_only'
    repair = json.loads(provider.requests[2].prompt.user_prefix)
    assert {item['path'] for item in repair['diagnostics']} == {TARGET + '/strength'}
