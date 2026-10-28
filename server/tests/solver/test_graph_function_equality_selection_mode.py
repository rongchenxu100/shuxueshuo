"""Unspecified source choice mode stays unspecified through safe repair and IR.

The initial candidate/review/failed repairs are the real 60809cd078af responses.
The corrected candidate and final confirmation below are offline provider probes,
not a claim that the failed browser photograph was successfully re-reviewed.
"""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    build_search_request,
)
from shuxueshuo_server.search.identity import (
    mathematical_candidate,
    public_structure_errors,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from tests.solver.test_graph_function_equality_ir import identity
from tests.solver.test_graph_function_equality_recognition import envelope
from tests.solver.test_graph_function_equality_repair import CONFIRMED, Sequence

FIXTURES = Path(__file__).parent / 'fixtures/function-equality'
RECORDING = Path(__file__).parents[1] / 'search/fixtures/function-equality/domain-first-mode-oscillation-20261028'
TARGET = '/root/goals/0'
MODE_PATHS = {TARGET + '/selection_mode', '/public_content/scopes/0/choices/0/selection_mode'}


def read(name):
    return json.loads((RECORDING / name).read_text())


def corrected():
    value = read('initial-candidate.json')
    value['root']['goals'][0]['selection_mode'] = 'unspecified'
    value['public_content']['scopes'][0]['choices'][0]['selection_mode'] = 'unspecified'
    return value


def execute(tmp_path, provider):
    request = build_search_request((RECORDING / 'question.png').read_bytes(),
                                   ExtractionArtifactStore(tmp_path / 'inputs'))
    return run_workflow(request, provider, tmp_path / 'workflow', [],
                        problem_id='domain-first-mode-offline', contract_adapter=SearchStageOneContract())


def test_real_failed_recording_is_immutable_and_not_mislabeled_success():
    metadata = read('recording.json')
    assert metadata['status'] == 'workflow.oscillation' and not metadata['source_reviewed']
    assert metadata['call_stages'] == ['extract', 'review', 'repair', 'repair']
    assert metadata['semantic_calls'] == metadata['network_attempts'] == 4
    for name, digest in metadata['files'].items():
        assert sha256((RECORDING / name).read_bytes()).hexdigest() == digest
    initial, partial, rollback = [read(name) for name in (
        'initial-candidate.json', 'partial-repair-candidate.json', 'rollback-candidate.json')]
    assert initial == rollback
    assert partial['root']['goals'][0]['selection_mode'] == 'single'
    assert partial['public_content']['scopes'][0]['choices'][0]['selection_mode'] == 'unspecified'
    assert public_structure_errors(partial)


@pytest.mark.parametrize('name', ['q20-public-candidate.json', 'q19-public-candidate.json'])
@pytest.mark.parametrize('mode', ['single', 'multiple', 'unspecified'])
def test_groups_and_shared_baseline_accept_source_modes_without_inventing_answers(tmp_path, name, mode):
    public = json.loads((FIXTURES / name).read_text())
    public['root']['goals'][0]['selection_mode'] = mode
    public['public_content']['scopes'][0]['choices'][0]['selection_mode'] = mode
    contract = SearchStageOneContract()
    parsed = contract.parse(json.dumps(public), problem_id='choice-mode', source_hash='source', registry=[], store=None)
    assert parsed['contract_valid'], parsed
    source_schema = json.loads((contracts.ROOT / 'internal/schemas/problem-math-notation-v1.schema.json').read_text())
    goal_schema = source_schema['$defs']['CompareFunctionsGoal']
    Draft202012Validator({'$defs': source_schema['$defs'], **goal_schema}).validate(public['root']['goals'][0])
    original = deepcopy(public)
    value = envelope(mathematical_candidate(public))
    assert validate_input(value)['ok']
    result = run_result(value, tmp_path / 'stage-two')
    assert result['goals'][0]['primary'] == 'type-function-equality'
    for row in value['features']:
        if row['feature_id'] in {'goal', 'function_comparison'}:
            assert row['value']['selection_mode'] == mode
    assert public == original


def test_pair_still_requires_none_and_has_no_source_choice_mode():
    value = mathematical_candidate(corrected())
    goal = value['root']['goals'][0]
    goal.update(mode='pair', select_relation=None, selection_mode='none', options=goal['options'][:1])
    assert validate_candidate(value)['contract_valid']
    features = envelope(value)
    assert validate_input(features)['ok']
    for mode in ('single', 'multiple', 'unspecified'):
        goal['selection_mode'] = mode
        assert not validate_candidate(value)['contract_valid']
        for feature_id in ('goal', 'function_comparison'):
            altered = deepcopy(features)
            next(row for row in altered['features'] if row['feature_id'] == feature_id)['value']['selection_mode'] = mode
            assert not validate_input(altered)['ok']


def test_public_mode_must_match_goal_and_identity_does_not_guess_from_answer_count():
    initial, unspecified = read('initial-candidate.json'), corrected()
    assert public_structure_errors(unspecified) == []
    assert identity(initial) != identity(unspecified)
    both = deepcopy(unspecified)
    both['root']['goals'][0]['selection_mode'] = 'multiple'
    both['public_content']['scopes'][0]['choices'][0]['selection_mode'] = 'multiple'
    assert len({identity(initial), identity(unspecified), identity(both)}) == 3
    unspecified['public_content']['scopes'][0]['choices'][0]['selection_mode'] = 'single'
    assert public_structure_errors(unspecified)


def test_real_review_can_repair_both_modes_then_review_without_oscillation(tmp_path):
    initial, review, fixed = read('initial-candidate.json'), read('review.json'), corrected()
    provider = Sequence(initial, review, fixed, CONFIRMED)
    result = execute(tmp_path, provider)
    assert result['status'] == 'reviewed_candidate' and result['source_reviewed'], result
    assert result['candidate'] == fixed
    assert provider.calls == 4
    assert [event['stage'] for event in result['events']] == ['extract', 'review', 'repair', 'review']
    repair = json.loads(provider.requests[2].prompt.user_prefix)
    assert repair['base_candidate'] == initial
    assert {item['path'] for item in repair['diagnostics']} == MODE_PATHS
    assert json.loads(provider.requests[3].prompt.user_prefix)['candidate'] == fixed
    # All stages carry the same source rule, not a repair-only convention.
    for request in provider.requests:
        assert contracts.SOURCE_RULES in request.prompt.system
        assert '正确项数量反推单选或多选' in request.prompt.system
        assert '默认按不定项选择处理' in request.prompt.system


def test_source_mode_repair_does_not_authorize_formula_or_polarity_changes(tmp_path):
    fixed = corrected()
    overbroad = deepcopy(fixed)
    overbroad['root']['goals'][0]['options'][0]['functions'][0]['definition'] = 'f(x)=sqrt(2*x^3)'
    overbroad['root']['goals'][0]['select_relation'] = 'different'
    provider = Sequence(read('initial-candidate.json'), read('review.json'), overbroad, fixed, CONFIRMED)
    result = execute(tmp_path, provider)
    assert result['status'] == 'reviewed_candidate' and result['source_reviewed'], result
    assert result['candidate'] == fixed
    rejected = [event for event in result['events'] if event['stage'] == 'repair' and not event['adopted']]
    assert len(rejected) == 1
    assert {item['path'] for item in rejected[0]['repair_rejected']} >= {
        TARGET + '/options/0/functions/0/definition', TARGET + '/select_relation'}


def test_historical_partial_repair_and_rollback_still_reproduce_the_failure(tmp_path):
    provider = Sequence(read('initial-candidate.json'), read('review.json'),
                        read('partial-repair-candidate.json'), read('rollback-candidate.json'))
    result = execute(tmp_path, provider)
    assert result['status'] == 'workflow.oscillation', result
    assert not result['source_reviewed']
