"""FM-T1: exact interval families, bounded admission, source binding and shared UI."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.function_monotonicity import describe, solve, verify
from shuxueshuo_server.graph_lesson.stage_three.monotonicity_presentation import (
    compile_monotonicity,
    graph_for,
    phase_views,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.learning.graph_walk import grade

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


def goal(expr, **kw):
    return {'kind': 'find_monotonic_intervals', 'expression': expr, 'variable': 'x', 'direction': 'both', **kw}


@pytest.mark.parametrize('expr,domain,inc,dec', [
    ('-x^2+2*abs(x)+3', 'ℝ', [sp.Interval(-sp.oo, -1), sp.Interval(0, 1)], [sp.Interval(-1, 0), sp.Interval(1, sp.oo)]),
    ('sqrt(-2*x^2+x+6)', 'ℝ', [sp.Interval(-sp.Rational(3, 2), sp.Rational(1, 4))], [sp.Interval(sp.Rational(1, 4), 2)]),
    ('-x^2+4*x+3', '[0,3]', [sp.Interval(0, 2)], [sp.Interval(2, 3)]),
    ('1/sqrt(x^2-5*x-6)', 'ℝ', [sp.Interval.open(-sp.oo, -1)], [sp.Interval.open(6, sp.oo)]),
    ('sqrt(x^2-2*x-3)', 'ℝ', [sp.Interval(3, sp.oo)], [sp.Interval(-sp.oo, -1)]),
    ('sqrt(-x^2+4*x-3)', 'ℝ', [sp.Interval(1, 2)], [sp.Interval(2, 3)]),
    ('2*x+abs(x)', 'ℝ', [sp.Interval(-sp.oo, sp.oo)], []),
    ('x+abs(x)', 'ℝ', [sp.Interval(0, sp.oo)], []),
    ('abs(-2*x+4)', 'ℝ', [sp.Interval(2, sp.oo)], [sp.Interval(-sp.oo, 2)]),
    ('-abs(x)', 'ℝ', [sp.Interval(-sp.oo, 0)], [sp.Interval(0, sp.oo)]),
    ('x^2+0*abs(x)', '(0,3)', [sp.Interval.open(0, 3)], []),
    ('x+abs(0)', 'ℝ', [sp.Interval(-sp.oo, sp.oo)], []),
    ('-3*x+2', '(-1,2]', [], [sp.Interval.Lopen(-1, 2)]),
    ('sqrt(x^2)', 'ℝ', [sp.Interval(0, sp.oo)], [sp.Interval(-sp.oo, 0)]),
    ('1/sqrt(x^2)', 'ℝ', [sp.Interval.open(-sp.oo, 0)], [sp.Interval.open(0, sp.oo)]),
    ('4', 'ℝ', [], []), ('sqrt(4)', 'ℝ', [], []), ('1/sqrt(4)', '[0,1]', [], []),
])
def test_exact_interval_families_and_degenerate_branches(expr, domain, inc, dec):
    d = describe(goal(expr, input_domain=domain), TARGET)
    m = solve(d)
    assert m['increasing_intervals'] == inc
    assert m['decreasing_intervals'] == dec
    assert verify(d, m)
    assert sp.Union(*(r['interval'] for r in m['partition'])) == m['effective_domain']


def test_verifier_rechecks_original_source_and_maximal_strict_intervals(monkeypatch):
    d = describe(goal('-x^2+2*abs(x)+3'), TARGET)
    m = solve(d)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_monotonicity.solve', lambda *_: pytest.fail('solver called by verifier'))
    assert verify(d, m)
    for field, bad in [('increasing_intervals', [sp.Interval(-sp.oo, 1)]),
                       ('increasing_intervals', [sp.Interval(-sp.oo, -1)]),
                       ('increasing_intervals', [sp.Interval(-sp.oo, -2), sp.Interval(0, 1)]),
                       ('effective_domain', sp.Interval(-4, 4)), ('expression', m['expression']+1)]:
        assert not verify(d, {**m, field: bad})
    bad = deepcopy(m); bad['partition'][0]['direction'] *= -1
    assert not verify(d, bad)
    bad = deepcopy(m); bad['partition'][1]['interval'] = sp.Interval.open(-1, 0)
    assert not verify(d, bad)
    bad = deepcopy(m); bad['junctions'][0]['merge'] = True
    assert not verify(d, bad)
    bad = deepcopy(m); bad['branches'][0]['coefficients'][0] = 1
    assert not verify(d, bad)


@pytest.mark.parametrize('expr,inc,dec', [
    ('piecewise(-x,x<0,x,x>=0)', [sp.Interval(0, sp.oo)], [sp.Interval(-sp.oo, 0)]),
    ('piecewise(x,x<0,-x,x>=0)', [sp.Interval(-sp.oo, 0)], [sp.Interval(0, sp.oo)]),
    ('piecewise(x,x<0,-x-1,x>=0)', [sp.Interval.open(-sp.oo, 0)], [sp.Interval(0, sp.oo)]),
    ('piecewise(x,x<0,-x+1,x>=0)', [sp.Interval(-sp.oo, 0)], [sp.Interval(0, sp.oo)]),
    ('piecewise(-x,x<=0,x,x>0)', [sp.Interval(0, sp.oo)], [sp.Interval(-sp.oo, 0)]),
    ('piecewise(-x,x<0,x,x>0)', [sp.Interval.open(0, sp.oo)], [sp.Interval.open(-sp.oo, 0)]),
])
def test_explicit_piecewise_maximal_intervals_check_the_actual_junction_value(expr, inc, dec):
    d = describe(goal(expr), TARGET)
    m = solve(d, 'piecewise')
    assert m['increasing_intervals'] == inc
    assert m['decreasing_intervals'] == dec
    assert verify(d, m)
    for key in ('increasing_intervals', 'decreasing_intervals'):
        region = m[key][0]
        altered = deepcopy(m)
        altered[key] = [sp.Interval(region.inf, region.sup,
                                   left_open=not region.left_open if region.inf.is_finite else True,
                                   right_open=not region.right_open if region.sup.is_finite else True)]
        assert not verify(d, altered)


def test_equal_constant_pieces_merge_but_distinct_constants_do_not():
    for expr, expected in [('piecewise(1,x<0,1,x>=0)', [sp.Interval(-sp.oo, sp.oo)]),
                           ('piecewise(1,x<0,2,x>=0)', [sp.Interval.open(-sp.oo, 0), sp.Interval(0, sp.oo)])]:
        d = describe(goal(expr), TARGET)
        m = solve(d, 'piecewise')
        assert m['constant_intervals'] == expected
        assert verify(d, m)


def test_composite_proof_requires_the_outer_domain_and_every_direction():
    d = describe(goal('1/sqrt(x^2-5*x-6)'), TARGET); m = solve(d)
    assert [r['direction'] for r in m['partition']] == [1, -1]
    bad = deepcopy(m); bad['partition'][0]['layers'][1]['after'] = -1
    assert not verify(d, bad)
    bad = deepcopy(m); bad['partition'][0]['layers'][1]['input_sign'] = 'unknown'
    assert not verify(d, bad)
    bad = deepcopy(m); bad['partition'][0]['interval'] = sp.Interval(-sp.oo, -1)
    assert not verify(d, bad)


@pytest.mark.parametrize('expr', ['x^3', 'a*x^2+1', 'abs(x^2-1)', 'abs(x)+abs(x-1)',
                                  'x*abs(x)', 'sqrt(x)+x', '1/x', '(x^2-1)/(x-1)',
                                  'sqrt(x^2-2)', '1/sqrt(0)', 'sqrt(-1)'])
def test_unsupported_structures_or_empty_domains_do_not_produce_a_success(expr):
    d = describe(goal(expr), TARGET)
    if d['structure_supported']:
        with pytest.raises(ValueError):
            solve(d)
    else:
        assert d['reason']


def test_declared_domain_cannot_silently_intersect_away_invalid_inputs():
    d = describe(goal('sqrt(x)', input_domain='[-1,1]', domain_role='declared'), TARGET)
    with pytest.raises(ValueError, match='declared_domain_conflict'):
        solve(d)
    m = solve(describe(goal('sqrt(x)', input_domain='[-1,1]', domain_role='restriction'), TARGET))
    assert m['effective_domain'] == sp.Interval(0, 1)
    with pytest.raises(ValueError, match='no_nondegenerate_interval'):
        solve(describe(goal('sqrt(-x^2)'), TARGET))
    d = describe(goal('x', input_domain='[1,1]'), TARGET)
    assert not d['structure_supported']  # singleton is not a nondegenerate interval


@pytest.mark.parametrize('wording,role', [
    (r'函数 $y=-x^2+4x+3$，$x\in[0,3]$', 'declared'),
    (r'函数 $y=-x^2+4x+3$，定义域为 $x\in[0,3]$', 'restriction'),
])
def test_source_domain_wording_can_vary_when_the_whole_interval_is_legal(wording, role):
    from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
    from shuxueshuo_server.graph_lesson.stage_two.monotonicity_surface import source_spans
    candidate = {'original_text': wording + ' 的单调递增区间是____。'}
    d = describe(goal('-x^2+4*x+3', direction='increasing', input_domain='[0,3]', domain_role=role), TARGET)
    assert source_spans(candidate, TARGET, [(0, len(candidate['original_text']))], d, _abstract_formula_matches)
    candidate['original_text'] = wording.replace('y=-x^2+4x+3', r'f(x)=\sqrt{x}').replace('[0,3]', '[-1,1]') + ' 的单调递增区间是____。'
    d = describe(goal('sqrt(x)', direction='increasing', input_domain='[-1,1]', domain_role=role), TARGET)
    assert source_spans(candidate, TARGET, [(0, len(candidate['original_text']))], d, _abstract_formula_matches) is None


def test_definition_proves_only_the_requested_interval_and_direction():
    g = goal('-x^2+4*x+3', input_domain='[0,2]', direction='increasing', kind='prove_monotonicity_on_interval')
    d = describe(g, TARGET); m = solve(d, 'definition')
    assert verify(d, m)
    for kw in ({'direction': 'decreasing'}, {'input_domain': '[0,3]'}):
        with pytest.raises(ValueError, match='requested_direction_false'):
            solve(describe({**g, **kw}, TARGET), 'definition')
    assert not describe({**g, 'direction': 'both'}, TARGET)['structure_supported']
    assert not describe({**g, 'expression': 'sqrt(x)'}, TARGET)['structure_supported']


@pytest.mark.parametrize('wording,direction', [
    ('求函数的单调递增区间和单调递减区间', 'both'),
    ('求函数的递减区间与递增区间', 'both'),
    ('判断函数的单调性', 'both'),
    ('求函数的单调递增区间', 'increasing'),
    ('求函数的递减区间', 'decreasing'),
])
def test_source_binding_preserves_every_requested_direction(wording, direction):
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    from shuxueshuo_server.graph_lesson.stage_two.monotonicity_surface import (
        source_spans,
    )
    candidate = {'original_text': '已知函数 $f(x)=x^2$，'+wording+'。'}
    for extracted in ('increasing', 'decreasing', 'both'):
        d = describe(goal('x^2', direction=extracted), TARGET)
        spans = source_spans(candidate, TARGET, [(0, len(candidate['original_text']))], d, _abstract_formula_matches)
        assert bool(spans) == (extracted == direction)
    if '和' in wording or '与' in wording:
        assert len(spans) == 3  # expression and both direction requests


@pytest.mark.parametrize('variable', ['t', 'u', 'v'])
def test_teaching_keeps_source_names_and_uses_distinct_composition_variables(variable):
    d = describe(goal(f'1/sqrt({variable}^2+1)', variable=variable, function='g'), TARGET)
    m = solve(d)
    for phase in ('inner', 'composition', 'answer'):
        for view in phase_views({'monotonicity_result': m, 'phase': phase}):
            left = view['derivation']['items'][0]['math']
            assert rf'{variable}\in' in left and r'x\in' not in left
            assert view['graph']['params']['variable'] == variable
            if phase == 'composition':
                operation = view['derivation']['operation']['math']
                if 'sqrt' in operation:
                    output, operand = operation.split('=')
                    assert output != variable and operand != rf'\sqrt{{{variable}}}'
                else:
                    assert operation.startswith(f'g({variable})=')
    m = solve(describe(goal(f'{variable}^2', variable=variable, function='g', input_domain='[0,1]'), TARGET))
    difference = phase_views({'monotonicity_result': m, 'phase': 'difference'})[0]
    assert f'g({variable}_2)-g({variable}_1)' in difference['derivation']['items'][0]['math']


def test_six_source_questions_and_every_native_interaction():
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    from shuxueshuo_server.graph_lesson.stage_two.monotonicity_surface import (
        source_spans,
    )
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'})
    for path in (ROOT/'internal/senior-high/authored-courses/function-monotonicity-t1-20261104').glob('*.json'):
        candidate = json.loads(path.read_text())['candidate']; g = candidate['root']['goals'][0]
        d = describe(g, TARGET); m = solve(d)
        spans = source_spans(candidate, TARGET, [(0, len(candidate['original_text']))], d, _abstract_formula_matches)
        assert spans, path.name
        wrong = deepcopy(d); wrong['source']['direction'] = 'decreasing' if g['direction'] == 'increasing' else 'increasing'
        assert source_spans(candidate, TARGET, [(0, len(candidate['original_text']))], wrong, _abstract_formula_matches) is None
        selection = evaluate_goal(candidate, TARGET, [], 'type-function-monotonicity')
        assert selection['d3']['interaction']['layout'] == 'connections'
        assert selection['d3']['verdicts']['definition']['value'] == 'fit'  # valid maths, not an opened route
        assert '不展开' in selection['d3']['verdicts']['definition']['message']
        assert all(b['target'] != 'method-monotonicity-definition' for b in selection['selection']['branches'])
        assert all(cue['note'] for cue in selection['d3']['interaction']['checks'][0]['options'])
        piecewise_cue = next(cue for cue in selection['d3']['interaction']['checks'][0]['options']
                             if cue['value'] == 'piecewise')
        assert piecewise_cue['label'] == '含绝对值，需要按符号分段'
        phases = ['inner', 'answer']
        if m['family'] == 'polynomial': phases += ['difference']
        if m['family'] in ('sqrt', 'reciprocal_sqrt'): phases += ['composition']
        if m['family'] == 'absolute': phases += ['join']
        for phase in phases:
            seed = {'values': encode_value({'description': d, 'monotonicity_result': m, 'phase': phase})}
            for part in compile_monotonicity([seed], 'a'*24)['parts']:
                validator.validate(part)
                assert part['stem_board']['items'][1]['math'] is None
                assert part['graph']
                correct = part['expected_answer']['one_of'][0]
                assert grade(part, {'value': correct}, {}) == 'passed'
                for option in part['interaction']['options']:
                    if option['value'] != correct:
                        assert grade(part, {'value': option['value']}, {}) != 'passed'


def test_actual_radical_graphs_keep_holes_and_open_poles():
    for expr, transform in [('sqrt(x^2-2*x-3)', 'sqrt'), ('1/sqrt(x^2-5*x-6)', 'reciprocal_sqrt')]:
        m = solve(describe(goal(expr), TARGET))
        plotted = graph_for(m)['params']['segments']
        assert len(plotted) == 2 and all(s['transform'] == transform for s in plotted)
        assert plotted[0]['interval'][1] < plotted[1]['interval'][0]
        assert all(s['transform'] == 'identity' for s in graph_for(m, inner=True)['params']['segments'])
        if transform == 'reciprocal_sqrt':
            assert all(s['interval_closed'] == [False, False] for s in plotted)


def test_reciprocal_composition_confirms_each_layer_with_its_actual_graph():
    m = solve(describe(goal('1/sqrt(x^2-5*x-6)'), TARGET))
    views = phase_views({'monotonicity_result': m, 'phase': 'composition'})
    assert len(views) == 4  # two connected intervals, two successive operations
    for root, reciprocal in zip(views[::2], views[1::2], strict=True):
        stem, done = root['derivation']['items'][0]['math'], root['derivation']['items'][1]['math']
        assert 'u>0' in stem and '开方保序' not in stem and '反序' not in stem
        assert 'v>0' in reciprocal['derivation']['items'][0]['math']
        assert '正数取倒数反序' not in reciprocal['derivation']['items'][0]['math']
        assert '开方保序' in done and r'\xrightarrow' in done
        assert root['derivation']['items'][1]['math'] != reciprocal['derivation']['items'][1]['math']
        for view in (root, reciprocal):
            params = view['graph']['params']
            mark, = params['interval_marks']
            highlight, = params['highlights']
            assert (mark['from'], mark['to']) == (highlight['from'], highlight['to'])
            assert mark['trend'] != 'pending'  # the pictured input direction is already known
        assert root['completion_graph']['params']['highlights']
        assert any(mark['trend'] in ('increasing', 'decreasing') for mark in root['completion_graph']['params']['interval_marks'])
        assert {s['transform'] for s in root['graph']['params']['segments']} == {'identity'}
        assert {s['transform'] for s in reciprocal['graph']['params']['segments']} == {'sqrt'}
        assert r'v=\sqrt{u}' in done
        assert r'\frac1v' in reciprocal['derivation']['items'][1]['math']
    graphs = [g for view in views for g in view.get('completion_graphs', [])]
    assert len(graphs) == 2  # completed replay does not repeat the same plots eight times
    assert {s['transform'] for s in graphs[0]['params']['segments']} == {'identity'}
    assert {s['transform'] for s in graphs[1]['params']['segments']} == {'reciprocal_sqrt'}
    assert any(mark['trend'] in ('increasing', 'decreasing') for mark in graphs[1]['params']['interval_marks'])


@pytest.mark.parametrize('expression', ['sqrt(-2*x^2+x+6)', '1/sqrt(x^2-5*x-6)'])
def test_composition_parts_show_operation_and_current_interval_without_output_answer(expression):
    m = solve(describe(goal(expression), TARGET))
    seed = {'values': encode_value({'monotonicity_result': m, 'phase': 'composition'})}
    parts = compile_monotonicity([seed], 'a'*24)['parts']
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'})
    expected = [(row, layer) for row in m['partition'] for layer in row['layers']]
    for part, (row, layer) in zip(parts, expected, strict=True):
        validator.validate(part)
        stem, done = part['stem_board'], part['completion_board']
        assert stem['operation'] == done['operation']
        assert stem['operation']['label'] == ('开方' if layer['operation'] == 'sqrt' else '取倒数')
        assert stem['operation']['math'] == (r'v=\sqrt{u}' if layer['operation'] == 'sqrt' else r'f(x)=\frac1v')
        assert stem['items'][1]['math'] is None
        assert all(text not in json.dumps(stem, ensure_ascii=False) for text in ('保序', '反序', 'xrightarrow'))
        assert 'x\\in' in part['title']
        mark, = part['graph']['params']['interval_marks']
        assert mark['trend'] == {1: 'increasing', -1: 'decreasing', 0: 'constant'}[layer['before']]
        region = row['interval']
        assert [mark['from'], mark['to']] == [float(v) if v.is_finite else None for v in (region.inf, region.sup)]
        assert [mark['left_closed'], mark['right_closed']] == [not region.left_open, not region.right_open]
        for option in part['interaction']['options']:
            assert (grade(part, {'value': option['value']}, {}) == 'passed') == (option['value'] in part['expected_answer']['one_of'])


def test_quadratic_square_step_and_progressive_interval_marks():
    from shuxueshuo_server.graph_lesson.stage_three.capabilities import complete_square
    d = describe(goal('-x^2+4*x+3', input_domain='[0,3]'), TARGET)
    m = solve(d)
    square = complete_square(m['expression'], m['variable'])['outputs']['square']
    seed = {'values': encode_value({'monotonicity_result': m, 'phase': 'square', 'square': square})}
    part, = compile_monotonicity([seed], 'b'*24)['parts']
    assert '顶点式' in part['title']
    assert 'graph' not in part  # the vertex is not disclosed before completing the square
    assert part['completion_graph']
    assert part['stem_board']['items'][1]['math'] is None
    for option in part['interaction']['options']:
        expected = option['value'] in part['expected_answer']['one_of']
        assert (grade(part, {'value': option['value']}, {}) == 'passed') == expected
    with pytest.raises(ValueError, match='square_identity_invalid'):
        phase_views({'monotonicity_result': m, 'phase': 'square', 'square': square+1})

    views = phase_views({'monotonicity_result': m, 'phase': 'inner'})
    assert all(v['title'] == '判断二次函数的增减' for v in views)
    assert views[0]['part_title'] != views[1]['part_title']
    first = views[0]['graph']['params']['interval_marks']
    second = views[1]['graph']['params']['interval_marks']
    assert [(v['from'], v['to'], v['trend']) for v in first] == [(0, 2, 'pending')]
    assert [(v['from'], v['to'], v['trend']) for v in second] == [(0, 2, 'increasing'), (2, 3, 'pending')]
    final = phase_views({'monotonicity_result': m, 'phase': 'answer'})[0]['graph']['params']['interval_marks']
    assert [v['trend'] for v in final] == ['increasing', 'decreasing']


def test_definition_route_is_open_for_proof_goals_only():
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    candidate = {'root': {'goals': [goal('x^2', input_domain='[0,2]', direction='increasing',
                                       kind='prove_monotonicity_on_interval')]}}
    selected = evaluate_goal(candidate, TARGET, [], 'type-function-monotonicity')
    assert selected['d3']['verdicts']['definition']['value'] == 'fit'
    assert selected['selection']['branches'][0]['target'] == 'method-monotonicity-definition'


@pytest.mark.parametrize('domain,count', [('ℝ', 1), ('[-3,-2]', 1), ('[-1,0]', 1)])
def test_piecewise_join_asks_only_about_the_actual_split_not_quadratic_axes(domain, count):
    d = describe(goal('-x^2+2*abs(x)+3', input_domain=domain), TARGET)
    m = solve(d)
    seed = {'values': encode_value({'description': d, 'monotonicity_result': m, 'phase': 'join'})}
    parts = compile_monotonicity([seed], 'a'*24)['parts']
    assert len(parts) == count
    left = parts[0]['stem_board']['items'][0]['math']
    assert ('f(0)' in left) == (domain == 'ℝ')
    correct = parts[0]['expected_answer']['one_of'][0]
    assert grade(parts[0], {'value': correct}, {}) == 'passed'


def test_child_bindings_are_real_subproblems_and_cannot_be_replaced():
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_runtime import (
        admitted,
        join,
        split,
    )
    candidate = {'original_text': '', 'root': {'goals': [goal('-x^2+2*abs(x)+3')]}}
    context = build_context(candidate, TARGET); cases = split(context)['outputs']['branch_cases']
    assert all(admitted(c['context'], 'structure') for c in cases)
    results = [{'case_id': c['id'], 'domain': c['domain'], 'condition': c['condition'],
                'outputs': {'model': solve(c['context']['monotonicity_goal'])}} for c in cases]
    assert join(context, results)['outputs']['monotonicity_result']['method'] == 'piecewise'
    results.reverse()
    with pytest.raises(ValueError, match='child_proof_invalid'):
        join(context, results)


@pytest.mark.parametrize('expr,domain,inc,dec,merge', [
    ('piecewise(2*x-1,x<1,x^2,x>=1)', 'ℝ', [sp.Interval(-sp.oo, sp.oo)], [], [True]),
    ('piecewise(-x^2+6*x,x<3,3*x,x>=3)', 'ℝ', [sp.Interval(-sp.oo, sp.oo)], [], [True]),
    ('piecewise(x,x<0,x-2,x>=0)', 'ℝ', [sp.Interval.open(-sp.oo, 0), sp.Interval(0, sp.oo)], [], [False]),
    ('piecewise(1,x<0,x^2+1,x>=0)', 'ℝ', [sp.Interval(0, sp.oo)], [], [False]),
])
def test_explicit_piecewise_image_order_controls_join(expr, domain, inc, dec, merge):
    d = describe(goal(expr, input_domain=domain), TARGET)
    assert d['family'] == 'explicit_piecewise'
    m = solve(d, 'piecewise')
    assert m['increasing_intervals'] == inc
    assert m['decreasing_intervals'] == dec
    assert [row['merge'] for row in m['junctions']] == merge
    assert verify(d, m)


def test_explicit_piecewise_prove_requires_cross_piece_order():
    g = goal('piecewise(2*x-1,x<1,x^2,x>=1)', input_domain='ℝ', direction='increasing',
             kind='prove_monotonicity_on_interval')
    d = describe(g, TARGET)
    m = solve(d, 'piecewise')
    assert m['increasing_intervals'] == [sp.Interval(-sp.oo, sp.oo)]
    assert verify(d, m)
    bad = goal('piecewise(x,x<0,x-2,x>=0)', input_domain='ℝ', direction='increasing',
               kind='prove_monotonicity_on_interval')
    with pytest.raises(ValueError, match='requested_direction_false'):
        solve(describe(bad, TARGET), 'piecewise')


@pytest.mark.parametrize('expr,domain,method,inc,dec', [
    ('3*x^2-12*x+7', '[-1,5)', 'structure', [sp.Interval.Ropen(2, 5)], [sp.Interval(-1, 2)]),
    ('-2*x+5', '(-3,4]', 'definition', [], [sp.Interval.Lopen(-3, 4)]),
    ('7', '[1,3]', 'definition', [], []),
    ('sqrt(9-x^2)', 'ℝ', 'structure', [sp.Interval(-3, 0)], [sp.Interval(0, 3)]),
    ('1/sqrt(2*x+4)', 'ℝ', 'structure', [], [sp.Interval.open(-2, sp.oo)]),
    ('3*x+abs(2*x-2)', 'ℝ', 'piecewise', [sp.Interval(-sp.oo, sp.oo)], []),
    ('abs(x-2)', '[3,6]', 'piecewise', [sp.Interval(3, 6)], []),
    ('abs(x-2)', '[0,2]', 'piecewise', [], [sp.Interval(0, 2)]),
    ('piecewise(2*x-1,x<1,x^2,x>=1)', 'ℝ', 'piecewise', [sp.Interval(-sp.oo, sp.oo)], []),
])
def test_new_structural_variants_execute_real_children_and_compile_every_step(expr, domain, method, inc, dec):
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from tests.solver.test_graph_stage_three_methods import finish
    candidate = {'original_text': '判断函数单调性', 'root': {'goals': [goal(expr, input_domain=domain)]}}
    context = build_context(candidate, TARGET)
    method_id = 'method-piecewise-monotonicity' if method == 'piecewise' else 'method-monotonicity-'+method
    state = finish(driver.create_state(features=extract_features(candidate)['features'], context=context,
                   method=method_id, route_id=method_id.removeprefix('method-'), branch=method,
                   target_ref=TARGET, run_id='monotonicity-variants', lesson_version='v1'))
    assert state['status'] == 'method_complete', state['diagnostics']
    model = driver.export_values(state)['monotonicity_result']
    assert model['increasing_intervals'] == inc and model['decreasing_intervals'] == dec
    assert verify(context['monotonicity_goal'], model)
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry())
    assert chunks and not pending
    for chunk, diagnostics in chunks:
        assert chunk['status'] == 'interactive', (chunk, diagnostics)
        interaction.validate_chunk(chunk)
