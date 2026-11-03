"""FR-T3 P2b: source thresholds, strictness, branch domains and progressive cards."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator
from shuxueshuo_server.graph_lesson import piecewise_inequality as pi
from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.piecewise_inequality_presentation import (
    compile_piecewise,
    phase_views,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.learning.graph_walk import grade

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'
ANSWER = sp.Union(sp.Interval.open(-3, 1), sp.Interval.open(3, sp.oo))


def candidate(definition=None, relation=None):
    value = json.loads((ROOT/'internal/senior-high/authored-courses/piecewise-p2-20261102/b10-v2.json').read_text())['candidate']
    if definition:
        value['root']['definitions'] = [definition]
    if relation:
        value['root']['facts'] = [relation]
    return value


def run(c):
    ctx = build_context(c, TARGET)
    assert pi.admitted(ctx), ctx.get('piecewise_inequality')
    level = pi.evaluate_level(ctx)['outputs']
    roots = pi.solve_roots(**level)['outputs']
    signs = pi.solve_signs(**level, **decode_value(encode_value(roots)))['outputs']
    result = pi.filter_branches(**level, **decode_value(encode_value(signs)))['outputs']
    return ctx, {**level, **result}


def test_original_threshold_branches_and_independent_full_set_verification(monkeypatch):
    c = candidate()
    ctx, result = run(c)
    assert result['level'] == 3 and result['feasible_set'] == ANSWER
    first, second = result['branch_results']
    assert first['accepted'] == sp.Union(sp.Interval.Ropen(0, 1), sp.Interval.open(3, sp.oo))
    assert second['accepted'] == sp.Interval.open(-3, 0)
    assert 0 in result['feasible_set']
    monkeypatch.setattr(pi, 'solve_signs', lambda *_: pytest.fail('verification must be independent'))
    assert pi.independent_verify(c, TARGET, ctx, ANSWER)['status'] == 'verified'
    for bad in [ANSWER-sp.FiniteSet(0), ANSWER|sp.FiniteSet(1), first['accepted']]:
        assert pi.independent_verify(c, TARGET, ctx, bad)['status'] == 'math_failed'
    assert pi.independent_verify(candidate(relation='f(x)>=f(1)'), TARGET, ctx, ANSWER)['status'] == 'math_failed'
    boundary = pi.endpoints(c, TARGET, ANSWER)
    assert boundary['status'] == 'passed'
    assert {p['point']['expression']: p['included'] for p in boundary['points']} == {'-3': False, '0': True, '1': False, '3': False}
    for key, value in [('domain', sp.S.Reals), ('positive_expression', sp.S.Zero), ('accepted', sp.S.Reals), ('roots', [])]:
        bad = deepcopy(result['branch_results']); bad[0][key] = value
        assert not pi.verify_rows(result['description'], 3, bad)
    assert not pi.verify_rows(result['description'], 4, result['branch_results'])


@pytest.mark.parametrize(('definition', 'relation', 'expected'), [
    (None, 'f(x)>=f(1)', sp.Union(sp.Interval(-3, 1), sp.Interval(3, sp.oo))),
    (None, 'f(1)<f(x)', ANSWER),
    (None, 'f(x)<=f(1)', sp.Union(sp.Interval(-sp.oo, -3), sp.Interval(1, 3))),
    ('f(t)=piecewise(t^2,t>=0,t+1,t<0)', 'f(x)>f(0)', sp.Interval.open(-1, 0)|sp.Interval.open(0, sp.oo)),
    ('f(t)=piecewise(0,t<=0,t^2,t>0)', 'f(x)>=0', sp.S.Reals),
    ('f(x)=piecewise(0,x<0,0,x>0)', 'f(x)>0', sp.S.EmptySet),
    ('f(x)=piecewise(x^2,x<0,x,x>0)', 'f(x)<2', sp.Interval.open(-sp.sqrt(2), 0)|sp.Interval.open(0, 2)),
])
def test_strict_closed_reversed_constant_gap_and_irrational_cases(definition, relation, expected):
    c = candidate(definition, relation)
    ctx, result = run(c)
    assert result['feasible_set'] == expected
    assert pi.independent_verify(c, TARGET, ctx, expected)['status'] == 'verified'
    assert pi.endpoints(c, TARGET, expected)['status'] == 'passed'


@pytest.mark.parametrize(('definition', 'relation'), [
    ('f(x)=piecewise(x,x<0,x^2,x>0)', 'f(x)>f(0)'),
    ('f(x)=piecewise(x,x<=0,x^2,x>=0)', 'f(x)>f(1)'),
    ('f(x)=piecewise(1/x,x<0,x,x>=0)', 'f(x)>1'),
    ('f(x)=piecewise(x^3,x<0,x,x>=0)', 'f(x)>1'),
    (None, 'f(x)>f(f(1))'),
    (None, 'f(x)>x'),
    (None, 'f(f(x))>1'),
])
def test_unsupported_sources_are_refused(definition, relation):
    assert not pi.inspect_target(candidate(definition, relation), TARGET)['structure_supported']


def test_additional_conditions_and_source_uncertainties_are_preserved():
    for field, extra in [('facts', 'x>0'), ('uncertainties', {'kind': 'ambiguous_symbol', 'text': '分界点不清'})]:
        c = candidate(); c['root'].setdefault(field, []).append(extra)
        assert not pi.inspect_target(c, TARGET)['structure_supported']


def test_source_reading_selection_original_options_and_frozen_contracts():
    from shuxueshuo_server.graph_lesson.stage_one.extraction import frozen_files
    from shuxueshuo_server.graph_lesson.stage_three.choice_matching import (
        match_original_choice,
    )
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import (
        load_contracts,
    )
    from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal
    from shuxueshuo_server.graph_lesson.stage_three.runner import fingerprint
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
    from shuxueshuo_server.search.lesson import d1_rows
    c = candidate(); features = candidate_features(c)
    assert features['ok'], features['diagnostics']
    assert pi.METHOD in load_contracts()
    selected = evaluate_goal(c, TARGET, features['features'], 'type-piecewise-function')
    assert selected['d4']['options'][0]['method'] == pi.METHOD
    fragments = build_d1(c, TARGET, features['features'], {'items': []})
    assert not fragments['diagnostics'] and len(fragments['fragments']) == 3
    rows = d1_rows(TARGET, fragments['fragments'], {'piecewise_inequality': pi.inspect_target(c, TARGET)}, c['original_text'])
    assert len(rows['rows']) == 1 and '不等式' in rows['summary']
    bad = deepcopy(c); bad['original_text'] = bad['original_text'].replace('f(x)>f(1)', 'f(x)>=f(1)')
    assert build_d1(bad, TARGET, features['features'], {'items': []})['diagnostics']
    answer = finalize_goal(c['root']['goals'][0], ANSWER)
    assert match_original_choice(c, TARGET, answer, encode_value(ANSWER))['correct_labels'] == ['A']
    path = 'server/shuxueshuo_server/graph_lesson/piecewise_inequality.py'
    assert path in frozen_files() and path in fingerprint()


def test_progressive_cards_include_context_math_derivations_and_graphs():
    _, data = run(candidate())
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'})
    for phase in ('level', 'branches', 'merge'):
        values = {**data, 'phase': phase}
        views = phase_views(values)
        parts = compile_piecewise([{'values': encode_value(values)}], 'b'*24)['parts']
        for part, view in zip(parts, views, strict=True):
            validator.validate(part)
            assert part['stem_board']['items'][1]['math'] is None
            assert '=' in view['proof'] or '>' in view['proof']
            answer = part['expected_answer']['one_of'][0]
            assert grade(part, {'value': answer}, 'piecewise-inequality') == 'passed'
            wrong = next(o['value'] for o in part['interaction']['options'] if o['value'] != answer)
            assert grade(part, {'value': wrong}, 'piecewise-inequality') != 'passed'
        if phase == 'branches':
            assert len(parts) == 4 and 'x\\ge 0' in parts[1]['question']
            # Both disjoint intervals must be intersected with the branch domain.
            assert r'\right)\cap' in views[1]['proof']
            assert parts[0]['graph']['kind'] == 'quadratic'
            assert 'markSign' not in parts[0]['graph']['params']
            assert parts[0]['completion_graph']['params']['markSign'] == 'above'
