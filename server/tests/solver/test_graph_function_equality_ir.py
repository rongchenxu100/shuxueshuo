"""The frozen extraction/IR boundary precedes T1 prompt and solver integration."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.function_equality import inspect_comparison_target
from shuxueshuo_server.graph_lesson.stage_one.repair_authority import repair_violations
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search.identity import build_identity, public_structure_errors

FIXTURES = Path(__file__).parent / 'fixtures/function-equality'
TARGET = '/root/goals/0'


def candidate():
    return json.loads((FIXTURES / 'q20-candidate.json').read_text())


def inspected(value):
    report = validate_candidate(value)
    assert report['contract_valid'], report['reports']
    return inspect_comparison_target(value, TARGET)


def identity(public):
    mathematical = {key: public[key] for key in ('original_text', 'root')}
    return build_identity({'status': 'reviewed_candidate', 'source_reviewed': True,
                           'output_contract': 'search-problem-extraction/v1',
                           'public_candidate': public, 'candidate': mathematical,
                           'reviewed_candidate_revision': revision(public)})['fingerprint']


def test_q20_local_scopes_and_unsimplified_root_structure():
    value = candidate()
    goal = inspected(value)
    assert goal['structure_supported']
    assert not value['root'].get('children')
    refs = [option[side]['function_ref'] for option in goal['options'] for side in ('left', 'right')]
    assert len(set(refs)) == 8
    a, _, c, d = goal['options']
    assert a['right']['expression_ast'][0] == '^'
    assert a['right']['expression_ast'][1][:2] == ['call', 'sqrt']
    assert a['right']['expression_latex'] == r'\left(\sqrt{x}\right)^{2}'
    assert c['left']['expression_ast'][:2] == ['call', 'sqrt']
    assert c['left']['expression_ast'][2][0] == '^'
    assert c['left']['expression_latex'] == r'\sqrt{x^{2}}'
    assert c['right']['expression_ast'][:2] == ['call', 'abs']
    assert d['right']['variable'] == 't'
    assert d['left']['expression_ast'] == d['right']['expression_ast']


def test_shared_baseline_can_be_referenced_repeatedly_and_shadowed_locally():
    value = candidate()
    goal = value['root']['goals'][0]
    goal.update(mode='shared_baseline', shared_functions=[{'id': 'base', 'definition': 'f(x)=x'}])
    for option in goal['options']:
        option['functions'] = [{'id': 'candidate', 'definition': 'f(x)=x^2'}]
        option.update(left='shared:base', right='local:candidate')
    result = inspected(value)
    assert result['structure_supported']
    assert len({o['left']['function_ref'] for o in result['options']}) == 1
    assert len({o['right']['function_ref'] for o in result['options']}) == 4
    assert all(o['left']['function_ref'] != o['right']['function_ref'] for o in result['options'])


@pytest.mark.parametrize('mutation', ['dangling', 'duplicate_option', 'duplicate_label', 'duplicate_function', 'unused', 'cross_scope'])
def test_invalid_references_and_identities_are_rejected(mutation):
    value = candidate()
    options = value['root']['goals'][0]['options']
    if mutation == 'dangling':
        options[0]['left'] = 'local:missing'
    elif mutation == 'duplicate_option':
        options[1]['id'] = options[0]['id']
    elif mutation == 'duplicate_label':
        options[1]['label'] = options[0]['label']
    elif mutation == 'duplicate_function':
        options[0]['functions'][1]['id'] = 'f'
    elif mutation == 'unused':
        options[0]['right'] = 'local:f'
    else:
        options[0]['left'] = 'B:local:f'
    assert not validate_candidate(value)['contract_valid']


@pytest.mark.parametrize('domain', ['[0,0]', '{0}', '[0,0)', 'ℝ'])
def test_explicit_domain_is_preserved_at_the_ir_boundary(domain):
    value = candidate()
    value['root']['goals'][0]['options'][0]['functions'][0]['domain'] = domain
    result = inspected(value)['options'][0]['left']
    assert result['explicit_domain'] is True
    assert result['input_domain_source_ref'] == TARGET + '/options/0/functions/0/domain'
    assert result['input_domain_ast'] != ['real'] or domain == 'ℝ'
    # Empty declared intervals are representable; mathematical validity is
    # independently checked at execution, never silently changed to a point.


def test_first_contract_contains_opposite_polarity_and_unknown_is_not_defaulted():
    value = candidate()
    goal = value['root']['goals'][0]
    goal['select_relation'] = 'different'
    assert inspected(value)['select_relation'] == 'different'
    goal['select_relation'] = 'unknown'
    assert not inspected(value)['structure_supported']
    del goal['select_relation']
    assert not validate_candidate(value)['contract_valid']


def test_incomplete_or_additional_scope_conditions_cannot_be_dropped():
    value = candidate()
    value['root']['goals'][0]['completeness'] = 'incomplete'
    assert not inspected(value)['structure_supported']
    value = candidate()
    value['root']['facts'] = ['a>0']
    assert inspected(value)['reason'] == 'comparison.additional_conditions_unsupported'


def test_one_pair_has_no_invented_choice_polarity():
    value = candidate()
    goal = value['root']['goals'][0]
    goal.update(mode='pair', select_relation=None, selection_mode='none', options=goal['options'][:1])
    assert inspected(value)['structure_supported']


def test_public_identity_ignores_opaque_ids_but_keeps_polarity_and_domains():
    public = json.loads((FIXTURES / 'q20-public-candidate.json').read_text())
    original = identity(public)
    renamed = deepcopy(public)
    for i, option in enumerate(renamed['root']['goals'][0]['options']):
        option['id'] = f'option_{i}'
        option['functions'][0]['id'] = 'left'
        option['functions'][1]['id'] = 'right'
        option.update(left='local:left', right='local:right')
    assert identity(renamed) == original
    for field, value in [('select_relation', 'different'), ('selection_mode', 'single')]:
        changed = deepcopy(public)
        changed['root']['goals'][0][field] = value
        if field == 'selection_mode':
            changed['public_content']['scopes'][0]['choices'][0]['selection_mode'] = value
        assert identity(changed) != original
    changed = deepcopy(public)
    changed['root']['goals'][0]['options'][0]['functions'][0]['domain'] = '[0,0]'
    assert identity(changed) != original


def test_public_options_must_match_goal_options():
    public = json.loads((FIXTURES / 'q20-public-candidate.json').read_text())
    assert public_structure_errors(public) == []
    public['public_content']['scopes'][0]['choices'][0]['options'].reverse()
    assert public_structure_errors(public)


@pytest.mark.parametrize('location', ['public', 'comparison'])
def test_malformed_option_formula_returns_local_repair_diagnostic(location):
    from shuxueshuo_server.search.extraction import SearchStageOneContract

    public = json.loads((FIXTURES / 'q20-public-candidate.json').read_text())
    if location == 'public':
        option = public['public_content']['scopes'][0]['choices'][0]['options'][0]
        path = '/public_content/scopes/0/choices/0/options/0/text'
    else:
        option = public['root']['goals'][0]['options'][0]
        path = TARGET + '/options/0/text'
    option['text'] = '$f(x)=x'
    report = SearchStageOneContract().parse(json.dumps(public), problem_id='q20', source_hash='hash', registry=None, store=None)
    assert report['contract_valid'] is False
    issue, = report['reports']['ir']['issues']
    assert issue['path'] == path
    assert issue['code'] == 'schema.invalid'
    assert '成对' in issue['message']


def test_repair_grant_is_local_to_one_option_field():
    before = candidate()
    after = deepcopy(before)
    after['root']['goals'][0]['options'][0]['functions'][0]['definition'] = 'f(x)=2*x'
    grant = [{'stage': 'review', 'action': 'repair', 'code': 'wrong_expression',
              'path': TARGET + '/options/0/functions/0/definition'}]
    assert not repair_violations(before, after, grant)
    after['root']['goals'][0]['options'][1]['functions'][0]['definition'] = 'f(x)=2*x'
    assert repair_violations(before, after, grant)


def test_domain_parse_error_authorizes_only_the_declared_domain_repair():
    before = candidate()
    function = before['root']['goals'][0]['options'][0]['functions'][0]
    function['domain'] = '[0,1'
    report = validate_candidate(before)
    issue, = report['reports']['ir']['issues']
    assert issue['path'] == TARGET + '/options/0/functions/0/domain'
    assert issue['reason_code'] == 'notation.unexpected_end'
    grant = [{'stage': 'ir', 'action': 'repair', 'code': issue['code'], 'path': issue['path']}]
    after = deepcopy(before)
    after['root']['goals'][0]['options'][0]['functions'][0]['domain'] = '[0,1]'
    assert validate_candidate(after)['contract_valid']
    assert not repair_violations(before, after, grant)
    after['root']['goals'][0]['options'][0]['functions'][0]['definition'] = 'f(x)=2*x'
    assert repair_violations(before, after, grant)


def test_definition_parse_error_does_not_authorize_a_valid_declared_domain():
    before = candidate()
    function = before['root']['goals'][0]['options'][0]['functions'][0]
    function.update(definition='f(x)=sqrt(', domain='[0,1]')
    issue, = validate_candidate(before)['reports']['ir']['issues']
    assert issue['path'] == TARGET + '/options/0/functions/0/definition'


def test_old_option_index_grant_cannot_repair_after_reordering():
    before = candidate()
    after = deepcopy(before)
    after['root']['goals'][0]['options'][0:2] = list(reversed(after['root']['goals'][0]['options'][0:2]))
    after['root']['goals'][0]['options'][0]['functions'][0]['definition'] = 'f(x)=2*x'
    grant = [{'stage': 'review', 'action': 'repair', 'code': 'wrong_expression',
              'path': TARGET + '/options/0/functions/0/definition'}]
    assert repair_violations(before, after, grant)
