"""Read-only workspace presentation; never promote a candidate to a Solver revision."""
from sqlalchemy import select

from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    uncertainty_diagnostics,
)

from . import models as m
from .understanding import candidate_state


def original_text_excerpt(candidate):
    """Display only a transcription; never synthesize source wording from IR."""
    excerpt = ' '.join(candidate.get('original_text', '').split())
    return (excerpt[:240] + '…') if len(excerpt) > 240 else excerpt


def understanding_presentation(p, source, candidate, run, config):
    state = candidate_state(p, candidate, run, config)
    result = (run['result_json'] or {}) if run else {}
    diagnostics = [*state['diagnostics'], *uncertainty_diagnostics(candidate['candidate_json'] if candidate else {})]
    reason = None
    if run and run['status'] in ('queued', 'running', 'failed', 'cancelled'):
        status = run['status']
        reason = run['error_code']
    elif any(d.get('code') == 'missing_figure' for d in diagnostics):
        status, reason = 'needs_confirmation', 'missing_figure'
    elif result.get('status') == 'needs_confirmation' or any(d.get('action') == 'needs_confirmation' for d in diagnostics):
        status = 'needs_confirmation'
    elif result.get('status') == 'code_gap' or any(d.get('action') == 'code_gap' for d in diagnostics):
        status = 'code_gap'
    elif run and result.get('status', '').startswith('workflow.'):
        status, reason = 'needs_confirmation', result['status']
    elif candidate and state['parse_status'] != 'valid':
        status = 'needs_revision'
    elif candidate and state['source_reviewed']:
        status = 'unsupported' if state['match_status'] == 'unmatched' else 'ready'
    elif candidate:
        status, reason = 'needs_review', state['source_status']
    else:
        status = 'not_started'
    excerpt = original_text_excerpt(candidate['candidate_json']) if candidate else ''
    return {
        'title': excerpt or p['title'] or ('原题文字待提取' if candidate else '待提取题目'),
        'title_kind': 'source_text' if excerpt else 'image',
        'image_source_id': source['images'][0]['source_id'],
        'phase': 'understanding', 'status': status, 'reason': reason,
        'result_id': str(run['id']) if run and status in ('ready', 'unsupported', 'needs_confirmation') else None,
    }


def problem_presentations(c, records, legacy):
    """Batch current pointers; query cost is independent of the number of problems."""
    def indexed(table, field):
        ids = [p[field] for p in records if p[field]]
        return {r['id']: r for r in c.execute(select(table).where(table.c.id.in_(ids))).mappings()} if ids else {}

    sources = indexed(m.problem_source_versions, 'current_source_version_id')
    candidates = indexed(m.problem_candidates, 'current_candidate_id')
    runs = indexed(m.extraction_runs, 'latest_extraction_run_id')
    config = None
    if sources:
        from .understanding_runtime import configuration
        config = configuration()
    presentations = {}
    for p in records:
        details = legacy[p['id']]
        source = sources.get(p['current_source_version_id'])
        candidate = candidates.get(p['current_candidate_id'])
        run = runs.get(p['latest_extraction_run_id'])
        # Only the current source may supply the candidate and its status.
        if candidate and candidate['source_version_id'] != p['current_source_version_id']:
            candidate = None
        if run and (run['source_version_id'] != p['current_source_version_id'] or run['generation'] != p['understanding_generation']):
            run = None
        activity_time = max(item['created_at'] for item in (source, candidate, run) if item) if source else None
        if source and (not details['build_created_at'] or activity_time >= details['build_created_at']):
            presentations[p['id']] = understanding_presentation(p, source, candidate, run, config)
        else:
            from .application import statement_text
            statement = statement_text(details['domain_json'])
            status = details['status'] or 'not_started'
            if status == 'succeeded':
                status = 'ready'
            presentations[p['id']] = {
                'title': statement or p['title'] or '待提取题目',
                'title_kind': 'source_text' if statement else 'image',
                'image_source_id': str(p['primary_source_id']),
                'phase': 'generation' if p['latest_build_id'] else 'upload',
                'status': status, 'reason': None,
                'result_id': str(p['current_page_build_id']) if status == 'ready' and p['current_page_build_id'] else None,
            }
    return presentations
