"""The illustration retains exact holes, finite domains and answer visibility."""
import json
import subprocess

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import parity_parameter_math as math
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import (
    validate_part_graphs,
)
from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_graphs import (
    _graph,
    _instance,
    examples,
)
from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_presentation import (
    compile_cards,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from tests.solver.test_graph_parity_parameter import candidate, description


@pytest.mark.parametrize('expr,prop,facts', [
    ('(x^2-1)^2+m*x', 'even', ()),
    ('(x-m)/(x-m)', 'even', ()),
    ('m/(x^2-2)', 'even', ()),
    ('abs(x+1)+m*abs(x-1)', 'even', ()),
    ('piecewise(-1,x<0,m,x=0,1,x>0)', 'odd', ()),
    ('sqrt(x^2+m)', 'even', ()),
    ('sqrt(m-x^2)', 'odd', ()),
    ('m*x^4+1', 'odd', ('Dom(f)={-1,1}',)),
])
def test_checked_cards_and_graphs_render_without_leaking_answers(expr, prop, facts, tmp_path):
    d = description(candidate(expr, prop, facts=facts, goal_kind='find_range'))
    model = math.solve(d)
    parts = []
    for phase, evidence in [('domain', {}), ('identity', []), ('compare', model['comparison']), ('solve', model), ('verify', model)]:
        values = encode_value({'phase': phase, 'description': d, 'evidence': evidence})
        compiled = compile_cards([{'values': values}], 'test-' + phase)['parts']
        validate_part_graphs(compiled)
        if phase != 'verify':
            assert all('completion_graph' not in p and 'completion_graphs' not in p for p in compiled)
        for part in compiled:
            if part['interaction']['type'] != 'read':
                assert part['stem_board']['items'][1]['math'] is None
        parts += compiled
    target = tmp_path / 'parts.json'
    target.write_text(json.dumps(parts, ensure_ascii=False))
    # Exercise actual shared SVG + KaTeX code against backend-generated shapes.
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-r2-render-check.mjs'), str(target)],
                           check=False, capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr


def test_original_cancelled_hole_is_open_and_not_bridged():
    d = description(candidate('(x-m)/(x-m)'))
    model = math.solve(d)
    x, domain, parts, discrete = _instance(d, model, sp.S.Zero)
    assert domain == sp.S.Reals-sp.FiniteSet(0)
    graph = _graph(d, sp.S.Zero, x, domain, parts, discrete)
    trace = graph['params']['traces'][0]
    assert trace['markers'] == [{'x': 0., 'y': 1., 'closed': False}]
    assert len(trace['segments']) == 2
    assert all(all(x < 0 for x, _ in s) or all(x > 0 for x, _ in s) for s in trace['segments'])


@pytest.mark.parametrize('expr,facts', [
    ('x^2+m*x', ('degree(f)=2',)),
    ('m*x', ('degree(f)=2',)),
    ('x^2+m*x', ('Dom(f)=[-1,1]', 'degree(f)=2')),
    ('m*x', ('Dom(f)=[-1,1]', 'degree(f)=2')),
    ('x^4+m*x', ('degree(f)=4',)),
    ('m*x', ('degree(f)=4',)),
    ('sqrt(m*x^2)', ()),
    ('sqrt(m*x^2+1)', ()),
])
def test_constant_conditions_have_student_wording_on_every_parameter_route(expr, facts):
    d = description(candidate(expr, 'odd', facts=facts))
    model = math.solve(d)
    for phase in ('solve', 'verify'):
        values = encode_value({'phase': phase, 'description': d, 'evidence': model})
        cards = compile_cards([{'values': values}], 'constant-' + phase)['parts']
        displayed = json.dumps(cards, ensure_ascii=False)
        assert r'\text{True}' not in displayed and r'\text{False}' not in displayed


def test_singleton_domain_is_a_point_without_a_fabricated_curve():
    d = description(candidate('sqrt(m-x^2)', 'odd'))
    model = math.solve(d)
    instance = _instance(d, model, sp.S.Zero)
    assert instance[1] == sp.FiniteSet(0)
    trace = _graph(d, sp.S.Zero, *instance)['params']['traces'][0]
    assert trace['segments'] == []
    assert trace['markers'] == [{'x': 0., 'y': 0., 'closed': True}]


def test_mirror_closed_point_cannot_cover_original_hole():
    d = description(candidate('(x-m)/(x-m)'))
    _, graphs = examples(d, math.solve(d))
    rejected = [g for g in graphs if 'm=-1' in g['params']['title']]
    assert len(rejected) == 2
    assert all(len(g['params']['traces']) == 1 for g in rejected)
    assert rejected[0]['params']['bounds'] == rejected[1]['params']['bounds']
    original = rejected[0]['params']['traces'][0]['markers']
    assert {'x': -1., 'y': 1., 'closed': False} in original
