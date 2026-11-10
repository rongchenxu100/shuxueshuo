"""Boundary regressions discovered by the full worksheet's real model output."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.extremum_math import (
    numeric_model,
    parameter_model,
    verify_numeric,
    verify_parameter,
)
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_two import (
    extremum_surface,
    monotonicity_inequality_surface,
    monotonicity_surface,
)
from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches

FIXTURES = Path(__file__).parents[1] / 'search/fixtures/function-monotonicity-topic/second'
TARGET = '/root/goals/0'


def candidate(key):
    value = json.loads((FIXTURES / key / 'workflow/candidate.json').read_text())
    value.pop('public_content', None)
    return value


@pytest.mark.parametrize('key,field,module', [
    ('a03', 'monotonicity_goal', monotonicity_surface),
    ('a16', 'extremum_goal', extremum_surface),
    ('b08', 'extremum_goal', extremum_surface),
    ('b13', 'mono_inequality_goal', monotonicity_inequality_surface),
])
def test_equivalent_source_spellings_keep_exact_original_spans(key, field, module):
    value = candidate(key)
    assert validate_candidate(value)['contract_valid']
    assert extract_features(value)['ok']
    description = build_context(value, TARGET)[field]
    text = value['original_text']
    assert module.source_spans(value, TARGET, [(0, len(text))], description, _abstract_formula_matches)
    altered = deepcopy(value)
    # Same structured data with a contradictory visible formula must not bind.
    changes = {'a03': ('4x', '5x'), 'a16': ('[-2,2]', '[-3,2]'),
               'b08': ('x-a', 'x+a'), 'b13': ('[0,+∞)', '[1,+∞)')}
    old, new = changes[key]
    assert old in text
    altered['original_text'] = text.replace(old, new)
    assert module.source_spans(altered, TARGET, [(0, len(altered['original_text']))], description,
                               _abstract_formula_matches) is None


def test_implicit_extremum_binder_uses_only_the_formal_argument(monkeypatch):
    value = candidate('b08')
    d = build_context(value, TARGET)['extremum_goal']
    model = parameter_model(d)
    assert model['feasible_set'] == sp.Interval(0, 2)
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.extremum_math.parameter_model',
                        lambda *_: pytest.fail('solver called by verifier'))
    assert verify_parameter(d, model)
    for fact in ('min_{a}(f(x))=f(0)', 'min(f(a))=f(0)'):
        bad = deepcopy(d)
        bad['given_definitions'][-1]['expression'] = fact
        assert not verify_parameter(bad, model)


def test_output_alias_does_not_consume_an_extra_constraint():
    from shuxueshuo_server.graph_lesson.function_monotonicity import describe
    value = candidate('a03')
    goal = value['root']['goals'][0]
    entries = [{'source_ref': '/root/definitions/0', 'expression': 'y=-x^2+4*x+3'}]
    assert describe(goal, TARGET, entries)['structure_supported']
    assert not describe(goal, TARGET, [*entries, {'source_ref': '/root/facts/0', 'expression': 'y>0'}])['structure_supported']
    assert not describe({**goal, 'variable': 'y', 'expression': '-y^2+4*y+3'}, TARGET,
                        [{'source_ref': '/root/definitions/0', 'expression': 'y=-y^2+4*y+3'}])['structure_supported']


def test_correct_radical_transcription_has_minimum_three_as_a_math_only_check():
    # Deliberately authored mathematical input, never substituted into the
    # retained model response or counted as real-photo acceptance.
    value = candidate('a14')
    value['root'] = {'definitions': ['f(x)=sqrt(1-2*x)+2*x^2-5*x+5'],
                     'goals': [{'kind': 'find_range', 'object': 'f',
                                'answer_request': {'kind': 'extremum', 'quantity': 'minimum'}}]}
    d = build_context(value, TARGET)['extremum_goal']
    model = numeric_model(d)
    assert verify_numeric(d, model)
    assert model['attained'] and model['value'] == 3
