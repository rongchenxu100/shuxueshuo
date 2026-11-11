"""FP-T3 review regressions and source-bound mechanism variations, without live model calls."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import parity_extension_math as extension
from shuxueshuo_server.graph_lesson import symmetry_value_math as symmetry
from shuxueshuo_server.graph_lesson.stage_three import (
    parity_extension_runtime as runtime,
)
from shuxueshuo_server.graph_lesson.stage_three.parity_extension_presentation import (
    phase_views as formula_views,
)
from shuxueshuo_server.graph_lesson.stage_three.symmetry_presentation import (
    phase_views as value_views,
)
from tests.solver.test_graph_parity_extension import candidate, description, math_only
from tests.solver.test_graph_symmetry_value import candidate as value_candidate
from tests.solver.test_graph_symmetry_value import description as value_description
from tests.solver.test_graph_symmetry_value import pair_goal, rule_goal

X = sp.Symbol('x', real=True)


@pytest.mark.parametrize('name,expected', [('a03', -2), ('a06', 5)])
def test_identity_can_be_an_ordinary_fact_without_changing_point_equations(name, expected):
    value = deepcopy(value_candidate(name))
    goal = value['root']['goals'][0]
    value['root']['facts'].append(goal['relation'])
    value['root']['goals'][0] = {'kind': 'find_value', 'expression': goal['expression']}
    desc = value_description(value)
    assert desc['structure_supported'], desc['reason']
    model = symmetry.solve(desc)
    assert model['value'] == expected and symmetry.verify(desc, model)
    # Fixed-point equations must not be promoted to identities.
    point = value_description(value_candidate('a13'))
    assert not point['identities'] and symmetry.solve(point)['value'] == -3


def test_repeated_local_rule_keeps_both_source_references_but_one_teaching_rule():
    value = candidate('a04', extra_facts=['∀x∈[0,∞):f(x)=x^2+4*x'])
    desc = description(value)
    assert desc['structure_supported'], desc['reason']
    row, = extension.rule_rows(desc)
    assert len(row['source_refs']) == 2
    model = extension.solve(desc)
    assert model['answer_expression'] == X**2 + 4*sp.Abs(X) and extension.verify(desc, model)
    value['root']['facts'][-1] = '∀x∈(0,∞):f(x)=x^2+4*x'
    assert description(value)['reason'] == 'parity_ext.source_not_bound'


def test_local_scope_can_explicitly_intersect_its_function_domain():
    value = value_candidate('a15')
    value['root']['facts'] = [*value['root']['facts'], '∀x∈[0,∞)∩Dom(f):f(x)=x^2-2*x']
    value['root']['goals'] = [{'kind': 'find_value', 'expression': 'f(m)'}]
    desc = value_description(value)
    assert desc['structure_supported'], desc['reason']
    assert desc['parameter']['name'] == 'm'
    assert desc['identities'][0]['domain_ast'] == ['interval', True, False, ['number', '0'], ['infinity', 1]]
    # A union or subtraction is not a redundant domain restriction.
    changed = deepcopy(value)
    changed['root']['facts'][-1] = '∀x∈[0,∞)∪Dom(f):f(x)=x^2-2*x'
    assert not value_description(changed)['structure_supported']
    domain = ['call', 'Dom', ['ref', 'r:function:f', 'function']]
    difference = ['set_difference', ['real'], domain]
    assert extension.within_domain_scope(difference, {'r:function:f'}) == difference


@pytest.mark.parametrize('name', ['a03', 'a06'])
def test_parity_words_are_bound_to_their_functions(name):
    value = value_candidate(name)
    value['root']['facts'] = [s.replace('parity(f,odd)', 'parity(f,even)').replace('parity(g,even)', 'parity(g,odd)')
                             for s in value['root']['facts']]
    assert value_description(value)['reason'] == 'symmetry_value.source_not_bound'


@pytest.mark.parametrize('intro', [r'奇函数 $f(x)$ 与偶函数 $g(x)$',
                                  r'$f(x)$ 是奇函数，$g(x)$ 是偶函数',
                                  r'$f(x)$，$g(x)$ 分别是奇函数和偶函数'])
def test_property_placement_keeps_the_same_function_binding(intro):
    value = value_candidate('a03', text='已知' + intro + r'，且 $f(x)+g(x)=x^2-x+1$，则 $f(2)=$____．')
    desc = value_description(value)
    assert desc['structure_supported'], desc['reason']
    assert symmetry.solve(desc)['value'] == -2
    value['root']['facts'] = ['parity(f,even)', 'parity(g,odd)']
    assert value_description(value)['reason'] == 'symmetry_value.source_not_bound'


@pytest.mark.parametrize('rule', ['sqrt(-x)*sqrt(-x)', 'sqrt(x-1)-sqrt(x-1)+x'])
def test_cancelled_radicals_still_require_real_original_inputs(rule):
    desc = math_only(candidate('a08', rule=rule))
    assert desc['reason'] == 'parity_ext.rule_undefined_on_range'
    desc = value_description(value_candidate(goal=rule_goal('f(-2)', rule=rule)), bound=False)
    assert desc['reason'] == 'symmetry_value.rule_undefined_on_range'
    # Even if a producer incorrectly labels the description supported, the verifier rejects it.
    desc['structure_supported'] = True
    try:
        model = symmetry.solve(desc)
    except ValueError:
        return
    assert not symmetry.verify(desc, model)


def test_two_identities_cannot_hide_their_conflict_at_a_special_target():
    facts = ['parity(f,odd)', 'parity(g,even)', '∀x∈ℝ:f(x)+g(x)=x', '∀x∈ℝ:f(x)+g(x)=x^3']
    value = value_candidate('a03', facts=facts, goal={'kind': 'find_value', 'expression': 'f(1)'},
                            text=r'已知 $f(x)$ 是奇函数，$g(x)$ 是偶函数，对任意实数 $x$ 都有 '
                                 r'$f(x)+g(x)=x$ 且 $f(x)+g(x)=x^3$，则 $f(1)=$____．')
    desc = value_description(value)
    assert desc['reason'] == 'symmetry_value.conditions_inconsistent'
    desc['structure_supported'] = True
    assert not symmetry.verify(desc, symmetry.solve(desc))


def test_distinct_even_functions_have_distinct_zero_values():
    desc = value_description(value_candidate('a03', facts=['parity(f,even)', 'parity(g,even)'],
                            goal=pair_goal('f(x)-g(x)=2', 'f(1)-g(1)'),
                            text=r'已知 $f(x)$ 是偶函数，$g(x)$ 是偶函数，且 $f(x)-g(x)=2$，则 $f(1)-g(1)=$____．'))
    assert desc['structure_supported'], desc['reason']
    model = symmetry.solve(desc)
    assert model['value'] == 2 and symmetry.verify(desc, model)


def test_rational_cancellation_confirms_on_the_original_punctured_domain():
    desc = math_only(candidate('a07', domain='ℝ∖{-1,1}', rule='(x^2-1)/(x-1)', requested='ℝ'))
    assert desc['reason'] == 'parity_ext.requested_outside_domain'
    value = candidate('a07', domain='ℝ∖{-1,1}', rule='(x^2-1)/(x-1)')
    del value['root']['goals'][0]['requested_domain']
    desc = math_only(value)
    assert desc['structure_supported'], desc['reason']
    mapping = runtime.map_input(desc)['outputs']['mapping']
    substitution = runtime.substitute(desc, mapping)['outputs']['substitution']
    write_back = runtime.write_back(desc, substitution)['outputs']['write_back']
    model = runtime.confirm(desc, mapping, substitution, write_back)['outputs']['parity_extension_result']
    assert model['answer_expression'] == sp.Abs(X) + 1
    assert model['domain'] == sp.S.Reals - sp.FiniteSet(-1, 1)


@pytest.mark.parametrize('rhs,expected', [('sqrt(x^2+1)', sp.sqrt(2)), ('abs(x-1)+abs(x+1)', sp.Integer(2))])
def test_every_admitted_identity_renders_in_all_teaching_phases(rhs, expected):
    desc = value_description(value_candidate('a03', goal=pair_goal('f(x)+g(x)=' + rhs, 'g(1)'),
                            text=rf'已知 $f(x)$ 是奇函数，$g(x)$ 是偶函数，且 $f(x)+g(x)={rhs}$，则 $g(1)=$____．'))
    assert desc['structure_supported'], desc['reason']
    model = symmetry.solve(desc)
    assert model['value'] == expected and symmetry.verify(desc, model)
    for phase in ('rewrite', 'evaluate', 'conclude'):
        assert value_views({'description': desc, 'phase': phase})


def multi_rule_candidate(consistent=False):
    second = 'x+2' if consistent else 'x+1'
    value = candidate('a08', prop='odd', domain='[-3,3]', rule='x^2', known='(0,2]', requested='[-3,0]',
                      extra_facts=[f'∀x∈[2,3]:f(x)={second}'],
                      text=rf'函数 $f(x)$ 是定义在 $[-3,3]$ 上的奇函数，当 $0<x\le2$ 时，$f(x)=x^2$，'
                           rf'当 $2\le x\le3$ 时，$f(x)={second}$，则当 $-3\le x\le0$ 时，$f(x)=$____．')
    # Consistent endpoint is 4; x+1 conflicts at x=2 and x+2 agrees.
    return value


def test_multiple_local_rules_check_overlap_and_join_reflected_pieces():
    assert description(multi_rule_candidate())['reason'] == 'parity_ext.overlap_conflict'
    desc = description(multi_rule_candidate(consistent=True))
    assert desc['structure_supported'], desc['reason']
    model = extension.solve(desc)
    assert extension.verify(desc, model)
    assert model['answer_expression'].subs(X, -3) == -5
    assert model['answer_expression'].subs(X, -2) == -4
    assert model['answer_expression'].subs(X, 0) == 0
    for phase in ('map', 'substitute', 'write_back', 'conclude'):
        assert formula_views({'description': desc, 'phase': phase})
    forged = deepcopy(model)
    forged['branches'][0]['expression'] += 1
    assert not extension.verify(desc, forged)


def test_absolute_value_uses_its_own_turning_point():
    desc = description(candidate('a07', rule='abs(x-1)',
                       text=r'已知函数 $f(x)$ 是定义域为 $\mathbf R$ 的偶函数，当 $x\ge0$ 时，$f(x)=|x-1|$，'
                            r'则当 $x<0$ 时，$f(x)=$____．'))
    assert desc['structure_supported'], desc['reason']
    model = extension.solve(desc)
    assert extension.verify(desc, model)
    assert extension._agree(model['answer_expression'], sp.Abs(X+1), sp.Interval.open(-sp.oo, 0), X)
    assert not extension._agree(sp.Abs(X-1), X-1, sp.Interval(0, 2), X)
    for phase in ('substitute', 'write_back', 'conclude'):
        assert formula_views({'description': desc, 'phase': phase})


def test_odd_and_even_property_forces_zero_on_ungiven_parts():
    desc = description(candidate('a08', prop='both', rule='0', known='(1,2)', requested='ℝ',
                       text=r'函数 $f(x)$ 是定义在 $\mathbf R$ 上既是奇函数又是偶函数，当 $1<x<2$ 时，$f(x)=0$，'
                            r'则当 $x\in\mathbf R$ 时，$f(x)=$____．'))
    assert desc['structure_supported'], desc['reason']
    model = extension.solve(desc)
    assert model['answer_expression'] == 0 and model['free_domain'] == sp.S.EmptySet
    assert extension.verify(desc, model)
    assert formula_views({'description': desc, 'phase': 'conclude'})
    assert math_only(candidate('a08', prop='both', rule='x'))['reason'] == 'parity_ext.overlap_conflict'
    value = value_candidate(facts=['Dom(f)=ℝ', 'parity(f,both)'],
                            goal={'kind': 'find_value', 'expression': 'f(-sqrt(2))+f(3)'},
                            text=r'已知函数 $f(x)$ 是定义在 $\mathbf R$ 上既是奇函数又是偶函数，则 $f(-sqrt(2))+f(3)=$____．')
    desc = value_description(value)
    assert desc['structure_supported'], desc['reason']
    assert symmetry.solve(desc)['value'] == 0
    proof = ' '.join(v['proof'] for v in value_views({'description': desc, 'phase': 'rewrite'}))
    assert 'f(3)=0' in proof and 'f(0)=0' not in proof


def test_quadratic_irrational_input_and_endpoint_are_exact():
    desc = value_description(value_candidate(goal=rule_goal('f(-sqrt(2))', rule='x^2+x'),
                            text=r'已知函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^2+x$，'
                                 r'则 $f(-sqrt(2))=$____．'))
    assert desc['structure_supported'], desc['reason']
    model = symmetry.solve(desc)
    assert model['value'] == -2-sp.sqrt(2) and symmetry.verify(desc, model)
    desc = math_only(candidate('a08', domain='[-sqrt(2),sqrt(2)]', known='(0,sqrt(2)]',
                               requested='[-sqrt(2),0]', rule='x^2'))
    assert desc['structure_supported'], desc['reason']
    model = extension.solve(desc)
    assert model['requested_domain'] == sp.Interval(-sp.sqrt(2), 0) and extension.verify(desc, model)


def test_local_identities_are_checked_together_including_their_reflections():
    facts = ['parity(f,odd)', '∀x∈(0,2):f(x)=x', '∀x∈(-2,0):f(x)=x']
    value = value_candidate(facts=facts, goal={'kind': 'find_value', 'expression': 'f(-1)'},
                            text=r'已知函数 $f(x)$ 是奇函数，当 $0<x<2$ 时，$f(x)=x$，'
                                 r'当 $-2<x<0$ 时，$f(x)=x$，则 $f(-1)=$____．')
    desc = value_description(value)
    assert desc['structure_supported'], desc['reason']
    model = symmetry.solve(desc)
    assert model['value'] == -1 and symmetry.verify(desc, model)
    value['root']['facts'][-1] = '∀x∈(-2,0):f(x)=x^3'
    assert value_description(value, bound=False)['reason'] == 'symmetry_value.conditions_inconsistent'
