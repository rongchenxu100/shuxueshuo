"""FR-T3 P2: all roots, original branch domains, and student-visible evidence."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import Draft202012Validator

from shuxueshuo_server.graph_lesson import piecewise_equation as pe
from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.piecewise_equation_presentation import (
    compile_piecewise,
    phase_views,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
from shuxueshuo_server.graph_lesson.stage_two.piecewise_surface import source_spans
from shuxueshuo_server.learning.graph_walk import grade

ROOT = Path(__file__).resolve().parents[3]
TARGET = '/root/goals/0'


def candidate(definition='f(x)=piecewise(x^2+1,x>0,-2*x+2,x<=0)', equation='f(x)=5'):
    return {'original_text': r'已知 $f(x)=\begin{cases}x^2+1,&x>0\\-2x+2,&x\le0\end{cases}$，若 $f(x)=5$，则 $x$ 的值为（）。',
            'root': {'definitions': [definition], 'facts': [equation], 'goals': [{'kind': 'find_range', 'symbol': 'x'}]}}


def run(c):
    ctx = build_context(c, TARGET)
    assert pe.admitted(ctx), ctx.get('piecewise_equation')
    roots = pe.solve_branches(ctx)['outputs']
    result = pe.filter_branches(roots['description'], decode_value(encode_value(roots['branch_roots'])))['outputs']
    return ctx, {**roots, **result}


def test_all_branch_roots_are_filtered_and_independently_verified(monkeypatch):
    c = candidate()
    ctx, result = run(c)
    assert result['feasible_set'] == sp.FiniteSet(-sp.Rational(3, 2), 2)
    first, second = result['branch_results']
    assert first['candidates'] == sp.FiniteSet(-2, 2)
    assert first['accepted'] == sp.FiniteSet(2) and first['rejected'] == sp.FiniteSet(-2)
    assert second['accepted'] == sp.FiniteSet(-sp.Rational(3, 2))
    monkeypatch.setattr(pe, 'solve_branches', lambda *_: pytest.fail('verifier must be independent'))
    assert pe.independent_verify(c, TARGET, ctx, result['feasible_set'])['status'] == 'verified'
    assert pe.independent_verify(c, TARGET, ctx, result['feasible_set'] | sp.FiniteSet(-2))['status'] == 'math_failed'
    assert pe.independent_verify(c, TARGET, ctx, sp.FiniteSet(2))['status'] == 'math_failed'
    assert pe.endpoints(c, TARGET, result['feasible_set'])['status'] == 'passed'
    for field, value in [('domain', sp.S.Reals), ('candidates', sp.FiniteSet(2)), ('accepted', sp.FiniteSet(-2, 2))]:
        bad = deepcopy(result['branch_results']); bad[0][field] = value
        assert not pe.verify_rows(result['description'], bad)
    changed = candidate(equation='f(x)=6')
    assert pe.independent_verify(changed, TARGET, ctx, result['feasible_set'])['status'] == 'math_failed'


@pytest.mark.parametrize(('definition', 'equation', 'expected'), [
    ('f(t)=piecewise(t^2,t>0,t+1,t<=0)', 'f(x)=0', sp.FiniteSet(-1)),
    ('f(t)=piecewise(t^2,t>=0,t+1,t<0)', 'f(x)=0', sp.FiniteSet(-1, 0)),
    ('f(x)=piecewise(x^2,x<0,x,x>0)', 'f(x)=0', sp.S.EmptySet),
    ('f(x)=piecewise(5,x<0,4,x>=0)', '5=f(x)', sp.Interval.open(-sp.oo, 0)),
    ('f(x)=piecewise(x^2,x<=0,x,x>0)', 'f(x)=2', sp.FiniteSet(-sp.sqrt(2), 2)),
])
def test_boundary_gaps_constant_branches_and_irrational_roots(definition, equation, expected):
    c = candidate(definition, equation)
    ctx, result = run(c)
    assert result['feasible_set'] == expected
    assert pe.independent_verify(c, TARGET, ctx, expected)['status'] == 'verified'
    assert pe.endpoints(c, TARGET, expected)['status'] == 'passed'


@pytest.mark.parametrize(('definition', 'equation'), [
    ('f(x)=piecewise(x,x<=0,x^2,x>=0)', 'f(x)=5'),
    ('f(x)=piecewise(1/x,x>0,x,x<=0)', 'f(x)=5'),
    ('f(x)=piecewise(x/0,x>0,x,x<=0)', 'f(x)=5'),
    ('f(x)=piecewise(x^3,x>0,x,x<=0)', 'f(x)=5'),
    ('f(x)=piecewise(x^2+1,x>0,-2*x+2,x<=0)', 'f(f(x))=5'),
])
def test_unsupported_sources_do_not_enter_the_route(definition, equation):
    assert not pe.inspect_target(candidate(definition, equation), TARGET)['structure_supported']


def test_additional_conditions_and_uncertainties_are_not_ignored():
    for key, extra in [('facts', 'x>0'), ('uncertainties', {'kind': 'ambiguous_symbol', 'text': '分界点不清'})]:
        c = candidate()
        c['root'].setdefault(key, []).append(extra)
        description = pe.inspect_target(c, TARGET)
        assert not description['structure_supported']
        if key == 'uncertainties':
            assert description['reason'] == 'piecewise_equation.unresolved_source'


def test_original_source_matching_and_complete_interactive_derivations():
    c = candidate()
    _, data = run(c)
    desc = data['description']
    def spans(value):
        return source_spans(value, TARGET, [(0, len(value['original_text']))], desc, _abstract_formula_matches)
    assert len(spans(c)) == 3
    for old, new in [(r'x\le0', 'x<0'), ('f(x)=5', 'f(x)=6'), (r'\\-2x+2,&x\le0', '')]:
        changed = deepcopy(c); changed['original_text'] = changed['original_text'].replace(old, new)
        assert spans(changed) is None
    schema = json.loads((ROOT/'internal/schemas/graph-step-interaction-v1.schema.json').read_text())
    validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/part'})
    for phase in ('branches', 'merge'):
        values = {**data, 'phase': phase}
        views = phase_views(values)
        parts = compile_piecewise([{'values': encode_value(values)}], 'a'*24)['parts']
        for part, view in zip(parts, views, strict=True):
            validator.validate(part)
            assert '$$' not in part['question']
            assert part['stem_board']['items'][1]['math'] is None
            assert '=' in view['proof']
            answer = part['expected_answer']['one_of'][0]
            assert grade(part, {'value': answer}, 'piecewise-equation') == 'passed'
            wrong = next(o['value'] for o in part['interaction']['options'] if o['value'] != answer)
            assert grade(part, {'value': wrong}, 'piecewise-equation') != 'passed'
    views = phase_views({**data, 'phase': 'branches'})
    assert len(views) == 4 and 'x>0' in views[1]['question'] and r'x\le 0' in views[3]['question']
    assert r'\text{舍去}' in views[1]['proof']


def test_native_contract_selection_and_frozen_modules():
    from shuxueshuo_server.graph_lesson.stage_one.extraction import frozen_files
    from shuxueshuo_server.graph_lesson.stage_three.execution_contracts import (
        load_contracts,
    )
    from shuxueshuo_server.graph_lesson.stage_three.runner import fingerprint
    from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
    feature_result = candidate_features(candidate())
    assert feature_result['ok'], feature_result['diagnostics']
    assert pe.METHOD in load_contracts()
    selected = evaluate_goal(candidate(), TARGET, [], 'type-piecewise-function')
    assert selected['d4']['options'][0]['method'] == pe.METHOD
    path = 'server/shuxueshuo_server/graph_lesson/piecewise_equation.py'
    assert path in frozen_files() and path in fingerprint()


def test_reading_card_survives_source_fragment_projection():
    from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
    from shuxueshuo_server.search.lesson import d1_rows
    c = candidate()
    features = candidate_features(c)['features']
    fragments = build_d1(c, TARGET, features, {'items': []})
    assert not fragments['diagnostics'] and len(fragments['fragments']) == 3
    lesson = d1_rows(TARGET, fragments['fragments'], {'piecewise_equation': pe.inspect_target(c, TARGET)}, c['original_text'])
    assert len(lesson['rows']) == 1
    assert lesson['rows'][0]['source_refs'] == [TARGET]
    assert '全部' in lesson['summary']
    assert lesson['rows'][0]['quote'][0]['text'] == '$x$'


def test_printed_values_match_the_whole_solution_and_follow_option_order():
    from shuxueshuo_server.graph_lesson.stage_three.choice_matching import (
        match_original_choice,
    )
    from shuxueshuo_server.graph_lesson.stage_three.goals import finalize_goal
    c = candidate()
    solution = sp.FiniteSet(-sp.Rational(3, 2), 2)
    answer = finalize_goal(c['root']['goals'][0], solution)
    options = [r'$-\frac32$', '$2$', r'$-\frac32,\ 2$', r'$-2,\ -\frac32$']

    def matched(values):
        source = deepcopy(c)
        source['original_text'] += '\n' + '\n'.join(f'{k}. {v}' for k, v in zip('ABCD', values, strict=True))
        before = deepcopy(source)
        result = match_original_choice(source, TARGET, answer, encode_value(solution))
        assert source == before
        return result

    result = matched(options)
    assert result['status'] == 'matched' and result['correct_labels'] == ['C']
    assert result['options'][2]['text'] == options[2]
    assert matched([options[2], options[0], options[1], options[3]])['correct_labels'] == ['A']
    for bad in ['$x,2$', '$1/0,2$', '$-3/2,$', '以上都对']:
        assert matched([*options[:2], bad, options[3]])['status'] == 'unavailable'
    # Parentheses remain an interval; they must not be read as two roots.
    assert matched([*options[:2], '$(-3/2,2)$', options[3]])['correct_labels'] == []
