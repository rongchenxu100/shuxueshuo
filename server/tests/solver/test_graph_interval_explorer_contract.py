"""Typed explorer transport shared by pending cards and completed highlights."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from shuxueshuo_server.graph_lesson.stage_one.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three import (
    abstract_parameter_presentation,
    presentation_templates,
)


def explorer():
    return {
        'parameter': 'a', 'variable': 'x',
        'intervals': [
            {'label': '第一个调用', 'call_latex': 'f(x+a)',
             'lower': {'slope': -1, 'intercept': 0, 'slope_exact': '-1', 'intercept_exact': '0'},
             'upper': {'slope': -1, 'intercept': 1, 'slope_exact': '-1', 'intercept_exact': '1'},
             'lower_latex': '-a', 'upper_latex': '1-a', 'left_open': False, 'right_open': False},
            {'label': '第二个调用', 'call_latex': 'f(x-a)',
             'lower': {'slope': 1, 'intercept': 0, 'slope_exact': '1', 'intercept_exact': '0'},
             'upper': {'slope': 1, 'intercept': 1, 'slope_exact': '1', 'intercept_exact': '1'},
             'left_open': False, 'right_open': False},
        ],
        'parameter_min': -1, 'parameter_max': 1, 'initial': 0,
        'critical_values': [-0.5, 0.5], 'critical_exact_values': ['-1/2', '1/2'],
        'mode': 'explore', 'strategy': 'complement',
    }


def schemas():
    return [json.loads((ROOT / 'internal/schemas' / name).read_text()) for name in (
        'graph-step-interaction-v1.schema.json', 'graph-math-step-v2.schema.json')]


def validate_boards(pending, completed):
    interaction_schema, math_schema = schemas()
    for board, schema, fragment in (
        (pending, interaction_schema, interaction_schema['$defs']['part']['properties']['stem_board']),
        (completed, math_schema, math_schema['properties']['highlight']),
    ):
        Draft202012Validator({'$defs': schema['$defs'], **fragment}).validate(board)


def test_explorer_is_preserved_as_an_object_in_pending_and_completed_cards(monkeypatch):
    graph = explorer()
    board = {'layout': 'derivation', 'caption': '观察共同输入', 'connector': '⇒',
             'items': [{'label': '两个范围', 'math': 'I_1,I_2'},
                       {'label': '共同输入', 'math': r'I_1\cap I_2\ne\varnothing'}],
             'interval_explorer': graph}
    prepared = {
        'domain_explanation': '观察交集。', 'derivation_caption': board['caption'],
        'derivation_left_label': '两个范围', 'derivation_left_math': 'I_1,I_2', 'derivation_left_note': '',
        'derivation_right_label': '共同输入', 'derivation_right_math': r'I_1\cap I_2\ne\varnothing',
        'interval_explorer': graph,
    }
    registry = json.loads((ROOT / 'site/data/knowledge-next/execution/presentation-registry.json').read_text())
    spec = registry['templates']['abstract_domain_parameter_derivation']
    presentation_templates.validate_registry({'templates': {'parameter': spec}, 'case_prefix': ''})
    monkeypatch.setitem(presentation_templates.PREPARERS, 'abstract_domain_parameter_view', lambda _: prepared)
    highlight = presentation_templates.render_highlight(spec, {})
    monkeypatch.setattr(abstract_parameter_presentation, 'phase_view', lambda _: {
        'title': '观察共同输入', 'question': '交集何时非空？', 'derivation': board,
        'interaction': {'type': 'read'}, 'expected_answer': {}, 'feedback': {'answer': '观察交集。'},
    })
    pending = abstract_parameter_presentation.compile_parameter([{'values': {}}], 'parameter')['parts'][0]['stem_board']
    assert pending['items'][1]['math'] is None
    assert highlight['items'][1]['math']
    assert pending['interval_explorer'] == highlight['interval_explorer'] == graph
    assert pending['interval_explorer'] is not graph and highlight['interval_explorer'] is not graph
    validate_boards(pending, highlight)
    graph['intervals'][0]['lower']['slope'] = 123
    assert pending['interval_explorer']['intervals'][0]['lower']['slope'] == -1
    assert highlight['interval_explorer']['intervals'][0]['lower']['slope'] == -1


def test_none_explorer_is_omitted_and_undeclared_template_path_is_rejected(monkeypatch):
    spec = {'title': '观察', 'explanation': '', 'required_bindings': [],
            'prepare': 'abstract_domain_parameter_view',
            'highlight': {'layout': 'derivation', 'caption': '观察', 'connector': '⇒',
                          'items': [{'label': '已知', 'math': 'I_1'}, {'label': '结果', 'math': 'I_2'}],
                          'interval_explorer': 'interval_explorer'}}
    monkeypatch.setitem(presentation_templates.PREPARERS, 'abstract_domain_parameter_view',
                        lambda _: {'interval_explorer': None})
    assert 'interval_explorer' not in presentation_templates.render_highlight(spec, {})
    spec['highlight']['interval_explorer'] = 'unregistered_object'
    with pytest.raises(ValueError, match='unknown_template_binding'):
        presentation_templates.validate_registry({'templates': {'parameter': spec}, 'case_prefix': ''})


@pytest.mark.parametrize('change', ['unknown_answer', 'string_coefficient', 'non_boolean_endpoint', 'bad_mode', 'string_object'])
def test_both_schema_boundaries_reject_malformed_explorers(change):
    interaction_schema, math_schema = schemas()
    assert interaction_schema['$defs']['interval_explorer'] == math_schema['$defs']['interval_explorer']
    graph = explorer()
    if change == 'unknown_answer':
        graph['correct_parameter_range'] = '[-1/2,1/2]'
    elif change == 'string_coefficient':
        graph['intervals'][0]['lower']['slope'] = '-1'
    elif change == 'non_boolean_endpoint':
        graph['intervals'][0]['left_open'] = 0
    elif change == 'bad_mode':
        graph['mode'] = 'answer'
    else:
        graph = json.dumps(graph)
    board = {'layout': 'derivation', 'caption': '观察', 'connector': '⇒',
             'items': [{'label': '已知', 'math': 'I_1'}, {'label': '结果', 'math': None}],
             'interval_explorer': graph}
    for schema, fragment, complete in (
        (interaction_schema, interaction_schema['$defs']['part']['properties']['stem_board'], False),
        (math_schema, math_schema['properties']['highlight'], True),
    ):
        value = deepcopy(board)
        if complete:
            value['items'][1]['math'] = 'I_2'
        with pytest.raises(ValidationError):
            Draft202012Validator({'$defs': schema['$defs'], **fragment}).validate(value)


@pytest.mark.parametrize('invalid', ['1/0', '1.5', '1e20', '--1', '1/-3', 'x', ''])
def test_exact_explorer_coefficients_and_cuts_require_rational_strings(invalid):
    for schema in schemas():
        validator = Draft202012Validator(schema['$defs']['interval_explorer'])
        for field in ('slope_exact', 'intercept_exact', 'critical_exact_values'):
            graph = explorer()
            if field == 'critical_exact_values':
                graph[field] = [invalid]
            else:
                graph['intervals'][0]['lower'][field] = invalid
            with pytest.raises(ValidationError):
                validator.validate(graph)


@pytest.mark.parametrize('cuts', [
    ['-1/3', '1/3'],
    ['0', '1/100000000000000000000'],
    ['19999999999999999/2', '10000000000000000', '20000000000000001/2'],
])
def test_exact_explorer_contract_preserves_close_or_nonterminating_rationals(cuts):
    from fractions import Fraction

    interaction, math = schemas()
    assert interaction['$defs']['interval_explorer'] == math['$defs']['interval_explorer']
    graph = explorer()
    graph['critical_exact_values'] = cuts
    graph['critical_values'] = [float(Fraction(value)) for value in cuts]
    graph['intervals'][0]['lower'].update(slope=1 / 3, slope_exact='1/3',
                                        intercept=1e16, intercept_exact='10000000000000000')
    graph['intervals'][0]['upper'].update(intercept=1e16, intercept_exact='10000000000000001')
    for schema in (interaction, math):
        Draft202012Validator(schema['$defs']['interval_explorer']).validate(graph)
    assert json.loads(json.dumps(graph)) == graph
