"""Validate the authored next graph, then atomically publish current public content."""

import json
import re
import subprocess
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from ..product import models
from ..product.db import canonical, digest, lock, transaction

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY_KINDS = {'knowledge', 'skill', 'method', 'problem_type'}
KINDS = CAPABILITY_KINDS | {'textbook', 'chapter', 'section', 'collection', 'judgment_rule'}
KEYS = {
    'knowledge_nodes': ['id'],
    'knowledge_entries': ['node_id', 'entry_id'],
    'knowledge_edges': ['source_id', 'target_id', 'relation_type'],
    'knowledge_resources': ['id'],
    'practice_topics': ['id'],
    'practice_problems': ['id'],
    'practice_topic_problems': ['topic_id', 'problem_id'],
    'practice_problem_types': ['problem_id', 'node_id'],
    'practice_routes': ['problem_id', 'route_id'],
    'practice_steps': ['problem_id', 'route_id', 'step_id'],
    'practice_step_nodes': ['problem_id', 'route_id', 'step_id', 'node_id'],
    'knowledge_drill_items': ['item_id'],
}
WRITE_KEYS = {**KEYS, 'learning_content_current': ['id']}
TABLES = {name: models.metadata.tables[name] for name in WRITE_KEYS}
REPLACE_RELATIONS = {'knowledge_edges', 'practice_topic_problems', 'practice_problem_types', 'practice_step_nodes'}


def encoded(value):
    return canonical(value)


def validate_graph(nodes, edges):
    """Guard direct Python publishing callers as well as Node-validated exports."""
    by_id = {}
    for node in nodes:
        if node['id'] in by_id:
            raise ValueError('duplicate nodes')
        kind, subtype = node['kind'], node.get('subtype')
        if kind not in KINDS or (kind == 'judgment_rule' and subtype not in {'method_selection', 'step_selection'}) or (kind != 'judgment_rule' and subtype is not None):
            raise ValueError('invalid node kind/subtype')
        body = node.get('body', {})
        status = body.get('status', 'active')
        if status not in {'active', 'planned', 'knowledge_only'}:
            raise ValueError('invalid node lifecycle')
        if body and (body.get('id') != node['id'] or body.get('kind') != kind):
            raise ValueError('node body identity mismatch')
        if status == 'planned':
            if kind != 'problem_type' or any(body.get(key) != [] for key in ('methods', 'rules', 'examples')):
                raise ValueError('planned problem type cannot expose executable routes or examples')
            if not body.get('knowledge') or not body.get('features'):
                raise ValueError('planned problem type requires knowledge and features')
        if status == 'knowledge_only' and (kind != 'knowledge' or body.get('examples') != [] or not body.get('entries')):
            raise ValueError('knowledge-only node requires substantive entries without examples')
        if body and status == 'active':
            if kind in CAPABILITY_KINDS | {'judgment_rule'} and (not isinstance(body.get('examples'), list) or not body['examples']):
                raise ValueError('active capability requires examples')
            if kind == 'problem_type' and not (body.get('methods') or body.get('rules')):
                raise ValueError('active problem type requires a method entry')
        by_id[node['id']] = node
    seen, adjacency = set(), {node: [] for node in by_id}
    for edge in edges:
        a, b, relation = edge['source_id'], edge['target_id'], edge['relation_type']
        if a not in by_id or b not in by_id or a == b:
            raise ValueError('invalid edge endpoint')
        ak, bk = by_id[a]['kind'], by_id[b]['kind']
        valid = {
            'contains': (ak == 'textbook' and bk == 'chapter') or (ak == 'chapter' and bk == 'section') or (ak == 'section' and bk in CAPABILITY_KINDS) or (ak == 'collection' and bk == 'knowledge'),
            'extends': ak == 'section' and bk in CAPABILITY_KINDS,
            'prerequisite': ak == bk == 'knowledge',
            'involves': ak == 'problem_type' and bk == 'knowledge',
            'candidate': ak == 'problem_type' and bk == 'method',
            'method_rule': ak == 'problem_type' and bk == 'judgment_rule' and by_id[b].get('subtype') == 'method_selection',
            'calls': ak == 'method' and bk in {'method', 'skill'},
            'step_rule': ak == 'method' and bk == 'judgment_rule' and by_id[b].get('subtype') == 'step_selection',
            'selects': ak == 'judgment_rule' and (bk == 'method' or (by_id[a].get('subtype') == 'step_selection' and bk == 'skill')),
            'uses': ak == 'skill' and bk == 'knowledge',
        }.get(relation, False)
        if by_id[a].get('body', {}).get('status') == 'planned' and relation in {'candidate', 'method_rule'}:
            raise ValueError('planned problem type cannot expose method edges')
        if not valid:
            raise ValueError('invalid edge types')
        key = (a, b, relation)
        if key in seen:
            raise ValueError('duplicate edge')
        seen.add(key)
        if relation == 'prerequisite':
            adjacency[a].append(b)
    active, visited = set(), set()

    def visit(node):
        if node in active:
            raise ValueError('prerequisite cycle')
        if node in visited:
            return
        active.add(node)
        for child in adjacency[node]:
            visit(child)
        active.remove(node)
        visited.add(node)

    for node in by_id:
        visit(node)
    return {key: node['kind'] for key, node in by_id.items()}


