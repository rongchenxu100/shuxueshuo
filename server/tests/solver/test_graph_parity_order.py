"""FP-T4 R1: odd rewrite to one comparison, a strict direction on all of D, legal inputs, per-cell verify."""
import copy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.parity_inequality_math import describe, solve, verify
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from tests.solver.test_graph_parity_inequality import candidate

TARGET = '/root/goals/0'
A05 = (r'已知 $f(x)$ 是定义在 $(-2,2)$ 上的奇函数，且当 $x\in(0,2)$ 时，$f(x)=x^2+2x$，'
       r'则当 $-2<x<0$ 时，$f(x)=$____，不等式 $f(x-1)+f(x)<0$ 的解集是____．')
A11 = (r'$f(x)$ 是定义在 $R$ 上的奇函数，且当 $x\ge0$ 时，$f(x)=x^2+x$．则 $x<0$ 时，$f(x)=$____；'
       r'不等式 $f(2x+1)+f(-5)>0$ 的解集是____．')
A18 = (r'已知定义在 $[-2,2]$ 上的函数 $f(x)$ 是奇函数，且 $\frac{f(x_1)-f(x_2)}{x_1-x_2}<0$，'
       r'则满足不等式 $f(1-2a)+f(a-3)>0$ 的实数 $a$ 的取值范围为____．')
QUOTIENT = {'kind': 'difference_quotient', 'statement': '(f(x_1)-f(x_2))/(x_1-x_2)<0'}


def two_goals(text, domain, rule, known, requested, expression):
    relation = f'f(x)={rule}'
    return {'original_text': text, 'root': {'facts': [f'Dom(f)={domain}', 'parity(f,odd)'], 'goals': [
        {'kind': 'find_function_formula', 'function': 'f', 'variable': 'x', 'relation': relation,
         'relation_domain': known, 'requested_domain': requested},
        {'kind': 'find_range', 'function': 'f', 'variable': 'x', 'relation': relation,
         'relation_domain': known, 'expression': expression, 'symbol': 'x'}]}}


def given(facts=('parity(f,odd)', 'f(1-2*a)+f(a-3)>0'), interval='[-2,2]', domain='[-2,2]',
          direction='decreasing', basis=QUOTIENT, text=A18):
    mono = {'function': 'f', 'domain': interval, 'function_domain': domain, 'direction': direction, 'strict': True}
    if basis is not None:
        mono['basis'] = basis
    return {'original_text': text, 'root': {'facts': list(facts), 'goals': [
        {'kind': 'find_range', 'symbol': 'a', 'function_monotonicity': mono}]}}


def a05():
    return two_goals(A05, '(-2,2)', 'x^2+2*x', '(0,2)', '(-2,0)', 'f(x-1)+f(x)<0')


def a11():
    return two_goals(A11, 'ℝ', 'x^2+x', '[0,∞)', '(-∞,0)', 'f(2*x+1)+f(-5)>0')


def described(value, target=TARGET, *, bind=False):
    context = build_context(value, target)
    return describe(context['goal'], context['goal_ast'], target, context['entries'],
                    candidate=value if bind else None)


@pytest.mark.parametrize('value,target,kind,direction,expected', [
    (a05(), '/root/goals/1', 'rule', 'increasing', sp.Interval.open(-1, sp.Rational(1, 2))),
    (a11(), '/root/goals/1', 'rule', 'increasing', sp.Interval.open(2, sp.oo)),
    (given(), TARGET, 'given', 'decreasing', sp.Interval(1, sp.Rational(3, 2))),
    (given(('parity(f,odd)', 'f(1-2*a)<f(a-3)'), '[0,∞)', 'ℝ', 'increasing', None), TARGET, 'given_half',
     'increasing', sp.Interval.open(sp.Rational(4, 3), sp.oo)),
    (candidate(('Dom(f)=ℝ', 'parity(f,odd)'), '-x^2-x', '[0,∞)', 'f(x)+f(x-2)>0'), TARGET, 'rule',
     'decreasing', sp.Interval.open(-sp.oo, 1)),
    (candidate(('Dom(f)=ℝ', 'parity(f,odd)'), '-x^2+x', '(-∞,0]', 'f(x-2)+f(x)<0'), TARGET, 'rule',
     'increasing', sp.Interval.open(-sp.oo, 1)),
])
def test_order_route_solves_and_verifies(value, target, kind, direction, expected):
    desc = described(value, target)
    assert desc['structure_supported'] and desc['route'] == 'order', desc['reason']
    model = solve(desc)
    assert model['certificate']['kind'] == kind and model['certificate']['direction'] == direction
    assert model['solution'] == expected and verify(desc, model)


