"""R1 complete domain pairing, finite-input parity and local extension contracts."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import parameter_domain as domains
from shuxueshuo_server.graph_lesson import parity_parameter_domain as domain_math
from shuxueshuo_server.graph_lesson import parity_parameter_math as math
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_runtime import (
    borrow_domain_parameter,
    verify_borrowed_parameter,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from tests.solver.test_graph_parity_parameter import TARGET, candidate, description


def abstract_candidate(domain='[m-3,2*m]', prop='even', rule=None):
    facts = [f'Dom(f)={domain}', f'parity(f,{prop})', *([rule] if rule else [])]
    return {'original_text': '已知' + '，'.join('$'+f+'$' for f in facts) + '，求 $m$ 的取值范围。',
            'root': {'definitions': [], 'facts': facts, 'goals': [{'kind': 'find_range', 'symbol': 'm'}]}}


@pytest.mark.parametrize('expr,prop,domain,expected', [
    ('x^2', 'even', '[-m,m]', sp.Interval.open(0, sp.oo)),
    ('x^2', 'even', '(-m,m)', sp.Interval.open(0, sp.oo)),
    ('x^2', 'even', '[-m,m)', sp.S.EmptySet),
    ('x^2', 'odd', '[-m,m]', sp.S.EmptySet),
    ('x^2', 'both', '{0}', sp.S.Reals),
    ('x^2', 'even', '∅', sp.S.EmptySet),
    ('m*x^2+1', 'odd', '{-1,1}', sp.FiniteSet(-1)),
    ('m*x', 'odd_only', '{-1,1}', sp.S.Reals-sp.FiniteSet(0)),
    ('m*x', 'odd_only', '{-m,m}', sp.S.Reals-sp.FiniteSet(0)),
    ('x^2', 'even', '[-3,3]∖{1,m}', sp.FiniteSet(-1)),
    ('x^2', 'even', '[-3,3]∖{m}', sp.Interval.open(-sp.oo, -3)|sp.FiniteSet(0)|sp.Interval.open(3, sp.oo)),
    ('x^2', 'even', '[-2,-1]∪[m,m+1]', sp.FiniteSet(1)),
    ('x', 'odd_only', 'ℝ∖{m}', sp.FiniteSet(0)),
    ('x^2', 'even', '[-2,m]∩[-m,2]', sp.Interval(0, sp.oo)),
    ('x^2', 'odd', '[-2,m]∩[-m,2]', sp.FiniteSet(0)),
    ('x^2', 'even', '[-m,m]∪{0}', sp.Interval.open(0, sp.oo)),
])
def test_domain_arrangement_and_all_input_obligations(expr, prop, domain, expected):
    d = description(candidate(expr, prop, facts=(f'Dom(f)={domain}',), goal_kind='find_range'))
    result = math.solve(d)
    assert result['feasible_set'] == expected
    assert math.verify(d, result)
    assert math.verify(d, decode_value(encode_value(result)))


@pytest.mark.parametrize('domain,prop,rule,expected', [
    ('[m-3,2*m]', 'even', None, sp.FiniteSet(1)),
    ('[-2*m,m+1]', 'even', None, sp.FiniteSet(1)),
    ('{0}', 'odd_only', None, sp.S.EmptySet),
    ('{0}', 'even_only', None, sp.S.Reals),
    ('{0}', 'both', None, sp.S.Reals),
    ('ℝ', 'odd', '∀x∈[0,∞):f(x)=x^2+m', sp.FiniteSet(0)),
    ('ℝ', 'odd', '∀x∈(0,∞):f(x)=x^2+m', sp.S.Reals),
    ('ℝ', 'odd_only', '∀x∈(0,∞):f(x)=0', sp.S.EmptySet),
    ('ℝ', 'even_only', '∀x∈(0,∞):f(x)=0', sp.S.Reals),
    ('ℝ', 'even_only', '∀x∈[0,∞):f(x)=0', sp.S.EmptySet),
    ('[m-5,1-2*m]', 'odd', '∀x∈(Dom(f)∩[0,∞)):f(x)=x^2-2*x', sp.FiniteSet(-4)),
])
def test_abstract_existence_and_local_rule_compatibility(domain, prop, rule, expected):
    d = description(abstract_candidate(domain, prop, rule))
    result = math.solve(d)
    assert result['feasible_set'] == expected
    assert math.verify(d, result)
    assert d['expression_ast'] is None  # Never invent a complete formula.


def test_domain_certificate_verifier_is_independent_and_rejects_missing_cells(monkeypatch):
    d = description(candidate('m*x^2+1', 'odd', facts=('Dom(f)={-1,1}',)))
    result = math.solve(d)
    def forbidden(*args, **kwargs):
        pytest.fail('verification must not solve the parameter/domain problem again')
    monkeypatch.setattr(domains, 'solve_domain_symmetry_conditions', forbidden)
    monkeypatch.setattr(math, 'solve', forbidden)
    monkeypatch.setattr(domain_math, 'solve', forbidden)
    monkeypatch.setattr(domain_math, 'compare', forbidden)
    monkeypatch.setattr(math, 'condition_set', forbidden)
    assert math.verify(d, result)
    changed = deepcopy(result)
    changed['comparison']['domain_evidence']['cells'].pop()
    assert not math.verify(d, changed)
    changed = deepcopy(result)
    changed['comparison']['rows'][0]['equations'] = []
    assert not math.verify(d, changed)
    changed = deepcopy(result)
    changed['feasible_set'] = sp.S.Reals
    assert not math.verify(d, changed)
    changed = deepcopy(result)
    atom = changed['comparison']['domain_evidence']['cells'][0]['input_atoms'][0]
    atom['member'] = not atom['member']
    assert not math.verify(d, changed)


@pytest.mark.parametrize('domain', ['[-m^2,m]', '[-m,n]', '[-m,m]∪[-2,2]∪[-3,3]∪[-4,4]∪[-5,5]'])
def test_unsupported_domain_is_a_gap_not_an_empty_answer(domain):
    d = build_context(candidate('x^2', facts=(f'Dom(f)={domain}',)), TARGET)['parity_parameter_goal']
    assert not d['structure_supported'] and d['reason']


def test_source_domain_and_local_rule_cannot_be_invented_or_changed():
    original = candidate('x^2')
    original['root']['facts'].append('Dom(f)=[-m,m]')
    assert not build_context(original, TARGET)['parity_parameter_goal']['structure_supported']
    value = abstract_candidate('ℝ', 'odd', '∀x∈(0,∞):f(x)=x^2+m')
    value['root']['facts'][-1] = '∀x∈[0,∞):f(x)=x^2+m'
    assert not build_context(value, TARGET)['parity_parameter_goal']['structure_supported']


def test_defined_on_is_a_separate_obligation_not_the_complete_domain():
    value = candidate('x^2', facts=('defined_on(f,[-1,m])',), goal_kind='find_range')
    value['original_text'] = '已知 $f(x)=x^2$ 为偶函数，原式在区间 $[-1,m]$ 上有意义，求 $m$ 的取值范围。'
    d = description(value)
    assert d['domain_ast'] == ['real']
    result = math.solve(d)
    assert result['feasible_set'] == sp.Interval.open(-1, sp.oo)
    assert math.verify(d, result)
    changed = deepcopy(value)
    changed['root']['facts'][-1] = 'Dom(f)=[-1,m]'
    assert not build_context(changed, TARGET)['parity_parameter_goal']['structure_supported']
    changed['root']['facts'].pop()
    assert not build_context(changed, TARGET)['parity_parameter_goal']['structure_supported']


def test_a15_borrow_returns_to_original_goal_with_unprocessed_conditions():
    value = abstract_candidate('[m-5,1-2*m]', 'odd', '∀x∈(Dom(f)∩[0,∞)):f(x)=x^2-2*x')
    value['root']['facts'].append('m<0')
    value['root']['goals'] = [{'kind': 'find_value', 'expression': 'f(m)'}]
    original = deepcopy(value)
    context = build_context(value, TARGET)
    assert 'parity_parameter_goal' not in context
    result = borrow_domain_parameter(context, 'r:scalar:m', ['/root/facts/0', '/root/facts/1', '/root/facts/2'])
    assert value == original
    assert result['parameter_set'] == sp.FiniteSet(-4)
    assert result['instantiated_domain'] == sp.Interval(-9, 9)
    assert result['parent_target_pending'] is True
    assert result['remaining_source_refs'] == ['/root/facts/3']
    assert result['parent_goal'] == {'kind': 'find_value', 'expression': 'f(m)'}
    assert verify_borrowed_parameter(context, result)
    for key, wrong in [('remaining_source_refs', []), ('parent_target_pending', False),
                       ('instantiated_domain', sp.Interval(-1, 1)), ('parameter_set', sp.FiniteSet(4))]:
        changed = deepcopy(result); changed[key] = wrong
        assert not verify_borrowed_parameter(context, changed)
    changed_context = deepcopy(context)
    changed_context['entries'][0]['ast'][2][1] = False
    assert not verify_borrowed_parameter(changed_context, result)


def test_a20_returns_parameter_without_completing_the_inequality():
    value = abstract_candidate('[-2*m,m+1]')
    value['root']['facts'] += ['∀s∈[-2*m,0]:∀t∈[-2*m,0]:s<t→f(s)<f(t)', 'f(x-1)<=f(2*x)']
    value['root']['goals'] = [{'kind': 'find_range', 'symbol': 'x'}]
    context = build_context(value, TARGET)
    assert 'parity_parameter_goal' not in context
    result = borrow_domain_parameter(context, 'r:scalar:m', ['/root/facts/0', '/root/facts/1'])
    assert result['parameter_set'] == sp.FiniteSet(1)
    assert result['instantiated_domain'] == sp.Interval(-2, 2)
    assert result['remaining_source_refs'] == ['/root/facts/2', '/root/facts/3']
    assert result['parent_goal'] == {'kind': 'find_range', 'symbol': 'x'}
    assert verify_borrowed_parameter(context, result)


def _cards(d, phase, evidence):
    from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_presentation import (
        compile_cards,
    )
    return compile_cards([{'values': {'description': d, 'phase': phase, 'evidence': encode_value(evidence)}}], phase)['parts']


def test_verify_states_the_symmetric_domain_without_number_lines():
    d = description(candidate('x^2', facts=('Dom(f)=[-3,3]∖{1,m}',)))
    model = math.solve(d)
    pending, = _cards(d, 'domain', model['comparison']['domain_evidence'])
    assert 'condition_number_lines' not in pending
    completed, = _cards(d, 'verify', model)
    assert 'condition_number_lines' not in completed
    text = ''.join(completed['stem_board']['lines'])
    assert '=D$$' in text and r'\cup' in text and r'f(-x)=x^{2}' in text
    assert [item['label'] for item in completed['completion_board']['items']] == ['代入 m=-1', '检验']


def test_endpoint_domain_card_names_the_symmetry_equation():
    from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_runtime import card_plan
    d = description(abstract_candidate())
    model = math.solve(d)
    assert card_plan(d) == {'value': False, 'merge': False}
    card, = _cards(d, 'domain', model['comparison']['domain_evidence'])
    assert card['title'] == '检查定义域是否关于原点对称'
    assert '定义域关于原点对称' in card['stem_board']['items'][0]['math']
    labels = {o['value']: o['label'] for o in card['interaction']['options']}
    correct, = card['expected_answer']['one_of']
    assert labels[correct] == r'$(m-3)+2\cdot m=0\ \Rightarrow\ m=1$'
    wrong = [v for k, v in labels.items() if k != correct]
    assert wrong and all('m=1$' not in v for v in wrong)
    verify, = _cards(d, 'verify', model)
    assert verify['stem_board']['lines'][:2] == [r'$$D=\left[-2, 2\right]$$', r'$$-D=\left[-2, 2\right]=D$$']


def test_formula_or_restriction_keeps_the_merge_cards():
    from shuxueshuo_server.graph_lesson.stage_three.parity_parameter_runtime import card_plan
    assert card_plan(description(candidate('m*x^2+1', 'odd', facts=('Dom(f)={-1,1}',)))) == {'value': True, 'merge': True}
    assert card_plan(description(abstract_candidate(prop='even_only'))) == {'value': False, 'merge': True}