def load_content(root=ROOT):
    """No generated HTML or legacy graph is involved; stdout stays private."""
    root = Path(root)
    try:
        result = subprocess.run(
            ['node', str(root / 'tools/export-public-knowledge.mjs')],
            cwd=root, capture_output=True, text=True, check=True,
        )
        rows = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        raise ValueError(f'Public learning content export failed: {detail}') from error
    validate_content(rows)
    return rows


def selector_leaves(tree, conditions=None):
    conditions = conditions or {}
    if isinstance(tree, dict) and 'field' in tree:
        field, options = tree['field'], tree.get('options')
        if not isinstance(field, str) or field in conditions or not isinstance(options, dict) or not options:
            raise ValueError('invalid conditional association')
        for option, child in options.items():
            yield from selector_leaves(child, {**conditions, field: option})
    else:
        yield conditions, tree


def validate_content(rows):
    types = validate_graph(rows['knowledge_nodes'], rows['knowledge_edges'])
    if set(rows) != set(KEYS) | {'_meta'}:
        raise ValueError('incomplete public content export')
    for name, keys in KEYS.items():
        for row in rows[name]:
            validate_row(name, row, keys)
    entries = {(e['node_id'], e['entry_id']) for e in rows['knowledge_entries']}
    resources = {r['id']: r['body'] for r in rows['knowledge_resources']}

    def reference(ref, kinds=CAPABILITY_KINDS):
        if not isinstance(ref, str) or not re.fullmatch(r'[a-z][a-z0-9-]*(?:#[a-z][a-z0-9-]*)?', ref):
            raise ValueError(f'invalid reference: {ref}')
        node, _, entry = ref.partition('#')
        if types.get(node) not in kinds or (entry and (node, entry) not in entries):
            raise ValueError(f'invalid reference: {ref}')

    for name, keys in KEYS.items():
        identities = [tuple(row[key] for key in keys) for row in rows[name]]
        if len(identities) != len(set(identities)):
            raise ValueError(f'duplicate identities: {name}')
    for node, _ in entries:
        if node not in types:
            raise ValueError('entry references removed node')
    for row in rows['knowledge_entries']:
        refs = row['body'].get('references')
        if refs is not None:
            if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs):
                raise ValueError('invalid entry references')
            for ref in refs:
                reference(ref, {'knowledge'})
    for edge in rows['knowledge_edges']:
        for occurrence in edge['occurrences']:
            if occurrence.get('entry'):
                reference(edge['target_id'] + '#' + occurrence['entry'])
            for key in ('step', 'branch'):
                if occurrence.get(key) and (edge['source_id'], occurrence[key]) not in entries:
                    raise ValueError('edge occurrence references removed entry')
    topics = {row['id'] for row in rows['practice_topics']}
    problems = {row['id'] for row in rows['practice_problems']}
    routes = {(row['problem_id'], row['route_id']) for row in rows['practice_routes']}
    steps = {(row['problem_id'], row['route_id'], row['step_id']) for row in rows['practice_steps']}
    from .graph_walk import route_steps, validate_contract
    for problem in rows['practice_problems']:
        contract = problem['problem_data'].get('_graph_walk')
        if contract is not None:
            validate_contract(contract, problem['id'])
            expected = {(problem['id'], route, step['id']) for route in contract['routes'] for step in route_steps(contract, route)}
            if expected != {step for step in steps if step[0] == problem['id']}:
                raise ValueError('graph-walk grading steps differ from published associations')
    for row in rows['practice_topic_problems']:
        if row['topic_id'] not in topics or row['problem_id'] not in problems:
            raise ValueError('topic membership references removed content')
    planned_types = {node['id'] for node in rows['knowledge_nodes'] if node.get('body', {}).get('status') == 'planned'}
    for row in rows['practice_problem_types']:
        if row['node_id'] in planned_types:
            raise ValueError('practice problem cannot publish a planned type')
        if row['problem_id'] not in problems:
            raise ValueError('problem type references removed problem')
        reference(row['node_id'], {'problem_type'})
    for route in rows['practice_routes']:
        if route['problem_id'] not in problems:
            raise ValueError('route references removed problem')
        for _, refs in selector_leaves(route['methods']):
            if not isinstance(refs, list) or not refs:
                raise ValueError('route requires methods')
            for ref in refs:
                reference(ref, {'method'})
                if '#' in ref:
                    raise ValueError('route requires whole method')
    for step in rows['practice_steps']:
        if (step['problem_id'], step['route_id']) not in routes:
            raise ValueError('step references removed route')
        refs = list(selector_leaves(step['refs']))
        for _, values in refs:
            if not isinstance(values, list) or (not values and not step.get('reason')):
                raise ValueError('invalid step references')
            for ref in values:
                reference(ref, {'knowledge', 'skill', 'method'})
        if step['tip']:
            for conditions, tip in selector_leaves(step['tip']):
                reference(tip['ref'], {'knowledge', 'skill', 'method'})
                compatible = [values for c, values in refs if all(k not in conditions or conditions[k] == v for k, v in c.items())]
                if not compatible or any(tip['ref'] not in values for values in compatible):
                    raise ValueError('tip missing from current step association')
                if tip.get('resource'):
                    resource = resources.get(tip['resource'])
                    if resource is None or (tip.get('case') and tip['case'] not in resource.get('cases', [])):
                        raise ValueError('invalid tip resource/case')
    for row in rows['practice_step_nodes']:
        if (row['problem_id'], row['route_id'], row['step_id']) not in steps:
            raise ValueError('step reference has missing step')
        reference(row['node_id'])
    for item in rows['knowledge_drill_items']:
        reference(item['node_id'] + ('#' + item['entry_id'] if item['entry_id'] else ''))
        options = [o['value'] for o in item['options']]
        selected = item['answer_spec']['selected']
        if item['question_type'] not in {'choice', 'multi'} or len(set(options)) != len(options) or len(options) < 2 or not selected or len(set(selected)) != len(selected) or not set(selected) <= set(options) or (item['question_type'] == 'choice' and len(selected) != 1):
            raise ValueError('invalid drill grading contract')
        if any(not o.get('feedback') for o in item['options'] if o['value'] not in selected):
            raise ValueError('drill distractor has no feedback')
    meta = rows['_meta']
    if meta['schema_version'] != 2 or meta['content_version'] != digest({name: rows[name] for name in KEYS}):
        raise ValueError('content version does not match authored rows')
    return types


