"""FM-T4: bounded families, original conditions, and their shared teaching route."""
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.monotonicity_parameter_math import (
    describe,
    solve,
    verify,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

ROOT = Path(__file__).resolve().parents[3]
RECORDS = ROOT / 'internal/senior-high/authored-courses/function-monotonicity-t4-20261109'
TARGET = '/root/goals/0'


def source(name):
    record = json.loads((RECORDS / f'{name}.json').read_text())
    candidate = record['candidate']
    entries = [{'source_ref': f'/root/{field}/{i}', 'expression': text}
               for field in ('definitions', 'facts')
               for i, text in enumerate(candidate['root'].get(field, []))]
    return record, describe(candidate['root']['goals'][0], TARGET, entries)


@pytest.mark.parametrize('name,gold', [
    ('a05', sp.Interval(-sp.oo, 2)),
    ('a09', sp.Interval(5, sp.oo)),
    ('a11', sp.Interval(-sp.oo, 0)),
])
def test_r0_gold_and_independent_verification(name, gold):
    _, d = source(name)
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['feasible_set'] == gold
    assert verify(d, m)
    assert verify(d, decode_value(encode_value(m)))
    bad = deepcopy(m)
    bad['feasible_set'] = gold ^ sp.FiniteSet(0)
    assert not verify(d, bad)


def test_a11_keeps_zero_coefficient_linear_case():
    _, d = source('a11')
    m = solve(d)
    zero = next(case for case in m['cases'] if case['premise'] == 'zero')
    assert zero['kept'] and zero['feasible'] == sp.FiniteSet(0)
    assert m['feasible_set'].contains(0) is True or m['feasible_set'].contains(0) is sp.S.true


def test_a05_endpoint_axis_allowed_and_exterior_excluded():
    _, d = source('a05')
    m = solve(d)
    assert m['feasible_set'].contains(2) in (True, sp.S.true)
    assert m['feasible_set'].contains(3) in (False, sp.S.false)


def test_feature_routes_required_monotonicity():
    from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features

    record, _ = source('a05')
    features = candidate_features(record['candidate'])
    values = {row['feature_id']: row.get('value') for row in features['features']}
    assert values.get('monotonicity_parameter', {}).get('structure_supported')
    for foreign in ('monotonicity_inequality', 'function_extremum'):
        foreign_value = values.get(foreign)
        assert not (isinstance(foreign_value, dict) and foreign_value.get('structure_supported'))


def test_admission_and_analyze_roundtrip():
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_runtime import (
        admitted,
        analyze,
    )

    record, _ = source('a09')
    context = build_context(record['candidate'], TARGET)
    assert admitted(context)
    out = analyze(context)
    assert out['outputs']['mono_parameter_result']['feasible_set'] == sp.Interval(5, sp.oo)


def test_presentation_options_name_parameter():
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_presentation import (
        phase_views,
    )

    _, d = source('a05')
    m = solve(d)
    views = phase_views({'description': d, 'mono_parameter_result': m, 'phase': 'conclude'})
    assert views
    labels = [row['label'].strip('$') for row in views[0]['interaction']['options']]
    assert labels
    assert all(label.startswith(r'm\in') for label in labels)
    assert not any(label.startswith((r'\left(', '[', '('))
                   for label in labels)


@pytest.mark.parametrize('name,gold,basis', [
    ('a06', sp.Interval.Lopen(-2, sp.Rational(4, 5)), 'stated'),
    ('a08', sp.Interval.Lopen(0, sp.Rational(5, 3)), 'difference_quotient'),
    ('a17', sp.Interval.Ropen(sp.Rational(1, 6), sp.Rational(1, 3)), 'difference_product'),
])
def test_r1_piecewise_gold_and_independent_verification(name, gold, basis):
    _, d = source(name)
    assert d['structure_supported'], d['reason']
    assert d['family'] == 'piecewise_parameter'
    assert d['basis_kind'] == basis and d['piece_count'] == 2
    m = solve(d)
    assert m['structure'] == 'piecewise'
    assert m['feasible_set'] == gold
    assert verify(d, m)
    assert verify(d, decode_value(encode_value(m)))
    # Dropping the breakpoint condition or flipping an endpoint must be rejected.
    pieces_only = deepcopy(m)
    pieces_only['feasible_set'] = sp.Intersection(*(piece['feasible'] for piece in m['pieces']))
    assert pieces_only['feasible_set'] != gold
    assert not verify(d, pieces_only)
    flipped = deepcopy(m)
    flipped['feasible_set'] = gold ^ sp.FiniteSet(gold.inf, gold.sup)
    assert not verify(d, flipped)


def test_r1_join_relation_is_non_strict():
    _, d = source('a06')
    m = solve(d)
    join = m['joins'][0]
    assert join['point'] == 1 and join['relation'] == '<='
    assert join['feasible'] == sp.Interval(-sp.oo, sp.Rational(4, 5))


def _variant(name, **changes):
    record, _ = source(name)
    goal = deepcopy(record['candidate']['root']['goals'][0])
    goal['required_monotonicity'].update(changes)
    return describe(goal, TARGET, [])


def test_basis_direction_must_match_requirement():
    d = _variant('a08', direction='increasing')
    assert not d['structure_supported']
    assert 'basis' in d['reason'] or 'direction' in d['reason']


def test_reciprocal_branch_must_avoid_zero():
    d = _variant('a17', expression='piecewise((3*a-1)*x+4*a,x<-1,a/x,x>=-1)')
    assert not d['structure_supported']
    assert 'branch_domain' in d['reason']


def test_r2_a10_needs_turning_point_condition():
    _, d = source('a10')
    assert d['structure_supported'], d['reason']
    m = solve(d)
    gold = sp.Interval(-1, sp.Rational(-1, 2))
    assert m['feasible_set'] == gold
    assert [piece['kind'] for piece in m['pieces']] == ['reciprocal', 'reciprocal_sum']
    assert m['pieces'][1]['feasible'] == sp.Interval(-1, sp.oo)
    assert verify(d, m) and verify(d, decode_value(encode_value(m)))
    # The source's handwritten answer drops the turning-point bound.
    handwritten = deepcopy(m)
    handwritten['feasible_set'] = sp.Interval(-sp.oo, sp.Rational(-1, 2))
    assert not verify(d, handwritten)


@pytest.mark.parametrize('expression,direction,domain,gold', [
    ('piecewise(a/x,0<x<=2,x-a/x-2,x>2)', 'increasing', '(0,+∞)', sp.Interval.Ropen(-4, 0)),
    ('piecewise(a/x,0<x<=1,x+a/x,x>1)', 'decreasing', '(0,+∞)', sp.S.EmptySet),
    ('piecewise(1-x,x<=1,-2*x-a/x,x>1)', 'decreasing', 'ℝ', sp.Interval(-2, 2)),
])
def test_r2_reciprocal_sum_variants(expression, direction, domain, gold):
    d = _variant('a10', expression=expression, direction=direction, input_domain=domain)
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['feasible_set'] == gold
    assert verify(d, m)


def test_r2_parameter_in_linear_coefficient_is_not_admitted():
    d = _variant('a10', expression='piecewise(a/x,0<x<=1,a*x-1/x,x>1)')
    assert not d['structure_supported']
    assert 'branch_family' in d['reason']


def test_r3_a13_intersects_inner_order_with_whole_interval_definition():
    _, d = source('a13')
    assert d['structure_supported'], d['reason']
    assert d['family'] == 'radical_parameter' and d['basis_kind'] == 'difference_quotient'
    m = solve(d)
    assert m['monotone_set'] == sp.Interval(sp.Rational(1, 2), sp.oo)
    assert m['minimum_end'] == -2 and m['minimum_attained']
    assert m['nonnegative_set'] == sp.Interval(-sp.oo, 1)
    assert m['feasible_set'] == sp.Interval(sp.Rational(1, 2), 1)
    assert verify(d, m) and verify(d, decode_value(encode_value(m)))
    # The source's handwritten answer forgets that every input must stay under the root.
    handwritten = deepcopy(m)
    handwritten['feasible_set'] = sp.Interval(sp.Rational(1, 2), sp.oo)
    assert not verify(d, handwritten)


@pytest.mark.parametrize('expression,direction,domain,gold', [
    ('sqrt(x^2-a*x+a)', 'increasing', '[1,+∞)', sp.Interval(-sp.oo, 2)),
    # Least values sit at an open end: only the approached value must be non-negative.
    ('sqrt(x^2-2*a*x+3)', 'decreasing', '(-∞,1)', sp.Interval(1, 2)),
    # A decreasing inner function on [0,+∞) eventually goes below zero.
    ('sqrt(a*x+1)', 'decreasing', '[0,+∞)', sp.S.EmptySet),
])
def test_r3_radical_variants(expression, direction, domain, gold):
    d = _variant('a13', expression=expression, direction=direction, input_domain=domain,
                 basis={'kind': 'stated', 'statement': ''})
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['feasible_set'] == gold
    assert verify(d, m)


def test_r3_root_of_non_polynomial_is_not_admitted():
    d = _variant('a13', expression='sqrt(a/x+1)')
    assert not d['structure_supported']
    assert 'branch_family' in d['reason']


@pytest.mark.parametrize('phase', ['prepare', 'pieces', 'join', 'conclude'])
def test_piecewise_presentation_names_parameter(phase):
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_presentation import (
        phase_views,
    )

    _, d = source('a17')
    m = solve(d)
    views = phase_views({'description': d, 'mono_parameter_result': m, 'phase': phase})
    assert views
    for view in views:
        text = json.dumps(view, ensure_ascii=False)
        assert '左' not in text and '右' not in text
        if phase == 'prepare':
            continue
        options = view.get('interaction', {}).get('options', [])
        assert options
        for option in options:
            assert r'a\in' in option['label']


@pytest.mark.parametrize('facts,gold', [
    (['m>0'], sp.Interval.Lopen(0, 2)),
    (['m>0', 'm!=1'], sp.Union(sp.Interval.open(0, 1), sp.Interval.Lopen(1, 2))),
    (['m∈[0,1]', 'm>0'], sp.Interval.Lopen(0, 1)),
    (['m=1'], sp.FiniteSet(1)),
    (['m>3'], sp.S.EmptySet),
])
def test_original_parameter_conditions_reach_answer_and_verification(facts, gold):
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_presentation import (
        phase_views,
    )
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_runtime import (
        analyze,
        verify_frozen,
    )

    record, _ = source('a05')
    candidate = deepcopy(record['candidate'])
    candidate['root']['facts'] = facts
    context = build_context(candidate, TARGET)
    d = context['mono_parameter_goal']
    m = analyze(context)['outputs']['mono_parameter_result']
    assert m['feasible_set'] == gold
    result = verify_frozen(candidate, TARGET, context, encode_value(m))
    assert result['status'] == 'verified'
    assert {r['source_ref'] for r in result['processing']} == {r['source_ref'] for r in context['entries']}
    # The unconstrained answer must never pass original-problem verification.
    assert not verify(d, dict(m, feasible_set=sp.Interval(-sp.oo, 2)))
    view, = phase_views({'description': d, 'mono_parameter_result': m, 'phase': 'conclude'})
    assert '题设参数条件' in view['derivation']['items'][0]['math']


def test_constrained_parameter_problem_executes_the_shared_method_and_compiles_interactions(tmp_path):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_two.runner import run_result

    record, _ = source('a05')
    candidate = deepcopy(record['candidate'])
    candidate['root']['facts'] = ['m>0']
    candidate['original_text'] += ' 其中 $m>0$。'
    prepared = prepare_authored(candidate, run_id='t4-constrained',
                                sources=record['sources'], reviewer=record['reviewer'])
    stage_two = run_result(prepared, tmp_path / 'stage-two', admission='authored_topic')
    assert stage_two['goals'][0]['primary'] == 'type-monotonicity-parameter'
    assert stage_two['goals'][0]['status'] == 'resolved'
    context = build_context(prepared['candidate'], TARGET)
    state = driver.create_state(
        features=prepared['features'], context=context,
        method='method-monotonicity-parameter', route_id='monotonicity-parameter', branch='parameter',
        target_ref=TARGET, run_id='t4-constrained', lesson_version='v1')
    for _ in range(100):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    model = driver.export_values(state)['mono_parameter_result']
    assert model['feasible_set'] == sp.Interval.Lopen(0, 2)
    assert verify(context['mono_parameter_goal'], model)
    chunks, pending = interaction.compile_route(
        state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert not pending and chunks
    assert all(chunk['status'] in ('interactive', 'readonly') for chunk, _ in chunks)
    parts = [part for chunk, _ in chunks for part in chunk.get('parts', [])]
    assert any('题设参数条件' in part['stem_board']['items'][0]['math'] for part in parts)


@pytest.mark.parametrize('extra', ['x>0', 'n>0', 'f(0)>0', 'g(x)=x^2', 'Dom(f)=[0,1]'])
def test_unhandled_or_conflicting_source_cannot_be_marked_processed(extra):
    record, d = source('a05')
    entries = [*d['given_definitions'], {'source_ref': '/root/facts/0', 'expression': extra}]
    d = describe(record['candidate']['root']['goals'][0], TARGET, entries)
    assert not d['structure_supported']
    with pytest.raises(ValueError):
        solve(d)


@pytest.mark.parametrize('definition,accepted', [
    ('f(x)=5-m*x+x*x', True),
    ('f(x)=x^2+m*x+5', False),
    ('f(x)=x^2-m*x+5+(x-1)/(x-1)-1', False),
])
def test_required_expression_is_checked_against_original_definition(definition, accepted):
    record, _ = source('a05')
    entries = [{'source_ref': '/root/definitions/0', 'expression': definition}]
    d = describe(record['candidate']['root']['goals'][0], TARGET, entries)
    assert d['structure_supported'] is accepted
    if accepted:
        assert verify(d, solve(d))


def test_optional_function_name_can_be_recovered_from_the_definition():
    record, d = source('a05')
    goal = deepcopy(record['candidate']['root']['goals'][0])
    del goal['required_monotonicity']['function']
    inferred = describe(goal, TARGET, d['given_definitions'])
    assert inferred['structure_supported'] and inferred['function'] == 'f'
    assert verify(inferred, solve(inferred))


@pytest.mark.parametrize('domain', ['[a,a+1]', '[a/a,2]', '[sqrt(-1)^2,2]'])
def test_interval_bounds_cannot_hide_parameter_or_definition_obligations(domain):
    assert not _variant('a10', input_domain=domain)['structure_supported']


def test_declared_domain_cannot_hide_undefined_inputs_outside_target_interval():
    d = _variant('a10')
    entries = [{'source_ref': '/root/facts/0', 'expression': 'Dom(f)=ℝ'}]
    assert not describe(d['source'], TARGET, entries)['structure_supported']


@pytest.mark.parametrize('expression', [
    'piecewise((x^2-1)/(x-1)+a*x,x<2,10*x+a,x>=2)',
    'a*x^2+a/a*x',
    'sqrt(a*x+a/a)',
    'a*x+sqrt(-1)^2',
])
def test_original_definition_obligations_survive_simplification(expression):
    d = _variant('a10', expression=expression, input_domain='[0,3]')
    assert not d['structure_supported']
    assert 'obligation' in d['reason']


def test_denominator_condition_stays_local_to_actual_branch_interval():
    d = _variant('a10', expression='piecewise((x^2-1)/(x-1)+a*x,x<2,10*x+a,x>=2)',
                 input_domain='[3/2,3]')
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['feasible_set'] == sp.Interval.Lopen(-1, 17)
    assert verify(d, m)


def test_narrow_parameter_interval_verifies_without_sampling_beyond_its_ends():
    d = _variant('a17', expression='piecewise((100*a-1)*x+4*a,x<1,a/x,x>=1)')
    m = solve(d)
    assert m['feasible_set'] == sp.Interval.Ropen(sp.Rational(1, 103), sp.Rational(1, 100))
    assert verify(d, m)
    assert verify(d, decode_value(encode_value(m)))


@pytest.mark.parametrize('feasible', [
    sp.Interval.open(sp.Rational(1, 103), sp.Rational(1, 100)),
    sp.Union(sp.Interval.open(0, sp.Rational(1, 100)), sp.Interval.open(sp.Rational(1, 50), 1)),
    sp.Union(sp.FiniteSet(0), sp.Interval.open(sp.Rational(1, 100), 1)),
])
def test_boundary_samples_belong_to_the_sets_they_check(feasible):
    from shuxueshuo_server.graph_lesson.monotonicity_parameter_math import (
        _boundary_samples,
    )
    inside, outside = _boundary_samples(feasible)
    assert inside and outside
    assert all(feasible.contains(v) is sp.S.true for v in inside)
    assert all(feasible.contains(v) is sp.S.false for v in outside)


@pytest.mark.parametrize('expression,interval,gold', [
    ('sqrt(a*x+1)', '[0,1]', sp.Interval.open(0, sp.oo)),
    ('sqrt(a)', '[0,1]', sp.S.EmptySet),
    ('piecewise(a*x,x<0,x,x>=0)', 'ℝ', sp.Interval.open(0, sp.oo)),
    ('piecewise(0,x<0,a*x,x>=0)', 'ℝ', sp.S.EmptySet),
    ('piecewise(x^2+a*x,x<2,(a+10)*x,x>=2)', '[1,3]', sp.Interval(-2, sp.oo)),
])
def test_supported_constant_linear_and_clipped_cases_compile_all_cards(expression, interval, gold):
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_presentation import (
        compile_mono_parameter,
        phase_views,
    )

    d = _variant('a10', expression=expression, input_domain=interval)
    assert d['structure_supported'], d['reason']
    m = solve(d)
    assert m['feasible_set'] == gold
    assert verify(d, m)
    phases = (['prepare', 'outer', 'inner', 'domain', 'conclude'] if m['structure'] == 'radical'
              else ['prepare', 'pieces', 'join', 'conclude'])
    for phase in phases:
        values = {'description': d, 'mono_parameter_result': m, 'phase': phase}
        views = phase_views(values)
        assert views, phase
        compiled = compile_mono_parameter([{'values': encode_value(values)}], f'test-{phase}')
        assert len(compiled['parts']) == len(views)
        for part in compiled['parts']:
            expected = part['expected_answer']['one_of']
            options = part['interaction']['options']
            assert sum(option['value'] in expected for option in options) == 1
            assert part['stem_board']['items'][1]['math'] is None
    if expression == 'sqrt(a*x+1)':
        view, = phase_views(dict(values, phase='inner'))
        assert '一次函数' in view['question'] and '0=0' not in view['question']
    if interval == '[1,3]':
        views = phase_views(dict(values, phase='pieces'))
        assert r'x\in \left[1, 2\right)' in views[0]['question']
        assert r'x\in \left[2, 3\right]' in views[1]['question']
        assert '$x < 2$' not in views[0]['question']


@pytest.mark.parametrize('expression,phases', [
    ('sqrt(a*t+1)', ['outer', 'inner', 'domain', 'conclude']),
    ('piecewise(a*t,t<0,t,t>=0)', ['pieces', 'join', 'conclude']),
])
def test_cards_keep_source_variable_and_do_not_redefine_original_function(expression, phases):
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_presentation import (
        phase_views,
    )
    d = _variant('a10', expression=expression, variable='t', function='g', input_domain='[-1,1]')
    m = solve(d)
    for phase in phases:
        views = phase_views({'description': d, 'mono_parameter_result': m, 'phase': phase})
        assert views
        text = json.dumps(views, ensure_ascii=False)
        assert 'g(x)' not in text and 'f(x)' not in text and 'h(x)' not in text
    if m['structure'] == 'radical':
        outer, = phase_views({'description': d, 'mono_parameter_result': m, 'phase': 'outer'})
        assert r'g(t)=\sqrt{h(t)}' in outer['derivation']['items'][0]['math']
        assert '内层 $h(t)$' in outer['question']


@pytest.mark.parametrize('expression,direction,interval,gold', [
    ('a/x', 'increasing', '(0,+∞)', sp.Interval.open(-sp.oo, 0)),
    ('a/x', 'decreasing', '(-∞,0)', sp.Interval.open(0, sp.oo)),
    ('x+a/x', 'increasing', '[1,+∞)', sp.Interval(-sp.oo, 1)),
    ('x+a/x', 'increasing', '(0,+∞)', sp.Interval(-sp.oo, 0)),
    ('x+a/x', 'decreasing', '[1,+∞)', sp.S.EmptySet),
    ('-2*x+a/x', 'decreasing', '(-∞,-1]', sp.Interval(-2, sp.oo)),
    ('1/x+a', 'decreasing', '(0,+∞)', sp.S.Reals),
    ('piecewise(a*x,x<1,2,x>=1)', 'increasing', '[0,1]', sp.Interval.Lopen(0, 2)),
    # Source order is immaterial, including ties between a point and an open interval.
    ('piecewise(x+1,x>0,a,x<=0)', 'increasing', '[0,1]', sp.Interval(-sp.oo, 1)),
    ('piecewise(x-a,x>0,x+a,x<0,0,x=0)', 'increasing', 'ℝ', sp.Interval(-sp.oo, 0)),
    ('piecewise(x,x<1,a*x,x>=1)', 'increasing', '[0,1/2]', sp.S.Reals),
    ('piecewise(-x,x<1,a*x,x>=1)', 'increasing', '[0,1/2]', sp.S.EmptySet),
    ('piecewise(x,x<=0,x+a/x,x>0)', 'increasing', 'ℝ', sp.FiniteSet(0)),
    ('piecewise(x+(a-1)/x,x<0,x,x>=0)', 'increasing', 'ℝ', sp.FiniteSet(1)),
    ('piecewise(x+2,x<=0,x+a/x,x>0)', 'increasing', 'ℝ', sp.S.EmptySet),
    ('piecewise(a/x,x<0,x,x>=0)', 'increasing', 'ℝ', sp.S.EmptySet),
])
def test_generalized_families_preserve_strictness_and_endpoint_values(expression, direction, interval, gold):
    d = _variant('a10', expression=expression, direction=direction, input_domain=interval)
    assert d['structure_supported'], d['reason']
    model = solve(d)
    assert model['feasible_set'] == gold
    assert verify(d, decode_value(encode_value(model)))
    assert not verify(d, dict(model, feasible_set=gold ^ sp.FiniteSet(0)))


def test_parameter_outside_target_interval_still_obeys_original_parameter_facts():
    d = _variant('a10', expression='piecewise(x,x<1,a*x,x>=1)', input_domain='[0,1/2]')
    constrained = describe(d['source'], TARGET, [{'source_ref': '/root/facts/0', 'expression': 'a>0'}])
    model = solve(constrained)
    assert model['unrestricted_set'] == sp.S.Reals
    assert model['feasible_set'] == sp.Interval.open(0, sp.oo)
    assert verify(constrained, model)


@pytest.mark.parametrize('expression,interval', [
    ('a/(x+1)', '[0,1]'),
    ('piecewise(x,x<0,a/x,x>=0)', '[0,1]'),
    ('piecewise(x,x<0,a/x,x=0,x,x>0)', 'ℝ'),
])
def test_generalization_does_not_admit_unhandled_denominators(expression, interval):
    assert not _variant('a10', expression=expression, input_domain=interval)['structure_supported']


@pytest.mark.parametrize('expression,interval,gold', [
    ('(a+1)*x+2', 'ℝ', sp.Interval.open(-1, sp.oo)),
    ('a/x', '(0,+∞)', sp.Interval.open(-sp.oo, 0)),
    ('x+a/x', '[1,+∞)', sp.Interval(-sp.oo, 1)),
    ('piecewise(a*x,x<1,2,x>=1)', '[0,1]', sp.Interval.Lopen(0, 2)),
    ('piecewise(x,x<1,a*x,x>=1)', '[0,1/2]', sp.S.Reals),
    ('piecewise(x,x<=0,x+a/x,x>0)', 'ℝ', sp.FiniteSet(0)),
])
def test_generalized_problems_execute_and_compile_the_shared_route(expression, interval, gold, tmp_path):
    from shuxueshuo_server.graph_lesson.stage_one.authored import prepare_authored
    from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    from shuxueshuo_server.graph_lesson.stage_three.interaction_graph_contract import (
        validate_graph,
    )
    from shuxueshuo_server.graph_lesson.stage_two.runner import run_result

    record, _ = source('a10')
    candidate = deepcopy(record['candidate'])
    candidate['root']['goals'][0]['required_monotonicity'].update(expression=expression, input_domain=interval)
    candidate['root']['definitions'] = ['f(x)=' + expression]
    candidate['root']['facts'] = []
    candidate['original_text'] = f'已知 f(x)={expression} 在 {interval} 上严格递增，求 a 的取值范围。'
    # These are synthetic variants, not source-photo acceptance records.
    fixture = Path(__file__)
    prepared = prepare_authored(candidate, run_id='t4-generalization', reviewer='unit-test', sources=[{
        'reference': str(fixture.relative_to(ROOT)), 'sha256': sha256(fixture.read_bytes()).hexdigest(),
        'location': 'synthetic generalization cases',
    }])
    stage_two = run_result(prepared, tmp_path / 'stage-two', admission='authored_topic')
    assert stage_two['status'] == 'completed', stage_two['input_diagnostics']
    assert stage_two['goals'][0]['primary'] == 'type-monotonicity-parameter'
    context = build_context(candidate, TARGET)
    state = driver.create_state(
        features=prepared['features'], context=context,
        method='method-monotonicity-parameter', route_id='monotonicity-parameter', branch='parameter',
        target_ref=TARGET, run_id='t4-generalization', lesson_version='v1')
    for _ in range(100):
        if state['status'] != 'running':
            break
        state = driver.advance(state)
    assert state['status'] == 'method_complete', state.get('diagnostics')
    assert driver.export_values(state)['mono_parameter_result']['feasible_set'] == gold
    chunks, pending = interaction.compile_route(
        state['interaction_seeds'], interaction.load_registry(), revision='test')
    assert chunks and not pending
    assert all(chunk['status'] in ('interactive', 'readonly') for chunk, _ in chunks)
    parts = [part for chunk, _ in chunks for part in chunk.get('parts', [])]
    assert len(parts) >= 3  # Prepare, a real function/branch decision, and conclusion.
    for part in parts:
        expected = part['expected_answer']['one_of']
        assert sum(option['value'] in expected for option in part['interaction']['options']) == 1
        for key in ('graph', 'completion_graph'):
            if key in part:
                validate_graph(part[key])
    if expression == '(a+1)*x+2':
        assert any('斜率' in part['title'] for part in parts)
    if interval == '[0,1]':
        assert any('单点' in part['title'] for part in parts)


def test_radical_inner_summary_keeps_original_parameter_restrictions():
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_presentation import (
        phase_views,
    )

    d = _variant('a10', expression='sqrt(a*x^2-x+2)', input_domain='[1,2]', direction='decreasing')
    d = describe(d['source'], TARGET, [{'source_ref': '/root/facts/0', 'expression': 'a>0'}])
    model = solve(d)
    assert model['feasible_set'] == sp.Interval.Lopen(0, sp.Rational(1, 4))
    views = phase_views({'description': d, 'mono_parameter_result': model, 'phase': 'inner'})
    summary = next(view for view in views if view.get('part_title') == '汇总三类')
    options = summary['interaction']['options']
    correct, = [o for o in options if o['value'] in summary['expected_answer']['one_of']]
    assert correct['label'] == r'$a\in \left(0, \frac{1}{4}\right]$'
    assert '题设参数条件' in summary['derivation']['items'][0]['math']


def test_fixed_axis_on_interval_endpoint_cannot_make_two_choices_correct():
    from shuxueshuo_server.graph_lesson.stage_three.monotonicity_parameter_presentation import (
        phase_views,
    )

    d = _variant('a10', expression='a*(x-1)^2', input_domain='[1,2]')
    model = solve(d)
    assert model['feasible_set'] == sp.Interval.open(0, sp.oo)
    cards = phase_views({'description': d, 'mono_parameter_result': model, 'phase': 'classify'})
    positive = next(card for card in cards if card['part_title'] == '$a>0$')
    correct, = [o for o in positive['interaction']['options'] if o['value'] in positive['expected_answer']['one_of']]
    conclusion = correct['label'].split(r'\Rightarrow')[-1]
    assert sum(o['label'].endswith(conclusion) for o in positive['interaction']['options']) == 1
