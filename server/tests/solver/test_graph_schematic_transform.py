"""G4 verifies only visible curve facts and exact input-coordinate identities."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.function_graph import describe, solve, verify
from shuxueshuo_server.graph_lesson.stage_three.graph_transform_presentation import (
    compile_graph,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


def candidate():
    return json.loads((ROOT/'internal/senior-high/authored-courses/function-graph-g4-20261102/b09-v3.json').read_text())['candidate']


def test_point_identity_direction_and_all_options_are_verified_independently(monkeypatch):
    g = candidate()['root']['goals'][0]
    d = describe(g, TARGET); r = solve(d)
    assert (r['target_zero'], r['target_direction'], r['correct_option_id']) == (2, 'decreasing', 'option-c')
    assert [row['differences'] for row in r['option_verdicts']] == [
        ['shown_direction'], ['shown_direction', 'x_intercept'], [], ['x_intercept']]
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.schematic_transform.solve', lambda *_: pytest.fail('verifier must not solve'))
    assert verify(d, r)
    for change in [{'target_zero': -2}, {'target_direction': 'increasing'}, {'a': 1}, {'correct_option_id': 'option-d'}]:
        assert not verify(d, {**r, **change})
    assert 'polynomial' not in r and 'formula' not in r


@pytest.mark.parametrize('expr,direction,zero,label', [
    ('f(x-2)', 'increasing', 2, 'A'), ('f(x+2)', 'increasing', -2, 'B'),
    ('f(-x-2)', 'decreasing', -2, 'D'),
])
def test_transform_uses_expression_not_answer_letter(expr, direction, zero, label):
    g = candidate()['root']['goals'][0]; g['expression'] = expr; g['options'].reverse()
    d = describe(g, TARGET); r = solve(d)
    assert (r['target_zero'], r['target_direction']) == (zero, direction)
    assert r['correct_option_id'] == 'option-'+label.lower() and verify(d, r)


@pytest.mark.parametrize('change', [
    lambda g: g.update(expression='f(x*x)'), lambda g: g.update(expression='f(2*x)'),
    lambda g: g.update(expression='g(2-x)'), lambda g: g.update(input_domain='[0,1]'),
    lambda g: g['source_graph'].update(uncertainties=['图被截断']),
    lambda g: g['source_graph']['facts'].update(direction='unknown'),
    lambda g: g['options'][0]['facts']['x_intercept'].update(evidence='estimated'),
    lambda g: g.update(comparison='exact_equivalence'),
])
def test_unknown_or_out_of_scope_facts_do_not_produce_answer(change):
    g = candidate()['root']['goals'][0]; change(g)
    d = describe(g, TARGET)
    assert not d['structure_supported']
    with pytest.raises(ValueError): solve(d)


def test_indistinguishable_options_do_not_pick_first():
    g = candidate()['root']['goals'][0]
    g['options'][3]['facts'] = deepcopy(g['options'][2]['facts'])
    with pytest.raises(ValueError, match='indistinguishable'): solve(describe(g, TARGET))


def test_schema_source_binding_selection_and_teaching_have_no_invented_curve():
    from jsonschema import Draft202012Validator

    from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
    from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_two.fragments import (
        _abstract_formula_matches,
    )
    from shuxueshuo_server.graph_lesson.stage_two.graph_surface import (
        graph_source_spans,
    )
    c = candidate(); g = c['root']['goals'][0]; d = describe(g, TARGET); r = solve(d)
    assert validate_candidate(c)['contract_valid']
    assert extract_features(c)['ok']
    select = evaluate_goal(c, TARGET, [], 'type-function-graph')
    assert select['d3']['expected_answer']['checks']['source_structure'] == 'source_graph'
    def spans(text):
        return graph_source_spans({**c, 'original_text': text}, TARGET, [(0, len(text))], d, _abstract_formula_matches)
    assert spans(c['original_text'])
    assert not spans(c['original_text'].replace('f(2-x)', 'f(2+x)'))
    assert not spans(c['original_text'].replace('则函数', '且定义域为正实数，则函数'))
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    parts = []
    for phase in ('transform', 'vertex', 'options'):
        compiled = compile_graph([{'values': encode_value({'description': d, 'graph_result': r, 'phase': phase})}], 'a'*24)
        for part in compiled['parts']:
            Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'}).validate(part)
            assert part['show_source_graph']
            assert 'graph' not in part and 'completion_graph' not in part
            assert part['stem_board']['items'][1]['math'] is None
        parts += compiled['parts']
    assert len(parts) == 5 and parts[-1]['figure_choices'] == ['option-a', 'option-b', 'option-c', 'option-d']