def validate_row(name, row, keys):
    """Only authored content tables and their declared columns may be written."""
    if name not in TABLES or keys != WRITE_KEYS[name]:
        raise ValueError(f'invalid public content table or key: {name}')
    table = TABLES[name]
    if not isinstance(row, dict) or not set(keys) <= set(row) or not set(row) <= set(table.c.keys()):
        raise ValueError(f'invalid public content fields: {name}')
    return table


def _write(c, name, row, keys):
    table = validate_row(name, row, keys)
    statement = insert(table).values(**row)
    updates = {field: statement.excluded[field] for field in row if field not in keys}
    statement = (statement.on_conflict_do_update(index_elements=keys, set_=updates) if updates
                 else statement.on_conflict_do_nothing(index_elements=keys))
    c.execute(statement)


def publish(db, rows):
    """Use one publish lock and transaction, or join a caller-owned rebuild transaction."""
    validate_content(rows)
    context = nullcontext(db) if isinstance(db, Connection) else transaction(db)
    with context as c:
        lock(c, 'learning.publish')
        old = {name: [dict(row) for row in c.execute(text(f'SELECT * FROM {name}')).mappings()] for name in KEYS}
        for name, items in rows.items():
            if name not in KEYS:
                continue
            keys = KEYS[name]
            previous = {tuple(row[key] for key in keys): row for row in old[name]}
            for row in items:
                existing = previous.get(tuple(row[key] for key in keys))
                if not existing:
                    continue
                if name == 'practice_problems' and existing['contract_hash'] != row['contract_hash']:
                    from .compatibility import teaching_contract
                    # Source hashes may change for wording fixes. Grading and
                    # step semantics still require a new course identity.
                    if (existing['problem_data'] == row['problem_data'] or
                            teaching_contract(existing['problem_data']) != teaching_contract(row['problem_data'])):
                        raise ValueError(f"{row['id']}: teaching contract changed; allocate a new ID")
                if name == 'knowledge_nodes' and (existing['kind'], existing['subtype']) != (row['kind'], row['subtype']):
                    raise ValueError(f"{row['id']}: node identity changed")
        route_hashes = {(row['problem_id'], row['route_id']): row['association_hash'] for row in rows['practice_routes']}
        for route in old['practice_routes']:
            key = (route['problem_id'], route['route_id'])
            if route_hashes.get(key) != route['association_hash']:
                c.execute(text("UPDATE student_practice_attempts SET status='closed',updated_at=clock_timestamp() WHERE problem_id=:problem_id AND route_id=:route_id AND status='in_progress'"), route)
        item_targets = {row['item_id']: (row['node_id'], row['entry_id'], row['content_hash']) for row in rows['knowledge_drill_items']}
        old_targets = {row['item_id']: (row['node_id'], row['entry_id'], row['content_hash']) for row in old['knowledge_drill_items'] if row['is_active']}
        changed_nodes = set()
        for item in item_targets.keys() | old_targets.keys():
            if item_targets.get(item) != old_targets.get(item):
                for target in (item_targets.get(item), old_targets.get(item)):
                    if target:
                        changed_nodes.add(target[0])
        for node in changed_nodes:
            c.execute(text("UPDATE knowledge_drill_attempts SET status='closed',updated_at=clock_timestamp() WHERE node_id=:node AND status='in_progress'"), {'node': node})
        # Relations are a current projection. Historical evidence uses attempt snapshots.
        for name in REPLACE_RELATIONS:
            keep = {tuple(row[key] for key in KEYS[name]) for row in rows[name]}
            for row in old[name]:
                if tuple(row[key] for key in KEYS[name]) not in keep:
                    where = ' AND '.join(f'{key}=:{key}' for key in KEYS[name])
                    c.execute(text(f'DELETE FROM {name} WHERE {where}'), row)
        for name, keys in KEYS.items():
            for row in rows[name]:
                _write(c, name, row, keys)
            if name not in REPLACE_RELATIONS:
                keep = {tuple(row[key] for key in keys) for row in rows[name]}
                for row in old[name]:
                    if tuple(row[key] for key in keys) not in keep:
                        where = ' AND '.join(f'{key}=:{key}' for key in keys)
                        c.execute(text(f'UPDATE {name} SET is_active=false WHERE {where}'), row)
        meta = rows['_meta']
        # Repeating a publication must not rewrite its original published_at.
        c.execute(text('INSERT INTO learning_content_releases(content_version,schema_version,counts) VALUES(:content_version,:schema_version,CAST(:counts AS jsonb)) ON CONFLICT DO NOTHING'),
                  {**meta, 'counts': encoded(meta['counts'])})
        _write(c, 'learning_content_current', {'id': 'public', 'content_version': meta['content_version']}, ['id'])
    return {name: len(rows[name]) for name in KEYS}
