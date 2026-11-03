"""Per-exercise compatibility, separate from the deployment release checksum."""

from fastapi import HTTPException
from sqlalchemy import text

from ..product.db import digest

DECORATIVE = {'note', 'hint', 'description', 'title', 'caption', 'method_notes'}
FIELDS = ('id', 'question', 'interaction', 'expected_answer', 'route_by_answer',
          'route_id', 'option_context', 'target_ref', 'require_complete_options',
          'select_relation', 'matching', 'alternatives', 'verdicts')


def inputs(value):
    if isinstance(value, list):
        return [inputs(item) for item in value]
    if isinstance(value, dict):
        return {key: inputs(item) for key, item in value.items() if key not in DECORATIVE}
    return value


def decision(value):
    result = {key: inputs(value[key]) if key == 'interaction' else value[key]
              for key in FIELDS if key in value}
    if not value.get('alternatives'):
        result.pop('alternatives', None)
    if value['interaction'].get('layout') != 'connections':
        result.pop('verdicts', None)
    if value.get('source') == 'original_choice' and (
            value['interaction']['type'] == 'original_choice_exact_set' or value.get('require_complete_options') or
            value.get('matching') in ('set_equality', 'range_domain_options')):
        result['source'] = value['source']
    return result


def page_contract(lesson, statement=None):
    native = bool(lesson.get('problemId'))
    return {'schema': 'practice-page/v1', 'id': lesson.get('problemId') or lesson['id'],
            'runtime': 'graph-walk' if native else 'practice',
            **({'statement': statement or lesson.get('problem', {}).get('text'),
                'intro': [decision(item) for item in lesson['intro']]} if native else {}),
            'routes': {key: [decision(item) for item in (
                route['steps'] if native else route if isinstance(route, list) else route['nodes'])]
                for key, route in lesson['routes'].items()}}


def teaching_contract(data):
    lesson = data.get('_graph_walk') or data['_lesson']
    page = page_contract(lesson, data.get('statement'))
    if data.get('_graph_walk'):
        return {'page': page}
    return {'page': page, 'problem': lesson['problem'],
            **({'initial_state': lesson['initial_state']} if 'initial_state' in lesson else {}),
            'criteria': {key: [{field: node[field] for field in ('required_evidence', 'criteria') if field in node}
                               for node in route['nodes']] for key, route in lesson['routes'].items()}}


def metadata(problem):
    data = problem['problem_data']
    page_hash = digest(page_contract(data.get('_graph_walk') or data['_lesson'], data.get('statement')))
    return {'id': problem['id'], 'page_contract_hash': page_hash,
            'practice_version': digest({'schema': 'practice-compatibility/v1',
                                        'teaching': teaching_contract(data),
                                        'associations': problem['association_hash']})}


def published(c, pid):
    row = c.execute(text('SELECT * FROM practice_problems WHERE id=:id AND is_active'),
                    {'id': pid}).mappings().first()
    if not row:
        raise HTTPException(404, '本题尚未发布或已更新，仍可在当前页面练习。')
    return row


def require_problem(c, pid, requested):
    problem = published(c, pid)
    if requested != metadata(problem)['practice_version']:
        raise HTTPException(409, {'code': 'practice_content_changed',
                                 'message': '本题的步骤、作答规则或能力关联已更新，请刷新本题后再保存。'})
    return problem


def require_attempt(c, attempt, requested):
    problem = require_problem(c, attempt['problem_id'], requested)
    # Records always use their original contract. Do not restore an old answer
    # into a changed page, even if its step IDs happen to be the same.
    if teaching_contract(attempt['problem_context']) != teaching_contract(problem['problem_data']):
        raise HTTPException(409, '本题的作答规则已更新，原练习记录仍保留。')
    current = c.execute(text('SELECT association_hash FROM practice_routes WHERE problem_id=:p AND route_id=:r AND is_active'),
                        {'p': attempt['problem_id'], 'r': attempt['route_id']}).scalar()
    if current != attempt['association_hash']:
        raise HTTPException(409, '本题路线的能力关联已更新，原练习记录仍保留。')
