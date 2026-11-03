"""G2 exact regions, strict endpoints, source binding and guided construction."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.absolute_graph import describe, solve, verify
from shuxueshuo_server.graph_lesson.stage_three.absolute_graph_presentation import (
    compile_absolute,
    phase_views,
)
from shuxueshuo_server.learning.graph_walk import grade

ROOT = Path(__file__).resolve().parents[3]


def goal(expression='abs(x^2-2*x-3)', **kwargs):
    return {'kind': 'solve_graph_inequality', 'expression': expression, 'variable': 'x', 'operator': '>=', 'level': '3', **kwargs}


@pytest.mark.parametrize('expr,level,op,expected', [
    ('abs(0)', '0', '>=', sp.S.Reals), ('abs(0)', '0', '>', sp.S.EmptySet),
    ('abs(-2)', '2', '<=', sp.S.Reals), ('abs(x)', '1', '<', sp.Interval.open(-1, 1)),
    ('abs(x^2+1)', '0', '>', sp.S.Reals), ('abs(x^2)', '0', '<=', sp.FiniteSet(0)),
    ('abs(x^2)', '0', '>', sp.S.Reals-sp.FiniteSet(0)),
    ('abs(-x^2)', '-1', '<', sp.S.EmptySet),
    ('abs(x^2-1)', '0', '>=', sp.S.Reals),
])
def test_polynomial_degeneracy_and_complete_regions(expr, level, op, expected):
    d = describe(goal(expr, level=level, operator=op), '/root/goals/0')
    model = solve(d)
    assert model['solution'] == expected
    assert verify(d, model)
    assert sp.Union(*(p['domain'] for p in model['pieces'])) == sp.S.Reals
    for phase in ('intersections', 'regions', 'endpoints'):
        parts = compile_absolute({'description': d, 'graph_result': model, 'phase': phase}, phase)['parts']
        assert len(parts[0]['interaction']['options']) >= 2


def test_ge_and_gt_differ_at_exactly_the_four_crossings_and_verifier_is_independent(monkeypatch):
    pairs = []
    for op in ('>=', '>'):
        d = describe(goal(operator=op), '/root/goals/0'); m = solve(d); pairs.append((d, m))
    expected = sp.Union(sp.Interval(-sp.oo, 1-sp.sqrt(7)), sp.Interval(0, 2), sp.Interval(1+sp.sqrt(7), sp.oo))
    assert pairs[0][1]['solution'] == expected
    assert pairs[0][1]['solution']-pairs[1][1]['solution'] == sp.FiniteSet(1-sp.sqrt(7), 0, 2, 1+sp.sqrt(7))
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.absolute_graph.solve', lambda *_: pytest.fail('independent verification'))
    for d, m in pairs:
        assert verify(d, m)
        for field, bad in [('solution', sp.S.Reals), ('crossings', sp.FiniteSet(0)), ('polynomial', m['polynomial']+1)]:
            assert not verify(d, {**m, field: bad})
        bad = deepcopy(m); bad['pieces'][1]['domain'] = sp.Interval(-1, 3)
        assert not verify(d, bad)  # Overlap at 3 must not count as a partition.
        bad = deepcopy(m); bad['pieces'][1]['expression'] *= -1
        assert not verify(d, bad)


def test_domain_open_ends_and_unsupported_expressions():
    d = describe(goal(input_domain='(-1,3]'), '/root/goals/0'); m = solve(d)
    assert verify(d, m) and m['roots'] == [3]
    assert m['solution'] == sp.Interval(0, 2)
    for expr in ('abs(x^3)', 'abs(1/x)', 'abs(a*x+1)', 'abs(x)+1'):
        assert not describe(goal(expr), '/root/goals/0')['structure_supported']


def test_source_binding_native_methods_and_each_guided_step():
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    from shuxueshuo_server.graph_lesson.stage_two.graph_surface import (
        graph_source_spans,
    )
    r = json.loads((ROOT/'internal/senior-high/authored-courses/function-graph-g2-20261102/b09-v1.json').read_text())
    candidate = r['candidate']; schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'})
    for index, g in enumerate(candidate['root']['goals']):
        target = f'/root/goals/{index}'; d = describe(g, target); m = solve(d)
        assert graph_source_spans(candidate, target, [(0, len(candidate['original_text']))], d, _abstract_formula_matches)
        selected = evaluate_goal(candidate, target, [], 'type-function-graph')
        assert selected['d3']['interaction']['layout'] == 'connections'
        phases = ('zeros', 'segments', 'assemble') if index == 0 else ('intersections', 'regions', 'endpoints')
        for phase in phases:
            values = {'description': d, 'graph_result': m, 'phase': phase}
            views = phase_views(values)
            parts = compile_absolute(values, 'a'*24)['parts']
            for part, view in zip(parts, views, strict=True):
                validator.validate(part)
                assert part['stem_board']['items'][1]['math'] is None
                assert view['proof'].startswith(r'\begin{gathered}') and r'\in' in view['proof']
                if part['interaction']['type'] == 'checklist':
                    assert part['guided_plot']['checks'] == ['pieces', 'intervals', 'direction', 'boundaries']
                    answer = {'value': part['expected_answer']['terms']}
                    wrong = {'value': ['wrong']*4}
                else:
                    answer = {'value': part['expected_answer']['one_of'][0]}
                    wrong = {'value': next(o['value'] for o in part['interaction']['options'] if o['value'] != answer['value'])}
                assert grade(part, answer, 'absolute-piecewise-graph') == 'passed'
                assert grade(part, wrong, 'absolute-piecewise-graph') != 'passed'
            if phase == 'segments':
                assert [len(p['completion_graph']['params']['segments']) for p in parts] == [1, 2, 3]
            if phase == 'endpoints':
                assert all(not point['open'] for point in parts[0]['completion_graphs'][0]['params']['points'])


def test_shared_definition_is_checked_in_each_child_and_cannot_hide_constraints():
    from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
    from shuxueshuo_server.graph_lesson.stage_three.absolute_graph_runtime import (
        construct,
    )
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.graph_transform_runtime import (
        admitted,
        verify_frozen,
    )
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

    drawing = {'kind': 'draw_function_graph', 'expression': 'abs(x^2-2*x-3)', 'variable': 'x'}
    candidate = {'original_text': '共同函数定义与两问', 'root': {
        'definitions': ['f(x)=abs(x^2-2*x-3)'],
        'children': [{'goals': [drawing]}, {'goals': [goal()]}]}}
    for i in range(2):
        target = f'/root/children/{i}/goals/0'
        context = build_context(candidate, target)
        assert admitted(context)
        desc = context['graph_goal']
        assert desc['source_refs'] == [target, '/root/definitions/0']
        features = candidate_features(candidate)['features']
        assert next(f['value'] for f in features if f['target_ref'] == target and f['feature_id'] == 'function_graph') == desc
        model = solve(desc)
        assert verify(desc, model)
        assert construct(context, inequality=i == 1)
        verified = verify_frozen(candidate, target, context, encode_value(model))
        assert verified['status'] == 'verified'
        assert verified['processing'][0]['source_ref'] == '/root/definitions/0'
        tampered = deepcopy(candidate)
        tampered['root']['definitions'][0] = 'f(x)=abs(x^2-2*x+3)'
        assert verify_frozen(tampered, target, context, encode_value(model))['status'] == 'math_failed'

    for patch in ({'definitions': ['f(x)=abs(x^2-2*x+3)']},
                  {'definitions': ['g(x)=abs(x^2-2*x-3)']}, {'facts': ['x>0']}):
        bad = deepcopy(candidate); bad['root'].update(patch)
        assert not admitted(build_context(bad, '/root/children/0/goals/0'))
    # A sibling's definition cannot silently become a shared condition.
    sibling = deepcopy(candidate)
    sibling['root']['children'][1]['definitions'] = ['g(x)=abs(x)']
    assert admitted(build_context(sibling, '/root/children/0/goals/0'))
    assert not admitted(build_context(sibling, '/root/children/1/goals/0'))
