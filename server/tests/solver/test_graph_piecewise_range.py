"""FR-T3 P3: exact output unions, source boundaries and the student course."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson import piecewise_range as pr
from shuxueshuo_server.graph_lesson.stage_one.function_range import inspect_range_target
from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three import function_range as fr
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.piecewise_range_presentation import (
    compile_union,
)
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


def candidate(definition=None):
    c = json.loads((ROOT/'internal/senior-high/authored-courses/piecewise-p3-20261102/b11.json').read_text())['candidate']
    if definition:
        c['root']['definitions'] = [definition]
    return c


def calculate(c):
    context = build_context(c, TARGET)
    assert fr.admitted(context, pr.METHOD), context
    rows = []
    for case in pr.prepare_piecewise_range(context)['outputs']['branch_cases']:
        values = pr.bind_piecewise_range(case)['outputs']
        result = fr.polynomial_image(values['function'], values['variable'], values['domain'])['outputs']
        rows.append({'branch': values['branch'], 'image': result['feasible_set']})
    result = pr.merge_piecewise_range(context, rows)['outputs']['feasible_set']
    return context, {'description': context['range_goal'], 'branch_results': rows, 'feasible_set': result}


def test_b11_output_union_and_endpoint_witnesses_are_source_bound(monkeypatch):
    c = candidate(); context, data = calculate(c)
    assert [r['image'] for r in data['branch_results']] == [sp.Interval(-1, 3), sp.Interval.Ropen(0, 3)]
    assert data['feasible_set'] == sp.Interval(-1, 3)
    monkeypatch.setattr(fr, 'polynomial_image', lambda *_: pytest.fail('verifier must recompute from source'))
    assert fr.independent_verify(c, TARGET, context, data['feasible_set'])['status'] == 'verified'
    for bad in [sp.Interval.Ropen(-1, 3), sp.Interval(0, 3), sp.Interval(-1, sp.oo)]:
        assert fr.independent_verify(c, TARGET, context, bad)['status'] == 'math_failed'
    from shuxueshuo_server.graph_lesson.stage_three.capabilities import LocalCheckFailed
    bad_rows = deepcopy(data['branch_results']); bad_rows[0]['image'] = sp.Interval(-1, 4)
    with pytest.raises(LocalCheckFailed, match='piece_image_mismatch'):
        pr.merge_piecewise_range(context, bad_rows)
    altered = deepcopy(c); altered['root']['definitions'][0] = altered['root']['definitions'][0].replace('0<=x', '0<x')
    assert fr.independent_verify(altered, TARGET, context, data['feasible_set'])['status'] == 'math_failed'
    endpoints = fr.image_endpoints(c, TARGET, data['feasible_set'])
    assert endpoints['status'] == 'passed'
    high = next(row for row in endpoints['points'] if row['point']['expression'] == '3')
    assert high['evidence']['legal_preimages'] == [{'branch': 1, 'input': {'expression': '0', 'latex': '0'}}]


@pytest.mark.parametrize(('definition', 'expected'), [
    ('f(x)=piecewise(x,x<0,x+2,x>=0)', sp.Interval.open(-sp.oo, 0)|sp.Interval(2, sp.oo)),
    ('f(x)=piecewise(5,x<0,5,x>0)', sp.FiniteSet(5)),
    ('f(x)=piecewise(x^2,-2<=x ∧ x<2,x,x>=2)', sp.Interval(0, sp.oo)),
    ('f(x)=piecewise(x^2,0<x ∧ x<1,4,2<=x ∧ x<=3)', sp.Interval.open(0, 1)|sp.FiniteSet(4)),
])
def test_gaps_constants_open_ends_and_shared_outputs(definition, expected):
    c = candidate(definition); context, data = calculate(c)
    assert data['feasible_set'] == expected
    assert fr.independent_verify(c, TARGET, context, expected)['status'] == 'verified'
    assert fr.image_endpoints(c, TARGET, expected)['status'] == 'passed'
    with pytest.raises(Exception, match='missing_piece'):
        pr.merge_piecewise_range(context, data['branch_results'][:-1])


def test_input_restrictions_skip_empty_pieces_and_do_not_clip_outputs():
    c = candidate(); c['root']['goals'][0]['input_domain'] = '[1,2]'
    context, data = calculate(c)
    assert len(data['branch_results']) == 1
    assert data['feasible_set'] == sp.Interval(-1, 0)
    assert fr.process_context(context, data['feasible_set'])[0] == data['feasible_set']
    assert fr.independent_verify(c, TARGET, context, data['feasible_set'])['status'] == 'verified'


@pytest.mark.parametrize('definition', [
    'f(x)=piecewise(x,x<=0,x^2,x>=0)',
    'f(x)=piecewise(1/x,x<0,x,x>=0)',
    'f(x)=piecewise(x^3,x<0,x,x>=0)',
])
def test_unsupported_structure_is_rejected(definition):
    assert not inspect_range_target(candidate(definition), TARGET)['structure_supported']


def test_conflicting_domains_extra_conditions_and_uncertain_sources_are_rejected():
    for field, value in [('facts', 'Dom(f)=ℝ'), ('facts', 'x>0'),
                         ('uncertainties', {'kind': 'ambiguous_symbol', 'text': '端点不清'})]:
        c = candidate(); c['root'].setdefault(field, []).append(value)
        assert not inspect_range_target(c, TARGET)['structure_supported']


def test_source_reading_direct_method_and_aligned_output_number_lines():
    c = candidate(); features = candidate_features(c)
    assert features['ok'], features['diagnostics']
    read = build_d1(c, TARGET, features['features'], {'items': []})
    assert not read['diagnostics'], read
    bad = deepcopy(c); bad['original_text'] = bad['original_text'].replace(r'0\le x\le3', r'0<x\le3')
    assert build_d1(bad, TARGET, features['features'], {'items': []})['diagnostics']
    selected = evaluate_goal(c, TARGET, features['features'], 'type-function-range')
    assert selected['d4']['options'][0]['method'] == pr.METHOD
    assert selected['d3']['title'] == '解题方法'
    assert selected['d3']['interaction'] == {'type': 'read'} and selected['selection']['rule'] is None
    assert selected['d3'].get('prerequisites') == []
    _, data = calculate(c)
    part = compile_union([{'values': encode_value(data)}], 'a'*24)['parts'][0]
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'}).validate(part)
    lines = [*part['condition_number_lines'], part['completion_number_line']]
    assert all(row['variable'] == 'y' for row in lines)
    assert all(row['bounds'] == lines[0]['bounds'] and row['ticks'] == lines[0]['ticks'] for row in lines)
    assert part['stem_board']['items'][1]['math'] is None
    assert 'f(0)=3' in part['feedback']['answer']


def test_b11_native_course_completes(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_three import runner
    from tests.solver.test_graph_stage_three_execution import constructed_upstream
    from tools.export_graph_walk_course import export_course
    output = tmp_path/'run'
    result = runner.run_sample(constructed_upstream(tmp_path, candidate()), output)
    assert result['status'] == 'completed' and result['goals'][0]['status'] == 'solved', result
    assert sp.sympify(result['goals'][0]['answer']['set']['expression']) == sp.Interval(-1, 3)
    course = export_course(output, 'function-representations-b11')
    goal = course['lesson']['goals'][0]
    assert goal['walk'] is not None
    assert not goal['d1'].get('diagnostics')
