"""A list status describes candidate readiness, independently of task completion."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from shuxueshuo_server.product.problem_presentation import (
    original_text_excerpt,
    problem_presentations,
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


def test_local_review_keeps_unmatched_candidate_as_unsupported_after_config_change(current):
    p, source, candidate, run, config = current
    result = understanding_presentation(p, source, candidate, run, {'contract': 'v2'}, local=True)
    assert result['status'] == 'unsupported'
    assert result['reason'] is None


def test_ready_candidate_defers_to_active_lesson_build(current):
    from shuxueshuo_server.product.problem_presentation import overlay_active_build

    p, source, candidate, run, config = current
    candidate = {
        **candidate,
        'candidate_json': {
            **candidate['candidate_json'],
            'match_status': 'matched',
            'family_id': 'parabola',
            'original_text': '已知抛物线',
        },
    }
    ready = understanding_presentation(p, source, candidate, run, config, local=True)
    assert ready['status'] == 'ready' and ready['result_id'] == str(run['id'])
    demoted = overlay_active_build(ready, 'running')
    assert demoted == {
        **ready,
        'phase': 'generation',
        'status': 'running',
        'result_id': None,
    }
    assert overlay_active_build(ready, 'succeeded') is ready
    assert overlay_active_build(ready, 'failed') is ready
    unsupported = overlay_active_build(ready, 'failed', 'admission.family_unmatched')
    assert unsupported['status'] == 'unsupported'
    assert unsupported['reason'] == 'admission.family_unmatched'


def test_completed_current_page_overrides_stale_understanding_intervention(current):
    from shuxueshuo_server.product.problem_presentation import overlay_active_build

    stale = {
        'title': '题目',
        'title_kind': 'source_text',
        'image_source_id': str(uuid4()),
        'phase': 'understanding',
        'status': 'needs_confirmation',
        'reason': 'missing_figure',
        'result_id': str(current[3]['id']),
    }
    page_id = uuid4()
    result = overlay_active_build(
        stale,
        'succeeded',
        current_page_build=True,
        page_id=page_id,
    )
    assert result == {
        **stale,
        'phase': 'generation',
        'status': 'ready',
        'reason': None,
        'result_id': str(page_id),
    }


def test_latest_build_page_overrides_stale_intervention_without_current_pointer(current):
    """Notation pages may exist while problems.current_page_build_id is null."""
    p, source, candidate, run, config = current
    problem_id, build_id, page_id = uuid4(), uuid4(), uuid4()
    created_at = datetime.now(UTC)
    source = {**source, 'created_at': created_at}
    candidate = {**candidate, 'candidate_json': {
        **candidate['candidate_json'], 'match_status': 'matched', 'family_id': 'parabola',
    }, 'created_at': created_at}
    run = {**run, 'result_json': {'status': 'needs_confirmation'}, 'frozen': config, 'created_at': created_at}
    record = {
        **p,
        'id': problem_id,
        'current_source_version_id': source['id'],
        'current_candidate_id': candidate['id'],
        'latest_extraction_run_id': run['id'],
        'understanding_generation': 1,
        'latest_build_id': build_id,
        'current_page_build_id': None,
        'primary_source_id': source['id'],
    }
    legacy = {problem_id: {
        'id': problem_id,
        'domain_json': {},
        'filename': 'question.png',
        'status': 'succeeded',
        'error_code': None,
        'build_created_at': created_at,
    }}

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def __iter__(self):
            return iter(self.rows)

    class Connection:
        def __init__(self, responses):
            self.responses = iter(responses)

        def execute(self, _statement):
            return Result(next(self.responses))

    result = problem_presentations(Connection([
        [source], [candidate], [run], [{'id': page_id, 'build_id': build_id}],
    ]), [record], legacy)

    assert result[problem_id]['status'] == 'ready'
    assert result[problem_id]['phase'] == 'generation'
    assert result[problem_id]['result_id'] == str(page_id)


def test_source_review_admission_keeps_missing_figure_intervention(current):
    from shuxueshuo_server.product.problem_presentation import overlay_active_build

    p, source, candidate, run, config = current
    candidate['candidate_json']['root']['children'] = [
        {'uncertainties': [{'kind': 'missing_figure', 'text': '配图缺失'}]}
    ]
    presentation = understanding_presentation(p, source, candidate, run, config)
    assert presentation['status'] == 'needs_confirmation'
    assert overlay_active_build(presentation, 'failed', 'admission.source_review_required') == presentation
    assert overlay_active_build(presentation, 'failed', 'admission.unresolved_source') == presentation
