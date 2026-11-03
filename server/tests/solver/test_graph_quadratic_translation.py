"""G3's exact translations, source evidence and small-step teaching contract."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.function_graph import describe, solve, verify
from shuxueshuo_server.graph_lesson.stage_three.graph_transform_presentation import (
    compile_graph,
    presentation,
    translation_views,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


def candidate():
    return json.loads((ROOT/'internal/senior-high/authored-courses/function-graph-g3-20261102/b09-v2.json').read_text())['candidate']


def goal():
    return candidate()['root']['goals'][0]


def test_exact_ordered_translations_and_independent_point_checks(monkeypatch):
    d = describe(goal(), TARGET); r = solve(d)
    assert r['states'][-1]['landmarks'] == [[-3, -1], [-2, 0], [-1, -1]]
    assert r['correct_option_id'] == 'option-c'
    from jsonschema import Draft202012Validator
    for name in ('graph-stage-three-result-v1', 'graph-stage-three-route-v1', 'graph-stage-three-route-v2'):
        schema = json.loads((ROOT/f'internal/schemas/{name}.schema.json').read_text())
        answer = {'kind':'select_function_graph','status':'complete','comparison':'rough_shape',
                  'correct_option_id':'option-c','correct_labels':['C'],'option_verdicts':r['option_verdicts']}
        answer_schema = {'$defs':schema['$defs'], '$ref':'#/$defs/goalAnswer'}
        Draft202012Validator(answer_schema).validate(answer)
    x = r['variable']
    assert x.name == 'x'
    assert sp.expand(r['states'][-1]['polynomial']-(1-(x+2)**2)) == 0
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.quadratic_translation.solve', lambda *_: pytest.fail('must verify independently'))
    assert verify(d, r)
    for mutate in [lambda v: v['states'][-1].update(offset=1),
                   lambda v: v['states'][1].update(polynomial=1-(x-2)**2),
                   lambda v: v['states'][-1]['landmarks'][0].__setitem__(1, 0),
                   lambda v: v.update(correct_option_id='option-a'),
                   lambda v: v['moves'][0].update(dx=2)]:
        changed = deepcopy(r); mutate(changed)
        assert not verify(d, changed)


def test_two_translation_orders_have_the_same_final_formula_and_landmarks():
    g = goal(); one = solve(describe(g, TARGET))
    g['transformations'].reverse(); two = solve(describe(g, TARGET))
    assert one['states'][-1] == two['states'][-1]
    assert one['states'][1] != two['states'][1]
    assert verify(describe(g, TARGET), two)


@pytest.mark.parametrize('moves', [
    [{'direction': 'right', 'distance': '2'}, {'direction': 'up', 'distance': '3'}],
    [{'direction': 'left', 'distance': '1/2'}],
    [{'direction': 'down', 'distance': '1'}],
])
def test_signed_and_fractional_moves_change_the_actual_formula(moves):
    g = goal(); g['transformations'] = moves
    dx = sum(sp.Rational(m['distance'])*(1 if m['direction'] == 'right' else -1) for m in moves if m['direction'] in ('left','right'))
    dy = sum(sp.Rational(m['distance'])*(1 if m['direction'] == 'up' else -1) for m in moves if m['direction'] in ('up','down'))
    g['options'][2]['facts']['landmarks'][0].update(x=str(dx), y=str(3+dy))
    g['options'][2]['facts']['landmarks'][1].update(x=str(1+dx), y=str(2+dy))
    d = describe(g, TARGET); r = solve(d)
    assert r['states'][-1]['landmarks'] == [[-1+dx,2+dy],[dx,3+dy],[1+dx,2+dy]]
    assert verify(d, r)
    assert len(translation_views({'description':d,'graph_result':r})) == len(moves)


def test_partial_option_needs_a_visible_contradiction_and_never_wins_by_omission():
    g = goal(); g['options'].reverse()
    d = describe(g, TARGET); r = solve(d)
    assert r['correct_option_id'] == 'option-c'
    assert r['option_verdicts'][0]['differences'] == ['left_corner_y']
    # The obscured D is excluded by y=0, not by assuming its hidden coordinates.
    g['options'][0]['facts']['landmarks'][0].update(y='-1', evidence='labelled')
    with pytest.raises(ValueError, match='insufficient_option_features'):
        solve(describe(g, TARGET))
    g['options'][0]['facts'] = deepcopy(g['options'][1]['facts'])
    with pytest.raises(ValueError, match='indistinguishable'):
        solve(describe(g, TARGET))
    g = goal(); g['options'][2]['facts']['symmetry'] = 'unknown'
    with pytest.raises(ValueError, match='insufficient_option_features'):
        solve(describe(g, TARGET))


@pytest.mark.parametrize('change', [
    lambda g: g.update(expression='abs(x*x+1)+2'),
    lambda g: g.update(expression='abs(x*x-2)+2'),
    lambda g: g.update(expression='abs(x)+2'),
    lambda g: g.update(input_domain='[0,2]'),
    lambda g: g.update(comparison='exact_equivalence'),
    lambda g: g['transformations'][0].update(distance='0'),
    lambda g: g['transformations'][0].update(direction='down'),
    lambda g: g['options'][0].update(uncertainties=['关键标注模糊']),
    lambda g: g['options'][2]['facts']['landmarks'][0].update(evidence='estimated'),
])
def test_outside_declared_scope_does_not_produce_a_guessed_answer(change):
    g = goal(); change(g); d = describe(g, TARGET)
    assert not d['structure_supported']
    with pytest.raises(ValueError): solve(d)


def test_native_schema_source_binding_and_method_card_preserve_the_requested_moves():
    from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    from shuxueshuo_server.graph_lesson.stage_two.graph_surface import (
        graph_source_spans,
    )
    c = candidate(); d = describe(goal(), TARGET)
    assert validate_candidate(c)['contract_valid']
    assert extract_features(c)['ok']
    def spans(text):
        return graph_source_spans({**c,'original_text':text}, TARGET, [(0,len(text))], d, _abstract_formula_matches)
    assert spans(c['original_text'])
    for old, new in [('向左','向右'), ('3 个','4 个'), ('向左、向下','向下、向左'), ('所得图像','再关于横轴翻折，所得图像')]:
        assert not spans(c['original_text'].replace(old,new))
    omitted = deepcopy(d); del omitted['source']['transformations']
    shortened = c['original_text'].replace('向左、向下分别平移 2 个、3 个单位长度', '左移2、下移3')
    assert not graph_source_spans({**c,'original_text':shortened}, TARGET, [(0,len(shortened))], omitted, _abstract_formula_matches)
    selected = evaluate_goal(c, TARGET, [], 'type-function-graph')
    assert selected['d3']['expected_answer']['checks']['source_structure'] == 'translation'


def test_each_card_starts_at_previous_picture_and_keeps_math_derivations():
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    part_schema = {'$defs':schema['$defs'], **schema['properties']['parts']['items']}
    d = describe(goal(), TARGET); r = solve(d)
    values = {'description':d,'graph_result':r,'phase':'transform'}
    views = translation_views(values)
    assert views[1]['graph'] == views[0]['completion_graph']
    for i, view in enumerate(views):
        assert view['completion_graph']['params']['reference'] == view['graph']['params']['segments']
        assert view['graph']['params']['bounds'] == view['completion_graph']['params']['bounds']
        assert '\\xrightarrow' in view['proof']
    for phase in ('transform','vertex','options'):
        values['phase'] = phase
        parts = compile_graph([{'values':encode_value(values)}], 'a'*24)['parts']
        assert len(parts) == (2 if phase == 'transform' else 1)
        for part in parts:
            Draft202012Validator(part_schema).validate(part)
            assert part['stem_board']['items'][1]['math'] is None
            assert part['completion_board']['items'][1]['math']
            assert '_input' not in json.dumps(part)
        assert '$$' in presentation(values)['formula_explanation']
        if phase == 'options':
            assert parts[0]['figure_choices'] == ['option-a','option-b','option-c','option-d']
