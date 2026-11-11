"""Joint affine parameter families, including free variables and finite domains."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import function_cells
from shuxueshuo_server.graph_lesson import linear_parameter_family as linear
from shuxueshuo_server.graph_lesson import parity_parameter_joint as joint
from shuxueshuo_server.graph_lesson import parity_parameter_math as math
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_parser import NotationError
from tests.solver.test_graph_parity_parameter import candidate, description


def pair_candidate(expr='a*x^2+b*x', prop='odd', *, facts=(), names=('a', 'b'), goal_kind='find_value'):
    return candidate(expr, prop, parameter='('+','.join(names)+')', facts=facts, goal_kind=goal_kind)


@pytest.mark.parametrize('expr,prop,facts,values,free', [
    ('a*x^2+b*x', 'odd', (), [0, 'b'], ['b']),
    ('a*x^2+b', 'odd', ('Dom(f)={-1,1}',), ['-b', 'b'], ['b']),
    ('a*x^2+b', 'odd', (), [0, 0], []),
    ('a*x^4+b*x^2', 'even', (), ['a', 'b'], ['a', 'b']),
    ('(a-2)*x^2+(b+3)', 'odd', (), [2, -3], []),
    ('a*x^2+b*x', 'both', (), [0, 0], []),
    ('a*x^2+b*x', 'odd', ('a+b=3',), [0, 3], []),
    ('a*x^2+b', 'odd', ('Dom(f)={0}',), ['a', 0], ['a']),
    ('a*x^2+b', 'odd', ('Dom(f)=[-1,1]',), [0, 0], []),
    ('a*x^2+b*x', 'even', ('Dom(f)=ℝ∖{0}',), ['a', 0], ['a']),
    ('a*x^2+b*x', 'even', ('Dom(f)=(-∞,-1]∪[1,∞)',), ['a', 0], ['a']),
    ('a*x^2+b*x', 'even', ('Dom(f)=(-∞,∞)',), ['a', 0], ['a']),
])
def test_joint_families(expr, prop, facts, values, free):
    d = description(pair_candidate(expr, prop, facts=facts))
    result = math.solve(d)
    assert math.verify(d, result)
    assert math.verify(d, decode_value(encode_value(result)))
    family, = result['solution']
    ps = {name: sp.Symbol(name, real=True) for name in ('a', 'b')}
    assert family['values'] == [sp.sympify(v, locals=ps) for v in values]
    assert family['free_parameters'] == [ps[n] for n in free]


@pytest.mark.parametrize('expr,prop,facts', [
    ('a*x^2+b*x+1', 'odd', ()),
    ('a*x^2+b*x', 'odd', ('a=1',)),
    ('a*x^2+b*x', 'odd', ('degree(f)=2',)),
    ('0', 'odd_only', ()),
    ('a*x+b', 'even', ('a!=0',)),
    ('a*x+b', 'even', ('Dom(f)=[0,1]',)),
    ('a*x+b', 'even', ('Dom(f)=[0,0]',)),
    ('a*x+b', 'even', ('Dom(f)=ℝ', 'Dom(f)=[-1,1]')),
])
def test_complete_empty_solution(expr, prop, facts):
    d = description(pair_candidate(expr, prop, facts=facts))
    result = math.solve(d)
    assert result['solution'] == []
    assert math.verify(d, result)


def test_exclusions_and_disjunctions_are_joint_conditions():
    d = description(pair_candidate('a*x^2+b*x', 'odd_only'))
    result = math.solve(d)
    family, = result['solution']
    assert family['nonzero'] == [sp.Symbol('b', real=True)]
    assert math.verify(d, result)
    d = description(pair_candidate('a*x^2+b', 'odd', facts=('Dom(f)={-1,1}', 'a+b!=0')))
    result = math.solve(d)
    assert result['solution'] == [] and math.verify(d, result)
    d = description(pair_candidate('a*x^2+b', 'even', facts=('a=1 ∨ b=2',)))
    result = math.solve(d)
    assert len(result['solution']) == 2 and math.verify(d, result)


def test_independent_verification_rejects_lost_free_variables_and_row_tampering(monkeypatch):
    d = description(pair_candidate('a*x^2+b', 'odd', facts=('Dom(f)={-1,1}', 'a!=0')))
    result = math.solve(d)
    def forbidden(*args, **kwargs):
        pytest.fail('verification must not repeat production solving or comparison')
    monkeypatch.setattr(joint, 'solve', forbidden)
    monkeypatch.setattr(joint, 'compare', forbidden)
    monkeypatch.setattr(linear, 'solve', forbidden)
    monkeypatch.setattr(linear, 'reduce_rows', forbidden)
    assert math.verify(d, result)
    for key, wrong in [('free_parameters', []), ('nonzero', []), ('values', [0, 0])]:
        changed = deepcopy(result)
        changed['solution'][0][key] = wrong
        assert not math.verify(d, changed)
    changed = deepcopy(result)
    changed['elimination']['records'][0]['operations'][1]['factor'] = sp.S.Zero
    assert not math.verify(d, changed)
    changed = deepcopy(result)
    changed['comparison']['equations'] = []
    assert not math.verify(d, changed)


@pytest.mark.parametrize('expr,facts', [
    ('a*b*x', ()), ('a*x+b', ('a>b',)), ('a*x+b', ('Dom(f)=[-a,a]',)),
    ('a/(x-b)', ()), ('a*x^5+b', ()), ('c*x^2+a*x+b', ()),
    ('sqrt(a*x^2+b)', ()), ('a*x+b', ('a^2+b=0',)),
    ('a*x+b', ('a/a=1',)),
])
def test_outside_joint_contract_is_capability_gap(expr, facts):
    d = build_context(pair_candidate(expr, facts=facts), '/root/goals/0')['parity_parameter_goal']
    assert not d['structure_supported'] and d['reason']


@pytest.mark.parametrize('domain,ast', [
    ('[-∞,∞]', ['interval', True, True, ['infinity', -1], ['infinity', 1]]),
    ('{-∞,∞}', ['set', ['infinity', -1], ['infinity', 1]]),
])
def test_infinity_is_only_an_open_interval_endpoint(domain, ast):
    value = pair_candidate('a*x+b', facts=(f'Dom(f)={domain}',))
    assert not NotationValidator().validate(value).ok
    with pytest.raises(ValueError, match='context.invalid_candidate'):
        build_context(value, '/root/goals/0')
    with pytest.raises(NotationError):
        function_cells.input_set(ast)


@pytest.mark.parametrize('wording', ['$a,b$', 'a、b', '$b$ 与 $a$', '（a，b）'])
def test_written_joint_request_keeps_both_parameters(wording):
    value = pair_candidate()
    value['original_text'] = value['original_text'].replace('$(a,b)$', wording)
    d = description(value)
    assert d['parameters'] == ['a', 'b']
    result = math.solve(d)
    assert math.verify(d, result)
    value['original_text'] = value['original_text'].replace(wording, '$a$')
    d = build_context(value, '/root/goals/0')['parity_parameter_goal']
    assert not d['structure_supported']


def test_ordered_parameters_keep_free_variables_and_complete_union():
    d = description(pair_candidate('a*x^2+b', 'odd', facts=('Dom(f)={-1,1}',), names=('b', 'a')))
    result = math.solve(d)
    _b, a = joint.symbols(d)[1]
    assert result['solution'][0]['values'] == [-a, a]
    assert result['solution'][0]['free_parameters'] == [a]
    assert math.verify(d, result)
    d = description(pair_candidate('a*x^2+b', 'even', facts=('a=1 ∨ b=2',)))
    result = math.solve(d)
    changed = deepcopy(result)
    changed['solution'].pop()
    assert not math.verify(d, changed)


def test_joint_branch_budget_returns_gap_instead_of_dropping_cases():
    fact = ' ∨ '.join(f'a={i}' for i in range(9))
    d = build_context(pair_candidate('a*x^2+b', 'even', facts=(fact,)), '/root/goals/0')['parity_parameter_goal']
    assert not d['structure_supported'] and 'branch_budget' in d['reason']


def test_finite_domain_tex_is_preserved_and_cannot_be_replaced_with_reals():
    value = pair_candidate('a*x^2+b', 'odd', facts=('Dom(f)={-1,1}',))
    value['original_text'] = value['original_text'].replace('$Dom(f)={-1,1}$', r'定义域为 $\{-1,1\}$')
    assert description(value)['domain_ast'][0] == 'set'
    value['root']['facts'][-1] = 'Dom(f)=ℝ'
    d = build_context(value, '/root/goals/0')['parity_parameter_goal']
    assert not d['structure_supported']


@pytest.mark.parametrize('goal', [
    {'kind': 'find_value', 'expression': '(a,a)'},
    {'kind': 'find_value', 'expression': '(a,b,c)'},
    {'kind': 'find_value', 'expression': '(a,f)'},
    {'kind': 'find_range', 'object': '(a,b)'},
])
def test_joint_target_does_not_weaken_unrelated_notation_contracts(goal):
    value = pair_candidate()
    value['root']['goals'] = [goal]
    assert not NotationValidator().validate(value).ok
