"""Exact recurrence prefix bounds, source binding and actual shared method execution."""
import json
from copy import deepcopy

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson.recurrence_extremum import (
    describe,
    relevant,
    solve,
    verify,
)
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.contracts import result_schema
from shuxueshuo_server.graph_lesson.stage_three.extremum_runtime import select
from shuxueshuo_server.graph_lesson.stage_two.extremum_surface import source_spans
from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
from tests.solver.test_graph_monotonicity_photo_regressions import (
    FIXTURES,
    TARGET,
    candidate,
)


def spec(origin=0, length=2, scale=2, coefficient=1, threshold=-3):
    facts = ['Dom(h)=ℝ', f'h(z+{length})={scale}*h(z)',
             f'∀z∈({origin},{origin+length}]:h(z)={coefficient}*(z-({origin}))*(z-({origin+length}))',
             f'∀z∈(-∞,b]:h(z)>={threshold}']
    return describe({'kind': 'find_maximum', 'expression': 'b'}, TARGET,
                    [{'source_ref': f'/root/facts/{i}', 'expression': f} for i, f in enumerate(facts)])


@pytest.mark.parametrize('args,expected', [
    ({}, sp.Rational(9, 2)),
    ({'origin': 1, 'length': 4, 'scale': 3, 'coefficient': 2, 'threshold': -20}, 7-sp.sqrt(6)/3),
    ({'threshold': -1}, 3-sp.sqrt(2)/2),
    ({'threshold': '-1/8'}, -3-sp.sqrt(2)/2),
    ({'origin': -5, 'scale': 3, 'threshold': -10}, 2-sp.sqrt(51)/9),
])
def test_shift_scale_coefficients_and_negative_blocks(args, expected, monkeypatch):
    d = spec(**args)
    assert d['structure_supported']
    model = solve(d)
    assert sp.simplify(model['value']-expected) == 0
    monkeypatch.setattr('shuxueshuo_server.graph_lesson.recurrence_extremum.solve',
                        lambda *_: pytest.fail('solver called by verifier'))
    assert verify(d, model)
    for field, bad in [('block', model['block']+1), ('value', expected+1),
                       ('offset', model['length']-model['offset']), ('threshold', 0), ('children', [])]:
        assert not verify(d, {**model, field: bad})


@pytest.mark.parametrize('args', [{'scale': 1}, {'scale': -2}, {'threshold': 0}, {'coefficient': -1}])
def test_unsupported_recurrences_do_not_inherit_a_certificate(args):
    d = spec(**args)
    assert not d['structure_supported']
    assert not verify(d, solve(spec()))


def test_global_domain_declaration_and_every_condition_are_required():
    d = spec()
    for i in range(len(d['given_definitions'])):
        entries = deepcopy(d['given_definitions'])
        entries.pop(i)
        assert not describe(d['source'], TARGET, entries)['structure_supported']
    assert not relevant({'kind': 'find_maximum', 'expression': 'a'},
                        [{'expression': 'f(x)=x^2'}, {'expression': 'a>0'}])


def test_real_photo_recurrence_compiles_binds_and_executes_shared_method():
    value = candidate('b15')
    assert validate_candidate(value)['contract_valid']
    context = build_context(value, TARGET)
    selected = select(context, {'rule': 'rule-monotonicity-extremum-method'}, 'type-monotonicity-extremum')
    schema = result_schema()
    Draft202012Validator({'$ref': '#/$defs/D3', '$defs': schema['$defs']}).validate(selected['d3'])
    assert selected['d3']['interaction']['type'] == 'read'
    description = context['extremum_goal']
    text = value['original_text']
    spans = source_spans(value, TARGET, [(0, len(text))], description, _abstract_formula_matches)
    assert spans and len(spans) == 7
    altered = deepcopy(value)
    altered['original_text'] = text.replace('对任意', '存在')
    assert source_spans(altered, TARGET, [(0, len(altered['original_text']))], description,
                        _abstract_formula_matches) is None
    state = driver.create_state(features=extract_features(value)['features'], context=context,
                                method='method-monotonicity-extremum', route_id='monotonicity-extremum',
                                branch='recurrence', target_ref=TARGET, run_id='recurrence', lesson_version='v1')
    for _ in range(200):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    assert driver.export_values(state)['extremum_result']['value'] == sp.Rational(9, 2)
    chunks, pending = interaction.compile_route(state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert chunks and not pending
    assert all(chunk['status'] == 'interactive' for chunk, _ in chunks)


def test_unknown_function_calls_without_a_declaration_stay_invalid():
    value = candidate('b15')
    value['root']['facts'].pop(0)
    assert not validate_candidate(value)['contract_valid']


def test_plain_real_set_spelling_is_bound_only_in_the_declared_domain():
    value = json.loads((FIXTURES.parent / 'fifth/b15/result.json').read_text())['candidate']
    context = build_context(value, TARGET)
    for name, expected in [('R', True), ('\\mathbf{R}', True), ('Q', False), ('R+1', False)]:
        changed = deepcopy(value)
        changed['original_text'] = value['original_text'].replace('$R$', '$'+name+'$')
        spans = source_spans(changed, TARGET, [(0, len(changed['original_text']))], context['extremum_goal'],
                             _abstract_formula_matches)
        assert bool(spans) is expected
