"""FP-T3 R4: the design's mechanism table (§8.1) on both routes; gaps stay gaps, never false answers."""
import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import parity_extension_math as ext
from shuxueshuo_server.graph_lesson import symmetry_value_math as sym
from shuxueshuo_server.graph_lesson.stage_three.context import build_context

TARGET = '/root/goals/0'
X = sp.Symbol('x', real=True)
ODD_EVEN = ['Dom(f)=ℝ', 'Dom(g)=ℝ', 'parity(f,odd)', 'parity(g,even)']


def _context(facts, goal, text='t'):
    return build_context({'original_text': text, 'root': {'facts': facts, 'goals': [goal]}}, TARGET)


def completion(facts, rule, known, requested=None):
    goal = {'kind': 'find_function_formula', 'function': 'f', 'variable': 'x', 'relation': f'f(x)={rule}',
            'relation_domain': known, **({'requested_domain': requested} if requested else {})}
    c = _context(facts, goal)
    return ext.describe(c['goal'], c['goal_ast'], TARGET, c['entries'])


def value(facts, expression, *, rule=None, known=None, relation=None):
    goal = {'kind': 'find_value', 'expression': expression}
    if rule or relation:
        goal.update(function='f', variable='x', relation=relation or f'f(x)={rule}')
    if rule:
        goal['relation_domain'] = known
    c = _context(facts, goal)
    return sym.describe(c['goal'], c['goal_ast'], TARGET, c['entries'])


def solved(desc, route):
    assert desc['structure_supported'], desc['reason']
    model = route.solve(desc)
    assert route.verify(desc, model)
    return model


def branches(model):
    return [(b['set'], sp.simplify(b['expression'])) for b in model['branches']]


def test_odd_jump_has_no_continuity_assumption():
    model = solved(completion(['Dom(f)=ℝ', 'parity(f,odd)'], 'x+1', '(0,∞)', 'ℝ'), ext)
    assert branches(model) == [(sp.Interval.open(-sp.oo, 0), X - 1), (sp.FiniteSet(0), 0),
                               (sp.Interval.open(0, sp.oo), X + 1)]


def test_even_free_zero_keeps_the_target_value():
    model = solved(completion(['Dom(f)=ℝ', 'parity(f,even)'], 'x+1', '(0,∞)', 'ℝ'), ext)
    assert model['status'] == 'insufficient_information' and model['free_domain'] == sp.FiniteSet(0)
    assert solved(value(['Dom(f)=ℝ', 'parity(f,even)'], 'f(-2)', rule='x+1', known='(0,∞)'), sym)['value'] == 3


def test_zero_conflict_is_a_contradiction_on_both_routes():
    assert completion(['Dom(f)=ℝ', 'parity(f,odd)'], 'x+1', '[0,∞)', '(-∞,0)')['reason'] == 'parity_ext.overlap_conflict'
    assert value(['Dom(f)=ℝ', 'parity(f,odd)'], 'f(-1)', rule='x+1', known='[0,∞)')['reason'] == \
        'symmetry_value.overlap_conflict'


def test_domain_without_zero_reflects_a_rational_rule():
    facts = ['Dom(f)=ℝ∖{0}', 'parity(f,odd)']
    model = solved(completion(facts, '1/x', '(0,∞)', '(-∞,0)'), ext)
    assert branches(model) == [(sp.Interval.open(-sp.oo, 0), 1 / X)]
    assert solved(value(facts, 'f(-2)', rule='1/x', known='(0,∞)'), sym)['value'] == sp.Rational(-1, 2)
    assert value(facts, 'f(0)', rule='1/x', known='(0,∞)')['reason'] == 'symmetry_value.input_outside_domain'


def test_uncovered_range_is_reported_not_guessed():
    facts = ['Dom(f)=[-3,3]', 'parity(f,even)']
    assert branches(solved(completion(facts, 'x^2', '[1,2]', '[-2,-1]'), ext)) == [(sp.Interval(-2, -1), X**2)]
    assert solved(value(facts, 'f(-2)', rule='x^2', known='[1,2]'), sym)['value'] == 4
    assert solved(value(facts, 'f(3)', rule='x^2', known='[1,2]'), sym)['status'] == 'insufficient_information'
    assert value(facts, 'f(4)', rule='x^2', known='[1,2]')['reason'] == 'symmetry_value.input_outside_domain'


def test_finite_domain_pairs_values_without_fitting():
    facts = ['Dom(f)={-2,-1,1,2}', 'parity(f,even)', 'f(1)=3']
    assert solved(value(facts, 'f(-1)'), sym)['value'] == 3
    assert solved(value(facts, 'f(2)'), sym)['status'] == 'insufficient_information'


def test_overlap_is_checked_beyond_zero():
    assert completion(['Dom(f)=[-2,2]', 'parity(f,odd)'], 'x^2', '[-1,2]', '[-2,-1)')['reason'] == \
        'parity_ext.overlap_conflict'
    model = solved(completion(['Dom(f)=[-2,2]', 'parity(f,even)'], 'x^2', '[-1,2]', '[-2,2]'), ext)
    assert branches(model) == [(sp.Interval(-2, 2), X**2)]


