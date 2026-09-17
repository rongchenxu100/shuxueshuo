"""A list status describes candidate readiness, independently of task completion."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from shuxueshuo_server.product.problem_presentation import (
    original_text_excerpt,
    understanding_presentation,
)
from shuxueshuo_server.product.understanding import candidate_state


@pytest.fixture
def current():
    sid, cid, rid = uuid4(), uuid4(), uuid4()
    config = {'contract': 'v1'}
    p = {'title': None, 'current_source_version_id': sid, 'understanding_generation': 1}
    source = {'id': sid, 'images': [{'source_id': str(uuid4())}]}
    candidate = {'id': cid, 'source_version_id': sid,
        'candidate_json': {'root': {'definitions': ['f(x)=x^2', 'g(x)=2*x-1']}, 'match_status': 'unmatched'},
        'validation_json': {'contract_valid': True, 'reports': {}}}
    run = {'id': rid, 'candidate_id': cid, 'source_version_id': sid, 'generation': 1,
        'status': 'completed', 'frozen': config, 'error_code': None, 'created_at': datetime.now(UTC),
        'result_json': {'status': 'reviewed_candidate', 'source_reviewed': True, 'source_status': 'confirmed', 'parse_status': 'valid'}}
    return p, source, candidate, run, config


@pytest.mark.parametrize('mutation,expected', [
    ('confirmed_unmatched', 'unsupported'), ('active_review', 'running'), ('failed', 'failed'),
    ('missing_figure', 'needs_confirmation'), ('code_gap', 'code_gap'), ('budget', 'needs_confirmation'),
    ('changed_config', 'needs_review'), ('changed_candidate', 'needs_review'), ('manual', 'needs_review'),
    ('new_source', 'not_started'),
])
def test_outcomes_preserve_blockers_and_current_review_binding(current, mutation, expected):
    p, source, candidate, run, config = current
    if mutation == 'active_review':
        run['status'] = 'running'
    elif mutation == 'failed':
        run.update(status='failed', error_code='workflow.provider_failed')
    elif mutation == 'missing_figure':
        candidate['candidate_json']['root']['children'] = [{'uncertainties': [{'kind': 'missing_figure', 'text': '配图缺失'}]}]
    elif mutation == 'code_gap':
        run['result_json'].update(status='code_gap', source_reviewed=False)
    elif mutation == 'budget':
        run['result_json'].update(status='workflow.budget_exhausted', source_reviewed=False)
    elif mutation == 'changed_config':
        config = {'contract': 'v2'}
    elif mutation == 'changed_candidate':
        run['candidate_id'] = uuid4()
    elif mutation == 'manual':
        run = None
    elif mutation == 'new_source':
        candidate = run = None
    result = understanding_presentation(p, source, candidate, run, config)
    assert result['status'] == expected
    if mutation == 'missing_figure':
        assert result['reason'] == 'missing_figure'
    if mutation in ('changed_config', 'changed_candidate', 'manual', 'new_source', 'active_review'):
        assert result['result_id'] is None


def test_excerpt_uses_source_wording_and_never_generates_text_from_ir():
    value = {'original_text': '已知函数f(x)=x²。\n（1）求其最小值。',
        'root': {'definitions': ['f(x) = x^2'], 'children': [{'facts': ['∀x∈ℝ: f(x)≥0']}]},
        'match_reason': '内部题型判断，不是题干', 'answer': '不应读取'}
    assert original_text_excerpt(value) == '已知函数f(x)=x²。 （1）求其最小值。'
    assert len(original_text_excerpt({'original_text': 'a' * 1000})) == 241
    del value['original_text']
    assert original_text_excerpt(value) == ''


def test_missing_transcription_uses_image_while_preserving_result_status(current):
    result = understanding_presentation(*current)
    assert result['title'] == '原题文字待提取'
    assert result['title_kind'] == 'image'
    assert result['status'] == 'unsupported'


@pytest.mark.parametrize('change,reason', [
    ('configuration', 'configuration_changed'),
    ('candidate', 'candidate_or_source_changed'),
    ('source', 'candidate_or_source_changed'),
    ('unfinished', 'run_not_completed'),
])
def test_stale_review_explains_which_binding_changed(current, change, reason):
    p, _, candidate, run, config = current
    if change == 'configuration': config = {'contract': 'v2'}
    elif change == 'candidate': run['candidate_id'] = uuid4()
    elif change == 'source': p['current_source_version_id'] = uuid4()
    else: run['status'] = 'running'
    state = candidate_state(p, candidate, run, config)
    assert not state['source_reviewed']
    assert state['source_status'] == 'stale'
    assert state['review_stale_reason'] == reason
