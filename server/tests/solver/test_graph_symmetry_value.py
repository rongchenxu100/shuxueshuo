"""FP-T3 R2: parity values at numeric inputs are rewritten, substituted and certified."""
import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.symmetry_value_math import describe, solve, verify
from tests.solver.test_graph_parity_extension import candidate as extension_candidate

TARGET = '/root/goals/0'
TEXTS = {
    'a12': r'已知函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^3+2x+1$，'
           r'则 $f(0)+f(-1)=$____．',
    'a13': r'已知 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，且 $f(-1)+f(2)=3$，则 $f(1)+f(-2)=$____．',
    'a03': r'已知函数 $f(x)$ 是奇函数，函数 $g(x)$ 为偶函数，若 $f(x)+g(x)=x^2-x+1$，则 $f(2)=$____．',
    'a06': r'已知 $f(x)$，$g(x)$ 分别是定义在 $\mathbf R$ 上的奇函数和偶函数，且 $f(x)-g(x)=x^3+x^2-1$，'
           r'则 $f(2)+g(2)=$____．',
    'a15': r'已知定义在 $[m-5,1-2m]$ 上的奇函数 $f(x)$，当 $x\ge0$ 时，$f(x)=x^2-2x$，则 $f(m)$ 的值为____．',
}
PAIRS = {'a03': (['parity(f,odd)', 'parity(g,even)'], 'f(x)+g(x)=x^2-x+1', 'f(2)'),
         'a06': (['Dom(f)=ℝ', 'Dom(g)=ℝ', 'parity(f,odd)', 'parity(g,even)'], 'f(x)-g(x)=x^3+x^2-1', 'f(2)+g(2)')}


def pair_goal(relation, expression):
    return {'kind': 'find_value', 'function': 'f', 'variable': 'x', 'relation': relation, 'expression': expression}


def rule_goal(expression, rule='x^3+2*x+1', known='(0,∞)'):
    return {'kind': 'find_value', 'function': 'f', 'variable': 'x', 'relation': f'f(x)={rule}',
            'relation_domain': known, 'expression': expression}


def candidate(name='a12', *, facts=None, goal=None, text=None):
    if name == 'a09':
        return extension_candidate('a09')
    if name in PAIRS:
        given, relation, expression = PAIRS[name]
        facts = facts or given
        goal = goal or pair_goal(relation, expression)
    elif name == 'a12':
        facts = facts or ['Dom(f)=ℝ', 'parity(f,odd)']
        goal = goal or rule_goal('f(0)+f(-1)')
    elif name == 'a15':
        facts = facts or ['Dom(f)=[m-5,1-2*m]', 'parity(f,odd)']
        goal = goal or rule_goal('f(m)', rule='x^2-2*x', known='[0,∞)')
    else:
        facts = facts or ['Dom(f)=ℝ', 'parity(f,odd)', 'f(-1)+f(2)=3']
        goal = goal or {'kind': 'find_value', 'expression': 'f(1)+f(-2)'}
    return {'original_text': text or TEXTS.get(name, 't'), 'root': {'facts': facts, 'goals': [goal]}}


def description(value, bound=True):
    context = build_context(value, TARGET)
    return describe(context['goal'], context['goal_ast'], TARGET, context['entries'],
                    candidate=value if bound else None)


@pytest.mark.parametrize('name,expected', [('a09', -15), ('a12', -4), ('a13', -3)])
def test_gold_values_are_certified(name, expected):
    desc = description(candidate(name))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert model['status'] == 'determined' and model['value'] == expected
    assert verify(desc, model)


def test_a12_zero_is_odd_and_negative_input_is_mirrored():
    model = solve(description(candidate('a12')))
    routes = {c['input']: c['route'] for c in model['calls']}
    assert routes == {0: 'zero', -1: 'mirrored_rule'}
    assert model['keys'] == [] and model['multipliers'] == []


def test_a13_rewrites_towards_the_given_combination():
    model = solve(description(candidate('a13')))
    assert model['keys'] == [['f', -1], ['f', 2]]
    assert model['target_coefficients'] == [-1, -1] and model['multipliers'] == [-1]