def test_cancelled_denominator_keeps_its_holes():
    model = solved(completion(['Dom(f)=ℝ∖{-1,1}', 'parity(f,even)'], '(x^2-1)/(x-1)', '[0,∞)', 'ℝ∖{-1,1}'), ext)
    assert sp.simplify(model['answer_expression'] - (sp.Abs(X) + 1)) == 0
    assert sp.Union(*(b['set'] for b in model['branches'])) == sp.Reals - sp.FiniteSet(-1, 1)


@pytest.mark.parametrize('rule', ['(x^2-1)/(x-1)', 'x/x'])
def test_printed_denominator_zero_inside_the_rule_range_is_illegal(rule):
    assert completion(['Dom(f)=ℝ', 'parity(f,even)'], rule, '[0,∞)', 'ℝ')['reason'] == \
        'parity_ext.rule_undefined_on_range'


def test_radicals_reflect_only_the_input():
    model = solved(completion(['Dom(f)=(-∞,-1]∪[1,∞)', 'parity(f,even)'], 'sqrt(x-1)', '[1,∞)',
                              '(-∞,-1]∪[1,∞)'), ext)
    assert branches(model) == [(sp.Interval(-sp.oo, -1), sp.sqrt(-X - 1)), (sp.Interval(1, sp.oo), sp.sqrt(X - 1))]
    model = solved(completion(['Dom(f)=ℝ', 'parity(f,odd)'], 'sqrt(x)', '(0,∞)', '(-∞,0)'), ext)
    assert branches(model) == [(sp.Interval.open(-sp.oo, 0), -sp.sqrt(-X))]


def test_degenerate_domain():
    assert solved(value(['Dom(f)={0}', 'parity(f,odd)'], 'f(0)'), sym)['value'] == 0
    assert solved(value(['Dom(f)={0}', 'parity(f,even)'], 'f(0)'), sym)['status'] == 'insufficient_information'


def test_zero_coefficient_and_zero_rows():
    assert solved(value(ODD_EVEN, 'g(1)', relation='0*f(x)+g(x)=x^2'), sym)['value'] == 1
    assert solved(value(ODD_EVEN, 'f(1)', relation='0*f(x)+g(x)=x^2'), sym)['status'] == 'insufficient_information'
    assert solved(value([*ODD_EVEN, 'f(1)=2'], 'f(-1)', relation='0*f(x)+0*g(x)=0'), sym)['value'] == -2
    assert value([*ODD_EVEN, 'f(1)=2'], 'f(-1)', relation='0*f(x)+0*g(x)=1')['reason'] == \
        'symmetry_value.conditions_inconsistent'


@pytest.mark.parametrize('target,expected', [('f(1)', 1), ('g(1)', 0), ('f(0)', 0), ('g(0)', None)])
def test_relation_range_smaller_than_the_domain(target, expected):
    model = solved(value([*ODD_EVEN, '∀x∈ℝ∖{0}:f(x)+g(x)=1/x'], target), sym)
    assert model['value'] == expected


def test_renamed_function_and_variable():
    goal = {'kind': 'find_value', 'function': 'h', 'variable': 't', 'relation': 'h(t)=t^3+2*t+1',
            'relation_domain': '(0,∞)', 'expression': 'h(0)+h(-1)'}
    c = _context(['Dom(h)=ℝ', 'parity(h,odd)'], goal)
    assert solved(sym.describe(c['goal'], c['goal_ast'], TARGET, c['entries']), sym)['value'] == -4


FINITE_PARAMETER = r'已知奇函数 $f(x)$ 的定义域为 $\{-1,1,m\}$，且 $f(1)=2$，则 ${}$ 的值为____．'


def _parameter(expression):
    from shuxueshuo_server.graph_lesson.stage_three.symmetry_runtime import _borrow_bound, prepare
    value = {'original_text': FINITE_PARAMETER.replace('{}', expression),
             'root': {'facts': ['Dom(f)={-1,1,m}', 'parity(f,odd)', 'f(1)=2'],
                      'goals': [{'kind': 'find_value', 'expression': expression}]}}
    context = build_context(value, TARGET)
    return context, prepare(context)['outputs']['description'], _borrow_bound


def test_every_parameter_candidate_is_instantiated_and_compared():
    context, borrowed, bound = _parameter('f(m)+f(-m)')
    assert borrowed['borrowed']['parameter_set'] == sp.FiniteSet(-1, 0, 1)
    assert borrowed['borrowed']['remaining_source_refs'] == ['/root/facts/2']
    model = sym.solve(borrowed)
    assert model['value'] == 0 and [r['parameter_value'] for r in model['borrow']['candidates']] == [-1, 0, 1]
    desc = context['symmetry_value_goal']
    assert sym.verify(desc, model) and bound(context, model)
    dropped = {**model, 'borrow': {**model['borrow'], 'candidates': model['borrow']['candidates'][:1]}}
    assert not sym.verify(desc, dropped)


def test_disagreeing_parameter_candidates_are_a_gap_not_the_first_value():
    _, borrowed, _ = _parameter('f(m)')
    with pytest.raises(ValueError, match='parameter_candidates_disagree'):
        sym.solve(borrowed)