@pytest.mark.parametrize('value,reason', [
    (candidate(('Dom(f)=(-2,2)', 'parity(f,odd)'), 'x-1', '(0,2)', 'f(x-1)+f(x)<0'), 'parity_ineq.junction_not_monotone'),
    (candidate(('Dom(f)=ℝ', 'parity(f,odd)'), 'x^2-3*x', '[0,∞)', 'f(x-1)+f(x)<0'), 'parity_ineq.rule_not_monotone'),
    (candidate(('Dom(f)=ℝ', 'parity(f,odd)'), 'x^2+x', '[0,∞)', 'f(x-1)+f(x)<1'), 'parity_ineq.threshold_value_unknown'),
    (candidate(('Dom(f)=ℝ', 'parity(f,even)'), 'x^2+x', '[0,∞)', 'f(x-1)+f(x)<0'), 'parity_ineq.even_sum_unsupported'),
    (given(interval='(0,∞)', domain='ℝ', direction='increasing', basis=None), 'parity_ineq.junction_unknown'),
    (given(direction='increasing'), 'parity_ineq.basis_direction_conflict'),
    (given(('parity(f,odd)', 'f(1-2*a)>0'), domain='(0,2]', interval='(0,2]'), 'parity_ineq.domain_not_symmetric'),
])
def test_unproven_direction_or_value_is_a_gap(value, reason):
    desc = described(value)
    assert not desc['structure_supported'] and desc['reason'] == reason


def test_plain_comparison_stays_with_monotonicity_inequality():
    context = build_context(given(('parity(f,odd)', 'f(1-2*a)<f(a-3)')), TARGET)
    assert 'parity_inequality_goal' not in context
    assert context['mono_inequality_goal']['structure_supported']
    even = build_context(given(('parity(f,even)', 'f(1-2*a)<f(a-3)')), TARGET)
    assert even['mono_inequality_goal']['reason'] == 'mono_ineq.parity_conflict'


@pytest.mark.parametrize('field,value', [
    ('solution', sp.Interval.open(1, sp.Rational(3, 2))),
    ('legal_set', sp.Interval(1, 2)),
    ('converted_operator', '>'),
    ('right_input', sp.Symbol('a', real=True) - 3),
])
def test_verify_rejects_tampered_order_models(field, value):
    desc = described(given())
    assert not verify(desc, {**solve(desc), field: value})


def test_verify_rejects_a_flipped_rule_direction():
    desc = described(a11(), '/root/goals/1')
    model = solve(desc)
    cert = {**model['certificate'], 'direction': 'decreasing'}
    assert not verify(desc, {**model, 'certificate': cert})


@pytest.mark.parametrize('build,target', [(a05, '/root/goals/0'), (a05, '/root/goals/1'),
                                          (a11, '/root/goals/0'), (a11, '/root/goals/1'), (given, TARGET)])
def test_whole_problems_bind_each_goal(build, target):
    value = build()
    context = build_context(value, target)
    key = 'parity_inequality_goal' if target.endswith('1') or build is given else 'parity_extension_goal'
    assert context[key]['structure_supported'], context[key]['reason']


@pytest.mark.parametrize('build,target,old,new', [
    (given, TARGET, '<0$', '>0$'),
    (given, TARGET, '奇函数', '偶函数'),
    (given, TARGET, 'f(1-2a)+f(a-3)>0', 'f(1-2a)-f(a-3)>0'),
    (a05, '/root/goals/1', 'f(x-1)+f(x)<0', 'f(x-1)-f(x)<0'),
    (a11, '/root/goals/1', r'x\ge0', 'x>0'),
])
def test_order_binding_follows_the_printed_text(build, target, old, new):
    value = copy.deepcopy(build())
    assert old in value['original_text']
    value['original_text'] = value['original_text'].replace(old, new)
    desc = described(value, target, bind=True)
    assert not desc['structure_supported'] and desc['reason'] == 'parity_ineq.source_not_bound'


def test_monotonicity_inequality_checks_a_basis_object():
    context = build_context(given(('parity(f,odd)', 'f(1-2*a)<f(a-3)'), direction='increasing'), TARGET)
    assert context['mono_inequality_goal']['reason'] == 'mono_ineq.basis_direction_conflict'


@pytest.mark.parametrize('basis,ok', [
    (QUOTIENT, True), ({'kind': 'stated', 'statement': ''}, True), ('proved_monotonicity', True),
    ({'kind': 'guessed', 'statement': ''}, False),
])
def test_extraction_schema_accepts_the_printed_basis(basis, ok):
    from jsonschema import Draft202012Validator
    from shuxueshuo_server.graph_lesson.stage_one.contracts import schema
    validator = Draft202012Validator(schema())
    errors = list(validator.iter_errors(given(basis=basis)))
    assert (not errors) is ok, [e.message for e in errors]