def test_only_the_combination_is_determined():
    desc = description(candidate('a13', goal={'kind': 'find_value', 'expression': 'f(1)'}), bound=False)
    model = solve(desc)
    assert model['status'] == 'insufficient_information' and model['value'] is None
    assert len(model['witnesses']) == 2 and verify(desc, model)
    assert not verify(desc, {**model, 'witnesses': [model['witnesses'][0]] * 2})


def test_repeated_calls_keep_their_count():
    value = candidate('a13', facts=['Dom(f)=ℝ', 'parity(f,odd)', 'f(2)=5'],
                      goal={'kind': 'find_value', 'expression': 'f(2)+f(-2)+f(2)'})
    desc = description(value, bound=False)
    assert solve(desc)['value'] == 5 and verify(desc, solve(desc))


def test_even_zero_stays_free_but_mirrored_inputs_are_fixed():
    facts = ['Dom(f)=ℝ', 'parity(f,even)']
    desc = description(candidate('a12', facts=facts, goal=rule_goal('f(-2)', rule='x+1')), bound=False)
    assert solve(desc)['value'] == 3
    desc = description(candidate('a12', facts=facts, goal=rule_goal('f(0)', rule='x+1')), bound=False)
    model = solve(desc)
    assert model['status'] == 'insufficient_information' and verify(desc, model)


@pytest.mark.parametrize('facts,goal,reason', [
    (['Dom(f)=ℝ', 'parity(f,odd)', 'f(1)=2', 'f(-1)=3'], {'kind': 'find_value', 'expression': 'f(1)'},
     'symmetry_value.conditions_inconsistent'),
    (['Dom(f)=(-2,2)', 'parity(f,odd)'], rule_goal('f(3)'), 'symmetry_value.input_outside_domain'),
    (['Dom(f)=ℝ', 'parity(f,odd)'], rule_goal('f(1)', rule='x+1', known='[0,∞)'), 'symmetry_value.overlap_conflict'),
    (['Dom(f)=ℝ', 'parity(f,odd)', 'f(1)*f(2)=3'], {'kind': 'find_value', 'expression': 'f(1)'},
     'symmetry_value.nonlinear_value_relation'),
])
def test_contradictions_and_unsupported_forms_are_gaps(facts, goal, reason):
    assert description(candidate('a12', facts=facts, goal=goal), bound=False)['reason'] == reason


def test_parameter_inputs_are_left_to_their_own_route():
    value = candidate('a12', facts=['parity(f,odd)'], goal={'kind': 'find_value', 'expression': 'f(m)'})
    assert description(value, bound=False) is None


@pytest.mark.parametrize('field,change', [
    ('value', lambda m: m['value'] + 1),
    ('multipliers', lambda m: [k + 1 for k in m['multipliers']] if m['multipliers'] else [1]),
    ('calls', lambda m: [{**c, 'factor': -c['factor'], 'value': None if c['value'] is None else -c['value'] + 1}
                         for c in m['calls']]),
    ('status', lambda m: 'insufficient_information'),
    ('target_constant', lambda m: m['target_constant'] + 1),
    ('witnesses', lambda m: [[w + 1 for w in m['witnesses'][0]]] if m['keys'] else []),
])
@pytest.mark.parametrize('name', ['a09', 'a12', 'a13'])
def test_tampered_certificate_fails(name, field, change):
    desc = description(candidate(name))
    model = solve(desc)
    assert not verify(desc, {**model, field: change(model)})


@pytest.mark.parametrize('text', [
    r'已知函数 $f(x)$ 是定义在 $\mathbf R$ 上的偶函数，当 $x>0$ 时，$f(x)=x^3+2x+1$，则 $f(0)+f(-1)=$____．',
    r'已知函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x\ge 0$ 时，$f(x)=x^3+2x+1$，则 $f(0)+f(-1)=$____．',
    r'已知函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^3+2x+1$，则 $f(0)-f(-1)=$____．',
    r'已知函数 $f(x)$ 是定义在 $\mathbf R$ 上的奇函数，当 $x>0$ 时，$f(x)=x^3+2x-1$，则 $f(0)+f(-1)=$____．',
])
def test_changed_source_is_not_bound(text):
    assert description(candidate('a12', text=text))['reason'] == 'symmetry_value.source_not_bound'


