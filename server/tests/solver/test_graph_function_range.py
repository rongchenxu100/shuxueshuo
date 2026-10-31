"""T5 R0: original input scope, complete image and independent endpoint checks."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_one.function_range import inspect_range_target
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_range import (
    admitted,
    image_endpoints,
    independent_verify,
    inputs,
    polynomial_image,
    prepare_function_range,
)
from shuxueshuo_server.graph_lesson.stage_three.goals import (
    GoalClosureMismatch,
    equivalent_answers,
    finalize_goal,
    verify_goal_answer,
)
from shuxueshuo_server.graph_lesson.stage_three.range_presentation import (
    _graph,
    phase_view,
)
from shuxueshuo_server.graph_lesson.stage_two.fragments import _abstract_formula_matches
from shuxueshuo_server.graph_lesson.stage_two.range_surface import range_source_spans
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types

TARGET = '/root/goals/0'


def candidate(expression='x^2-2*x+2', domain='[0,3]'):
    return {'original_text': f'已知函数 $f(x)={expression}$，$x∈{domain}$，求函数的值域。',
            'root': {'definitions': [f'f(x)={expression}'],
                     'goals': [{'kind': 'find_range', 'object': 'f', 'input_domain': domain}]}}


@pytest.mark.parametrize('expression,domain,expected', [
    ('x^2-2*x+2', '[0,3]', sp.Interval(1, 5)),
    ('x^2-2*x+3', '[0,3]', sp.Interval(2, 6)),
    ('-x^2+2*x-2', '[0,3]', sp.Interval(-5, -1)),
    ('(x-1)^2+2', '[2,3]', sp.Interval(3, 6)),
    ('x^2', '(0,2]', sp.Interval.Lopen(0, 4)),
    ('x^2', '[0,2)', sp.Interval.Ropen(0, 4)),
    ('x^2', '[-2,2)', sp.Interval(0, 4)),
    ('x^2', '(-2,2)', sp.Interval.Ropen(0, 4)),
    ('x^2', '(-∞,+∞)', sp.Interval(0, sp.oo)),
    ('x^2', '(0,+∞)', sp.Interval.open(0, sp.oo)),
    ('2*x+1', '(-1,2]', sp.Interval.Lopen(-1, 5)),
    ('-2*x+1', '(-1,2]', sp.Interval.Ropen(-3, 3)),
    ('x', '(-∞,+∞)', sp.S.Reals),
    ('5', '(0,1)', sp.FiniteSet(5)),
    ('0', '(0,1)', sp.FiniteSet(0)),
    ('x^2+3', '[0,0]', sp.FiniteSet(3)),
])
def test_complete_polynomial_image(expression, domain, expected):
    value = candidate(expression, domain)
    desc = inspect_range_target(value, TARGET)
    assert desc['structure_supported'], desc
    f, x, interval = inputs(desc)
    result = polynomial_image(f, x, interval)
    assert result['outputs']['feasible_set'] == expected
    context = build_context(value, TARGET)
    proof = independent_verify(value, TARGET, context, expected)
    assert proof['status'] == 'verified', proof
    assert proof['proof']['cover']
    assert image_endpoints(value, TARGET, expected)['status'] == 'passed'
    # Correct extrema alone are insufficient: deleting an interior output fails.
    if isinstance(expected, sp.Interval) and expected.measure > 0:
        witness = ((expected.start + expected.end)/2 if expected.start.is_finite and expected.end.is_finite
                   else expected.start+1 if expected.start.is_finite else expected.end-1 if expected.end.is_finite else 0)
        assert independent_verify(value, TARGET, context, expected-sp.FiniteSet(witness))['status'] == 'math_failed'


@pytest.mark.parametrize('expression', ['(x^2-1)/(x-1)', '(x-1)^0+x', 'x^2+sqrt(1-x)', 'sqrt(x)+sqrt(x+1)', 'x^3', 'm*x^2'])
def test_future_or_originally_restricted_syntax_is_not_admitted(expression):
    value = candidate(expression)
    desc = inspect_range_target(value, TARGET)
    assert not desc['structure_supported'], desc
    features = extract_features(value)
    assert features['ok'], features
    assert not any(row['status'] == 'supported' and row['type_id'] == 'type-function-range'
                   for row in evaluate_types(features['features']))


def test_declared_domain_and_additional_input_limit_stay_input_constraints():
    value = candidate('x^2', '[1,2]')
    value['root']['facts'] = ['Dom(f)=[-2,2]']
    value['original_text'] = '已知函数 $f(x)=x^2$ 的定义域为 $[-2,2]$，求 $x∈[1,2]$ 时的值域。'
    desc = inspect_range_target(value, TARGET)
    f, x, domain = inputs(desc)
    assert domain == sp.Interval(1, 2)
    assert polynomial_image(f, x, domain)['outputs']['feasible_set'] == sp.Interval(1, 4)
    assert range_source_spans(value, TARGET, [(0, len(value['original_text']))], desc, _abstract_formula_matches)


@pytest.mark.parametrize('domain,expected', [
    ('[0,1+1/2]', sp.Interval(0, sp.Rational(9, 4))),
    ('[(1-3)/2,2^2/2]', sp.Interval(0, 4)),
    ('{1+1/2}', sp.FiniteSet(sp.Rational(9, 4))),
])
@pytest.mark.parametrize('source', ['input_domain', 'declared_domain', 'restriction_fact'])
def test_rational_endpoint_arithmetic_has_the_same_admission_and_execution(domain, expected, source):
    value = candidate('x^2', domain)
    if source != 'input_domain':
        value['root']['goals'][0].pop('input_domain')
        if source == 'declared_domain':
            value['root']['facts'] = [f'Dom(f)={domain}']
            value['original_text'] = f'已知函数 $f(x)=x^2$ 的定义域为 ${domain}$，求值域。'
        else:
            value['root']['facts'] = [f'x∈{domain}']
    desc = inspect_range_target(value, TARGET)
    assert desc['structure_supported'], desc
    assert admitted(build_context(value, TARGET))
    f, x, interval = inputs(desc)
    assert polynomial_image(f, x, interval)['outputs']['feasible_set'] == expected
    assert independent_verify(value, TARGET, build_context(value, TARGET), expected)['status'] == 'verified'
    assert image_endpoints(value, TARGET, expected)['status'] == 'passed'


@pytest.mark.parametrize('domain,show_vertex', [
    ('[1,2]', False), ('[-2,-1]', False),
    ('(0,2]', False), ('[-2,0)', False),
    ('[0,2]', True), ('[-2,2]', True),
])
def test_range_graph_does_not_mark_an_unattainable_vertex(domain, show_vertex):
    desc = inspect_range_target(candidate('x^2', domain), TARGET)
    f, x, interval = inputs(desc)
    graph = _graph({'description': desc, 'function': f, 'variable': x, 'domain': interval})
    assert graph['params']['showVertex'] is show_vertex
    for point in graph['params']['points']:
        assert bool(interval.contains(point['x'])) is (not point.get('open', False))
    assert '浅色曲线仅作参考' in graph['caption']


def test_source_binding_rejects_wrong_formula_or_input_interval():
    value = candidate()
    desc = inspect_range_target(value, TARGET)
    assert range_source_spans(value, TARGET, [(0, len(value['original_text']))], desc, _abstract_formula_matches)
    for wrong in ('[0,2]', 'x^2-2*x+3'):
        changed = deepcopy(value)
        changed['original_text'] = changed['original_text'].replace('[0,3]', wrong) if wrong[0] == '[' else changed['original_text'].replace('x^2-2*x+2', wrong)
        assert range_source_spans(changed, TARGET, [(0, len(changed['original_text']))], desc, _abstract_formula_matches) is None


def test_range_and_scalar_parameter_targets_are_distinct():
    value = candidate()
    features = extract_features(value)
    assert features['ok']
    assert [row['type_id'] for row in evaluate_types(features['features']) if row['status'] == 'supported'] == ['type-function-range']
    goal = next(row for row in features['features'] if row['feature_id'] == 'goal')
    assert goal['value'] == {'kind': 'find_range', 'object': 'f'}


def test_range_answer_retains_its_function_identity():
    goal = {'kind': 'find_range', 'object': 'f'}
    image = sp.Interval(1, 5)
    answer = finalize_goal(goal, image)
    assert answer['object'] == 'f'
    parameter_answer = finalize_goal({'kind': 'find_range', 'symbol': 'm'}, image)
    assert not equivalent_answers(answer, parameter_answer)
    assert not equivalent_answers(answer, {**answer, 'object': 'g'})
    with pytest.raises(GoalClosureMismatch):
        verify_goal_answer(goal, image, parameter_answer)
    assert verify_goal_answer(goal, image, answer)['status'] == 'set'


def test_constant_card_does_not_invent_open_output_bounds():
    value = candidate('5', '(0,1)')
    desc = inspect_range_target(value, TARGET)
    f, x, domain = inputs(desc)
    outputs = polynomial_image(f, x, domain)['outputs']
    view = phase_view({'phase': 'values', 'description': desc, 'function': f,
                       'variable': x, 'domain': domain, **outputs})
    assert view['interaction']['type'] == 'read'
    assert '保持不变' in view['question']


@pytest.mark.parametrize('expression,domain,compare', [
    ('x^2', '[0,3]', True),
    ('x^2', 'ℝ', True),
    ('x^2', 'ℝ∖{0}', False),
    ('x-2', 'ℝ∖{2}', False),
    ('5', '(0,1)', False),
])
def test_extrema_comparison_is_only_used_for_a_quadratic_on_one_interval(expression, domain, compare):
    from shuxueshuo_server.graph_lesson.stage_three import execution_contracts
    from shuxueshuo_server.graph_lesson.stage_three.driver import _guard

    prepared = prepare_function_range(build_context(candidate(expression, domain), TARGET))['outputs']
    contract = execution_contracts.read('method-quadratic-interval-range')
    prepare = next(call for step in contract['steps'] for call in step['calls']
                   if call['capability'] == 'prepare_function_range')
    bindings = {target: prepared[source] for source, target in prepare['outputs'].items()}
    card = next(unit for step in contract['steps'] for unit in step['display_units']
                if unit['id'] == 'range_values')
    assert _guard(card.get('guard'), bindings) is compare
