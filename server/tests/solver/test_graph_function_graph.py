"""FR-T2 G1: source-bound graph facts, exact point maps and answer checks."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_graph import describe, describe_scoped, solve, verify
from shuxueshuo_server.graph_lesson.stage_three.graph_transform_presentation import (
    compile_graph,
    graph_for,
    translation_views,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


def record():
    return json.loads((ROOT/'internal/senior-high/authored-courses/function-graph-g1-20261102/b09.json').read_text())


def goal():
    return record()['candidate']['root']['goals'][0]


@pytest.mark.parametrize('a,b,c,domain,base', [
    (1, -1, 1, 'ℝ', sp.S.Reals),
    (-2, 3, -1, '[0,2)', sp.Interval.Lopen(-1, 3)),
    (sp.Rational(1, 2), -1, 0, '(0,4]', sp.Interval.Lopen(-1, 1)),
])
def test_exact_point_map_transports_open_ends_and_reverses_negative_input(a, b, c, domain, base, monkeypatch):
    g = goal(); g.update(expression=f'abs(({a})*x+({b}))+({c})', input_domain=domain)
    h = -sp.S(b)/a
    for i, option in enumerate(g['options']):
        option['facts']['vertex'].update(x=str(h+i), y=str(c))
        option['facts']['domain'] = domain
    d = describe(g, TARGET); r = solve(d)
    assert r['vertex'] == [h, c] and r['base_domain'] == base
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.function_graph.solve', lambda *_: pytest.fail('verification must not solve'))
    assert verify(d, r)
    for key, wrong in [('vertex', [h+1, c]), ('correct_option_id', 'option-b'), ('a', -a), ('domain', sp.Interval(0, 99))]:
        assert not verify(d, {**r, key: wrong})
    if base != sp.S.Reals:
        assert not verify(d, {**r, 'base_domain': sp.Interval(base.start, base.end)})


@pytest.mark.parametrize('change', [
    lambda g: g.update(expression='abs(0*x+1)+1'),
    lambda g: g.update(expression='abs(x*x)+1'),
    lambda g: g.update(comparison='exact_equivalence'),
    lambda g: g['options'][0]['facts']['vertex'].update(evidence='estimated'),
    lambda g: g['options'][0]['facts'].update(left_direction='unknown'),
    lambda g: g['options'][0].update(uncertainties=['vertex unreadable']),
    lambda g: g['options'][1].update(option_id='option-a'),
    lambda g: g.update(input_domain='[0,2)'),
])
def test_unsupported_or_uncertain_sources_never_become_wrong_options(change):
    g = goal(); change(g); d = describe(g, TARGET)
    assert not d['structure_supported']
    with pytest.raises(ValueError): solve(d)


def test_rough_graph_scoring_ignores_order_but_not_ambiguity_or_changed_vertex():
    g = goal(); g['options'].reverse(); r = solve(describe(g, TARGET))
    assert r['correct_option_id'] == 'option-a'
    assert [row['label'] for row in r['option_verdicts']] == ['D', 'C', 'B', 'A']
    g['options'][0]['facts'] = deepcopy(g['options'][-1]['facts'])
    with pytest.raises(ValueError, match='indistinguishable'): solve(describe(g, TARGET))


def test_same_given_formula_is_consumed_with_provenance_and_verified_again():
    g = goal()
    definition = {'source_ref': '/root/definitions/0', 'expression': 'f(x)=abs(x-1)+1'}
    d = describe_scoped(g, TARGET, [definition])
    assert d['structure_supported'] and d['given_definitions'] == [definition]
    assert definition['source_ref'] in d['source_refs'] and not d['extra_source_refs']
    result = solve(d)
    assert verify(d, result)
    changed = deepcopy(d)
    changed['given_definitions'][0]['expression'] = 'f(x)=abs(x+1)+1'
    assert not verify(changed, result)
    for text in ('f(x)=abs(x+1)+1', 'f(t)=abs(t-1)+1', 'g(x)=abs(x-1)+1'):
        assert not describe_scoped(g, TARGET, [{**definition, 'expression': text}])['structure_supported']
    assert not describe_scoped(g, TARGET, [definition, definition])['structure_supported']
    assert not describe_scoped(g, TARGET, [definition, {
        'source_ref': '/root/facts/0', 'expression': 'x>0'}])['structure_supported']


def test_native_contracts_mask_answers_keep_pictures_and_show_mathematical_derivations():
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import (
        load_contracts,
    )
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    from shuxueshuo_server.graph_lesson.stage_two.graph_surface import (
        graph_source_spans,
    )
    from shuxueshuo_server.learning.graph_walk import grade
    c = record()['candidate']; d = describe(goal(), TARGET); r = solve(d)
    assert 'method-function-graph-transform' in load_contracts()
    selected = evaluate_goal(c, TARGET, [], 'type-function-graph')
    assert selected['d3']['interaction']['layout'] == 'connections'
    assert selected['d3']['verdicts']['piecewise']['value'] == 'fit'
    assert graph_source_spans(c, TARGET, [(0, len(c['original_text']))], d, _abstract_formula_matches)
    changed = deepcopy(c); changed['original_text'] = c['original_text'].replace('|x-1|', '|x+1|')
    assert not graph_source_spans(changed, TARGET, [(0, len(changed['original_text']))], d, _abstract_formula_matches)
    for phase in ('transform', 'vertex', 'options'):
        seed = {'values': encode_value({'description': d, 'graph_result': r, 'phase': phase})}
        parts = compile_graph([seed], phase)['parts']
        assert len(parts) == (2 if phase == 'transform' else 1)
        for part in parts:
            assert part['stem_board']['items'][1]['math'] is None
            assert part['completion_board']['items'][1]['math']
            correct = part['expected_answer']['one_of'][0]
            assert grade(part, {'value': correct}, 'function-graph-transform') == 'passed'
            wrong = next(o['value'] for o in part['interaction']['options'] if o['value'] != correct)
            assert grade(part, {'value': wrong}, 'function-graph-transform') != 'passed'
            if phase == 'options': assert part['figure_choices'] == ['option-a','option-b','option-c','option-d']
    assert graph_for(sp.S(-2), sp.S(3), sp.S(-1), sp.Interval.Ropen(0, 2))['params']['interval_closed'] == [True, False]


@pytest.mark.parametrize('b,c,titles', [
    (-1, 1, ['左右移动', '上下移动']),
    (2, -3, ['左右移动', '上下移动']),
    (0, 2, ['上下移动']),
    (3, 0, ['左右移动']),
])
def test_translation_cards_start_from_previous_result_and_skip_absent_moves(b, c, titles):
    g = goal(); g.update(expression=f'abs(x+({b}))+({c})')
    for i, option in enumerate(g['options']):
        option['facts']['vertex'].update(x=str(-b+i), y=str(c))
    d = describe(g, TARGET); r = solve(d)
    views = translation_views({'description': d, 'graph_result': r})
    assert [v['title'] for v in views] == titles
    assert views[0]['graph']['params']['b'] == views[0]['graph']['params']['c'] == 0
    for i, view in enumerate(views):
        before, after = view['graph']['params'], view['completion_graph']['params']
        assert after['reference']['b'] == before['b']
        assert after['reference']['c'] == before['c']
        if i: assert view['graph'] == views[i-1]['completion_graph']
        if view['title'] == '左右移动': assert after['b'] == b and after['c'] == 0
        else: assert after['b'] == b and after['c'] == c
        assert '\\xrightarrow' in view['proof']