@pytest.mark.parametrize('name,expected,multipliers', [('a03', -2, None), ('a06', 5, [0, -1])])
def test_two_functions_use_the_identity_at_the_input_and_its_opposite(name, expected, multipliers):
    desc = description(candidate(name))
    assert desc['structure_supported'], desc['reason']
    assert [F['name'] for F in desc['functions']] == ['f', 'g']
    model = solve(desc)
    assert [e['instance'] for e in model['equations']] == [2, -2]
    assert model['keys'] == [['f', 2], ['g', 2]]
    assert model['value'] == expected and verify(desc, model)
    if multipliers:
        assert model['multipliers'] == multipliers


def test_a03_other_value_and_quantified_identity():
    desc = description(candidate('a03', goal=pair_goal('f(x)+g(x)=x^2-x+1', 'g(2)')), bound=False)
    assert solve(desc)['value'] == 5
    facts = ['Dom(f)=ℝ', 'Dom(g)=ℝ', 'parity(f,odd)', 'parity(g,even)', '∀x∈ℝ:f(x)-g(x)=x^3+x^2-1']
    desc = description(candidate('a06', facts=facts, goal={'kind': 'find_value', 'expression': 'f(2)+g(2)'}),
                       bound=False)
    assert desc['structure_supported'], desc['reason']
    assert solve(desc)['value'] == 5 and verify(desc, solve(desc))


def test_same_parity_fixes_only_the_combination():
    facts = ['Dom(f)=ℝ', 'Dom(g)=ℝ', 'parity(f,odd)', 'parity(g,odd)']
    desc = description(candidate('a06', facts=facts, goal=pair_goal('f(x)+g(x)=x^3', 'f(2)+g(2)')), bound=False)
    assert solve(desc)['value'] == 8
    desc = description(candidate('a06', facts=facts, goal=pair_goal('f(x)+g(x)=x^3', 'f(2)')), bound=False)
    model = solve(desc)
    assert model['status'] == 'insufficient_information' and verify(desc, model)
    desc = description(candidate('a06', facts=facts, goal=pair_goal('f(x)+g(x)=x^2', 'f(2)+g(2)')), bound=False)
    assert desc['reason'] == 'symmetry_value.conditions_inconsistent'


@pytest.mark.parametrize('relation,expression,expected', [
    ('f(x)-f(-x)=2*x', 'f(2)', 2),
    ('f(x)=x^3+1', 'f(2)', 'symmetry_value.conditions_inconsistent'),
    ('f(x)+g(x)=x^2', 'f(2)', 'symmetry_value.other_function'),
])
def test_single_function_identities(relation, expression, expected):
    desc = description(candidate('a13', facts=['Dom(f)=ℝ', 'parity(f,odd)'], goal=pair_goal(relation, expression)),
                       bound=False)
    if isinstance(expected, str):
        assert desc['reason'] == expected
    else:
        assert solve(desc)['value'] == expected and verify(desc, solve(desc))


@pytest.mark.parametrize('change', [
    lambda m: {**m, 'equations': m['equations'][:1]},
    lambda m: {**m, 'equations': [{**e, 'instance': -e['instance']} for e in m['equations']]},
    lambda m: {**m, 'equations': [{**e, 'constant': e['constant'] + 1} for e in m['equations']]},
    lambda m: {**m, 'signs': {'f': 1, 'g': 1}},
    lambda m: {**m, 'keys': [['g', 2], ['f', 2]]},
])
def test_tampered_identity_instances_fail(change):
    desc = description(candidate('a06'))
    assert not verify(desc, change(solve(desc)))


def _a15():
    from copy import deepcopy

    from shuxueshuo_server.graph_lesson.stage_three.symmetry_runtime import _borrow_bound, prepare
    value = candidate('a15')
    context = build_context(value, TARGET)
    desc = context['symmetry_value_goal']
    borrowed = deepcopy(prepare(context)['outputs']['description'])
    return context, desc, solve(borrowed), _borrow_bound


