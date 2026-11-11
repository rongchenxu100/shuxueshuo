"""FP-T3 R0/R1: local-rule completion is bound to source, mapped, substituted and verified."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import parity_compatibility as compatibility
from shuxueshuo_server.graph_lesson.parity_extension_math import describe, solve, verify
from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.parity_extension_runtime import answer_for
from shuxueshuo_server.graph_lesson.stage_three.selection import evaluate_goal
from shuxueshuo_server.graph_lesson.stage_two.recognition import evaluate_types

TARGET = '/root/goals/0'
X = sp.Symbol('x', real=True)
TEXTS = {
    'a07': r'已知函数 $f(x)$ 是定义域为 $\mathbf R$ 的偶函数，当 $x\ge 0$ 时，$f(x)=x(1+x)$．'
           r'则当 $x<0$ 时，$f(x)=$____．',
    'a08': r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，'
           r'则当 $x<0$ 时，$f(x)=$____．',
    'a09': r'设 $f(x)$ 是定义在 $(-\infty,+\infty)$ 上的奇函数，且 $x>0$ 时，$f(x)=2x^2-x$，'
           r'则 $f(-3)=$____；当 $x\le 0$ 时，$f(x)=$____．',
    'a04': r'已知 $f(x)$ 为偶函数，若当 $x\ge 0$ 时，$f(x)=x^2+4x$，则 $f(x)$ 的解析式是____．',
}
CASES = {
    'a04': (None, 'x^2+4*x', 'even', '[0,∞)', None),
    'a07': ('ℝ', 'x*(1+x)', 'even', '[0,∞)', '(-∞,0)'),
    'a08': ('ℝ', 'x^2-3*x-1', 'odd', '(0,∞)', '(-∞,0)'),
    'a09': ('ℝ', '2*x^2-x', 'odd', '(0,∞)', '(-∞,0]'),
    'a05': ('(-2,2)', 'x^2+2*x', 'odd', '(0,2)', '(-2,0)'),
    'a11': ('ℝ', 'x^2+x', 'odd', '[0,∞)', '(-∞,0)'),
}


def candidate(name='a07', *, domain=None, rule=None, prop=None, known=None, requested=None, text=None,
              extra_facts=()):
    base_domain, base_rule, base_prop, base_known, base_requested = CASES[name]
    goal = {'kind': 'find_function_formula', 'function': 'f', 'variable': 'x',
            'relation': f'f(x)={rule or base_rule}', 'relation_domain': known or base_known}
    if requested or base_requested:
        goal['requested_domain'] = requested or base_requested
    goals = [goal]
    facts = [f'parity(f,{prop or base_prop})', *extra_facts]
    if domain or base_domain:
        facts.insert(0, f'Dom(f)={domain or base_domain}')
    if name == 'a09':
        goals = [{'kind': 'find_value', 'function': 'f', 'variable': 'x', 'relation': goal['relation'],
                  'relation_domain': goal['relation_domain'], 'expression': 'f(-3)'}, goal]
    return {'original_text': text or TEXTS.get(name, 't'), 'root': {'facts': facts, 'goals': goals}}


def target(name):
    return '/root/goals/1' if name == 'a09' else TARGET


def description(value, name='a07'):
    return build_context(value, target(name))['parity_extension_goal']


def math_only(value, name='a07'):
    context = build_context(value, target(name))
    return describe(context['goal'], context['goal_ast'], target(name), context['entries'])


@pytest.mark.parametrize('name,expected,requested', [
    ('a07', 'x**2-x', sp.Interval.open(-sp.oo, 0)),
    ('a08', '-x**2-3*x+1', sp.Interval.open(-sp.oo, 0)),
    ('a09', '-2*x**2-x', sp.Interval(-sp.oo, 0)),
])
def test_gold_formula_is_substituted_whole_and_verified(name, expected, requested):
    desc = description(candidate(name), name)
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert sp.expand(model['answer_expression'] - sp.sympify(expected, locals={'x': X})) == 0
    assert model['mapped_domain'] == sp.Interval.open(0, sp.oo)
    assert model['requested_domain'] == requested and verify(desc, model)
    answer = answer_for(desc, model)
    assert answer['status'] == 'determined_on_domain' and answer['requested_domain']['exact']


def test_a09_zero_merges_only_after_the_value_check():
    model = solve(description(candidate('a09'), 'a09'))
    branch, = model['branches']
    assert branch['set'] == sp.Interval(-sp.oo, 0) and branch['origins'] == ['mirrored', 'zero']
    assert model['zero_status'] == 'forced_zero'
    # A08's negative-side formula gives 1 at 0, so f(0)=0 stays a separate branch.
    desc = math_only(candidate('a08', requested='(-∞,0]'))
    model = solve(desc)
    assert [b['set'] for b in model['branches']] == [sp.Interval.open(-sp.oo, 0), sp.FiniteSet(0)]
    assert isinstance(model['answer_expression'], sp.Piecewise) and verify(desc, model)
    assert not verify(desc, {**model, 'branches': [{**model['branches'][0], 'set': sp.Interval(-sp.oo, 0)}],
                             'answer_expression': -X**2-3*X+1})


@pytest.mark.parametrize('name,expected,requested', [
    ('a05', '-x**2+2*x', sp.Interval.open(-2, 0)),
    ('a11', '-x**2+x', sp.Interval.open(-sp.oo, 0)),
])
def test_cross_type_first_parts_keep_open_ends(name, expected, requested):
    desc = math_only(candidate(name))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert sp.expand(model['answer_expression'] - sp.sympify(expected, locals={'x': X})) == 0
    assert model['requested_domain'] == requested and verify(desc, model)


def test_a04_abstract_domain_keeps_its_identity():
    desc = description(candidate('a04'), 'a04')
    assert desc['structure_supported'], desc['reason']
    assert desc['domain_ast'] is None and desc['requested_domain_ast'] is None
    model = solve(desc)
    assert sp.expand(model['answer_expression'] - (X**2 + 4*sp.Abs(X))) == 0
    assert model['domain_identity'] == 'declared_symmetric_domain' and verify(desc, model)
    assert not verify(desc, {**model, 'domain_identity': 'explicit'})
    answer = answer_for(desc, model)
    assert answer['domain_identity'] == 'declared_symmetric_domain'
    assert answer['declared_domain'] is None and answer['determined_domain'] is None
    assert answer['requested_domain'] is None and answer['source_domain']['expression'] == 'Interval(0, oo)'
    # An abstract odd extension needs f(0)=0 only if 0 ∈ D; the rule's own value decides the merge.
    desc = math_only(candidate('a04', prop='odd', known='(0,∞)', rule='x^2+4*x'))
    model = solve(desc)
    assert [b['set'] for b in model['branches']] == [sp.Interval(-sp.oo, 0), sp.Interval.open(0, sp.oo)]
    assert verify(desc, model)


@pytest.mark.parametrize('text', [
    r'已知 $f(x)$ 为偶函数，若当 $x\ge 0$ 时，$f(x)=x^2+4x$，则当 $x<0$ 时，$f(x)$ 的解析式是____．',
    r'已知 $f(x)$ 是定义在 $\mathbf R$ 上的偶函数，若当 $x\ge 0$ 时，$f(x)=x^2+4x$，则 $f(x)$ 的解析式是____．',
    r'已知 $f(x)$ 为奇函数，若当 $x\ge 0$ 时，$f(x)=x^2+4x$，则 $f(x)$ 的解析式是____．',
])
def test_a04_source_must_match_abstract_whole_request(text):
    assert description(candidate('a04', text=text), 'a04')['reason'] == 'parity_ext.source_not_bound'


def test_whole_domain_request_joins_given_and_mirrored_parts():
    desc = math_only(candidate('a07', requested='ℝ'))
    model = solve(desc)
    assert sp.expand(model['answer_expression'] - (X**2 + sp.Abs(X))) == 0 and verify(desc, model)
    desc = math_only(candidate('a08', requested='ℝ'))
    model = solve(desc)
    assert len(model['branches']) == 3 and verify(desc, model)


@pytest.mark.parametrize('field,value', [
    ('expression', lambda m: m['expression'] + 1),
    ('answer_expression', lambda m: m['answer_expression'] + 1),
    ('sign', lambda m: -m['sign']),
    ('substituted', lambda m: m['rule']),
    ('mapped_domain', lambda m: sp.Interval(0, sp.oo)),
    ('zero_status', lambda m: 'free'),
    ('determined_domain', lambda m: m['determined_domain'] - sp.FiniteSet(0)),
    ('branches', lambda m: m['branches'][:-1] if len(m['branches']) > 1 else
     [{**m['branches'][0], 'set': m['branches'][0]['set'] | sp.Interval(0, 1)}]),
])
@pytest.mark.parametrize('name', ['a07', 'a08', 'a09', 'a04'])
def test_tampered_certificate_fails(name, field, value):
    desc = description(candidate(name), name)
    model = solve(desc)
    assert not verify(desc, {**model, field: value(model)})


@pytest.mark.parametrize('changes,reason', [
    ({'rule': 'x+1', 'prop': 'odd', 'known': '[0,∞)'}, 'parity_ext.overlap_conflict'),
    ({'rule': 'x^2', 'prop': 'odd', 'known': '[-1,2]', 'domain': '[-2,2]', 'requested': '[-2,-1)'},
     'parity_ext.overlap_conflict'),
    ({'rule': 'x^5', 'prop': 'odd'}, 'parity_param.degree_budget'),
    ({'requested': '(-3,0)', 'domain': '(-2,2)', 'known': '(0,2)'}, 'parity_ext.requested_outside_domain'),
    ({'domain': '(-2,3)'}, 'parity_ext.domain_not_symmetric'),
    ({'requested': '(1,2)'}, 'parity_ext.requested_range_not_mirrored'),
    ({'known': '(2,1)'}, 'parity_ext.invalid_interval'),
])
def test_unsupported_or_contradictory_givens_are_gaps(changes, reason):
    desc = math_only(candidate('a08', **changes))
    assert not desc['structure_supported'] and desc['reason'] == reason


def test_rule_is_read_inside_the_declared_domain():
    # “x>0 时” on D=(-2,2) carries values only on (0,2).
    desc = math_only(candidate('a05', known='(0,∞)'))
    model = solve(desc)
    assert model['rule_domain'] == sp.Interval.open(0, 2) and verify(desc, model)


def test_negative_side_known_and_finite_target():
    text = (r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的偶函数，当 $x\le 0$ 时，$f(x)=x^2-3x-1$，'
            r'则当 $x>0$ 时，$f(x)=$____．')
    desc = description(candidate('a08', prop='even', known='(-∞,0]', requested='(0,∞)', text=text))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert sp.expand(model['expression'] - (X**2+3*X-1)) == 0 and verify(desc, model)
    desc = math_only(candidate('a08', prop='even', known='[0,∞)', requested='[-2,-1]'))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert sp.expand(model['expression'] - (X**2+3*X-1)) == 0 and verify(desc, model)


def test_even_free_zero_is_reported_not_guessed():
    desc = math_only(candidate('a08', prop='even', requested='(-∞,0]'))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert model['status'] == 'insufficient_information' and model['free_domain'] == sp.FiniteSet(0)
    assert model['determined_domain'] == sp.Reals - sp.FiniteSet(0) and verify(desc, model)
    assert not verify(desc, {**model, 'free_domain': sp.EmptySet})
    assert not verify(desc, {**model, 'status': 'determined_on_domain'})
    answer = answer_for(desc, model)
    assert answer['status'] == 'insufficient_information'
    assert answer['free_domain']['expression'] == '{0}'
    assert answer['determined_domain']['expression'] == 'Interval.open(-oo, 0)'


def test_point_rule_fixes_zero_or_contradicts_oddness():
    desc = math_only(candidate('a08', prop='even', requested='ℝ', extra_facts=['f(0)=1']))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert model['status'] == 'determined_on_domain' and verify(desc, model)
    assert model['determined_domain'] == sp.Reals
    zero, = [b for b in model['branches'] if b['set'] == sp.FiniteSet(0)]
    assert zero['expression'] == 1
    desc = math_only(candidate('a08', extra_facts=['f(0)=1']))
    assert desc['reason'] == 'parity_ext.overlap_conflict'
    desc = math_only(candidate('a08', extra_facts=['f(1)=2']))
    assert desc['reason'] == 'parity_ext.overlap_conflict'
    # f(1)=1-3-1=-3, so the odd point f(-1)=3 agrees and f(-1)=2 does not.
    assert math_only(candidate('a08', extra_facts=['f(-1)=3']))['structure_supported']
    desc = math_only(candidate('a08', extra_facts=['f(-1)=2']))
    assert desc['reason'] == 'parity_ext.overlap_conflict'


def test_point_rule_is_bound_to_its_printed_formula():
    text = (r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的偶函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，且 $f(0)=1$，'
            r'则 $f(x)$ 的解析式是____．')
    value = candidate('a08', prop='even', requested=None, text=text, extra_facts=['f(0)=1'])
    del value['root']['goals'][0]['requested_domain']
    desc = description(value)
    assert desc['structure_supported'], desc['reason']
    assert solve(desc)['status'] == 'determined_on_domain'
    wrong = candidate('a08', prop='even', text=text.replace('f(0)=1', 'f(0)=2'), extra_facts=['f(0)=1'])
    del wrong['root']['goals'][0]['requested_domain']
    assert description(wrong)['reason'] == 'parity_ext.source_not_bound'


def test_second_local_rule_is_a_capability_gap():
    value = candidate('a08')
    value['root']['goals'][0]['additional_relations'] = ['f(x)=x']
    assert math_only(value)['reason'] == 'parity_ext.additional_relation_unsupported'
    value = candidate('a08', extra_facts=['f(x)=2*x'])
    assert math_only(value)['reason'] == 'parity_ext.additional_condition_unsupported'


def test_radical_rule_is_substituted_on_its_range():
    desc = math_only(candidate('a08', rule='sqrt(x)+1'))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert sp.simplify(model['expression'] - (-sp.sqrt(-X) - 1)) == 0 and verify(desc, model)
    assert math_only(candidate('a08', rule='sqrt(x-1)'))['reason'] == 'parity_ext.rule_undefined_on_range'
    assert math_only(candidate('a08', rule='1/x'))['structure_supported']
    assert math_only(candidate('a08', rule='1/(x-1)'))['reason'] == 'parity_ext.rule_undefined_on_range'
    assert math_only(candidate('a08', rule='sqrt(x)+sqrt(x+1)+sqrt(x+2)'))['reason'] == \
        'parity_ext.radical_budget'


@pytest.mark.parametrize('signs,here,mirror,zero,role', [
    ([-1], True, True, False, 'overlap'), ([1], True, False, False, 'known'),
    ([1], False, True, False, 'mirrored'), ([-1], False, False, True, 'forced_zero'),
    ([1], False, False, True, 'free'), ([1, -1], False, False, False, 'forced_zero'),
])
def test_shared_atom_roles(signs, here, mirror, zero, role):
    assert compatibility.atom_role(signs, here, mirror, zero) == role


def test_shared_atoms_partition_finite_domain_with_holes():
    domain = sp.Interval.open(-2, 2) - sp.FiniteSet(-1, 1)
    atoms = compatibility.fixed_atoms(domain, sp.Interval.open(0, 1), [-1])
    assert [a['role'] for a in atoms] == ['free', 'mirrored', 'forced_zero', 'known', 'free']
    assert sp.Union(*(a['set'] for a in atoms)) == domain


@pytest.mark.parametrize('name', ['a07', 'a08', 'a09', 'a04'])
def test_source_bound_recognition_and_single_method(name):
    value = candidate(name)
    original = deepcopy(value)
    report = extract_features(value)
    assert report['ok']
    rows = [r for r in report['features'] if r['target_ref'] == target(name)]
    supported = [r['type_id'] for r in evaluate_types(rows) if r['status'] == 'supported']
    assert supported == ['type-parity-formula']
    selected = evaluate_goal(value, target(name), rows, 'type-parity-formula')
    assert selected['d3']['submit_label'] == '用对称补全法解题'
    assert value == original


@pytest.mark.parametrize('text', [
    r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的偶函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，则当 $x<0$ 时，$f(x)=$____．',
    r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x\ge 0$ 时，$f(x)=x^2-3x-1$，则当 $x<0$ 时，$f(x)=$____．',
    r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^2-3x+1$，则当 $x<0$ 时，$f(x)=$____．',
    r'函数 $f(x)$ 是奇函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，则当 $x<0$ 时，$f(x)=$____．',
    r'函数 $f(x)$ 是定义在 $(-2,2)$ 上的奇函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，则当 $x<0$ 时，$f(x)=$____．',
    r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，且 $f(1)=2$，则当 $x<0$ 时，$f(x)=$____．',
    r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，则当 $x<-1$ 时，$f(x)=$____．',
    r'函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^2-3x-1$，则 $f(-3)=$____；当 $x<0$ 时，$f(x)=$____．',
])
def test_changed_source_cannot_admit_the_route(text):
    value = candidate('a08', text=text)
    rows = extract_features(value)['features']
    feature = next(r for r in rows if r['feature_id'] == 'parity_extension')
    assert not feature['value']['structure_supported']
    assert not any(r['status'] == 'supported' and r['type_id'] == 'type-parity-formula' for r in evaluate_types(rows))
    assert evaluate_goal(value, TARGET, rows, 'type-parity-formula')['status'] == 'no_applicable_method'


def test_unresolved_source_is_a_gap():
    value = candidate('a08')
    value['root']['uncertainties'] = [{'kind': 'unreadable', 'text': '原图不等号不清楚'}]
    assert description(value)['reason'] == 'parity_ext.unresolved_source'
