"""Shared child ownership, interval transport and automatic course invalidation."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    execution_contracts,
    interaction,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities import CapabilityGap
from shuxueshuo_server.graph_lesson.stage_three.capabilities.substitution import (
    substitution,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from tests.solver.test_graph_piecewise_range_parameter import candidate
from tests.solver.test_graph_stage_three_methods import candidate as quantified
from tests.solver.test_graph_stage_three_methods import start


def execute(c, method, contracts):
    state = start(c, method)
    for _ in range(180):
        if state['status'] != 'running':
            break
        state = driver.advance(state, contracts=contracts)
    assert state['status'] == 'method_complete', state['diagnostics']
    return state


def test_host_uses_current_child_contract_and_existing_interactions():
    contracts = deepcopy(execution_contracts.load_contracts())
    # Simulate a published child teaching-flow change. Neither caller is edited.
    step = contracts['method-separation']['steps'][1]
    unit = deepcopy(step['display_units'][0])
    unit['id'] = 'updated-quantifier-teaching'
    step['display_units'][0] = unit
    host = execute(candidate(1), 'method-piecewise-range-parameter', contracts)
    direct = execute(quantified('∀x∈(1,∞): a*x^2-x+4>=0'), 'method-separation', contracts)
    child = [f for f in host['fragments'] if f['method_ref'].startswith('method-separation#')]
    assert [(f['method_ref'], f['display_unit']) for f in child] == [
        (f['method_ref'], f['display_unit']) for f in direct['fragments']]
    assert any(f['display_unit'] == unit['id'] for f in child)
    assert driver.export_values(host)['feasible_set'] == sp.Interval(sp.Rational(1, 16), sp.oo)
    seeds = host['interaction_seeds']
    phases = {decode_value(s['values']).get('phase') for s in seeds}
    assert {'recognize', 'select'} <= phases
    assert not {'isolate', 'substitute', 'maximum'} & phases
    chunks, pending = interaction.compile_route(seeds, interaction.load_registry())
    assert not pending
    parts = []
    for chunk, diagnostics in chunks:
        assert chunk['status'] == 'interactive', (chunk, diagnostics)
        interaction.validate_chunk(chunk)
        parts.extend(chunk['parts'])
    recognize = next(p for p in parts if p['title'] == '判断转化后的问题')
    assert [p for p in parts if p.get('source_context')] == [recognize]
    assert '第 2 段函数' in recognize['source_context']
    assert recognize['question'].count(recognize['source_context']) == 1
    assert all('本步条件来自' not in p['question'] for p in parts if p is not recognize)
    assert all('本步条件来自' not in f['explanation']
               and '本步条件来自' not in f.get('highlight', {}).get('caption', '')
               for f in host['fragments'] if f['method_ref'].startswith('method-separation#'))
    assert all('一元二次不等式' in o['label'] for o in recognize['interaction']['options'])
    plane = next(p for p in parts if p['title'] == '选择恒成立问题的解题方法')
    assert plane['interaction']['type'] == 'plane'
    assert plane['expected_answer'] == {'cell': ['interval', 'free'], 'method': 'separation'}
    fixed_part = next(p for p in parts if p['title'] == '先求不含参数那一段函数的值域')
    assert fixed_part['graph'] == fixed_part['completion_graph']
    assert fixed_part['graph']['params']['vertex'] == [0, -2]
    assert fixed_part['graph']['params']['interval'] == [None, 1]
    assert fixed_part['graph']['params']['interval_closed'] == [False, True]
    assert fixed_part['graph']['params']['points'] == [{'x': 1.0}]
    range_part = next(p for p in parts if p['title'] == '求 $h(x)$ 的值域')
    assert 'h(x)=- 4 t^{2} + t' in range_part['question']
    assert 'h(t)' not in range_part['question']
    assert r't\in\left(0, 1\right)' in range_part['question']
    assert range_part['graph'] == range_part['completion_graph']
    assert range_part['graph']['params']['variable'] == 't'
    assert range_part['graph']['params']['coefficient'] == -4
    assert range_part['graph']['params']['vertex'] == [1/8, 1/16]
    assert range_part['graph']['params']['interval_closed'] == [False, False]
    assert range_part['graph']['params']['points'] == [{'x': 0.0, 'open': True}, {'x': 1.0, 'open': True}]
    assert 'h(x)' in range_part['graph']['caption'] and 'h(t)' not in range_part['graph']['caption']
    range_card = next(f for f in child if f['title'] == range_part['title'])
    assert 'h(x)' in range_card['highlight']['items'][1]['math']
    assert r'\frac{1}{16}' in range_card['explanation']
    assert 'h(t)' not in range_card['explanation']
    restore_part = next(p for p in parts if p['title'] == '把取值点换回原变量')
    assert '$h(x)$' in restore_part['question']
    restore_card = next(f for f in child if f['title'] == restore_part['title'])
    assert '$h(x)$' in restore_card['explanation']
    assert '原函数' not in restore_card['explanation']
    child_seeds = [s for s in seeds if s['method_ref'].startswith('method-separation#')]
    assert any(s['template'] == 'policy' for s in child_seeds)
    assert any(s['template'] == 'reciprocal_substitution' for s in child_seeds)
    for s in child_seeds:
        assert '第 2 段函数' in decode_value(s.get('context', {})).get('subproblem_context', '')


@pytest.mark.parametrize(('domain', 'expected'), [
    (sp.Interval.open(1, sp.oo), sp.Interval.open(0, 1)),
    (sp.Interval.Lopen(0, 2), sp.Interval(sp.Rational(1, 2), sp.oo)),
    (sp.Interval.Ropen(-2, 0), sp.Interval(-sp.oo, -sp.Rational(1, 2))),
])
def test_reciprocal_substitution_preserves_open_boundaries(domain, expected):
    x, t = sp.symbols('z u', real=True)
    output = substitution((x-4)/x**2, x, domain, t, 1/x)['outputs']
    assert output['domain'] == expected
    assert sp.expand(output['expression']) == t-4*t**2
    assert output['mapping']['inverse'] == 1/t


def test_reciprocal_substitution_rejects_zero_in_domain():
    x, t = sp.symbols('x t', real=True)
    with pytest.raises(CapabilityGap):
        substitution((x-4)/x**2, x, sp.Interval(-1, 1), t, 1/x)


def test_course_build_refreshes_on_teaching_change_without_copying_child_steps(tmp_path, monkeypatch):
    from tools import refresh_graph_walk_courses as refresh
    recipe = tmp_path/'internal/course.json'
    source = tmp_path/'site/data/graph-walk/demo.source.json'
    evidence = source.with_name('demo.evidence.json')
    recipe.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    recipe.write_text(json.dumps({'problem_id': 'demo'}))
    source.write_text(json.dumps({'problemId': 'demo', 'authoringSource': 'internal/course.json',
                                 'evidence': 'site/data/graph-walk/demo.evidence.json'}))
    version = ['v1']
    monkeypatch.setattr(refresh, 'teaching_revision', lambda: version[0])
    calls = []
    def rebuild(record, recording, target):
        calls.append(record)
        target.write_text(json.dumps({'provenance': {'teaching_revision': version[0],
            'authoring_record_sha256': sha256(record.read_bytes()).hexdigest()}}))
    monkeypatch.setattr(refresh, 'import_course', rebuild)
    name = str(source.relative_to(tmp_path))
    assert refresh.refresh_courses([name], root=tmp_path) == ['demo']
    assert refresh.refresh_courses([name], root=tmp_path) == []
    previous = evidence.read_bytes()
    version[0] = 'v2'
    with pytest.raises(ValueError, match='teaching flow is stale'):
        refresh.refresh_courses([name], root=tmp_path, check=True)
    assert evidence.read_bytes() == previous
    assert refresh.refresh_courses([name], root=tmp_path) == ['demo']
    assert len(calls) == 2