def test_a15_borrows_the_domain_parameter_then_evaluates():
    context, desc, model, bound = _a15()
    assert desc['structure_supported'], desc['reason']
    assert desc['parameter'] == {'ref': 'r:scalar:m', 'name': 'm', 'source_refs': ['/root/facts/0', '/root/facts/1']}
    with pytest.raises(ValueError, match='parameter_requires_borrow'):
        solve(desc)
    output = model['borrow']['output']
    assert output['parameter_set'] == sp.FiniteSet(-4) and output['instantiated_domain'] == sp.Interval(-9, 9)
    assert output['parent_target_pending'] is True and output['remaining_source_refs'] == []
    assert model['value'] == -8 and model['rule_domain'] == sp.Interval(0, 9)
    assert [c['route'] for c in model['calls']] == ['mirrored_rule']
    assert verify(desc, model) and bound(context, model)


@pytest.mark.parametrize('field,wrong', [
    ('parameter_set', sp.FiniteSet(4)), ('instantiated_domain', sp.Interval(-1, 1)),
    ('processed_source_refs', ['/root/facts/0']), ('remaining_source_refs', ['/root/facts/1']),
    ('parent_target_pending', False), ('parent_goal', {'kind': 'find_value', 'expression': 'f(1)'}),
    ('parent_target_ref', '/root/goals/1'),
])
def test_a15_tampered_borrow_fails(field, wrong):
    from copy import deepcopy
    context, desc, model, bound = _a15()
    changed = deepcopy(model)
    changed['borrow']['output'][field] = wrong
    assert not (verify(desc, changed) and bound(context, changed))


def test_a15_tampered_parent_result_fails():
    from copy import deepcopy
    context, desc, model, bound = _a15()
    for change in (lambda m: m.update(value=sp.Integer(8)), lambda m: m.update(borrow=None),
                   lambda m: m['borrow']['candidates'][0].update(parameter_value=sp.Integer(4))):
        changed = deepcopy(model)
        change(changed)
        assert not verify(desc, changed)
    changed_context = deepcopy(context)
    changed_context['entries'][0]['ast'][2][1] = False
    assert not bound(changed_context, model)


H03 = (r'设 $f(x)$ 为奇函数，$g(x)$ 为偶函数，它们的定义域都是 $\mathbf R$，且 $2f(x)+g(x)=x^2+4x$，'
       r'则 $g(1)=$____．')
H04 = (r'已知 $f(x)$ 是偶函数，$g(x)$ 是奇函数，且对任意实数 $x$ 都有 $f(x)-3g(x)=x^3-2x^2+5$，'
       r'则 $f(-2)+g(2)=$____．')


def h04(relation='∀x∈ℝ:f(x)-3*g(x)=x^3-2*x^2+5', text=H04):
    return candidate('a03', text=text, facts=['parity(f,even)', 'parity(g,odd)', relation],
                     goal={'kind': 'find_value', 'expression': 'f(-2)+g(2)'})


def test_holdout_phrasings_are_bound():
    value = candidate('a03', text=H03, facts=['Dom(f)=ℝ', 'Dom(g)=ℝ', 'parity(f,odd)', 'parity(g,even)'],
                      goal=pair_goal('2*f(x)+g(x)=x^2+4*x', 'g(1)'))
    desc = description(value)
    assert desc['structure_supported'], desc['reason']
    assert solve(desc)['value'] == 1
    desc = description(h04())
    assert desc['structure_supported'], desc['reason']
    assert solve(desc)['value'] == sp.Rational(-17, 3)


@pytest.mark.parametrize('value', [
    h04(relation='∀x∈(-3,3):f(x)-3*g(x)=x^3-2*x^2+5'),
    h04(text=H04.replace('任意实数', '任意正数')),
    h04(text=H04.replace('定义域', '').replace('$f(x)-3g(x)', '$f(x)+3g(x)')),
])
def test_quantified_identity_must_match_the_source(value):
    assert description(value)['reason'] == 'symmetry_value.source_not_bound'
